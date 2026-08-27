"""
SafeNet Nigeria — Phase 1, Day 3
Intelligence Dashboard Generator
==================================
Reads from the SQLite intelligence store and generates a
self-contained HTML dashboard — zero extra dependencies.

Psychology principles applied to dashboard design:
  1. Progressive disclosure: summary first, detail on demand
     (Shneiderman's mantra: overview, zoom, filter, details-on-demand)
  2. Severity colours follow universal warning conventions
     (red=stop, amber=caution, green=safe) — not brand colours
  3. Human labels everywhere — never ACLED codes in analyst-facing UI
  4. Fatality numbers shown with context, not raw counts
     (Slovic 2007: "psychic numbing" — large numbers feel abstract)
  5. Trend arrows give temporal context — analyst sees direction not
     just current state (Klein: situational awareness requires change)
  6. Audit trail visible — analyst can always trace why an alert fired
"""

import sqlite3
import json
import os
import sys
import datetime
import math

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "safenet.db")
OUTPUT_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "dashboard", "index.html")


def load_data():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row

    # Zone summaries
    zones = [dict(r) for r in conn.execute("""
        SELECT * FROM zone_threat_summary
        ORDER BY risk_pct DESC
    """).fetchall()]

    # Top threat events (recent, high score)
    top_events = [dict(r) for r in conn.execute("""
        SELECT event_date, admin1, zone, human_label, actor1,
               fatalities, threat_score, severity_level, notes, days_ago
        FROM conflict_events
        ORDER BY threat_score DESC, days_ago ASC
        LIMIT 8
    """).fetchall()]

    # State summaries for heatmap
    states = [dict(r) for r in conn.execute("""
        SELECT state, zone, total_events, total_fatalities,
               avg_threat_score, dominant_event_type
        FROM state_threat_summary
        ORDER BY avg_threat_score DESC
    """).fetchall()]

    # Time series: events per day last 30 days
    timeseries = [dict(r) for r in conn.execute("""
        SELECT event_date, COUNT(*) as count,
               SUM(fatalities) as fatalities,
               SUM(CASE WHEN severity_level='CRITICAL' THEN 1 ELSE 0 END) as critical
        FROM conflict_events
        WHERE days_ago <= 30
        GROUP BY event_date
        ORDER BY event_date
    """).fetchall()]

    # Event type breakdown
    event_types = [dict(r) for r in conn.execute("""
        SELECT human_label, COUNT(*) as count,
               SUM(fatalities) as fatalities
        FROM conflict_events
        GROUP BY human_label
        ORDER BY count DESC
    """).fetchall()]

    # Top actors
    actors = [dict(r) for r in conn.execute("""
        SELECT actor1 as actor, COUNT(*) as incidents,
               SUM(fatalities) as fatalities
        FROM conflict_events
        WHERE actor1 NOT IN ('Military Forces of Nigeria','Nigerian Police Force')
        GROUP BY actor1
        ORDER BY incidents DESC
        LIMIT 6
    """).fetchall()]

    # Combined stats from all three sources
    acled = dict(conn.execute("""
        SELECT COUNT(*) as total_events,
               SUM(CASE WHEN severity_level='CRITICAL' THEN 1 ELSE 0 END) as critical,
               SUM(fatalities) as total_fatalities,
               COUNT(DISTINCT admin1) as states_affected
        FROM conflict_events
    """).fetchone())

    unodc_count = conn.execute(
        "SELECT COUNT(*) FROM unodc_crime_stats"
    ).fetchone()[0] if conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='unodc_crime_stats'"
    ).fetchone() else 0

    npf_count = conn.execute(
        "SELECT COUNT(*) FROM npf_crime_records"
    ).fetchone()[0] if conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='npf_crime_records'"
    ).fetchone() else 0

    npf_reported = conn.execute(
        "SELECT SUM(reported_cases) FROM npf_crime_records"
    ).fetchone()[0] or 0 if npf_count > 0 else 0

    stats = {
        "total_events":     acled["total_events"],
        "critical":         acled["critical"],
        "total_fatalities": acled["total_fatalities"] or 0,
        "states_affected":  acled["states_affected"],
        "unodc_records":    unodc_count,
        "npf_records":      npf_count,
        "npf_reported":     int(npf_reported or 0),
        "total_records":    (acled["total_events"] or 0) + unodc_count + npf_count,
    }

    # ETL log
    etl_log = [dict(r) for r in conn.execute("""
        SELECT run_at, run_type, records_fetched, records_inserted,
               duration_seconds, status, data_source
        FROM etl_run_log
        ORDER BY run_at DESC LIMIT 3
    """).fetchall()]

    # Determine data mode from latest run
    latest = etl_log[0] if etl_log else {}
    is_live = latest.get("data_source", "Synthetic") not in [
        "Synthetic", "SYNTHETIC", "SafeNet Synthetic"
    ]
    data_mode = "LIVE" if is_live else "SAMPLE"

    conn.close()
    return {
        "zones": zones,
        "top_events": top_events,
        "states": states,
        "timeseries": timeseries,
        "event_types": event_types,
        "actors": actors,
        "stats": stats,
        "etl_log": etl_log,
        "data_mode": data_mode,
        "generated_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S WAT"),
    }


def build_nigeria_map_svg(states_data):
    """
    Renders a schematic Nigeria map with state zones colour-coded by threat.
    Uses representative zone polygons — not exact boundaries.
    Zone blocks positioned to approximate Nigeria's geography.
    """
    zone_colors = {
        "Northwest":    "#FF4D4D",
        "Northeast":    "#FF6B35",
        "NorthCentral": "#FFB830",
        "SouthSouth":   "#FFD700",
        "SouthEast":    "#90EE90",
        "SouthWest":    "#3CB371",
    }
    zone_scores = {}
    for s in states_data:
        z = s.get("zone", "Unknown")
        if z not in zone_scores:
            zone_scores[z] = []
        zone_scores[z].append(s.get("avg_threat_score", 0))
    zone_avg = {z: round(sum(v)/len(v), 1) for z, v in zone_scores.items() if v}

    # Schematic zone blocks [x, y, w, h, zone_name]
    blocks = [
        (30,  10, 100, 75, "Northwest"),
        (140, 10, 110, 75, "Northeast"),
        (50,  95, 130, 70, "NorthCentral"),
        (30, 175, 110, 70, "SouthSouth"),
        (145, 175, 95,  70, "SouthEast"),
        (10, 175, 15,  70, "SouthWest"),
    ]
    # Move SouthWest to bottom left properly
    blocks = [
        (30,  10, 100, 75, "Northwest"),
        (138, 10, 112, 75, "Northeast"),
        (50,  93, 130, 70, "NorthCentral"),
        (10, 170,  95, 75, "SouthWest"),
        (112, 170, 80, 75, "SouthSouth"),
        (198, 170, 54, 75, "SouthEast"),
    ]

    rects = ""
    for x, y, w, h, zone in blocks:
        color = zone_colors.get(zone, "#666")
        score = zone_avg.get(zone, 0)
        opacity = 0.3 + (score / 100) * 0.65
        short = zone.replace("North", "N.").replace("South", "S.")
        cx, cy = x + w//2, y + h//2
        rects += f"""
        <rect x="{x}" y="{y}" width="{w}" height="{h}" rx="6"
              fill="{color}" fill-opacity="{opacity:.2f}"
              stroke="{color}" stroke-opacity="0.6" stroke-width="1.5"/>
        <text x="{cx}" y="{cy - 6}" text-anchor="middle"
              font-size="9" font-weight="600" fill="white" font-family="monospace">{short}</text>
        <text x="{cx}" y="{cy + 8}" text-anchor="middle"
              font-size="8" fill="rgba(255,255,255,0.85)" font-family="monospace">{score}</text>
        """

    return f"""<svg viewBox="0 0 260 260" xmlns="http://www.w3.org/2000/svg" width="100%" height="100%">
      <rect width="260" height="260" fill="transparent"/>
      {rects}
      <text x="130" y="252" text-anchor="middle" font-size="8"
            fill="rgba(255,255,255,0.4)" font-family="monospace">Avg. threat score by zone</text>
    </svg>"""


def build_timeseries_svg(timeseries):
    """Sparkline chart of daily events over last 30 days."""
    if not timeseries:
        return ""
    counts = [t["count"] for t in timeseries]
    crits = [t["critical"] for t in timeseries]
    dates = [t["event_date"][:10] for t in timeseries]
    max_c = max(counts) if counts else 1
    W, H, PAD = 500, 80, 8

    def pt(i, v):
        x = PAD + i * (W - 2*PAD) / max(len(counts)-1, 1)
        y = H - PAD - (v / max_c) * (H - 2*PAD)
        return f"{x:.1f},{y:.1f}"

    pts = " ".join(pt(i, c) for i, c in enumerate(counts))
    cpts = " ".join(pt(i, c) for i, c in enumerate(crits))
    # Area fill path
    first_x = PAD
    last_x = PAD + (len(counts)-1) * (W - 2*PAD) / max(len(counts)-1, 1)
    area = f"M {first_x} {H-PAD} " + " ".join(
        f"L {pt(i,c)}" for i, c in enumerate(counts)) + f" L {last_x} {H-PAD} Z"

    return f"""<svg viewBox="0 0 {W} {H}" xmlns="http://www.w3.org/2000/svg" width="100%">
      <defs>
        <linearGradient id="areaGrad" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stop-color="#FFB830" stop-opacity="0.35"/>
          <stop offset="100%" stop-color="#FFB830" stop-opacity="0.02"/>
        </linearGradient>
      </defs>
      <path d="{area}" fill="url(#areaGrad)"/>
      <polyline points="{pts}" fill="none" stroke="#FFB830" stroke-width="1.5" stroke-linejoin="round"/>
      <polyline points="{cpts}" fill="none" stroke="#FF4D4D" stroke-width="1" stroke-dasharray="3,2" stroke-linejoin="round"/>
      <text x="4" y="12" font-size="8" fill="rgba(255,255,255,0.4)" font-family="monospace">All events</text>
      <text x="4" y="22" font-size="8" fill="rgba(255,77,77,0.7)" font-family="monospace">── Critical</text>
    </svg>"""


def render_html(data) -> str:
    zones = data["zones"]
    top_events = data["top_events"]
    states = data["states"][:10]
    timeseries = data["timeseries"]
    event_types = data["event_types"]
    actors = data["actors"]
    stats = data["stats"]
    etl_log = data["etl_log"]
    generated_at  = data["generated_at"]
    data_mode     = data.get("data_mode", "SAMPLE")
    is_live       = data_mode == "LIVE"
    data_mode_label   = "LIVE INTELLIGENCE" if is_live else "SAMPLE DATA — NOT LIVE"
    data_source_note  = "Live data" if is_live else "Sample data · ACLED access pending"
    sample_banner = "" if is_live else """
    <div style="background:#FFB830;color:#000;padding:10px 28px;font-size:13px;
                font-weight:600;display:flex;align-items:center;gap:10px;
                border-bottom:1px solid rgba(0,0,0,0.1);">
      <span>⚠️</span>
      <span>This dashboard is currently showing sample data for demonstration purposes.
      Live data integration is in progress. Numbers shown are illustrative, not real.</span>
    </div>""" 

    severity_color = {"CRITICAL": "#FF4D4D", "HIGH": "#FF8C42", "MEDIUM": "#FFB830", "LOW": "#4CAF50"}
    trend_arrow = {"RISING": "↑", "DECLINING": "↓", "STABLE": "→"}
    trend_color = {"RISING": "#FF4D4D", "DECLINING": "#4CAF50", "STABLE": "#FFB830"}

    map_svg = build_nigeria_map_svg(data["states"])
    ts_svg = build_timeseries_svg(timeseries)

    # Build zone cards
    zone_cards = ""
    for z in zones:
        col = severity_color.get("CRITICAL" if z["risk_pct"] > 60 else
                                  "HIGH" if z["risk_pct"] > 40 else
                                  "MEDIUM" if z["risk_pct"] > 20 else "LOW", "#666")
        arrow = trend_arrow.get(z.get("trend_7d", "STABLE"), "→")
        tcol = trend_color.get(z.get("trend_7d", "STABLE"), "#FFB830")
        bar_w = min(100, z.get("risk_pct", 0))
        zone_cards += f"""
        <div class="zone-card">
          <div class="zone-head">
            <span class="zone-name">{z['zone']}</span>
            <span class="trend-badge" style="color:{tcol}">{arrow} {z.get('trend_7d','STABLE')}</span>
          </div>
          <div class="zone-bar-wrap">
            <div class="zone-bar" style="width:{bar_w}%;background:{col}"></div>
          </div>
          <div class="zone-stats">
            <span>{z['total_events']} events</span>
            <span style="color:#FF4D4D">{z['critical_events']} critical</span>
            <span>{z['total_fatalities']} fatalities</span>
            <span style="color:{col};font-weight:600">{z['risk_pct']}%</span>
          </div>
          <div class="zone-actor">Top actor: <em>{z.get('top_actor','Unknown')}</em></div>
        </div>"""

    # Build alert rows
    alert_rows = ""
    for e in top_events:
        col = severity_color.get(e["severity_level"], "#666")
        score = e.get("threat_score", 0)
        days = e.get("days_ago", 0)
        recency = "Today" if days == 0 else f"{days}d ago"
        alert_rows += f"""
        <div class="alert-row" data-severity="{e['severity_level']}">
          <div class="sev-pill" style="background:{col}22;color:{col};border-color:{col}44">
            {e['severity_level']}
          </div>
          <div class="alert-info">
            <div class="alert-title">{e['human_label']} — {e['admin1']}, {e['zone']}</div>
            <div class="alert-sub">{e['actor1']} · {recency} · {e['fatalities']} fatalities</div>
            <div class="alert-note">{e.get('notes','')}</div>
          </div>
          <div class="score-badge" style="border-color:{col}66">
            <span style="color:{col};font-size:18px;font-weight:700">{score:.0f}</span>
            <span style="font-size:10px;color:rgba(255,255,255,0.4)">/ 100</span>
          </div>
        </div>"""

    # Build state rows
    state_rows = ""
    for s in states:
        sc = s.get("avg_threat_score", 0)
        bar = min(100, sc)
        col = "#FF4D4D" if sc > 40 else "#FFB830" if sc > 20 else "#4CAF50"
        state_rows += f"""
        <div class="state-row">
          <span class="state-name">{s['state']}</span>
          <div class="state-bar-wrap">
            <div class="state-bar" style="width:{bar}%;background:{col}"></div>
          </div>
          <span class="state-score" style="color:{col}">{sc:.1f}</span>
        </div>"""

    # Build event type donut data
    et_total = sum(e["count"] for e in event_types)
    et_rows = ""
    et_colors = ["#FF4D4D", "#FF8C42", "#FFB830", "#3B9EFF", "#A855F7"]
    for i, et in enumerate(event_types):
        col = et_colors[i % len(et_colors)]
        pct = round(et["count"] / et_total * 100) if et_total else 0
        et_rows += f"""
        <div class="et-row">
          <span class="et-dot" style="background:{col}"></span>
          <span class="et-label">{et['human_label']}</span>
          <span class="et-bar-wrap"><div class="et-bar" style="width:{pct}%;background:{col}"></div></span>
          <span class="et-pct">{pct}%</span>
        </div>"""

    # Actor rows
    actor_rows = ""
    max_inc = max((a["incidents"] for a in actors), default=1)
    for a in actors:
        bar = round(a["incidents"] / max_inc * 100)
        actor_rows += f"""
        <div class="actor-row">
          <span class="actor-name">{a['actor']}</span>
          <div class="actor-bar-wrap">
            <div class="actor-bar" style="width:{bar}%"></div>
          </div>
          <span class="actor-count">{a['incidents']}</span>
        </div>"""

    # Data freshness rows — plain English format
    etl_rows = ""
    for log in etl_log:
        status_text = "✓ Updated successfully" if log["status"] == "SUCCESS" else "⚠ Update had issues"
        status_col  = "#4CAF50" if log["status"] == "SUCCESS" else "#FFB830"
        run_time    = log["run_at"][:16].replace("T", " at ")
        etl_rows += f"""
        <div class="log-row">
          <span style="font-size:12px;color:var(--text2)">Last updated: {run_time} WAT</span>
          <span style="font-size:12px;color:var(--text2)">{log['records_fetched']} records checked</span>
          <span style="color:{status_col};font-size:12px;font-weight:600">{status_text}</span>
        </div>"""

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<link rel="icon" type="image/svg+xml" href="favicon.svg">
<link rel="shortcut icon" href="favicon.svg">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>SafeNet Nigeria — Security Intelligence Platform</title>
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=Space+Mono:ital,wght@0,400;0,700;1,400&family=Barlow:wght@300;400;500;600;700&display=swap" rel="stylesheet">
<style>
  :root {{
    --bg:       #07090D;
    --surface:  #0C1018;
    --surface2: #121820;
    --border:   rgba(255,255,255,0.06);
    --border2:  rgba(255,255,255,0.11);
    --text:     #E8EEFF;
    --text2:    #7A8BAA;
    --text3:    #394558;
    --red:      #FF4D4D;
    --amber:    #FFB830;
    --green:    #3CB371;
    --blue:     #3B9EFF;
    --nigeria:  #008751;
  }}
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}

  body {{
    background: var(--bg);
    color: var(--text);
    font-family: 'Barlow', sans-serif;
    font-weight: 400;
    min-height: 100vh;
    line-height: 1.5;
  }}

  /* Grain overlay */
  body::after {{
    content: '';
    position: fixed; inset: 0;
    background-image: url("data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='n'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.75' numOctaves='4'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23n)' opacity='0.03'/%3E%3C/svg%3E");
    pointer-events: none; z-index: 9999;
  }}

  /* ── HEADER ── */
  .header {{
    border-bottom: 1px solid var(--border);
    background: linear-gradient(180deg, rgba(0,135,81,0.08) 0%, transparent 100%);
    padding: 0 28px;
    display: flex; align-items: center; gap: 20px;
    height: 58px;
    position: sticky; top: 0; z-index: 100;
    backdrop-filter: blur(20px);
  }}
  .logo {{
    display: flex; align-items: center; gap: 10px;
  }}
  .logo-mark {{
    width: 32px; height: 32px; background: var(--nigeria);
    border-radius: 8px; display: flex; align-items: center;
    justify-content: center; font-family: 'Space Mono', monospace;
    font-size: 12px; font-weight: 700; color: white;
    flex-shrink: 0;
  }}
  .logo-text {{
    font-size: 16px; font-weight: 700; letter-spacing: .03em;
  }}
  .logo-text span {{ color: var(--nigeria); }}
  .header-meta {{
    margin-left: auto; display: flex; align-items: center; gap: 16px;
  }}
  .live-badge {{
    display: flex; align-items: center; gap: 6px;
    font-family: 'Space Mono', monospace; font-size: 10px;
    color: var(--green); padding: 4px 10px; border-radius: 20px;
    background: rgba(60,179,113,0.1); border: 1px solid rgba(60,179,113,0.2);
  }}
  .live-dot {{
    width: 5px; height: 5px; border-radius: 50%;
    background: var(--green); animation: pulse 2s infinite;
  }}
  @keyframes pulse {{ 0%,100%{{opacity:1}} 50%{{opacity:.2}} }}
  .gen-time {{
    font-family: 'Space Mono', monospace; font-size: 10px; color: var(--text3);
  }}

  /* ── LAYOUT ── */
  .content {{ padding: 24px 28px; }}

  .page-title {{
    font-size: 13px; font-weight: 500;
    color: var(--text2); text-transform: uppercase;
    letter-spacing: .1em; margin-bottom: 20px;
    font-family: 'Space Mono', monospace;
  }}
  .page-title span {{ color: var(--amber); }}

  /* ── STAT ROW ── */
  .stat-row {{
    display: grid; grid-template-columns: repeat(4, 1fr);
    gap: 14px; margin-bottom: 22px;
  }}
  .stat-card {{
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 12px; padding: 16px 18px;
    position: relative; overflow: hidden;
  }}
  .stat-card::before {{
    content: ''; position: absolute; top: 0; left: 0; right: 0;
    height: 2px; border-radius: 12px 12px 0 0;
  }}
  .sc-red::before   {{ background: var(--red); }}
  .sc-amber::before {{ background: var(--amber); }}
  .sc-green::before {{ background: var(--green); }}
  .sc-blue::before  {{ background: var(--blue); }}
  .stat-label {{
    font-family: 'Space Mono', monospace; font-size: 10px;
    color: var(--text3); text-transform: uppercase; letter-spacing: .07em;
    margin-bottom: 8px;
  }}
  .stat-num {{
    font-size: 32px; font-weight: 700; letter-spacing: -.02em;
    line-height: 1;
  }}
  .sc-red .stat-num   {{ color: var(--red); }}
  .sc-amber .stat-num {{ color: var(--amber); }}
  .sc-green .stat-num {{ color: var(--green); }}
  .sc-blue .stat-num  {{ color: var(--blue); }}
  .stat-sub {{
    font-size: 11px; color: var(--text3); margin-top: 5px;
  }}

  /* ── PANELS ── */
  .grid-2 {{ display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-bottom: 16px; }}
  .grid-3 {{ display: grid; grid-template-columns: 1fr 1fr 1fr; gap: 16px; margin-bottom: 16px; }}
  .grid-map {{ display: grid; grid-template-columns: 240px 1fr; gap: 16px; margin-bottom: 16px; }}

  .panel {{
    background: var(--surface); border: 1px solid var(--border);
    border-radius: 12px; overflow: hidden;
  }}
  .panel-head {{
    display: flex; align-items: center; justify-content: space-between;
    padding: 13px 18px; border-bottom: 1px solid var(--border);
  }}
  .panel-title {{
    font-size: 12px; font-weight: 600; color: var(--text);
    letter-spacing: .03em; display: flex; align-items: center; gap: 8px;
  }}
  .panel-badge {{
    font-family: 'Space Mono', monospace; font-size: 10px;
    padding: 2px 7px; border-radius: 20px;
  }}
  .pb-red   {{ background:rgba(255,77,77,.12);   color:var(--red);   border:1px solid rgba(255,77,77,.2);   }}
  .pb-amber {{ background:rgba(255,184,48,.12);  color:var(--amber); border:1px solid rgba(255,184,48,.2);  }}
  .pb-green {{ background:rgba(60,179,113,.12);  color:var(--green); border:1px solid rgba(60,179,113,.2);  }}
  .panel-meta {{
    font-family: 'Space Mono', monospace; font-size: 10px; color: var(--text3);
  }}

  /* ── ZONE CARDS ── */
  .zones-wrap {{ padding: 14px 18px; display: flex; flex-direction: column; gap: 10px; }}
  .zone-card {{
    background: var(--surface2); border: 1px solid var(--border);
    border-radius: 8px; padding: 10px 12px;
  }}
  .zone-head {{
    display: flex; justify-content: space-between; align-items: center;
    margin-bottom: 6px;
  }}
  .zone-name {{ font-size: 12px; font-weight: 600; }}
  .trend-badge {{ font-size: 10px; font-weight: 600; letter-spacing: .03em; }}
  .zone-bar-wrap {{
    height: 4px; background: var(--border); border-radius: 2px; overflow: hidden; margin-bottom: 6px;
  }}
  .zone-bar {{ height: 100%; border-radius: 2px; transition: width .5s; }}
  .zone-stats {{
    display: flex; gap: 10px; font-size: 10px; color: var(--text2);
    font-family: 'Space Mono', monospace;
  }}
  .zone-actor {{
    font-size: 10px; color: var(--text3); margin-top: 4px;
    font-style: italic;
  }}

  /* ── ALERT FEED ── */
  .alerts-wrap {{ display: flex; flex-direction: column; }}
  .alert-row {{
    display: flex; align-items: flex-start; gap: 12px;
    padding: 12px 18px; border-bottom: 1px solid var(--border);
    transition: background .15s; cursor: pointer;
  }}
  .alert-row:hover {{ background: var(--surface2); }}
  .alert-row:last-child {{ border-bottom: none; }}
  .sev-pill {{
    font-family: 'Space Mono', monospace; font-size: 9px;
    padding: 3px 7px; border-radius: 4px; border: 1px solid;
    flex-shrink: 0; margin-top: 2px; font-weight: 700;
    letter-spacing: .06em; white-space: nowrap;
  }}
  .alert-info {{ flex: 1; min-width: 0; }}
  .alert-title {{ font-size: 12px; font-weight: 600; margin-bottom: 2px; }}
  .alert-sub {{
    font-size: 11px; color: var(--text2);
    font-family: 'Space Mono', monospace; margin-bottom: 3px;
  }}
  .alert-note {{ font-size: 11px; color: var(--text3); font-style: italic; }}
  .score-badge {{
    border: 1px solid; border-radius: 8px;
    padding: 4px 8px; text-align: center; flex-shrink: 0;
    min-width: 52px;
  }}

  /* ── STATE BARS ── */
  .states-wrap {{ padding: 14px 18px; display: flex; flex-direction: column; gap: 7px; }}
  .state-row {{ display: flex; align-items: center; gap: 10px; }}
  .state-name {{
    font-size: 11px; color: var(--text2);
    font-family: 'Space Mono', monospace; width: 88px; flex-shrink: 0;
  }}
  .state-bar-wrap {{
    flex: 1; height: 5px; background: var(--border); border-radius: 3px; overflow: hidden;
  }}
  .state-bar {{ height: 100%; border-radius: 3px; }}
  .state-score {{
    font-family: 'Space Mono', monospace; font-size: 11px;
    font-weight: 700; width: 32px; text-align: right; flex-shrink: 0;
  }}

  /* ── EVENT TYPES ── */
  .et-wrap {{ padding: 14px 18px; display: flex; flex-direction: column; gap: 8px; }}
  .et-row {{ display: flex; align-items: center; gap: 8px; }}
  .et-dot {{ width: 7px; height: 7px; border-radius: 50%; flex-shrink: 0; }}
  .et-label {{ font-size: 11px; color: var(--text2); flex: 1; }}
  .et-bar-wrap {{
    width: 80px; height: 4px; background: var(--border);
    border-radius: 2px; overflow: hidden; flex-shrink: 0;
  }}
  .et-bar {{ height: 100%; border-radius: 2px; }}
  .et-pct {{
    font-family: 'Space Mono', monospace; font-size: 10px;
    color: var(--text3); width: 28px; text-align: right;
  }}

  /* ── ACTORS ── */
  .actors-wrap {{ padding: 14px 18px; display: flex; flex-direction: column; gap: 8px; }}
  .actor-row {{ display: flex; align-items: center; gap: 8px; }}
  .actor-name {{ font-size: 11px; color: var(--text2); flex: 1; min-width: 0;
    white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }}
  .actor-bar-wrap {{
    width: 70px; height: 5px; background: var(--border);
    border-radius: 3px; overflow: hidden; flex-shrink: 0;
  }}
  .actor-bar {{ height: 100%; border-radius: 3px; background: var(--red); opacity: .7; }}
  .actor-count {{
    font-family: 'Space Mono', monospace; font-size: 11px;
    color: var(--text3); width: 24px; text-align: right;
  }}

  /* ── MAP ── */
  .map-wrap {{ padding: 12px 14px; }}

  /* ── TIMESERIES ── */
  .ts-wrap {{ padding: 14px 18px; }}
  .ts-label {{
    font-family: 'Space Mono', monospace; font-size: 10px;
    color: var(--text3); margin-bottom: 8px;
  }}

  /* ── ETL LOG ── */
  .log-wrap {{ padding: 12px 18px; display: flex; flex-direction: column; gap: 7px; }}
  .log-row {{
    display: flex; gap: 16px; align-items: center;
    padding: 6px 0; border-bottom: 1px solid var(--border);
  }}
  .log-row:last-child {{ border-bottom: none; }}

  /* ── PSYCH NOTE ── */
  .psych-note {{
    background: rgba(59,158,255,0.05);
    border: 1px solid rgba(59,158,255,0.15);
    border-radius: 8px; padding: 10px 14px;
    font-size: 11px; color: var(--text2);
    font-style: italic; line-height: 1.6; margin: 14px 0 0;
  }}
  .psych-note strong {{ color: var(--blue); font-style: normal; }}

  /* ── SCROLLBAR ── */
  ::-webkit-scrollbar {{ width: 4px; }}
  ::-webkit-scrollbar-track {{ background: transparent; }}
  ::-webkit-scrollbar-thumb {{ background: var(--border2); border-radius: 2px; }}

  /* ── ANIMATIONS ── */
  @keyframes fadeUp {{
    from {{ opacity: 0; transform: translateY(12px); }}
    to   {{ opacity: 1; transform: translateY(0); }}
  }}
  .panel {{ animation: fadeUp .5s ease both; }}
  .stat-card {{ animation: fadeUp .4s ease both; }}
  .stat-card:nth-child(1){{animation-delay:.05s}}
  .stat-card:nth-child(2){{animation-delay:.1s}}
  .stat-card:nth-child(3){{animation-delay:.15s}}
  .stat-card:nth-child(4){{animation-delay:.2s}}
</style>
</head>
<body>

<!-- HEADER -->
<header class="header">
  <div class="logo">
    <div class="logo-mark">SN</div>
    <div class="logo-text">Safe<span>Net</span> Nigeria</div>
  </div>
  <span style="font-size:11px;color:var(--text3);font-family:'Space Mono',monospace;padding:3px 10px;border:1px solid var(--border);border-radius:6px">PHASE 1 · CONFLICT INTELLIGENCE</span>
  <div class="header-meta">
    <div class="live-badge"><div class="live-dot"></div> SAMPLE DATA — DEMONSTRATION MODE</div>
    <div class="gen-time">Generated {generated_at}</div>
  </div>
</header>

<!-- SAMPLE DATA BANNER -->
{sample_banner}


  <!-- SAMPLE DATA NOTICE -->
  <div style="background:linear-gradient(90deg,#FFB830,#FF8C42);
              color:#000;padding:11px 28px;font-size:13px;
              font-weight:600;display:flex;align-items:center;
              gap:10px;position:sticky;top:58px;z-index:99;">
    <span style="font-size:16px">⚠️</span>
    <span>SAMPLE DATA — This dashboard is running on demonstration data.
    Live intelligence integration is in progress.
    Statistics shown are illustrative only.</span>
    <a href="https://github.com/Abbey-commit/safenet-nigeria"
       style="margin-left:auto;color:#000;font-size:11px;
              text-decoration:underline;white-space:nowrap">
      View source →
    </a>
  </div>

  <!-- SAMPLE DATA NOTICE -->
<!-- CONTENT -->
<main class="content">
  <div class="page-title">Nigeria Security Intelligence Dashboard · <span>90-Day Analysis Window</span></div>

  <!-- STAT CARDS -->
  <div class="stat-row">
    <div class="stat-card sc-red">
      <div class="stat-label">Conflict Events</div>
      <div class="stat-num">{stats['total_events']}</div>
      <div class="stat-sub">Last 90 days · all zones · ACLED</div>
    </div>
    <div class="stat-card sc-red">
      <div class="stat-label">Critical Incidents</div>
      <div class="stat-num">{stats['critical']}</div>
      <div class="stat-sub">Battles and bombings</div>
    </div>
    <div class="stat-card sc-amber">
      <div class="stat-label">Confirmed Fatalities</div>
      <div class="stat-num">{stats['total_fatalities']}</div>
      <div class="stat-sub">Human cost · every life counted</div>
    </div>
    <div class="stat-card sc-blue">
      <div class="stat-label">Total Intelligence Records</div>
      <div class="stat-num">{stats['total_records']}</div>
      <div class="stat-sub">ACLED + UNODC + Police · 3 sources</div>
    </div>
  </div>

  <!-- MAP + ZONE RISK -->
  <div class="grid-map">
    <div class="panel">
      <div class="panel-head">
        <div class="panel-title">🗺️ Zone Risk Map</div>
        <div class="panel-meta">Avg threat score</div>
      </div>
      <div class="map-wrap">{map_svg}</div>
      <div class="psych-note">
        <strong>Design note:</strong> Colour intensity scales with threat score, not raw event count.
        High-fatality low-frequency zones are not underweighted — protecting against
        "psychic numbing" (Slovic, 2007).
      </div>
    </div>

    <div class="panel">
      <div class="panel-head">
        <div class="panel-title">⚡ Zone Threat Breakdown <span class="panel-badge pb-red">6 ZONES</span></div>
        <div class="panel-meta">Sorted by risk score</div>
      </div>
      <div class="zones-wrap">{zone_cards}</div>
    </div>
  </div>

  <!-- ALERT FEED + STATE BARS -->
  <div class="grid-2">
    <div class="panel">
      <div class="panel-head">
        <div class="panel-title">🚨 Highest Threat Events <span class="panel-badge pb-red">TOP 8</span></div>
        <div class="panel-meta">Score = recency × severity × impact</div>
      </div>
      <div class="alerts-wrap">{alert_rows}</div>
      <div class="psych-note" style="margin:0;border-radius:0;border-left:none;border-right:none;border-bottom:none">
        <strong>Human labels:</strong> Analysts see "Armed confrontation" not "Battles" —
        clinical distance increases error rate under stress (Klein, 1998).
      </div>
    </div>

    <div class="panel">
      <div class="panel-head">
        <div class="panel-title">📍 Top 10 Threat States</div>
        <div class="panel-meta">Avg threat score</div>
      </div>
      <div class="states-wrap">{state_rows}</div>
    </div>
  </div>

  <!-- TIMESERIES + EVENT TYPES + ACTORS -->
  <div class="grid-3">
    <div class="panel">
      <div class="panel-head">
        <div class="panel-title">📈 30-Day Event Trend</div>
      </div>
      <div class="ts-wrap">
        <div class="ts-label">Daily conflict events — amber=total, red dashed=critical</div>
        {ts_svg}
      </div>
    </div>

    <div class="panel">
      <div class="panel-head">
        <div class="panel-title">🔖 Incident Type Breakdown</div>
      </div>
      <div class="et-wrap">{et_rows}</div>
    </div>

    <div class="panel">
      <div class="panel-head">
        <div class="panel-title">⚔️ Most Active Non-State Actors</div>
        <div class="panel-meta">Excludes security forces</div>
      </div>
      <div class="actors-wrap">{actor_rows}</div>
    </div>
  </div>

  <!-- ETL AUDIT LOG -->
  <div class="panel">
    <div class="panel-head">
      <div class="panel-title">✅ Data Freshness &amp; Update Log <span class="panel-badge pb-green">VERIFIED</span></div>
      <div class="panel-meta" style="font-style:italic;color:var(--text3)">When was this data last updated?</div>
    </div>
    <div class="log-wrap">{etl_rows}</div>
    <div class="psych-note" style="margin:12px 18px;border-radius:8px">
      <strong>Why transparency matters:</strong> Displaying the pipeline audit log to analysts
      builds appropriate trust in the data — neither over-reliance nor dismissal.
      Automation bias (Parasuraman & Manzey, 2010) is reduced when humans can see
      how the intelligence was produced.
    </div>
  </div>

</main>

<script>
  // Live clock
  function updateClock() {{
    var el = document.querySelector('.gen-time');
    if (el) {{
      var d = new Date();
      var h = String(d.getHours()).padStart(2,'0');
      var m = String(d.getMinutes()).padStart(2,'0');
      var s = String(d.getSeconds()).padStart(2,'0');
      el.textContent = 'Live: ' + h + ':' + m + ':' + s + ' WAT';
    }}
  }}
  setInterval(updateClock, 1000); updateClock();

  // Filter by severity
  document.querySelectorAll('.alert-row').forEach(function(row) {{
    row.addEventListener('click', function() {{
      this.style.outline = '1px solid rgba(255,184,48,0.4)';
      setTimeout(function(){{ row.style.outline=''; }}, 1200);
    }});
  }});
</script>
</body>
</html>"""


def generate():
    os.makedirs(os.path.dirname(OUTPUT_PATH), exist_ok=True)
    print("[Dashboard] Loading intelligence data from store...")
    data = load_data()
    print(f"[Dashboard] Rendering HTML dashboard...")
    html = render_html(data)
    with open(OUTPUT_PATH, "w", encoding="utf-8") as f:
        f.write(html)
    size_kb = round(os.path.getsize(OUTPUT_PATH) / 1024, 1)
    print(f"[Dashboard] Written to: {OUTPUT_PATH} ({size_kb} KB)")
    print(f"[Dashboard] Open in browser: file://{os.path.abspath(OUTPUT_PATH)}")
    return OUTPUT_PATH


if __name__ == "__main__":
    generate()