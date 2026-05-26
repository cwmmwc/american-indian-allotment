"""
One-shot data fix for the SD2610 re-scrape import: clean up empty-shell
records, add the authority column, populate it from the scraped BLM values,
and update the all_patents view to use it.

What this does (idempotent):
  1. DELETE the empty-shell records that got inserted because page_is_not_found
     missed BLM's "A document does not exist" message.
  2. ALTER TABLE rails_patents ADD COLUMN authority text (if not present).
  3. UPDATE rails_patents.authority for the legitimate SD2610 records by
     parsing the BLM long-form string from the scrape CSV — e.g.
     "February 8, 1887: Indian Allotment - General (24 Stat. 388)"
     yields "Indian Allotment - General".
  4. CREATE OR REPLACE all_patents view so its un-mappable branch uses
     COALESCE(rp.authority, rp.document_class) — vision into the authority
     column for rescraped records, falls back to document_class for the
     ~45,000 un-mappable records we haven't rescraped yet.

Run on local first, verify, then point DATABASE_URL at the Cloud SQL proxy
and run again.

Usage:
    ./venv/bin/python3 scripts/fix_sd2610_authority.py
    DATABASE_URL="host=127.0.0.1 port=5433 dbname=allotment_research user=appuser password=allotment-app-2026" \\
        ./venv/bin/python3 scripts/fix_sd2610_authority.py
"""
import csv
import os
import re
import sys
import psycopg2
import psycopg2.extras

DB_URL = os.environ.get("DATABASE_URL", "dbname=allotment_research user=cwm6W")
CSV    = "data/rescrape_SD2610.csv"


def parse_authority(raw):
    """BLM serves authority as 'DATE: NAME (STATUTE)'. Extract NAME.
    Returns None if the string doesn't match the pattern (e.g., empty)."""
    if not raw:
        return None
    m = re.search(r':\s*(.+?)\s*\(', raw)
    return m.group(1).strip() if m else None


# View definition pulled from `SELECT pg_get_viewdef('all_patents'::regclass, true)`
# with the un-mappable branch's `rp.document_class AS authority` changed to
# COALESCE(rp.authority, rp.document_class). Everything else unchanged.
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
    if not os.path.exists(CSV):
        sys.exit(f"missing {CSV}")

    # Read scrape CSV; identify the 54 empty-shells and parse authorities
    empties = []      # accessions to DELETE
    auth_updates = []  # (accession, parsed_authority) to UPDATE
    with open(CSV) as f:
        for r in csv.DictReader(f):
            if r["status"] != "ok":
                continue
            acc = r["accession_number"]
            auth_raw = r.get("authority") or ""
            # An empty-shell row has nothing — no name, no date, no allotment,
            # no remarks, no authority. Same heuristic as the import-side guard.
            data_fields = ("full_name", "signature_date",
                           "indian_allotment_number", "remarks")
            if not any(r.get(f) for f in data_fields) and not auth_raw:
                empties.append(acc)
                continue
            parsed = parse_authority(auth_raw)
            if parsed:
                auth_updates.append((acc, parsed))

    print(f"From {CSV}:")
    print(f"  empty-shell records (will DELETE if newly inserted): {len(empties)}")
    print(f"  records with parseable authority (will UPDATE):      {len(auth_updates)}")
    print()

    conn = psycopg2.connect(DB_URL)
    cur  = conn.cursor()

    # ── Step 1: DELETE empty-shell records (only those we inserted today) ──
    cur.execute("""
        DELETE FROM rails_patents
        WHERE accession_number = ANY(%s) AND id > 285870
        RETURNING accession_number
    """, (empties,))
    deleted = [r[0] for r in cur.fetchall()]
    print(f"Step 1: DELETEd {len(deleted)} empty-shell records (id > 285870)")
    if len(deleted) != len(empties):
        print(f"  (note: {len(empties) - len(deleted)} were not in the new-insert range; left alone)")

    # ── Step 2: ALTER TABLE add authority column if needed ──
    cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'rails_patents' AND column_name = 'authority'
    """)
    if cur.fetchone():
        print(f"Step 2: authority column already exists, skipping ALTER")
    else:
        cur.execute("ALTER TABLE rails_patents ADD COLUMN authority text")
        print(f"Step 2: ALTERed rails_patents to add authority column")

    # ── Step 3: UPDATE authority for legitimate SD2610 records ──
    psycopg2.extras.execute_batch(
        cur,
        "UPDATE rails_patents SET authority = %s WHERE accession_number = %s",
        [(auth, acc) for acc, auth in auth_updates],
        page_size=200,
    )
    print(f"Step 3: UPDATEd authority on {len(auth_updates)} rails_patents rows")

    # ── Step 4: Recreate all_patents view to use COALESCE(rp.authority, rp.document_class) ──
    cur.execute(VIEW_SQL)
    print(f"Step 4: CREATE OR REPLACE VIEW all_patents (un-mappable branch now uses rp.authority)")

    conn.commit()
    print()

    # ── Verification ──
    cur.execute("SELECT COUNT(*) FROM rails_patents WHERE accession_number LIKE 'SD2610__%'")
    print(f"Verification: SD2610 volume now contains {cur.fetchone()[0]} records")

    cur.execute("""
        SELECT authority, COUNT(*) FROM rails_patents
        WHERE accession_number LIKE 'SD2610__%' AND authority IS NOT NULL
        GROUP BY authority ORDER BY 2 DESC
    """)
    print(f"  SD2610 authority distribution:")
    for auth, n in cur.fetchall():
        print(f"    {n:>4}  {auth}")

    cur.execute("""
        SELECT accession_number, full_name, authority
        FROM rails_patents WHERE accession_number = 'SD2610__.247'
    """)
    row = cur.fetchone()
    print(f"  Helena Larvie (SD2610__.247): name={row[1]!r}, authority={row[2]!r}")

    cur.execute("""
        SELECT accession_number, full_name, authority FROM all_patents
        WHERE accession_number = 'SD2610__.247'
    """)
    row = cur.fetchone()
    print(f"  Helena Larvie via all_patents view: authority={row[2]!r}")


if __name__ == "__main__":
    main()
