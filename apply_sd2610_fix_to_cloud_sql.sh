#!/bin/bash
# Re-run scripts/fix_sd2610_authority.py against Cloud SQL via the proxy.
#
# Why: the first run against Cloud SQL did DELETE + ALTER + UPDATE + then
# crashed on CREATE OR REPLACE VIEW (appuser wasn't the view owner yet).
# The crash rolled back the whole transaction. After the OWNER transfer
# done by update_cloud_sql_view.sh, the view step now succeeds, so the
# full transaction commits cleanly.
#
# Idempotent — the script checks for column existence before ALTERing,
# and the DELETE/UPDATE/CREATE OR REPLACE are all no-ops on second run.
set -e

DATABASE_URL="host=127.0.0.1 port=5433 dbname=allotment_research user=appuser password=allotment-app-2026" \
  /Users/cwm6W/projects/american-indian-allotment/venv/bin/python3 \
  /Users/cwm6W/projects/american-indian-allotment/scripts/fix_sd2610_authority.py
