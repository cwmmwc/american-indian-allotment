-- Add io_labeled tracking to patent_file_references + patent_file_ref_links.
--
-- Per-link (patent_file_ref_links.io_labeled): what BLM's column placement OR
-- the remarks transcriber's label OR the vision pipeline's reading says about
-- whether this specific occurrence carried an "I.O." mark on the document.
-- Values: 'yes' | 'no' | 'unknown'.
--
-- Per-ref rollup (patent_file_references.io_labeled): aggregated across all
-- links to this ref. 'yes' if any/all link says yes; 'no' if all say no;
-- 'mixed' if both yes and no exist; 'unknown' if no link evidence.
--
-- Values are loose text (not CHECK-constrained) so backfill scripts and
-- future vision pipeline runs can write them without migration overhead.
-- Schema is additive; existing rows get NULL io_labeled until backfilled.

ALTER TABLE patent_file_ref_links   ADD COLUMN IF NOT EXISTS io_labeled TEXT;
ALTER TABLE patent_file_references  ADD COLUMN IF NOT EXISTS io_labeled TEXT;

CREATE INDEX IF NOT EXISTS idx_pfrl_io_labeled ON patent_file_ref_links  (io_labeled);
CREATE INDEX IF NOT EXISTS idx_pfr_io_labeled  ON patent_file_references (io_labeled);
