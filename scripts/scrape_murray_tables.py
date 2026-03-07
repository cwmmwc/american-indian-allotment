#!/usr/bin/env python3
"""Scrape multiple Murray Memorandum tables into PostgreSQL.

Tables scraped:
  - Table XXVII (p.49): Agency-level acreage removed from trust (1947-1957)
  - Tables 2-10 (p.78-80): Transaction counts by agency by year (1948-1957)
  - Pages 104-112: Comparative trust land stats, 1947 vs 1957, by agency
  - Pages 96-98: Federal lands acquired since 1930, by agency

Source: https://land-sales.iath.virginia.edu/
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


def parse_file(path):
    with open(path, "r", encoding="utf-8") as f:
        html = f.read()
    p = TableParser()
    p.feed(html)
    return p.tables


def clean_number(s):
    if not s:
        return None
    s = s.replace(",", "").strip()
    # Remove footnote markers like "1" at end
    s = re.sub(r'\s+\d+$', '', s)
    if not s or s in ("—", "-", "…", "No answer", "0"):
        return None
    try:
        return float(s)
    except ValueError:
        return None


def clean_agency(name):
    """Clean agency name — remove footnote markers, normalize whitespace."""
    name = name.strip()
    # Remove trailing footnote numbers like " 1"
    name = re.sub(r'\s+\d+$', '', name)
    # Normalize some names
    name = name.replace(" consolidated", "").replace(" area field office", "")
    return name


AREA_OFFICES = [
    "Aberdeen", "Anadarko", "Billings", "Gallup",
    "Minneapolis", "Muskogee", "Phoenix", "Portland", "Sacramento"
]


def scrape_t27(cur):
    """Table XXVII: Agency-level acreage removed from trust (total 1947-1957)."""
    print("\n=== Table XXVII: Agency trust removal totals ===")
    tables = parse_file("/tmp/murray_t27.html")
    t = tables[0]

    cur.execute("DROP TABLE IF EXISTS murray_agency_removal")
    cur.execute("""
        CREATE TABLE murray_agency_removal (
            id SERIAL PRIMARY KEY,
            agency TEXT NOT NULL,
            acres_removed NUMERIC(12,2),
            source TEXT DEFAULT 'Murray Memorandum Table XXVII'
        )
    """)

    inserted = 0
    for row in t:
        if len(row) < 2:
            continue
        name = clean_agency(row[0])
        if not name or name == "Agency":
            continue
        acres = clean_number(row[1])
        if acres is not None:
            cur.execute(
                "INSERT INTO murray_agency_removal (agency, acres_removed) VALUES (%s, %s)",
                (name, acres)
            )
            inserted += 1

    print(f"  Inserted {inserted} agencies")

    # Verify top 5
    cur.execute("SELECT agency, acres_removed FROM murray_agency_removal ORDER BY acres_removed DESC LIMIT 5")
    for r in cur.fetchall():
        print(f"    {r[0]:<30} {r[1]:>12,.2f} acres")

    cur.execute("SELECT SUM(acres_removed) FROM murray_agency_removal")
    print(f"  Total: {cur.fetchone()[0]:>12,.2f} acres")


def scrape_transactions(cur):
    """Tables 2-10 (p.78-80): Transaction counts by agency by year."""
    print("\n=== Tables 2-10: Transaction counts by agency by year ===")
    tables = parse_file("/tmp/murray_p078_transactions.html")
    years = list(range(1948, 1958))

    cur.execute("DROP TABLE IF EXISTS murray_transactions")
    cur.execute("""
        CREATE TABLE murray_transactions (
            id SERIAL PRIMARY KEY,
            area_office TEXT NOT NULL,
            agency TEXT NOT NULL,
            year INT NOT NULL,
            transaction_count INT,
            source TEXT DEFAULT 'Murray Memorandum Tables 2-10 (p.78-80)'
        )
    """)

    inserted = 0
    for ti, table in enumerate(tables):
        area = AREA_OFFICES[ti] if ti < len(AREA_OFFICES) else f"Unknown_{ti}"
        for row in table:
            if len(row) < 12:
                continue
            name = clean_agency(row[0])
            if not name or name in ("Jurisdiction", "Total"):
                continue

            for j, year in enumerate(years):
                val = clean_number(row[j + 1]) if j + 1 < len(row) else None
                count = int(val) if val is not None else 0
                cur.execute(
                    "INSERT INTO murray_transactions (area_office, agency, year, transaction_count) VALUES (%s, %s, %s, %s)",
                    (area, name, year, count)
                )
                inserted += 1

    print(f"  Inserted {inserted} rows")

    # Verify — top agencies by total transactions
    cur.execute("""
        SELECT agency, SUM(transaction_count) as total
        FROM murray_transactions
        GROUP BY agency ORDER BY total DESC LIMIT 10
    """)
    print("  Top 10 by transaction count:")
    for r in cur.fetchall():
        print(f"    {r[0]:<35} {r[1]:>6} transactions")


def scrape_comparative(cur):
    """Pages 104-112: Comparative trust land stats, 1947 vs 1957."""
    print("\n=== Comparative Stats: 1947 vs 1957 by agency ===")
    tables = parse_file("/tmp/murray_p104_agencies.html")

    cur.execute("DROP TABLE IF EXISTS murray_comparative")
    cur.execute("""
        CREATE TABLE murray_comparative (
            id SERIAL PRIMARY KEY,
            area_office TEXT NOT NULL,
            agency TEXT NOT NULL,
            tribal_acres_1947 NUMERIC(14,3),
            tribal_acres_1957 NUMERIC(14,3),
            tribal_increase NUMERIC(14,3),
            tribal_decrease NUMERIC(14,3),
            individual_acres_1947 NUMERIC(14,3),
            individual_acres_1957 NUMERIC(14,3),
            individual_increase NUMERIC(14,3),
            individual_decrease NUMERIC(14,3),
            source TEXT DEFAULT 'Murray Memorandum (p.104-112)'
        )
    """)

    inserted = 0
    area_idx = 0
    for ti, table in enumerate(tables):
        # Skip summary tables (they have <=4 rows and different structure)
        if len(table) < 3 or len(table[0]) < 5:
            continue

        area = AREA_OFFICES[area_idx] if area_idx < len(AREA_OFFICES) else f"Unknown_{area_idx}"
        area_idx += 1

        for row in table[2:]:  # skip 2 header rows
            if len(row) < 9:
                continue
            name = clean_agency(row[0])
            if not name or name == "Total":
                continue

            cur.execute("""
                INSERT INTO murray_comparative
                (area_office, agency, tribal_acres_1947, tribal_acres_1957,
                 tribal_increase, tribal_decrease,
                 individual_acres_1947, individual_acres_1957,
                 individual_increase, individual_decrease)
                VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
            """, (
                area, name,
                clean_number(row[1]), clean_number(row[2]),
                clean_number(row[3]), clean_number(row[4]),
                clean_number(row[5]), clean_number(row[6]),
                clean_number(row[7]), clean_number(row[8])
            ))
            inserted += 1

    print(f"  Inserted {inserted} agencies")

    # Verify — biggest individual land losses
    cur.execute("""
        SELECT agency, area_office,
               individual_acres_1947, individual_acres_1957, individual_decrease
        FROM murray_comparative
        WHERE individual_decrease IS NOT NULL
        ORDER BY individual_decrease DESC LIMIT 10
    """)
    print("  Top 10 individual land losses:")
    for r in cur.fetchall():
        print(f"    {r[0]:<30} ({r[1]:<12}) {r[2]:>12,.0f} -> {r[3]:>12,.0f}  (-{r[4]:>10,.0f})")

    # Total individual land change
    cur.execute("""
        SELECT SUM(individual_acres_1947), SUM(individual_acres_1957),
               SUM(COALESCE(individual_decrease, 0)) - SUM(COALESCE(individual_increase, 0))
        FROM murray_comparative
    """)
    r = cur.fetchone()
    print(f"\n  Individual land totals: {r[0]:>14,.0f} (1947) -> {r[1]:>14,.0f} (1957), net loss: {r[2]:>12,.0f}")


def scrape_acquired(cur):
    """Pages 96-98: Federal lands acquired since 1930."""
    print("\n=== Lands Acquired Since 1930 ===")
    tables = parse_file("/tmp/murray_p096_acquired.html")

    cur.execute("DROP TABLE IF EXISTS murray_lands_acquired")
    cur.execute("""
        CREATE TABLE murray_lands_acquired (
            id SERIAL PRIMARY KEY,
            area_office TEXT NOT NULL,
            agency TEXT NOT NULL,
            tracts INT,
            total_acreage NUMERIC(12,2),
            used_by_indians NUMERIC(12,2),
            source TEXT DEFAULT 'Murray Memorandum (p.96-98)'
        )
    """)

    inserted = 0
    for ti, table in enumerate(tables):
        area = AREA_OFFICES[ti] if ti < len(AREA_OFFICES) else f"Unknown_{ti}"
        for row in table:
            if len(row) < 4:
                continue
            name = clean_agency(row[0])
            if not name or name in ("Agency", "Total"):
                continue

            tracts_val = clean_number(row[1])
            tracts = int(tracts_val) if tracts_val is not None else None
            total_acres = clean_number(row[2])
            used = clean_number(row[3])

            # Skip rows where everything is "No answer"
            if tracts is None and total_acres is None and used is None:
                continue

            cur.execute("""
                INSERT INTO murray_lands_acquired
                (area_office, agency, tracts, total_acreage, used_by_indians)
                VALUES (%s, %s, %s, %s, %s)
            """, (area, name, tracts, total_acres, used))
            inserted += 1

    print(f"  Inserted {inserted} agencies (skipped 'No answer' rows)")

    cur.execute("""
        SELECT agency, total_acreage, used_by_indians
        FROM murray_lands_acquired
        WHERE total_acreage IS NOT NULL
        ORDER BY total_acreage DESC LIMIT 10
    """)
    print("  Top 10 by acreage acquired:")
    for r in cur.fetchall():
        used = f"{r[2]:>12,.2f}" if r[2] else "         N/A"
        print(f"    {r[0]:<30} {r[1]:>12,.2f} total, {used} used by Indians")

    cur.execute("SELECT SUM(total_acreage), SUM(used_by_indians) FROM murray_lands_acquired")
    r = cur.fetchone()
    print(f"\n  Totals: {r[0]:>12,.2f} acquired, {r[1]:>12,.2f} used by Indians")


def main():
    conn = psycopg2.connect("dbname=allotment_research user=cwm6W")
    cur = conn.cursor()

    scrape_t27(cur)
    scrape_transactions(cur)
    scrape_comparative(cur)
    scrape_acquired(cur)

    conn.commit()
    print("\n✓ All Murray tables committed to database.")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
