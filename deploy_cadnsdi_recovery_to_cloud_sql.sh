#!/usr/bin/env bash
# Coordinated deploy of CadNSDI bulk recovery to Cloud SQL.
#
# PRECONDITIONS
#   1. cloud-sql-proxy already running on 127.0.0.1:5433 (it is — PID was 71625
#      when this script was written).
#   2. Local allotment_research has the 12,907 recovered records to ship.
#
# WHAT IT DOES
#   1. Create cadnsdi_recovered_patents on Cloud SQL (idempotent).
#   2. TRUNCATE cadnsdi_recovered_patents on Cloud SQL (clean reload).
#   3. Apply update_all_patents_view_with_recovered.sql (the view DDL).
#   4. Dump local cadnsdi_recovered_patents and load into Cloud SQL.
#   5. GRANT SELECT to appuser so the Flask app can read the new table.
#   6. Verify counts and sample.
#
# Prompts ONCE for the postgres superuser password; uses it for all steps.

set -euo pipefail

echo "Cloud SQL deploy — CadNSDI recovery"
read -s -p "Cloud SQL postgres password: " PGPASSWORD
echo
export PGPASSWORD

CONN="host=127.0.0.1 port=5433 dbname=allotment_research user=postgres"
SQL_FILE="sql/update_all_patents_view_with_recovered.sql"

if [ ! -f "$SQL_FILE" ]; then
  echo "ERROR: $SQL_FILE not found. Run from project root."
  exit 1
fi

echo
echo "Step 1/6: Create cadnsdi_recovered_patents on Cloud SQL (IF NOT EXISTS)..."
psql "$CONN" <<'SQL'
CREATE TABLE IF NOT EXISTS cadnsdi_recovered_patents (
  accession_number        TEXT PRIMARY KEY,
  full_name               TEXT,
  preferred_name          TEXT,
  signature_date          DATE,
  authority               TEXT,
  document_class          TEXT,
  state                   TEXT,
  county                  TEXT,
  indian_allotment_number TEXT,
  centroid_lat            NUMERIC,
  centroid_lon            NUMERIC,
  geometry_geojson        JSONB NOT NULL,
  cadnsdi_source          TEXT,
  created_at              TIMESTAMP DEFAULT now(),
  township_number         TEXT,
  township_direction      TEXT,
  range_number            TEXT,
  range_direction         TEXT,
  section_number          TEXT,
  aliquot_parts           TEXT,
  meridian_code           TEXT,
  granularity             TEXT CHECK (granularity IN ('parcel', 'section')),
  aliquot_query_used      TEXT
);
SQL

echo
echo "Step 2/6: TRUNCATE existing rows (clean reload)..."
psql "$CONN" -c "TRUNCATE cadnsdi_recovered_patents;"

echo
echo "Step 3/6: Apply all_patents view DDL (additive is_mappable + recovered LEFT JOIN)..."
psql "$CONN" -f "$SQL_FILE"

echo
echo "Step 4/6: Dump local cadnsdi_recovered_patents and load to Cloud SQL..."
pg_dump --data-only --no-owner --no-privileges \
        --table=cadnsdi_recovered_patents \
        --dbname=allotment_research \
        | psql "$CONN"

echo
echo "Step 5/6: GRANT SELECT to appuser..."
psql "$CONN" -c "GRANT SELECT ON cadnsdi_recovered_patents TO appuser;"

echo
echo "Step 6/6: Verify..."
psql "$CONN" <<'SQL'
\echo '--- recovered table totals ---'
SELECT COUNT(*) AS total,
       COUNT(*) FILTER (WHERE granularity='parcel')  AS parcel,
       COUNT(*) FILTER (WHERE granularity='section') AS section
FROM cadnsdi_recovered_patents;

\echo '--- all_patents view counts ---'
SELECT COUNT(*) FILTER (WHERE is_mappable)        AS mappable,
       COUNT(*) FILTER (WHERE NOT is_mappable)    AS not_mappable,
       COUNT(*) FILTER (WHERE has_plss_geometry)  AS in_blm_mirror_unchanged,
       COUNT(*) AS total
FROM all_patents;

\echo '--- Lizzie 1919 sanity check ---'
SELECT accession_number, full_name, granularity,
       jsonb_array_length(geometry_geojson->'coordinates') AS pieces
FROM cadnsdi_recovered_patents WHERE accession_number = '715724';
SQL

unset PGPASSWORD
echo
echo "Cloud SQL deploy complete."
