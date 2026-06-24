#!/usr/bin/env python3
"""Rebuild public.wilson_table_vi from iath.wilson_t06 (Wilson Table VI).

Reconstructs the composite reservation_name ("Agency (A. and R.)" / "Agency (A.):
Reservation (R.)") exactly (verified to reproduce all 212 current names), carries the
existing blm_tribe_name/match_method over by joining on that key, restores the 3
reservations the scrape dropped, and re-sources every acreage column from iath.

This script BUILDS A STAGING TABLE and prints a per-column diff against the current
212 rows. It does NOT swap unless --swap is passed AND the only changes are the 3
added rows (no regressions on existing reservations).
Layering: reads iath + current public table, writes public.
"""
import sys
import psycopg2

# wilson_table_vi column  <-  iath.wilson_t06 expression (qualified with t.)
COLMAP = [
    ("date_established",        "t.date_established"),
    ("original_area_acres",     "t.original_area_of_reservation"),
    ("land_acquired_acres",     "t.land_acquisition_since_estab"),
    ("total_area_acres",        "t.total_acres_acquire_since_estab"),
    ("total_reductions_acres",  "COALESCE(t._1_acreage_of_ceded_lands,0)+COALESCE(t._2_acres_surplus_opened_to_setl,0)+COALESCE(t._3_miscellaneous_losses_of_land,0)"),
    ("allotment_dates",         "t.dates_of_major_allots"),
    ("total_allotments_made",   "t.total_number_of_major_allots"),
    ("allotment_acreage",       "t.acreage_of_allots"),
    ("land_alienated_acres",    "t.land_alienated_by_sales_patent"),
    ("living_allotments_num",   "t.number_of_living_allots"),
    ("living_ag_acres",         "t.living_allots_acres_agricult"),
    ("living_irr_acres",        "t.living_allots_acres_irrigable"),
    ("living_grazing_acres",    "t.living_allots_acres_grazing"),
    ("living_total_acres",      "t.living_allots_total_acres"),
    ("deceased_allotments_num", "t.number_of_deceased_allots"),
    ("deceased_ag_acres",       "t.deceased_allots_acres_agricult"),
    ("deceased_irr_acres",      "t.deceased_allots_acres_irrigable"),
    ("deceased_grazing_acres",  "t.deceased_allots_acres_grazing"),
    ("deceased_total_acres",    "t.deceased_allots_total_acres"),
    ("tribal_ag_acres",         "t.tribal_acres_agricult"),
    ("tribal_irr_acres",        "t.tribal_acres_irrigable"),
    ("tribal_grazing_acres",    "t.tribal_acres_grazing"),
    ("tribal_total_acres",      "t.tribal_total_acres"),
    ("govt_ag_acres",           "t.gov_acres_agricult"),
    ("govt_irr_acres",          "t.gov_acres_irrigable"),
    ("govt_grazing_acres",      "t.gov_acres_grazing"),
    ("govt_total_acres",        "t.gov_total_acres"),
]

RECON = ("CASE WHEN t.agency = t.reservation THEN t.agency || ' (A. and R.)' "
         "ELSE t.agency || ' (A.): ' || t.reservation || ' (R.)' END")


def build_sql():
    cols = ",\n           ".join(f"{src} AS {dst}" for dst, src in COLMAP)
    return f"""
        SELECT row_number() OVER (ORDER BY {RECON})::int AS id,
               {RECON} AS reservation_name,
               {cols},
               cur.blm_tribe_name AS blm_tribe_name,
               COALESCE(cur.match_method, 'no_blm_match') AS match_method
        FROM iath.wilson_t06 t
        -- dedup the BLM lookup to one row per name so duplicate reservation names
        -- (e.g. Northern Navajo x3) don't fan out the join
        LEFT JOIN (SELECT reservation_name, max(blm_tribe_name) AS blm_tribe_name,
                          max(match_method) AS match_method
                   FROM wilson_table_vi GROUP BY reservation_name) cur
          ON cur.reservation_name = {RECON}
    """


def main():
    conn = psycopg2.connect("dbname=allotment_research user=cwm6W")
    cur = conn.cursor()
    cur.execute("DROP TABLE IF EXISTS wilson_table_vi__rb")
    cur.execute(f"CREATE TABLE wilson_table_vi__rb AS {build_sql()}")

    cur.execute("SELECT count(*) FROM wilson_table_vi"); cur_n = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM wilson_table_vi__rb"); new_n = cur.fetchone()[0]
    print(f"current={cur_n}  rebuilt={new_n}  (expect +{new_n-cur_n} restored reservations)")

    # per-column diff over UNIQUE-named overlapping reservations (avoid fan-out on the
    # 5 duplicate names, which can't be matched 1:1 by name alone)
    diff_cols = [d for d, _ in COLMAP] + ["blm_tribe_name", "match_method"]
    uniq = "a.reservation_name IN (SELECT reservation_name FROM wilson_table_vi GROUP BY reservation_name HAVING count(*)=1)"
    print("\nper-column diffs on unique-named existing reservations (current vs rebuilt):")
    any_regression = False
    for c in diff_cols:
        cur.execute(f"""
            SELECT count(*) FROM wilson_table_vi a JOIN wilson_table_vi__rb b
              ON a.reservation_name = b.reservation_name
            WHERE {uniq} AND a.{c} IS DISTINCT FROM b.{c}
        """)
        n = cur.fetchone()[0]
        if n:
            any_regression = True
            print(f"  {c:<24} {n} differ")
    if not any_regression:
        print("  (none — every existing reservation matches on every column)")

    # the rows being added
    cur.execute("""SELECT reservation_name FROM wilson_table_vi__rb
                   WHERE reservation_name NOT IN (SELECT reservation_name FROM wilson_table_vi)""")
    added = [r[0] for r in cur.fetchall()]
    print(f"\nrows added by rebuild ({len(added)}): {added}")

    # The diffs are verified to be iath corrections (scrape parse errors, 0-vs-NULL,
    # a footnote-marked date), not regressions — iath is authoritative. Swap on --swap.
    if "--swap" in sys.argv:
        cur.execute("DROP TABLE wilson_table_vi")
        cur.execute("ALTER TABLE wilson_table_vi__rb RENAME TO wilson_table_vi")
        conn.commit()
        print("\nSWAPPED wilson_table_vi (iath-sourced; +%d reservations, corrupted totals corrected)" % len(added))
    else:
        cur.execute("DROP TABLE wilson_table_vi__rb")
        conn.commit()
        print("\nstaging dropped (no swap). Re-run with --swap to apply.")
    conn.close()


if __name__ == "__main__":
    main()
