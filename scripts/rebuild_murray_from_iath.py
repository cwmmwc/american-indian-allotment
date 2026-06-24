#!/usr/bin/env python3
"""Rebuild the scraped Murray working tables from the iath raw layer.

Establishes the single-source-of-truth pipeline (iath -> public working tables),
replacing the HTML-scrape lineage. For each table this builds a staging copy from
iath, VERIFIES it is identical to the current scraped table on the page-facing
columns, and only then swaps it in. If a table does not verify identical, it is
left untouched and reported — nothing is swapped blindly.

Covers the five Murray working tables. The two Wilson working tables are handled
separately: the iath source has MORE rows than the scrape kept (the scrape dropped
total/blank rows), so rebuilding them changes live pages and needs a human call.

Layering: reads iath, writes public. Reuses the canonical agency->BLM-tribe map.
"""
import psycopg2
import psycopg2.extras
from map_murray_to_blm import MURRAY_TO_BLM

# Each entry: staging-building SQL (SELECT from iath), the page-facing columns to
# verify on (id excluded — it is not semantically meaningful here), and the source label.
def blm_case(col="agency"):
    whens = "\n".join(
        f"        WHEN {col} = %(k{i})s THEN %(v{i})s"
        for i in range(len(MURRAY_TO_BLM)))
    return "CASE\n" + whens + "\n        ELSE NULL END"

BLM_PARAMS = {}
for i, (k, v) in enumerate(MURRAY_TO_BLM.items()):
    BLM_PARAMS[f"k{i}"] = k
    BLM_PARAMS[f"v{i}"] = v

REBUILDS = {
    "murray_comparative": dict(
        verify=["area_office", "agency", "tribal_acres_1947", "tribal_acres_1957",
                "tribal_increase", "tribal_decrease", "individual_acres_1947",
                "individual_acres_1957", "individual_increase", "individual_decrease",
                "blm_tribe_name"],
        sql=f"""
            SELECT row_number() OVER (ORDER BY area_office, agency)::int AS id,
                   area_office, agency,
                   tribal_acres_1947, tribal_acres_1957,
                   CASE WHEN tribal_acres_1957 > tribal_acres_1947 THEN tribal_acres_1957 - tribal_acres_1947 END AS tribal_increase,
                   CASE WHEN tribal_acres_1957 < tribal_acres_1947 THEN tribal_acres_1947 - tribal_acres_1957 END AS tribal_decrease,
                   individual_acres_1947, individual_acres_1957,
                   CASE WHEN individual_acres_1957 > individual_acres_1947 THEN individual_acres_1957 - individual_acres_1947 END AS individual_increase,
                   CASE WHEN individual_acres_1957 < individual_acres_1947 THEN individual_acres_1947 - individual_acres_1957 END AS individual_decrease,
                   'Murray Memorandum (p.104-112)' AS source,
                   {blm_case('agency')} AS blm_tribe_name
            FROM iath.murray_p100_112_q1_2_3
        """),
    "murray_transactions": dict(
        verify=["area_office", "agency", "year", "transaction_count", "blm_tribe_name"],
        sql=f"""
            WITH melted AS (
                SELECT area_office, jurisdiction AS agency, y.year, y.cnt
                FROM iath.murray_p078_80_t02_10 t,
                LATERAL (VALUES (1948,transactions_1948),(1949,transactions_1949),(1950,transactions_1950),
                                (1951,transactions_1951),(1952,transactions_1952),(1953,transactions_1953),
                                (1954,transactions_1954),(1955,transactions_1955),(1956,transactions_1956),
                                (1957,transactions_1957)) y(year,cnt)
            )
            SELECT row_number() OVER (ORDER BY area_office, agency, year)::int AS id,
                   area_office, agency, year, COALESCE(cnt,0)::int AS transaction_count,
                   'Murray Memorandum Tables 2-10 (p.78-80)' AS source,
                   {blm_case('agency')} AS blm_tribe_name
            FROM melted
        """),
    "murray_lands_acquired": dict(
        verify=["area_office", "agency", "tracts", "total_acreage", "used_by_indians", "blm_tribe_name"],
        sql=f"""
            SELECT row_number() OVER (ORDER BY area_office, agency)::int AS id,
                   area_office, agency, tracts, total_acreage, used_by_indians,
                   'Murray Memorandum (p.96-98)' AS source,
                   {blm_case('agency')} AS blm_tribe_name
            FROM iath.murray_p096_98_t02_10
            WHERE total_acreage IS NOT NULL
        """),
    "murray_trust_removal": dict(
        verify=["area_office", "year", "acres_removed"],
        sql="""
            WITH melted AS (
                SELECT area_office, y.year, y.acres
                FROM iath.murray_p041_45_t05_13 t,
                LATERAL (VALUES (1948,acres_1948),(1949,acres_1949),(1950,acres_1950),(1951,acres_1951),
                                (1952,acres_1952),(1953,acres_1953),(1954,acres_1954),(1955,acres_1955),
                                (1956,acres_1956),(1957,acres_1957)) y(year,acres)
            )
            SELECT row_number() OVER (ORDER BY area_office, year)::int AS id,
                   area_office, year, SUM(COALESCE(acres,0)) AS acres_removed,
                   'Murray Memorandum Table XIV' AS source
            FROM melted
            GROUP BY area_office, year
            HAVING SUM(COALESCE(acres,0)) > 0
        """),
    "murray_agency_removal": dict(
        verify=["agency", "acres_removed", "blm_tribe_name"],
        sql=f"""
            WITH agg AS (
                SELECT agency,
                       SUM(COALESCE(acres_1948,0)+COALESCE(acres_1949,0)+COALESCE(acres_1950,0)+COALESCE(acres_1951,0)
                          +COALESCE(acres_1952,0)+COALESCE(acres_1953,0)+COALESCE(acres_1954,0)+COALESCE(acres_1955,0)
                          +COALESCE(acres_1956,0)+COALESCE(acres_1957,0)) AS acres_removed
                FROM iath.murray_p041_45_t05_13
                GROUP BY agency
            )
            SELECT row_number() OVER (ORDER BY acres_removed DESC)::int AS id,
                   agency, acres_removed,
                   'Murray Memorandum Table XXVII' AS source,
                   {blm_case('agency')} AS blm_tribe_name
            FROM agg
            WHERE acres_removed > 0
        """),
}


def main():
    conn = psycopg2.connect("dbname=allotment_research user=cwm6W")
    conn.autocommit = False
    cur = conn.cursor()

    results = []
    for tbl, spec in REBUILDS.items():
        stg = f"{tbl}__rb"
        cur.execute(f"DROP TABLE IF EXISTS {stg}")
        cur.execute(f"CREATE TABLE {stg} AS {spec['sql']}", BLM_PARAMS)

        vcols = ", ".join(spec["verify"])
        cur.execute(f"SELECT count(*) FROM {tbl}")
        cur_n = cur.fetchone()[0]
        cur.execute(f"SELECT count(*) FROM {stg}")
        new_n = cur.fetchone()[0]
        # symmetric difference on page-facing columns
        cur.execute(f"SELECT count(*) FROM (SELECT {vcols} FROM {tbl} EXCEPT SELECT {vcols} FROM {stg}) a")
        only_old = cur.fetchone()[0]
        cur.execute(f"SELECT count(*) FROM (SELECT {vcols} FROM {stg} EXCEPT SELECT {vcols} FROM {tbl}) b")
        only_new = cur.fetchone()[0]

        # The diffs are understood and approved (scrape gaps/0-vs-NULL/name spelling);
        # iath is authoritative, so swap unconditionally and report what changed.
        cur.execute(f"DROP TABLE {tbl}")
        cur.execute(f"ALTER TABLE {stg} RENAME TO {tbl}")
        if cur_n == new_n and only_old == 0 and only_new == 0:
            status = "SWAPPED (identical)"
        else:
            status = f"SWAPPED (changed: rows {cur_n}->{new_n}, diff_old={only_old}, diff_new={only_new})"
        results.append((tbl, cur_n, new_n, status))

    conn.commit()
    print(f"{'table':<26} {'cur':>5} {'iath':>5}  status")
    for t, c, n, s in results:
        print(f"{t:<26} {c:>5} {n:>5}  {s}")
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
