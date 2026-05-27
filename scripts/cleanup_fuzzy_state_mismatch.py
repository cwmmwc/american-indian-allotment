"""
Delete trust_fee_linkages_recovered rows where the match is fuzzy AND the
trust state differs from the fee state.

These rows are likely false positives created by the fuzzy validator path
when the truly-correct fee accession isn't in the catalog (e.g., the SER
600K gap). With no exact match available, the validator's edit-distance +
shared-name-token logic substitutes some other patent that shares a name
token by chance. State mismatch is a strong signal these aren't real
linkages — trust patents in SD don't get fee-converted to CA in normal
allotment-to-fee flows.

Conservative: only deletes when both states are populated AND differ.
Fuzzy rows where states match (or one is unknown) are left alone for
separate review.

Idempotent (subsequent runs find no more state-mismatch fuzzy rows).

Usage:
    ./venv/bin/python3 scripts/cleanup_fuzzy_state_mismatch.py --dry-run
    ./venv/bin/python3 scripts/cleanup_fuzzy_state_mismatch.py
    DATABASE_URL="host=127.0.0.1 port=5433 dbname=allotment_research user=appuser password=allotment-app-2026" \\
        ./venv/bin/python3 scripts/cleanup_fuzzy_state_mismatch.py
"""
import argparse
import os
import psycopg2

DB_URL = os.environ.get("DATABASE_URL", "dbname=allotment_research user=cwm6W")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    conn = psycopg2.connect(DB_URL)
    cur  = conn.cursor()

    # Identify the rows: fuzzy match type + state mismatch.
    # Trust state comes via JOIN to all_patents (which exposes either
    # blm_allotment_patents.state for mappable or rails_patents.state for un-mappable).
    select_sql = """
        SELECT tflr.id, tflr.trust_accession, tp.state AS trust_state,
               tflr.fee_accession, tflr.fee_state, tflr.match_type, tflr.extracted_raw
        FROM trust_fee_linkages_recovered tflr
        JOIN all_patents tp ON tp.accession_number = tflr.trust_accession
        WHERE tflr.match_type LIKE 'fuzzy%%'
          AND tflr.fee_state IS NOT NULL
          AND tp.state IS NOT NULL
          AND tp.state <> tflr.fee_state
    """
    cur.execute(select_sql)
    rows = cur.fetchall()
    print(f"Identified {len(rows)} fuzzy linkage rows with state mismatch.")

    # Breakdown by match_type
    from collections import Counter
    by_type = Counter(r[5] for r in rows)
    for mt, n in by_type.most_common():
        print(f"  {n:>4}  match_type={mt}")
    print()

    if args.dry_run:
        print("DRY RUN — would DELETE these rows.")
        print()
        print("First 5 samples:")
        for r in rows[:5]:
            print(f"  id={r[0]}  trust={r[1]}({r[2]})  fee={r[3]}({r[4]})  extracted_raw={r[6]!r}  match={r[5]}")
        return

    if not rows:
        print("Nothing to delete.")
        return

    ids = [r[0] for r in rows]
    cur.execute("DELETE FROM trust_fee_linkages_recovered WHERE id = ANY(%s)", (ids,))
    deleted = cur.rowcount
    conn.commit()
    print(f"DELETEd {deleted} rows.")

    # Final tally
    cur.execute("SELECT match_type, COUNT(*) FROM trust_fee_linkages_recovered GROUP BY match_type ORDER BY 2 DESC")
    print()
    print("trust_fee_linkages_recovered match_type distribution after cleanup:")
    for mt, n in cur.fetchall():
        print(f"  {mt or '(null)':<25s}  {n:>7,}")


if __name__ == "__main__":
    main()
