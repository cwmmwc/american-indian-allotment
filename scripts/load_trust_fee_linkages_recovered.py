"""
Load linkage_candidates.csv (57,019 validated trust→fee linkages recovered from
the BLM patent remarks field) into trust_fee_linkages_recovered.

Uses psycopg2.extras.execute_values to batch-insert 1,000 rows per round-trip
so the load completes in seconds locally and in minutes against Cloud SQL.
Idempotent: re-running skips rows that already exist (ON CONFLICT DO NOTHING
on the unique (trust_accession, fee_accession) pair).

Usage:
    ./venv/bin/python3 scripts/load_trust_fee_linkages_recovered.py            # writes
    ./venv/bin/python3 scripts/load_trust_fee_linkages_recovered.py --dry-run  # report only
"""
import os
import sys
import csv
import psycopg2
import psycopg2.extras
from collections import Counter

DB_URL    = os.environ.get("DATABASE_URL", "dbname=allotment_research user=cwm6W")
CSV_PATH  = "linkage_candidates.csv"
DRY_RUN   = "--dry-run" in sys.argv
BATCH     = 1000


def to_int(v):
    if v is None or v == "": return None
    try: return int(v)
    except ValueError: return None


def to_date(v):
    if v is None or v == "": return None
    return v   # CSV already has ISO YYYY-MM-DD; let Postgres parse


def to_bool(v):
    if v is None or v == "": return None
    s = str(v).strip().lower()
    if s in ("yes", "true", "1", "t"): return True
    if s in ("no",  "false", "0", "f"): return False
    return None


def main():
    if not os.path.exists(CSV_PATH):
        sys.exit(f"missing {CSV_PATH}")

    rows = []
    types = Counter()
    with open(CSV_PATH) as f:
        for r in csv.DictReader(f):
            rows.append((
                r["trust_accession"],
                r["fee_accession"],
                r.get("extracted_raw") or None,
                r.get("match_type") or None,
                r.get("name_overlap") or None,
                to_bool(r.get("name_consistent")),
                to_int(r.get("date_gap_years")),
                to_date(r.get("trust_date")),
                to_date(r.get("fee_date")),
                r.get("fee_authority") or None,
                r.get("fee_state") or None,
            ))
            types[r.get("match_type", "?")] += 1
    print(f"loaded {len(rows):,} rows from {CSV_PATH}")
    print(f"match_type breakdown: {dict(types.most_common())}")
    print()

    conn = psycopg2.connect(DB_URL)
    cur  = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM trust_fee_linkages_recovered")
    before = cur.fetchone()[0]
    print(f"trust_fee_linkages_recovered before: {before:,}")

    if DRY_RUN:
        print()
        print(f"DRY RUN — would insert {len(rows):,} rows in batches of {BATCH}.")
        return

    print()
    print(f"inserting in batches of {BATCH}...")
    sql = """
        INSERT INTO trust_fee_linkages_recovered
            (trust_accession, fee_accession, extracted_raw, match_type,
             name_overlap, name_consistent, date_gap_years,
             trust_date, fee_date, fee_authority, fee_state)
        VALUES %s
        ON CONFLICT (trust_accession, fee_accession) DO NOTHING
    """
    n_done = 0
    for i in range(0, len(rows), BATCH):
        batch = rows[i:i + BATCH]
        psycopg2.extras.execute_values(cur, sql, batch, page_size=BATCH)
        n_done += len(batch)
        if n_done % 10000 == 0 or n_done == len(rows):
            print(f"  ... {n_done:,} processed")
    conn.commit()

    cur.execute("SELECT COUNT(*) FROM trust_fee_linkages_recovered")
    after = cur.fetchone()[0]
    cur.execute("SELECT match_type, COUNT(*) FROM trust_fee_linkages_recovered GROUP BY match_type ORDER BY 2 DESC")
    print()
    print(f"trust_fee_linkages_recovered after:  {after:,}  (+{after-before:,})")
    print(f"match_type distribution in DB:")
    for r in cur.fetchall():
        print(f"  {r[0]:<15s}  {r[1]:,}")


if __name__ == "__main__":
    main()
