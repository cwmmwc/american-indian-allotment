#!/bin/bash
# Apply sql/update_all_patents_view_with_authority.sql to Cloud SQL as
# the postgres superuser via the already-running cloud-sql-proxy on 5433.
#
# Prompts for the postgres password silently — avoids history-expansion
# issues (`!!`, `!$`, etc.) that mangle passwords pasted on the zsh
# command line.
set -e

read -s -p "Cloud SQL postgres password: " PGPASSWORD
echo
export PGPASSWORD

psql "host=127.0.0.1 port=5433 dbname=allotment_research user=postgres" \
  -f /Users/cwm6W/projects/american-indian-allotment/sql/update_all_patents_view_with_authority.sql

unset PGPASSWORD
