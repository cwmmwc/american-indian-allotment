"""
Generalized version of fix_sd2610_authority.py: clean up empty-shell rows,
populate the authority column, and refresh the all_patents view for any
re-scraped state volume.

Identical logic to fix_sd2610_authority.py but parameterized — pass
--volume <prefix> (e.g. NE1360__) and the script derives CSV path and
verification queries from it. The view-recreation step assumes the
all_patents view's un-mappable branch already uses
COALESCE(rp.authority, rp.document_class) (landed in the SD2610 cycle).
If you re-run it on a fresh clone, that's still in
sql/update_all_patents_view_with_authority.sql.

Idempotent. Designed to be run once per volume per environment (local +
Cloud SQL).

Usage:
    ./venv/bin/python3 scripts/fix_volume_authority.py --volume NE1360__
    DATABASE_URL="host=127.0.0.1 port=5433 dbname=allotment_research user=appuser password=allotment-app-2026" \\
        ./venv/bin/python3 scripts/fix_volume_authority.py --volume NE1360__
"""
import argparse
import csv
import os
import re
import sys
import psycopg2
import psycopg2.extras

DB_URL = os.environ.get("DATABASE_URL", "dbname=allotment_research user=cwm6W")


def parse_authority(raw):
    """BLM serves authority as 'DATE: NAME (STATUTE)'. Extract NAME."""
    if not raw:
        return None
    m = re.search(r':\s*(.+?)\s*\(', raw)
    return m.group(1).strip() if m else None


VIEW_SQL = """
CREATE OR REPLACE VIEW all_patents AS
 SELECT rp.id,
    bap.objectid,
    bap.accession_number,
    COALESCE(bap.full_name, rp.full_name) AS full_name,
    bap.preferred_name,
    rp.state,
    rp.document_class,
    rp.indian_allotment_number,
    bap.authority,
    rp.signature_date,
    bap.forced_fee,
    bap.cancelled_doc,
    rp.total_acres,
    rp.remarks,
    rp.document_code,
    bap.county,
    bap.meridian,
    bap.township_number,
    bap.township_direction,
    bap.range_number,
    bap.range_direction,
    bap.section_number,
    bap.aliquot_parts,
    bap.centroid_lat,
    bap.centroid_lon,
    true AS has_plss_geometry
   FROM rails_patents rp
     JOIN blm_allotment_patents bap ON rp.accession_number = bap.accession_number
UNION ALL
 SELECT rp.id,
    NULL::integer AS objectid,
    rp.accession_number,
    rp.full_name,
    COALESCE(tnm.preferred_name, rp.glo_tribe_name) AS preferred_name,
    rp.state,
    rp.document_class,
    rp.indian_allotment_number,
    COALESCE(rp.authority, rp.document_class) AS authority,
    rp.signature_date,
    'False'::text AS forced_fee,
    rp.cancelled_doc::text AS cancelled_doc,
    rp.total_acres,
    rp.remarks,
    rp.document_code,
    NULL::text AS county,
    NULL::text AS meridian,
    NULL::text AS township_number,
    NULL::text AS township_direction,
    NULL::text AS range_number,
    NULL::text AS range_direction,
    NULL::text AS section_number,
    NULL::text AS aliquot_parts,
    NULL::double precision AS centroid_lat,
    NULL::double precision AS centroid_lon,
    false AS has_plss_geometry
   FROM rails_patents rp
     LEFT JOIN blm_allotment_patents bap ON rp.accession_number = bap.accession_number
     LEFT JOIN tribe_name_map tnm ON rp.glo_tribe_name = tnm.glo_tribe_name
  WHERE bap.accession_number IS NULL;
"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--volume", required=True,
                    help="Volume prefix, e.g. NE1360__")
    ap.add_argument("--csv", default=None,
                    help="Override CSV path (default: data/rescrape_<volume_clean>.csv)")
    args = ap.parse_args()

    vol_clean = args.volume.rstrip("_")
    csv_path  = args.csv or f"data/rescrape_{vol_clean}.csv"

    if not os.path.exists(csv_path):
        sys.exit(f"missing {csv_path} — run scrape_blm_volume.py --volume {args.volume} first")

    empties = []
    auth_updates = []
    with open(csv_path) as f:
        for r in csv.DictReader(f):
            if r["status"] != "ok":
                continue
            acc = r["accession_number"]
            auth_raw = r.get("authority") or ""
            data_fields = ("full_name", "signature_date",
                           "indian_allotment_number", "remarks")
            if not any(r.get(f) for f in data_fields) and not auth_raw:
                empties.append(acc)
                continue
            parsed = parse_authority(auth_raw)
            if parsed:
                auth_updates.append((acc, parsed))

    print(f"From {csv_path}:")
    print(f"  empty-shell records (will DELETE if newly inserted): {len(empties)}")
    print(f"  records with parseable authority (will UPDATE):      {len(auth_updates)}")
    print()

    conn = psycopg2.connect(DB_URL)
    cur  = conn.cursor()

    # Step 1: DELETE empty-shell records (only those inserted via re-scrape,
    # which always have id > 285870 because rails_patents_id_seq starts there)
    cur.execute("""
        DELETE FROM rails_patents
        WHERE accession_number = ANY(%s) AND id > 285870
        RETURNING accession_number
    """, (empties,))
    deleted = [r[0] for r in cur.fetchall()]
    print(f"Step 1: DELETEd {len(deleted)} empty-shell records (id > 285870)")
    if len(deleted) != len(empties):
        print(f"  (note: {len(empties) - len(deleted)} were not in the new-insert range; left alone)")

    # Step 2: authority column should already exist (added in SD2610 cycle).
    # Add it defensively in case this is a fresh DB.
    cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'rails_patents' AND column_name = 'authority'
    """)
    if cur.fetchone():
        print(f"Step 2: authority column already exists, skipping ALTER")
    else:
        cur.execute("ALTER TABLE rails_patents ADD COLUMN authority text")
        print(f"Step 2: ALTERed rails_patents to add authority column")

    # Step 3: UPDATE authority
    psycopg2.extras.execute_batch(
        cur,
        "UPDATE rails_patents SET authority = %s WHERE accession_number = %s",
        [(auth, acc) for acc, auth in auth_updates],
        page_size=200,
    )
    print(f"Step 3: UPDATEd authority on {len(auth_updates)} rails_patents rows")

    # Step 4: CREATE OR REPLACE view (no-op if already at this definition)
    cur.execute(VIEW_SQL)
    print(f"Step 4: CREATE OR REPLACE VIEW all_patents (un-mappable branch uses rp.authority)")

    conn.commit()
    print()

    # Verification — volume-scoped
    cur.execute(f"SELECT COUNT(*) FROM rails_patents WHERE accession_number LIKE %s",
                (f"{args.volume}%",))
    print(f"Verification: {args.volume} volume now contains {cur.fetchone()[0]} records")

    cur.execute(f"""
        SELECT authority, COUNT(*) FROM rails_patents
        WHERE accession_number LIKE %s AND authority IS NOT NULL
        GROUP BY authority ORDER BY 2 DESC
    """, (f"{args.volume}%",))
    print(f"  {args.volume} authority distribution:")
    for auth, n in cur.fetchall():
        print(f"    {n:>4}  {auth}")

    # Surface one sample record so the user can spot-check
    cur.execute(f"""
        SELECT accession_number, full_name, authority, indian_allotment_number, glo_tribe_name
        FROM rails_patents
        WHERE accession_number LIKE %s AND authority IS NOT NULL AND full_name IS NOT NULL
        ORDER BY accession_number LIMIT 1
    """, (f"{args.volume}%",))
    row = cur.fetchone()
    if row:
        print(f"  Sample record: acc={row[0]}  name={row[1]!r}  allot={row[3]}  tribe={row[4]}")
        print(f"                 authority={row[2]!r}")


if __name__ == "__main__":
    main()
