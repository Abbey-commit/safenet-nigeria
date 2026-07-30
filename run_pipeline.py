"""
SafeNet Nigeria — Phase 1
Master Run Script
=================
Runs the full pipeline end-to-end:
  Day 1: Extract (ACLED ingestor)
  Day 2: Transform + Load (ETL + DB)
  Day 3: Generate dashboard

Usage:
    python run_pipeline.py                     # synthetic data (dev)
    ACLED_API_KEY=xxx ACLED_EMAIL=y@z.com python run_pipeline.py  # live data

To connect live ACLED data:
  1. Register at: https://acleddata.com/register/
  2. Get your API key from your account dashboard
  3. Set env vars: ACLED_API_KEY and ACLED_EMAIL
  4. Run again — zero other code changes needed
"""

import os
import sys
import time

sys.path.insert(0, os.path.dirname(__file__))

from pipeline.database import ETLPipeline
from pipeline.generate_dashboard import generate

def main():
    print("\n" + "="*60)
    print("  SAFENET NIGERIA — PHASE 1 PIPELINE")
    print("  Conflict Intelligence System")
    print("="*60 + "\n")

    start = time.time()

    # Step 1 + 2: Extract, Transform, Load
    pipeline = ETLPipeline(
        password=os.getenv("ACLED_PASSWORD"),
        email=os.getenv("ACLED_EMAIL"),
    )
    result = pipeline.run(days_back=90, run_type="full_refresh")

    # Step 3: Generate dashboard
    print("\nGenerating intelligence dashboard...")
    output_path = generate()

    total = round(time.time() - start, 2)
    print(f"\n{'='*60}")
    print(f"  COMPLETE in {total}s")
    print(f"  Events in store : {result['total_events']}")
    print(f"  Critical events : {result['critical_events']}")
    print(f"  Total fatalities: {result['total_fatalities']}")
    print(f"  Dashboard        : {output_path}")
    print(f"\n  To switch to live ACLED data:")
    print(f"  1. Register free at https://acleddata.com/register/")
    print(f"  2. export ACLED_API_KEY=your_key")
    print(f"  3. export ACLED_EMAIL=your@email.com")
    print(f"  4. python run_pipeline.py")
    print(f"{'='*60}\n")

if __name__ == "__main__":
    main()
