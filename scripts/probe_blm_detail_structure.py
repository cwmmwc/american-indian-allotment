"""
Phase 0 of the gappy-volume re-scrape: probe a single BLM detail page to map
field locations in the HTML.

Picks a known-existing patent we already have in rails_patents (default
SD2610__.014 — sits in the SD2610 gappy zone, one of the 201 we managed to
import). Fetches the detail page, attempts metadata extraction via several
candidate patterns, prints a side-by-side comparison vs. the DB ground truth,
and saves the raw HTML for manual inspection.

The goal is to validate WHICH HTML patterns reliably yield WHICH fields
BEFORE committing 8 hours of BLM requests for the full re-scrape. If any
scraped field disagrees with the DB ground truth, the extraction is wrong
and we redesign here cheaply.

Run yourself; this issues a single real GET to BLM over ~5 seconds.

Usage:
    ./venv/bin/python3 scripts/probe_blm_detail_structure.py
    ./venv/bin/python3 scripts/probe_blm_detail_structure.py --accession SD2610__.083
    ./venv/bin/python3 scripts/probe_blm_detail_structure.py --accession SD2470__.253 --doc-class STA
"""
import argparse
import os
import re
import sys
import time
import urllib.request
import urllib.error
import psycopg2
import psycopg2.extras

from blm_extract import extract_all, ID_FIELDS

DB_URL    = os.environ.get("DATABASE_URL", "dbname=allotment_research user=cwm6W")
BLM_BASE  = "https://glorecords.blm.gov"
DETAILS   = BLM_BASE + "/details/patent/default.aspx?accession={acc}&docClass={dc}"

HEADERS = {
    "User-Agent": (
        "IATH-Allotment-Research/0.1 (https://land-sales.iath.virginia.edu; "
        "research; contact christian.w.mcmillen@gmail.com)"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.7",
    "Accept-Language": "en-US,en;q=0.9",
}


def http_get(url, timeout=30):
    req = urllib.request.Request(url, headers=HEADERS)
    t0 = time.time()
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        body = resp.read().decode("utf-8", errors="replace")
        status = resp.status
    return status, body, int((time.time() - t0) * 1000)


def ground_truth_from_db(accession):
    conn = psycopg2.connect(DB_URL)
    cur  = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT accession_number, full_name, signature_date, state,
               document_class, document_code, indian_allotment_number,
               glo_tribe_name, remarks
        FROM rails_patents
        WHERE accession_number = %s
    """, (accession,))
    row = cur.fetchone()
    cur.close(); conn.close()
    return row


# Extraction logic lives in scripts/blm_extract.py so this probe and the
# full-volume scraper (scrape_blm_volume.py) can't drift apart.


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--accession", default="SD2610__.014",
                    help="Accession to probe (must already exist in rails_patents)")
    ap.add_argument("--doc-class", default="STA",
                    help="BLM doc class code (STA / SER / MV / IA)")
    args = ap.parse_args()

    print(f"=== Phase 0 BLM detail-page structure probe ===")
    print(f"  Accession: {args.accession}")
    print(f"  DocClass:  {args.doc_class}")
    print()

    truth = ground_truth_from_db(args.accession)
    if not truth:
        sys.exit(f"missing {args.accession} in rails_patents — pick a different known-existing accession")
    print("Ground truth from rails_patents:")
    for k in ("full_name","signature_date","state","document_class","document_code",
              "indian_allotment_number","glo_tribe_name","remarks"):
        v = truth.get(k)
        v_str = (str(v)[:80] + "…") if v and len(str(v)) > 80 else str(v)
        print(f"  {k:28s}  {v_str}")
    print()

    url = DETAILS.format(acc=args.accession, dc=args.doc_class)
    print(f"GET {url}")
    try:
        status, html, elapsed_ms = http_get(url)
    except urllib.error.HTTPError as e:
        sys.exit(f"HTTP error {e.code}: {e.reason}")
    print(f"  status={status}  elapsed={elapsed_ms}ms  body={len(html):,} chars")
    print()

    out_path = f"data/blm_probe_{args.accession.replace('.','_')}.html"
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        f.write(html)
    print(f"Raw HTML saved to: {out_path}")
    print(f"  Open in a browser or grep through it manually to find the field labels")
    print(f"  the BLM page uses, so the FIELD_PATTERNS list can be refined.")
    print()

    scraped = extract_all(html, args.doc_class)

    # Side-by-side: only fields we have in BOTH the DB ground truth and the scrape
    compare_fields = [
        "full_name", "signature_date", "state", "document_class", "document_code",
        "indian_allotment_number", "glo_tribe_name", "remarks",
    ]
    print(f"=== Extraction vs. ground truth (DB-known fields) ===")
    print(f"  {'field':<28s}  {'truth':<35s}  {'scraped':<35s}  match?")
    any_miss = False
    for field in compare_fields:
        truth_val = truth.get(field)
        scraped_val = scraped.get(field)
        truth_s   = (str(truth_val)[:33] + "…") if truth_val and len(str(truth_val)) > 33 else str(truth_val)
        scraped_s = (str(scraped_val)[:33] + "…") if scraped_val and len(str(scraped_val)) > 33 else str(scraped_val)
        if truth_val is None and scraped_val is None:
            ok = "—"  # both empty, neutral
        elif str(truth_val or "").strip().lower() == str(scraped_val or "").strip().lower():
            ok = "✓"
        else:
            ok = "✗"
            any_miss = True
        print(f"  {field:<28s}  {truth_s:<35s}  {scraped_s:<35s}  {ok}")
    print()

    # Bonus: print ALL extracted fields so we see what's available beyond the DB schema
    print(f"=== All scraped fields (including ones not in rails_patents) ===")
    for field, val in scraped.items():
        val_s = (str(val)[:60] + "…") if val and len(str(val)) > 60 else str(val)
        print(f"  {field:<28s}  {val_s}")
    print()

    if any_miss:
        print("Some fields disagree. Inspect the saved HTML to refine the extraction.")
    else:
        print("All non-NULL DB fields extracted cleanly. Phase 1 (SD2610 smoke test) can proceed.")
        print("Recommend re-running this probe on one MORE record (default is a canceled-incomplete one);")
        print("pick a 'normal' record with a real signature_date to verify date extraction works there too.")


if __name__ == "__main__":
    main()
