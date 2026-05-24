"""
Compare the v5 extraction outputs from Sonnet (local API) and Gemma 3 27B (HPC).
Same 50 PDFs, same v5 schema. Reports agreement and surfaces disagreements
for the human researcher to adjudicate against the actual PDFs.

NOTE: per project feedback, this script does NOT declare which model is "right"
on any given disagreement. It surfaces them; the PDF is the only arbiter.
"""
import json
import os
import sys
from collections import Counter

SONNET_FILE = "annotation_v5_sonnet_50.json"
GEMMA_FILE  = "annotation_v5_gemma_50.json"


def load(path):
    if not os.path.exists(path):
        sys.exit(f"missing {path}")
    with open(path) as f:
        raw = json.load(f)
    if isinstance(raw, list):
        return {r["accession_number"]: r for r in raw if "accession_number" in r}
    return raw


def letter_numbers(ref_list):
    return frozenset((r.get("letter_number") or "") for r in ref_list)


def io_any(ref_list):
    return any(r.get("explicitly_labeled_io") for r in ref_list)


def main():
    sonnet = load(SONNET_FILE)
    gemma  = load(GEMMA_FILE)

    common = sorted(set(sonnet) & set(gemma))
    only_s = set(sonnet) - set(gemma)
    only_g = set(gemma) - set(sonnet)

    print("=== Sample coverage ===")
    print(f"  Sonnet records:    {len(sonnet)}")
    print(f"  Gemma records:     {len(gemma)}")
    print(f"  Common (compared): {len(common)}")
    if only_s or only_g:
        print(f"  Only in Sonnet:    {sorted(only_s)}")
        print(f"  Only in Gemma:     {sorted(only_g)}")
    print()

    # ─── Token usage ──────────────────────────────────────────────────────
    def usage(rows):
        tin  = sum(r.get("usage", {}).get("input",  0) for r in rows.values())
        tout = sum(r.get("usage", {}).get("output", 0) for r in rows.values())
        return tin, tout
    s_in, s_out = usage(sonnet)
    g_in, g_out = usage(gemma)
    print("=== Token usage ===")
    print(f"  Sonnet  input={s_in:>9,}  output={s_out:>7,}  (Anthropic API, billed)")
    print(f"  Gemma   input={g_in:>9,}  output={g_out:>7,}  (UVA HPC, no per-token cost)")
    print()

    # ─── Per-record agreement ─────────────────────────────────────────────
    ref_count_same       = 0
    letter_set_same      = 0
    io_flag_same         = 0
    fee_issued_same      = 0
    fee_issued_both_true = 0
    cancelled_same       = 0

    disagree_refs   = []   # acc, sonnet refs, gemma refs
    disagree_fee    = []   # acc, sonnet bool, gemma bool, sonnet refs, gemma refs
    disagree_canc   = []   # acc, sonnet bool, gemma bool

    s_fee_count = 0
    g_fee_count = 0
    s_canc_count = 0
    g_canc_count = 0

    for acc in common:
        s = sonnet[acc]["extraction"]
        g = gemma[acc]["extraction"]

        s_refs = s.get("top_left_form_block", {}).get("references", []) or []
        g_refs = g.get("top_left_form_block", {}).get("references", []) or []

        if len(s_refs) == len(g_refs):
            ref_count_same += 1
        s_set = letter_numbers(s_refs)
        g_set = letter_numbers(g_refs)
        if s_set == g_set:
            letter_set_same += 1
        else:
            disagree_refs.append((acc, sorted(s_set), sorted(g_set)))
        if io_any(s_refs) == io_any(g_refs):
            io_flag_same += 1

        s_fee = bool(s.get("middle_page_outcome", {}).get("fee_patent_issued"))
        g_fee = bool(g.get("middle_page_outcome", {}).get("fee_patent_issued"))
        if s_fee: s_fee_count += 1
        if g_fee: g_fee_count += 1
        if s_fee == g_fee:
            fee_issued_same += 1
            if s_fee and g_fee:
                fee_issued_both_true += 1
        else:
            disagree_fee.append((acc, s_fee, g_fee, sorted(s_set), sorted(g_set)))

        s_canc = bool(s.get("middle_page_outcome", {}).get("patent_cancelled"))
        g_canc = bool(g.get("middle_page_outcome", {}).get("patent_cancelled"))
        if s_canc: s_canc_count += 1
        if g_canc: g_canc_count += 1
        if s_canc == g_canc:
            cancelled_same += 1
        else:
            disagree_canc.append((acc, s_canc, g_canc))

    n = len(common)
    pct = lambda k: f"{k}/{n} = {100*k/n:.1f}%"

    # ─── Marginal counts ──────────────────────────────────────────────────
    print("=== What each model flagged (presence counts) ===")
    print(f"  fee_patent_issued = true:  Sonnet {s_fee_count}/{n}, Gemma {g_fee_count}/{n}")
    print(f"  patent_cancelled  = true:  Sonnet {s_canc_count}/{n}, Gemma {g_canc_count}/{n}")
    print()

    # ─── Agreement ────────────────────────────────────────────────────────
    print("=== Agreement on the commonly-extracted records ===")
    print()
    print("LAYER 1 — top-left form block:")
    print(f"  same count of refs:           {pct(ref_count_same)}")
    print(f"  same set of letter_numbers:   {pct(letter_set_same)}")
    print(f"  same overall I.O. flag:       {pct(io_flag_same)}")
    print()
    print("LAYER 2 — middle-page outcome:")
    print(f"  same fee_patent_issued bool:  {pct(fee_issued_same)}")
    print(f"  same patent_cancelled bool:   {pct(cancelled_same)}")
    print(f"  (both said fee issued:  {fee_issued_both_true}/{n})")
    print()

    # ─── Disagreement samples ─────────────────────────────────────────────
    if disagree_refs:
        print(f"=== Top-left letter_number disagreements ({len(disagree_refs)} total) ===")
        print("  format: accession  sonnet=[...]  gemma=[...]")
        for acc, s_set, g_set in disagree_refs:
            print(f"  {acc:>10s}  sonnet={s_set}  gemma={g_set}")
        print()

    if disagree_fee:
        print(f"=== fee_patent_issued bool disagreements ({len(disagree_fee)} total) ===")
        print("  format: accession  sonnet.fee  gemma.fee  (top-left refs as context)")
        for acc, s_fee, g_fee, s_set, g_set in disagree_fee:
            print(f"  {acc:>10s}  sonnet.fee={s_fee}  gemma.fee={g_fee}  sonnet_refs={s_set} gemma_refs={g_set}")
        print()

    if disagree_canc:
        print(f"=== patent_cancelled bool disagreements ({len(disagree_canc)} total) ===")
        for acc, s_canc, g_canc in disagree_canc:
            print(f"  {acc:>10s}  sonnet={s_canc}  gemma={g_canc}")
        print()

    print("=== Notes for manual review ===")
    print("  Where the two models agree, that is a strong consensus signal.")
    print("  Where they disagree, the PDF is the only arbiter. Open the page and judge.")
    print("  This script does NOT declare which model was 'right' on any disagreement.")


if __name__ == "__main__":
    main()
