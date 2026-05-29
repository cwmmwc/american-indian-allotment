"""
One-off candidate finder: every FRN record in all_patents that has a same-state
+ same-allotment-number sibling whose preferred_name is a specific tribe (not
FRN). Name matching is fuzzy (pg_trgm strict_word_similarity ≥ 0.65) so that
spelling drift like DESHENQUETTE/DESHEUQUETTE, APEYOHA-TANKA/TAHKA, PAHA
JATA/PAHAJATA still surfaces the sibling.

Writes CSV with all evidence columns. Nothing is written back to the DB.
This is a research-review artifact, not a backfill operation.

Output: data/frn_backfill_candidates.csv

Each row is one (FRN record, non-FRN sibling) pair. A FRN record with multiple
qualifying siblings appears in multiple rows. The user reads the CSV and
decides per-row whether the sibling is good evidence for backfilling the
FRN row's tribe label.

Columns:
  frn_*       : FRN record's identifiers, doc class, date, authority, parcel
  sibling_*   : sibling record's identifiers, tribe label, doc class, date,
                authority, parcel
  name_similarity : strict_word_similarity score (0–1)
  parcel_match    : yes/no — do the two records sit on the same T/R/sec?
  direction       : 'frn_earlier' if FRN signature_date < sibling's,
                    'frn_later'   if FRN > sibling's, 'same' if equal.
                    Most cases are 'frn_later' (later fee patent lost the
                    band identification that the earlier trust carried).

Usage:
    ./venv/bin/python3 scripts/find_frn_backfill_candidates.py
"""
import csv
import os
import psycopg2
import psycopg2.extras

DB_URL = os.environ.get("DATABASE_URL", "dbname=allotment_research user=cwm6W")
OUT_CSV = "data/frn_backfill_candidates.csv"
THRESHOLD = 0.65


SQL = f"""
SET pg_trgm.strict_word_similarity_threshold = {THRESHOLD};

WITH frn_records AS (
    SELECT accession_number, full_name, state, county,
           indian_allotment_number, preferred_name, document_code,
           signature_date::date AS signature_date, authority,
           township_number, range_number, section_number
    FROM all_patents
    WHERE preferred_name ILIKE 'Frn%'
      AND indian_allotment_number IS NOT NULL
      AND TRIM(indian_allotment_number) <> ''
      AND full_name IS NOT NULL
      AND TRIM(full_name) <> ''
      AND state IS NOT NULL
),
pairs AS (
    SELECT
        frn.accession_number    AS frn_accession,
        frn.full_name           AS frn_full_name,
        frn.state               AS state,
        frn.county              AS frn_county,
        frn.indian_allotment_number AS allotment_number,
        frn.preferred_name      AS frn_preferred_name,
        frn.document_code       AS frn_doc_code,
        frn.signature_date      AS frn_date,
        frn.authority           AS frn_authority,
        COALESCE('T'||frn.township_number||'R'||frn.range_number||'s'||frn.section_number, '') AS frn_parcel,
        sib.accession_number    AS sibling_accession,
        sib.full_name           AS sibling_full_name,
        sib.preferred_name      AS sibling_preferred_name,
        sib.document_code       AS sibling_doc_code,
        sib.signature_date::date AS sibling_date,
        sib.authority           AS sibling_authority,
        COALESCE('T'||sib.township_number||'R'||sib.range_number||'s'||sib.section_number, '') AS sibling_parcel,
        strict_word_similarity(LOWER(frn.full_name), sib.full_name) AS name_similarity,
        (frn.township_number IS NOT NULL
         AND frn.township_number = sib.township_number
         AND frn.range_number    = sib.range_number
         AND frn.section_number  = sib.section_number) AS parcel_match,
        CASE
          WHEN frn.signature_date::date < sib.signature_date::date THEN 'frn_earlier'
          WHEN frn.signature_date::date > sib.signature_date::date THEN 'frn_later'
          ELSE 'same'
        END AS direction
    FROM frn_records frn
    JOIN all_patents sib
      ON sib.state = frn.state
     AND sib.indian_allotment_number = frn.indian_allotment_number
     AND sib.accession_number <> frn.accession_number
     AND sib.preferred_name IS NOT NULL
     AND sib.preferred_name NOT ILIKE 'Frn%'
     AND sib.full_name IS NOT NULL
     AND LOWER(frn.full_name) <<% sib.full_name
)
SELECT * FROM pairs
ORDER BY state, allotment_number, frn_full_name, frn_date, sibling_date;
"""


def main():
    os.makedirs(os.path.dirname(OUT_CSV), exist_ok=True)
    conn = psycopg2.connect(DB_URL)
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute(SQL)
    rows = cur.fetchall()
    print(f"Pairs found: {len(rows):,}")

    if not rows:
        print("Nothing to write.")
        return

    distinct_frn  = {r["frn_accession"]    for r in rows}
    distinct_sibs = {r["sibling_accession"] for r in rows}
    print(f"Distinct FRN records with at least one sibling:    {len(distinct_frn):,}")
    print(f"Distinct sibling specific-tribe records involved:  {len(distinct_sibs):,}")
    print()

    # Tribe-label distribution on the sibling side
    from collections import Counter
    sib_tribes = Counter(r["sibling_preferred_name"] for r in rows)
    print("Top sibling tribe labels (counts are pair-rows, not distinct FRN):")
    for tribe, n in sib_tribes.most_common(20):
        print(f"  {n:>6}  {tribe}")
    print()

    # Direction
    dir_counts = Counter(r["direction"] for r in rows)
    print("Direction (frn date vs sibling date):")
    for d, n in dir_counts.most_common():
        print(f"  {n:>6}  {d}")
    print()

    # Parcel match
    pm_counts = Counter(r["parcel_match"] for r in rows)
    print("Parcel match (same T/R/sec):")
    for v, n in pm_counts.most_common():
        print(f"  {n:>6}  {v}")
    print()

    cols = list(rows[0].keys())
    with open(OUT_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        for r in rows:
            row = {k: v for k, v in r.items()}
            # Format dates and floats
            if row.get("frn_date"):     row["frn_date"]     = str(row["frn_date"])
            if row.get("sibling_date"): row["sibling_date"] = str(row["sibling_date"])
            if row.get("name_similarity") is not None:
                row["name_similarity"] = f"{float(row['name_similarity']):.3f}"
            w.writerow(row)
    print(f"Wrote {len(rows):,} rows to {OUT_CSV}")


if __name__ == "__main__":
    main()
