-- Load the IATH person-side tables (patent_roles, people, patent_persons)
-- into allotment_research.
--
-- Schema mirrors the IATH source (land-sales.iath.virginia.edu / land-sales
-- database) verified 2026-06-10. Foreign keys to tribes(id) and genders(id) on
-- the source are dropped here because those tables aren't imported.
-- patent_persons.patent_id is FK'd to rails_patents(id) — patent ids are
-- preserved between IATH and the local mirror (verified on the Rush Roberts
-- accessions).
--
-- README §472–481 lists this as pending work. Loading these enables structured
-- name matching (glo_last_name + glo_first_name + glo_middle_name) and exposes
-- the multi-patentee join structure that the scraped full_name column collapses.

BEGIN;

-- pg_trgm backs the gin_trgm_ops indexes below and the % operator used by
-- patent_name_fuzzy_clauses() in app.py. Almost certainly already installed
-- (the patent search has long used pg_trgm); kept here so this file is reproducible.
CREATE EXTENSION IF NOT EXISTS pg_trgm;

DROP TABLE IF EXISTS patent_persons;
DROP TABLE IF EXISTS people;
DROP TABLE IF EXISTS patent_roles;

CREATE TABLE patent_roles (
    id           bigint PRIMARY KEY,
    name         varchar,
    description  text,
    notes        text,
    created_at   timestamp(6) NOT NULL,
    updated_at   timestamp(6) NOT NULL
);

CREATE TABLE people (
    id               bigint PRIMARY KEY,
    glo_last_name    varchar,
    glo_first_name   varchar,
    glo_middle_name  varchar,
    description      text,
    tribe_id         bigint,
    notes            text,
    created_at       timestamp(6) NOT NULL,
    updated_at       timestamp(6) NOT NULL,
    gender_id        bigint
);

CREATE INDEX index_people_on_glo_last_name   ON people (glo_last_name);
CREATE INDEX index_people_on_glo_first_name  ON people (glo_first_name);
CREATE INDEX index_people_on_glo_middle_name ON people (glo_middle_name);
CREATE INDEX index_people_on_tribe_id        ON people (tribe_id);
CREATE INDEX index_people_on_gender_id       ON people (gender_id);

-- Trigram indexes for the % operator in patent_name_fuzzy_clauses(). The btree
-- indexes above CANNOT serve a trigram similarity predicate; without these, a name
-- search sequentially scans all 316k people. Measured 2026-06-16: the 1-token
-- common-surname worst case ("roberts") dropped from ~564ms to ~379ms warm. The
-- people table is a static IATH snapshot, so index maintenance cost is negligible.
CREATE INDEX index_people_on_glo_first_name_trgm ON people USING gin (glo_first_name gin_trgm_ops);
CREATE INDEX index_people_on_glo_last_name_trgm  ON people USING gin (glo_last_name  gin_trgm_ops);

CREATE TABLE patent_persons (
    id                       bigint PRIMARY KEY,
    patent_id                bigint NOT NULL REFERENCES rails_patents(id),
    person_id                bigint NOT NULL REFERENCES people(id),
    patent_role_id           bigint NOT NULL REFERENCES patent_roles(id),
    patentee_sequence_number integer,
    public_notes             text,
    project_notes            text,
    created_at               timestamp(6) NOT NULL,
    updated_at               timestamp(6) NOT NULL
);

CREATE INDEX index_patent_persons_on_patent_id                ON patent_persons (patent_id);
CREATE INDEX index_patent_persons_on_person_id                ON patent_persons (person_id);
CREATE INDEX index_patent_persons_on_patent_role_id           ON patent_persons (patent_role_id);
CREATE INDEX index_patent_persons_on_patentee_sequence_number ON patent_persons (patentee_sequence_number);

\copy patent_roles   FROM '/Users/cwm6W/Desktop/iath_export/patent_roles.csv'   CSV HEADER
\copy people         FROM '/Users/cwm6W/Desktop/iath_export/people.csv'         CSV HEADER
\copy patent_persons FROM '/Users/cwm6W/Desktop/iath_export/patent_persons.csv' CSV HEADER

ANALYZE patent_roles;
ANALYZE people;
ANALYZE patent_persons;

COMMIT;
