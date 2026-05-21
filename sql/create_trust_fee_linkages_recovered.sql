-- Trust-to-fee patent linkages recovered from BLM patent records.
--
-- Two recovery sources contribute rows, distinguished by the `source` column:
--   - remarks_regex_v2 : parse_remarks_fee_refs.py + validate_remarks_extractions.py
--   - parcel_match_v1  : recover_linkages_by_parcel.py (parcel + allottee match)
--
-- Kept distinct from the older `trust_fee_linkages` table (29,229 rows from
-- the originally-computed allotment-matching join) so each table's provenance
-- is preserved and the two sources can be reconciled or unioned downstream.

CREATE TABLE IF NOT EXISTS trust_fee_linkages_recovered (
    id                  SERIAL PRIMARY KEY,
    trust_accession     TEXT    NOT NULL,
    fee_accession       TEXT    NOT NULL,
    extracted_raw       TEXT,                     -- the raw substring from remarks (regex source) or note (parcel source)
    match_type          TEXT,                     -- 'exact' | 'normalized' | 'fuzzy(d=N)' | 'parcel_name'
    name_overlap        TEXT,                     -- shared name tokens (semicolon-separated)
    name_consistent     BOOLEAN,                  -- yes if trust and fee patentee names share tokens
    date_gap_years      INTEGER,                  -- fee_date - trust_date in years (null if either date missing)
    trust_date          DATE,
    fee_date            DATE,
    fee_authority       TEXT,
    fee_state           TEXT,
    source              TEXT    DEFAULT 'remarks_regex_v2',
    created_at          TIMESTAMP DEFAULT NOW(),
    UNIQUE (trust_accession, fee_accession),
    CHECK (trust_accession <> fee_accession)      -- a patent cannot be its own fee patent
);

-- For tables already created without the CHECK constraint, the following is
-- idempotent on Postgres 13+ (NOT VALID skips an existing-row scan). Wrapped
-- in a DO block so it doesn't error if the constraint already exists.
DO $$
BEGIN
    ALTER TABLE trust_fee_linkages_recovered
        ADD CONSTRAINT trust_fee_linkages_recovered_not_self
        CHECK (trust_accession <> fee_accession) NOT VALID;
EXCEPTION WHEN duplicate_object THEN
    NULL;
END $$;

CREATE INDEX IF NOT EXISTS idx_tflr_trust   ON trust_fee_linkages_recovered (trust_accession);
CREATE INDEX IF NOT EXISTS idx_tflr_fee     ON trust_fee_linkages_recovered (fee_accession);
CREATE INDEX IF NOT EXISTS idx_tflr_match   ON trust_fee_linkages_recovered (match_type);
CREATE INDEX IF NOT EXISTS idx_tflr_state   ON trust_fee_linkages_recovered (fee_state);
CREATE INDEX IF NOT EXISTS idx_tflr_consist ON trust_fee_linkages_recovered (name_consistent);
CREATE INDEX IF NOT EXISTS idx_tflr_source  ON trust_fee_linkages_recovered (source);
