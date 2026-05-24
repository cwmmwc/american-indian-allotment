"""
Sample 300 patents from the residual CSV that have PDFs on disk, for a
head-to-head benchmark of Opus vs Sonnet on the v4 extraction task.

Stratified by signature year so the sample spans the 1907-1942 window
rather than clustering in any single year. Reproducible (fixed seed).
"""
import csv
import os
import random
from collections import defaultdict

CSV_IN   = "blm_residual_v4_ser_loren_window.csv"
PDF_DIR  = "blm_pdfs"
CSV_OUT  = "blm_benchmark_300.csv"
N_TOTAL  = 300
SEED     = 0x42  # reproducibility

random.seed(SEED)

# Read all eligible rows.
with open(CSV_IN) as f:
    rows = list(csv.DictReader(f))
header = list(rows[0].keys())

# Keep only those whose PDF exists on disk.
on_disk = [r for r in rows if os.path.exists(os.path.join(PDF_DIR, r["accession_number"] + ".pdf"))]
print(f"rows in CSV:      {len(rows):,}")
print(f"PDFs on disk:     {len(on_disk):,}")

# Stratify by year.
by_year = defaultdict(list)
for r in on_disk:
    y = (r.get("signature_date") or "")[:4]
    by_year[y].append(r)

print()
print("year distribution in eligible pool (years with >0 eligible):")
for y in sorted(by_year):
    print(f"  {y}  {len(by_year[y]):,}")

# Proportional allocation across years, with a minimum of 1 per year that has any.
total_eligible = sum(len(v) for v in by_year.values())
quota = {y: max(1, round(N_TOTAL * len(v) / total_eligible)) for y, v in by_year.items()}

# Quotas may sum to slightly more or less than N_TOTAL due to rounding. Adjust
# by trimming the year with the largest quota (or growing it if we are under).
def quota_sum():
    return sum(quota.values())

while quota_sum() > N_TOTAL:
    biggest = max(quota, key=quota.get)
    quota[biggest] -= 1

while quota_sum() < N_TOTAL:
    biggest_eligible = max(quota, key=lambda y: len(by_year[y]) - quota[y])
    quota[biggest_eligible] += 1

# Draw the sample.
sample = []
for y, q in quota.items():
    sample.extend(random.sample(by_year[y], min(q, len(by_year[y]))))

# Shuffle so the extraction does not process the corpus in year order.
random.shuffle(sample)
assert len(sample) == N_TOTAL, f"got {len(sample)} rows, expected {N_TOTAL}"

# Write out.
with open(CSV_OUT, "w", newline="") as f:
    w = csv.DictWriter(f, fieldnames=header)
    w.writeheader()
    for r in sample:
        w.writerow(r)

print()
print(f"wrote {CSV_OUT} ({N_TOTAL} rows)")
print()
print("year distribution in the sample:")
year_counts = defaultdict(int)
for r in sample:
    year_counts[(r.get("signature_date") or "")[:4]] += 1
for y in sorted(year_counts):
    print(f"  {y}  {year_counts[y]}")
