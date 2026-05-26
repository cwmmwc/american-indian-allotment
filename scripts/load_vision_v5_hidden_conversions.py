"""
Load v5 vision-extraction hidden fee conversions into trust_fee_linkages_recovered.

Input sources:
  - data/vision_v5_candidate_hidden_with_qwen.csv (merged Sonnet+Qwen comparison)
  - verification_qwen_cross_check/sonnet_only_qwen_dropped/real_stamp/ (folder of
    sonnet_only PDFs the user manually verified as having real fee stamps)

Inclusion rule:
  - All `consensus='both_agree'` rows (188) — Sonnet and Qwen both flagged a
    fee-issued stamp on the page; manual spot-check of the 16 Indian-Fee-Patent
    cases confirmed all have real stamps.
  - The subset of `consensus='sonnet_only'` rows whose PDF was moved into
    real_stamp/ during the verification step (9 rows). The remaining 10
    sonnet_only PDFs are supplemental/reissued-trust oddities — not fee
    conversions — and are excluded.

Each loaded row has:
  trust_accession = the BLM trust patent's accession
  fee_accession   = NULL (the v5 prompt drops fee-number extraction; we know
                    a fee conversion occurred but not its accession)
  trust_date      = the trust patent's signature_date
  source          = 'vision_v5'
  match_type      = 'vision_fee_stamp'
  all other fields = NULL

Requires the schema migration:
    ALTER TABLE trust_fee_linkages_recovered ALTER COLUMN fee_accession DROP NOT NULL;

Usage:
    ./venv/bin/python3 scripts/load_vision_v5_hidden_conversions.py --dry-run
    ./venv/bin/python3 scripts/load_vision_v5_hidden_conversions.py
"""
import argparse
import csv
import os
import sys
import psycopg2
import psycopg2.extras

DB_URL = os.environ.get("DATABASE_URL", "dbname=allotment_research user=cwm6W")

MERGED_CSV     = "data/vision_v5_candidate_hidden_with_qwen.csv"
REAL_STAMP_DIR = "verification_qwen_cross_check/sonnet_only_qwen_dropped/real_stamp"
SOURCE_TAG     = "vision_v5"
MATCH_TYPE     = "vision_fee_stamp"


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    return ap.parse_args()


def to_date(v):
    if v is None or v == "":
        return None
    return v  # ISO YYYY-MM-DD; let Postgres parse


def main():
    args = parse_args()

    if not os.path.exists(MERGED_CSV):
        sys.exit(f"missing {MERGED_CSV}")
    if not os.path.isdir(REAL_STAMP_DIR):
        sys.exit(f"missing {REAL_STAMP_DIR}")

    real_stamp_acc = {
        os.path.splitext(f)[0].split("-")[0]
        for f in os.listdir(REAL_STAMP_DIR)
        if f.endswith(".pdf")
    }
    print(f"sonnet_only PDFs verified as real_stamp: {len(real_stamp_acc)}")
    print(f"  {sorted(real_stamp_acc)}")
    print()

    rows = []
    counts = {"both_agree": 0, "sonnet_only_verified": 0, "sonnet_only_excluded": 0}
    with open(MERGED_CSV) as f:
        for r in csv.DictReader(f):
            acc = r["accession_number"]
            consensus = r["consensus"]
            if consensus == "both_agree":
                counts["both_agree"] += 1
                include = True
            elif consensus == "sonnet_only":
                if acc in real_stamp_acc:
                    counts["sonnet_only_verified"] += 1
                    include = True
                else:
                    counts["sonnet_only_excluded"] += 1
                    include = False
            else:
                include = False
            if include:
                rows.append((
                    acc,                            # trust_accession
                    None,                           # fee_accession (unknown for vision-derived)
                    None,                           # extracted_raw
                    MATCH_TYPE,                     # match_type
                    None,                           # name_overlap
                    None,                           # name_consistent
                    None,                           # date_gap_years
                    to_date(r.get("signature_date")),  # trust_date
                    None,                           # fee_date
                    None,                           # fee_authority
                    r.get("state") or None,         # fee_state — reuse trust state as locality hint
                    SOURCE_TAG,                     # source
                ))

    print(f"row breakdown:")
    print(f"  both_agree (all included):              {counts['both_agree']:>4}")
    print(f"  sonnet_only verified real_stamp:        {counts['sonnet_only_verified']:>4}")
    print(f"  sonnet_only excluded (oddities):        {counts['sonnet_only_excluded']:>4}")
    print(f"  → total to load:                        {len(rows):>4}")
    print()

    conn = psycopg2.connect(DB_URL)
    cur  = conn.cursor()

    cur.execute("SELECT COUNT(*) FROM trust_fee_linkages_recovered WHERE source = %s", (SOURCE_TAG,))
    existing = cur.fetchone()[0]
    print(f"already in trust_fee_linkages_recovered with source='{SOURCE_TAG}': {existing}")

    if existing:
        cur.execute("SELECT trust_accession FROM trust_fee_linkages_recovered WHERE source = %s", (SOURCE_TAG,))
        existing_set = {r[0] for r in cur.fetchall()}
        before = len(rows)
        rows = [r for r in rows if r[0] not in existing_set]
        print(f"  filtered out {before - len(rows)} already-loaded rows; {len(rows)} new to insert")
    print()

    if args.dry_run:
        print(f"DRY RUN — would insert {len(rows):,} rows.")
        if rows:
            print("first 3:")
            for r in rows[:3]:
                print(f"  trust={r[0]}  trust_date={r[7]}  state={r[10]}  source={r[11]}")
        return

    if not rows:
        print("nothing to insert.")
        return

    sql = """
        INSERT INTO trust_fee_linkages_recovered
            (trust_accession, fee_accession, extracted_raw, match_type,
             name_overlap, name_consistent, date_gap_years,
             trust_date, fee_date, fee_authority, fee_state, source)
        VALUES %s
    """
    psycopg2.extras.execute_values(cur, sql, rows, page_size=500)
    conn.commit()

    cur.execute("SELECT COUNT(*) FROM trust_fee_linkages_recovered WHERE source = %s", (SOURCE_TAG,))
    after = cur.fetchone()[0]
    print(f"trust_fee_linkages_recovered (source='{SOURCE_TAG}') after: {after}  (+{after - existing})")
    cur.execute("SELECT COUNT(*) FROM trust_fee_linkages_recovered")
    grand = cur.fetchone()[0]
    print(f"grand total in trust_fee_linkages_recovered: {grand:,}")


if __name__ == "__main__":
    main()
