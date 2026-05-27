#!/bin/bash
# Sequentially scrape the 7 remaining Phase 2 gappy state volumes.
# Each uses --until-empty 50 (terminates after 50 consecutive not_founds,
# hard ceiling .1500).
#
# Run after SD2570__ scrape has completed (you started that one separately).
# Worst case ~3 hrs if every volume runs the full BLM range; many will
# terminate early via stored-status detection.
#
# Output is tee'd to logs/phase2_remaining_<timestamp>.log so you can
# `tail -f` it from another terminal if you want to check progress.
#
# This script does NOT --apply imports — it just scrapes. Once all 7
# finish, review each volume's authority distribution (printed at the end
# of each scrape), then run `./phase2_apply.sh <volume>` per volume.
set -e
cd /Users/cwm6W/projects/american-indian-allotment

mkdir -p logs
LOG="logs/phase2_remaining_$(date +%Y%m%d_%H%M%S).log"
echo "Logging to: $LOG"

VOLUMES=(NE2890__ KS0630__ NE2870__ UT0250__ OK1840__ NE2950__ WI3790__)

{
  echo "Phase 2 remaining: ${#VOLUMES[@]} volumes, sequential"
  echo "Volumes: ${VOLUMES[*]}"
  echo "Started: $(date)"
  echo

  for VOLUME in "${VOLUMES[@]}"; do
    echo "=================================="
    echo "=== $VOLUME ($(date +%H:%M:%S)) ==="
    echo "=================================="
    ./phase2_scrape.sh "$VOLUME" || echo "[ERROR: $VOLUME exited non-zero — moving on]"
    echo
  done

  echo "Finished: $(date)"
} 2>&1 | tee "$LOG"
