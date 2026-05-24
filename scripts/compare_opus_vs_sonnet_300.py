"""
Compare two v4 extraction runs on the same 300-PDF sample.

Reads:
    annotation_v4_opus_300.json
    annotation_v4_sonnet_300.json

Reports:
    - per-model token usage (input + output)
    - per-model cost at current public list prices
    - agreement on top-left references (count, letter_number, IO flag)
    - agreement on middle-page fee patent issued flag
    - agreement on fee patent number / letter number / date when both say issued
    - agreement on patent cancelled flag
    - confidence-level distribution
    - sample of disagreements for manual review

Usage:
    ./venv/bin/python3 scripts/compare_opus_vs_sonnet_300.py
"""
import json
import os
import sys
from collections import Counter

OPUS_FILE   = "annotation_v4_opus_300.json"
SONNET_FILE = "annotation_v4_sonnet_300.json"

# Public list prices per million tokens, May 2026.
# Adjust if Anthropic publishes different rates.
PRICE = {
    "opus":   {"in": 15.00, "out": 75.00},
    "sonnet": {"in":  3.00, "out": 15.00},
}


def load(path):
    if not os.path.exists(path):
        sys.exit(f"missing {path}")
    with open(path) as f:
        raw = json.load(f)
    # The extraction script writes a list of records; index by accession.
    # Accept either format for safety.
    if isinstance(raw, list):
        return {r["accession_number"]: r for r in raw if "accession_number" in r}
    return raw


def usage(records):
    """Total input/output token counts across all records."""
    tin = sum(r.get("usage", {}).get("input", 0) for r in records.values())
    tout = sum(r.get("usage", {}).get("output", 0) for r in records.values())
    return tin, tout


def cost(tin, tout, prices):
    return tin / 1_000_000 * prices["in"] + tout / 1_000_000 * prices["out"]


def io_flag(ref_list):
    """True if any ref in the list has explicitly_labeled_io = True."""
    return any(r.get("explicitly_labeled_io") for r in ref_list)


def letter_numbers(ref_list):
    """Set of letter_number values from a refs list."""
    return frozenset(r.get("letter_number") for r in ref_list if r.get("letter_number"))


def main():
    opus = load(OPUS_FILE)
    sonnet = load(SONNET_FILE)

    common = sorted(set(opus) & set(sonnet))
    only_opus = set(opus) - set(sonnet)
    only_sonnet = set(sonnet) - set(opus)

    print("=== Sample coverage ===")
    print(f"  Opus records:       {len(opus)}")
    print(f"  Sonnet records:     {len(sonnet)}")
    print(f"  Common (compared):  {len(common)}")
    if only_opus or only_sonnet:
        print(f"  Only Opus:          {len(only_opus)}")
        print(f"  Only Sonnet:        {len(only_sonnet)}")
    print()

    # ============================== Cost ===========================
    o_in, o_out = usage(opus)
    s_in, s_out = usage(sonnet)
    o_cost = cost(o_in, o_out, PRICE["opus"])
    s_cost = cost(s_in, s_out, PRICE["sonnet"])

    print("=== Token usage and computed cost (list prices, May 2026) ===")
    print(f"  Opus    input={o_in:>10,}  output={o_out:>8,}  ${o_cost:7.2f}  (${o_cost / len(opus):.4f}/PDF)")
    print(f"  Sonnet  input={s_in:>10,}  output={s_out:>8,}  ${s_cost:7.2f}  (${s_cost / len(sonnet):.4f}/PDF)")
    print(f"  Ratio   Sonnet costs {s_cost / o_cost * 100:.1f}% of Opus")
    print()
    print(f"  Projected cost for the full 8,818-PDF residual:")
    print(f"    Opus:   ${o_cost / len(opus) * 8818:7.2f}")
    print(f"    Sonnet: ${s_cost / len(sonnet) * 8818:7.2f}")
    print()

    # ============================ Agreement ========================
    top_left_ref_counts_match = 0
    top_left_letter_sets_match = 0
    top_left_io_flag_match = 0
    fee_issued_match = 0
    fee_letter_match = 0
    fee_number_match = 0
    fee_date_match = 0
    cancelled_match = 0
    both_say_fee_issued = 0
    disagreements_top_left = []
    disagreements_fee_issued = []           # opus/sonnet disagree on the BOOL
    disagreements_fee_letter = []           # both say issued, disagree on letter_number
    disagreements_fee_number = []           # both say issued, disagree on patent_number
    conf_opus = Counter()
    conf_sonnet = Counter()

    for acc in common:
        o = opus[acc]["extraction"]
        s = sonnet[acc]["extraction"]

        conf_opus[o.get("confidence", "?")] += 1
        conf_sonnet[s.get("confidence", "?")] += 1

        o_refs = o.get("top_left_form_block", {}).get("references", []) or []
        s_refs = s.get("top_left_form_block", {}).get("references", []) or []

        if len(o_refs) == len(s_refs):
            top_left_ref_counts_match += 1

        if letter_numbers(o_refs) == letter_numbers(s_refs):
            top_left_letter_sets_match += 1
        else:
            if len(disagreements_top_left) < 12:
                disagreements_top_left.append((acc, sorted(letter_numbers(o_refs)), sorted(letter_numbers(s_refs))))

        if io_flag(o_refs) == io_flag(s_refs):
            top_left_io_flag_match += 1

        o_mp = o.get("middle_page_outcome", {})
        s_mp = s.get("middle_page_outcome", {})
        o_fee = bool(o_mp.get("fee_patent_issued"))
        s_fee = bool(s_mp.get("fee_patent_issued"))
        if o_fee == s_fee:
            fee_issued_match += 1
        else:
            disagreements_fee_issued.append((acc, o_fee, s_fee))

        if o_fee and s_fee:
            both_say_fee_issued += 1
            o_letter = o_mp.get("fee_letter_number") or ""
            s_letter = s_mp.get("fee_letter_number") or ""
            o_number = o_mp.get("fee_patent_number") or ""
            s_number = s_mp.get("fee_patent_number") or ""
            if o_letter == s_letter:
                fee_letter_match += 1
            else:
                disagreements_fee_letter.append((acc, o_letter, s_letter, o_number, s_number))
            if o_number == s_number:
                fee_number_match += 1
            else:
                disagreements_fee_number.append((acc, o_letter, s_letter, o_number, s_number))
            if (o_mp.get("fee_patent_date") or "") == (s_mp.get("fee_patent_date") or ""):
                fee_date_match += 1

        if bool(o_mp.get("patent_cancelled")) == bool(s_mp.get("patent_cancelled")):
            cancelled_match += 1

    n = len(common)
    pct = lambda k: f"{k}/{n} = {100 * k / n:.1f}%"

    print("=== Agreement, on the 300 commonly-extracted records ===")
    print()
    print("LAYER 1 — top-left form block:")
    print(f"  same count of refs:              {pct(top_left_ref_counts_match)}")
    print(f"  same set of letter_numbers:      {pct(top_left_letter_sets_match)}")
    print(f"  same overall I.O. flag:          {pct(top_left_io_flag_match)}")
    print()
    print("LAYER 2 — middle-page outcome:")
    print(f"  same fee_patent_issued bool:     {pct(fee_issued_match)}")
    print(f"  same patent_cancelled bool:      {pct(cancelled_match)}")
    if both_say_fee_issued:
        b = both_say_fee_issued
        print(f"  both said fee_patent_issued:     {b}/{n}")
        print(f"    same fee_letter_number:        {fee_letter_match}/{b} = {100 * fee_letter_match / b:.1f}%")
        print(f"    same fee_patent_number:        {fee_number_match}/{b} = {100 * fee_number_match / b:.1f}%")
        print(f"    same fee_patent_date:          {fee_date_match}/{b} = {100 * fee_date_match / b:.1f}%")
    print()

    print("=== Confidence distribution ===")
    print(f"  Opus:    {dict(conf_opus.most_common())}")
    print(f"  Sonnet:  {dict(conf_sonnet.most_common())}")
    print()

    if disagreements_top_left:
        print("=== Top-left disagreements (12 max) ===")
        for acc, o_refs, s_refs in disagreements_top_left:
            print(f"  {acc:>10s}  opus={o_refs}  sonnet={s_refs}")
        print()

    if disagreements_fee_issued:
        print(f"=== fee_patent_issued bool disagreements ({len(disagreements_fee_issued)} total) ===")
        for acc, ov, sv in disagreements_fee_issued:
            print(f"  {acc:>10s}  opus.issued={ov}  sonnet.issued={sv}")
        print()

    if disagreements_fee_letter:
        print(f"=== fee_letter_number disagreements when both say issued ({len(disagreements_fee_letter)} total) ===")
        print("  Each row: opus_letter | sonnet_letter | opus_number | sonnet_number")
        for acc, ol, sl, on, sn in disagreements_fee_letter[:20]:
            print(f"  {acc:>10s}  L:'{ol}' vs '{sl}'   N:'{on}' vs '{sn}'")
        if len(disagreements_fee_letter) > 20:
            print(f"  ... and {len(disagreements_fee_letter) - 20} more")
        print()

    if disagreements_fee_number:
        print(f"=== fee_patent_number disagreements when both say issued ({len(disagreements_fee_number)} total) ===")
        print("  Each row: opus_letter | sonnet_letter | opus_number | sonnet_number")
        for acc, ol, sl, on, sn in disagreements_fee_number[:20]:
            print(f"  {acc:>10s}  L:'{ol}' vs '{sl}'   N:'{on}' vs '{sn}'")
        if len(disagreements_fee_number) > 20:
            print(f"  ... and {len(disagreements_fee_number) - 20} more")
        print()

    print("=== Notes for manual review ===")
    print("  Each disagreement row shows both fields (letter_number AND patent_number) from both models.")
    print("  If the two values are SWAPPED between fields (e.g. opus letter='X' number='Y' vs sonnet letter='Y' number='X'),")
    print("  the underlying problem is schema-routing, not reading. Both models read the page correctly but assigned")
    print("  the numbers to different fields. Fix is prompt clarification.")
    print()
    print("  If the values are genuinely different (one model reads digits the other does not), the PDF is the arbiter.")


if __name__ == "__main__":
    main()
