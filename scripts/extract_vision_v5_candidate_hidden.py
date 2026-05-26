"""
Extract candidate hidden fee conversions from a v5 vision-extraction output.

Filters a Sonnet (or any v5-schema) annotation JSON down to trust patents
where the model said `fee_patent_issued=true` AND whose accession is NOT
already present as `trust_accession` in trust_fee_linkages_recovered.
Those are the patents whose conversions aren't independently corroborated
by an existing remarks-regex or parcel-match linkage — i.e. the research
candidates worth a closer look before promoting to the DB.

Writes a CSV the user can skim before any DB load and before any optional
second-model cross-check.

Usage:
    ./venv/bin/python3 scripts/extract_vision_v5_candidate_hidden.py \\
        annotation_v5_sonnet_full.json \\
        data/vision_v5_sonnet_candidate_hidden.csv
"""
import csv
import json
import os
import sys
import psycopg2

DB_URL = os.environ.get("DATABASE_URL", "dbname=allotment_research user=cwm6W")


def main():
    if len(sys.argv) != 3:
        sys.exit(f"usage: {sys.argv[0]} <annotation_json> <out_csv>")
    in_json, out_csv = sys.argv[1], sys.argv[2]

    if not os.path.exists(in_json):
        sys.exit(f"missing {in_json}")

    with open(in_json) as f:
        rows = json.load(f)
    if not isinstance(rows, list):
        sys.exit("expected a list of annotation records")
    print(f"loaded {len(rows):,} annotation records from {in_json}")

    flagged = [
        r for r in rows
        if r.get("extraction", {}).get("middle_page_outcome", {}).get("fee_patent_issued")
    ]
    print(f"  flagged fee_patent_issued=true: {len(flagged):,}")

    conn = psycopg2.connect(DB_URL)
    cur  = conn.cursor()
    cur.execute("SELECT DISTINCT trust_accession FROM trust_fee_linkages_recovered")
    already_linked = {r[0] for r in cur.fetchall()}
    print(f"  trust_accessions already in trust_fee_linkages_recovered: {len(already_linked):,}")

    candidates = [
        r for r in flagged
        if r.get("accession_number") not in already_linked
    ]
    print(f"  → candidate hidden conversions (flagged AND not already linked): {len(candidates):,}")

    auth_counts = {}
    for c in candidates:
        a = (c.get("authority") or "").strip() or "(none)"
        auth_counts[a] = auth_counts.get(a, 0) + 1
    print()
    print("authority breakdown of candidate set:")
    for a, n in sorted(auth_counts.items(), key=lambda kv: -kv[1]):
        print(f"  {n:>4}  {a}")
    print()

    out_dir = os.path.dirname(out_csv)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    with open(out_csv, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "accession_number",
            "full_name",
            "signature_date",
            "state",
            "county",
            "authority",
            "patent_cancelled",
            "n_topleft_refs",
            "raw_block_text",
            "model_notes",
        ])
        for c in candidates:
            ex = c.get("extraction", {})
            mpo = ex.get("middle_page_outcome", {})
            tlb = ex.get("top_left_form_block", {})
            w.writerow([
                c.get("accession_number") or "",
                c.get("full_name") or "",
                c.get("signature_date") or "",
                c.get("state") or "",
                c.get("county") or "",
                c.get("authority") or "",
                "true" if mpo.get("patent_cancelled") else "false",
                len(tlb.get("references") or []),
                (tlb.get("raw_block_text") or "").replace("\n", " ")[:300],
                (ex.get("notes") or "").replace("\n", " ")[:300],
            ])
    print(f"wrote {len(candidates):,} rows to {out_csv}")


if __name__ == "__main__":
    main()
