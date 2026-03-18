# Database: `allotment_research`

## Overview

PostgreSQL database containing forced fee patent claims from the 1983 Federal Register, BLM patent records, trust-to-fee linkages, PLSS land descriptions, and a full ArcGIS patent mirror. Built to support research on Indian allotment land dispossession.

**Total: 10 tables, 9 views, ~1,250,000 rows.**

## Data Sources

### 1. Federal Register Notices (1983)

The Bureau of Indian Affairs published two Federal Register notices listing Indian allotment claims:
- **March 31, 1983** (48 FR 13698)
- **November 7, 1983** (48 FR 51204)

These listed allotments where fee patents were issued without the allottee's consent ("forced fee patents") and secretarial transfers. The data was originally digitized and managed through a Rails admin application at the Institute for Advanced Technology in the Humanities (IATH), University of Virginia.

**Tables built from this source:**
- `federal_register_claims` — 10,976 claims parsed from the Federal Register notices
- `forced_fee_patents_rails` — 17,560 rows of denormalized patent-to-claim linkages, exported from the Rails admin interface as CSV

### 2. BLM General Land Office Records

Patent records downloaded from the Bureau of Land Management's General Land Office (GLO) database at [glorecords.blm.gov](https://glorecords.blm.gov/). These represent the universe of Indian allotment patents.

**Tables built from this source:**
- `fee_patents` — 88,537 fee patent records
- `trust_patents` — 95,353 trust patent records
- `indian_allotment_general` — 75,743 general allotment records
- `parcels_patents_by_tribe` — 401,811 PLSS legal land descriptions

### 3. Derived/Computed

- `trust_fee_linkages` — 29,229 records linking trust patents to their corresponding fee patents (matched by allotment number, tribe, and other fields)
- `tribes` — 908 tribe name lookup entries

## Table Schemas

### `federal_register_claims` (10,976 rows)

Primary claims from the 1983 Federal Register notices. Contains 9,649 forced fee patent claims and 1,327 secretarial transfers.

| Column | Type | Description |
|--------|------|-------------|
| id | integer PK | Auto-increment |
| bia_agency_code | text | BIA agency identifier |
| tribe_identified | text | Tribe name (corrected 2026-03-17; see `sql/tribe_identification_fixes.sql`) |
| case_number | text | BIA case number (may have leading zeros) |
| allottee_name | text | Name of the allottee |
| allotment_number | text | Allotment number |
| claim_type | text | All 30 variants start with "FORCED FEE PATENT" |
| document_source | text | Federal Register citation |
| publication_date | text | Date of Federal Register publication |

**80 tribes** represented (after 2026-03-17 corrections). Largest: Blackfeet (860), Flathead (859), Rosebud Sioux (766), Cheyenne River Sioux (763), Crow (619).

**Data quality note (2026-03-17/18):** The original import assigned `tribe_identified` by sequential position in the Federal Register PDF rather than by BIA agency code lookup. This caused 38 agency codes (1,818 records, 16.6% of total) to be labeled with the wrong tribe — typically the tribe that appeared nearby in the document. Corrected by validating all 89 codes against the authoritative mapping at `land-sales.iath.virginia.edu/federal_register-search.php`. See `sql/tribe_identification_fixes.sql` for the full list of corrections.

### `forced_fee_patents_rails` (17,560 rows)

Denormalized patent-to-claim linkages from the Rails admin application. Each row links a Federal Register claim to its corresponding BLM patent record(s). Exported as CSV from the Rails admin interface.

| Column | Type | Description |
|--------|------|-------------|
| id | integer PK | |
| patent_state | text | State |
| tribe_name | text | Tribe (Rails naming) |
| fedreg_allottee | text | Allottee name from Federal Register |
| glo_patentees | text | Patentee name(s) from GLO |
| fedreg_allotment | text | Allotment number from Federal Register |
| patents_indian_allotment_number | text | Allotment number from GLO |
| patents_signature_date | date | Patent signature date |
| type_of_claim | text | Claim type |
| patents_authority_name | text | Patent authority |
| patents_document_class | text | Document class |
| patents_accession_number | text | GLO accession number |
| case_number | text | BIA case number |
| patents_cancelled_doc | text | Cancellation status |
| fedreg_document | text | Federal Register reference |
| patents_remarks | text | GLO remarks |
| patents_glo_tribe | text | GLO tribe name |
| fedreg_toc_tribe_name | text | Table of contents tribe name |

### `fee_patents` (88,537 rows)

All BLM fee patent records for Indian allotments.

| Column | Type | Description |
|--------|------|-------------|
| id | integer PK | |
| accession_number | text UNIQUE | GLO accession number |
| document_class | text | e.g., "Serial Land Patent" |
| document_code | text | e.g., "SER" |
| state | text | Two-letter state code |
| blm_serial_number | text | BLM serial number |
| document_number | text | Document number |
| indian_allotment_number | text | Allotment number |
| tribe_raw | text | Tribe name as recorded in GLO |
| tribe_normalized | text | Standardized tribe name |
| land_office | text | Issuing land office |
| signature_date | text | Date signed (YYYY-MM-DD format) |
| acres | real | Acreage |
| remarks | text | GLO remarks (may reference other patents) |
| cancelled | integer | 0 = active, 1 = cancelled |
| glo_url | text | Direct link to GLO record |

### `trust_patents` (95,353 rows)

All BLM trust patent records for Indian allotments.

Same schema as `fee_patents` plus:

| Column | Type | Description |
|--------|------|-------------|
| subsurface_reserved | integer | Whether subsurface rights reserved |
| has_fee_patent_ref | integer | 1 if remarks reference a fee patent |
| fee_patent_accessions | text | JSON array of fee patent accession numbers found in remarks |

### `trust_fee_linkages` (29,229 rows)

Computed links between trust patents and their corresponding fee patents.

| Column | Type | Description |
|--------|------|-------------|
| id | integer PK | |
| trust_accession | text | Trust patent accession number |
| fee_accession | text | Fee patent accession number |
| trust_date | text | Trust patent date |
| fee_date | text | Fee patent date |
| trust_acres | real | Trust patent acreage |
| fee_acres | real | Fee patent acreage |
| years_to_conversion | real | Years between trust and fee issuance |
| tribe_normalized | text | Tribe |
| state | text | State |
| allotment_number | text | Allotment number |
| trust_glo_url | text | Link to trust patent GLO record |
| fee_glo_url | text | Link to fee patent GLO record |

### `parcels_patents_by_tribe` (401,811 rows)

PLSS legal land descriptions for patents, keyed by tribe and allotment number.

| Column | Type | Description |
|--------|------|-------------|
| glo_tribe_id | text | GLO tribe identifier |
| indian_allotment_number | text | Allotment number |
| signature_date | text | Patent date |
| authority | text | Patent authority |
| state | text | State |
| township_number | text | PLSS township |
| range_number | text | PLSS range |
| section_number | text | PLSS section |
| aliquot_parts | text | Subdivision (e.g., "NW¼ SE¼") |
| county | text | County |
| meridian / meridian_code | text | PLSS meridian |
| block_number, fractional_section, survey_number | text | Additional PLSS fields |

### `indian_allotment_general` (75,743 rows)

General allotment records (broader category than fee/trust).

| Column | Type | Description |
|--------|------|-------------|
| id | integer PK | |
| accession_number | text UNIQUE | GLO accession number |
| document_code | text | |
| state | text | |
| tribe_raw / tribe_normalized | text | Tribe names |
| date | text | Patent date |
| acres | real | |
| names | text | Patentee name(s) |
| fedreg_tribe | text | Federal Register tribe ID |
| glo_url | text | Link to GLO record |

### `tribes` (908 rows)

Tribe name lookup table.

| Column | Type | Description |
|--------|------|-------------|
| id | integer PK | |
| normalized_name | text | Standardized tribe name |
| state | text | Primary state |
| notes | text | |

### `rails_patents` (285,870 rows)

Full patent catalog exported from the Rails admin application (land-sales.iath.virginia.edu/db/admin/patents). Covers all 285,870 allotment patents. Of these, 239,845 also appear in `blm_allotment_patents` (matched by accession_number) and have PLSS geometry; the remaining 46,025 are searchable but not mappable.

**Source CSV:** `patents-2026-03-18.csv` exported from the Rails admin.

| Column | Type | Description |
|--------|------|-------------|
| id | integer PK | Rails record ID |
| accession_number | text | GLO accession number (various formats: numeric, state-prefixed like "KS4580__.311", hyphenated like "04-2000-0042") |
| document_class | text | e.g., "Serial Land Patent", "State Land Patent", "Indian Allotment Patent", "Indian Fee Patent", "Miscellaneous Volume Patent" |
| document_code | text | e.g., "SER", "STA", "IA", "IF", "MV" |
| state | text | Two-letter state code |
| glo_tribe_name | text | Tribe name as recorded in GLO (raw, not normalized — many variant spellings) |
| indian_allotment_number | text | Allotment number |
| signature_date | date | Patent signature date |
| total_acres | numeric | Acreage |
| land_office | text | Issuing land office |
| remarks | text | GLO remarks (often references other patent serial numbers) |
| cancelled_doc | boolean | True if document was cancelled |
| blm_serial_number | text | BLM serial number |
| document_number | text | Document number |
| misc_document_number | text | Miscellaneous document number |

**Indexes:** accession_number, glo_tribe_name, state, signature_date.

**Non-mappable patents (46,025) by document class:**

| Category | Count | Reason |
|----------|-------|--------|
| Serial Land Patent | ~27,000 | Legal descriptions that did not match PLSS parcels |
| State Land Patent | ~14,000 | Many in AL/MS (Chickasaw/Choctaw removal-era), pre-rectangular surveys |
| Indian Allotment Patent | ~3,100 | Non-standard allotment types |
| Miscellaneous Volume Patent | ~1,000 | Various |
| Other (Sioux Scrip, Chippewa Treaty, etc.) | ~325 | Specialized document types |

### `tribe_name_map` (1,286 rows)

Lookup table mapping raw `glo_tribe_name` values to normalized `preferred_name` values. Built by extracting the known mappings from records that appear in both `rails_patents` and `blm_allotment_patents`. Used by the `all_patents` view to normalize tribe names for the 46,025 non-BLM patents.

| Column | Type | Description |
|--------|------|-------------|
| glo_tribe_name | text | Raw tribe name from GLO (e.g., "CITIZEN POTAWATOMIE", "0NEIDA") |
| preferred_name | text | Normalized tribe name from BLM (e.g., "Citizen Potawatomi", "Oneida") |

No ambiguous mappings: each glo_tribe_name maps to exactly one preferred_name.

## Views

| View | Purpose |
|------|---------|
| `all_patents` | Unified view of all 285,870 patents — UNION of (rails_patents JOIN blm_allotment_patents) for 239,845 mappable + rails_patents-only for 46,025 non-mappable. Uses tribe_name_map for tribe normalization. See `sql/create_all_patents_view.sql` |
| `conversion_rates_by_tribe` | Trust-to-fee conversion statistics per tribe |
| `dispossession_chain` | Joins trust_fee_linkages with federal_register_claims to show full allotment history |
| `fee_patents_by_decade` | Fee patents grouped by decade |
| `crow_allotments` | Crow tribe allotments (case study) |
| `crow_township_conversion` | Crow conversion rates by township |
| `montana_conversion_summary` | Montana-specific conversion stats |
| `reservation_township_conversion` | Conversion by reservation and township |
| `tribe_id_map` | Tribe ID mapping |

## Key Join Logic

### Claims → Patents

```sql
LEFT JOIN forced_fee_patents_rails ffp
    ON LTRIM(fr.case_number, '0') = LTRIM(ffp.case_number, '0')
    AND fr.allottee_name = ffp.fedreg_allottee
```

- 7,110 of 9,649 forced fee claims have patent linkages
- ~2,539 claims remain unlinked
- Case numbers have leading zeros in `federal_register_claims` but not always in `forced_fee_patents_rails`

### Trust → Fee Patent Conversion

```sql
trust_fee_linkages links trust_patents.accession_number to fee_patents.accession_number
```

## Construction Notes

- The `forced_fee_patents_rails` table was built through hand-verification in a Rails admin application at IATH, UVA. The Rails app is separate from this repository.
- The `fee_patents`, `trust_patents`, and `indian_allotment_general` tables were bulk-imported from BLM GLO records.
- The `trust_fee_linkages` table was computed by matching trust patents to fee patents using allotment numbers, tribe, and cross-references in the `remarks` field.
- The `parcels_patents_by_tribe` table was imported from BLM's PLSS-based patent search, providing geographic coordinates for allotments.
- **No ETL scripts survive** for the original tables — the database was constructed iteratively and the construction process is preserved only in this documentation and the SQL dump file (`allotment_research.sql`).
- **`tribe_identified` corrections (2026-03-17):** 38 of 89 BIA agency codes had the wrong `tribe_identified` value, affecting 1,818 of 10,976 records. The error originated when Claude built the initial data import, assigning tribe names by position in the Federal Register PDF rather than by BIA agency code lookup against the legacy site. Validated against the legacy PHP site and corrected in both local and Cloud SQL. Script: `sql/tribe_identification_fixes.sql`.
- **`tribe_name_map` additions (2026-03-17):** 18 double-T Pottawatomie spelling variants added (e.g., PRAIRIE BAND POTTAWATOMIE → Prairie Band Of Potawatami Nation, CITIZEN POTTAWATOMIE → Citizen Potawatomi). These variants existed in `rails_patents.glo_tribe_name` but were missing from `tribe_name_map`, causing ~1,600 patents to show raw GLO tribe names instead of normalized preferred names in the `all_patents` view.
- The `blm_allotment_patents` table was imported via `import_blm_patents.py`, which pages through the BLM ArcGIS Feature Service REST API.
- The `rails_patents` table was imported from a CSV export of the Rails admin app (`patents-2026-03-18.csv`, 285,870 rows). The Rails app is at `land-sales.iath.virginia.edu/db/admin/patents`.
- The `tribe_name_map` table was derived by extracting distinct `glo_tribe_name → preferred_name` mappings from records that exist in both `rails_patents` and `blm_allotment_patents` (1,286 mappings, no ambiguities).
- The `all_patents` view was created via `sql/create_all_patents_view.sql`.

### `blm_allotment_patents` (239,845 rows)

Full mirror of the BLM ArcGIS tribal land patents aliquot feature service. Includes all patent types (trust, fee, allotment, etc.) with polygon geometry and PLSS descriptions. Imported via `import_blm_patents.py`.

| Column | Type | Description |
|--------|------|-------------|
| objectid | integer PK | ArcGIS OBJECTID |
| accession_number | text | GLO accession number |
| preferred_name | text | Standardized tribe name (208 distinct values; 35,706 rows blank) |
| full_name | text | Patentee full name |
| signature_date | timestamp | Patent signature date |
| authority | text | Patent authority (e.g., "Indian Fee Patent", "Indian Trust Patent") |
| state | text | Two-letter state code (21 states) |
| county | text | County name |
| forced_fee | text | 'True' or 'False' — 15,045 flagged True |
| cancelled_doc | text | Cancellation status |
| aliquot_parts | text | PLSS subdivision (e.g., "NW¼ SE¼") |
| section_number | text | PLSS section |
| township_number | text | PLSS township |
| range_number | text | PLSS range |
| township_direction | text | N or S |
| range_direction | text | E or W |
| meridian | text | PLSS meridian name |
| meridian_code | text | PLSS meridian code |
| indian_allotment_number | text | Allotment number |
| remarks | text | GLO remarks |
| centroid_lon | double precision | Centroid longitude (WGS84) |
| centroid_lat | double precision | Centroid latitude (WGS84) |
| geom_geojson | text | Polygon geometry as GeoJSON (WGS84) |

**Indexes:** accession_number, preferred_name, state, forced_fee, authority, signature_date, indian_allotment_number.

**Source:** `https://services2.arcgis.com/8k2PygHqghVevhzy/arcgis/rest/services/tribal_land_patents_aliquot_20240304/FeatureServer/0`

**Top tribes by patent count:** Rosebud Sioux (12,970), Oglala Lakota (12,634), Crow (11,643), Blackfeet (10,333), Standing Rock Sioux (10,139).

**Top tribes by forced fee count:** Blackfeet (2,886), Crow (1,645), Cheyenne River Sioux (1,407), Oglala Lakota (1,316), Standing Rock Sioux (1,253), Rosebud Sioux (1,236).

## Backup

The complete database is preserved as `allotment_research.sql` (110 MB), a `pg_dump` export. To restore:

```bash
createdb allotment_research
psql -d allotment_research < allotment_research.sql
```
