-- Patent file-reference tracking for the allotment-research database.
--
-- These tables hold structural references of the form NNNNN-YY (five-digit
-- "letter" number + two-digit year) that appear on BLM patent documents and
-- in their transcribed `remarks` field. The name is deliberately NEUTRAL:
-- some of these refs are true BIA Central Classified Files (CCF) / Indian
-- Office (IO) references, but others share the format without being CCF.
--
-- BIA CCF citation structure (per NARA): a full citation has FOUR elements --
--     letter_number / year / decimal_classification / agency_or_jurisdiction
-- e.g. 12540 / 1950 / 307.4 / Alaska. Only `decimal_classification` + `agency`
-- carry semantic meaning; the 5-digit letter_number is just the ID of the
-- first letter that opened the file. We only ever recover (letter, year) from
-- patent documents; the other two elements come from NARA verification.
--
-- KNOWN DATA-QUALITY ISSUE (see DATABASE.md "Data Quality Caveats"):
-- BLM remarks transcribers loosely applied "IO #" to any NNNNN-YY number in
-- the patent's top-left form-number block, even when the original document
-- carried no IO label. The `context_label` column captures what was claimed,
-- not what was true; verification status lives on `nara_verified`.
--
-- Relationship is many-to-many: one file can be referenced by many patents
-- (Fred Nason's 1908 fee batch -- 5 patents share #60798-08 in remarks), and
-- one patent can reference multiple files (trust application, fee conversion,
-- cancellation, etc.).
--
-- See: https://www.archives.gov/research/native-americans/central-classified-files

CREATE TABLE IF NOT EXISTS patent_file_references (
    id              SERIAL PRIMARY KEY,
    letter_number   TEXT    NOT NULL,
    year            INTEGER,           -- 4-digit; null if year not recoverable
    year_raw        TEXT,              -- 2-digit suffix as it appears in source
    decimal_class   TEXT,              -- e.g. "307.4"; populated later from NARA scheme
    agency          TEXT,              -- e.g. "Leech Lake"; populated later
    nara_verified   BOOLEAN DEFAULT FALSE,
    nara_url        TEXT,
    notes           TEXT,
    created_at      TIMESTAMP DEFAULT NOW(),
    UNIQUE (letter_number, year_raw)
);

CREATE INDEX IF NOT EXISTS idx_pfr_letter   ON patent_file_references (letter_number);
CREATE INDEX IF NOT EXISTS idx_pfr_year     ON patent_file_references (year);
CREATE INDEX IF NOT EXISTS idx_pfr_verified ON patent_file_references (nara_verified);

CREATE TABLE IF NOT EXISTS patent_file_ref_links (
    id                  SERIAL PRIMARY KEY,
    patent_accession    TEXT    NOT NULL,         -- accession_number (universal key in this DB)
    file_ref_id         INTEGER NOT NULL REFERENCES patent_file_references(id) ON DELETE CASCADE,
    context_label       TEXT,                     -- as transcribed: "IO", "ADDITIONAL IO", "ADDITIONAL DOCUMENT", "unlabeled"
    source_location     TEXT    NOT NULL,         -- 'remarks' | 'top_left_header' | 'manual'
    source_table        TEXT,                     -- which table the remark was scanned from
    matched_text        TEXT,                     -- the literal substring from remarks
    notes               TEXT,
    created_at          TIMESTAMP DEFAULT NOW(),
    UNIQUE (patent_accession, file_ref_id, context_label, source_location)
);

CREATE INDEX IF NOT EXISTS idx_pfrl_acc    ON patent_file_ref_links (patent_accession);
CREATE INDEX IF NOT EXISTS idx_pfrl_refid  ON patent_file_ref_links (file_ref_id);
CREATE INDEX IF NOT EXISTS idx_pfrl_source ON patent_file_ref_links (source_location);
