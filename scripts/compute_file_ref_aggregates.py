"""
Compute and write the materialized aggregate columns on patent_file_references:
  - patent_count        (DISTINCT count of patent_accession across all links)
  - state_list          (comma-separated DISTINCT states from blm_allotment_patents)
  - top_tribe           (most-common preferred_name across linked patents)
  - top_context_label   (most-common context_label across links — IO / misc_document_number / etc.)
  - min_signature_date / max_signature_date (date range of linked patents)

Run after any backfill that adds rows to patent_file_ref_links. Idempotent —
overwrites the columns in place.

Usage:
    ./venv/bin/python3 scripts/compute_file_ref_aggregates.py             # writes
    ./venv/bin/python3 scripts/compute_file_ref_aggregates.py --dry-run   # report sample only
"""
import os
import sys
import psycopg2
import psycopg2.extras

DB_URL = os.environ.get("DATABASE_URL", "dbname=allotment_research user=cwm6W")
DRY_RUN = "--dry-run" in sys.argv


def main():
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    print("Computing aggregates for patent_file_references…")
    # One big UPDATE … FROM with a subquery that does the aggregation per file_ref_id.
    # The subquery joins blm_allotment_patents to get state, preferred_name, signature_date.
    sql = """
    WITH agg AS (
        SELECT
            pfrl.file_ref_id,
            COUNT(DISTINCT pfrl.patent_accession)                                   AS patent_count,
            string_agg(DISTINCT bap.state, ', ' ORDER BY bap.state)                  AS state_list,
            mode() WITHIN GROUP (ORDER BY bap.preferred_name)                        AS top_tribe,
            mode() WITHIN GROUP (ORDER BY pfrl.context_label)                        AS top_context_label,
            MIN(bap.signature_date)::date                                            AS min_signature_date,
            MAX(bap.signature_date)::date                                            AS max_signature_date
        FROM patent_file_ref_links pfrl
        LEFT JOIN blm_allotment_patents bap
            ON bap.accession_number = pfrl.patent_accession
        GROUP BY pfrl.file_ref_id
    )
    UPDATE patent_file_references pfr
       SET patent_count       = agg.patent_count,
           state_list         = agg.state_list,
           top_tribe          = agg.top_tribe,
           top_context_label  = agg.top_context_label,
           min_signature_date = agg.min_signature_date,
           max_signature_date = agg.max_signature_date
      FROM agg
     WHERE pfr.id = agg.file_ref_id
    """

    if DRY_RUN:
        # Just count what would be updated
        cur.execute("""
            SELECT COUNT(DISTINCT file_ref_id) AS n
            FROM patent_file_ref_links
        """)
        n = cur.fetchone()["n"]
        print(f"  would update {n:,} file_ref rows")
        print("DRY RUN — no writes performed.")
        return

    write_cur = conn.cursor()
    write_cur.execute(sql)
    n_updated = write_cur.rowcount
    conn.commit()
    print(f"  updated {n_updated:,} patent_file_references rows")

    # Sample output for verification
    cur.execute("""
        SELECT letter_number, year_raw, patent_count, state_list, top_tribe,
               top_context_label, min_signature_date, max_signature_date, io_labeled
        FROM patent_file_references
        ORDER BY patent_count DESC NULLS LAST
        LIMIT 5
    """)
    print()
    print("--- top 5 by patent_count ---")
    for r in cur.fetchall():
        print(f"  {r['letter_number']}-{r['year_raw']:<5}  n={r['patent_count']:>5}  "
              f"{(r['state_list'] or '-')[:25]:<25}  tribe={(r['top_tribe'] or '-')[:25]:<25}  "
              f"{r['min_signature_date']}→{r['max_signature_date']}  io={r['io_labeled']}")

    cur.close()
    write_cur.close()
    conn.close()


if __name__ == "__main__":
    main()
