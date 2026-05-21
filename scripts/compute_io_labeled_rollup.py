"""
Compute the per-ref io_labeled rollup on patent_file_references, aggregating
from the per-link io_labeled values on patent_file_ref_links.

Rollup rules:
  has_yes      = any link with io_labeled='yes'
  has_no       = any link with io_labeled='no'
  has_unknown  = any link with io_labeled='unknown'

  has_yes AND has_no       → 'mixed'   (real labeling inconsistency across docs)
  has_yes AND NOT has_no   → 'yes'
  has_no  AND NOT has_yes  → 'no'
  only 'unknown'           → 'unknown'
  no links at all          → leave NULL (shouldn't happen if a ref exists)

The 'mixed' refs are the 0.1% leaky tail that the audit identified. Per audit:
that tail has both BLM data-entry errors AND real document-level labeling
variation. The 'mixed' label honestly surfaces the inconsistency for manual
or NARA-card review without pretending we know the cause.

Read/write on patent_file_references. Idempotent.

Usage:
    ./venv/bin/python3 scripts/compute_io_labeled_rollup.py             # writes
    ./venv/bin/python3 scripts/compute_io_labeled_rollup.py --dry-run   # report only
"""
import os
import sys
import psycopg2
import psycopg2.extras
from collections import Counter

DB_URL = os.environ.get("DATABASE_URL", "dbname=allotment_research user=cwm6W")
DRY_RUN = "--dry-run" in sys.argv


def main():
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # For each ref, aggregate the io_labeled values across its links
    cur.execute("""
        SELECT
            pfr.id,
            BOOL_OR(pfrl.io_labeled = 'yes')     AS has_yes,
            BOOL_OR(pfrl.io_labeled = 'no')      AS has_no,
            BOOL_OR(pfrl.io_labeled = 'unknown') AS has_unknown,
            COUNT(pfrl.id)                        AS n_links
        FROM patent_file_references pfr
        LEFT JOIN patent_file_ref_links pfrl ON pfrl.file_ref_id = pfr.id
        GROUP BY pfr.id
    """)
    rows = cur.fetchall()

    counts = Counter()
    updates = []
    for r in rows:
        if r["n_links"] == 0:
            verdict = None
        elif r["has_yes"] and r["has_no"]:
            verdict = "mixed"
        elif r["has_yes"]:
            verdict = "yes"
        elif r["has_no"]:
            verdict = "no"
        elif r["has_unknown"]:
            verdict = "unknown"
        else:
            verdict = None
        counts[verdict] += 1
        updates.append((r["id"], verdict))

    print(f"patent_file_references rollup verdicts:")
    for v, n in sorted(counts.items(), key=lambda kv: -kv[1]):
        print(f"  {(v or 'NULL'):<10}  {n:,}")

    if DRY_RUN:
        print()
        print("DRY RUN — no writes performed.")
        return

    print()
    print("Writing rollup to patent_file_references.io_labeled...")
    write_cur = conn.cursor()
    n_updated = 0
    for rid, verdict in updates:
        write_cur.execute(
            "UPDATE patent_file_references SET io_labeled = %s WHERE id = %s",
            (verdict, rid),
        )
        n_updated += write_cur.rowcount
    conn.commit()
    print(f"  updated rows: {n_updated:,}")


if __name__ == "__main__":
    main()
