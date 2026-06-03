-- Normalize capital "And" -> lowercase "and" in three places that hold the
-- canonical BLM tribe name (all three feed the `all_patents` view):
--   - blm_allotment_patents.preferred_name      (mirror of the ArcGIS layer)
--   - tribe_name_map.preferred_name             (lookup for non-mappable rails-only patents)
--   - derived_tribe_labels.derived_preferred_name (sibling-backfill overrides for FRN cases;
--                                                   takes precedence over bap.preferred_name)
--
-- The upstream ArcGIS feature service (tribal_land_patents_aliquot_20240304
-- on UVA Library's ArcGIS Online account) capitalizes the connector "And"
-- in 8 tribe-name strings; the IATH Tribes crosswalk vocabulary canonically
-- lowercases small words. This local override aligns both BLM-side stores
-- with the crosswalk so the Circular 2464 testimony JOINs and the existing
-- patents-page tribe dropdowns (which read from the `all_patents` view, a
-- UNION across both stores) display the canonical casing.
--
-- This is a LOCAL override. The upstream ArcGIS layer is configured
-- capabilities=Query,Extract (read-only) and hasStaticData=True, so it's
-- not drifting under us. A separate request to the Scholars' Lab specialist
-- will eventually apply the same change upstream. Until then:
--   - import_blm_patents.py uses ON CONFLICT DO NOTHING, so a routine
--     re-run will NOT overwrite this override.
--   - import_blm_patents.py --drop WOULD wipe this override (it truncates
--     before re-pulling from ArcGIS). If you need to --drop, re-run this
--     file afterward to reapply.
--
-- Idempotent: re-running shows 0 rows updated for each statement after the
-- first successful run.
--
-- Run with:  psql -d allotment_research -f sql/normalize_blm_preferred_name_and.sql

BEGIN;

UPDATE blm_allotment_patents SET preferred_name = 'Otoe and Missouria'
    WHERE preferred_name = 'Otoe And Missouria';
UPDATE blm_allotment_patents SET preferred_name = 'Assiniboine and Gros Ventre'
    WHERE preferred_name = 'Assiniboine And Gros Ventre';
UPDATE blm_allotment_patents SET preferred_name = 'Assiniboine and Sioux'
    WHERE preferred_name = 'Assiniboine And Sioux';
UPDATE blm_allotment_patents SET preferred_name = 'Caddo and Wichita'
    WHERE preferred_name = 'Caddo And Wichita';
UPDATE blm_allotment_patents SET preferred_name = 'Pima and Maricopa'
    WHERE preferred_name = 'Pima And Maricopa';
UPDATE blm_allotment_patents SET preferred_name = 'Sac and Fox'
    WHERE preferred_name = 'Sac And Fox';
UPDATE blm_allotment_patents SET preferred_name = 'Shoshone and Arapaho'
    WHERE preferred_name = 'Shoshone And Arapaho';
UPDATE blm_allotment_patents SET preferred_name = 'Shoshone and Bannock'
    WHERE preferred_name = 'Shoshone And Bannock';

-- Same 8 transformations against tribe_name_map (which feeds rails-only
-- patents into the all_patents view).
UPDATE tribe_name_map SET preferred_name = 'Otoe and Missouria'
    WHERE preferred_name = 'Otoe And Missouria';
UPDATE tribe_name_map SET preferred_name = 'Assiniboine and Gros Ventre'
    WHERE preferred_name = 'Assiniboine And Gros Ventre';
UPDATE tribe_name_map SET preferred_name = 'Assiniboine and Sioux'
    WHERE preferred_name = 'Assiniboine And Sioux';
UPDATE tribe_name_map SET preferred_name = 'Caddo and Wichita'
    WHERE preferred_name = 'Caddo And Wichita';
UPDATE tribe_name_map SET preferred_name = 'Pima and Maricopa'
    WHERE preferred_name = 'Pima And Maricopa';
UPDATE tribe_name_map SET preferred_name = 'Sac and Fox'
    WHERE preferred_name = 'Sac And Fox';
UPDATE tribe_name_map SET preferred_name = 'Shoshone and Arapaho'
    WHERE preferred_name = 'Shoshone And Arapaho';
UPDATE tribe_name_map SET preferred_name = 'Shoshone and Bannock'
    WHERE preferred_name = 'Shoshone And Bannock';

-- Same 8 transformations against derived_tribe_labels (which the
-- all_patents view COALESCEs in front of bap.preferred_name). Only 1 row
-- currently affected (sibling backfill of FRN accession 541632) but
-- written as 8 statements for symmetry and to catch any future siblings.
UPDATE derived_tribe_labels SET derived_preferred_name = 'Otoe and Missouria'
    WHERE derived_preferred_name = 'Otoe And Missouria';
UPDATE derived_tribe_labels SET derived_preferred_name = 'Assiniboine and Gros Ventre'
    WHERE derived_preferred_name = 'Assiniboine And Gros Ventre';
UPDATE derived_tribe_labels SET derived_preferred_name = 'Assiniboine and Sioux'
    WHERE derived_preferred_name = 'Assiniboine And Sioux';
UPDATE derived_tribe_labels SET derived_preferred_name = 'Caddo and Wichita'
    WHERE derived_preferred_name = 'Caddo And Wichita';
UPDATE derived_tribe_labels SET derived_preferred_name = 'Pima and Maricopa'
    WHERE derived_preferred_name = 'Pima And Maricopa';
UPDATE derived_tribe_labels SET derived_preferred_name = 'Sac and Fox'
    WHERE derived_preferred_name = 'Sac And Fox';
UPDATE derived_tribe_labels SET derived_preferred_name = 'Shoshone and Arapaho'
    WHERE derived_preferred_name = 'Shoshone And Arapaho';
UPDATE derived_tribe_labels SET derived_preferred_name = 'Shoshone and Bannock'
    WHERE derived_preferred_name = 'Shoshone And Bannock';

-- Sanity check across all three tables and the all_patents view. Expect 0 rows.
SELECT 'blm_allotment_patents' AS source, preferred_name, count(*) AS rows
FROM blm_allotment_patents WHERE preferred_name ~ '\m(And)\M' GROUP BY preferred_name
UNION ALL
SELECT 'tribe_name_map', preferred_name, count(*)
FROM tribe_name_map WHERE preferred_name ~ '\m(And)\M' GROUP BY preferred_name
UNION ALL
SELECT 'derived_tribe_labels', derived_preferred_name, count(*)
FROM derived_tribe_labels WHERE derived_preferred_name ~ '\m(And)\M' GROUP BY derived_preferred_name
UNION ALL
SELECT 'all_patents (view)', preferred_name, count(*)
FROM all_patents WHERE preferred_name ~ '\m(And)\M' GROUP BY preferred_name
ORDER BY 1, 2;

COMMIT;
