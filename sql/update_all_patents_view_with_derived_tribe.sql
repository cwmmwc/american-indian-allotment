-- Update all_patents view to layer derived_tribe_labels on top of the
-- existing preferred_name resolution. Precedence (highest wins):
--
--   1. derived_tribe_labels.derived_preferred_name
--        Per-accession overrides applied by mechanisms like the sibling
--        backfill (sibling_backfill_v1, 2026-05-29 — 638 FRN records
--        resolved via same-allotment same-state sibling evidence).
--
--   2. document_class_metadata.default_tribe_label
--        Doc-class-level overrides (e.g. SS docClass → "Dacotah/Sioux
--        Nation" for the 3,025 Sioux Scrip Patents), applied only when
--        the otherwise-computed preferred_name is FRN.
--
--   3. bap.preferred_name (BLM-matched arm) or
--      COALESCE(tnm.preferred_name, rp.glo_tribe_name) (rails-only arm)
--        The IATH crosswalk's tribe assignment as stored.
--
-- Original data sources (bap.preferred_name, rp.glo_tribe_name,
-- tribe_crosswalk) are never modified — overrides are purely additive
-- layers and are reversible by deleting the corresponding override row.

CREATE OR REPLACE VIEW all_patents AS
 SELECT rp.id,
    bap.objectid,
    bap.accession_number,
    COALESCE(bap.full_name, rp.full_name) AS full_name,
    COALESCE(
      dtl.derived_preferred_name,
      CASE WHEN bap.preferred_name ILIKE 'Frn%' THEN dcm.default_tribe_label END,
      bap.preferred_name
    ) AS preferred_name,
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
     LEFT JOIN document_class_metadata dcm ON dcm.doc_code = rp.document_code
     LEFT JOIN derived_tribe_labels   dtl ON dtl.accession_number = rp.accession_number
UNION ALL
 SELECT rp.id,
    NULL::integer AS objectid,
    rp.accession_number,
    rp.full_name,
    COALESCE(
      dtl.derived_preferred_name,
      CASE WHEN COALESCE(tnm.preferred_name, rp.glo_tribe_name) ILIKE 'Frn%'
           THEN dcm.default_tribe_label END,
      COALESCE(tnm.preferred_name, rp.glo_tribe_name)
    ) AS preferred_name,
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
     LEFT JOIN document_class_metadata dcm ON dcm.doc_code = rp.document_code
     LEFT JOIN derived_tribe_labels   dtl ON dtl.accession_number = rp.accession_number
  WHERE bap.accession_number IS NULL;
