-- Per-record historian-arbitrated resolutions of BLM "Frn …" tribe
-- placeholders. The Scholars' Lab tribal_land_patents_aliquot layer
-- assigns a "Frn …" preferred_name to patents whose tribe was unresolved
-- at publication time (~12,200 rows total across 15 distinct strings).
-- When Christian's research definitively identifies an individual
-- record's tribe, the resolution lands here as one UPDATE keyed on
-- accession_number.
--
-- This is a LOCAL override. The upstream ArcGIS layer is currently
-- configured capabilities=Query,Extract (read-only) and hasStaticData=True
-- so the canonical fix is to send Drew a periodic list of these
-- resolutions. The local override keeps the federal-register-app in
-- sync until that happens.
--
-- Idempotent — every UPDATE filters on both accession_number AND the
-- expected old preferred_name, so re-running on already-resolved rows
-- is a no-op.
--
-- Run with:  psql -d allotment_research -f sql/blm_frn_resolutions.sql
--            (or against Cloud SQL via the proxy)

BEGIN;

-- James Senoya, allotment 518 (accession 722323, objectid 145688) —
-- historian-confirmed Comanche per Christian's research, 2026-06-04.
UPDATE blm_allotment_patents
SET preferred_name = 'Comanche'
WHERE accession_number = '722323'
  AND preferred_name = 'Frn COMANCHE AND APACHE';

-- Sanity check: expect zero remaining `Frn …` rows for accessions
-- listed above. Returns rows only if the UPDATE above failed (e.g.,
-- the row's current state was unexpected).
SELECT accession_number, preferred_name
FROM blm_allotment_patents
WHERE accession_number IN ('722323')
  AND preferred_name ILIKE 'frn%';

COMMIT;
