#!/bin/bash
# Extend the probe range for SD2610 and SD2620 from .551 to .700.
# scrape_blm_volume.py is resumable — it skips accessions already in the
# output CSV — so this only probes the new range without re-doing .001-.550.
#
# After both finish, the script prints what was added so we can decide
# whether to re-import. Total runtime ~15 min per volume = ~30 min.
set -e
cd /Users/cwm6W/projects/american-indian-allotment

echo "======================="
echo "=== SD2610 .551-.700 ==="
echo "======================="
./venv/bin/python3 scripts/scrape_blm_volume.py --volume SD2610__ --min 551 --max 700

echo
echo "======================="
echo "=== SD2620 .551-.700 ==="
echo "======================="
./venv/bin/python3 scripts/scrape_blm_volume.py --volume SD2620__ --min 551 --max 700

echo
echo "================================"
echo "=== Status of the extensions ==="
echo "================================"
for VOL in SD2610 SD2620; do
  echo "--- $VOL ---"
  ./venv/bin/python3 - <<EOF
import csv, re
from collections import Counter
ok = 0
not_found = 0
errors = 0
authority = Counter()
with open("data/rescrape_${VOL}.csv") as f:
    for r in csv.DictReader(f):
        # Only count the .551-.700 range
        m = re.search(r'\.(\d+)\$', r['accession_number'])
        if not m: continue
        n = int(m.group(1))
        if n < 551 or n > 700: continue
        if r['status'] == 'ok':
            ok += 1
            a = r.get('authority') or ''
            am = re.search(r':\s*(.+?)\s*\(', a)
            authority[am.group(1) if am else (a or '(empty)')] += 1
        elif r['status'] == 'not_found':
            not_found += 1
        else:
            errors += 1
print(f"  .551-.700 results: ok={ok}, not_found={not_found}, errors={errors}")
if authority:
    print(f"  Authority distribution:")
    for k, v in authority.most_common():
        print(f"    {v:>4}  {k!r}")
EOF
  echo
done
