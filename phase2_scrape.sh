#!/bin/bash
# Phase 2 step 1: scrape one gappy state volume from glorecords.blm.gov.
# Outputs data/rescrape_<volume_clean>.csv + data/blm_html_<volume_clean>/.
# When done, prints the BLM authority distribution so you can decide whether
# any new authority strings need to be added to TRUST_AUTHORITIES /
# FEE_AUTHORITIES in app.py before importing.
#
# Usage: ./phase2_scrape.sh NE1360__
set -e
if [ -z "$1" ]; then
  echo "usage: $0 <volume_prefix>   e.g. $0 NE1360__"
  exit 1
fi
VOLUME=$1
VOL_CLEAN=${VOLUME%_*}
VOL_CLEAN=${VOL_CLEAN%_}
CSV="data/rescrape_${VOL_CLEAN}.csv"

cd /Users/cwm6W/projects/american-indian-allotment
./venv/bin/python3 scripts/scrape_blm_volume.py --volume "$VOLUME"

echo
echo "=== Authority distribution in $CSV (review before --apply import) ==="
./venv/bin/python3 - <<EOF
import csv, re
from collections import Counter
c = Counter()
with open("$CSV") as f:
    for r in csv.DictReader(f):
        if r['status'] != 'ok':
            continue
        a = r.get('authority') or ''
        m = re.search(r':\s*(.+?)\s*\(', a)
        c[m.group(1) if m else (a or '(empty)')] += 1
for s, n in c.most_common():
    print(f"  {n:>4}  {s!r}")
EOF

echo
echo "Next step: review the distribution above. If any authority string isn't"
echo "in TRUST_AUTHORITIES or FEE_AUTHORITIES in app.py, add it. Then run:"
echo "  ./phase2_apply.sh $VOLUME"
