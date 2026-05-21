"""
Validate the 58,892 fee-patent references extracted from trust-patent remarks
by looking each one up in all_patents. Where the extracted number matches a
real patent, cross-check name/date consistency. Where it doesn't match, try
common normalizations (strip dashes, zero-pad widths, dashed forms).

For unmatched extractions, attempt one round of low-edit-distance
reconciliation: find candidate fee patents for the same allottee within a
plausible date window, then accept the closest accession by edit distance
if (a) the name token overlap is high and (b) the edit distance is small.

Outputs:
  linkage_candidates.csv -- trust_acc, fee_acc, extracted, match_type, name_overlap, date_gap_years, notes
  linkage_unmatched.csv  -- trust_acc, allottee, extracted, sample_candidates, notes

Read-only on database. Run after parse_remarks_fee_refs.py --full.

Usage:
    ./venv/bin/python3 scripts/validate_remarks_extractions.py
"""
import os
import re
import csv
import sys
import psycopg2
import psycopg2.extras
from collections import Counter, defaultdict

DB_URL = os.environ.get("DATABASE_URL", "dbname=allotment_research user=cwm6W")
IN_CSV = "data/remarks_fee_refs.csv"
CANDIDATES_CSV = "data/linkage_candidates.csv"
UNMATCHED_CSV = "data/linkage_unmatched.csv"

MAX_EDIT_DISTANCE = 2          # cap for fuzzy match
MIN_NAME_OVERLAP_TOKENS = 1    # at least one shared name token (>=2 chars)
DATE_WINDOW_YEARS = 50         # fee patent must be within this many years of trust


def normalize_acc(s):
    """Normalize an accession number for comparison: uppercase, strip non-alphanum."""
    if not s:
        return ""
    return re.sub(r"[^A-Z0-9]", "", str(s).upper())


def variants(extracted):
    """Generate plausible accession-number variants for a raw extracted string."""
    if not extracted:
        return []
    raw = str(extracted).strip().upper()
    base = re.sub(r"[^0-9A-Z]", "", raw)
    out = {raw, base}
    if base.isdigit():
        out.add(base.lstrip("0") or "0")
        for w in (5, 6, 7, 8):
            if len(base) < w:
                out.add(base.zfill(w))
    # Try dashed-format variants if the base is pure digits
    if base.isdigit() and len(base) >= 5:
        out.add(f"{base[:-3]}-{base[-3:]}")
        out.add(f"{base[:-4]}-{base[-4:]}")
    # Keep the raw form (preserves dashes like "75921-09" and "0581-106")
    return list(out)


def name_tokens(name):
    if not name:
        return set()
    s = re.sub(r"[^A-Z0-9 ]", " ", name.upper())
    return {t for t in s.split() if len(t) > 1}


def edit_distance(a, b, cap=3):
    """Levenshtein distance, capped for speed."""
    a, b = a or "", b or ""
    la, lb = len(a), len(b)
    if abs(la - lb) > cap:
        return cap + 1
    # Standard DP, with early termination
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        curr = [i] + [0] * lb
        min_in_row = curr[0]
        for j in range(1, lb + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            curr[j] = min(curr[j - 1] + 1, prev[j] + 1, prev[j - 1] + cost)
            min_in_row = min(min_in_row, curr[j])
        if min_in_row > cap:
            return cap + 1
        prev = curr
    return prev[lb]


def main():
    if not os.path.exists(IN_CSV):
        sys.exit(f"Missing {IN_CSV}. Run parse_remarks_fee_refs.py --full first.")

    print("Loading trust-patent extractions...")
    with open(IN_CSV) as f:
        all_rows = list(csv.DictReader(f))
    with_fee = [r for r in all_rows if r["fee_ref_extracted"]]
    print(f"  trust patents with extracted fee ref: {len(with_fee)}")

    conn = psycopg2.connect(DB_URL)
    cur = conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor)

    print("Building index of all_patents accession -> row...")
    cur.execute("""
        SELECT accession_number, full_name, authority, signature_date, state, county
        FROM all_patents
        WHERE accession_number IS NOT NULL
    """)
    by_acc = {}
    by_acc_norm = {}
    for r in cur.fetchall():
        by_acc[r["accession_number"]] = r
        nrm = normalize_acc(r["accession_number"])
        if nrm and nrm not in by_acc_norm:
            by_acc_norm[nrm] = r
    print(f"  indexed {len(by_acc)} patents (by accession), {len(by_acc_norm)} by normalized form")

    print("Building index by first name-token for fuzzy lookups...")
    # For fuzzy: index fee patents by first significant name token
    by_first_token = defaultdict(list)
    for r in by_acc.values():
        auth = r["authority"] or ""
        if "Fee" not in auth and "Trust to Fee" not in auth:
            continue
        toks = sorted(name_tokens(r["full_name"]))
        for t in toks[:2]:
            by_first_token[t].append(r)
    n_fee_indexed = sum(len(v) for v in by_first_token.values())
    print(f"  indexed {n_fee_indexed} fee-patent rows by first/second name token")

    cur.close()
    conn.close()

    stats = Counter()
    candidates_out = []
    unmatched_out = []

    for i, row in enumerate(with_fee):
        if i % 5000 == 0 and i > 0:
            print(f"  processed {i}/{len(with_fee)}...")
        trust_acc = row["trust_accession"]
        trust_name = row["allottee"] or ""
        trust_date = row["signature_date"]
        extracted = row["fee_ref_extracted"]

        match = None
        match_type = None
        for v in variants(extracted):
            if v in by_acc:
                match = by_acc[v]
                match_type = "exact" if v == extracted else "normalized"
                break
            nv = normalize_acc(v)
            if nv and nv in by_acc_norm:
                match = by_acc_norm[nv]
                match_type = "normalized"
                break

        # Compute name overlap and date gap
        if match:
            t_toks = name_tokens(trust_name)
            f_toks = name_tokens(match["full_name"])
            shared = t_toks & f_toks
            date_gap = None
            try:
                from datetime import date
                if trust_date and match["signature_date"]:
                    td = date.fromisoformat(str(trust_date))
                    fd = match["signature_date"]
                    date_gap = abs((fd - td).days) // 365
            except Exception:
                pass
            stats[match_type] += 1
            candidates_out.append({
                "trust_accession": trust_acc,
                "fee_accession":   match["accession_number"],
                "extracted_raw":   extracted,
                "match_type":      match_type,
                "trust_name":      trust_name,
                "fee_name":        match["full_name"],
                "name_overlap":    ";".join(sorted(shared)),
                "name_consistent": "yes" if shared else "no",
                "date_gap_years":  date_gap if date_gap is not None else "",
                "trust_date":      trust_date,
                "fee_date":        match["signature_date"],
                "fee_authority":   match["authority"],
                "fee_state":       match["state"],
            })
            continue

        # Try fuzzy lookup: same name + low edit distance
        t_toks = sorted(name_tokens(trust_name))
        ext_norm = normalize_acc(extracted)
        best = None
        best_dist = MAX_EDIT_DISTANCE + 1
        candidates_seen = set()
        for tok in t_toks[:2]:
            for fr in by_first_token.get(tok, []):
                if fr["accession_number"] in candidates_seen:
                    continue
                candidates_seen.add(fr["accession_number"])
                d = edit_distance(ext_norm, normalize_acc(fr["accession_number"]), cap=MAX_EDIT_DISTANCE)
                if d <= MAX_EDIT_DISTANCE and d < best_dist:
                    f_toks = name_tokens(fr["full_name"])
                    if len(set(t_toks) & f_toks) >= MIN_NAME_OVERLAP_TOKENS:
                        best = fr
                        best_dist = d
        if best:
            stats["fuzzy"] += 1
            shared = set(t_toks) & name_tokens(best["full_name"])
            date_gap = None
            try:
                from datetime import date
                if trust_date and best["signature_date"]:
                    td = date.fromisoformat(str(trust_date))
                    fd = best["signature_date"]
                    date_gap = abs((fd - td).days) // 365
            except Exception:
                pass
            candidates_out.append({
                "trust_accession": trust_acc,
                "fee_accession":   best["accession_number"],
                "extracted_raw":   extracted,
                "match_type":      f"fuzzy(d={best_dist})",
                "trust_name":      trust_name,
                "fee_name":        best["full_name"],
                "name_overlap":    ";".join(sorted(shared)),
                "name_consistent": "yes" if shared else "no",
                "date_gap_years":  date_gap if date_gap is not None else "",
                "trust_date":      trust_date,
                "fee_date":        best["signature_date"],
                "fee_authority":   best["authority"],
                "fee_state":       best["state"],
            })
            continue

        stats["unmatched"] += 1
        unmatched_out.append({
            "trust_accession": trust_acc,
            "allottee":        trust_name,
            "extracted_raw":   extracted,
            "trust_date":      trust_date,
            "remarks_raw":     row.get("remarks_raw", ""),
        })

    # Write outputs
    with open(CANDIDATES_CSV, "w", newline="") as f:
        if candidates_out:
            w = csv.DictWriter(f, fieldnames=list(candidates_out[0].keys()))
            w.writeheader()
            for r in candidates_out:
                w.writerow(r)
    with open(UNMATCHED_CSV, "w", newline="") as f:
        if unmatched_out:
            w = csv.DictWriter(f, fieldnames=list(unmatched_out[0].keys()))
            w.writeheader()
            for r in unmatched_out:
                w.writerow(r)

    total = len(with_fee)
    print()
    print("=== Validation summary ===")
    for k in ["exact", "normalized", "fuzzy", "unmatched"]:
        n = stats.get(k, 0)
        pct = 100 * n / total if total else 0
        print(f"  {k:12s} {n:6d}  ({pct:.0f}%)")
    print()

    # Date-gap distribution among matches
    gaps = [c["date_gap_years"] for c in candidates_out if c["date_gap_years"] != "" and c["date_gap_years"] is not None]
    if gaps:
        gaps = sorted(int(g) for g in gaps if g != "")
        n = len(gaps)
        median = gaps[n // 2]
        p25 = gaps[n // 4]
        p75 = gaps[(3 * n) // 4]
        print(f"Date gap (trust -> fee, years) across {n} matches: p25={p25} median={median} p75={p75}")
        print(f"  min={gaps[0]}  max={gaps[-1]}")

    # Name-consistency check
    name_yes = sum(1 for c in candidates_out if c["name_consistent"] == "yes")
    print()
    print(f"Name overlap on matches: {name_yes}/{len(candidates_out)} = {100*name_yes/len(candidates_out):.0f}% share at least one name token")
    print(f"  (low overlap usually means name normalization differences, not wrong match)")

    # Authority distribution of matched fee patents
    auth = Counter(c["fee_authority"] for c in candidates_out)
    print()
    print("Authority of matched 'fee' patents:")
    for a, n in auth.most_common(10):
        print(f"  {n:6d}  {a}")

    print()
    print(f"Outputs:")
    print(f"  {CANDIDATES_CSV}  ({len(candidates_out)} candidate linkages)")
    print(f"  {UNMATCHED_CSV}   ({len(unmatched_out)} unmatched extractions)")


if __name__ == "__main__":
    main()
