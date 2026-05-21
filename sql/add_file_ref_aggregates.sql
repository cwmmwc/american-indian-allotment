-- Materialized aggregate columns on patent_file_references.
--
-- These mirror what the old /file_refs route's inline GROUP BY computed.
-- Pre-computing them once after each backfill lets the new server-side
-- DataTables API return paged results with a simple SELECT … LIMIT/OFFSET,
-- which is ~50ms regardless of corpus size. The alternative (computing the
-- aggregates per API call on 180k links) would be a few seconds per request.
--
-- Recompute via scripts/compute_file_ref_aggregates.py after any new
-- backfill (remarks, structured, or future vision-pipeline).

ALTER TABLE patent_file_references
    ADD COLUMN IF NOT EXISTS patent_count        INTEGER,
    ADD COLUMN IF NOT EXISTS state_list          TEXT,
    ADD COLUMN IF NOT EXISTS top_tribe           TEXT,
    ADD COLUMN IF NOT EXISTS top_context_label   TEXT,
    ADD COLUMN IF NOT EXISTS min_signature_date  DATE,
    ADD COLUMN IF NOT EXISTS max_signature_date  DATE;

CREATE INDEX IF NOT EXISTS idx_pfr_patent_count ON patent_file_references (patent_count DESC);
CREATE INDEX IF NOT EXISTS idx_pfr_year        ON patent_file_references (year);
CREATE INDEX IF NOT EXISTS idx_pfr_state_list  ON patent_file_references (state_list);
CREATE INDEX IF NOT EXISTS idx_pfr_top_tribe   ON patent_file_references (top_tribe);
