"""
Parse the `remarks` field of trust-class patents in all_patents to extract
embedded fee-patent cross-references like:

    SEE SERIAL PATENT NR 75921-09 FOR FEE PATENT
    See Serial Patent No 1104347 for Fee Patent
    SEE FEE PATENT NR 527838

Test mode (default): runs on the 250 patents already vision-extracted
across the v1, v2, and v3 samples. Compares the regex output against the
vision model's `fee_patent_number` for each row and prints an agreement
report. The point is to validate the regex before scaling.

Production mode (--full): runs on every trust-class patent with non-empty
remarks. Writes results to remarks_fee_refs.csv for downstream import.

Read-only on the database.

Usage:
    ./venv/bin/python3 scripts/parse_remarks_fee_refs.py          # test on 250
    ./venv/bin/python3 scripts/parse_remarks_fee_refs.py --full   # full scan
"""
import os
import re
import sys
import csv
import json
import psycopg2
import psycopg2.extras
from collections import Counter

DB_URL = os.environ.get("DATABASE_URL", "dbname=allotment_research user=cwm6W")
FULL = "--full" in sys.argv

# Vision-extraction JSON files to draw the test set from
EXTRACTION_FILES = [
    "annotation_extractions.json",      # v1 (50)
    "annotation_extractions_v2.json",   # v2 (100)
    "annotation_extractions_v3.json",   # v3 (100)
]

OUT_CSV = "data/remarks_fee_refs.csv"

# Regex patterns for fee-patent references in remarks text.
#
# Two layers:
#  - CLUSTER_PATTERNS capture the ENTIRE numeric cluster between an introducer
#    (e.g. "SEE SERIAL PATENT NR") and "FOR FEE PATENT". The cluster may
#    contain multiple accession numbers connected by AND or whitespace, e.g.
#    "NR 942795 AND 1196898" or "NR 957685 957686 AND 957687". We tokenize
#    the cluster and emit every digit-bearing token as a separate fee_ref.
#    Multiple clauses in one remarks string ("NR X FOR FEE PATENT ... AND
#    SERIAL PATENT NR Y FOR FEE PATENT") are handled by finditer.
#  - FALLBACK_PATTERNS catch single-accession forms like "PATENT #706068"
#    that don't fit the introducer/cluster shape. Only consulted when no
#    cluster pattern matched.
#
# The earlier single-match logic captured only the first accession and
# silently dropped any sibling refs — costing ~3,970 real linkages corpus-wide.

# Tokens that show up inside a cluster but are NOT accession numbers.
_NON_ACC_TOKENS = {
    "AND", "OR", "&", "NR", "NO", "NUMBER", "NOS",
    "SERIAL", "PATENT", "PATENTS", "MISCELLANEOUS", "VOLUME", "FEE",
    "TO", "FOR", "OF", "ALSO", "SEE",
}

CLUSTER_PATTERNS = [
    # SEE SERIAL PATENT NR <numbers> FOR FEE PATENT(S)
    re.compile(r"SEE\s+SERIAL\s+PATENT\s+(?:NR\.?|NO\.?|NUMBER)?\s*([0-9][0-9A-Z\-\s]*?)\s+FOR\s+FEE\s+PATENT"),
    # SEE MISCELLANEOUS VOLUME NR <numbers> FOR FEE PATENT(S)
    re.compile(r"SEE\s+MISCELLANEOUS\s+VOLUME\s+(?:NR\.?|NO\.?|NUMBER)?\s*([0-9][0-9A-Z\-\s]*?)\s+FOR\s+FEE\s+PATENT"),
    # SEE ACCESSION NR <numbers> FOR FEE PATENT(S)
    re.compile(r"SEE\s+ACCESSION\s+(?:NR\.?|NO\.?|NUMBER)?\s*([0-9][0-9A-Z\-\.\s]*?)\s+FOR\s+FEE\s+PATENT"),
    # bare "SERIAL PATENT NR <numbers> ... FEE PATENT" (no SEE prefix; rare)
    re.compile(r"SERIAL\s+PATENT\s+(?:NR\.?|NO\.?|NUMBER)?\s*([0-9][0-9A-Z\-\s]*?)\s+FOR\s+FEE\s+PATENT"),
]

FALLBACK_PATTERNS = [
    # SEE FEE PATENT NR 527838
    re.compile(r"SEE\s+FEE\s+PATENT\s+(?:NR\.?|NO\.?|NUMBER)?\s*([A-Z0-9\-]+)"),
    # FEE PATENT NR 527838 ISSUED
    re.compile(r"FEE\s+PATENT\s+(?:NR\.?|NO\.?|NUMBER)?\s*([A-Z0-9\-]+)\s+(?:ISSUED|GRANTED)"),
    # leading "FEE PATENT 527838"
    re.compile(r"^FEE\s+PATENT\s+(?:NR\.?|NO\.?|NUMBER)?\s*([A-Z0-9\-]+)"),
    # "PATENT #706068"
    re.compile(r"\bPATENT\s*#\s*([A-Z0-9\-]+)"),
]

CANCEL_PATTERNS = [
    r"CANCELED\s+DOCUMENT",
    r"CANCELLED\s+DOCUMENT",
    r"CANCELED\s+PATENT",
    r"CANCELLED\s+PATENT",
]


def _cluster_tokens(cluster_text):
    """Pull digit-bearing tokens out of a captured cluster, dropping AND/NR/etc."""
    out = []
    for raw in cluster_text.split():
        tok = raw.strip(",.;:")
        if not tok:
            continue
        if tok.upper() in _NON_ACC_TOKENS:
            continue
        # must contain at least one digit
        if any(c.isdigit() for c in tok):
            if tok not in out:
                out.append(tok)
    return out


def parse_remarks(remarks):
    """Return (list_of_fee_refs, cancellation_flag, pattern_indices, normalized_remarks).

    list_of_fee_refs may be empty, length 1, or longer. Each entry is one
    accession-shaped token recovered from the remarks. Downstream validator
    treats each entry as an independent candidate linkage.
    """
    if not remarks:
        return [], False, [], ""
    s = re.sub(r"\s+", " ", str(remarks).upper()).strip()

    fee_refs = []
    pat_idxs = []

    # Layer 1: cluster patterns (handle "AND" + multi-number cases).
    for i, pat in enumerate(CLUSTER_PATTERNS):
        for m in pat.finditer(s):
            for tok in _cluster_tokens(m.group(1)):
                if tok not in fee_refs:
                    fee_refs.append(tok)
                    pat_idxs.append(i)

    # Layer 2: fallbacks for single-accession forms — only if cluster found nothing.
    if not fee_refs:
        for i, pat in enumerate(FALLBACK_PATTERNS):
            for m in pat.finditer(s):
                ref = m.group(1)
                if any(c.isdigit() for c in ref) and ref not in fee_refs:
                    fee_refs.append(ref)
                    pat_idxs.append(len(CLUSTER_PATTERNS) + i)

    cancelled = any(re.search(p, s) for p in CANCEL_PATTERNS)
    return fee_refs, cancelled, pat_idxs, s


def normalize_acc_for_compare(s):
    if not s: return ""
    return re.sub(r"[^A-Z0-9]", "", s.upper())


def load_vision_extractions():
    """Build a {accession: extraction_row} map from the three vision-extraction JSONs."""
    by_acc = {}
    for path in EXTRACTION_FILES:
        if not os.path.exists(path):
            continue
        with open(path) as f:
            for r in json.load(f):
                acc = r.get("accession_number")
                if acc:
                    # Tag with which sample it came from
                    r["_source"] = path
                    by_acc[acc] = r
    return by_acc


def run_test():
    vision = load_vision_extractions()
    if not vision:
        sys.exit("No vision-extraction JSON files found. Run extract_annotations* first.")
    print(f"Test set: {len(vision)} patents across {len(EXTRACTION_FILES)} sample runs")

    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT accession_number, remarks
        FROM all_patents
        WHERE accession_number = ANY(%s)
    """, (list(vision.keys()),))
    remarks_map = {r["accession_number"]: r["remarks"] for r in cur.fetchall()}

    # Agreement matrix
    agreements = Counter()
    pattern_use = Counter()
    sample_rows = {"both_yes_match": [], "both_yes_mismatch": [],
                   "rescue": [],
                   "vision_yes_remarks_no": [], "vision_no_remarks_yes": [],
                   "both_no": [], "cancellation_in_remarks": []}

    rows_out = []
    for acc, vrow in vision.items():
        ext = vrow.get("extraction", {})
        # Read fee flag from both v2 and v3 schemas
        vision_fee = ext.get("fee_patent_issued")
        if vision_fee is None:
            vision_fee = ext.get("annotation_present")  # v1/v2
        vision_pn = (ext.get("fee_patent_number") or ext.get("patent_number") or "").strip()

        remarks_raw = remarks_map.get(acc, "")
        fee_refs, cancelled, pat_idxs, norm = parse_remarks(remarks_raw)
        # Test-mode classification compares against the vision model's single
        # fee_patent_number, so collapse multiple refs into the first one for
        # this report. The full-run pipeline preserves all refs.
        fee_ref = fee_refs[0] if fee_refs else None

        for pi in pat_idxs:
            pattern_use[pi] += 1
        if cancelled:
            sample_rows["cancellation_in_remarks"].append((acc, vrow.get("full_name"), norm[:100]))

        # Classify
        if vision_fee and fee_ref:
            v_norm = normalize_acc_for_compare(vision_pn)
            r_norm = normalize_acc_for_compare(fee_ref)
            if not v_norm and r_norm:
                # Vision said fee but couldn't read number; remarks supplies it
                agreements["rescue"] += 1
                if len(sample_rows["rescue"]) < 10:
                    sample_rows["rescue"].append((acc, fee_ref, vrow.get("full_name")))
            elif v_norm and r_norm and (v_norm == r_norm or v_norm in r_norm or r_norm in v_norm):
                agreements["both_yes_match"] += 1
                if len(sample_rows["both_yes_match"]) < 6:
                    sample_rows["both_yes_match"].append((acc, vision_pn, fee_ref, vrow.get("full_name")))
            else:
                agreements["both_yes_mismatch"] += 1
                if len(sample_rows["both_yes_mismatch"]) < 12:
                    sample_rows["both_yes_mismatch"].append((acc, vision_pn, fee_ref, vrow.get("full_name")))
        elif vision_fee and not fee_ref:
            agreements["vision_yes_remarks_no"] += 1
            if len(sample_rows["vision_yes_remarks_no"]) < 8:
                sample_rows["vision_yes_remarks_no"].append((acc, vision_pn, norm[:80], vrow.get("full_name")))
        elif not vision_fee and fee_ref:
            agreements["vision_no_remarks_yes"] += 1
            if len(sample_rows["vision_no_remarks_yes"]) < 8:
                sample_rows["vision_no_remarks_yes"].append((acc, fee_ref, norm[:80], vrow.get("full_name")))
        else:
            agreements["both_no"] += 1

        rows_out.append({
            "accession": acc,
            "full_name": vrow.get("full_name"),
            "vision_fee_issued": vision_fee,
            "vision_patent_number": vision_pn,
            "remarks_raw": remarks_raw,
            "remarks_fee_ref": fee_ref,
            "remarks_cancellation": cancelled,
        })

    total = sum(agreements.values())
    print()
    print("=== Agreement summary ===")
    for k in ["both_yes_match", "rescue", "both_yes_mismatch",
             "vision_yes_remarks_no", "vision_no_remarks_yes", "both_no"]:
        n = agreements.get(k, 0)
        pct = 100 * n / total if total else 0
        print(f"  {k:25s} {n:4d}  ({pct:.0f}%)")
    print(f"  cancellation_in_remarks  {len(sample_rows['cancellation_in_remarks']):4d}  (overlay flag)")
    # Strategic coverage: fraction of vision-detected fees where remarks also documents one
    vision_yes = agreements.get("both_yes_match", 0) + agreements.get("rescue", 0) + \
                 agreements.get("both_yes_mismatch", 0) + agreements.get("vision_yes_remarks_no", 0)
    remarks_documented = agreements.get("both_yes_match", 0) + agreements.get("rescue", 0) + \
                         agreements.get("both_yes_mismatch", 0)
    print()
    if vision_yes:
        print(f"Strategic coverage: {remarks_documented}/{vision_yes} = "
              f"{100*remarks_documented/vision_yes:.0f}% of vision-detected fees are also documented in remarks")

    print()
    print("Regex pattern usage:")
    all_patterns = [*CLUSTER_PATTERNS, *FALLBACK_PATTERNS]
    for i, n in sorted(pattern_use.items()):
        label = all_patterns[i].pattern[:60] if i < len(all_patterns) else f"pat#{i}"
        print(f"  [{i}] {label:60s}  {n}")

    print()
    print("Sample: both yes AND numbers match (regex is working):")
    for acc, vpn, rref, name in sample_rows["both_yes_match"]:
        print(f"  {acc:14s}  vision={vpn:12s}  remarks={rref:12s}  {name}")

    if sample_rows["rescue"]:
        print()
        print("Sample: vision saw fee but couldn't read number — remarks supplies it:")
        for acc, rref, name in sample_rows["rescue"]:
            print(f"  {acc:14s}  remarks={rref:12s}  {name}")

    if sample_rows["both_yes_mismatch"]:
        print()
        print("Sample: both have numbers BUT they don't match (transcription discrepancies):")
        for acc, vpn, rref, name in sample_rows["both_yes_mismatch"]:
            print(f"  {acc:14s}  vision={vpn:12s}  remarks={rref:12s}  {name}")

    if sample_rows["vision_yes_remarks_no"]:
        print()
        print("Sample: vision saw fee, remarks didn't help (where PDF scraping pays off):")
        for acc, vpn, rem, name in sample_rows["vision_yes_remarks_no"][:8]:
            print(f"  {acc:14s}  vision={vpn:12s}  remarks={rem!r}  {name}")

    if sample_rows["vision_no_remarks_yes"]:
        print()
        print("Sample: remarks has fee ref but vision didn't see one (model false negative?):")
        for acc, rref, rem, name in sample_rows["vision_no_remarks_yes"][:8]:
            print(f"  {acc:14s}  remarks_ref={rref:12s}  remarks={rem!r}  {name}")

    if sample_rows["cancellation_in_remarks"]:
        print()
        print(f"Sample: remarks indicates cancellation ({len(sample_rows['cancellation_in_remarks'])} total in test set):")
        for acc, name, rem in sample_rows["cancellation_in_remarks"][:8]:
            print(f"  {acc:14s}  {name}  remarks={rem!r}")

    # Write test results to CSV for inspection
    with open("data/remarks_test_results.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[
            "accession", "full_name", "vision_fee_issued", "vision_patent_number",
            "remarks_fee_ref", "remarks_cancellation", "remarks_raw"
        ])
        w.writeheader()
        for row in rows_out:
            w.writerow(row)
    print()
    print("Per-row test results: data/remarks_test_results.csv")

    cur.close()
    conn.close()


def run_full():
    """Scan every trust-class patent's remarks for fee/cancellation references."""
    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)
    cur.execute("""
        SELECT accession_number, full_name, signature_date, state, authority,
               indian_allotment_number, remarks
        FROM all_patents
        WHERE authority IN ('Indian Trust Patent', 'Indian Allotment - General',
                            'Indian Reissue Trust', 'Indian Homestead Trust',
                            'Indian Allotment Patent', 'Indian Trust Patent (Wind R)',
                            'Indian Allotment-Wyandotte')
          AND remarks IS NOT NULL AND remarks <> ''
    """)
    rows = cur.fetchall()
    print(f"Scanning {len(rows)} trust-class patents with non-empty remarks...")

    # Emit ONE ROW PER (trust_accession, fee_ref) pair. A trust patent whose
    # remarks reference two fee patents produces two rows in the output CSV.
    # Patents with no fee_refs still get a single row with empty fee_ref so
    # downstream counts of "scanned" stay accurate.
    n_patents_with_fee = n_total_refs = n_cancel = n_neither = 0
    n_multi_ref_patents = 0
    out = []
    for r in rows:
        fee_refs, cancelled, _, _ = parse_remarks(r["remarks"])
        base = {
            "trust_accession": r["accession_number"],
            "allottee":        r["full_name"],
            "signature_date":  r["signature_date"],
            "state":           r["state"],
            "authority":       r["authority"],
            "allotment_number": r["indian_allotment_number"],
            "remarks_cancellation": cancelled,
            "remarks_raw": r["remarks"],
        }
        if fee_refs:
            n_patents_with_fee += 1
            n_total_refs += len(fee_refs)
            if len(fee_refs) > 1:
                n_multi_ref_patents += 1
            for ref in fee_refs:
                out.append({**base, "fee_ref_extracted": ref})
        else:
            out.append({**base, "fee_ref_extracted": ""})
            if not cancelled:
                n_neither += 1
        if cancelled:
            n_cancel += 1

    print(f"  patents with at least one fee_ref:   {n_patents_with_fee}")
    print(f"  total fee_refs extracted:            {n_total_refs}")
    print(f"  patents with multiple fee_refs:      {n_multi_ref_patents}")
    print(f"  with cancellation phrase:            {n_cancel}")
    print(f"  with neither fee_ref nor cancel:     {n_neither}")

    with open(OUT_CSV, "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=[
            "trust_accession", "allottee", "signature_date", "state", "authority",
            "allotment_number", "fee_ref_extracted", "remarks_cancellation", "remarks_raw"
        ])
        w.writeheader()
        for row in out:
            w.writerow(row)
    print(f"Wrote {OUT_CSV}  ({len(out)} rows)")

    cur.close()
    conn.close()


if __name__ == "__main__":
    if FULL:
        run_full()
    else:
        run_test()
