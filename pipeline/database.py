"""
SafeNet Nigeria — Phase 1, Day 2
Database Layer + ETL Pipeline
==============================
Stores conflict events in SQLite (dev) → PostgreSQL (production).
Schema designed for both analytical queries and real-time
intelligence lookups.

Psychology note on schema design:
  Fields are named for the human analyst, not the machine.
  'human_label' not 'event_type_code'.
  'days_ago' not 'delta_t'.
  'fatality_band' not 'fatalities_bucket_id'.
  This reduces cognitive load during high-stress alert review.
  Research (Klein, 1998 — Naturalistic Decision Making) shows
  that under stress, analysts pattern-match on familiar language.
  Clinical or technical field names increase error rates.
"""

import sqlite3
import pandas as pd
import json
import datetime
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from pipeline.acled_ingestor import ACLEDIngestor


DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "safenet.db")

# ── Schema DDL ─────────────────────────────────────────────────────────────────
SCHEMA_SQL = """
-- Core conflict events table
CREATE TABLE IF NOT EXISTS conflict_events (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    event_id_cnty       TEXT UNIQUE NOT NULL,
    event_date          TEXT NOT NULL,
    year                INTEGER,

    -- What happened (human-readable labels for analyst UX)
    event_type          TEXT,           -- ACLED category
    human_label         TEXT,           -- "Armed confrontation" not "Battles"
    severity_level      TEXT,           -- CRITICAL / HIGH / MEDIUM / LOW

    -- Who
    actor1              TEXT,
    actor2              TEXT,

    -- Where
    country             TEXT DEFAULT 'Nigeria',
    zone                TEXT,           -- Northwest, Northeast, etc.
    admin1              TEXT,           -- State
    admin2              TEXT,           -- LGA
    location            TEXT,
    latitude            REAL,
    longitude           REAL,

    -- Impact
    fatalities          INTEGER DEFAULT 0,
    fatality_band       TEXT,           -- "None", "1-2", "3-9", "10-24", "25+"

    -- Intelligence scores
    threat_score        REAL,           -- 0-100 composite
    days_ago            INTEGER,

    -- Source
    notes               TEXT,
    source              TEXT,

    -- Pipeline metadata
    ingested_at         TEXT DEFAULT (datetime('now')),
    updated_at          TEXT DEFAULT (datetime('now'))
);

-- Zone-level aggregation cache (refreshed by ETL)
CREATE TABLE IF NOT EXISTS zone_threat_summary (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    zone                TEXT NOT NULL,
    snapshot_date       TEXT NOT NULL,
    total_events        INTEGER DEFAULT 0,
    critical_events     INTEGER DEFAULT 0,
    high_events         INTEGER DEFAULT 0,
    total_fatalities    INTEGER DEFAULT 0,
    avg_threat_score    REAL,
    top_actor           TEXT,
    top_event_type      TEXT,
    trend_7d            TEXT,           -- "RISING", "STABLE", "DECLINING"
    risk_pct            REAL,           -- 0-100 for heatmap bars
    UNIQUE(zone, snapshot_date)
);

-- State-level summary
CREATE TABLE IF NOT EXISTS state_threat_summary (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    state               TEXT NOT NULL,
    zone                TEXT,
    snapshot_date       TEXT NOT NULL,
    total_events        INTEGER DEFAULT 0,
    total_fatalities    INTEGER DEFAULT 0,
    avg_threat_score    REAL,
    dominant_event_type TEXT,
    UNIQUE(state, snapshot_date)
);

-- ETL run log (audit trail — every pipeline run recorded)
CREATE TABLE IF NOT EXISTS etl_run_log (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    run_at              TEXT DEFAULT (datetime('now')),
    run_type            TEXT,           -- "full_refresh" / "incremental"
    records_fetched     INTEGER,
    records_inserted    INTEGER,
    records_updated     INTEGER,
    duration_seconds    REAL,
    status              TEXT,           -- "SUCCESS" / "FAILED"
    error_message       TEXT,
    data_source         TEXT
);

-- Indexes for common query patterns
CREATE INDEX IF NOT EXISTS idx_events_date     ON conflict_events(event_date);
CREATE INDEX IF NOT EXISTS idx_events_zone     ON conflict_events(zone);
CREATE INDEX IF NOT EXISTS idx_events_state    ON conflict_events(admin1);
CREATE INDEX IF NOT EXISTS idx_events_severity ON conflict_events(severity_level);
CREATE INDEX IF NOT EXISTS idx_events_score    ON conflict_events(threat_score);
CREATE INDEX IF NOT EXISTS idx_events_coords   ON conflict_events(latitude, longitude);
"""


class SafeNetDB:
    """
    Database interface for SafeNet conflict intelligence store.
    Wraps SQLite in dev; swap connection string for PostgreSQL in prod.
    """

    def __init__(self, db_path: str = DB_PATH):
        self.db_path = db_path
        os.makedirs(os.path.dirname(db_path), exist_ok=True)
        self._init_schema()
        print(f"[SafeNetDB] Connected to: {db_path}")

    def _connect(self):
        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")   # better concurrent read performance
        conn.execute("PRAGMA foreign_keys=ON")
        return conn

    def _init_schema(self):
        with self._connect() as conn:
            conn.executescript(SCHEMA_SQL)
        print("[SafeNetDB] Schema initialised")

    def upsert_events(self, df: pd.DataFrame) -> dict:
        """
        Insert new events; update existing ones by event_id_cnty.
        Returns counts for ETL log.
        """
        inserted = 0
        updated = 0
        cols = [
            "event_id_cnty", "event_date", "year", "event_type", "human_label",
            "severity_level", "actor1", "actor2", "zone", "admin1", "admin2",
            "location", "latitude", "longitude", "fatalities", "fatality_band",
            "threat_score", "days_ago", "notes", "source"
        ]

        with self._connect() as conn:
            for _, row in df.iterrows():
                event_date = str(row["event_date"])[:10] if pd.notna(row["event_date"]) else None
                values = (
                    row.get("event_id_cnty"), event_date,
                    int(row.get("year", 0)),
                    row.get("event_type"), row.get("human_label"),
                    row.get("severity_level"),
                    row.get("actor1"), row.get("actor2"),
                    row.get("zone"), row.get("admin1"), row.get("admin2"),
                    row.get("location"),
                    float(row.get("latitude", 0)), float(row.get("longitude", 0)),
                    int(row.get("fatalities", 0)),
                    str(row.get("fatality_band", "None")),
                    float(row.get("threat_score", 0)),
                    int(row.get("days_ago", 0)),
                    row.get("notes"), row.get("source")
                )
                try:
                    conn.execute(f"""
                        INSERT INTO conflict_events
                            (event_id_cnty, event_date, year, event_type, human_label,
                             severity_level, actor1, actor2, zone, admin1, admin2,
                             location, latitude, longitude, fatalities, fatality_band,
                             threat_score, days_ago, notes, source)
                        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                        ON CONFLICT(event_id_cnty) DO UPDATE SET
                            threat_score = excluded.threat_score,
                            days_ago     = excluded.days_ago,
                            updated_at   = datetime('now')
                    """, values)
                    inserted += 1
                except Exception:
                    updated += 1

        return {"inserted": inserted, "updated": updated}

    def refresh_zone_summaries(self):
        """Recompute zone-level aggregates. Called after every ingest."""
        today = datetime.date.today().isoformat()
        with self._connect() as conn:
            zones = [r[0] for r in conn.execute(
                "SELECT DISTINCT zone FROM conflict_events WHERE zone IS NOT NULL"
            ).fetchall()]

            for zone in zones:
                rows = conn.execute("""
                    SELECT severity_level, fatalities, threat_score, actor1, event_type,
                           event_date
                    FROM conflict_events
                    WHERE zone = ? AND days_ago <= 90
                """, (zone,)).fetchall()

                if not rows:
                    continue

                total = len(rows)
                critical = sum(1 for r in rows if r["severity_level"] == "CRITICAL")
                high = sum(1 for r in rows if r["severity_level"] == "HIGH")
                fatalities = sum(r["fatalities"] for r in rows)
                avg_score = sum(r["threat_score"] for r in rows) / total

                from collections import Counter
                top_actor = Counter(r["actor1"] for r in rows).most_common(1)[0][0]
                top_type = Counter(r["event_type"] for r in rows).most_common(1)[0][0]

                # Trend: compare last 7d vs prior 7d event count
                recent = sum(1 for r in rows
                             if (datetime.date.today() - datetime.date.fromisoformat(r["event_date"][:10])).days <= 7)
                prior = sum(1 for r in rows
                            if 7 < (datetime.date.today() - datetime.date.fromisoformat(r["event_date"][:10])).days <= 14)
                if prior == 0:
                    trend = "STABLE"
                elif recent > prior * 1.2:
                    trend = "RISING"
                elif recent < prior * 0.8:
                    trend = "DECLINING"
                else:
                    trend = "STABLE"

                risk_pct = min(100, avg_score)

                conn.execute("""
                    INSERT INTO zone_threat_summary
                        (zone, snapshot_date, total_events, critical_events, high_events,
                         total_fatalities, avg_threat_score, top_actor, top_event_type,
                         trend_7d, risk_pct)
                    VALUES (?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(zone, snapshot_date) DO UPDATE SET
                        total_events      = excluded.total_events,
                        critical_events   = excluded.critical_events,
                        total_fatalities  = excluded.total_fatalities,
                        avg_threat_score  = excluded.avg_threat_score,
                        trend_7d          = excluded.trend_7d,
                        risk_pct          = excluded.risk_pct
                """, (zone, today, total, critical, high, fatalities,
                      round(avg_score, 2), top_actor, top_type, trend, round(risk_pct, 1)))

        print(f"[SafeNetDB] Zone summaries refreshed for {len(zones)} zones")

    def refresh_state_summaries(self):
        today = datetime.date.today().isoformat()
        with self._connect() as conn:
            states = [r[0] for r in conn.execute(
                "SELECT DISTINCT admin1 FROM conflict_events WHERE admin1 IS NOT NULL"
            ).fetchall()]

            for state in states:
                rows = conn.execute("""
                    SELECT fatalities, threat_score, event_type, zone
                    FROM conflict_events
                    WHERE admin1 = ? AND days_ago <= 90
                """, (state,)).fetchall()
                if not rows:
                    continue
                from collections import Counter
                total = len(rows)
                fatalities = sum(r["fatalities"] for r in rows)
                avg_score = sum(r["threat_score"] for r in rows) / total
                dom_type = Counter(r["event_type"] for r in rows).most_common(1)[0][0]
                zone = rows[0]["zone"]

                conn.execute("""
                    INSERT INTO state_threat_summary
                        (state, zone, snapshot_date, total_events, total_fatalities,
                         avg_threat_score, dominant_event_type)
                    VALUES (?,?,?,?,?,?,?)
                    ON CONFLICT(state, snapshot_date) DO UPDATE SET
                        total_events      = excluded.total_events,
                        total_fatalities  = excluded.total_fatalities,
                        avg_threat_score  = excluded.avg_threat_score,
                        dominant_event_type = excluded.dominant_event_type
                """, (state, zone, today, total, fatalities, round(avg_score, 2), dom_type))

        print(f"[SafeNetDB] State summaries refreshed for {len(states)} states")

    def log_etl_run(self, run_type: str, fetched: int, inserted: int,
                    updated: int, duration: float, status: str,
                    error: str = None, source: str = "ACLED"):
        with self._connect() as conn:
            conn.execute("""
                INSERT INTO etl_run_log
                    (run_type, records_fetched, records_inserted, records_updated,
                     duration_seconds, status, error_message, data_source)
                VALUES (?,?,?,?,?,?,?,?)
            """, (run_type, fetched, inserted, updated, duration, status, error, source))

    def query(self, sql: str, params: tuple = ()) -> pd.DataFrame:
        with self._connect() as conn:
            return pd.read_sql_query(sql, conn, params=params)

    def get_summary(self) -> dict:
        with self._connect() as conn:
            total = conn.execute("SELECT COUNT(*) FROM conflict_events").fetchone()[0]
            critical = conn.execute(
                "SELECT COUNT(*) FROM conflict_events WHERE severity_level='CRITICAL'"
            ).fetchone()[0]
            fatalities = conn.execute(
                "SELECT SUM(fatalities) FROM conflict_events"
            ).fetchone()[0] or 0
            zones = conn.execute(
                "SELECT COUNT(DISTINCT zone) FROM conflict_events"
            ).fetchone()[0]
        return {
            "total_events": total,
            "critical_events": critical,
            "total_fatalities": fatalities,
            "zones_covered": zones,
        }


class ETLPipeline:
    """
    Orchestrates the full Extract → Transform → Load cycle.
    In production this runs on Apache Airflow daily at 06:00 WAT.
    """

    def __init__(self, email=None, password=None):
        self.ingestor = ACLEDIngestor(email=email, password=password)
        self.db = SafeNetDB()

    def run(self, days_back: int = 90, run_type: str = "full_refresh") -> dict:
        import time
        start = time.time()
        print(f"\n{'='*55}")
        print(f"SafeNet ETL Pipeline — {run_type.upper()}")
        print(f"{'='*55}")

        try:
            # EXTRACT
            print("\n[1/4] Extracting conflict data...")
            try:
                df = self.ingestor.fetch(days_back=days_back)
            except Exception as e:
                print(f"      → Live fetch failed: {e}")
                print(f"      → Falling back to synthetic data")
                self.ingestor.use_live = False
                df = self.ingestor._fetch_synthetic(days_back)

            # TRANSFORM (already done in ingestor._normalise)
            print("\n[2/4] Transform complete (normalised in ingestor)")
            print(f"      → {df['severity_level'].value_counts().to_dict()}")

            # LOAD
            print("\n[3/4] Loading into intelligence store...")
            counts = self.db.upsert_events(df)
            print(f"      → Inserted: {counts['inserted']}, Updated: {counts['updated']}")

            # AGGREGATE
            print("\n[4/4] Refreshing intelligence summaries...")
            self.db.refresh_zone_summaries()
            self.db.refresh_state_summaries()

            duration = round(time.time() - start, 2)
            self.db.log_etl_run(run_type, len(df), counts["inserted"],
                                counts["updated"], duration, "SUCCESS")

            summary = self.db.get_summary()
            print(f"\n{'='*55}")
            print(f"Pipeline complete in {duration}s")
            print(f"Database summary: {summary}")
            print(f"{'='*55}\n")
            return {"status": "SUCCESS", "duration": duration, **summary}

        except Exception as e:
            duration = round(time.time() - start, 2)
            self.db.log_etl_run(run_type, 0, 0, 0, duration, "FAILED", str(e))
            print(f"[ETL ERROR] {e}")
            raise


if __name__ == "__main__":
    pipeline = ETLPipeline()
    result = pipeline.run(days_back=90)
    print(f"\nFinal result: {result}")

    # Quick data check
    db = SafeNetDB()
    print("\nTop 5 highest threat events:")
    print(db.query("""
        SELECT event_date, admin1, human_label, actor1, fatalities, threat_score
        FROM conflict_events
        ORDER BY threat_score DESC
        LIMIT 5
    """).to_string(index=False))

    print("\nZone risk summary:")
    print(db.query("""
        SELECT zone, total_events, critical_events, total_fatalities,
               round(avg_threat_score,1) as avg_score, trend_7d, risk_pct
        FROM zone_threat_summary
        ORDER BY risk_pct DESC
    """).to_string(index=False))
