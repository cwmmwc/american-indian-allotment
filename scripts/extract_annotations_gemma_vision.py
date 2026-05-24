"""
Gemma 3 27B vision extraction client for BLM patent PDFs.

Talks to a local vLLM OpenAI-compatible server (started by the SLURM job in
hpc/run_gemma_blm_benchmark.slurm). Uses the SAME v5 prompt and schema as
scripts/extract_annotations_v4.py so the outputs are directly comparable to
the Anthropic Opus / Sonnet runs.

Inputs are PDF pages rendered as PNG images via PyMuPDF and sent as base64
inline_data in the chat completion message. Gemma 3 is natively multimodal;
vLLM serves it through the standard OpenAI-compatible /v1/chat/completions
endpoint with image_url content.

Usage (typically invoked from the SLURM script):
    VLLM_URL=http://localhost:8000/v1 \\
    GEMMA_MODEL=google/gemma-3-27b-it \\
    python3 scripts/extract_annotations_gemma_vision.py \\
        blm_benchmark_50.csv blm_pdfs annotation_v5_gemma_50.json

Environment variables:
    VLLM_URL      — vLLM server URL (default: http://localhost:8000/v1)
    GEMMA_MODEL   — model identifier (default: google/gemma-3-27b-it)
    DPI           — render resolution for PDF pages (default: 150)
"""
import os
import sys
import csv
import json
import base64
import time
import io
import urllib.request
import urllib.error

# PyMuPDF for PDF -> image rendering. Available on HPC via pip install pymupdf.
import fitz

CSV_PATH = sys.argv[1] if len(sys.argv) > 1 else "blm_benchmark_50.csv"
PDF_DIR  = sys.argv[2] if len(sys.argv) > 2 else "blm_pdfs"
OUT_PATH = sys.argv[3] if len(sys.argv) > 3 else "annotation_v5_gemma_50.json"

VLLM_URL    = os.environ.get("VLLM_URL", "http://localhost:8000/v1").rstrip("/")
MODEL_NAME  = os.environ.get("GEMMA_MODEL", "google/gemma-3-27b-it")
RENDER_DPI  = int(os.environ.get("DPI", "150"))
REQ_TIMEOUT = 180

# ─────────────────────────────────────────────────────────────────────────────
# v5 prompt and schema — KEPT IN SYNC WITH scripts/extract_annotations_v4.py.
# If you change the v5 prompt or schema in the Anthropic extractor, mirror the
# changes here so Gemma's outputs stay comparable. Both scripts are intentional
# duplicates for now; refactor to a shared module if v6 is added.
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

REFERENCE_SCHEMA = {
    "type": "object",
    "properties": {
        "letter_number":         {"type": "string"},
        "year_suffix":           {"type": "string"},
        "explicitly_labeled_io": {"type": "boolean"},
        "label_text":            {"type": ["string", "null"]},
    },
    "required": ["letter_number", "year_suffix", "explicitly_labeled_io", "label_text"],
    "additionalProperties": False,
}

SCHEMA = {
    "type": "object",
    "properties": {
        "top_left_form_block": {
            "type": "object",
            "properties": {
                "references":      {"type": "array", "items": REFERENCE_SCHEMA},
                "allotment_number": {"type": ["string", "null"]},
                "raw_block_text":   {"type": "string"},
            },
            "required": ["references", "allotment_number", "raw_block_text"],
            "additionalProperties": False,
        },
        "middle_page_outcome": {
            "type": "object",
            "properties": {
                "fee_patent_issued": {"type": "boolean"},
                "patent_cancelled":  {"type": "boolean"},
            },
            "required": ["fee_patent_issued", "patent_cancelled"],
            "additionalProperties": False,
        },
        "page_legibility": {"type": "string", "enum": ["clear", "partial", "poor"]},
        "confidence":      {"type": "string", "enum": ["high", "medium", "low"]},
        "notes":           {"type": "string"},
    },
    "required": ["top_left_form_block", "middle_page_outcome", "page_legibility", "confidence", "notes"],
    "additionalProperties": False,
}


def render_pdf_first_page_png_b64(pdf_path, dpi=150):
    """Render page 1 of a PDF to a PNG, return base64-encoded bytes."""
    doc = fitz.open(pdf_path)
    page = doc[0]
    pix = page.get_pixmap(dpi=dpi)
    png_bytes = pix.tobytes("png")
    doc.close()
    return base64.b64encode(png_bytes).decode("ascii")


def call_gemma(img_b64):
    """Send one image + the v5 prompt to vLLM.

    Adapted from extraction-pipeline/run_qwen_vl_index_cards_full.py — the proven
    pattern for vLLM 0.14.1 multimodal serving. Does NOT use response_format
    (which is not reliably honored for Gemma 3 in vLLM 0.14.1). Instead asks
    for JSON in the prompt and parses tolerantly on the way out.

    Returns (parsed_dict_or_none, raw_text, usage_dict).
    """
    payload = {
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
    }
    req = urllib.request.Request(
        f"{VLLM_URL}/chat/completions",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=REQ_TIMEOUT) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    raw_text = body["choices"][0]["message"]["content"]
    parsed = parse_json_response(raw_text)
    usage = body.get("usage", {})
    return parsed, raw_text, usage


def parse_json_response(text):
    """Tolerant JSON parser (pattern from extraction-pipeline qwen client).
    Strips markdown fences, slices from first '{', returns None on failure."""
    text = text.strip()
    if text.startswith("```"):
        # Drop the opening fence line and the closing fence if present.
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


def load_existing(path):
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return {row["accession_number"]: row for row in json.load(f)}


def save_all(rows_by_acc, path):
    with open(path, "w") as f:
        json.dump(list(rows_by_acc.values()), f, indent=2)


def summarize(extracted):
    tl = extracted.get("top_left_form_block", {})
    mp = extracted.get("middle_page_outcome", {})
    refs = tl.get("references", [])
    n_refs = len(refs)
    io_count = sum(1 for r in refs if r.get("explicitly_labeled_io"))
    fee = "FEE" if mp.get("fee_patent_issued") else "---"
    canc = "CANC" if mp.get("patent_cancelled") else "----"
    conf = extracted.get("confidence", "-")
    return f"[{fee}][{canc}]  top-left: {n_refs} refs ({io_count} I.O.)  conf={conf}"


def main():
    if not os.path.exists(CSV_PATH):
        sys.exit(f"Missing {CSV_PATH}")

    with open(CSV_PATH) as f:
        sample = list(csv.DictReader(f))
    existing = load_existing(OUT_PATH)

    print(f"=== Gemma vision extraction (v5 prompt, presence-only Layer 2) ===")
    print(f"CSV:                {CSV_PATH}")
    print(f"Output:             {OUT_PATH}")
    print(f"vLLM URL:           {VLLM_URL}")
    print(f"Model:              {MODEL_NAME}")
    print(f"Render DPI:         {RENDER_DPI}")
    print(f"Sample size:        {len(sample)}")
    print(f"Already extracted:  {len(existing)}")
    print()

    total_in = total_out = 0
    for i, row in enumerate(sample, 1):
        acc = row["accession_number"]
        pdf_path = os.path.join(PDF_DIR, f"{acc.replace('/', '_')}.pdf")
        if acc in existing:
            print(f"[{i}/{len(sample)}] {acc:14s}  SKIP (already extracted)")
            continue
        if not os.path.exists(pdf_path):
            print(f"[{i}/{len(sample)}] {acc:14s}  SKIP (no PDF on disk)")
            continue

        print(f"[{i}/{len(sample)}] {acc:14s}  ", end="", flush=True)
        try:
            img_b64 = render_pdf_first_page_png_b64(pdf_path, dpi=RENDER_DPI)
            extracted, raw_text, usage = call_gemma(img_b64)
            total_in  += usage.get("prompt_tokens", 0)
            total_out += usage.get("completion_tokens", 0)

            if extracted is None:
                # JSON parse failed. Save the raw response to a sidecar for
                # debugging without losing the rest of the run.
                debug_path = OUT_PATH + f".raw_{acc}.txt"
                with open(debug_path, "w") as df:
                    df.write(raw_text)
                print(f"FAIL  unparseable JSON ({len(raw_text)} chars); saved raw to {debug_path}")
                continue

            existing[acc] = {
                "accession_number": acc,
                "full_name":      row.get("full_name"),
                "signature_date": row.get("signature_date"),
                "state":          row.get("state"),
                "county":         row.get("county"),
                "authority":      row.get("authority"),
                "extraction":     extracted,
                "usage":          {"input": usage.get("prompt_tokens", 0),
                                   "output": usage.get("completion_tokens", 0)},
            }
            save_all(existing, OUT_PATH)
            print(summarize(extracted))
        except urllib.error.HTTPError as e:
            err_body = e.read().decode("utf-8", errors="replace")[:200]
            print(f"FAIL  HTTP {e.code}: {err_body}")
            time.sleep(5)
        except Exception as e:
            print(f"FAIL  {type(e).__name__}: {e}")

    print()
    print(f"=== Done ===")
    print(f"Input tokens:  {total_in}")
    print(f"Output tokens: {total_out}")
    print(f"Results: {OUT_PATH}")


if __name__ == "__main__":
    main()
