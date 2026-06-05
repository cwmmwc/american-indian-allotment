-- Path B / Option 1: extend all_patents view with cadnsdi_recovered_patents.
--
-- WHAT THIS DOES
--   Arm 2 (rails-only patents) LEFT JOINs cadnsdi_recovered_patents and
--   surfaces the recovered centroid, township/range/section, and county
--   when a recovered entry exists for that accession. Also introduces a
--   new column `is_mappable` (true in arm 1 always; true in arm 2 only
--   when a recovered entry exists).
--
-- WHAT IT DOES NOT CHANGE
--   `has_plss_geometry` retains its existing meaning: true iff the patent
--   has a row in blm_allotment_patents. Existing queries that filter on
--   has_plss_geometry — including patent_detail's `src=rails` branch
--   (`WHERE id = X AND has_plss_geometry = false`) — keep working.
--
--   All existing columns retain their names and types. Only one column
--   added (`is_mappable`) and it is added at the end.
--
-- DEPLOY ORDER (Cloud SQL): cadnsdi_recovered_patents table must exist
-- before this DDL runs. Recovered patents themselves can be loaded later.

CREATE OR REPLACE VIEW all_patents AS
SELECT rp.id,
       bap.objectid,
       bap.accession_number,
       COALESCE(bap.full_name, rp.full_name) AS full_name,
       COALESCE(dtl.derived_preferred_name,
           CASE
               WHEN bap.preferred_name ILIKE 'Frn%' THEN dcm.default_tribe_label
               ELSE NULL::text
           END, bap.preferred_name) AS preferred_name,
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
       true AS has_plss_geometry,
       true AS is_mappable
  FROM rails_patents rp
       JOIN blm_allotment_patents bap ON rp.accession_number = bap.accession_number
       LEFT JOIN document_class_metadata dcm ON dcm.doc_code = rp.document_code
       LEFT JOIN derived_tribe_labels dtl ON dtl.accession_number = rp.accession_number
UNION ALL
SELECT rp.id,
       NULL::integer AS objectid,
       rp.accession_number,
       rp.full_name,
       COALESCE(dtl.derived_preferred_name,
           CASE
               WHEN COALESCE(tnm.preferred_name, rp.glo_tribe_name) ILIKE 'Frn%' THEN dcm.default_tribe_label
               ELSE NULL::text
           END, COALESCE(tnm.preferred_name, rp.glo_tribe_name)) AS preferred_name,
       rp.state,
       rp.document_class,
       rp.indian_allotment_number,
       COALESCE(rec.authority, rp.authority, rp.document_class) AS authority,
       rp.signature_date,
       'False'::text AS forced_fee,
       rp.cancelled_doc::text AS cancelled_doc,
       rp.total_acres,
       rp.remarks,
       rp.document_code,
       rec.county,
       NULL::text AS meridian,
       rec.township_number,
       rec.township_direction,
       rec.range_number,
       rec.range_direction,
       rec.section_number,
       rec.aliquot_parts,
       rec.centroid_lat::double precision AS centroid_lat,
       rec.centroid_lon::double precision AS centroid_lon,
       false AS has_plss_geometry,
       (rec.accession_number IS NOT NULL) AS is_mappable
  FROM rails_patents rp
       LEFT JOIN blm_allotment_patents bap ON rp.accession_number = bap.accession_number
       LEFT JOIN tribe_name_map tnm ON rp.glo_tribe_name = tnm.glo_tribe_name
       LEFT JOIN document_class_metadata dcm ON dcm.doc_code = rp.document_code
       LEFT JOIN derived_tribe_labels dtl ON dtl.accession_number = rp.accession_number
       LEFT JOIN cadnsdi_recovered_patents rec ON rec.accession_number = rp.accession_number
 WHERE bap.accession_number IS NULL;
