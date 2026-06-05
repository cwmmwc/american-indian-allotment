#!/usr/bin/env bash
# The all_patents view is owned by appuser (normal Cloud SQL pattern — postgres
# isn't a true superuser there). Apply the view DDL as appuser, which has the
# rights to CREATE OR REPLACE its own view.
set -euo pipefail

CONN="host=127.0.0.1 port=5433 dbname=allotment_research user=appuser password=allotment-app-2026"
SQL_FILE="sql/update_all_patents_view_with_recovered.sql"

echo "Step 1/2: Apply view DDL as appuser..."
psql "$CONN" -f "$SQL_FILE"

echo
echo "Step 2/2: Verify..."
psql "$CONN" <<'SQL'
\echo '--- all_patents view counts (should show is_mappable column now) ---'
SELECT COUNT(*) FILTER (WHERE is_mappable)        AS mappable,
       COUNT(*) FILTER (WHERE NOT is_mappable)    AS not_mappable,
       COUNT(*) FILTER (WHERE has_plss_geometry)  AS in_blm_mirror_unchanged,
       COUNT(*) AS total
FROM all_patents;

\echo '--- Lizzie 1919 via the view ---'
SELECT accession_number, full_name, has_plss_geometry, is_mappable,
       centroid_lat::numeric(7,4) AS lat, centroid_lon::numeric(8,4) AS lon
FROM all_patents WHERE accession_number = '715724';
SQL

echo
echo "Done."
