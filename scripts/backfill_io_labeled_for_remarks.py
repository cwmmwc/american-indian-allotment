"""
Backfill patent_file_ref_links.io_labeled for the existing remarks-grep links
(the 2,373 rows from `source_location='remarks'`) based on context_label.

Labeling rules (per audit + memory: BLM transcribers used IO / BIA / DOCUMENT
labels interchangeably for the same kind of refs — the label is operator
convention, not document truth):
  - context_label contains 'IO' (case-insensitive) → io_labeled='yes'
    Transcriber explicitly chose the IO label, which IS positive evidence
    that the original document said I.O.
  - context_label is in {BIA, ADDITIONAL BIA, DOCUMENT, ADDITIONAL DOCUMENT}
    → io_labeled='unknown'
    Transcriber chose a different label. Per memory: BIA / DOCUMENT and IO
    labels appear interchangeably across the same files. Don't infer
    "not I.O." from the absence of an IO label in remarks — that's a
    stronger claim than the evidence supports.

Read/write on patent_file_ref_links. Idempotent: only updates rows where
io_labeled IS NULL and source_location='remarks'.

Usage:
    ./venv/bin/python3 scripts/backfill_io_labeled_for_remarks.py             # writes
    ./venv/bin/python3 scripts/backfill_io_labeled_for_remarks.py --dry-run   # report only
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

    cur.execute("""
        SELECT id, context_label
        FROM patent_file_ref_links
        WHERE source_location = 'remarks' AND io_labeled IS NULL
    """)
    rows = cur.fetchall()
    print(f"Existing remarks-grep links with io_labeled NULL: {len(rows):,}")

    plan = {"yes": 0, "unknown": 0, "other": 0}
    updates = []
    for r in rows:
        lab = (r["context_label"] or "").upper()
        if "IO" in lab.replace(".", "").replace(" ", ""):
            verdict = "yes"
        elif "BIA" in lab or "DOCUMENT" in lab:
            verdict = "unknown"
        else:
            verdict = "other"  # shouldn't happen given the existing label vocab
        plan[verdict] += 1
        updates.append((r["id"], verdict))

    print(f"  proposed yes:     {plan['yes']:,}")
    print(f"  proposed unknown: {plan['unknown']:,}")
    print(f"  proposed other:   {plan['other']:,}  (unrecognized labels — leave NULL)")

    if DRY_RUN:
        print()
        print("DRY RUN — no writes performed.")
        return

    print()
    print("Applying updates...")
    write_cur = conn.cursor()
    n_updated = 0
    for rid, verdict in updates:
        if verdict == "other":
            continue  # leave NULL
        write_cur.execute(
            "UPDATE patent_file_ref_links SET io_labeled = %s WHERE id = %s",
            (verdict, rid),
        )
        n_updated += write_cur.rowcount
    conn.commit()
    print(f"  updated rows: {n_updated:,}")

    # Verify
    write_cur.execute("""
        SELECT io_labeled, COUNT(*)
        FROM patent_file_ref_links
        WHERE source_location = 'remarks'
        GROUP BY io_labeled ORDER BY 2 DESC
    """)
    print()
    print("Final state of remarks-grep links by io_labeled:")
    for r in write_cur.fetchall():
        print(f"  {(r[0] or 'NULL'):<10}  {r[1]:,}")


if __name__ == "__main__":
    main()
