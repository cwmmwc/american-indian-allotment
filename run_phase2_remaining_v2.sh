#!/bin/bash
# Phase 2 remaining (v2 — audit-bounded + higher until-empty threshold).
#
# For each of the 7 volumes, queries rails_patents for the existing max
# accession number ("audit_max"), then scrapes .001 through (audit_max +
# 200) with --until-empty 250. This combines:
#  (a) audit-bounded range — probes the whole known data range + 200 margin
#  (b) high --until-empty threshold — 250 > NE2890's biggest observed
#      internal gap of 138, so the seen_any_ok-then-50-nfs termination
#      that fails on sparse volumes is replaced by something more tolerant
#
# The new --until-empty=250 doesn't actually fire within audit_max+200
# for any of these 7 volumes (it would need 250 nfs after the last ok,
# and audit_max+200 only allows 200 nfs past last_ok). So effectively
# the upper bound is audit_max+200; the --until-empty is a defensive
# layer if future volumes have unbounded tails.
#
# Resumable: scrape_blm_volume.py skips accessions already in the
# output CSV, so cached results from prior runs (including the failed
# --until-empty 50 run) are used and not re-probed.
#
# Run after stopping any in-flight phase2 scraper. Total runtime ~3.3 hrs
# for fresh runs across all 7; less if some are partially cached.
set -e
cd /Users/cwm6W/projects/american-indian-allotment

mkdir -p logs
LOG="logs/phase2_remaining_v2_$(date +%Y%m%d_%H%M%S).log"
echo "Logging to: $LOG"

VOLUMES=(NE2890__ KS0630__ NE2870__ UT0250__ OK1840__ NE2950__ WI3790__)

{
  echo "Phase 2 remaining (v2): ${#VOLUMES[@]} volumes, sequential, audit-bounded"
  echo "Started: $(date)"
  echo

  for VOLUME in "${VOLUMES[@]}"; do
    # Query audit_max for this volume
    AUDIT_MAX=$(psql -d allotment_research -tA -c "
      SELECT COALESCE(MAX(CAST(substring(accession_number FROM '\.(\d+)\$') AS int)), 0)
      FROM rails_patents
      WHERE accession_number LIKE '${VOLUME}%'
        AND accession_number ~ '^[A-Z]{2}[0-9]+__\.[0-9]+\$'
    ")
    if [ -z "$AUDIT_MAX" ] || [ "$AUDIT_MAX" = "0" ]; then
      echo "WARNING: no audit_max for $VOLUME — defaulting to 600"
      AUDIT_MAX=600
    fi
    MAX=$((AUDIT_MAX + 200))

    echo "=================================="
    echo "=== $VOLUME ($(date +%H:%M:%S)) ==="
    echo "===   audit_max=.${AUDIT_MAX}, probing .001-.${MAX}"
    echo "=================================="
    PYTHONUNBUFFERED=1 ./venv/bin/python3 scripts/scrape_blm_volume.py \
      --volume "$VOLUME" \
      --min 1 \
      --max "$MAX" \
      --until-empty 250 \
      || echo "[ERROR: $VOLUME exited non-zero — moving on]"
    echo
  done

  echo "Finished: $(date)"
} 2>&1 | tee "$LOG"
