"""
Load a validated-linkages CSV into trust_fee_linkages_recovered.

Uses psycopg2.extras.execute_values to batch-insert 1,000 rows per round-trip
so the load completes in seconds locally and in minutes against Cloud SQL.
Idempotent: re-running skips rows that already exist (ON CONFLICT DO NOTHING
on the unique (trust_accession, fee_accession) pair). Self-referential rows
(trust_accession == fee_accession) are filtered out before insertion; the DB
CHECK constraint also rejects them at the database level.

Usage:
    # default: load data/linkage_candidates.csv with source=remarks_regex_v2
    ./venv/bin/python3 scripts/load_trust_fee_linkages_recovered.py

    # truncate the table first (use after a regex / matcher rerun)
    ./venv/bin/python3 scripts/load_trust_fee_linkages_recovered.py --truncate

    # parcel-matcher output with its own source tag
    ./venv/bin/python3 scripts/load_trust_fee_linkages_recovered.py \\
        --csv data/parcel_match_candidates.csv --source parcel_match_v1

    # dry run (no writes)
    ./venv/bin/python3 scripts/load_trust_fee_linkages_recovered.py --dry-run
"""
import argparse
import os
import sys
import csv
import psycopg2
import psycopg2.extras
from collections import Counter

DB_URL = os.environ.get("DATABASE_URL", "dbname=allotment_research user=cwm6W")
BATCH  = 1000


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv",      default="data/linkage_candidates.csv")
    ap.add_argument("--source",   default="remarks_regex_v2")
    ap.add_argument("--truncate", action="store_true",
                    help="Truncate trust_fee_linkages_recovered before loading.")
    ap.add_argument("--dry-run",  action="store_true")
    return ap.parse_args()


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
    args = parse_args()

    if not os.path.exists(args.csv):
        sys.exit(f"missing {args.csv}")

    rows = []
    types = Counter()
    n_skipped_self_ref = 0
    with open(args.csv) as f:
        for r in csv.DictReader(f):
            if r["trust_accession"] == r["fee_accession"]:
                n_skipped_self_ref += 1
                continue
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
                args.source,
            ))
            types[r.get("match_type", "?")] += 1
    print(f"loaded {len(rows):,} candidate rows from {args.csv}")
    if n_skipped_self_ref:
        print(f"  (skipped {n_skipped_self_ref} self-references where trust_accession == fee_accession)")
    print(f"match_type breakdown: {dict(types.most_common())}")
    print(f"source tag: {args.source}")
    print()

    conn = psycopg2.connect(DB_URL)
    cur  = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM trust_fee_linkages_recovered")
    before = cur.fetchone()[0]
    print(f"trust_fee_linkages_recovered before: {before:,}")

    if args.dry_run:
        print()
        print(f"DRY RUN — would {'truncate then ' if args.truncate else ''}insert {len(rows):,} rows in batches of {BATCH}.")
        return

    if args.truncate:
        print(f"  TRUNCATE TABLE trust_fee_linkages_recovered (existing {before:,} rows will be dropped)")
        cur.execute("TRUNCATE TABLE trust_fee_linkages_recovered RESTART IDENTITY")

    print()
    print(f"inserting in batches of {BATCH}...")
    sql = """
        INSERT INTO trust_fee_linkages_recovered
            (trust_accession, fee_accession, extracted_raw, match_type,
             name_overlap, name_consistent, date_gap_years,
             trust_date, fee_date, fee_authority, fee_state, source)
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
    cur.execute("""
        SELECT source, match_type, COUNT(*) AS n
        FROM trust_fee_linkages_recovered
        GROUP BY source, match_type ORDER BY source, n DESC
    """)
    print()
    delta = after - before
    sign = '+' if delta >= 0 else ''
    print(f"trust_fee_linkages_recovered after:  {after:,}  ({sign}{delta:,})")
    print(f"by source × match_type:")
    for r in cur.fetchall():
        print(f"  {r[0]:<20s}  {r[1]:<15s}  {r[2]:,}")


if __name__ == "__main__":
    main()
