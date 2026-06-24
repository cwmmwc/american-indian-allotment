#!/usr/bin/env python3
"""Scrape Murray Memorandum Table XIV into PostgreSQL.

Table XIV: Individual Indian trust lands removed from all trust status,
1948 to 1957 — by area office.

Source: https://land-sales.iath.virginia.edu/murray_p045_t14.php
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
        self.rows = []
        self._colspan = 1

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.in_table = True
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
        elif tag == "tr" and self.in_row:
            self.in_row = False
            if self.current_row:
                self.rows.append(self.current_row)
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
    s = s.replace(",", "").strip()
    if not s or s in ("—", "-", "…"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def main():
    html_path = "/tmp/murray_t14.html"
    print(f"Reading {html_path}")
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()

    parser = TableParser()
    parser.feed(html)

    print(f"Parsed {len(parser.rows)} rows")
    for i, row in enumerate(parser.rows):
        print(f"  [{i}] len={len(row)}: {row[:3]}...")

    # Find data rows — should have area office name + year columns + total
    years = list(range(1948, 1958))  # 1948-1957

    conn = psycopg2.connect("dbname=allotment_research user=cwm6W")
    cur = conn.cursor()

    cur.execute("DROP TABLE IF EXISTS murray_trust_removal")
    cur.execute("""
        CREATE TABLE murray_trust_removal (
            id SERIAL PRIMARY KEY,
            area_office TEXT NOT NULL,
            year INT NOT NULL,
            acres_removed NUMERIC(12,2),
            source TEXT DEFAULT 'Murray Memorandum Table XIV'
        )
    """)

    inserted = 0
    for row in parser.rows:
        if len(row) < 11:
            continue
        name = row[0].strip()
        if not name or "Total" in name and "Grand" not in name:
            continue
        # Skip header rows
        if "Area" in name or "Office" in name or "1948" in name:
            continue

        is_grand_total = "Grand" in name or "total" in name.lower()
        office = "Grand Total" if is_grand_total else name

        # Columns 1-10 are years 1948-1957, column 11 is total
        for j, year in enumerate(years):
            val = clean_number(row[j + 1]) if j + 1 < len(row) else None
            if val is not None and val > 0:
                cur.execute("""
                    INSERT INTO murray_trust_removal (area_office, year, acres_removed)
                    VALUES (%s, %s, %s)
                """, (office, year, val))
                inserted += 1

    conn.commit()
    print(f"Inserted {inserted} rows into murray_trust_removal")

    # Verify
    cur.execute("""
        SELECT area_office, SUM(acres_removed) as total
        FROM murray_trust_removal
        WHERE area_office != 'Grand Total'
        GROUP BY area_office
        ORDER BY total DESC
    """)
    print("\nVerification:")
    for row in cur.fetchall():
        print(f"  {row[0]:<20} {row[1]:>12,.2f} acres")

    cur.execute("SELECT SUM(acres_removed) FROM murray_trust_removal WHERE area_office != 'Grand Total'")
    print(f"\n  Computed total: {cur.fetchone()[0]:>12,.2f}")

    cur.execute("SELECT SUM(acres_removed) FROM murray_trust_removal WHERE area_office = 'Grand Total'")
    gt = cur.fetchone()[0]
    if gt:
        print(f"  Grand Total row: {gt:>12,.2f}")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
