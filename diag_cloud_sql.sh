#!/bin/bash
# Diagnostic for Cloud SQL connection state via the proxy.
# Tests proxy reachability and appuser credentials in isolation.
set -e

echo "=== 1. Is anything listening on 127.0.0.1:5433? ==="
lsof -i :5433 -P -n | head -5 || echo "  nothing on :5433 (proxy is down)"
echo

echo "=== 2. appuser via proxy ==="
PGPASSWORD='allotment-app-2026' \
  psql "host=127.0.0.1 port=5433 dbname=allotment_research user=appuser" \
  -c "SELECT current_user, current_database()" 2>&1 || true
