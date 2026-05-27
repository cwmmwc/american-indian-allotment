"""
Step 2 of the FRN cleanup: add preferred_reservation column to
blm_allotment_patents, populate it for records currently labeled 'Frn*'
where the tribe_crosswalk has a canonical reservation name.

Bounded scope:
  - Only updates rows where bap.preferred_name ILIKE 'Frn%'
  - Only sets preferred_reservation when tribe_crosswalk.canonical_reservation
    is non-NULL (i.e. spreadsheet has a real reservation name, not FRN/None)
  - Does NOT touch the 177,801 non-FRN records that could also get a reservation
    from the crosswalk — that's deferred until we've validated this slice
  - Does NOT touch tribe data, app.py, templates, or the all_patents view

Requires: scripts/build_tribe_crosswalk.py to have run first.

Idempotent — re-runs are safe; UPDATE just rewrites the same values.

Usage:
    ./venv/bin/python3 scripts/populate_preferred_reservation_for_frn.py
    DATABASE_URL="host=127.0.0.1 port=5433 dbname=allotment_research user=appuser password=allotment-app-2026" \\
        ./venv/bin/python3 scripts/populate_preferred_reservation_for_frn.py
"""
import os
import sys
import psycopg2
import psycopg2.extras

DB_URL = os.environ.get("DATABASE_URL", "dbname=allotment_research user=cwm6W")


def main():
    conn = psycopg2.connect(DB_URL)
    cur  = conn.cursor()

    # Sanity: does tribe_crosswalk exist?
    cur.execute("""
        SELECT 1 FROM information_schema.tables
        WHERE table_name = 'tribe_crosswalk'
    """)
    if not cur.fetchone():
        sys.exit("tribe_crosswalk table does not exist — run build_tribe_crosswalk.py first")

    # Step 1: add column if not exists
    cur.execute("""
        SELECT column_name FROM information_schema.columns
        WHERE table_name = 'blm_allotment_patents' AND column_name = 'preferred_reservation'
    """)
    if cur.fetchone():
        print("preferred_reservation column already exists on blm_allotment_patents")
    else:
        cur.execute("ALTER TABLE blm_allotment_patents ADD COLUMN preferred_reservation text")
        print("Added preferred_reservation column to blm_allotment_patents")

    # Step 2: count what's currently populated (idempotent check)
    cur.execute("""
        SELECT COUNT(*) FROM blm_allotment_patents
        WHERE preferred_name ILIKE 'Frn%' AND preferred_reservation IS NOT NULL
    """)
    before = cur.fetchone()[0]
    print(f"Frn-prefixed records with preferred_reservation already set: {before}")

    # Step 3: UPDATE — JOIN through rails_patents → tribe_crosswalk on normalized GLO name
    cur.execute("""
        UPDATE blm_allotment_patents bap
        SET preferred_reservation = tc.canonical_reservation
        FROM rails_patents rp
        JOIN tribe_crosswalk tc
          ON tc.glo_name_normalized = UPPER(TRIM(rp.glo_tribe_name))
        WHERE bap.accession_number = rp.accession_number
          AND bap.preferred_name ILIKE 'Frn%'
          AND tc.canonical_reservation IS NOT NULL
    """)
    conn.commit()

    cur.execute("""
        SELECT COUNT(*) FROM blm_allotment_patents
        WHERE preferred_name ILIKE 'Frn%' AND preferred_reservation IS NOT NULL
    """)
    after = cur.fetchone()[0]
    print(f"Frn-prefixed records with preferred_reservation set after UPDATE: {after}  (Δ {after - before:+d})")

    # Step 4: report distribution
    cur.execute("""
        SELECT preferred_reservation, COUNT(*) AS n
        FROM blm_allotment_patents
        WHERE preferred_name ILIKE 'Frn%' AND preferred_reservation IS NOT NULL
        GROUP BY preferred_reservation ORDER BY n DESC
    """)
    print()
    print("Distribution of preferred_reservation among Frn-prefixed records:")
    print(f"  {'reservation':<55s}  {'n':>7s}")
    for res, n in cur.fetchall():
        print(f"  {res:<55s}  {n:>7,}")

    # Spot-check: confirm the KCA canonicalization fired
    cur.execute("""
        SELECT COUNT(*) FROM blm_allotment_patents
        WHERE preferred_reservation IN
              ('Kiowa, Comanche, Apache Reservation',
               'Comanche, Kiowa, and Apache Reservation')
    """)
    bad = cur.fetchone()[0]
    print()
    if bad > 0:
        print(f"WARNING: {bad} records have NON-canonical KCA spelling — canonicalization didn't fire")
    else:
        print(f"KCA canonicalization confirmed: 0 records with the two raw spreadsheet spellings")


if __name__ == "__main__":
    main()
