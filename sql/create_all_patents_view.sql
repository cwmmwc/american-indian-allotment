-- all_patents: unified view of 285,870 allotment patents
-- Joins rails_patents (full catalog) with blm_allotment_patents (239,845 with PLSS geometry)
-- Uses tribe_name_map to normalize glo_tribe_name → preferred_name for non-BLM patents

CREATE OR REPLACE VIEW all_patents AS

-- Patents that exist in both rails_patents and blm_allotment_patents (239,845 mappable)
SELECT
    rp.id,
    bap.objectid,
    bap.accession_number,
    bap.full_name,
    bap.preferred_name,
    rp.state,
    rp.document_class,
    rp.indian_allotment_number,
    bap.authority,
    rp.signature_date,
    bap.forced_fee,
    bap.cancelled_doc::text,
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
    TRUE as has_plss_geometry
FROM rails_patents rp
JOIN blm_allotment_patents bap ON rp.accession_number = bap.accession_number

UNION ALL

-- Patents only in rails_patents (46,025 non-mappable)
SELECT
    rp.id,
    NULL::integer as objectid,
    rp.accession_number,
    NULL::text as full_name,
    COALESCE(tnm.preferred_name, rp.glo_tribe_name) as preferred_name,
    rp.state,
    rp.document_class,
    rp.indian_allotment_number,
    rp.document_class as authority,
    rp.signature_date,
    'False'::text as forced_fee,
    rp.cancelled_doc::text,
    rp.total_acres,
    rp.remarks,
    rp.document_code,
    NULL::text as county,
    NULL::text as meridian,
    NULL::text as township_number,
    NULL::text as township_direction,
    NULL::text as range_number,
    NULL::text as range_direction,
    NULL::text as section_number,
    NULL::text as aliquot_parts,
    NULL::double precision as centroid_lat,
    NULL::double precision as centroid_lon,
    FALSE as has_plss_geometry
FROM rails_patents rp
LEFT JOIN blm_allotment_patents bap ON rp.accession_number = bap.accession_number
LEFT JOIN tribe_name_map tnm ON rp.glo_tribe_name = tnm.glo_tribe_name
WHERE bap.accession_number IS NULL;
