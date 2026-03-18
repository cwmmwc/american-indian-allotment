-- Tribe identification fixes applied 2026-03-17
-- Validated all 89 BIA agency codes against the legacy PHP site at
-- land-sales.iath.virginia.edu/federal_register-search.php
-- The legacy site's tribe-to-agency-code mappings are the authoritative source.
--
-- 36 mismatches found and corrected (including J50500 fixed earlier).
-- Pattern: the original import assigned tribe names by position in the
-- Federal Register PDF rather than by BIA agency code lookup, causing
-- neighboring tribes to get the wrong label.

-- A codes (Dakota/Nebraska)
UPDATE federal_register_claims SET tribe_identified = 'Santee Sioux' WHERE bia_agency_code = 'A00007';  -- was: Flandreau Santee Sioux (49 rows)
UPDATE federal_register_claims SET tribe_identified = 'Sisseton-Wahpeton' WHERE bia_agency_code = 'A09347';  -- was: Rosebud Sioux (93 rows)
UPDATE federal_register_claims SET tribe_identified = 'Turtle Mountain Chippewa' WHERE bia_agency_code = 'A11304';  -- was: Yankton Sioux (81 rows)

-- B codes (Oklahoma/Kansas/Montana)
UPDATE federal_register_claims SET tribe_identified = 'Potawatomi (Kansas)' WHERE bia_agency_code = 'B04862';  -- was: Crow (49 rows)
UPDATE federal_register_claims SET tribe_identified = 'Sac and Fox (Kansas/Nebraska)' WHERE bia_agency_code = 'B04864';  -- was: Crow (1 row)
UPDATE federal_register_claims SET tribe_identified = 'Kiowa, Comanche, Apache' WHERE bia_agency_code = 'B06806';  -- was: Blackfeet (15 rows)
UPDATE federal_register_claims SET tribe_identified = 'Otoe-Missouria' WHERE bia_agency_code = 'B07811';  -- was: Fort Belknap (4 rows)
UPDATE federal_register_claims SET tribe_identified = 'Absentee Shawnee' WHERE bia_agency_code = 'B08820';  -- was: Fort Peck (1 row)
UPDATE federal_register_claims SET tribe_identified = 'Iowa (Oklahoma)' WHERE bia_agency_code = 'B08822';  -- was: Fort Peck (1 row)
UPDATE federal_register_claims SET tribe_identified = 'Sac and Fox (Oklahoma)' WHERE bia_agency_code = 'B08824';  -- was: Fort Peck (1 row)

-- C codes (Montana/Dakota)
UPDATE federal_register_claims SET tribe_identified = 'Fort Belknap (Gros Ventre-Assiniboine)' WHERE bia_agency_code = 'C55204';  -- was: Sisseton-Wahpeton (7 rows)
UPDATE federal_register_claims SET tribe_identified = 'Turtle Mountain Chippewa' WHERE bia_agency_code = 'C55224';  -- was: Devil's Lake / Spirit Lake (97 rows)
UPDATE federal_register_claims SET tribe_identified = 'Fort Peck (Assiniboine-Sioux)' WHERE bia_agency_code = 'C56206';  -- was: Flathead (459 rows)
UPDATE federal_register_claims SET tribe_identified = 'Turtle Mountain Chippewa' WHERE bia_agency_code = 'C56226';  -- was: Blackfeet (405 rows)

-- F codes (Wisconsin/Michigan)
UPDATE federal_register_claims SET tribe_identified = 'Bad River Chippewa' WHERE bia_agency_code = 'F55430';  -- was: Lac du Flambeau (1 row)
UPDATE federal_register_claims SET tribe_identified = 'Red Cliff Chippewa' WHERE bia_agency_code = 'F55435';  -- was: Menominee (2 rows)
UPDATE federal_register_claims SET tribe_identified = 'Wisconsin Winnebago' WHERE bia_agency_code = 'F55439';  -- was: Menominee (2 rows)
UPDATE federal_register_claims SET tribe_identified = 'Sault Ste. Marie' WHERE bia_agency_code = 'F60469';  -- was: Saginaw Chippewa (4 rows)
UPDATE federal_register_claims SET tribe_identified = 'Keweenaw Bay' WHERE bia_agency_code = 'F60473';  -- was: Saginaw Chippewa (1 row)

-- G codes (Oklahoma)
UPDATE federal_register_claims SET tribe_identified = 'Chickasaw' WHERE bia_agency_code = 'G03906';  -- was: Citizen Potawatomi (OK) (11 rows)
UPDATE federal_register_claims SET tribe_identified = 'Seneca-Shawnee' WHERE bia_agency_code = 'G04923';  -- was: Pawnee (2 rows)
UPDATE federal_register_claims SET tribe_identified = 'Osage' WHERE bia_agency_code = 'G06930';  -- was: Unidentified (1 row)
UPDATE federal_register_claims SET tribe_identified = 'Creek' WHERE bia_agency_code = 'G07908';  -- was: Cheyenne-Arapaho (5 rows)
UPDATE federal_register_claims SET tribe_identified = 'Creek' WHERE bia_agency_code = 'G08905';  -- was: Kiowa (11 rows)
UPDATE federal_register_claims SET tribe_identified = 'Cherokee' WHERE bia_agency_code = 'G09907';  -- was: Osage (20 rows)

-- J codes (California/Pacific Northwest)
UPDATE federal_register_claims SET tribe_identified = 'California Indians' WHERE bia_agency_code = 'J50500';  -- was: Umatilla (196 rows)
UPDATE federal_register_claims SET tribe_identified = 'Hoopa Extension' WHERE bia_agency_code = 'J52562';  -- was: Coeur d'Alene (64 rows)
UPDATE federal_register_claims SET tribe_identified = 'Capitan Grande' WHERE bia_agency_code = 'J54571';  -- was: Nez Perce (1 row)

-- P codes (Pacific Northwest/Oregon/Washington)
UPDATE federal_register_claims SET tribe_identified = 'Celilo Village' WHERE bia_agency_code = 'P00148';  -- was: Potawatomi (8 rows)
UPDATE federal_register_claims SET tribe_identified = 'Lower Elwha' WHERE bia_agency_code = 'P06125';  -- was: Unidentified (1 row)
UPDATE federal_register_claims SET tribe_identified = 'Public Domain (WA)' WHERE bia_agency_code = 'P06130';  -- was: Unidentified (4 rows)
UPDATE federal_register_claims SET tribe_identified = 'Lummi' WHERE bia_agency_code = 'P10107';  -- was: Unidentified (1 row)
UPDATE federal_register_claims SET tribe_identified = 'Nisqually' WHERE bia_agency_code = 'P10110';  -- was: Unidentified (2 rows)
UPDATE federal_register_claims SET tribe_identified = 'Port Gamble' WHERE bia_agency_code = 'P10113';  -- was: Unidentified (1 row)
UPDATE federal_register_claims SET tribe_identified = 'Port Madison' WHERE bia_agency_code = 'P10114';  -- was: Unidentified (2 rows)
UPDATE federal_register_claims SET tribe_identified = 'Swinomish' WHERE bia_agency_code = 'P10122';  -- was: Unidentified (1 row)
UPDATE federal_register_claims SET tribe_identified = 'Spokane' WHERE bia_agency_code = 'P12102';  -- was: Mission Indians (CA) (42 rows)

-- Additional fixes (2026-03-18)
-- Portland Area Statute Claims from western Oregon. Legacy site has no tribe name for either code.
-- Allottee names include Chetco, Alsea, and other Oregon coast tribal names (likely Confederated Tribes of Siletz).
UPDATE federal_register_claims SET tribe_identified = 'Portland Area (unidentified)' WHERE bia_agency_code = 'P00141';  -- was: Potawatomi (1 row)
UPDATE federal_register_claims SET tribe_identified = 'Portland Area (unidentified)' WHERE bia_agency_code = 'P01142';  -- was: Potawatomi (127 rows)
