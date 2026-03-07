# Database: `allotment_research`

## Overview

PostgreSQL database containing forced fee patent claims from the 1983 Federal Register, BLM patent records, trust-to-fee linkages, PLSS land descriptions, and a full ArcGIS patent mirror. Built to support research on Indian allotment land dispossession.

**Total: 9 tables, 8 views, ~960,000 rows.**

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
| tribe_identified | text | Tribe name as identified in the Federal Register |
| case_number | text | BIA case number (may have leading zeros) |
| allottee_name | text | Name of the allottee |
| allotment_number | text | Allotment number |
| claim_type | text | All 30 variants start with "FORCED FEE PATENT" |
| document_source | text | Federal Register citation |
| publication_date | text | Date of Federal Register publication |

**56 tribes** represented. Largest: Cheyenne River Sioux (1,382), Standing Rock Sioux (830), Yakama (693), Winnebago (687), Potawatomi (638).

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

## Views

| View | Purpose |
|------|---------|
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
- The `blm_allotment_patents` table was imported via `import_blm_patents.py`, which pages through the BLM ArcGIS Feature Service REST API.

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
