"""
SafeNet Nigeria — Phase 2A
Master Pipeline Runner
=======================
Three data sources running in sequence:
  Source 1: ACLED   — conflict events (incident level)
  Source 2: UNODC   — crime statistics (UN level)
  Source 3: NPF     — Nigeria Police Force records

Usage:
    python run_pipeline.py

Live ACLED requires .env file with:
    ACLED_EMAIL=info@safe-nigeria.com.ng
    ACLED_PASSWORD=your_password
"""

import os
import sys
import time
import shutil

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

sys.path.insert(0, os.path.dirname(__file__))

from pipeline.database import ETLPipeline
from pipeline.unodc_ingestor import UNODCIngestor, UNODCDBStore
from pipeline.npf_ingestor import NPFIngestor, NPFDBStore
from pipeline.generate_dashboard import generate


def run_source(label, fn):
    """Run a data source with consistent logging."""
    print(f"\n{'━'*60}")
    print(f"  DATA SOURCE: {label}")
    print(f"{'━'*60}")
    try:
        return fn()
    except Exception as e:
        print(f"[ERROR] {label} failed: {e}")
        return None


def main():
    start = time.time()
    print("\n" + "="*60)
    print("  SAFENET NIGERIA — PHASE 2A PIPELINE")
    print("  Three-Source Security Intelligence System")
    print("="*60)

    db_path = os.path.join(os.path.dirname(__file__), "data", "safenet.db")

    # ── SOURCE 1: ACLED ──────────────────────────────────────────
    # PAUSED as of [today's date] pending resolution of ACLED compliance
    # review (formal notice received re: non-transformative display).
    # Re-enable only after: (1) written confirmation from ACLED, and
    # (2) confirming the correct license tier for public/non-academic use.
    ACLED_PAUSED = True

    def run_acled():
        pipeline = ETLPipeline(
            email=os.getenv("ACLED_EMAIL"),
            password=os.getenv("ACLED_PASSWORD"),
        )
        return pipeline.run(days_back=90, run_type="full_refresh")

    if ACLED_PAUSED:
        print("\n[SKIPPED] ACLED Conflict Events — paused pending compliance review")
        acled_result = None
    else:
        acled_result = run_source("ACLED Conflict Events", run_acled)

    # ── SOURCE 2: UNODC ──────────────────────────────────────────
    def run_unodc():
        ingestor = UNODCIngestor()
        df = ingestor.fetch(years_back=5)
        summary = ingestor.get_summary(df)
        store = UNODCDBStore(db_path)
        counts = store.upsert(df)
        store.refresh_sector_summary()
        print(f"[UNODC] {summary['total_records']} records across "
              f"{summary['categories']} categories, "
              f"{summary['states']} states")
        print(f"[UNODC] Stored: {counts}")
        return summary

    unodc_result = run_source("UNODC Crime Statistics", run_unodc)

    # ── SOURCE 3: NPF ─────────────────────────────────────────────
    def run_npf():
        ingestor = NPFIngestor()
        df = ingestor.fetch(years_back=3)
        summary = ingestor.get_summary(df)
        store = NPFDBStore(db_path)
        counts = store.upsert(df)
        store.refresh_sector_summary()
        print(f"[NPF] {summary['total_records']} records")
        print(f"[NPF] Total reported cases: "
              f"{summary['total_reported']:,}")
        print(f"[NPF] Estimated real cases: "
              f"{summary['total_estimated']:,}")
        print(f"[NPF] Avg clearance rate: "
              f"{summary['avg_clearance_rate']}%")
        print(f"[NPF] Stored: {counts}")
        return summary

    npf_result = run_source("Nigeria Police Force Records", run_npf)

    # ── GENERATE DASHBOARD ────────────────────────────────────────
    print(f"\n{'━'*60}")
    print(f"  GENERATING INTELLIGENCE DASHBOARD")
    print(f"{'━'*60}")
    output_path = generate()

    # ── SYNC TO DOCS FOR GITHUB PAGES ────────────────────────────
    docs_path = os.path.join(os.path.dirname(__file__), "docs")
    os.makedirs(docs_path, exist_ok=True)
    shutil.copy(
        os.path.join(os.path.dirname(__file__), "dashboard", "index.html"),
        os.path.join(docs_path, "index.html")
    )
    cname_path = os.path.join(docs_path, "CNAME")
    if not os.path.exists(cname_path):
        with open(cname_path, "w") as f:
            f.write("safe-nigeria.com.ng")
    print(f"[Pages] docs/index.html synced")

    # ── FINAL SUMMARY ─────────────────────────────────────────────
    total = round(time.time() - start, 2)
    acled_events    = acled_result.get("total_events", 0) if acled_result else 0
    acled_critical  = acled_result.get("critical_events", 0) if acled_result else 0
    unodc_records   = unodc_result.get("total_records", 0) if unodc_result else 0
    npf_records     = npf_result.get("total_records", 0) if npf_result else 0
    npf_reported    = npf_result.get("total_reported", 0) if npf_result else 0

    print(f"\n{'='*60}")
    print(f"  PIPELINE COMPLETE in {total}s")
    print(f"{'='*60}")
    print(f"  ACLED conflict events : {acled_events:,}")
    print(f"  Critical events       : {acled_critical:,}")
    print(f"  UNODC crime records   : {unodc_records:,}")
    print(f"  NPF police records    : {npf_records:,}")
    print(f"  NPF reported cases    : {npf_reported:,}")
    print(f"  Total intelligence    : "
          f"{acled_events + unodc_records + npf_records:,} records")
    print(f"  Dashboard             : {output_path}")
    print(f"  Live domain           : https://safe-nigeria.com.ng")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()