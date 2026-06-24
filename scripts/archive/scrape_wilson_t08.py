#!/usr/bin/env python3
"""Scrape Wilson Report Table VIII into PostgreSQL.

Table VIII: Annual sales of Indian allotted lands, 1903-34, inclusive.
Tracks number of tracts, acreage, and proceeds for original allotments
vs inherited lands, by year.

Source: https://land-sales.iath.virginia.edu/wilson_t08.php
"""

import re
import psycopg2
from html.parser import HTMLParser


class TableParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.in_table = False
        self.in_row = False
        self.in_cell = False
        self.current_row = []
        self.current_cell = ""
        self._colspan = 1
        self.tables = []
        self._current_table = []

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.in_table = True
            self._current_table = []
        elif tag == "tr" and self.in_table:
            self.in_row = True
            self.current_row = []
        elif tag in ("td", "th") and self.in_row:
            self.in_cell = True
            self.current_cell = ""
            self._colspan = 1
            for name, val in attrs:
                if name == "colspan":
                    try:
                        self._colspan = int(val)
                    except ValueError:
                        pass

    def handle_endtag(self, tag):
        if tag == "table":
            self.in_table = False
            self.tables.append(self._current_table)
        elif tag == "tr" and self.in_row:
            self.in_row = False
            self._current_table.append(self.current_row)
        elif tag in ("td", "th") and self.in_cell:
            self.in_cell = False
            val = self.current_cell.strip()
            self.current_row.append(val)
            for _ in range(self._colspan - 1):
                self.current_row.append("")

    def handle_data(self, data):
        if self.in_cell:
            self.current_cell += data


def clean_number(s):
    if not s:
        return None
    s = s.replace(",", "").replace("$", "").strip()
    if not s or s in ("—", "-", "…"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def clean_year(s):
    """Extract year from strings like '1909 4' (with footnote markers)."""
    m = re.match(r'(\d{4})', s.strip())
    return int(m.group(1)) if m else None


def main():
    html_path = "/tmp/wilson_t08.html"
    print(f"Reading {html_path}")
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()

    parser = TableParser()
    parser.feed(html)
    table = parser.tables[0]
    print(f"Parsed {len(table)} rows")

    conn = psycopg2.connect("dbname=allotment_research user=cwm6W")
    cur = conn.cursor()

    cur.execute("DROP TABLE IF EXISTS wilson_annual_sales")
    cur.execute("""
        CREATE TABLE wilson_annual_sales (
            id SERIAL PRIMARY KEY,
            year INT NOT NULL,
            original_tracts INT,
            original_acreage NUMERIC(12,2),
            original_proceeds NUMERIC(14,2),
            inherited_tracts INT,
            inherited_acreage NUMERIC(12,2),
            inherited_proceeds NUMERIC(14,2),
            total_tracts INT,
            total_acres NUMERIC(12,2),
            total_proceeds NUMERIC(14,2),
            source TEXT DEFAULT 'Wilson Report Table VIII'
        )
    """)

    inserted = 0
    for row in table[2:]:  # skip 2 header rows
        if len(row) < 10:
            continue
        year = clean_year(row[0])
        if not year:
            continue
        if year < 1903 or year > 1934:
            continue

        cur.execute("""
            INSERT INTO wilson_annual_sales
            (year, original_tracts, original_acreage, original_proceeds,
             inherited_tracts, inherited_acreage, inherited_proceeds,
             total_tracts, total_acres, total_proceeds)
            VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
        """, (
            year,
            clean_number(row[1]), clean_number(row[2]), clean_number(row[3]),
            clean_number(row[4]), clean_number(row[5]), clean_number(row[6]),
            clean_number(row[7]), clean_number(row[8]), clean_number(row[9]),
        ))
        inserted += 1

    conn.commit()
    print(f"Inserted {inserted} rows")

    # Verify
    cur.execute("""
        SELECT year, total_tracts, total_acres, total_proceeds
        FROM wilson_annual_sales
        ORDER BY year
    """)
    print("\nYear    Tracts    Acres       Proceeds")
    print("-" * 50)
    for r in cur.fetchall():
        tracts = f"{r[1]:>6,}" if r[1] else "     —"
        acres = f"{r[2]:>10,.0f}" if r[2] else "        —"
        proceeds = f"${r[3]:>14,.2f}" if r[3] else "            —"
        print(f"{r[0]}  {tracts}  {acres}  {proceeds}")

    cur.execute("SELECT SUM(total_acres), SUM(total_proceeds) FROM wilson_annual_sales")
    r = cur.fetchone()
    print(f"\nTotal: {r[0]:,.0f} acres, ${r[1]:,.2f} proceeds")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
