#!/usr/bin/env bash
# Coordinated deploy of the IATH person tables (people / patent_persons /
# patent_roles) to Cloud SQL, to back per-person patent name search.
#
# RUN THIS YOURSELF IN YOUR TERMINAL — it prompts for the Cloud SQL postgres
# password (interactive) and needs the Cloud SQL Auth Proxy already running.
#
# PRECONDITIONS
#   1. cloud-sql-proxy running on 127.0.0.1:5433, e.g.:
#        cloud-sql-proxy lunar-mercury-397321:us-east1:allotment-db --port 5433 &
#      (The CadNSDI deploy used port 5433; adjust CONN below if yours differs.)
#   2. The IATH export CSVs are on this machine at ~/Desktop/iath_export/
#      (people.csv, patent_persons.csv, patent_roles.csv) — the paths the
#      committed sql/create_iath_people_tables.sql \copy's from.
#   3. Cloud SQL allotment_research already has rails_patents (it does); the
#      patent_persons FK to rails_patents(id) must resolve. If Cloud SQL's
#      rails_patents diverges from local, the load transaction aborts cleanly.
#
# WHAT IT DOES
#   1. Run the committed schema file against Cloud SQL: creates the 3 tables,
#      loads them via client-side \copy from ~/Desktop, builds btree + the two
#      gin_trgm_ops indexes — all in one transaction (atomic; rolls back on error).
#   2. GRANT SELECT on the 3 tables to appuser (the Flask app's role). The schema
#      file omits this because locally cwm6W owns everything; on Cloud SQL the
#      tables are owned by postgres and appuser must be granted read access or
#      name search returns "permission denied" after the code deploys.
#   3. Verify: rush roberts -> 6, caleb carter -> 2 against Cloud SQL.
#
# AFTER this prints 6 and 2, tell Claude (or push yourself): merging to main and
# pushing triggers the Cloud Run build that switches the live app to per-person
# search. Loading first means there is no breakage window.

set -euo pipefail

SCHEMA_FILE="sql/create_iath_people_tables.sql"
if [ ! -f "$SCHEMA_FILE" ]; then
  echo "ERROR: $SCHEMA_FILE not found. Run from the project root."
  exit 1
fi

echo "Cloud SQL deploy — IATH person tables"
read -s -p "Cloud SQL postgres password: " PGPASSWORD
echo
export PGPASSWORD

CONN="host=127.0.0.1 port=5433 dbname=allotment_research user=postgres"

echo
echo "Step 1/3: Create + load people / patent_persons / patent_roles (atomic)..."
echo "         (client-side \\copy streams the ~/Desktop CSVs to Cloud SQL; ~370k"
echo "          rows over the proxy — give it a minute or two.)"
# Prerequisite, done once on 2026-06-16: rails_patents is owned by appuser, and
# Cloud SQL's postgres role is not a true superuser, so postgres lacked REFERENCES
# on it. Granted as appuser:  GRANT REFERENCES ON rails_patents TO postgres;
# With that in place this postgres-run load creates the patent_id -> rails_patents(id)
# FK normally, matching the committed schema (no local/prod divergence).
psql "$CONN" -v ON_ERROR_STOP=1 -f "$SCHEMA_FILE"

echo
echo "Step 2/3: GRANT SELECT to appuser..."
psql "$CONN" -v ON_ERROR_STOP=1 -c \
  "GRANT SELECT ON people, patent_persons, patent_roles TO appuser;"

echo
echo "Step 3/3: Verify per-person search against Cloud SQL..."
psql "$CONN" -v ON_ERROR_STOP=1 <<'SQL'
\echo '--- loaded counts (expect 316776 / 371582 / 1) ---'
SELECT (SELECT count(*) FROM people)         AS people,
       (SELECT count(*) FROM patent_persons) AS patent_persons,
       (SELECT count(*) FROM patent_roles)   AS patent_roles;

SET pg_trgm.similarity_threshold = 0.65;
\echo '--- rush roberts (expect 6) ---'
SELECT count(DISTINCT pp.patent_id) AS rush_roberts
FROM patent_persons pp JOIN people pe ON pe.id = pp.person_id
WHERE pe.glo_first_name % 'rush' AND pe.glo_last_name % 'roberts';

\echo '--- caleb carter (expect 2) ---'
SELECT count(DISTINCT pp.patent_id) AS caleb_carter
FROM patent_persons pp JOIN people pe ON pe.id = pp.person_id
WHERE pe.glo_first_name % 'caleb' AND pe.glo_last_name % 'carter';
SQL

unset PGPASSWORD
echo
echo "Cloud SQL load complete. If the counts above read 6 and 2, the data side is"
echo "ready — proceed to merge main + push to deploy the code."
