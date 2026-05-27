"""
Phase 3a: insert trust→fee linkage rows for cases where the remarks
contain a real-looking fee accession but no fee patent record exists in
our catalog (because BLM doesn't have it either — verified by sampling
several SER 600K accessions and finding all return "A document does not
exist" on glorecords.blm.gov).

Source: data/linkage_unmatched.csv (produced by validate_remarks_extractions.py).

Each kept row creates a trust_fee_linkages_recovered entry:
  source        = 'remarks_regex_v2'  (unchanged — these came from that pass)
  match_type    = 'remarks_only_no_catalog'  (new category, flags that the
                  fee patent is named in the trust patent's transcribed
                  remarks but no catalog record exists)
  fee_accession = the extracted accession from remarks
  fee_date/fee_authority/fee_state = NULL  (no catalog record to read from)

Filter: only insert rows where extracted_raw is a pure-digit string of 6+
characters (real-looking accession). The other ~2,246 unmatched rows are
extraction noise (short numbers like '08' '40', date fragments like
'3-2-1933', file-ref-shaped strings like '40815-08') and shouldn't be
treated as fee-patent references.

Idempotent — UNIQUE (trust_accession, fee_accession) skips re-inserts.

Usage:
    ./venv/bin/python3 scripts/load_remarks_only_linkages.py --dry-run
    ./venv/bin/python3 scripts/load_remarks_only_linkages.py
    DATABASE_URL="host=127.0.0.1 port=5433 dbname=allotment_research user=appuser password=allotment-app-2026" \\
        ./venv/bin/python3 scripts/load_remarks_only_linkages.py
"""
import argparse
import csv
import os
import re
import sys
import psycopg2
import psycopg2.extras
from collections import Counter

DB_URL = os.environ.get("DATABASE_URL", "dbname=allotment_research user=cwm6W")
CSV    = "data/linkage_unmatched.csv"

REAL_ACCESSION = re.compile(r'^\d{6,}$')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not os.path.exists(CSV):
        sys.exit(f"missing {CSV} — run scripts/validate_remarks_extractions.py first")

    rows = []
    skipped = Counter()
    with open(CSV) as f:
        for r in csv.DictReader(f):
            extracted = (r.get("extracted_raw") or "").strip()
            if not REAL_ACCESSION.match(extracted):
                skipped["non_real_accession"] += 1
                continue
            trust_acc = r.get("trust_accession")
            if not trust_acc:
                skipped["no_trust_acc"] += 1
                continue
            rows.append({
                "trust_accession": trust_acc,
                "fee_accession":   extracted,
                "extracted_raw":   extracted,
                "trust_date":      r.get("trust_date") or None,
            })

    print(f"Loaded {len(rows)} candidate linkages from {CSV}")
    if skipped:
        print("Skipped (not real-accession-shaped):")
        for k, n in skipped.most_common():
            print(f"  {k:<25s}  {n:>5}")
    print()

    # De-dupe input by (trust, fee) — the CSV may have repeats across multiple
    # remarks variants pointing to the same fee
    seen = set()
    deduped = []
    for r in rows:
        key = (r["trust_accession"], r["fee_accession"])
        if key in seen:
            continue
        seen.add(key)
        deduped.append(r)
    if len(deduped) != len(rows):
        print(f"De-duped CSV rows: {len(rows)} → {len(deduped)} distinct (trust,fee) pairs")
        print()

    conn = psycopg2.connect(DB_URL)
    cur  = conn.cursor()

    # Snapshot counts before
    cur.execute("SELECT COUNT(*) FROM trust_fee_linkages_recovered")
    before_total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM trust_fee_linkages_recovered WHERE match_type = 'remarks_only_no_catalog'")
    before_marked = cur.fetchone()[0]
    print(f"Before: trust_fee_linkages_recovered total = {before_total:,}")
    print(f"        remarks_only_no_catalog rows       = {before_marked}")
    print()

    if args.dry_run:
        print(f"DRY RUN — would attempt to insert {len(deduped)} rows with:")
        print(f"  source = 'remarks_regex_v2'")
        print(f"  match_type = 'remarks_only_no_catalog'")
        print(f"  (existing (trust,fee) pairs skipped by ON CONFLICT DO NOTHING)")
        print(f"  first 3 examples:")
        for r in deduped[:3]:
            print(f"    trust={r['trust_accession']}  fee={r['fee_accession']}  trust_date={r['trust_date']}")
        return

    values = [
        (r["trust_accession"], r["fee_accession"], r["extracted_raw"],
         "remarks_only_no_catalog", r["trust_date"], "remarks_regex_v2")
        for r in deduped
    ]
    sql = """
        INSERT INTO trust_fee_linkages_recovered
            (trust_accession, fee_accession, extracted_raw, match_type,
             trust_date, source)
        VALUES %s
        ON CONFLICT (trust_accession, fee_accession) DO NOTHING
    """
    psycopg2.extras.execute_values(cur, sql, values, page_size=500)
    conn.commit()

    # Verify
    cur.execute("SELECT COUNT(*) FROM trust_fee_linkages_recovered")
    after_total = cur.fetchone()[0]
    cur.execute("SELECT COUNT(*) FROM trust_fee_linkages_recovered WHERE match_type = 'remarks_only_no_catalog'")
    after_marked = cur.fetchone()[0]
    print(f"After:  trust_fee_linkages_recovered total = {after_total:,}  (+{after_total - before_total:,})")
    print(f"        remarks_only_no_catalog rows       = {after_marked}  (+{after_marked - before_marked})")
    skipped_dupe = len(deduped) - (after_total - before_total)
    if skipped_dupe > 0:
        print(f"        skipped as duplicates of existing (trust,fee) pairs: {skipped_dupe}")


if __name__ == "__main__":
    main()
