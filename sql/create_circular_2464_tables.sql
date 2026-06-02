-- Circular 2464 corpus integration — Phase 1 schema (Layer 1 only)
--
-- Adds three objects to the existing `allotment_research` database, all
-- prefixed `circular_2464_` so they sit alongside the existing 25 tables
-- without colliding:
--
--   circular_2464_documents          one row per source extraction JSON
--   circular_2464_records            one row per allottee, the 18 flat fields
--                                    plus authoritative_tribe resolved at load
--                                    time via tribe_crosswalk
--   circular_2464_allotment_matches  materialized view joining records to
--                                    blm_allotment_patents and
--                                    federal_register_claims on
--                                    (allotment_number, authoritative_tribe)
--
-- Strictly additive. No DROP, ALTER, or UPDATE against any existing table.
-- Idempotent: IF NOT EXISTS on every CREATE. Safe to re-run.
--
-- Layer 2/3 enrichment (Kimi v5 entities, Sonnet vision fee_patents, mortgages,
-- testimony, taxes, financial_transactions) is deferred to a later phase and
-- will add additional tables alongside these. The schema below is the
-- minimum needed to expose the corpus in the Flask app.
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

-- Composite (allotment_number, authoritative_tribe) is the materialized
-- view's join key — make it cheap.
CREATE INDEX IF NOT EXISTS idx_c2464_rec_join
    ON circular_2464_records(allotment_number, authoritative_tribe);

-- ─────────────────────────────────────────────────────────────────
-- circular_2464_allotment_matches  (materialized view)
--
--   Pre-computes the bridge between the 1928 testimony corpus and the
--   existing patent / claim universe. One row per
--   (testimony_record × BLM patent × FR claim) combination. LEFT JOINs
--   so testimony records with no BLM or FR match still appear with
--   NULL on those columns — absence is data.
--
--   Refreshed by the loader at the end of every run:
--       REFRESH MATERIALIZED VIEW circular_2464_allotment_matches;
-- ─────────────────────────────────────────────────────────────────

CREATE MATERIALIZED VIEW IF NOT EXISTS circular_2464_allotment_matches AS
SELECT
    r.id                            AS record_id,
    r.document_id                   AS document_id,
    r.name                          AS testimony_name,
    r.allotment_number              AS allotment_number,
    r.authoritative_tribe           AS authoritative_tribe,
    r.tribe_reservation             AS testimony_tribe_label,
    r.fee_patent_date               AS testimony_fee_patent_date,

    bap.objectid                    AS blm_patent_objectid,
    bap.accession_number            AS blm_accession,
    bap.full_name                   AS blm_patentee,
    bap.signature_date              AS blm_signature_date,
    bap.authority                   AS blm_authority,
    bap.preferred_name              AS blm_preferred_name,

    fr.id                           AS fr_claim_id,
    fr.case_number                  AS fr_case_number,
    fr.claim_type                   AS fr_claim_type,
    fr.allottee_name                AS fr_allottee_name,
    fr.bia_agency_code              AS fr_bia_agency_code
FROM circular_2464_records r
LEFT JOIN blm_allotment_patents bap
    ON r.allotment_number IS NOT NULL
    AND r.allotment_number <> ''
    AND r.allotment_number = bap.indian_allotment_number
    AND r.authoritative_tribe IS NOT NULL
    AND r.authoritative_tribe = bap.preferred_name
LEFT JOIN federal_register_claims fr
    ON r.allotment_number IS NOT NULL
    AND r.allotment_number <> ''
    AND r.allotment_number = fr.allotment_number
    AND r.authoritative_tribe IS NOT NULL
    AND r.authoritative_tribe = fr.tribe_identified;

CREATE INDEX IF NOT EXISTS idx_c2464_matches_record ON circular_2464_allotment_matches(record_id);
CREATE INDEX IF NOT EXISTS idx_c2464_matches_allot ON circular_2464_allotment_matches(allotment_number);
CREATE INDEX IF NOT EXISTS idx_c2464_matches_blm ON circular_2464_allotment_matches(blm_patent_objectid);
CREATE INDEX IF NOT EXISTS idx_c2464_matches_fr ON circular_2464_allotment_matches(fr_claim_id);

COMMIT;
