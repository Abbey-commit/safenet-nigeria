"""
SafeNet Nigeria — Phase 1
ACLED Data Ingestor (OAuth Version)
=====================================
Updated to use ACLED's current OAuth authentication method.
Replaces the old API key approach with email + password → Bearer token.

How it works:
    Step 1: POST your email + password to ACLED's token endpoint
    Step 2: Receive an access_token (valid 24hrs) + refresh_token (valid 14 days)
    Step 3: Use Bearer token in all subsequent API requests
    Step 4: Auto-refresh when token expires — no manual re-login needed

Codespaces secrets needed (Settings → Secrets → Codespaces):
    ACLED_EMAIL     →  info@safe-nigeria.com.ng
    ACLED_PASSWORD  →  your ACLED account password

Psychology note:
  ACLED categories use clinical language ("fatalities", "violence").
  We map these to human-centred labels so analysts reviewing alerts
  feel the human weight of each event — reducing the psychological
  distance that causes review fatigue and rubber-stamping.
"""

import requests
import pandas as pd
import math
import random
import datetime
import os
from typing import Optional


# ── ACLED OAuth endpoints ──────────────────────────────────────────────────────
ACLED_TOKEN_URL = "https://acleddata.com/oauth/token"
ACLED_API_URL   = "https://acleddata.com/api/acled/read"


# ── Nigerian geopolitical zones ───────────────────────────────────────────────
NIGERIA_ZONES = {
    "Northwest": {
        "states": ["Zamfara", "Kaduna", "Katsina", "Sokoto", "Kebbi", "Niger", "Jigawa"],
        "lat_range": (11.0, 13.5), "lon_range": (4.5, 9.0),
        "threat_weight": 0.35,
        "event_types": {
            "Violence against civilians": 0.30, "Battles": 0.35,
            "Explosions/Remote violence": 0.10, "Riots": 0.10,
            "Strategic developments": 0.15,
        }
    },
    "Northeast": {
        "states": ["Borno", "Yobe", "Adamawa", "Gombe", "Bauchi", "Taraba"],
        "lat_range": (9.0, 13.9), "lon_range": (11.0, 15.0),
        "threat_weight": 0.30,
        "event_types": {
            "Battles": 0.40, "Explosions/Remote violence": 0.25,
            "Violence against civilians": 0.20, "Strategic developments": 0.10,
            "Riots": 0.05,
        }
    },
    "NorthCentral": {
        "states": ["Plateau", "Benue", "Kogi", "Kwara", "Nasarawa", "FCT"],
        "lat_range": (7.5, 10.5), "lon_range": (7.0, 11.0),
        "threat_weight": 0.20,
        "event_types": {
            "Violence against civilians": 0.35, "Battles": 0.25,
            "Riots": 0.20, "Explosions/Remote violence": 0.10,
            "Strategic developments": 0.10,
        }
    },
    "SouthSouth": {
        "states": ["Delta", "Rivers", "Bayelsa", "Edo", "Cross River", "Akwa Ibom"],
        "lat_range": (4.5, 6.5), "lon_range": (5.5, 9.5),
        "threat_weight": 0.08,
        "event_types": {
            "Riots": 0.30, "Violence against civilians": 0.25,
            "Strategic developments": 0.20, "Battles": 0.15,
            "Explosions/Remote violence": 0.10,
        }
    },
    "SouthEast": {
        "states": ["Anambra", "Imo", "Enugu", "Ebonyi", "Abia"],
        "lat_range": (5.0, 7.5), "lon_range": (6.5, 9.0),
        "threat_weight": 0.04,
        "event_types": {
            "Riots": 0.35, "Violence against civilians": 0.30,
            "Strategic developments": 0.20, "Battles": 0.15,
        }
    },
    "SouthWest": {
        "states": ["Lagos", "Ogun", "Oyo", "Osun", "Ekiti", "Ondo"],
        "lat_range": (6.0, 8.5), "lon_range": (2.5, 6.0),
        "threat_weight": 0.03,
        "event_types": {
            "Riots": 0.40, "Violence against civilians": 0.25,
            "Strategic developments": 0.20, "Battles": 0.15,
        }
    },
}

ACTORS = {
    "Northwest":    ["Bandits", "Yan Bindiga", "Yan Daba", "Unknown Armed Group",
                     "Military Forces of Nigeria", "Nigerian Police Force"],
    "Northeast":    ["Boko Haram", "ISWAP", "Military Forces of Nigeria",
                     "CJTF (Civilian Joint Task Force)", "Unknown Armed Group"],
    "NorthCentral": ["Fulani Ethnic Militia", "Farmers/Herders",
                     "Military Forces of Nigeria", "Nigerian Police Force",
                     "Unknown Armed Group"],
    "SouthSouth":   ["Unknown Armed Group", "Nigerian Police Force",
                     "NDELTA Avengers", "Pirates/Sea Robbers", "Cult Groups"],
    "SouthEast":    ["IPOB/ESN", "Nigerian Police Force",
                     "Unknown Armed Group", "Cult Groups"],
    "SouthWest":    ["Unknown Armed Group", "Nigerian Police Force",
                     "Cult Groups", "Protesters"],
}

SEVERITY_MAP = {
    "Battles":                    {"level": "CRITICAL", "human_label": "Armed confrontation"},
    "Explosions/Remote violence": {"level": "CRITICAL", "human_label": "Bombing or IED"},
    "Violence against civilians": {"level": "HIGH",     "human_label": "Civilian attack"},
    "Riots":                      {"level": "MEDIUM",   "human_label": "Civil unrest"},
    "Strategic developments":     {"level": "LOW",      "human_label": "Intelligence signal"},
}


class ACLEDAuth:
    """
    Handles OAuth token lifecycle.
    Fetches fresh token → auto-refreshes before expiry → never stores to disk.
    """

    def __init__(self, email: str, password: str):
        self.email         = email
        self.password      = password
        self.access_token  = None
        self.refresh_token = None
        self.token_expiry  = None

    def get_token(self) -> str:
        now = datetime.datetime.utcnow()
        if self.access_token and self.token_expiry:
            minutes_left = (self.token_expiry - now).total_seconds() / 60
            if minutes_left > 10:
                return self.access_token
        if self.refresh_token:
            print("[ACLEDAuth] Refreshing access token...")
            return self._refresh()
        print("[ACLEDAuth] Fetching new access token...")
        return self._login()

    def _login(self) -> str:
        response = requests.post(
            ACLED_TOKEN_URL,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "username":   self.email,
                "password":   self.password,
                "grant_type": "password",
                "client_id":  "acled",
                "scope":      "authenticated",
            },
            timeout=30,
        )
        if response.status_code != 200:
            raise Exception(
                f"\n[ACLEDAuth] Login failed ({response.status_code})\n"
                f"Check ACLED_EMAIL and ACLED_PASSWORD in your Codespaces secrets.\n"
                f"Details: {response.text}"
            )
        return self._store(response.json())

    def _refresh(self) -> str:
        response = requests.post(
            ACLED_TOKEN_URL,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            data={
                "refresh_token": self.refresh_token,
                "grant_type":    "refresh_token",
                "client_id":     "acled",
            },
            timeout=30,
        )
        if response.status_code != 200:
            print("[ACLEDAuth] Refresh expired — re-logging in...")
            self.refresh_token = None
            return self._login()
        return self._store(response.json())

    def _store(self, data: dict) -> str:
        self.access_token  = data["access_token"]
        self.refresh_token = data.get("refresh_token")
        expires_in         = data.get("expires_in", 86400)
        self.token_expiry  = datetime.datetime.utcnow() + datetime.timedelta(
            seconds=expires_in
        )
        print(f"[ACLEDAuth] Token valid for {expires_in // 3600} hours")
        return self.access_token

    def header(self) -> dict:
        return {
            "Authorization": f"Bearer {self.get_token()}",
            "Content-Type":  "application/json",
        }


class ACLEDIngestor:
    """
    Fetches Nigerian conflict events from ACLED.
    Live mode: OAuth with your ACLED email + password.
    Dev mode:  synthetic data matching exact ACLED schema.
    """

    def __init__(self, email: Optional[str] = None, password: Optional[str] = None):
        self.email    = email    or os.getenv("ACLED_EMAIL",    "")
        self.password = password or os.getenv("ACLED_PASSWORD", "")
        self.use_live = bool(self.email and self.password)
        self.auth     = ACLEDAuth(self.email, self.password) if self.use_live else None

        mode = "LIVE (ACLED OAuth)" if self.use_live else "SYNTHETIC (dev mode)"
        print(f"[ACLEDIngestor] Mode: {mode}")
        if not self.use_live:
            print("[ACLEDIngestor] Add ACLED_EMAIL + ACLED_PASSWORD to Codespaces")
            print("[ACLEDIngestor] secrets to switch to live Nigerian conflict data.")

    def fetch(self, country: str = "Nigeria", days_back: int = 90) -> pd.DataFrame:
        if self.use_live:
            return self._fetch_live(country, days_back)
        return self._fetch_synthetic(days_back)

    def _fetch_live(self, country: str, days_back: int) -> pd.DataFrame:
        since = (datetime.date.today() - datetime.timedelta(days=days_back)).strftime("%Y-%m-%d")
        today = datetime.date.today().strftime("%Y-%m-%d")
        all_events = []
        page = 1

        print(f"[ACLEDIngestor] Pulling {country} events {since} → {today}...")

        while True:
            params = {
                "country":          country,
                "event_date":       f"{since}|{today}",
                "event_date_where": "BETWEEN",
                "limit":            5000,
                "page":             page,
                "_format":          "json",
            }
            resp = requests.get(
                ACLED_API_URL, params=params,
                headers=self.auth.header(), timeout=60
            )
            resp.raise_for_status()
            data   = resp.json()
            events = data.get("data", [])
            if not events:
                break
            all_events.extend(events)
            print(f"[ACLEDIngestor] Page {page}: {len(events)} events "
                  f"({len(all_events)} total)")
            if len(events) < 5000:
                break
            page += 1

        print(f"[ACLEDIngestor] Done — {len(all_events)} events fetched")
        return self._normalise(pd.DataFrame(all_events))

    def _fetch_synthetic(self, days_back: int) -> pd.DataFrame:
        random.seed(42)
        today = datetime.date.today()
        events = []
        event_id = 10000

        for zone, profile in NIGERIA_ZONES.items():
            n = int(days_back * profile["threat_weight"] * 4.5)
            for _ in range(n):
                event_id += 1
                days_ago   = random.randint(0, days_back)
                event_date = today - datetime.timedelta(days=days_ago)
                lat  = random.uniform(*profile["lat_range"])
                lon  = random.uniform(*profile["lon_range"])
                etype = random.choices(
                    list(profile["event_types"].keys()),
                    weights=list(profile["event_types"].values())
                )[0]
                state  = random.choice(profile["states"])
                actors = ACTORS[zone]
                actor1 = random.choice(actors)
                actor2 = random.choice([a for a in actors if a != actor1] + ["Civilians"])
                fatalities = 0
                if random.random() < 0.35:
                    fatalities = min(int(random.paretovariate(1.5)), 80)

                events.append({
                    "event_id_cnty": f"NGA{event_id}",
                    "event_date":    event_date.strftime("%Y-%m-%d"),
                    "year":          event_date.year,
                    "event_type":    etype,
                    "actor1":        actor1,
                    "actor2":        actor2,
                    "country":       "Nigeria",
                    "admin1":        state,
                    "admin2":        self._random_lga(state),
                    "location":      f"{self._random_lga(state)} area",
                    "latitude":      round(lat, 6),
                    "longitude":     round(lon, 6),
                    "fatalities":    fatalities,
                    "notes":         self._generate_notes(etype, actor1, state),
                    "source":        "SafeNet Synthetic",
                    "zone":          zone,
                })

        df = pd.DataFrame(events).sort_values(
            "event_date", ascending=False
        ).reset_index(drop=True)
        print(f"[ACLEDIngestor] Generated {len(df)} synthetic events")
        return self._normalise(df)

    def _normalise(self, df: pd.DataFrame) -> pd.DataFrame:
        df["latitude"]   = pd.to_numeric(df["latitude"],   errors="coerce")
        df["longitude"]  = pd.to_numeric(df["longitude"],  errors="coerce")
        df["fatalities"] = pd.to_numeric(df["fatalities"], errors="coerce").fillna(0).astype(int)
        df["event_date"] = pd.to_datetime(df["event_date"])
        df["severity_level"] = df["event_type"].map(
            lambda x: SEVERITY_MAP.get(x, {}).get("level", "LOW"))
        df["human_label"] = df["event_type"].map(
            lambda x: SEVERITY_MAP.get(x, {}).get("human_label", x))
        today = pd.Timestamp(datetime.date.today())
        df["days_ago"] = (today - df["event_date"]).dt.days
        df["threat_score"] = df.apply(
            lambda r: self._threat_score(
                r["severity_level"], r["fatalities"], r["days_ago"]), axis=1)
        df["fatality_band"] = pd.cut(
            df["fatalities"],
            bins=[-1, 0, 2, 9, 24, 999],
            labels=["None", "1–2", "3–9", "10–24", "25+"])
        if "zone" not in df.columns:
            df["zone"] = df["admin1"].map(self._state_to_zone)
        return df.dropna(subset=["latitude", "longitude"]).reset_index(drop=True)

    @staticmethod
    def _threat_score(severity: str, fatalities: int, days_ago: int) -> float:
        base   = {"CRITICAL": 70, "HIGH": 50, "MEDIUM": 30, "LOW": 10}.get(severity, 10)
        bonus  = math.log1p(fatalities) * 8
        decay  = math.exp(-days_ago / 30)
        return round(min(100, (base + bonus) * decay), 2)

    @staticmethod
    def _random_lga(state: str) -> str:
        lgas = {
            "Zamfara": ["Anka", "Birnin Magaji", "Gusau", "Kaura Namoda", "Maru"],
            "Kaduna":  ["Birnin Gwari", "Chikun", "Giwa", "Igabi", "Kaduna North"],
            "Borno":   ["Gwoza", "Konduga", "Maiduguri", "Bama", "Chibok"],
            "Plateau": ["Barkin Ladi", "Bokkos", "Jos North", "Mangu", "Riyom"],
            "Benue":   ["Guma", "Logo", "Makurdi", "Kwande", "Agatu"],
        }
        return random.choice(lgas.get(state, ["North LGA", "Central LGA", "South LGA"]))

    @staticmethod
    def _state_to_zone(state: str) -> str:
        for zone, p in NIGERIA_ZONES.items():
            if state in p["states"]:
                return zone
        return "Unknown"

    @staticmethod
    def _generate_notes(event_type: str, actor: str, state: str) -> str:
        t = {
            "Battles": [
                f"Armed clash between {actor} and security forces in {state}.",
                f"Gun battle involving {actor} near farmland in {state}.",
            ],
            "Violence against civilians": [
                f"Attack on community by {actor} in {state}.",
                f"Village raided; residents displaced. {actor} suspected in {state}.",
            ],
            "Explosions/Remote violence": [
                f"IED detonated on rural road in {state}. {actor} implicated.",
                f"Bombing in {state} attributed to {actor}.",
            ],
            "Riots": [
                f"Civil unrest in {state}. Crowds clashed with security.",
                f"Protest turned violent in {state}.",
            ],
            "Strategic developments": [
                f"Security forces neutralised {actor} cell in {state}.",
                f"Community warning: {actor} movement reported in {state}.",
            ],
        }
        return random.choice(t.get(event_type, [f"Incident reported in {state}."]))


if __name__ == "__main__":
    ingestor = ACLEDIngestor()
    df = ingestor.fetch(days_back=90)
    print(f"\nShape          : {df.shape}")
    print(f"Severity counts:\n{df['severity_level'].value_counts()}")
    print(f"\nTop 3 events by threat score:")
    print(df[["event_date","admin1","human_label","actor1",
              "fatalities","threat_score"]].head(3).to_string(index=False))