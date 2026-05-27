#!/bin/bash
# Re-extend SD2610, SD2620, and NE1360 with --until-empty 50.
#
# Stops probing each volume after 50 consecutive 'not_found' responses
# (counts both new probes and stored statuses from prior runs). Hard
# ceiling at .1500.
#
# Run AFTER ./extend_probe_sd2610_sd2620.sh has finished — this script
# uses the already-probed range as a baseline and only probes beyond it
# until BLM signals "nothing more here."
#
# Run sequentially (not parallel) to keep the BLM-side load mannerly.
set -e
cd /Users/cwm6W/projects/american-indian-allotment

for VOLUME in SD2610__ SD2620__ NE1360__; do
  echo "============================="
  echo "=== $VOLUME --until-empty 50 ==="
  echo "============================="
  ./venv/bin/python3 scripts/scrape_blm_volume.py \
    --volume "$VOLUME" \
    --min 1 \
    --max 1500 \
    --until-empty 50
  echo
done

echo "Done. If any volume reported a 'last ok' past .550, the additions are"
echo "in data/rescrape_<volume>.csv and ready to import via ./phase2_apply.sh"
