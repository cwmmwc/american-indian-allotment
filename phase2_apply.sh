#!/bin/bash
# Phase 2 step 2: import the scraped CSV into rails_patents (local + Cloud SQL)
# and run fix_volume_authority on both. Idempotent.
#
# Usage: ./phase2_apply.sh NE1360__
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

if [ ! -f "$CSV" ]; then
  echo "ERROR: $CSV not found. Run ./phase2_scrape.sh $VOLUME first."
  exit 1
fi

echo "===================="
echo "=== LOCAL import ==="
echo "===================="
./venv/bin/python3 scripts/import_rescrape_to_rails_patents.py --csv "$CSV" --apply

echo
echo "===================="
echo "=== LOCAL fix    ==="
echo "===================="
./venv/bin/python3 scripts/fix_volume_authority.py --volume "$VOLUME"

echo
echo "========================="
echo "=== CLOUD SQL import  ==="
echo "========================="
DATABASE_URL="host=127.0.0.1 port=5433 dbname=allotment_research user=appuser password=allotment-app-2026" \
  ./venv/bin/python3 scripts/import_rescrape_to_rails_patents.py --csv "$CSV" --apply

echo
echo "========================="
echo "=== CLOUD SQL fix     ==="
echo "========================="
DATABASE_URL="host=127.0.0.1 port=5433 dbname=allotment_research user=appuser password=allotment-app-2026" \
  ./venv/bin/python3 scripts/fix_volume_authority.py --volume "$VOLUME"
