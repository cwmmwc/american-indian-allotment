-- Update all_patents view: un-mappable branch now uses
-- COALESCE(rp.authority, rp.document_class) AS authority so vision into
-- rails_patents.authority for re-scraped records (e.g. the SD2610 batch
-- as of 2026-05-26), with fallback to document_class for the ~45,000
-- un-mappable records we haven't re-scraped yet.
--
-- Includes a one-time OWNER transfer (Cloud SQL only): the view was
-- originally created by `postgres` so `appuser` couldn't CREATE OR REPLACE
-- it through the regular proxy. After this OWNER change, future view
-- updates work through the standard appuser proxy connection — no more
-- postgres-superuser escalation needed for view changes.
--
-- Run in Cloud SQL Studio (browser UI uses your GCP identity, bypasses
-- Cloud SQL password prompt):
--   https://console.cloud.google.com/sql/instances/allotment-db/studio?project=lunar-mercury-397321
-- Or locally:
--   psql -d allotment_research -f sql/update_all_patents_view_with_authority.sql

ALTER VIEW all_patents OWNER TO appuser;

CREATE OR REPLACE VIEW all_patents AS
 SELECT rp.id,
    bap.objectid,
    bap.accession_number,
    COALESCE(bap.full_name, rp.full_name) AS full_name,
    bap.preferred_name,
    rp.state,
    rp.document_class,
    rp.indian_allotment_number,
    bap.authority,
    rp.signature_date,
    bap.forced_fee,
    bap.cancelled_doc,
    rp.total_acres,
    rp.remarks,
    rp.document_code,
    bap.county,
    bap.meridian,
    bap.township_number,
    bap.township_direction,
    bap.range_number,
    bap.range_direction,
    bap.section_number,
    bap.aliquot_parts,
    bap.centroid_lat,
    bap.centroid_lon,
    true AS has_plss_geometry
   FROM rails_patents rp
     JOIN blm_allotment_patents bap ON rp.accession_number = bap.accession_number
UNION ALL
 SELECT rp.id,
    NULL::integer AS objectid,
    rp.accession_number,
    rp.full_name,
    COALESCE(tnm.preferred_name, rp.glo_tribe_name) AS preferred_name,
    rp.state,
    rp.document_class,
    rp.indian_allotment_number,
    COALESCE(rp.authority, rp.document_class) AS authority,
    rp.signature_date,
    'False'::text AS forced_fee,
    rp.cancelled_doc::text AS cancelled_doc,
    rp.total_acres,
    rp.remarks,
    rp.document_code,
    NULL::text AS county,
    NULL::text AS meridian,
    NULL::text AS township_number,
    NULL::text AS township_direction,
    NULL::text AS range_number,
    NULL::text AS range_direction,
    NULL::text AS section_number,
    NULL::text AS aliquot_parts,
    NULL::double precision AS centroid_lat,
    NULL::double precision AS centroid_lon,
    false AS has_plss_geometry
   FROM rails_patents rp
     LEFT JOIN blm_allotment_patents bap ON rp.accession_number = bap.accession_number
     LEFT JOIN tribe_name_map tnm ON rp.glo_tribe_name = tnm.glo_tribe_name
  WHERE bap.accession_number IS NULL;
