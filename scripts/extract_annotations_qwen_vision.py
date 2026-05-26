#!/usr/bin/env python3
"""
Qwen2.5-VL-72B vision extraction client for BLM patent PDFs.

Structurally a transcription of extraction-pipeline/run_qwen_vl_index_cards_full.py
(Loren's production-tested client for the NARA RG 60 index card extraction),
with two adaptations for this task:

  1. CSV-driven (one row per patent, one page per patent) instead of
     directory-walking-multi-page. The PDF being read is always page 1.
  2. The prompt and schema are our v5 prompt for BLM patent annotation
     extraction (top-left CCF references + middle-page fee/cancellation
     booleans), not the NARA DOJ index card prompt.

Everything else — server URL discovery, payload structure, tolerant JSON
parsing, ThreadPool concurrency, raw-failure debug dump — is the same as
the working NARA client. Per the project's discipline of adapting working
infrastructure rather than re-implementing.

Output is one merged JSON file with the same shape as the Sonnet/Gemma
outputs, so the existing compare_sonnet_vs_gemma_50.py script (and any
future merge code) reads Qwen output without modification.

Usage:
    VLLM_URL=http://host:8000/v1 \\
    PARALLEL=6 \\
    python3 scripts/extract_annotations_qwen_vision.py \\
        blm_benchmark_50.csv blm_pdfs annotation_v5_qwen_50.json
"""
import base64
import csv
import io
import json
import os
import sys
import time
import urllib.request
import urllib.error
from concurrent.futures import ThreadPoolExecutor, as_completed

import fitz  # PyMuPDF

# ─────────────────────────────────────────────────────────────────────────────
# Configuration
# ─────────────────────────────────────────────────────────────────────────────
CSV_PATH = sys.argv[1] if len(sys.argv) > 1 else "blm_benchmark_50.csv"
PDF_DIR  = sys.argv[2] if len(sys.argv) > 2 else "blm_pdfs"
OUT_PATH = sys.argv[3] if len(sys.argv) > 3 else "annotation_v5_qwen_50.json"

VLLM_URL    = os.environ.get("VLLM_URL", "http://localhost:8000/v1").rstrip("/")
MODEL_NAME  = os.environ.get("QWEN_MODEL", "qwen-vl-72b")
RENDER_DPI  = int(os.environ.get("DPI", "200"))   # 200 dpi matches Loren's client
PARALLEL    = int(os.environ.get("PARALLEL", "6"))
REQ_TIMEOUT = 300

# ─────────────────────────────────────────────────────────────────────────────
# v5 prompt and schema — kept in sync with scripts/extract_annotations_v4.py
# and scripts/extract_annotations_gemma_vision.py. If you change the prompt in
# any of those, mirror the change here so the three clients remain comparable.
# ─────────────────────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are reading scanned BLM Indian trust-patent documents from the late 19th and early 20th centuries. Each page is a printed federal grant of an allotment to a Native American individual.

You must extract TWO INDEPENDENT LAYERS of data. A page can have data in one layer, the other, both, or neither.

═══════════════════════════════════════════════════════════════════════════════
LAYER 1 — TOP-LEFT FORM-NUMBER BLOCK
═══════════════════════════════════════════════════════════════════════════════

The upper-left corner of patents in the BIA Central Classified Files era (1907+) typically carries:
  - One or more NNNNN-YY administrative references (4-6 digit letter number + dash + 2-digit year)
  - The allotment number (typically 1-4 digits, sometimes with a letter suffix like "242A")
  - Possibly other numeric content (long serials without year suffixes, form codes, etc.)

Some of those NNNNN-YY references will be marked with "I.O." (or variants: "IO", "I. O.", "Indian Office"). The I.O. mark identifies the reference as a Bureau of Indian Affairs Indian Office / Central Classified Files pointer.

Rules for top_left_form_block:
  1. Look ONLY in the upper-left corner of the page.
  2. references[] contains ONLY entries matching the NNNNN-YY format (4-6 digits, dash, 2-digit year). Numbers in other formats do NOT go in references.
  3. explicitly_labeled_io is true if and only if the number is accompanied by an "I.O.", "IO", "I. O.", "Indian Office", or unambiguous variant. label_text captures the exact label string.
  4. raw_block_text is a best-effort verbatim transcription of EVERYTHING visible in the top-left block.
  5. allotment_number is the short allotment identifier (typically 1-4 digits, optionally with letter suffix). Null if no allotment number is printed in this block.
  6. If the top-left block has no NNNNN-YY references, return references=[].
  7. DO NOT mistake printed BLM form codes for CCF references. Form codes appear in the top header of the printed template in patterns like `4-1063-R.`, `4-1042-R.`, `4-1063-B.`, `6-2179`, etc. — short digit groups separated by dashes, frequently with a single-letter suffix. The CCF reference format is different: a 4-6 digit letter number, a dash, and a TWO-DIGIT year suffix (e.g., `73344-08`, `49611-29`). A token like `1063` extracted from the form code `4-1063-R.` is NOT a CCF reference.

═══════════════════════════════════════════════════════════════════════════════
LAYER 2 — MIDDLE-PAGE OUTCOME (presence detection only)
═══════════════════════════════════════════════════════════════════════════════

Look in the MIDDLE of the page — between the printed land description and the printed "NOW KNOW YE..." paragraph — for TWO independent outcomes. Presence-only detection; do NOT transcribe numbers, dates, or text.

OUTCOME 1: fee_patent_issued
  A mark recording that the trust was later converted to a fee-simple patent. Its identifying signature is the phrase "Fee Patent Issued" or "Fee Pat. Issued". The mark may be a pre-printed label with handwritten fill-in, a stamp (sometimes inked or colored), or entirely handwritten. Presence of such a mark in the middle of the page sets this true.

OUTCOME 2: patent_cancelled
  A handwritten overlay applied diagonally across the printed body text in the middle of the page, with wording like "Cancelled by Application..." Cursive handwriting written ACROSS the printed body, not a discrete labeled block. Presence sets this true.

A Fee Patent Issued mark is a localized stamp or label in a confined area. A Cancellation is a sprawling diagonal handwritten phrase. They can both be present on the same page.

═══════════════════════════════════════════════════════════════════════════════
ANTI-LEAK RULE
═══════════════════════════════════════════════════════════════════════════════

Top-left content (CCF references, allotment number, form codes) is NEVER evidence of a fee patent conversion. fee_patent_issued requires a MIDDLE-PAGE mark with the "Fee Patent Issued" wording.

A page with NEITHER middle-page mark is the EXPECTED outcome for many patents. Do not invent fee or cancellation marks where they aren't present."""

USER_INSTRUCTION = """Extract both data layers from this trust patent page: the top-left form-number block AND the middle-page outcome flags (fee_patent_issued and patent_cancelled).

Return ONLY valid JSON matching this exact structure, no markdown fencing, no commentary, no explanation:

{
  "top_left_form_block": {
    "references": [{"letter_number": "...", "year_suffix": "...", "explicitly_labeled_io": true, "label_text": "..."}],
    "allotment_number": "..." or null,
    "raw_block_text": "..."
  },
  "middle_page_outcome": {
    "fee_patent_issued": true or false,
    "patent_cancelled": true or false
  },
  "page_legibility": "clear" or "partial" or "poor",
  "confidence": "high" or "medium" or "low",
  "notes": "..."
}

Use empty array [] for no references, null for missing allotment_number, empty string "" for empty raw_block_text or notes. Output ONLY the JSON object, starting with { and ending with }."""


# ─────────────────────────────────────────────────────────────────────────────
# Rendering + API call (transcribed from Loren's client)
# ─────────────────────────────────────────────────────────────────────────────

def render_pdf_first_page_png_b64(pdf_path, dpi=200):
    """Render page 1 of a PDF to a PNG, return base64-encoded bytes.
    DPI of 200 matches the Loren NARA-cards setup."""
    doc = fitz.open(pdf_path)
    page = doc[0]
    matrix = fitz.Matrix(dpi / 72, dpi / 72)
    pix = page.get_pixmap(matrix=matrix)
    png = pix.tobytes("png")
    doc.close()
    return base64.standard_b64encode(png).decode("utf-8")


def send_to_qwen(img_b64):
    """One image + the v5 prompt → vLLM. Returns (raw_text, usage_dict, elapsed_seconds).

    Same payload shape as Loren's NARA client: no response_format
    (vLLM 0.14.1 doesn't reliably honor it for multimodal models), JSON
    asked for in the prompt itself, tolerantly parsed downstream.
    """
    payload = json.dumps({
        "model": MODEL_NAME,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{img_b64}"}},
                    {"type": "text", "text": USER_INSTRUCTION},
                ],
            },
        ],
        "max_tokens": 4096,
        "temperature": 0.3,
    }).encode("utf-8")
    req = urllib.request.Request(
        f"{VLLM_URL}/chat/completions",
        data=payload, headers={"Content-Type": "application/json"},
    )
    start = time.time()
    resp = urllib.request.urlopen(req, timeout=REQ_TIMEOUT)
    elapsed = time.time() - start
    body = json.loads(resp.read().decode("utf-8"))
    raw_text = body["choices"][0]["message"]["content"]
    usage    = body.get("usage", {})
    return raw_text, usage, elapsed


def parse_json_response(text):
    """Tolerant JSON parser — transcribed verbatim from Loren's client."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        text = "\n".join(lines[1:])
        if text.endswith("```"):
            text = text[:-3]
        text = text.strip()
    first_brace = text.find("{")
    if first_brace > 0:
        text = text[first_brace:]
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


# ─────────────────────────────────────────────────────────────────────────────
# Per-row worker for the thread pool
# ─────────────────────────────────────────────────────────────────────────────

def process_one_row(row, pdf_dir, raw_failures_dir):
    acc = row["accession_number"]
    pdf_path = os.path.join(pdf_dir, f"{acc.replace('/', '_')}.pdf")
    result = {
        "accession_number": acc,
        "full_name":      row.get("full_name"),
        "signature_date": row.get("signature_date"),
        "state":          row.get("state"),
        "county":         row.get("county"),
        "authority":      row.get("authority"),
        "extraction":     None,
        "usage":          {"input": 0, "output": 0},
        "error":          None,
    }
    if not os.path.exists(pdf_path):
        result["error"] = "no PDF on disk"
        return result
    try:
        img_b64 = render_pdf_first_page_png_b64(pdf_path, dpi=RENDER_DPI)
    except Exception as e:
        result["error"] = f"render error: {e}"
        return result
    try:
        raw_text, usage, _elapsed = send_to_qwen(img_b64)
    except urllib.error.HTTPError as e:
        body = e.read().decode("utf-8", errors="replace")[:200]
        result["error"] = f"HTTP {e.code}: {body}"
        return result
    except Exception as e:
        result["error"] = f"server error: {type(e).__name__}: {e}"
        return result

    result["usage"] = {"input":  usage.get("prompt_tokens", 0),
                       "output": usage.get("completion_tokens", 0)}
    parsed = parse_json_response(raw_text)
    if parsed is None:
        result["error"] = "unparseable JSON"
        try:
            os.makedirs(raw_failures_dir, exist_ok=True)
            with open(os.path.join(raw_failures_dir, f"{acc}.txt"), "w") as f:
                f.write(raw_text)
        except Exception:
            pass
        return result
    result["extraction"] = parsed
    return result


# ─────────────────────────────────────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────────────────────────────────────

def load_existing(path):
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return {r["accession_number"]: r for r in json.load(f) if "accession_number" in r}


def save_all(rows_by_acc, path):
    with open(path, "w") as f:
        json.dump(list(rows_by_acc.values()), f, indent=2)


def summarize(r):
    ex = r.get("extraction") or {}
    tl = ex.get("top_left_form_block") or {}
    mp = ex.get("middle_page_outcome") or {}
    refs = tl.get("references", [])
    n_refs = len(refs)
    io_count = sum(1 for x in refs if x.get("explicitly_labeled_io"))
    fee  = "FEE"  if mp.get("fee_patent_issued") else "---"
    canc = "CANC" if mp.get("patent_cancelled")  else "----"
    conf = ex.get("confidence", "-")
    return f"[{fee}][{canc}]  top-left: {n_refs} refs ({io_count} I.O.)  conf={conf}"


def main():
    if not os.path.exists(CSV_PATH):
        sys.exit(f"Missing {CSV_PATH}")

    with open(CSV_PATH) as f:
        sample = list(csv.DictReader(f))
    existing = load_existing(OUT_PATH)
    raw_failures_dir = OUT_PATH + ".raw_failures"

    print(f"=== Qwen-VL vision extraction (v5 prompt, presence-only Layer 2) ===")
    print(f"CSV:                {CSV_PATH}")
    print(f"Output:             {OUT_PATH}")
    print(f"vLLM URL:           {VLLM_URL}")
    print(f"Model:              {MODEL_NAME}")
    print(f"Render DPI:         {RENDER_DPI}")
    print(f"Parallel workers:   {PARALLEL}")
    print(f"Sample size:        {len(sample)}")
    print(f"Already extracted:  {len(existing)}")
    print(flush=True)

    todo = [row for row in sample if row["accession_number"] not in existing]
    if not todo:
        print("Nothing to do; all rows already extracted.")
        return

    total_in = total_out = 0
    n_ok = n_fail = 0
    n_done = 0

    with ThreadPoolExecutor(max_workers=PARALLEL) as ex:
        futures = {ex.submit(process_one_row, row, PDF_DIR, raw_failures_dir): row
                   for row in todo}
        for fut in as_completed(futures):
            r = fut.result()
            n_done += 1
            acc = r["accession_number"]
            total_in  += r["usage"]["input"]
            total_out += r["usage"]["output"]
            if r["extraction"] is not None:
                n_ok += 1
                existing[acc] = r
                save_all(existing, OUT_PATH)
                print(f"[{n_done}/{len(todo)}] {acc:14s}  {summarize(r)}", flush=True)
            else:
                n_fail += 1
                print(f"[{n_done}/{len(todo)}] {acc:14s}  FAIL  {r['error']}", flush=True)

    print()
    print(f"=== Done ===")
    print(f"OK:    {n_ok}")
    print(f"FAIL:  {n_fail}")
    print(f"Input tokens:  {total_in}")
    print(f"Output tokens: {total_out}")
    print(f"Results: {OUT_PATH}")


if __name__ == "__main__":
    main()
