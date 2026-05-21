"""
Backfill patent_file_references + patent_file_ref_links from BLM's already-structured
CCF reference columns: rails_patents.misc_document_number and rails_patents.document_number.

Scope: ALL rails_patents rows, regardless of signature_date. CCF era is 1907-1975,
but we don't filter on signature_date — we just take every NNNNN-YY-format value
in either column. Refs whose year resolves outside Loren's 1907-1942 window are
still real archival references in CCF series 121B/121C (1943-1975); they're
captured here even though Loren's join can't verify them.

What this does:
  - For each rails_patents row in scope, scan both misc_document_number and
    document_number for NNNNN-YY format values.
  - Upsert each distinct (letter, year_raw) pair into patent_file_references.
  - Upsert one row into patent_file_ref_links per (accession, ref, source) tuple,
    distinguishing the source column via context_label and source_location.
  - Skip values that are not NNNNN-YY format (these are BLM serials, state patent
    codes, short integers, or empty).

Provenance:
  - source_location = 'structured_misc_doc'  →  came from rails_patents.misc_document_number
  - source_location = 'structured_doc_number' → came from rails_patents.document_number
  - context_label = 'misc_document_number' or 'document_number' (the BLM field name)

Idempotent. Re-running won't create duplicates because of UNIQUE constraints on
both tables.

Usage:
    ./venv/bin/python3 scripts/backfill_file_refs_from_structured.py             # local
    ./venv/bin/python3 scripts/backfill_file_refs_from_structured.py --dry-run   # report only
    DATABASE_URL="..." ./venv/bin/python3 scripts/backfill_file_refs_from_structured.py  # remote
"""
import os
import re
import sys
import psycopg2
import psycopg2.extras
from collections import Counter

DB_URL = os.environ.get("DATABASE_URL", "dbname=allotment_research user=cwm6W")
DRY_RUN = "--dry-run" in sys.argv

NNNNN_YY = re.compile(r"^(\d{4,6})-(\d{2})$")

# (column_name, source_location_tag, context_label, io_labeled_value)
# Per audit 2026-05-20: BLM's misc_document_number reliably holds I.O.-labeled
# refs; document_number holds unlabeled. ~99.9% of refs follow this; the 0.1%
# leaky tail surfaces as 'mixed' in the per-ref rollup, which is the honest
# answer for those.
SOURCES = [
    ("misc_document_number", "structured_misc_doc",   "misc_document_number", "yes"),
    ("document_number",      "structured_doc_number", "document_number",      "no"),
]


def four_digit_year(yy: str) -> int:
    """CCF runs 1907-1975; all 2-digit suffixes resolve to 19xx."""
    return 1900 + int(yy)


def main():
    conn = psycopg2.connect(DB_URL)
    read_cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    write_cur = conn.cursor()

    # No date filter: capture all NNNNN-YY refs from both columns across the
    # entire rails_patents table. CCF runs 1907-1975 but we don't pre-filter;
    # the year column resolves whatever YY suffix is found via 1900+yy.
    print("Querying rails_patents (no date filter)...")
    read_cur.execute(
        """
        SELECT accession_number, signature_date, misc_document_number, document_number
        FROM rails_patents
        WHERE
              misc_document_number ~ '^[0-9]{4,6}-[0-9]{2}$'
           OR document_number      ~ '^[0-9]{4,6}-[0-9]{2}$'
        """
    )
    rows = read_cur.fetchall()
    print(f"  {len(rows):,} rows have at least one CCF-format value in scope")

    # Collect distinct refs + extraction tuples
    distinct_refs = set()           # (letter, year_raw)
    extractions   = []              # one per (acc, source) hit
    source_counts = Counter()
    for r in rows:
        for col_name, source_loc, context_label, io_value in SOURCES:
            v = (r.get(col_name) or "").strip()
            if not v:
                continue
            m = NNNNN_YY.match(v)
            if not m:
                continue
            letter, year_raw = m.group(1), m.group(2)
            distinct_refs.add((letter, year_raw))
            extractions.append({
                "acc":          r["accession_number"],
                "letter":       letter,
                "year_raw":     year_raw,
                "source_loc":   source_loc,
                "context_label": context_label,
                "matched_text": v,
                "io_labeled":   io_value,
            })
            source_counts[source_loc] += 1

    print(f"  distinct (letter, year) pairs:     {len(distinct_refs):,}")
    print(f"  total extractions:                 {len(extractions):,}")
    for k, n in source_counts.most_common():
        print(f"    {k:<25s}  {n:>9,}")

    # Existing state for comparison
    write_cur.execute("SELECT COUNT(*) FROM patent_file_references")
    n_refs_before = write_cur.fetchone()[0]
    write_cur.execute("SELECT COUNT(*) FROM patent_file_ref_links")
    n_links_before = write_cur.fetchone()[0]
    print()
    print(f"Existing patent_file_references rows: {n_refs_before:,}")
    print(f"Existing patent_file_ref_links rows:  {n_links_before:,}")

    if DRY_RUN:
        print()
        print("DRY RUN -- no writes performed.")
        return

    print()
    print("Writing patent_file_references (upsert on letter+year_raw)...")
    for letter, year_raw in distinct_refs:
        write_cur.execute(
            """
            INSERT INTO patent_file_references (letter_number, year, year_raw)
            VALUES (%s, %s, %s)
            ON CONFLICT (letter_number, year_raw) DO NOTHING
            """,
            (letter, four_digit_year(year_raw), year_raw),
        )
    conn.commit()

    # Map (letter, year_raw) -> id
    write_cur.execute("SELECT id, letter_number, year_raw FROM patent_file_references")
    ref_id_map = {(r[1], r[2]): r[0] for r in write_cur.fetchall()}
    print(f"  patent_file_references now: {len(ref_id_map):,} rows")

    print("Writing patent_file_ref_links...")
    inserted = 0
    skipped_dupes = 0
    for ext in extractions:
        ref_id = ref_id_map[(ext["letter"], ext["year_raw"])]
        write_cur.execute(
            """
            INSERT INTO patent_file_ref_links
                (patent_accession, file_ref_id, context_label,
                 source_location, source_table, matched_text, io_labeled)
            VALUES (%s, %s, %s, %s, 'rails_patents', %s, %s)
            ON CONFLICT (patent_accession, file_ref_id, context_label, source_location)
            DO NOTHING
            """,
            (ext["acc"], ref_id, ext["context_label"], ext["source_loc"],
             ext["matched_text"], ext["io_labeled"]),
        )
        if write_cur.rowcount:
            inserted += 1
        else:
            skipped_dupes += 1
    conn.commit()

    print(f"  inserted: {inserted:,}")
    print(f"  skipped (already present): {skipped_dupes:,}")

    write_cur.execute("SELECT COUNT(*) FROM patent_file_references")
    n_refs_after = write_cur.fetchone()[0]
    write_cur.execute("SELECT COUNT(*) FROM patent_file_ref_links")
    n_links_after = write_cur.fetchone()[0]
    write_cur.execute("SELECT COUNT(DISTINCT patent_accession) FROM patent_file_ref_links")
    n_patents = write_cur.fetchone()[0]
    print()
    print("=== Final state ===")
    print(f"  patent_file_references:   {n_refs_before:>7,} -> {n_refs_after:>7,}  ({n_refs_after - n_refs_before:+,})")
    print(f"  patent_file_ref_links:    {n_links_before:>7,} -> {n_links_after:>7,}  ({n_links_after - n_links_before:+,})")
    print(f"  distinct patents w/ >=1 ref:                       {n_patents:>7,}")

    write_cur.close(); read_cur.close(); conn.close()


if __name__ == "__main__":
    main()
