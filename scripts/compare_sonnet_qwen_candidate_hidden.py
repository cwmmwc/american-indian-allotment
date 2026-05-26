"""
Compare Sonnet and Qwen on the candidate-hidden-conversions cross-check.

Inputs:
  annotation_v5_sonnet_full.json            — full Sonnet production run
  annotation_v5_qwen_candidate_hidden.json  — Qwen cross-check on the 207
                                              Sonnet candidates

Both files are filtered to the 207 candidate accessions
(data/vision_v5_sonnet_candidate_hidden.csv). The script reports:

  - Sonnet AND Qwen both flagged   → strong-consensus hidden conversions
  - Sonnet flagged, Qwen did not   → Qwen disagreed (Sonnet false positive,
                                     OR Qwen missed it — model disagreement,
                                     not ground truth)
  - Per-authority breakdown so the "Indian Fee Patent" structural-FP class
    can be inspected separately.

Does NOT declare which model is right; per the comparison policy used in
compare_sonnet_gemma_qwen_50.py, model disagreement is surfaced for human
adjudication against the PDFs.

Usage:
    ./venv/bin/python3 scripts/compare_sonnet_qwen_candidate_hidden.py
"""
import csv
import json
import os
import sys
from collections import Counter, defaultdict

CANDIDATES_CSV = "data/vision_v5_sonnet_candidate_hidden.csv"
SONNET_JSON    = "annotation_v5_sonnet_full.json"
QWEN_JSON      = "annotation_v5_qwen_candidate_hidden.json"
OUT_CSV        = "data/vision_v5_candidate_hidden_with_qwen.csv"


def load_records(path, restrict_to=None):
    if not os.path.exists(path):
        sys.exit(f"missing {path}")
    with open(path) as f:
        raw = json.load(f)
    by_acc = {}
    for r in raw if isinstance(raw, list) else raw.values():
        acc = r.get("accession_number")
        if not acc:
            continue
        if restrict_to is not None and acc not in restrict_to:
            continue
        by_acc[acc] = r
    return by_acc


def fee_flag(rec):
    return bool(
        (rec or {}).get("extraction", {})
                   .get("middle_page_outcome", {})
                   .get("fee_patent_issued")
    )


def main():
    if not os.path.exists(CANDIDATES_CSV):
        sys.exit(f"missing {CANDIDATES_CSV}")

    candidate_meta = {}
    with open(CANDIDATES_CSV) as f:
        for row in csv.DictReader(f):
            candidate_meta[row["accession_number"]] = row
    candidate_set = set(candidate_meta)
    print(f"candidate set: {len(candidate_set)} accessions from {CANDIDATES_CSV}")

    sonnet = load_records(SONNET_JSON, restrict_to=candidate_set)
    qwen   = load_records(QWEN_JSON,   restrict_to=candidate_set)
    print(f"  sonnet rows present: {len(sonnet)}")
    print(f"  qwen   rows present: {len(qwen)}")

    missing_in_qwen = sorted(candidate_set - set(qwen))
    if missing_in_qwen:
        print(f"  WARNING: {len(missing_in_qwen)} candidates not present in Qwen output (extraction failure?):")
        for acc in missing_in_qwen[:10]:
            print(f"    {acc}")
        if len(missing_in_qwen) > 10:
            print(f"    ... and {len(missing_in_qwen) - 10} more")
    print()

    both, sonnet_only, qwen_missing = [], [], []
    for acc in sorted(candidate_set):
        s = fee_flag(sonnet.get(acc))
        if acc not in qwen:
            qwen_missing.append(acc)
            continue
        q = fee_flag(qwen[acc])
        if s and q:
            both.append(acc)
        elif s and not q:
            sonnet_only.append(acc)

    print("=== Cross-check outcome ===")
    print(f"  Sonnet AND Qwen both flagged (strong consensus):  {len(both):>4}")
    print(f"  Sonnet flagged, Qwen did NOT:                     {len(sonnet_only):>4}")
    if qwen_missing:
        print(f"  Qwen output missing (treat as inconclusive):      {len(qwen_missing):>4}")
    print()

    # ── Per-authority breakdown ──────────────────────────────────────────
    auth_outcomes = defaultdict(Counter)
    for acc in candidate_set:
        if acc not in qwen:
            label = "qwen_missing"
        elif fee_flag(sonnet.get(acc)) and fee_flag(qwen[acc]):
            label = "both_agree"
        else:
            label = "sonnet_only"
        auth = (candidate_meta[acc].get("authority") or "").strip() or "(none)"
        auth_outcomes[auth][label] += 1

    print("=== Per-authority outcomes ===")
    print(f"  {'authority':<28s}  both  sonnet_only  qwen_missing  total")
    for auth in sorted(auth_outcomes, key=lambda a: -sum(auth_outcomes[a].values())):
        c = auth_outcomes[auth]
        total = sum(c.values())
        print(f"  {auth:<28s}  {c.get('both_agree',0):>4}  {c.get('sonnet_only',0):>11}  {c.get('qwen_missing',0):>12}  {total:>5}")
    print()

    # ── Write merged CSV for skim/triage ─────────────────────────────────
    with open(OUT_CSV, "w", newline="") as f:
        w = csv.writer(f)
        w.writerow([
            "accession_number", "full_name", "signature_date",
            "state", "county", "authority",
            "sonnet_fee", "qwen_fee", "consensus",
        ])
        for acc in sorted(candidate_set):
            meta = candidate_meta[acc]
            s_fee = fee_flag(sonnet.get(acc))
            q_present = acc in qwen
            q_fee = fee_flag(qwen.get(acc)) if q_present else None
            if not q_present:
                consensus = "qwen_missing"
            elif s_fee and q_fee:
                consensus = "both_agree"
            elif s_fee and not q_fee:
                consensus = "sonnet_only"
            else:
                consensus = "neither"  # shouldn't happen — Sonnet flagged is the input filter
            w.writerow([
                acc,
                meta.get("full_name") or "",
                meta.get("signature_date") or "",
                meta.get("state") or "",
                meta.get("county") or "",
                meta.get("authority") or "",
                "true" if s_fee else "false",
                ("true" if q_fee else "false") if q_present else "",
                consensus,
            ])
    print(f"wrote merged CSV: {OUT_CSV}")
    print()
    print("=== Notes ===")
    print("  This report surfaces model disagreement; it does NOT declare which model is right.")
    print("  'both_agree' = strongest-confidence candidates for trust_fee_linkages_recovered load.")
    print("  'sonnet_only' = Qwen disagreed — could be Sonnet false positive OR Qwen miss.")
    print("  Pay particular attention to 'Indian Fee Patent' authority cases (structural FP class).")


if __name__ == "__main__":
    main()
