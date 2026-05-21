"""
Second recovery layer for trust→fee linkages.

The remarks-regex pass (parse_remarks_fee_refs.py + validate_remarks_extractions.py)
can only recover linkages where the BLM operator wrote a cross-reference in the
trust patent's remarks AND the accession number is transcribed correctly.

This script picks up two cases that regex cannot:
  - Bug 2: BLM transcription typo in the cross-reference itself (Lizzie Dowd's
    0505-453 remarks point at "0505-453" instead of the real fee MV-0580-454).
  - Bug 3: Trust patent remarks are empty, so there's no text to parse, but a
    fee patent for the same parcel + same allottee does exist in the catalog.

Matching strategy: join trust-class patents to fee-class patents on shared
parcel attributes (same state + county + township + range + section + aliquot
parts) AND name overlap (at least one shared token in the patentee names,
ignoring stop tokens like initials and titles). The fee patent must be dated
later than the trust patent.

Output: data/parcel_match_candidates.csv with the same column schema as
data/linkage_candidates.csv so the same loader can ingest both. `match_type`
is set to 'parcel_name' to distinguish from the regex layer.

Usage:
    ./venv/bin/python3 scripts/recover_linkages_by_parcel.py
"""
import csv
import os
import re
import sys
import psycopg2
import psycopg2.extras
from collections import defaultdict
from datetime import date

DB_URL  = os.environ.get("DATABASE_URL", "dbname=allotment_research user=cwm6W")
OUT_CSV = "data/parcel_match_candidates.csv"

TRUST_AUTHORITIES = (
    "Indian Trust Patent", "Indian Allotment - General",
    "Indian Reissue Trust", "Indian Homestead Trust",
    "Indian Allotment Patent", "Indian Trust Patent (Wind R)",
    "Indian Allotment-Wyandotte",
)
FEE_AUTHORITIES = (
    "Indian Fee Patent",
    "Indian Fee Patent (Heir)",
    "Indian Homestead Fee Patent",
    "Indian Trust to Fee",
)

# Name tokens that say nothing about identity — ignore for overlap test.
_STOP_NAME_TOKENS = {
    "JR", "SR", "II", "III", "IV", "MRS", "MR", "MISS", "DR",
    # Common single-letter initials would match anything; require 2+ chars.
}


def name_tokens(name):
    """Return uppercase tokens of length >=2 that aren't in the stop list."""
    if not name:
        return set()
    out = set()
    for tok in re.split(r"[\s,;./\-]+", name.upper()):
        tok = tok.strip().rstrip(".")
        if len(tok) < 2:
            continue
        if tok in _STOP_NAME_TOKENS:
            continue
        out.add(tok)
    return out


def parcel_key(r):
    """A tuple that uniquely identifies a parcel across patents."""
    return (
        r["state"] or "",
        r["county"] or "",
        r["township_number"] or "",
        r["township_direction"] or "",
        r["range_number"] or "",
        r["range_direction"] or "",
        r["meridian_code"] or "",
        r["section_number"] or "",
        (r["aliquot_parts"] or "").strip(),
    )


def main():
    conn = psycopg2.connect(DB_URL)
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    # Fetch all trust-class patents.
    print("Fetching trust-class patents from blm_allotment_patents...")
    cur.execute(f"""
        SELECT accession_number, full_name, signature_date, authority, state,
               county, township_number, township_direction,
               range_number, range_direction, meridian_code,
               section_number, aliquot_parts, indian_allotment_number
        FROM blm_allotment_patents
        WHERE authority IN %s
          AND aliquot_parts IS NOT NULL AND aliquot_parts <> ''
          AND section_number IS NOT NULL
    """, (TRUST_AUTHORITIES,))
    trusts = cur.fetchall()
    print(f"  {len(trusts):,} trust-class patents with PLSS coords")

    print("Fetching fee-class patents...")
    cur.execute(f"""
        SELECT accession_number, full_name, signature_date, authority, state,
               county, township_number, township_direction,
               range_number, range_direction, meridian_code,
               section_number, aliquot_parts, indian_allotment_number
        FROM blm_allotment_patents
        WHERE authority IN %s
          AND aliquot_parts IS NOT NULL AND aliquot_parts <> ''
          AND section_number IS NOT NULL
    """, (FEE_AUTHORITIES,))
    fees = cur.fetchall()
    print(f"  {len(fees):,} fee-class patents with PLSS coords")

    # Index fee patents by parcel key.
    print("Indexing fee patents by parcel key...")
    fees_by_parcel = defaultdict(list)
    for f in fees:
        fees_by_parcel[parcel_key(f)].append(f)
    print(f"  {len(fees_by_parcel):,} distinct fee-side parcels")

    # Also pull patents that have NO PLSS data (rails-only or BLM with missing
    # geom) so we can include the broader corpus for diagnostic counts later.

    candidates = []
    n_no_parcel_match = 0
    n_no_name_overlap = 0
    n_emitted = 0

    print("Matching trusts to fees by parcel + name overlap...")
    for t in trusts:
        key = parcel_key(t)
        if key not in fees_by_parcel:
            n_no_parcel_match += 1
            continue

        t_toks = name_tokens(t["full_name"])
        if not t_toks:
            n_no_name_overlap += 1
            continue

        for f in fees_by_parcel[key]:
            if t["accession_number"] == f["accession_number"]:
                continue  # never link to self
            if t["signature_date"] and f["signature_date"]:
                if f["signature_date"] < t["signature_date"]:
                    continue  # fee must come after trust

            f_toks = name_tokens(f["full_name"])
            shared = t_toks & f_toks
            if not shared:
                continue  # require name overlap

            date_gap = None
            if t["signature_date"] and f["signature_date"]:
                date_gap = (f["signature_date"] - t["signature_date"]).days // 365

            candidates.append({
                "trust_accession": t["accession_number"],
                "fee_accession":   f["accession_number"],
                "extracted_raw":   "(parcel+name match)",
                "match_type":      "parcel_name",
                "trust_name":      t["full_name"],
                "fee_name":        f["full_name"],
                "name_overlap":    ";".join(sorted(shared)),
                "name_consistent": "yes",
                "date_gap_years":  date_gap if date_gap is not None else "",
                "trust_date":      t["signature_date"].date().isoformat() if t["signature_date"] else "",
                "fee_date":        f["signature_date"].date().isoformat() if f["signature_date"] else "",
                "fee_authority":   f["authority"],
                "fee_state":       f["state"],
            })
            n_emitted += 1

    print(f"\n  trusts with no parcel match in fee side: {n_no_parcel_match:,}")
    print(f"  trusts with no usable name tokens:       {n_no_name_overlap:,}")
    print(f"  candidate (trust, fee) pairs emitted:    {n_emitted:,}")
    print(f"  distinct trusts covered: {len({c['trust_accession'] for c in candidates}):,}")
    print(f"  distinct fees   covered: {len({c['fee_accession']   for c in candidates}):,}")

    # Sanity check: did we find Lizzie Dowd?
    dowd = [c for c in candidates if c["trust_accession"] in ("0505-452", "0505-453")
                                     or c["fee_accession"]   == "0580-454"]
    if dowd:
        print("\n  Lizzie Dowd sanity check — recovered linkages:")
        for c in dowd:
            print(f"    {c['trust_accession']} -> {c['fee_accession']}  "
                  f"({c['trust_date']} -> {c['fee_date']}, gap={c['date_gap_years']}, "
                  f"shared={c['name_overlap']})")
    else:
        print("\n  Lizzie Dowd NOT FOUND — investigate before loading.")

    if not candidates:
        sys.exit("\nNo candidates produced — refusing to write empty CSV.")

    with open(OUT_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(candidates[0].keys()))
        w.writeheader()
        for row in candidates:
            w.writerow(row)
    print(f"\nWrote {OUT_CSV}  ({len(candidates):,} rows)")

    cur.close()
    conn.close()


if __name__ == "__main__":
    main()
