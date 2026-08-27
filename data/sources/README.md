# SafeNet Data Sources

Drop downloaded datasets here. Pipeline reads local files
automatically — no code changes needed.

Files expected:
  unodc_nigeria.xlsx  → UNODC crime stats
                        Download: https://dataunodc.un.org
  npf_nigeria.xlsx    → NBS/NPF crime records
                        Download: https://nigerianstat.gov.ng

Once a file is here, run:  python run_pipeline.py
The pipeline switches from sample to real data automatically.
