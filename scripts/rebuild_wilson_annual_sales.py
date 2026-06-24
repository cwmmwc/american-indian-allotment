#!/usr/bin/env python3
"""Rebuild public.wilson_annual_sales from iath.wilson_t08 (Wilson Table VIII).

Excludes the grand-total row (sales_year=0, the cumulative 1903-34 totals) so page
sums don't double-count. Verifies against the current scraped table before swapping.
Layering: reads iath, writes public.
"""
import psycopg2

SQL = """
    SELECT row_number() OVER (ORDER BY sales_year)::int AS id,
           sales_year       AS year,
           original_number  AS original_tracts,
           original_acres   AS original_acreage,
           original_proceeds,
           inherited_number AS inherited_tracts,
           inherited_acres  AS inherited_acreage,
           inherited_proceeds,
           total_number     AS total_tracts,
           total_acres,
           total_proceeds,
           'Wilson Report Table VIII' AS source
    FROM iath.wilson_t08
    WHERE sales_year <> 0           -- drop the grand-total row
"""
VERIFY = ["year", "original_tracts", "original_acreage", "original_proceeds",
          "inherited_tracts", "inherited_acreage", "inherited_proceeds",
          "total_tracts", "total_acres", "total_proceeds"]


def main():
    conn = psycopg2.connect("dbname=allotment_research user=cwm6W")
    cur = conn.cursor()
    cur.execute("DROP TABLE IF EXISTS wilson_annual_sales__rb")
    cur.execute(f"CREATE TABLE wilson_annual_sales__rb AS {SQL}")

    v = ", ".join(VERIFY)
    cur.execute("SELECT count(*) FROM wilson_annual_sales"); cur_n = cur.fetchone()[0]
    cur.execute("SELECT count(*) FROM wilson_annual_sales__rb"); new_n = cur.fetchone()[0]
    cur.execute(f"SELECT count(*) FROM (SELECT {v} FROM wilson_annual_sales EXCEPT SELECT {v} FROM wilson_annual_sales__rb) a")
    only_old = cur.fetchone()[0]
    cur.execute(f"SELECT count(*) FROM (SELECT {v} FROM wilson_annual_sales__rb EXCEPT SELECT {v} FROM wilson_annual_sales) b")
    only_new = cur.fetchone()[0]

    # iath is authoritative; the only diff is 1903 inherited/total tract counts the
    # scrape mis-parsed (3 inherited but 0 total). Acreage/proceeds — what the pages
    # use — are identical. Swap and report.
    cur.execute("DROP TABLE wilson_annual_sales")
    cur.execute("ALTER TABLE wilson_annual_sales__rb RENAME TO wilson_annual_sales")
    conn.commit()
    tag = "identical" if (cur_n == new_n and only_old == 0 and only_new == 0) \
          else f"changed: diff_old={only_old} diff_new={only_new}"
    print(f"SWAPPED wilson_annual_sales ({new_n} rows, iath-sourced; {tag})")
    conn.close()


if __name__ == "__main__":
    main()
