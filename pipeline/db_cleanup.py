"""
SafeNet Nigeria — Database Cleanup Utility
==========================================
Removes duplicate rows accumulated in summary tables
from multiple pipeline runs.

Run once to clean existing database:
    python pipeline/db_cleanup.py

The fix in database.py, unodc_ingestor.py and npf_ingestor.py
prevents new duplicates from forming going forward.
"""

import sqlite3
import os

DB_PATH = os.path.join(
    os.path.dirname(os.path.dirname(__file__)), "data", "safenet.db"
)


def cleanup(db_path: str):
    print(f"[Cleanup] Connecting to: {db_path}")
    conn = sqlite3.connect(db_path)

    tables = {
        "zone_threat_summary":  ("zone", "snapshot_date"),
        "state_threat_summary": ("state", "snapshot_date"),
        "unodc_sector_summary": ("sector", "zone", "snapshot_date"),
        "npf_sector_summary":   ("sector", "zone", "snapshot_date"),
    }

    for table, keys in tables.items():
        # Check table exists
        exists = conn.execute(
            f"SELECT name FROM sqlite_master "
            f"WHERE type='table' AND name='{table}'"
        ).fetchone()

        if not exists:
            print(f"[Cleanup] {table} — not found, skipping")
            continue

        before = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]

        # Keep only the row with the highest id for each unique key combination
        key_cols = ", ".join(keys)
        conn.execute(f"""
            DELETE FROM {table}
            WHERE id NOT IN (
                SELECT MAX(id)
                FROM {table}
                GROUP BY {key_cols}
            )
        """)
        conn.commit()

        after = conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
        removed = before - after
        print(f"[Cleanup] {table}: {before} → {after} rows "
              f"({removed} duplicates removed)")

    # Also clean conflict_events — keep latest per event_id_cnty
    before = conn.execute("SELECT COUNT(*) FROM conflict_events").fetchone()[0]
    conn.execute("""
        DELETE FROM conflict_events
        WHERE id NOT IN (
            SELECT MAX(id)
            FROM conflict_events
            GROUP BY event_id_cnty
        )
    """)
    conn.commit()
    after = conn.execute("SELECT COUNT(*) FROM conflict_events").fetchone()[0]
    print(f"[Cleanup] conflict_events: {before} → {after} rows "
          f"({before - after} duplicates removed)")

    conn.close()
    print("[Cleanup] Complete — database is clean")


if __name__ == "__main__":
    cleanup(DB_PATH)