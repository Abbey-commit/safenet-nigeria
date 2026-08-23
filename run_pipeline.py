"""
SafeNet Nigeria — Phase 2A
Master Pipeline Runner
=======================
Runs all data sources in sequence:
  Source 1: ACLED    — conflict events (incident level)
  Source 2: UNODC    — crime statistics (structural level)

Usage:
    python run_pipeline.py

Live data requires .env file with:
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
from pipeline.generate_dashboard import generate


def main():
    start = time.time()
    print("\n" + "="*60)
    print("  SAFENET NIGERIA — PHASE 2A PIPELINE")
    print("  Multi-Source Security Intelligence System")
    print("="*60 + "\n")

    # ── SOURCE 1: ACLED conflict events ──────────────────────────
    print("━"*60)
    print("  DATA SOURCE 1: ACLED Conflict Events")
    print("━"*60)
    pipeline = ETLPipeline(
        email=os.getenv("ACLED_EMAIL"),
        password=os.getenv("ACLED_PASSWORD"),
    )
    result = pipeline.run(days_back=90, run_type="full_refresh")

    # ── SOURCE 2: UNODC crime statistics ─────────────────────────
    print("\n" + "━"*60)
    print("  DATA SOURCE 2: UNODC Crime Statistics")
    print("━"*60)
    unodc = UNODCIngestor()
    unodc_df = unodc.fetch(years_back=5)
    unodc_summary = unodc.get_summary(unodc_df)
    print(f"[UNODC] Records: {unodc_summary['total_records']}")
    print(f"[UNODC] Categories: {unodc_summary['categories']}")
    print(f"[UNODC] States: {unodc_summary['states']}")

    db_path = os.path.join(os.path.dirname(__file__), "data", "safenet.db")
    unodc_store = UNODCDBStore(db_path)
    unodc_counts = unodc_store.upsert(unodc_df)
    unodc_store.refresh_sector_summary()
    print(f"[UNODC] Stored: {unodc_counts}")

    # ── GENERATE DASHBOARD ────────────────────────────────────────
    print("\n" + "━"*60)
    print("  GENERATING INTELLIGENCE DASHBOARD")
    print("━"*60)
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
    print(f"[Pages] docs/index.html synced for GitHub Pages")

    # ── SUMMARY ──────────────────────────────────────────────────
    total = round(time.time() - start, 2)
    print(f"\n{'='*60}")
    print(f"  PIPELINE COMPLETE in {total}s")
    print(f"  ACLED events     : {result['total_events']}")
    print(f"  Critical events  : {result['critical_events']}")
    print(f"  UNODC records    : {unodc_summary['total_records']}")
    print(f"  Dashboard        : {output_path}")
    print(f"  Live domain      : https://safe-nigeria.com.ng")
    print(f"{'='*60}\n")


if __name__ == "__main__":
    main()
