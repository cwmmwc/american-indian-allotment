-- Circular 2464 corpus integration — Phase 1 schema (Layer 1 only)
--
-- Adds two tables to the existing `allotment_research` database, both
-- prefixed `circular_2464_` so they sit alongside the existing 25 tables
-- without colliding:
--
--   circular_2464_documents   one row per source extraction JSON
--   circular_2464_records     one row per allottee, the 18 flat fields
--                             plus authoritative_tribe resolved at load
--                             time via tribe_crosswalk
--
-- The BLM ↔ FR linkage for testimony records is intentionally NOT
-- precomputed here. The Flask routes that surface testimony will join
-- `circular_2464_records` to `blm_allotment_patents` and
-- `forced_fee_patents_rails` inline, matching the pattern `app.py`
-- already uses everywhere for BLM↔FR linkages.
--
-- Strictly additive. No DROP, ALTER, or UPDATE against any existing table.
-- Idempotent: IF NOT EXISTS on every CREATE. Safe to re-run.
--
-- Run with:  psql -d allotment_research -f sql/create_circular_2464_tables.sql

BEGIN;

-- ─────────────────────────────────────────────────────────────────
-- circular_2464_documents
-- ─────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS circular_2464_documents (
    id                  SERIAL PRIMARY KEY,
    document_id         TEXT NOT NULL UNIQUE,    -- e.g. "part1_affidavit_001"
    document_type       TEXT NOT NULL,           -- affidavit | questionnaire | agency_narrative | ledger_entry
    source_pdf          TEXT,                    -- e.g. "RG 75 1929 Circular 2464 part 1.pdf"
    source_pages        TEXT,                    -- e.g. "96" or "42-43"
    part_number         INTEGER,                 -- parsed from document_id ("part12_..." -> 12)
    extraction_model    TEXT,                    -- sonnet | qwen-vl-72b
    created_at          TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_c2464_docs_type ON circular_2464_documents(document_type);
CREATE INDEX IF NOT EXISTS idx_c2464_docs_part ON circular_2464_documents(part_number);

-- ─────────────────────────────────────────────────────────────────
-- circular_2464_records
--   The 18 flat fields from each extraction's `extraction` block, plus
--   the load-time resolved authoritative_tribe and a JSONB column that
--   preserves the structured recovery_notes audit trail verbatim.
-- ─────────────────────────────────────────────────────────────────

CREATE TABLE IF NOT EXISTS circular_2464_records (
    id                      SERIAL PRIMARY KEY,
    document_id             INTEGER NOT NULL REFERENCES circular_2464_documents(id) ON DELETE CASCADE,
    record_index            INTEGER NOT NULL DEFAULT 0,
    -- Most JSONs hold one allottee record (record_index=0). The Fort Berthold
    -- ledger pages and a handful of bundled affidavits/narratives hold
    -- multiple records per file; those get record_index = 0, 1, 2, ... in
    -- source-document order. UNIQUE(document_id, record_index) below is the
    -- upsert key.
    UNIQUE (document_id, record_index),

    -- 18 flat fields, all kept as TEXT because the source extraction
    -- intentionally preserves strings like "not stated" alongside real values.
    name                    TEXT,
    tribe_reservation       TEXT,                -- raw label from the affidavit/questionnaire
    authoritative_tribe     TEXT,                -- resolved via tribe_crosswalk at load time;
                                                 -- NULL when the corpus label is FRN, blank,
                                                 -- or doesn't appear in the crosswalk
    post_office_address     TEXT,
    allotment_number        TEXT,
    cancelled               TEXT,
    refused_protested       TEXT,
    recorded_patent         TEXT,
    sold_mortgaged          TEXT,
    buyer                   TEXT,
    tax_burden              TEXT,                -- source key: "Tax burden forced sale/Mortgage"
    trust_patent_date       TEXT,
    fee_patent_date         TEXT,
    gender                  TEXT,
    age                     TEXT,
    occupation_income       TEXT,
    literate_illiterate     TEXT,
    notes                   TEXT,                -- the prose NOTES field

    -- Provenance
    recovery_notes_json     JSONB,               -- preserves the structured audit trail
                                                 -- (date, type, method, source_url,
                                                 -- previous_values, corrected_values,
                                                 -- user_confirmed, etc.) verbatim
    source_layer            TEXT NOT NULL DEFAULT 'sonnet_text',

    -- Full-text search across the substantive prose fields
    search_vector           tsvector,

    created_at              TIMESTAMP DEFAULT CURRENT_TIMESTAMP
);

CREATE INDEX IF NOT EXISTS idx_c2464_rec_doc ON circular_2464_records(document_id);
CREATE INDEX IF NOT EXISTS idx_c2464_rec_allot ON circular_2464_records(allotment_number);
CREATE INDEX IF NOT EXISTS idx_c2464_rec_auth_tribe ON circular_2464_records(authoritative_tribe);
CREATE INDEX IF NOT EXISTS idx_c2464_rec_name ON circular_2464_records(name);
CREATE INDEX IF NOT EXISTS idx_c2464_rec_fee_date ON circular_2464_records(fee_patent_date);
CREATE INDEX IF NOT EXISTS idx_c2464_rec_fts ON circular_2464_records USING gin(search_vector);

-- Composite (allotment_number, authoritative_tribe) is the join key the
-- Flask routes use when looking up matching BLM patents — make it cheap.
CREATE INDEX IF NOT EXISTS idx_c2464_rec_join
    ON circular_2464_records(allotment_number, authoritative_tribe);

COMMIT;
