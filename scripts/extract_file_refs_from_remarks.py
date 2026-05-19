"""
Extract NNNNN-YY patent-file references from BLM `remarks` fields and populate
patent_file_references + patent_file_ref_links.

Scope: scans rails_patents, trust_patents, and fee_patents remarks. Skips
blm_allotment_patents (its remarks carry PLSS descriptions, not patent refs).

Captures three label variants of the same structural reference -- the label
is recorded as a TRANSCRIBER CLAIM, not as ground truth (see DATABASE.md
"Data Quality Caveats" for why the BLM "IO" label is unreliable):
  - "IO #NNNNN-YY" / "IO#NNNNN-YY" / "I.O. #NNNNN-YY"      -> context_label = 'IO'
  - "ADDITIONAL IO #NNNNN-YY"                              -> context_label = 'ADDITIONAL IO'
  - "ADDITIONAL DOCUMENT #NNNNN-YY"                        -> context_label = 'ADDITIONAL DOCUMENT'

Deliberately skipped:
  - "SEE SERIAL PATENT NR NNNNN-YY FOR FEE PATENT"         -- handled by parse_remarks_fee_refs.py
  - "SEE MISCELLANEOUS VOLUME NR NNNN-YY"                  -- patent-volume locator, not a file ref

Read/write on the database. Idempotent: re-running won't create duplicates
because of UNIQUE (letter_number, year_raw) on patent_file_references and
the UNIQUE constraint on patent_file_ref_links.

Usage:
    ./venv/bin/python3 scripts/extract_file_refs_from_remarks.py             # write
    ./venv/bin/python3 scripts/extract_file_refs_from_remarks.py --dry-run   # report only
"""
import os
import re
import sys
import psycopg2
import psycopg2.extras
from collections import Counter, defaultdict

DB_URL = os.environ.get("DATABASE_URL", "dbname=allotment_research user=cwm6W")
DRY_RUN = "--dry-run" in sys.argv

# Capture: (full_label, letter, year_2digit)
# Same archival file gets transcribed under at least three different labels
# (IO / BIA / DOCUMENT) by BLM operators -- the labels are noise, the number
# is the signal. Accept all variants and record which label was used.
IO_PATTERN = re.compile(
    r"(?P<label>"
    r"(?:ADDITIONAL\s+|ADDTIONAL\s+)?I\.?\s*O\.?"     # IO, I.O., ADDITIONAL IO  (ADDTIONAL = real typo in data)
    r"|(?:ADDITIONAL\s+|ADDTIONAL\s+)?B\.?\s*I\.?\s*A\.?"  # BIA, B.I.A., ADDITIONAL BIA
    r"|(?:ADDITIONAL\s+|ADDTIONAL\s+)?DOCUMENT"            # DOCUMENT, ADDITIONAL DOCUMENT
    r")"
    r"\s*#?\s*"
    r"(?P<letter>\d{4,6})"
    r"-"
    r"(?P<year>\d{2})"
    r"\b",
    re.IGNORECASE,
)

# Tables to scan (table_name, accession_column)
SOURCE_TABLES = [
    ("rails_patents",  "accession_number"),
    ("trust_patents",  "accession_number"),
    ("fee_patents",    "accession_number"),
]


def four_digit_year(yy: str) -> int:
    """IO references appear on BLM patents issued 1880-1980s.
    The 2-digit year on those refs is always 19xx -- no pivot needed."""
    return 1900 + int(yy)


def normalize_label(label_raw: str) -> str:
    # Collapse punctuation/whitespace, fix the "ADDTIONAL" typo, then classify
    s = re.sub(r"[.\s]+", "", label_raw.upper()).replace("ADDTIONAL", "ADDITIONAL")
    additional = s.startswith("ADDITIONAL")
    if "DOCUMENT" in s:
        family = "DOCUMENT"
    elif "BIA" in s:
        family = "BIA"
    else:
        family = "IO"
    return f"ADDITIONAL {family}" if additional else family


def scan_table(cur, table: str, acc_col: str):
    """Yield extraction rows for `table`."""
    cur.execute(
        f"""
        SELECT {acc_col} AS acc, remarks
        FROM {table}
        WHERE remarks IS NOT NULL
          AND remarks <> ''
          AND remarks ~* '(I\\.?\\s*O\\.?|B\\.?\\s*I\\.?\\s*A\\.?|DOCUMENT)\\s*#?\\s*[0-9]{{4,6}}-[0-9]{{2}}'
        """
    )
    for row in cur.fetchall():
        acc = row["acc"]
        remarks = row["remarks"]
        for m in IO_PATTERN.finditer(remarks):
            yield {
                "acc": acc,
                "matched_text": m.group(0),
                "label": normalize_label(m.group("label")),
                "letter": m.group("letter"),
                "year_raw": m.group("year"),
                "table": table,
            }


def main():
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    label_counts = Counter()
    table_counts = Counter()
    distinct_refs = set()                    # (letter, year_raw)
    ref_to_patents = defaultdict(set)        # (letter, year_raw) -> set(accession)
    extractions = []

    print("Scanning patent remarks for NNNNN-YY file references...")
    print()
    for table, acc_col in SOURCE_TABLES:
        n_before = len(extractions)
        for ext in scan_table(cur, table, acc_col):
            extractions.append(ext)
            label_counts[ext["label"]] += 1
            table_counts[ext["table"]] += 1
            distinct_refs.add((ext["letter"], ext["year_raw"]))
            ref_to_patents[(ext["letter"], ext["year_raw"])].add(ext["acc"])
        print(f"  {table:22s}  {len(extractions) - n_before:>6,} extractions")

    print()
    print(f"Distinct (letter, year) pairs: {len(distinct_refs):,}")
    print(f"Total extractions:             {len(extractions):,}")
    print()
    print("Label breakdown (transcriber claim, not document truth):")
    for lab, n in label_counts.most_common():
        print(f"  {lab:24s}  {n:>6,}")

    print()
    print("Top shared file references (patents sharing the same letter+year):")
    top = sorted(ref_to_patents.items(), key=lambda kv: -len(kv[1]))[:15]
    for (letter, yr), patents in top:
        sample = sorted(patents)[:3]
        print(f"  {letter}-{yr}  -> {len(patents):>3} patents (e.g. {sample})")

    if DRY_RUN:
        print()
        print("DRY RUN -- no writes performed.")
        cur.close(); conn.close()
        return

    print()
    print("Writing patent_file_references...")
    write_cur = conn.cursor()
    for letter, year_raw in distinct_refs:
        write_cur.execute(
            """
            INSERT INTO patent_file_references (letter_number, year, year_raw)
            VALUES (%s, %s, %s)
            ON CONFLICT (letter_number, year_raw) DO NOTHING
            """,
            (letter, four_digit_year(year_raw), year_raw),
        )
    conn.commit()

    write_cur.execute("SELECT id, letter_number, year_raw FROM patent_file_references")
    ref_id_map = {(r[1], r[2]): r[0] for r in write_cur.fetchall()}
    print(f"  patent_file_references now has {len(ref_id_map):,} rows")

    print("Writing patent_file_ref_links...")
    inserted = 0
    skipped_dupes = 0
    for ext in extractions:
        ref_id = ref_id_map[(ext["letter"], ext["year_raw"])]
        write_cur.execute(
            """
            INSERT INTO patent_file_ref_links
                (patent_accession, file_ref_id, context_label,
                 source_location, source_table, matched_text)
            VALUES (%s, %s, %s, 'remarks', %s, %s)
            ON CONFLICT (patent_accession, file_ref_id, context_label, source_location)
            DO NOTHING
            """,
            (ext["acc"], ref_id, ext["label"], ext["table"], ext["matched_text"]),
        )
        if write_cur.rowcount:
            inserted += 1
        else:
            skipped_dupes += 1
    conn.commit()

    print(f"  inserted: {inserted:,}")
    print(f"  skipped (already present): {skipped_dupes:,}")

    write_cur.execute("SELECT COUNT(*) FROM patent_file_references")
    n_refs = write_cur.fetchone()[0]
    write_cur.execute("SELECT COUNT(*) FROM patent_file_ref_links")
    n_links = write_cur.fetchone()[0]
    write_cur.execute("SELECT COUNT(DISTINCT patent_accession) FROM patent_file_ref_links")
    n_distinct_patents = write_cur.fetchone()[0]
    print()
    print(f"=== Final state ===")
    print(f"  patent_file_references:   {n_refs:,}")
    print(f"  patent_file_ref_links:    {n_links:,}")
    print(f"  distinct patents w/ >=1 ref: {n_distinct_patents:,}")

    write_cur.close()
    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
