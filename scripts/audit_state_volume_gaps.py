"""
Audit State Land Patent volumes in rails_patents for completeness gaps.

A State Land Patent accession looks like `SD2610__.247` — state code +
volume number + double underscore + dot + patent number within the volume.
Each volume nominally runs from .001 to .500 (or thereabouts). A gap is
detected when COUNT(rows in DB) is meaningfully smaller than MAX(pnum)
within the volume — i.e. patent numbers are missing in the middle or at
the top of the range.

This audit finds every gappy state volume, by state, with estimated
missing-record counts. Output drives the re-scrape work for item 11 in
the open-threads memory.

Usage:
    ./venv/bin/python3 scripts/audit_state_volume_gaps.py
    ./venv/bin/python3 scripts/audit_state_volume_gaps.py --csv data/state_volume_gaps.csv
"""
import argparse
import csv
import os
import sys
import psycopg2
import psycopg2.extras

DB_URL = os.environ.get("DATABASE_URL", "dbname=allotment_research user=cwm6W")
MIN_VOL_SIZE = 100         # ignore volumes with max patent < 100 (probably tiny)
GAP_THRESHOLD = 50         # count a volume as gappy if (max-count) >= this


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", help="write the gappy-volumes list to this CSV")
    args = ap.parse_args()

    conn = psycopg2.connect(DB_URL)
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    cur.execute("""
        WITH state_vol AS (
          SELECT
            substring(accession_number FROM '^([A-Z]{2}[0-9]+__)')        AS volume,
            substring(accession_number FROM '^([A-Z]{2})')                AS state,
            NULLIF(substring(accession_number FROM '\\.([0-9]+)$'), '')::int AS pnum
          FROM rails_patents
          WHERE document_class = 'State Land Patent'
            AND accession_number ~ '^[A-Z]{2}[0-9]+__\\.[0-9]+$'
        )
        SELECT
          volume,
          state,
          COUNT(*)        AS rows_in_db,
          MAX(pnum)       AS max_pnum,
          MAX(pnum) - COUNT(*) AS gap,
          ROUND(100.0 * COUNT(*) / NULLIF(MAX(pnum),0), 1) AS completeness_pct
        FROM state_vol
        WHERE volume IS NOT NULL AND pnum IS NOT NULL
        GROUP BY volume, state
        HAVING MAX(pnum) >= %s
        ORDER BY (MAX(pnum) - COUNT(*)) DESC
    """, (MIN_VOL_SIZE,))
    rows = cur.fetchall()

    gappy = [r for r in rows if r["gap"] >= GAP_THRESHOLD]
    complete = [r for r in rows if r["gap"] < GAP_THRESHOLD]

    print(f"=== State Land Patent volume audit ===")
    print(f"  Total volumes (max_pnum >= {MIN_VOL_SIZE}):  {len(rows)}")
    print(f"  Complete (gap < {GAP_THRESHOLD}):              {len(complete)}")
    print(f"  Gappy (gap >= {GAP_THRESHOLD}):                {len(gappy)}")
    print(f"  Estimated missing records (gappy only): {sum(r['gap'] for r in gappy):,}")
    print()

    # By-state rollup
    print(f"=== Gappy volumes by state ===")
    by_state = {}
    for r in gappy:
        s = r["state"]
        if s not in by_state:
            by_state[s] = {"n_gappy": 0, "missing": 0}
        by_state[s]["n_gappy"] += 1
        by_state[s]["missing"] += r["gap"]
    for s in sorted(by_state, key=lambda k: -by_state[k]["missing"]):
        d = by_state[s]
        print(f"  {s}  {d['n_gappy']:>3} gappy volumes, ~{d['missing']:>5,} missing records")
    print()

    # Top-30 gappy volumes
    print(f"=== Top 30 gappy volumes (by absolute gap) ===")
    print(f"  {'volume':<14s}  {'in_db':>6s}  {'max':>5s}  {'gap':>5s}  {'pct':>6s}")
    for r in gappy[:30]:
        print(f"  {r['volume']:<14s}  {r['rows_in_db']:>6}  {r['max_pnum']:>5}  {r['gap']:>5}  {r['completeness_pct']:>5}%")
    print()

    if args.csv:
        os.makedirs(os.path.dirname(args.csv) or ".", exist_ok=True)
        with open(args.csv, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["volume", "state", "rows_in_db", "max_pnum", "gap", "completeness_pct"])
            for r in gappy:
                w.writerow([r["volume"], r["state"], r["rows_in_db"], r["max_pnum"], r["gap"], r["completeness_pct"]])
        print(f"Wrote {len(gappy)} gappy volumes to {args.csv}")


if __name__ == "__main__":
    main()
