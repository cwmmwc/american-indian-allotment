-- Build the Wilson state-level WORKING tables in public, from the iath raw layer.
-- These reconcile cleanly (no taxonomy / no gaps), so this is a typed copy with
-- clearer column names plus an is_national_total flag for the source "All" row.
-- Layering: reads iath (raw source), writes public (app working tables). Idempotent.

-- Table VII — original tribal acreage and the deductions from it, by state (the loss arc)
DROP TABLE IF EXISTS public.wilson_land_loss_by_state;
CREATE TABLE public.wilson_land_loss_by_state AS
SELECT
    united_state                                AS state,
    (united_state = 'All')                      AS is_national_total,
    gross_original_acres                        AS original_acres,
    gross_added                                 AS added_acres,
    gross_total                                 AS gross_acres,
    deduct_acres_ceded                          AS ceded_acres,
    deduct_acres_surplus                        AS surplus_acres,
    deduct_miscellaneous                        AS miscellaneous_acres,
    deduct_total                                AS deductions_total,
    allotments_number                           AS allotments_number,
    allotments_acreage                          AS allotments_acres,
    allotments_alienated                        AS allotments_alienated_acres,
    'Wilson Report Table VII (iath.wilson_t07)' AS source
FROM iath.wilson_t07;

-- Table V — 1934 reservation acreage by ownership (and character), by state (the snapshot)
DROP TABLE IF EXISTS public.wilson_ownership_1934_by_state;
CREATE TABLE public.wilson_ownership_1934_by_state AS
SELECT
    united_state                                AS state,
    (united_state = 'All')                      AS is_national_total,
    living_allots_total_acres                   AS living_allottee_acres,
    deceased_allots_total_acres                 AS deceased_allottee_acres,
    tribal_total_acres                          AS tribal_acres,
    gov_total_acres                             AS government_acres,
    total_all_types                             AS total_acres,
    'Wilson Report Table V (iath.wilson_t05)'   AS source
FROM iath.wilson_t05;
