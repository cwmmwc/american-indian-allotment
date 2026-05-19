-- cancelled_patent_research: hand-curated research data on fee patents that
-- were later cancelled. Source: Cancelled patents_6.11._cwm.xlsx, hand-built
-- by Christian McMillen documenting the legal authority and circumstances
-- of each cancellation. Complements the BLM cancelled_doc flag in all_patents,
-- which knows that cancellation happened but carries no reason information
-- for ~86% of cancelled patents.

DROP TABLE IF EXISTS cancelled_patent_research;

CREATE TABLE cancelled_patent_research (
    id                     SERIAL PRIMARY KEY,
    name                   TEXT,
    allotment_number       TEXT,
    tribe_reservation      TEXT,
    state                  TEXT,
    reason_for_cancellation TEXT,
    cancellation_date      DATE,
    fee_patent_date        DATE,
    patent_number          TEXT,
    ccf_number             TEXT,
    gender                 TEXT,
    carlisle_yn            TEXT,
    comments               TEXT,
    in_dtpo                TEXT,
    ccf_alt                TEXT,
    source                 TEXT DEFAULT 'mcmillen_cancelled_patents_spreadsheet',
    source_row_index       INT,
    imported_at            TIMESTAMP DEFAULT now()
);

CREATE INDEX cancelled_patent_research_patent_idx ON cancelled_patent_research (patent_number);
CREATE INDEX cancelled_patent_research_name_idx   ON cancelled_patent_research (name);
CREATE INDEX cancelled_patent_research_tribe_idx  ON cancelled_patent_research (tribe_reservation);
CREATE INDEX cancelled_patent_research_reason_idx ON cancelled_patent_research (reason_for_cancellation);

COMMENT ON TABLE cancelled_patent_research IS 'Hand-curated research data on fee patents that were later cancelled. Source: Cancelled patents_6.11._cwm.xlsx by Christian McMillen. Provides legal authority (1927 Act, 1931 Act, individual orders) and CCF references for cancelled patents that the BLM digital cancelled_doc flag alone does not document.';
