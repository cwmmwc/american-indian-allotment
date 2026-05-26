"""
Import a BLM volume re-scrape CSV (from scrape_blm_volume.py) into
rails_patents using Option C semantics:

  - status='ok' AND accession NOT in rails_patents → INSERT all scraped fields
  - status='ok' AND accession IN rails_patents     → UPDATE each column ONLY
                                                     where rails_patents.<col>
                                                     IS NULL (preserve any
                                                     existing non-NULL value)
  - status != 'ok' (not_found / error / http_*)    → skip

Idempotent — re-running re-evaluates each row against current DB state.

Dry-run by default; pass --apply to commit. Use DATABASE_URL env var to point
at Cloud SQL instead of local (after verifying local).

Usage:
    ./venv/bin/python3 scripts/import_rescrape_to_rails_patents.py --csv data/rescrape_SD2610.csv
    ./venv/bin/python3 scripts/import_rescrape_to_rails_patents.py --csv data/rescrape_SD2610.csv --apply
    DATABASE_URL="host=127.0.0.1 port=5433 dbname=allotment_research user=appuser password=allotment-app-2026" \\
        ./venv/bin/python3 scripts/import_rescrape_to_rails_patents.py --csv data/rescrape_SD2610.csv --apply
"""
import argparse
import csv
import os
import sys
import psycopg2
import psycopg2.extras
from collections import Counter

DB_URL = os.environ.get("DATABASE_URL", "dbname=allotment_research user=cwm6W")

# Columns in rails_patents we can populate from the scrape, in (column, type) form.
# type is used to coerce CSV strings: 'text' (None for empty), 'date' (None for
# empty or non-ISO), 'numeric' (None for empty or non-parseable).
RAILS_COLUMNS = [
    ("accession_number",        "text"),
    ("full_name",               "text"),
    ("signature_date",          "date"),
    ("state",                   "text"),
    ("document_class",          "text"),
    ("document_code",           "text"),
    ("indian_allotment_number", "text"),
    ("glo_tribe_name",          "text"),
    ("remarks",                 "text"),
    ("land_office",             "text"),
    ("document_number",         "text"),
    ("misc_document_number",    "text"),
    ("blm_serial_number",       "text"),
    ("total_acres",             "numeric"),
    ("survey_date",             "text"),   # rails_patents.survey_date is text, not date
    ("geographic_name",         "text"),
    ("metes_bounds",            "text"),
]


def coerce(value, type_):
    """CSV-string → Python value with type-appropriate NULL-coercion."""
    if value is None:
        return None
    s = str(value).strip()
    if s == "":
        return None
    if type_ == "date":
        # Must be ISO YYYY-MM-DD (the scraper already normalizes). If anything
        # else slips through, return None — better to leave NULL than insert bad data.
        import re
        if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
            return s
        return None
    if type_ == "numeric":
        try:
            return float(s)
        except ValueError:
            return None
    return s


def parse_args():
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True,
                    help="path to rescrape_<VOLUME>.csv produced by scrape_blm_volume.py")
    ap.add_argument("--apply", action="store_true",
                    help="commit the changes (default is dry-run)")
    return ap.parse_args()


def main():
    args = parse_args()

    if not os.path.exists(args.csv):
        sys.exit(f"missing {args.csv}")

    rows = []
    skipped_by_status = Counter()
    with open(args.csv) as f:
        for r in csv.DictReader(f):
            if r.get("status") != "ok":
                skipped_by_status[r.get("status") or "(no status)"] += 1
                continue
            # Coerce all populated fields
            clean = {}
            for col, ty in RAILS_COLUMNS:
                clean[col] = coerce(r.get(col), ty)
            if not clean["accession_number"]:
                skipped_by_status["missing_accession"] += 1
                continue
            # Defense-in-depth: skip rows that have no useful data even though
            # they slipped past page_is_not_found upstream (this caught 54
            # SD2610 empty-shell pages where BLM served a 200 with an unknown
            # variant of the "no document" message). If a row has no name, no
            # date, no allotment number, no remarks — there's nothing to import.
            data_fields = ("full_name", "signature_date",
                           "indian_allotment_number", "remarks")
            if not any(clean.get(f) for f in data_fields):
                skipped_by_status["empty_data"] += 1
                continue
            rows.append(clean)
    print(f"loaded {len(rows)} ok rows from {args.csv}")
    if skipped_by_status:
        print(f"skipped:")
        for k, n in skipped_by_status.most_common():
            print(f"  {k}: {n}")
    print()

    conn = psycopg2.connect(DB_URL)
    cur  = conn.cursor()

    # Classify each row: INSERT vs UPDATE
    accs = [r["accession_number"] for r in rows]
    cur.execute("SELECT accession_number FROM rails_patents WHERE accession_number = ANY(%s)", (accs,))
    existing = {a for (a,) in cur.fetchall()}
    to_insert = [r for r in rows if r["accession_number"] not in existing]
    to_update = [r for r in rows if r["accession_number"]     in existing]
    print(f"rows that will INSERT (new accessions):           {len(to_insert)}")
    print(f"rows that will UPDATE (NULL-fill existing rows):  {len(to_update)}")
    print()

    # For UPDATE preview: count which fields would actually change per row
    # (UPDATE with COALESCE is a no-op when DB column is already populated).
    if to_update:
        update_field_cols = [c for c, _ in RAILS_COLUMNS if c != "accession_number"]
        select_cols = ", ".join(update_field_cols)
        cur.execute(
            f"SELECT accession_number, {select_cols} FROM rails_patents "
            f"WHERE accession_number = ANY(%s)",
            ([r["accession_number"] for r in to_update],)
        )
        db_by_acc = {r[0]: dict(zip(update_field_cols, r[1:])) for r in cur.fetchall()}
        field_fill_counts = Counter()
        for r in to_update:
            db = db_by_acc.get(r["accession_number"], {})
            for col in update_field_cols:
                if db.get(col) is None and r.get(col) is not None:
                    field_fill_counts[col] += 1
        print("UPDATE preview — how many existing rows would gain a value per field:")
        if field_fill_counts:
            for col in update_field_cols:
                n = field_fill_counts.get(col, 0)
                if n:
                    print(f"  {col:<28s}  +{n}")
        else:
            print("  (no field gains — all UPDATE rows are already fully populated)")
        print()

    if not args.apply:
        print("DRY RUN — pass --apply to commit.")
        return

    # ── INSERT new rows ────────────────────────────────────────────────────
    if to_insert:
        cols   = [c for c, _ in RAILS_COLUMNS]
        col_list   = ", ".join(cols)
        placeholders = ", ".join(["%s"] * len(cols))
        sql = f"INSERT INTO rails_patents ({col_list}) VALUES ({placeholders})"
        values = [tuple(r[c] for c in cols) for r in to_insert]
        psycopg2.extras.execute_batch(cur, sql, values, page_size=200)
        print(f"  INSERTed {len(to_insert)} new rows")

    # ── UPDATE existing rows (NULL-fill only) ──────────────────────────────
    if to_update:
        update_cols = [c for c, _ in RAILS_COLUMNS if c != "accession_number"]
        set_clause = ", ".join(f"{c} = COALESCE({c}, %s)" for c in update_cols)
        sql = f"UPDATE rails_patents SET {set_clause} WHERE accession_number = %s"
        values = [tuple(r[c] for c in update_cols) + (r["accession_number"],)
                  for r in to_update]
        psycopg2.extras.execute_batch(cur, sql, values, page_size=200)
        print(f"  UPDATEd {len(to_update)} existing rows (NULL-fill semantics)")

    conn.commit()

    # Final summary
    cur.execute("SELECT COUNT(*) FROM rails_patents WHERE accession_number = ANY(%s)", (accs,))
    print(f"  rails_patents now contains {cur.fetchone()[0]} of the {len(accs)} ok accessions")


if __name__ == "__main__":
    main()
