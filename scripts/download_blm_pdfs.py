"""
Download BLM patent PDFs for the accessions listed in
blm_sample_missing_allotment.csv (created by select_missing_allotment_sample.py).

Flow per patent:
  1. GET the details page -> extract var imageURL = '...getImage.ashx?...&key=XXX'
  2. GET that imageURL -> parse JSON for conversionStatus.
       - READY: extract imageFileLink (the PDF URL), GET it, save to disk.
       - Otherwise: wait 5s, retry up to MAX_POLLS times.
  3. Save PDF as blm_pdfs/{accession}.pdf

Polite:
  - 5-second pause between distinct patents.
  - 5-second poll interval for PDF generation.
  - Resumable: skips PDFs already on disk.
  - Identifies institutional researcher in User-Agent.
  - Stops on 403 (assumed block) or repeated failure.

Run yourself; this issues real GETs to BLM.

Usage:
    ./venv/bin/python3 scripts/download_blm_pdfs.py [csv_path]

If csv_path is omitted, defaults to blm_sample_missing_allotment.csv.
"""
import os
import re
import csv
import sys
import json
import time
import urllib.request
import urllib.error
from urllib.parse import urljoin

CSV_PATH = sys.argv[1] if len(sys.argv) > 1 else "blm_sample_missing_allotment.csv"
OUT_DIR = "blm_pdfs"
LOG_PATH = "blm_pdfs/_download_log.txt"
BLM_BASE = "https://glorecords.blm.gov"
DETAILS_URL = BLM_BASE + "/details/patent/default.aspx?accession={acc}&docClass={dc}"

HEADERS = {
    "User-Agent": (
        "IATH-Allotment-Research/0.1 (https://land-sales.iath.virginia.edu; "
        "research; contact christian.w.mcmillen@gmail.com)"
    ),
    "Accept": "text/html,application/json,application/pdf,*/*;q=0.7",
    "Accept-Language": "en-US,en;q=0.9",
}

PATENT_DELAY = 5   # seconds between distinct patents
POLL_DELAY   = 5   # seconds between PDF-generation polls
MAX_POLLS    = 12  # ~60 seconds max wait for PDF


def http_get(url, timeout=30):
    req = urllib.request.Request(url, headers=HEADERS)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.status, resp.read()


def extract_image_url(details_html):
    """Pull out: var imageURL = 'https://glorecords.blm.gov/WebServices/getImage.ashx?...';"""
    m = re.search(r"var\s+imageURL\s*=\s*'([^']+)'", details_html)
    if not m:
        return None
    return m.group(1)


def parse_conversion_response(body_bytes):
    """The response is JSON-ish (originally evaluated via eval() in JS).
    Try strict JSON first, then a permissive fallback."""
    text = body_bytes.decode("utf-8", errors="replace").strip()
    # Try JSON
    try:
        return json.loads(text)
    except Exception:
        pass
    # Fallback: pull fields by regex
    status_m = re.search(r"conversionStatus\s*[:=]\s*['\"]?([A-Z_]+)['\"]?", text)
    link_m   = re.search(r"imageFileLink\s*[:=]\s*['\"]([^'\"]+)['\"]", text)
    err_m    = re.search(r"errorMessage\s*[:=]\s*['\"]([^'\"]*)['\"]", text)
    return {
        "conversionStatus": status_m.group(1) if status_m else None,
        "imageFileLink":    link_m.group(1)   if link_m   else None,
        "errorMessage":     err_m.group(1)    if err_m    else None,
        "_raw": text[:400],
    }


def log(msg):
    print(msg)
    with open(LOG_PATH, "a") as f:
        f.write(msg + "\n")


def download_one(acc, doc_code, full_name):
    """Returns ('ok', path) | ('skip', reason) | ('fail', reason)."""
    out_path = os.path.join(OUT_DIR, f"{acc.replace('/', '_')}.pdf")
    if os.path.exists(out_path) and os.path.getsize(out_path) > 1000:
        return ("skip", "already exists")

    # Step 1: details page
    details_url = DETAILS_URL.format(acc=acc, dc=doc_code)
    try:
        status, body = http_get(details_url)
    except urllib.error.HTTPError as e:
        return ("fail", f"details HTTP {e.code}")
    except Exception as e:
        return ("fail", f"details {type(e).__name__}: {e}")
    if status == 403:
        return ("fail", "details 403 (blocked?)")
    if status != 200:
        return ("fail", f"details status {status}")

    image_url = extract_image_url(body.decode("utf-8", errors="replace"))
    if not image_url:
        return ("fail", "no imageURL in details page")

    # Step 2: poll getImage.ashx until READY
    for poll in range(MAX_POLLS):
        try:
            status, body = http_get(image_url)
        except urllib.error.HTTPError as e:
            return ("fail", f"getImage HTTP {e.code}")
        except Exception as e:
            return ("fail", f"getImage {type(e).__name__}: {e}")
        if status != 200:
            return ("fail", f"getImage status {status}")

        info = parse_conversion_response(body)
        st = info.get("conversionStatus")
        if st == "READY":
            link = info.get("imageFileLink")
            if not link:
                return ("fail", "READY but no imageFileLink")
            # Resolve relative URLs
            if link.startswith("/"):
                link = BLM_BASE + link
            elif not link.startswith("http"):
                link = urljoin(BLM_BASE + "/", link)
            break
        elif st in ("FAILED", "ERROR"):
            return ("fail", f"conversion {st}: {info.get('errorMessage', '')}")
        else:
            # PROCESSING / CREATING / unknown — poll again
            time.sleep(POLL_DELAY)
    else:
        return ("fail", "timed out waiting for PDF")

    # Step 3: download PDF
    try:
        status, pdf_bytes = http_get(link, timeout=60)
    except urllib.error.HTTPError as e:
        return ("fail", f"pdf HTTP {e.code}")
    except Exception as e:
        return ("fail", f"pdf {type(e).__name__}: {e}")
    if status != 200:
        return ("fail", f"pdf status {status}")
    if len(pdf_bytes) < 1000:
        return ("fail", f"pdf too small ({len(pdf_bytes)} bytes)")
    # Quick sanity check
    if not pdf_bytes.startswith(b"%PDF"):
        return ("fail", f"not a PDF (first bytes: {pdf_bytes[:8]!r})")

    with open(out_path, "wb") as f:
        f.write(pdf_bytes)
    return ("ok", out_path)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    if not os.path.exists(CSV_PATH):
        sys.exit(f"Missing {CSV_PATH}. Run select_missing_allotment_sample.py first.")

    with open(CSV_PATH) as f:
        rows = list(csv.DictReader(f))

    # Build a fast lookup of accessions already on disk so we can skip them
    # in microseconds rather than paying a 5-second rate-limit wait per skip.
    already_have = {
        fn[:-4] for fn in os.listdir(OUT_DIR)
        if fn.endswith(".pdf")
    }

    log(f"=== BLM PDF download run, {len(rows)} patents ===")
    log(f"Output dir: {OUT_DIR}")
    log(f"Already on disk: {len(already_have):,} PDFs (will skip)")
    log("")

    counts = {"ok": 0, "skip": 0, "fail": 0}
    download_started = False
    for i, r in enumerate(rows, 1):
        acc = r["accession_number"]
        doc_code = r["document_code"]
        full_name = (r.get("full_name") or "")[:50]

        # Fast-path skip: no logging, no HTTP, no rate-limit sleep.
        # download_one() still does its own existence check as defense in depth.
        if acc.replace("/", "_") in already_have:
            counts["skip"] += 1
            continue

        if not download_started:
            log(f"Skipped {counts['skip']:,} already-downloaded entries; "
                f"starting real downloads at row {i}.")
            download_started = True

        log(f"[{i}/{len(rows)}] {doc_code:4s} acc={acc:14s} {full_name}")

        status, info = download_one(acc, doc_code, full_name)
        counts[status] += 1
        log(f"        -> {status.upper()}: {info}")

        if status == "fail" and "403" in info:
            log("Stopping early on 403.")
            break

        # Rate-limit only when we actually hit BLM — never on cached skips.
        if status != "skip":
            time.sleep(PATENT_DELAY)

    log("")
    log(f"=== Summary: ok={counts['ok']} skip={counts['skip']} fail={counts['fail']} ===")


if __name__ == "__main__":
    main()
