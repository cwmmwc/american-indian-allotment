"""
Sample 50 patents from the residual CSV for the v5 Sonnet validation run.
Stratified by year, reproducible (different seed from the 300-benchmark so the
samples don't overlap by accident).
"""
import csv
import os
import random
from collections import defaultdict

CSV_IN   = "blm_residual_v4_ser_loren_window.csv"
PDF_DIR  = "blm_pdfs"
CSV_OUT  = "blm_benchmark_50.csv"
N_TOTAL  = 50
SEED     = 0xDEAD

random.seed(SEED)

with open(CSV_IN) as f:
    rows = list(csv.DictReader(f))
header = list(rows[0].keys())

on_disk = [r for r in rows if os.path.exists(os.path.join(PDF_DIR, r["accession_number"] + ".pdf"))]
print(f"PDFs eligible: {len(on_disk):,}")

by_year = defaultdict(list)
for r in on_disk:
    y = (r.get("signature_date") or "")[:4]
    by_year[y].append(r)

total_eligible = sum(len(v) for v in by_year.values())
quota = {y: max(1, round(N_TOTAL * len(v) / total_eligible)) for y, v in by_year.items()}

while sum(quota.values()) > N_TOTAL:
    biggest = max(quota, key=quota.get)
    quota[biggest] -= 1
while sum(quota.values()) < N_TOTAL:
    biggest_eligible = max(quota, key=lambda y: len(by_year[y]) - quota[y])
    quota[biggest_eligible] += 1

sample = []
for y, q in quota.items():
    sample.extend(random.sample(by_year[y], min(q, len(by_year[y]))))

random.shuffle(sample)
assert len(sample) == N_TOTAL, f"got {len(sample)} rows, expected {N_TOTAL}"

with open(CSV_OUT, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=header)
    w.writeheader()
    for r in sample:
        w.writerow(r)

print(f"wrote {CSV_OUT} ({N_TOTAL} rows)")
