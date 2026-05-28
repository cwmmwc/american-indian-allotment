"""
Create and populate document_class_metadata — a small table that captures
known facts about BLM document classes (the doc_code values like SS, SER,
STA, MV, IA, etc.). For each entry the table records:

  - legal_instrument_name : BLM's canonical Document Type label
                            (e.g. "Sioux Scrip Patent" for doc_code='SS')
  - default_tribe_label   : When the spreadsheet's GLO→tribe crosswalk
                            returns FRN for records of this doc class
                            but the document class itself implies a known
                            higher-level grouping (e.g. SS patents all
                            went to recipients identified in the 1854 Act
                            as "the half breeds or mixed bloods of the
                            Dacotah or Sioux nation of Indians"), this
                            field carries the umbrella label.
                            The app uses it to replace 'Frn' in the
                            displayed tribe when a default is available.
  - notes                 : Free-form historical / provenance notes.

This table is independent of tribe_crosswalk (which is keyed by GLO name).
The spreadsheet can be edited and the crosswalk rebuilt without affecting
this table, and vice versa.

Idempotent — DROPs and rebuilds.

Usage:
    ./venv/bin/python3 scripts/build_document_class_metadata.py
    DATABASE_URL="host=127.0.0.1 port=5433 dbname=allotment_research user=appuser password=allotment-app-2026" \\
        ./venv/bin/python3 scripts/build_document_class_metadata.py
"""
import os
import psycopg2

DB_URL = os.environ.get("DATABASE_URL", "dbname=allotment_research user=cwm6W")


SS_NOTES = (
    'BLM Document Type for these records is "Sioux Scrip Patent". '
    'The patent recital quotes the originating statute: '
    '"WHEREAS, By the act of Congress, approved on the 17th day of July, 1854, '
    'entitled \'An act to authorize the PRESIDENT of the UNITED STATES to cause '
    'to be surveyed the tract of land in the Territory of Minnesota belonging '
    'to the half breeds or mixed bloods of the Dacotah or Sioux nation of '
    'Indians, and for other purposes\', to which Congress passed an amendatory '
    'act, ..." '
    'BLM\'s "authority" field for SS records shows "Act of February 8, 1887 '
    '(24 Stat. 388) — Indian Allotment - General" across all issuance dates, '
    'including patents issued in 1864 (e.g. accession 0389-012, MARY ANGE) — '
    'well before the 1887 Dawes Act existed. We have not determined why BLM '
    'applies the 1887 label retroactively to pre-1887 issuances. The actual '
    'per-record issuance authority would require case-by-case research. '
    'The 3,025 Sioux Scrip Patents currently in the FRN-residual bucket are '
    'records whose specific Dakota band remains unresolved, but whose nation-'
    'level identity (Dacotah/Sioux Nation) is explicit in the patent text itself.'
)


def main():
    conn = psycopg2.connect(DB_URL)
    cur  = conn.cursor()

    cur.execute("DROP TABLE IF EXISTS document_class_metadata")
    cur.execute("""
        CREATE TABLE document_class_metadata (
            doc_code text PRIMARY KEY,
            legal_instrument_name text,
            default_tribe_label text,
            notes text
        )
    """)
    print("Created document_class_metadata table")

    cur.execute("""
        INSERT INTO document_class_metadata (doc_code, legal_instrument_name, default_tribe_label, notes)
        VALUES (%s, %s, %s, %s)
    """, ('SS', 'Sioux Scrip Patent', 'Dacotah/Sioux Nation', SS_NOTES))
    conn.commit()
    print("Inserted SS row")

    cur.execute("SELECT doc_code, legal_instrument_name, default_tribe_label FROM document_class_metadata")
    print()
    print("Current rows:")
    for r in cur.fetchall():
        print(f"  {r[0]}  {r[1]!r}  default_tribe={r[2]!r}")


if __name__ == "__main__":
    main()
