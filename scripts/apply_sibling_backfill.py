"""
Apply T1+T2 sibling backfills from data/frn_backfill_candidates.csv into
the derived_tribe_labels table.

Mechanism: the candidate CSV holds (FRN record, non-FRN sibling) pairs. For
each FRN record, pick the single best evidence pair under this priority:

  T1 = sim == 1.0       AND parcel_match=True   (exact-name + same-parcel)
  T2 = sim >= 0.7       AND parcel_match=True   (fuzzy-name + same-parcel)

Skip any FRN record whose siblings disagree on the tribe label (the user
reviews those manually).

Writes nothing to source data (rails_patents, blm_allotment_patents,
tribe_crosswalk are untouched). The derived label is layered on top via
the derived_tribe_labels table and surfaced by the all_patents view.

The script:
  1. Creates the derived_tribe_labels table (idempotent, DROP+CREATE)
  2. Loads candidates CSV and picks best evidence per FRN record
  3. Inserts the T1+T2 rows
  4. Writes the residual (T3+T4+T5 + disagreements) to a review CSV

Runs against the DSN in DATABASE_URL env (defaults to local).

Usage:
    ./venv/bin/python3 scripts/apply_sibling_backfill.py [--dry-run]

    DATABASE_URL="host=127.0.0.1 port=5433 dbname=allotment_research user=appuser password=allotment-app-2026" \\
        ./venv/bin/python3 scripts/apply_sibling_backfill.py
"""
import argparse
import csv
import os
import sys
from collections import defaultdict
import psycopg2
import psycopg2.extras

DB_URL    = os.environ.get("DATABASE_URL", "dbname=allotment_research user=cwm6W")
IN_CSV    = "data/frn_backfill_candidates.csv"
REVIEW_CSV = "data/frn_backfill_for_review.csv"
SOURCE_TAG = "sibling_backfill_v1"

DDL = """
DROP TABLE IF EXISTS derived_tribe_labels;
CREATE TABLE derived_tribe_labels (
    accession_number       text PRIMARY KEY,
    derived_preferred_name text NOT NULL,
    source                 text NOT NULL,
    evidence_accession     text NOT NULL,
    name_similarity        numeric,
    parcel_match           boolean,
    tier                   text NOT NULL,
    applied_at             timestamp DEFAULT now(),
    notes                  text
);
CREATE INDEX idx_dtl_evidence ON derived_tribe_labels (evidence_accession);
"""


def classify(record_pairs):
    """Pick the best evidence pair for one FRN record and return (tier, chosen_pair).

    Returns (None, None) if no T1/T2-qualifying pair exists or siblings disagree.
    """
    sib_labels = {p["sibling_preferred_name"] for p in record_pairs}
    if len(sib_labels) > 1:
        return ("disagreement", None)

    # Best T1 candidate
    t1s = [p for p in record_pairs
           if float(p["name_similarity"]) == 1.0 and p["parcel_match"] == "True"]
    if t1s:
        return ("T1", sorted(t1s, key=lambda p: p["sibling_date"])[0])

    # Best T2 candidate
    t2s = [p for p in record_pairs
           if float(p["name_similarity"]) >= 0.7 and p["parcel_match"] == "True"]
    if t2s:
        # Within T2, prefer higher similarity, then earliest sibling
        return ("T2", sorted(t2s, key=lambda p: (-float(p["name_similarity"]), p["sibling_date"]))[0])

    # T3+
    if any(p["parcel_match"] == "True" for p in record_pairs):
        return ("T3", None)
    if any(float(p["name_similarity"]) == 1.0 for p in record_pairs):
        return ("T4", None)
    return ("T5", None)


def build_rows(by_frn):
    """Yield (tier, frn_accession, chosen_pair) for every distinct FRN record."""
    for frn_acc, pairs in by_frn.items():
        tier, chosen = classify(pairs)
        yield frn_acc, tier, chosen, pairs


def make_notes(p):
    return (f"sibling {p['sibling_accession']} ({p['sibling_doc_code']}, "
            f"{p['sibling_date']}, {p['sibling_authority']}); "
            f"sim={p['name_similarity']} parcel={p['parcel_match']} dir={p['direction']}")


def write_review_csv(by_frn, path):
    """Write the residual (non-applied) FRN records as a review CSV."""
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="") as f:
        w = None
        n_rows = 0
        for frn_acc, tier, chosen, pairs in build_rows(by_frn):
            if tier in ("T1", "T2"):
                continue
            for p in pairs:
                if w is None:
                    cols = ["tier"] + list(p.keys())
                    w = csv.DictWriter(f, fieldnames=cols)
                    w.writeheader()
                row = {"tier": tier}
                row.update(p)
                w.writerow(row)
                n_rows += 1
    print(f"Wrote {n_rows:,} review rows to {path}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    if not os.path.exists(IN_CSV):
        sys.exit(f"Missing {IN_CSV}")
    rows = list(csv.DictReader(open(IN_CSV)))
    by_frn = defaultdict(list)
    for r in rows:
        by_frn[r["frn_accession"]].append(r)
    print(f"Loaded {len(rows):,} candidate pairs across {len(by_frn):,} distinct FRN records.")

    # Tier counts
    from collections import Counter
    tier_counts = Counter()
    apply_rows = []
    for frn_acc, tier, chosen, pairs in build_rows(by_frn):
        tier_counts[tier] += 1
        if tier in ("T1", "T2"):
            apply_rows.append((tier, frn_acc, chosen))
    print()
    print("Tier breakdown:")
    for t in ("T1","T2","T3","T4","T5","disagreement"):
        print(f"  {tier_counts.get(t,0):>4}  {t}")
    print()
    print(f"Will apply: {len(apply_rows):,} FRN records (T1 + T2)")

    if args.dry_run:
        print("\nDRY RUN — sample 5 apply rows:")
        for tier, frn_acc, p in apply_rows[:5]:
            print(f"  [{tier}]  {frn_acc} → derived={p['sibling_preferred_name']!r}")
            print(f"      {make_notes(p)}")
        write_review_csv(by_frn, REVIEW_CSV)
        return

    # Apply for real
    print()
    print(f"Connecting: {DB_URL.split()[0]}...")
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor()
    print("Recreating derived_tribe_labels table...")
    cur.execute(DDL)
    conn.commit()

    print(f"Inserting {len(apply_rows):,} rows...")
    psycopg2.extras.execute_values(cur, """
        INSERT INTO derived_tribe_labels
            (accession_number, derived_preferred_name, source,
             evidence_accession, name_similarity, parcel_match, tier, notes)
        VALUES %s
    """, [
        (frn_acc, p["sibling_preferred_name"], SOURCE_TAG,
         p["sibling_accession"], float(p["name_similarity"]),
         p["parcel_match"] == "True", tier, make_notes(p))
        for tier, frn_acc, p in apply_rows
    ], page_size=500)
    conn.commit()

    cur.execute("SELECT COUNT(*) FROM derived_tribe_labels")
    print(f"derived_tribe_labels row count after insert: {cur.fetchone()[0]:,}")

    cur.execute("""
        SELECT derived_preferred_name, COUNT(*) AS n
        FROM derived_tribe_labels GROUP BY derived_preferred_name ORDER BY n DESC LIMIT 10
    """)
    print()
    print("Top derived tribe labels:")
    for r in cur.fetchall():
        print(f"  {r[1]:>4}  {r[0]}")

    write_review_csv(by_frn, REVIEW_CSV)


if __name__ == "__main__":
    main()
