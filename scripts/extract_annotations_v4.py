"""
Vision pipeline v5 (2026-05-23): two-layer structured extraction from BLM
trust-patent PDFs, scoped to the research question.

The research question this extraction supports is: how many trust patents were
later converted to fee patents but where the conversion was only recorded as a
stamp on the original trust patent (and is NOT separately registered as a fee
patent in the database)? Answering that requires presence-detection on the
fee-conversion stamp, not transcription of the handwritten numbers inside it.

  LAYER 1 — Top-left form-number block
    The upper-left corner of the printed form carries 1-3 NNNNN-YY administrative
    references (BIA letter-number/year, sometimes labeled "I.O." for Indian
    Office / Central Classified Files) and the allotment number. v5 captures
    these as structured data, with an anti-pattern for printed form codes
    (e.g. `4-1063-R.`) so they don't leak into the CCF references list.

  LAYER 2 — Middle-page outcome (PRESENCE DETECTION ONLY)
    Two booleans: is there a "Fee Patent Issued" mark in the middle of the page,
    and is there a "Cancelled by Application" handwritten overlay across the
    body text. The numbers, dates, and text inside those marks are NOT
    transcribed in v5. Prior versions tried to transcribe the handwritten
    Letter No. and Patent No. inside the fee stamp; OCR accuracy was the
    bottleneck and the numbers were not actually needed for the analysis.
    v5 strips that work.

Changes from v4 to v5:
  - Layer 1 prompt adds explicit form-code anti-pattern (the `4-1063-R.` problem)
  - Layer 2 schema collapsed: removed fee_letter_number, fee_patent_number,
    fee_date, fee_evidence_form, cancellation_date, cancellation_text.
    Kept only fee_patent_issued (bool) and patent_cancelled (bool).
  - Layer 2 prompt rewritten as presence detection. No transcription guidance.

Why dual-layer matters:
  - Most trust patents in the CCF era (1907-1975) carry a top-left CCF reference.
    Capturing it for every patent we scrape — independent of whether the patent
    ever became a fee patent — is the bigger payload by an order of magnitude.
  - The two layers are independent: a patent that stayed in trust still has a
    top-left CCF reference; a patent that converted to fee has both.

See:
  - reference_trust_patent_page_anatomy.md (the two layers)
  - reference_nara_ccf_citation_conventions.md (NNNNN-YY → four-element citation)

Output: annotation_extractions_v4.json
Resumable.

Usage:
    ./venv/bin/python3 scripts/extract_annotations_v4.py [csv_path] [pdf_dir] [out_json]

Defaults:
    csv_path = blm_trust_sample_v3.csv
    pdf_dir  = blm_pdfs
    out_json = annotation_extractions_v4.json

Requires ANTHROPIC_API_KEY.
"""
import os
import sys
import csv
import json
import base64
import time
import anthropic

CSV_PATH = sys.argv[1] if len(sys.argv) > 1 else "blm_trust_sample_v3.csv"
PDF_DIR  = sys.argv[2] if len(sys.argv) > 2 else "blm_pdfs"
OUT_PATH = sys.argv[3] if len(sys.argv) > 3 else "annotation_extractions_v4.json"

# Model is configurable via the EXTRACT_MODEL env var so the same script can be
# run side-by-side against different models for benchmarking.
MODEL = os.environ.get("EXTRACT_MODEL", "claude-opus-4-7")

SYSTEM_PROMPT = """You are reading scanned BLM Indian trust-patent documents from the late 19th and early 20th centuries. Each page is a printed federal grant of an allotment to a Native American individual.

You must extract TWO INDEPENDENT LAYERS of data. A page can have data in one layer, the other, both, or neither.

═══════════════════════════════════════════════════════════════════════════════
LAYER 1 — TOP-LEFT FORM-NUMBER BLOCK
═══════════════════════════════════════════════════════════════════════════════

The upper-left corner of patents in the BIA Central Classified Files era (1907+) typically carries:
  - One or more NNNNN-YY administrative references (4-6 digit letter number + dash + 2-digit year)
  - The allotment number (typically 1-4 digits, sometimes with a letter suffix like "242A" or "650 A")
  - Possibly other numeric content (long serials without year suffixes, form codes, etc.)

This block appears on:
  - FEE patents issued in the CCF era (near-universal coverage)
  - TRUST patents issued 1907 or later (near-universal coverage)
  - It does NOT appear on pre-1907 trust patents (older bound-volume forms used a different layout — the top-left of those carries only the allotment number, or nothing)

Some of those NNNNN-YY references will be marked with "I.O." (or variants: "IO", "I. O.", "Indian Office"). The I.O. mark identifies the reference as a Bureau of Indian Affairs Indian Office / Central Classified Files pointer — the canonical BIA archival citation. Other NNNNN-YY entries in the same block may share the format but be from different administrative series and should be captured without the io flag set.

Examples (these are illustrations of structure, NOT a checklist of what every page has):
  • "14329-08 I.O."   → reference: letter_number="14329", year_suffix="08", explicitly_labeled_io=true, label_text="I.O."
  • "60798-08"        → reference: letter_number="60798", year_suffix="08", explicitly_labeled_io=false, label_text=null
  • "1025243"         → 7-digit, no year suffix: does NOT go in references; capture verbatim in raw_block_text
  • "735"             → allotment_number="735"
  • "242A"            → allotment_number="242A"

Rules for top_left_form_block:
  1. Look ONLY in the upper-left corner of the page — the printed form-number block.
  2. references[] contains ONLY entries matching the NNNNN-YY format (4-6 digits, dash, 2-digit year). Numbers in other formats do NOT go in references.
  3. explicitly_labeled_io is true if and only if the number is accompanied by an "I.O.", "IO", "I. O.", "Indian Office", or unambiguous variant. label_text captures the exact label string as it appears (or null if no label).
  4. raw_block_text contains a best-effort verbatim transcription of EVERYTHING you can see in the top-left block, including non-NNNNN-YY numbers, form codes, the allotment number, and any labels. This serves as audit data.
  5. allotment_number is the short allotment identifier (typically 1-4 digits plus optional letter suffix). Capture as printed. Null if the page has no allotment number printed in this block — some older Miscellaneous Volume forms (pre-1900s) do not carry an allotment number on the page itself; their allotment ID is in agency schedules elsewhere.
  6. If the top-left block has no NNNNN-YY references at all (older forms, or unclear scans), return references=[] — empty list, not nulls.
  7. DO NOT mistake printed BLM form codes for CCF references. Form codes appear in the top header of the printed template (often near the center, above the "The United States of America" title) in patterns like `4-1063-R.`, `4-1042-R.`, `4-1063-B.`, `6-2179`, etc. — short digit groups separated by dashes, frequently with a single-letter suffix (`-R.`, `-B.`, `-C.`). The CCF reference format is different: a 4-6 digit letter number, a dash, and a TWO-DIGIT year suffix (e.g., `73344-08`, `49611-29`, `87941-09`). A token like `1063` extracted from the form code `4-1063-R.` is NOT a CCF reference and must NOT appear in references[].

═══════════════════════════════════════════════════════════════════════════════
LAYER 2 — MIDDLE-PAGE OUTCOME (presence detection only)
═══════════════════════════════════════════════════════════════════════════════

Look in the MIDDLE of the page — between the printed land description and the printed "NOW KNOW YE..." paragraph — for TWO independent outcomes. You only need to determine WHETHER each is present. You do NOT need to transcribe any numbers, dates, or text associated with them. Presence-only detection.

OUTCOME 1: FEE PATENT ISSUED (`fee_patent_issued`)

A mark recording that the trust was later converted to a fee-simple patent. Its identifying signature is the phrase "Fee Patent Issued" or "Fee Pat. Issued". The mark may be a pre-printed label with handwritten fill-in, a stamp (sometimes inked or colored) with or without handwriting, or entirely handwritten. It may be rotated, partially worn, or stylized. The presence of any of those forms with the "Fee Patent Issued" or "Fee Pat. Issued" wording is enough to set `fee_patent_issued=true`. Set false if no such mark is visible in the middle of the page.

Why we only need presence: the purpose of this extraction is to count trust patents that were later converted to fee but where the fee conversion was only recorded as a stamp on the original trust patent (and never registered as a separate fee patent record in the database). The numbers and dates on the stamp are not needed for that count; the cross-referencing happens at the database level afterward.

OUTCOME 2: PATENT CANCELLED (`patent_cancelled`)

A handwritten overlay applied diagonally or at an angle ACROSS the printed boilerplate text in the middle of the page, with wording like "Cancelled by Appl[ication] [date] by Secretary of the Interior" or similar. Identifying signature: cursive handwriting written ACROSS (intersecting) the printed body of the patent, not a discrete labeled block. The text content of the overlay does not need to be transcribed; only the presence of such an overlay is being recorded.

DISTINGUISHING THE TWO

A Fee Patent Issued mark is a localized stamp or label in a confined area. A Cancellation is a sprawling diagonal handwritten phrase overlaid on the body text. They can both be present on the same page.

═══════════════════════════════════════════════════════════════════════════════
CRITICAL — ANTI-LEAK RULE BETWEEN THE TWO LAYERS
═══════════════════════════════════════════════════════════════════════════════

Top-left content (CCF references, allotment number, form codes) is NEVER evidence of a fee patent conversion. A fee-patent-issued mark requires:
  - The mark located in the MIDDLE of the page (not the top-left)
  - The phrase "Fee Patent Issued" (or "Fee Pat. Issued") on/near the mark
  - Or a clear printed-label-with-handwriting-fill of equivalent semantics

If you see a NNNNN-YY number in the top-left and NO middle-page mark, set fee_patent_issued=false. Top-left references are independent of middle-page outcomes.

NOT-TO-CONFUSE:
  - Do NOT confuse the printed footer "RECORD OF PATENTS: Patent Number ______" with a fee-conversion mark. The footer is THIS patent's own ID, not a conversion reference.
  - A Cancellation mark may LOOK busy and visually similar to a fee-conversion stamp at first glance. Use the wording test: "Cancelled" or "Cancelled by Appl" → cancellation. "Fee Patent Issued" → fee conversion. They are not the same.

═══════════════════════════════════════════════════════════════════════════════

A page with NEITHER middle-page mark — clean boilerplate with no stamps, no labels, no diagonal handwriting overlays — most likely indicates the allotment stayed in trust through the original allottee's life. This is the EXPECTED outcome for many patents. Do not invent fee or cancellation marks where they aren't present. A patent that stayed in trust will commonly STILL have a top-left form-number block with CCF/IO references — those are independent."""

USER_INSTRUCTION = "Extract both data layers from this trust patent page: the top-left form-number block (CCF/IO references + allotment number) AND the middle-page outcome (fee patent issued and/or cancellation)."

REFERENCE_SCHEMA = {
    "type": "object",
    "properties": {
        "letter_number": {
            "type": "string",
            "description": "The 4-6 digit letter number portion of the NNNNN-YY reference (digits only)."
        },
        "year_suffix": {
            "type": "string",
            "description": "The 2-digit year suffix portion of the NNNNN-YY reference."
        },
        "explicitly_labeled_io": {
            "type": "boolean",
            "description": "True if and only if this reference is accompanied by an 'I.O.', 'IO', 'I. O.', 'Indian Office', or unambiguous variant label."
        },
        "label_text": {
            "type": ["string", "null"],
            "description": "The exact label string as printed next to the number (e.g., 'I.O.'). Null if no label."
        }
    },
    "required": ["letter_number", "year_suffix", "explicitly_labeled_io", "label_text"],
    "additionalProperties": False
}

SCHEMA = {
    "type": "object",
    "properties": {
        "top_left_form_block": {
            "type": "object",
            "properties": {
                "references": {
                    "type": "array",
                    "items": REFERENCE_SCHEMA,
                    "description": "Zero or more NNNNN-YY references found in the top-left form-number block."
                },
                "allotment_number": {
                    "type": ["string", "null"],
                    "description": "Allotment number as printed in the top-left block (e.g., '735', '242A'). Null if not present on the page."
                },
                "raw_block_text": {
                    "type": "string",
                    "description": "Best-effort verbatim transcription of everything visible in the top-left form-number block. Empty string if the block is blank or absent."
                }
            },
            "required": ["references", "allotment_number", "raw_block_text"],
            "additionalProperties": False
        },
        "middle_page_outcome": {
            "type": "object",
            "properties": {
                "fee_patent_issued": {
                    "type": "boolean",
                    "description": "True if a 'Fee Patent Issued' (or 'Fee Pat. Issued') mark is present in the MIDDLE of the page (not the top-left). The numbers written on the stamp do not need to be transcribed; only the presence of the stamp is being recorded."
                },
                "patent_cancelled": {
                    "type": "boolean",
                    "description": "True if a 'Cancelled by Application' (or similar) handwritten overlay is present, written across the printed body text in the middle of the page. The text of the overlay does not need to be transcribed."
                }
            },
            "required": ["fee_patent_issued", "patent_cancelled"],
            "additionalProperties": False
        },
        "page_legibility": {
            "type": "string",
            "enum": ["clear", "partial", "poor"],
            "description": "Overall legibility of the page."
        },
        "confidence": {
            "type": "string",
            "enum": ["high", "medium", "low"],
            "description": "Confidence in the structured extraction overall."
        },
        "notes": {
            "type": "string",
            "description": "Brief observations about location, ambiguity, anomalies, or anything noteworthy. Empty string if nothing to add."
        }
    },
    "required": ["top_left_form_block", "middle_page_outcome", "page_legibility", "confidence", "notes"],
    "additionalProperties": False
}


def load_existing(path):
    if not os.path.exists(path):
        return {}
    with open(path) as f:
        return {row["accession_number"]: row for row in json.load(f)}


def save_all(rows_by_acc, path):
    with open(path, "w") as f:
        json.dump(list(rows_by_acc.values()), f, indent=2)


def encode_pdf(path):
    with open(path, "rb") as f:
        return base64.standard_b64encode(f.read()).decode("utf-8")


def call_model(client, pdf_b64):
    response = client.messages.create(
        model=MODEL,
        max_tokens=2500,
        system=SYSTEM_PROMPT,
        output_config={"format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{
            "role": "user",
            "content": [
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": "application/pdf",
                        "data": pdf_b64,
                    },
                },
                {"type": "text", "text": USER_INSTRUCTION},
            ],
        }],
    )
    text = next((b.text for b in response.content if b.type == "text"), None)
    if not text:
        raise RuntimeError("No text block in response")
    return json.loads(text), response.usage


def summarize_row(extracted):
    """One-line console summary for a row."""
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
    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("Set ANTHROPIC_API_KEY in the environment.")
    if not os.path.exists(CSV_PATH):
        sys.exit(f"Missing {CSV_PATH}.")

    client = anthropic.Anthropic()
    with open(CSV_PATH) as f:
        sample = list(csv.DictReader(f))
    existing = load_existing(OUT_PATH)

    print(f"=== Extract annotations (v4 — dual-layer: top-left + middle-page) ===")
    print(f"CSV:               {CSV_PATH}")
    print(f"Output:            {OUT_PATH}")
    print(f"Sample size:       {len(sample)}")
    print(f"Already extracted: {len(existing)}")
    print(f"Model:             {MODEL}")
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
            pdf_b64 = encode_pdf(pdf_path)
            extracted, usage = call_model(client, pdf_b64)
            total_in  += usage.input_tokens
            total_out += usage.output_tokens
            existing[acc] = {
                "accession_number": acc,
                "full_name":      row.get("full_name"),
                "signature_date": row.get("signature_date"),
                "state":          row.get("state"),
                "county":         row.get("county"),
                "authority":      row.get("authority"),
                "extraction": extracted,
                "usage": {"input": usage.input_tokens, "output": usage.output_tokens},
            }
            save_all(existing, OUT_PATH)
            print(summarize_row(extracted))
        except anthropic.APIStatusError as e:
            print(f"FAIL  API {e.status_code}: {e.message}")
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
