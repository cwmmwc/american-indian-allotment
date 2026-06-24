#!/usr/bin/env python3
"""Scrape Wilson Report Table VI and load into PostgreSQL.

Column mapping (from Crow row with 32 cells):
[0]  reservation name
[1]  date established
[2]  original area (acres)
[3]  land acquired since establishment
[4]  total area (original + acquired)
[5]  reductions (other than allotted/alienated) — may have footnote numbers
[6]  (reductions sub-column or blank)
[7]  (reductions sub-column)
[8]  (reductions sub-column)
[9]  total reductions
[10] dates of major allotments
[11] total allotments made
[12] acreage of allotments
[13] land alienated (sales patent, cert of competency, etc.)
-- Living allotments:
[14] living allotments - number
[15] living allotments - agricultural acres
[16] living allotments - irrigable acres
[17] living allotments - grazing acres
[18] living allotments - total acres
-- Deceased allotments:
[19] deceased allotments - number
[20] deceased allotments - agricultural acres
[21] deceased allotments - irrigable acres
[22] deceased allotments - grazing acres
[23] deceased allotments - total acres
-- Tribal lands:
[24] tribal - agricultural acres
[25] tribal - irrigable acres
[26] tribal - grazing acres
[27] tribal - total acres
-- Government reserve:
[28] govt - agricultural acres
[29] govt - irrigable acres
[30] govt - grazing acres
[31] govt - total acres
"""

import re
import sys
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
        self.cell_tag = None
        self.table_count = 0
        self._colspan = 1

    def handle_starttag(self, tag, attrs):
        if tag == "table":
            self.table_count += 1
            self.in_table = True
        elif tag == "tr" and self.in_table:
            self.in_row = True
            self.current_row = []
        elif tag in ("td", "th") and self.in_row:
            self.in_cell = True
            self.current_cell = ""
            self.cell_tag = tag
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
    # Remove leading footnote numbers (e.g., "22 34,380,726" → "34,380,726")
    # Only match when followed by a space then a comma-formatted number
    s = re.sub(r'^(\d{1,2})\s+(\d{1,3}(,\d{3})+)', r'\2', s)
    # Remove leading footnote when followed by space then plain number
    s = re.sub(r'^(\d{1,2})\s+(\d+)$', r'\2', s)
    s = s.replace(",", "").strip()
    if not s or s in ("—", "-", "…", "0"):
        return 0 if s == "0" else None
    # Remove any remaining non-digit chars (footnote letters etc)
    cleaned = re.sub(r'[^0-9]', '', s)
    if not cleaned:
        return None
    try:
        return int(cleaned)
    except ValueError:
        return None


def parse_reservations(html_path):
    with open(html_path, "r", encoding="utf-8") as f:
        html = f.read()

    parser = TableParser()
    parser.feed(html)

    results = []
    for row in parser.rows:
        if len(row) < 20:
            continue
        # Data rows have a name in [0] and numbers in [2]+
        name = row[0].strip() if row[0] else ""
        if not name or name.startswith("("):
            continue
        # Skip header-like rows
        if "Agency" in name or "Acreage" in name or "Number" in name:
            continue
        if name.lower() in ("total", "grand total"):
            # Store grand total separately
            if "grand" in name.lower():
                results.append({"name": "__GRAND_TOTAL__", "row": row})
            continue

        # Must have some numeric content
        has_num = any(clean_number(c) is not None and clean_number(c) > 0
                      for c in row[2:6])
        if not has_num:
            continue

        results.append({"name": name, "row": row})

    return results


def extract_state(name):
    """Guess state from reservation naming patterns in Wilson Report."""
    # The table is organized by agency, which often indicates state
    # We'll fill this in from the database later via name matching
    return None


def main():
    html_path = "/tmp/wilson_t06.html"
    reservations = parse_reservations(html_path)
    print(f"Parsed {len(reservations)} reservation rows")

    conn = psycopg2.connect("dbname=allotment_research user=cwm6W")
    cur = conn.cursor()

    # Create table
    cur.execute("DROP TABLE IF EXISTS wilson_table_vi")
    cur.execute("""
        CREATE TABLE wilson_table_vi (
            id SERIAL PRIMARY KEY,
            reservation_name TEXT NOT NULL,
            date_established TEXT,
            original_area_acres BIGINT,
            land_acquired_acres BIGINT,
            total_area_acres BIGINT,
            total_reductions_acres BIGINT,
            allotment_dates TEXT,
            total_allotments_made INT,
            allotment_acreage BIGINT,
            land_alienated_acres BIGINT,
            living_allotments_num INT,
            living_ag_acres BIGINT,
            living_irr_acres BIGINT,
            living_grazing_acres BIGINT,
            living_total_acres BIGINT,
            deceased_allotments_num INT,
            deceased_ag_acres BIGINT,
            deceased_irr_acres BIGINT,
            deceased_grazing_acres BIGINT,
            deceased_total_acres BIGINT,
            tribal_ag_acres BIGINT,
            tribal_irr_acres BIGINT,
            tribal_grazing_acres BIGINT,
            tribal_total_acres BIGINT,
            govt_ag_acres BIGINT,
            govt_irr_acres BIGINT,
            govt_grazing_acres BIGINT,
            govt_total_acres BIGINT,
            blm_tribe_name TEXT,
            match_method TEXT
        )
    """)

    inserted = 0
    for r in reservations:
        name = r["name"]
        row = r["row"]
        if name == "__GRAND_TOTAL__":
            continue

        # Pad row to 32 cells
        while len(row) < 32:
            row.append("")

        try:
            cur.execute("""
                INSERT INTO wilson_table_vi (
                    reservation_name, date_established,
                    original_area_acres, land_acquired_acres, total_area_acres,
                    total_reductions_acres,
                    allotment_dates, total_allotments_made, allotment_acreage,
                    land_alienated_acres,
                    living_allotments_num, living_ag_acres, living_irr_acres,
                    living_grazing_acres, living_total_acres,
                    deceased_allotments_num, deceased_ag_acres, deceased_irr_acres,
                    deceased_grazing_acres, deceased_total_acres,
                    tribal_ag_acres, tribal_irr_acres, tribal_grazing_acres, tribal_total_acres,
                    govt_ag_acres, govt_irr_acres, govt_grazing_acres, govt_total_acres
                ) VALUES (
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s, %s, %s,
                    %s, %s, %s, %s, %s, %s, %s, %s
                )
            """, (
                name, row[1].strip() if row[1] else None,
                clean_number(row[2]), clean_number(row[3]), clean_number(row[4]),
                clean_number(row[9]),
                row[10].strip() if row[10] else None,
                clean_number(row[11]), clean_number(row[12]),
                clean_number(row[13]),
                clean_number(row[14]), clean_number(row[15]), clean_number(row[16]),
                clean_number(row[17]), clean_number(row[18]),
                clean_number(row[19]), clean_number(row[20]), clean_number(row[21]),
                clean_number(row[22]), clean_number(row[23]),
                clean_number(row[24]), clean_number(row[25]),
                clean_number(row[26]), clean_number(row[27]),
                clean_number(row[28]), clean_number(row[29]),
                clean_number(row[30]), clean_number(row[31]),
            ))
            inserted += 1
        except Exception as e:
            print(f"Error inserting {name}: {e}")
            conn.rollback()
            continue

    conn.commit()
    print(f"Inserted {inserted} rows into wilson_table_vi")

    # Verify key reservations
    cur.execute("""
        SELECT reservation_name, original_area_acres, total_allotments_made,
               allotment_acreage, land_alienated_acres
        FROM wilson_table_vi
        WHERE reservation_name ILIKE '%crow%'
           OR reservation_name ILIKE '%pine ridge%'
           OR reservation_name ILIKE '%blackfeet%'
           OR reservation_name ILIKE '%flathead%'
        ORDER BY original_area_acres DESC NULLS LAST
    """)
    print("\nVerification:")
    for row in cur.fetchall():
        print(f"  {row[0]:<40} orig={row[1]:>12,}  allot={row[2]:>6}  "
              f"allot_ac={row[3]:>10,}  alienated={row[4]:>10,}" if row[1] and row[3] and row[4]
              else f"  {row[0]}")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
