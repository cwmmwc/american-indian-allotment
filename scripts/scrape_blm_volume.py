"""
Phase 1+ of the gappy-volume re-scrape: scrape every accession in a single
state-volume range from glorecords.blm.gov, save metadata to CSV, save raw
HTML for spot-checking, and report scrape-vs-DB agreement on the records we
already have.

Default target is SD2610 (the volume whose gap surfaced Helena Larvie's
missing record). Probes SD2610__.001 through SD2610__.550 (50 beyond the
observed max of .483 in case BLM has records past where our DB stops).

For each accession:
  GET the BLM detail page
  classify as ok / not_found / error
  for ok: extract all fields via scripts.blm_extract.extract_all()
  append a row to <out_csv>
  save the raw HTML to <html_dir>/<accession>.html
  sleep DELAY seconds

Resumable: rows already in the output CSV are skipped on rerun.

At the end: comparison report against rails_patents. For each ok accession
that exists in rails_patents, count exact-matches per field, disagreements,
and DB-was-NULL-but-scrape-has-value cases. That comparison is the
extraction-correctness validation — if extract_all() is wrong, the known
ground-truth rows will reveal it.

Run yourself; this issues real GETs to BLM at ~3s/request. SD2610 = 550
probes = ~30 min.

Usage:
    ./venv/bin/python3 scripts/scrape_blm_volume.py
    ./venv/bin/python3 scripts/scrape_blm_volume.py --volume SD2620__ --min 1 --max 550
    ./venv/bin/python3 scripts/scrape_blm_volume.py --volume NE1360__ --doc-class STA --delay 4
"""
import argparse
import csv
import os
import sys
import time
import urllib.request
import urllib.error
import psycopg2
import psycopg2.extras

from blm_extract import extract_all, page_is_not_found, ID_FIELDS

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

OUTPUT_FIELDS = [
    "accession_number", "status",
    "full_name", "signature_date", "state", "document_class", "document_code",
    "indian_allotment_number", "glo_tribe_name", "remarks",
    "authority", "land_office", "document_number", "misc_document_number",
    "blm_serial_number", "total_acres", "survey_date", "geographic_name",
    "metes_bounds",
]


def http_get(url, timeout=30):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read().decode("utf-8", errors="replace")


def already_scraped(csv_path):
    """Return the set of accession_numbers already in the output CSV."""
    if not os.path.exists(csv_path):
        return set()
    with open(csv_path) as f:
        return {row["accession_number"] for row in csv.DictReader(f)}


def append_row(csv_path, row):
    file_exists = os.path.exists(csv_path)
    with open(csv_path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=OUTPUT_FIELDS)
        if not file_exists:
            w.writeheader()
        # Only write the fields we know about
        clean = {k: row.get(k) for k in OUTPUT_FIELDS}
        w.writerow(clean)


def fetch_one(accession, doc_class, html_dir):
    url = DETAILS.format(acc=accession, dc=doc_class)
    try:
        status, html = http_get(url)
    except urllib.error.HTTPError as e:
        return {"accession_number": accession, "status": f"http_{e.code}"}
    except Exception as e:
        return {"accession_number": accession, "status": f"error:{type(e).__name__}"}

    # Save raw HTML for spot-checking
    html_path = os.path.join(html_dir, f"{accession}.html")
    with open(html_path, "w") as f:
        f.write(html)

    if status != 200:
        return {"accession_number": accession, "status": f"http_{status}"}

    if page_is_not_found(html):
        return {"accession_number": accession, "status": "not_found"}

    fields = extract_all(html, doc_class)
    fields["accession_number"] = accession
    fields["status"] = "ok"
    return fields


def compare_against_db(csv_path):
    """Read the output CSV; for each ok row whose accession is in rails_patents,
    compute per-field agreement and report counts. This is the extraction-
    correctness validation."""
    if not os.path.exists(csv_path):
        return
    with open(csv_path) as f:
        rows = [r for r in csv.DictReader(f) if r["status"] == "ok"]
    accs = [r["accession_number"] for r in rows]
    if not accs:
        print("No ok rows to compare.")
        return

    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT accession_number, full_name, signature_date, state, document_class,
               document_code, indian_allotment_number, glo_tribe_name, remarks
        FROM rails_patents WHERE accession_number = ANY(%s)
    """, (accs,))
    db_by_acc = {r["accession_number"]: r for r in cur.fetchall()}
    cur.close(); conn.close()

    print()
    print(f"=== Scrape vs DB comparison ===")
    print(f"  ok rows scraped:           {len(rows)}")
    print(f"  of which in rails_patents: {len(db_by_acc)}")
    print(f"  net-new (not in DB):       {len(rows) - len(db_by_acc)}")
    print()

    compare_fields = [
        "full_name", "signature_date", "state", "document_class", "document_code",
        "indian_allotment_number", "glo_tribe_name", "remarks",
    ]
    # Per-field tallies
    tallies = {f: {"match": 0, "disagree": 0, "db_null_scrape_has": 0,
                   "db_has_scrape_null": 0, "both_null": 0} for f in compare_fields}
    disagreement_examples = {f: [] for f in compare_fields}

    for scraped in rows:
        acc = scraped["accession_number"]
        if acc not in db_by_acc:
            continue
        db = db_by_acc[acc]
        for field in compare_fields:
            s_val = (scraped.get(field) or "").strip()
            d_val = db.get(field)
            d_str = (str(d_val) if d_val is not None else "").strip()
            if not s_val and not d_str:
                tallies[field]["both_null"] += 1
            elif not d_str and s_val:
                tallies[field]["db_null_scrape_has"] += 1
            elif d_str and not s_val:
                tallies[field]["db_has_scrape_null"] += 1
            elif d_str.lower() == s_val.lower():
                tallies[field]["match"] += 1
            else:
                tallies[field]["disagree"] += 1
                if len(disagreement_examples[field]) < 5:
                    disagreement_examples[field].append((acc, d_str[:50], s_val[:50]))

    print(f"  {'field':<26s}  {'match':>6s}  {'disagree':>8s}  {'db_null+scrape':>14s}  {'db_has+scrape_null':>18s}  {'both_null':>9s}")
    for field in compare_fields:
        t = tallies[field]
        print(f"  {field:<26s}  {t['match']:>6}  {t['disagree']:>8}  {t['db_null_scrape_has']:>14}  {t['db_has_scrape_null']:>18}  {t['both_null']:>9}")
    print()
    any_disagree = False
    for field, examples in disagreement_examples.items():
        if examples:
            any_disagree = True
            print(f"  Sample disagreements on {field}:")
            for acc, db_v, scr_v in examples:
                print(f"    {acc:<14s}  db={db_v!r:<55s}  scrape={scr_v!r}")
            print()
    if not any_disagree:
        print("  No disagreements on any field. Extraction validated against ground truth.")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--volume",      default="SD2610__",
                    help="Volume prefix, e.g. SD2610__")
    ap.add_argument("--min",         type=int, default=1)
    ap.add_argument("--max",         type=int, default=550)
    ap.add_argument("--doc-class",   default="STA")
    ap.add_argument("--delay",       type=float, default=3.0,
                    help="seconds between requests")
    ap.add_argument("--out-csv",     default=None,
                    help="output CSV (default: data/rescrape_<VOLUME>.csv)")
    ap.add_argument("--html-dir",    default=None,
                    help="raw HTML output dir (default: data/blm_html_<VOLUME>/)")
    ap.add_argument("--compare-only", action="store_true",
                    help="skip scraping; just rerun the scrape-vs-DB comparison")
    args = ap.parse_args()

    vol_clean = args.volume.rstrip("_")
    out_csv  = args.out_csv  or f"data/rescrape_{vol_clean}.csv"
    html_dir = args.html_dir or f"data/blm_html_{vol_clean}/"
    os.makedirs(os.path.dirname(out_csv), exist_ok=True)
    os.makedirs(html_dir, exist_ok=True)

    if args.compare_only:
        compare_against_db(out_csv)
        return

    done = already_scraped(out_csv)
    todo = []
    for n in range(args.min, args.max + 1):
        acc = f"{args.volume}.{n:03d}"
        if acc not in done:
            todo.append((n, acc))

    print(f"=== BLM volume scrape ===")
    print(f"  Volume:      {args.volume}")
    print(f"  Range:       .{args.min:03d} – .{args.max:03d}  ({args.max - args.min + 1} accessions)")
    print(f"  Already in:  {len(done)}")
    print(f"  To scrape:   {len(todo)}")
    print(f"  Delay:       {args.delay}s/request → est. {int(len(todo) * args.delay // 60)} min")
    print(f"  Output:      {out_csv}")
    print(f"  HTML dir:    {html_dir}")
    print()

    if not todo:
        print("Nothing to do. Run with --compare-only to see the comparison.")
        compare_against_db(out_csv)
        return

    for i, (n, acc) in enumerate(todo, 1):
        result = fetch_one(acc, args.doc_class, html_dir)
        append_row(out_csv, result)
        status = result.get("status", "?")
        name = (result.get("full_name") or "")[:30]
        # one-line live log
        print(f"  [{i:>4}/{len(todo)}] {acc:<14s}  {status:<12s}  {name}")
        if i < len(todo):
            time.sleep(args.delay)

    compare_against_db(out_csv)


if __name__ == "__main__":
    main()
