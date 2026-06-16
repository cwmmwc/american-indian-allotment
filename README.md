# Indian Land Allotment Research

A Flask web application for researching the history of Indian allotment land dispossession — from the allotment era (1887–1934) through termination (1947–1957). Built at the [Institute for Advanced Technology in the Humanities](https://www.iath.virginia.edu/), University of Virginia, as part of the [Indian Land Allotment Research](https://land-sales.iath.virginia.edu/) project directed by Christian W. McMillen.

The site integrates four primary historical datasets — 285,870 BLM allotment patents, 10,976 Federal Register forced fee claims, the Wilson Report (1934), and the Murray Memorandum (1958) — into a searchable, cross-referenced research tool with an interactive allotment map and data visualizations.

## Site Structure

### Landing Page (`/`)
A splash page modeled after the [IATH main site](https://land-sales.iath.virginia.edu/), featuring full-width historical document images with clickable hotspots linking to high-resolution scans. Includes the Neda Laura Parker quote (Comanche, 1925) and links to the four primary datasets. Serves as the gateway to the research application.

### Research Home (`/home`)
Overview of the project's four datasets — BLM Patents, Federal Register Claims, the Wilson Report, and the Murray Memorandum — with summary statistics and navigation to all sections of the site.

### Allotment Map (`/map`)
Interactive Leaflet map displaying 239,845 allotment patents matched to Public Land Survey System (PLSS) parcels. The polygon layer was built by **UVA Library's [Scholars' Lab](https://scholarslab.lib.virginia.edu/)** from BLM cadastral survey records joined to allotment patent data, and published as a public-shared feature service on UVA Library's ArcGIS Online account. Both the project's one-time ingest (`import_blm_patents.py`) and the live map's JavaScript fetch directly from that public layer. Features include:
- Filter by tribe, state, patent category, and time range
- Name search with zoom-to-parcel
- Cumulative timeline mode showing trust-to-fee conversion over time
- Heatmap and parcel-level rendering (parcels at zoom >= 9, centroids at wider zoom)
- Analysis panel with temporal distribution, trust vs. fee comparison, forced fee rates by reservation, conversion velocity, and top counties
- Tribe comparison table
- Federal Indian Reservations and Rankin 1907 Crow map overlays
- Deep-linking from claim, patent, and tribe pages via `?tribe=...&accession=...`

The map is a standalone page (does not use the Bootstrap base template) with its own thin navigation bar and full-viewport 3-column grid layout. Assets live in `static/map/js/` and `static/map/css/`.

**Data coverage:** The research database contains 285,870 patents. The map displays 239,845 — those matched to PLSS parcels. Approximately 46,000 patents cannot be mapped because they use non-rectangular survey descriptions (primarily Arizona/New Mexico reservations using metes-and-bounds surveys, and southeastern removal-era patents predating the PLSS). All 285,870 patents are searchable on the Patents page.

### Claims Search (`/claims`)
Full-text search across 10,976 Federal Register claims (9,649 forced fee, 1,327 secretarial transfer). Filter by allottee name, allotment number, tribe, claim type, and date range. Server-side pagination and CSV export.

### Individual Claim Pages (`/claim/<id>`)
Detailed view of each FR claim including linked BLM patents, trust-to-fee conversion details, PLSS land descriptions, and direct links to GLO patent images.

### Patent Search (`/patents`)
Browse and search 285,870 BLM allotment patent records. Filter by name, tribe, state, patent type, date range, and map status (mappable vs. not mappable). The patent-type filter offers **Fee Patents**, **Trust Patents**, and **Forced Fee & Related Claims**. The last bucket covers the seven Federal Register `claim_type` categories that represent loss of trust title: forced fee patent, secretarial transfer, unapproved land sale (incl. land sold without approval), tax forfeiture, taxation, and claim for recovery of trust/restricted land. Trespass, welfare, timber, old-age-assistance, allotment-never-issued, and questionable-cancellation claims are intentionally excluded — they're not about loss of trust title. Server-side pagination and CSV export. Each patent links to its detail page and, if mappable, directly to its parcel on the allotment map.

### Individual Patent Pages (`/patent/<id>`)
Full patent detail with legal land descriptions, authority citations, and links to the allotment map.

### Tribe Pages (`/tribes`, `/tribe/<slug>`)
Landing pages for each of 57 tribes with summary statistics, timeline charts, sortable claims tables, and links to the allotment map.

### Visualizations

- **Forced Fee Timeline** (`/timeline`) — FR claims plotted by year with policy era context and historical annotations.

- **All Patents Timeline** (`/patents/timeline`) — Distribution of 239,845 patents by year with forced fee toggle, Wilson Table VIII annual sales overlay (1903–1934), and Murray Memorandum overlay (acres removed from trust, 1948–1957). Includes a dedicated Wilson annual sales chart showing original vs. inherited land breakdowns and proceeds.

- **Trust-to-Fee Conversion / Sankey** (`/sankey`) — D3 Sankey diagram showing how patents moved between trust and fee status, with FR forced fee claims as a sub-flow. Per-tribe Wilson baseline cards and Murray termination-era context.

- **Claims by Reservation** (`/claims-rate`) — Scatter plot and bar chart comparing fee patents vs. FR claims per tribe.

- **Wilson Report** (`/wilson`) — Stacked bar charts of 1934 reservation land composition (212 reservations), alienation rates vs. FR forced fee comparison, and Murray termination-era comparison showing two waves of land loss. Links to all digitized Wilson source tables and the original 1935 PDF.

- **Murray Memorandum** (`/murray`) — Comprehensive page with summary statistics, four interactive charts (trust removal by year, transactions by year, lands acquired, 1947 vs 1957 comparative), a searchable agency table, a complete source table directory linking to every IATH-digitized table, and the original PDF.

- **Du Bois Data Portraits** (`/dubois`) — Experimental visualizations inspired by W.E.B. Du Bois's data portraits: a spiral chart of Wilson annual sales, horizontal bars of land alienated vs. retained by reservation, a forced fee timeline with policy era shading, and a radial bar chart of FR claims by tribe.

### BIA File References (`/file_refs`, `/file_ref/<letter>-<year>`)

Browse the **66,840 BIA archival file references** that the project has parsed and clustered against allotment patents.

- **`/file_refs`** — Sortable index of every distinct file reference, with filters for I.O.-label status (`yes` / `no` / `mixed` / `unknown`), CCF era (pre-1907 / 1907–1942 / 1943–1975 / post-1975), minimum patent count, and tribe-or-state. Server-side paginated (DataTables AJAX) so the page loads in under a second even at 66K rows. Each row shows the file reference, year, number of patents that share it, geographic and tribal concentration, and the rolled-up I.O. label.

- **`/file_ref/<letter>-<year>`** — Cluster view for a single file reference. Shows the full cohort of patents that share the reference, plus state / tribe / authority / label-variant breakdowns and a date range. Used to turn batches of individually unremarkable patents into a single coherent administrative episode (e.g., the 4,544 Blackfeet patents from 1922 that share file `25338-21`).

A "Related BIA File References" block also appears on individual patent pages (`/patent/<id>`) whenever the patent has a captured reference.

### Trust → Fee Linkages (`/linkages`)

Browse the **74,424 trust→fee linkages** recovered from BLM patent records by two independent passes: (1) **remarks-regex** — parse cross-references like `SEE SERIAL PATENT NR 75921-09 FOR FEE PATENT` from the BLM remarks text (65,381 linkages); (2) **parcel-matching** — link trusts to fees that share a PLSS parcel and an allottee name token (9,043 linkages), used when remarks are empty or carry a transcription typo. Filters: source (remarks / parcel), match type (exact / normalized / fuzzy / parcel+name), fee state, name-consistent, trust→fee gap range. Server-side paginated. A "Trust ↔ Fee Linkages" block also appears on individual patent pages whenever the patent is on either side of a recovered linkage, showing the source badge per row. See the [dedicated section below](#trust--fee-linkages-from-remarks-may-2026) for provenance and the bug fixes that made this layer reliable.

### About (`/about`)
Project background, methodology, data sources, and acknowledgments.

## The Data

### Federal Register Claims (1983)
In 1983, the Bureau of Indian Affairs published two Federal Register notices listing Indian allotment claims — documenting allotments where fee patents had been issued without the allottee's consent ("forced fee patents"), as well as secretarial transfers.

- **9,649** forced fee patent claims
- **1,327** secretarial transfers
- ~7,110 linked to BLM patent records; ~2,539 unlinked

**The Federal Register is the sole authoritative source for forced fee counts.** The BLM `forced_fee` flag inflates numbers through one-to-many patent matching and must not be used for this purpose.

The patents page exposes the broader **Forced Fee & Related Claims** view — forced fee plus secretarial transfer, unapproved land sale, tax forfeiture, taxation, and claim for recovery of trust/restricted land. These are the FR `claim_type` buckets that all represent loss of trust title. For some agencies (notably the Ponca Agency `B07813`, which submitted **zero** forced-fee claims and **fourteen** recovery-of-trust claims), the broader view is the only way to surface dispossession at all. The strict forced-fee-only view remains available via the claims page dropdown.

### BLM Allotment Patents
**285,870** General Land Office patent records from the Bureau of Land Management, covering trust patents, fee patents, and other allotment-related patents across all tribes. Of these, **239,845** were originally matched to PLSS parcels via BLM's published `tribal_land_patents_aliquot` Esri layer. In June 2026 a separate recovery pipeline brought another **12,907** patents onto the map via BLM CadNSDI (see [next section](#cadnsdi-patent-recovery-june-2026)), so the current mappable total is **252,752** of 285,870. The remaining **33,690** patents (down from 46,025) are still searchable on the patents page but cannot be geocoded — these are dominated by metes-and-bounds Navajo / Pueblo / Apache allotments in the Southwest and pre-PLSS removal-era patents in Alabama and Mississippi.

### CadNSDI Patent Recovery (June 2026)

**12,907** previously-unmappable Serial Land Patents and State Land Patents were brought onto the map by extending the project beyond the original BLM aliquot Esri service to the **BLM National PLSS CadNSDI** service. Of the recovered records, **1,676 render at parcel-level precision** (the actual ~40-acre government lot or quarter-quarter subdivision) and **11,231 render at section-level precision** (a 1-square-mile section box containing the actual parcel). Section-level records are visually distinct on the map — dashed border, lighter fill — and the popup carries an explanatory note.

#### What CadNSDI is

The **Cadastral National Spatial Data Infrastructure** is the federal program that publishes the United States Public Land Survey System as standardized vector geometry. "Cadastre" is the old surveyors' term for a registry of land parcels; "NSDI" is the broader federal effort to coordinate geospatial data across agencies. CadNSDI is the cadastral piece of that effort.

#### Who maintains it

The **Federal Geographic Data Committee (FGDC)** coordinates federal geospatial themes; each theme has a lead steward. The **Bureau of Land Management (BLM)** is the federal steward for the cadastral theme, which in the public-land states means the PLSS. State PLSS stewards (typically state geological surveys or land offices) submit their data upward to BLM, which aggregates and republishes nationally. **The depth of detail each state submits varies** — this is the load-bearing fact for why the recovery yields different precision in different states.

#### What's published

BLM's National PLSS CadNSDI service exposes the PLSS as a public Esri ArcGIS REST API at:

```
https://gis.blm.gov/arcgis/rest/services/Cadastral/BLM_Natl_PLSS_CadNSDI/MapServer
```

with four nested layers:

| layer | name | resolution |
|---|---|---|
| 0 | State Boundaries | very coarse |
| 1 | PLSS Township | 6 mi × 6 mi (~23,040 acres) |
| 2 | PLSS Section (First Division) | 1 mi × 1 mi (~640 acres) |
| 3 | **PLSS Intersected** | **atomic — aliquots, government lots, special-survey tracts** |

The recovery pipeline queries **layer 3** for parcel-level matches and falls back to **layer 2** for section-perimeter approximations. Layer 3 returns the atomic non-overlapping polygons for everything below the section level: quarter-sections (`QSEC`), quarter-quarter sections (`QQSEC`), government lots (`GOVLOT`), and non-rectangular special surveys (`SURVTYP` / `SURVNO`). Each polygon carries the full PLSS keys (`PRINMERCD`, `TWNSHPNO`, `TWNSHPDIR`, `RANGENO`, `RANGEDIR`, `FRSTDIVNO`) plus whichever sub-section identifier applies.

#### How the recovery joins to our data

The other half of the join sits in our own Postgres: `parcels_patents_by_tribe` (401,811 rows, sourced from BLM GLO bulk data) records the meridian/township/range/section/aliquot for each patent, keyed on `indian_allotment_number + state + signature_date`. The recovery pipeline pulls a patent's PLSS keys from that table (or from the IATH GLO Bulk Data CSVs for patents without allotment numbers — KS treaty-era cases, etc.) and constructs the matching CadNSDI query.

A sample query for Lizzie Anderson's 1919 patent (Lot 1 NE¼ + Lot 3 NW¼ of Section 26, T10N R3E, Indian Meridian, Pottawatomie OK):

```
GET https://gis.blm.gov/arcgis/rest/services/Cadastral/BLM_Natl_PLSS_CadNSDI/MapServer/3/query
    ?where=PRINMERCD='17' AND TWNSHPNO='010' AND TWNSHPDIR='N'
           AND RANGENO='003' AND RANGEDIR='E'
           AND FRSTDIVNO='26' AND GOVLOT='1'
    &outFields=SECDIVID,SECDIVNO,SECDIVSUF,GOVLOT,SURVTYP,SECDIVTYP
    &returnGeometry=true
    &f=geojson
```

The response is a standard GeoJSON FeatureCollection with the lot's polygon and metadata. For records described by a standard aliquot like `NESW`, the filter is `QQSEC='NESW'` instead of `GOVLOT=`. Multiple polygons sharing a SECDIVID are dissolved (a lot can be split into adjacent pieces by an internal survey line).

#### Per-meridian coverage variation

Sub-section detail isn't uniform across CadNSDI. The state stewards decide how far down they publish. Empirically:

| Principal Meridian | states it covers | sub-section detail | typical recovery granularity |
|---|---|---|---|
| PM05 (5th) | MN, parts of MO/AR/SD | mostly published | parcel-level |
| PM06 (6th) | KS, NE, parts of CO/WY/SD | NOT published | section-level (640 acres) |
| PM17 (Indian) | OK | mostly published | parcel-level |
| PM34 (Wind River) | WY | published | parcel-level |
| PM46 (4th) | WI | private claims, different schema | deferred |

Kansas and Nebraska records dominate the section-level recovered set (~2,500 + ~464 records respectively) because the 6th Principal Meridian state stewards never pushed sub-section detail to the national index. The underlying surveys exist as paper tract books and survey plats in BLM GLO bulk data; converting those to vector polygons would be a separate project.

#### Recovery yield

| outcome | count | share |
|---|---|---|
| Recovered, parcel-level | 1,676 | 12.4% |
| Recovered, section-level | 11,231 | 83.3% |
| Not in CadNSDI (genuine gaps) | 571 | 4.2% |
| **Total recovery rate** | **12,907 / 13,478 attempted** | **95.8%** |

#### Files

- `scripts/recover_lizzie_smoke_test.py` — single-record proof of concept for accession 715724 (the first record recovered).
- `scripts/recover_patents_bulk.py` — full bulk pipeline. Parallel HTTP queries (6 workers default), resumable, idempotent via `ON CONFLICT DO UPDATE`. Run log streamed to `data/cadnsdi_bulk_run_<timestamp>.csv` with per-accession outcome.
- `sql/update_all_patents_view_with_recovered.sql` — additive view extension that surfaces recovered patents through the `all_patents` view via a new `is_mappable` column.
- `deploy_cadnsdi_recovery_to_cloud_sql.sh` — coordinated Cloud SQL deploy.
- `fix_view_owner_and_retry.sh` — companion that applies the view DDL as `appuser` (the role that owns `all_patents` on Cloud SQL — Cloud SQL's `postgres` role isn't a true superuser and can't override object ownership).

### Wilson Report (1934)
The Wilson Report documented the state of **212 Indian reservations** as of 1934, when the Indian Reorganization Act ended general allotment. Records original reservation areas, allotments made, and **23.2 million acres alienated** through sales and fee patents — the cumulative land loss of the allotment era.

### Murray Memorandum (1947–1957)
The Murray Memorandum documented a second wave of land loss during the termination era. Across **52 BIA agencies**, individual Indian trust land fell from **15.9 million acres (1947) to 12.6 million (1957)** — a net loss of 3.3 million acres through 18,546 trust removal transactions.

### BIA Central Classified Files References (May 2026)
**66,840** distinct BIA archival file references (in the NNNNN-YY format used by the Bureau of Indian Affairs' Central Classified Files system, 1907–1975) linked to **159,477** allotment patents through **182,446** patent-reference connections. Each file reference is a pointer into the BIA correspondence record at the National Archives — the underlying paper trail of allotment processing, fee conversions, and policy decisions. Files are shared across patents that were processed together, so clustering by reference exposes administrative episodes that aren't otherwise visible in the patent metadata. The largest single cluster connects **4,544 Blackfeet 1922 trust patents** to one 1921 BIA file. See the [dedicated section below](#bia-file-references-may-2026) for the schema, the I.O. labeling system, and the major clusters.

## Research Notes

- [`CORPORATE_BUYERS.md`](CORPORATE_BUYERS.md) — corporate (non-Native) grantees of allotment patents across the corpus. Identifies five distinct historical episodes (Creek removal speculators, Plains cattle, Western timber, Great Lakes paper, California utilities) and the mass-acquisition events that define them. Sources: `scripts/find_corporate_buyers.py`, `scripts/find_lumber_buyers.py`, `scripts/link_lumber_to_fr.py`.
- [`AI_AS_RESEARCH_PARTNER.md`](AI_AS_RESEARCH_PARTNER.md) — note on how working with an AI model contributed to this project, prompted by the discovery that ~55,000 missing trust→fee linkages were already sitting unparsed in the database's `remarks` field. A reflection on AI's value not in automation but in asking the right question at the right moment.

## Tech Stack

- **Backend**: Python 3, Flask, psycopg2
- **Database**: PostgreSQL (`allotment_research`)
- **Frontend**: Bootstrap 5, jQuery, DataTables
- **Map**: Leaflet.js, leaflet.heat, Esri ArcGIS Feature Service (UVA Library's Scholars' Lab polygon layer; basemap tiles from Esri's public ArcGIS Online; reservation boundary overlays from Census TIGERweb)
- **Charts**: Chart.js (bar/line charts), D3.js v7 (Sankey, radial/spiral, Du Bois plates)
- **Templates**: Jinja2
- **Deployment**: Google Cloud Run, Cloud SQL (PostgreSQL), Cloud Build (auto-deploy on push)

## Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install flask psycopg2-binary
```

## Configuration

The database connection defaults to `dbname=allotment_research user=cwm6W`. Override with the `DATABASE_URL` environment variable:

```bash
export DATABASE_URL="dbname=allotment_research user=your_user host=localhost"
```

## Running

```bash
cd /Users/cwm6W/projects/federal-register-app
source venv/bin/activate
python3 app.py
```

The app runs at http://127.0.0.1:5001.

## Database Tables

| Table | Rows | Description |
|-------|------|-------------|
| `federal_register_claims` | 10,976 | 1983 Federal Register forced fee claims and secretarial transfers |
| `rails_patents` | 285,870 | Full patent catalog with `has_plss_geometry` flag |
| `blm_allotment_patents` | 239,845 | BLM patent mirror from ArcGIS (mappable patents) |
| `all_patents` (view) | 285,870 | Unified view joining `rails_patents` + `blm_allotment_patents` |
| `forced_fee_patents_rails` | 17,560 | Hand-verified claim-to-patent linkages |
| `trust_fee_linkages` | 29,229 | Trust-to-fee patent conversion records (from allotment-number / tribe matching) |
| `trust_fee_linkages_recovered` | 74,424 | Trust-to-fee linkages recovered by parsing BLM remarks (65,381) and matching PLSS parcels + allottee name family (9,043); kept distinct from `trust_fee_linkages` |
| `wilson_table_vi` | 212 | Wilson Report 1934 reservation baseline data |
| `wilson_annual_sales` | ~32 | Wilson Table VIII annual land sales 1903–1934 |
| `murray_comparative` | 52 | Murray Memorandum 1947 vs 1957 land by agency |
| `murray_transactions` | 520 | Murray trust removal transaction counts by agency and year |
| `murray_trust_removal` | 83 | Murray trust land removed by area office and year |
| `murray_agency_removal` | 41 | Murray total acres removed by agency |
| `murray_lands_acquired` | 23 | Federal lands acquired since 1930 |
| `parcels_patents_by_tribe` | 401,811 | PLSS legal land descriptions |
| `cadnsdi_recovered_patents` | 12,907 | Patents whose geometry was recovered from BLM CadNSDI (1,676 parcel-level, 11,231 section-level). Sourced via `scripts/recover_patents_bulk.py`. Joined into `all_patents` via the `is_mappable` column. |
| `patent_file_references` | 66,840 | Distinct BIA NNNNN-YY archival file references with I.O. rollup + cluster aggregates |
| `patent_file_ref_links` | 182,446 | Many-to-many between patents and file references, with per-link I.O. label evidence |
| `cancelled_patent_research` | 439 | McMillen-compiled cancelled-patent metadata (legal authority, dates, CCF numbers) |

## Key Files

- `app.py` — All routes, queries, and API endpoints (single file)
- `templates/` — Jinja2 HTML templates (splash, home, claims, patents, map, tribe pages, visualizations)
- `templates/map.html` — Standalone map template (does not extend `base.html`)
- `static/style.css` — Global styles
- `static/map/js/` — Map application JavaScript modules (config, data, map, controls, analysis, timeline, utils, main)
- `static/map/css/styles.css` — Map-specific styles (3-column grid layout, custom design system)
- `scripts/` — Data import and scraping scripts (Wilson, Murray)
- `Dockerfile` — Container build for Cloud Run
- `cloudbuild.yaml` — Cloud Build CI/CD pipeline (auto-deploy on push to main)
- `CLAUDE.md` — Full architecture guide (auto-loaded by Claude Code)
- `CLOUD_RUN.md` — Cloud Run deployment cheat sheet
- `DATABASE.md` — Complete database documentation

## Deployment

The app is deployed on Google Cloud Run with auto-deploy via Cloud Build. Pushing to `main` triggers a build and deploy.

- **Live URL:** https://federal-register-app-996830241007.us-east1.run.app
- **GCP Project:** lunar-mercury-397321
- **Region:** us-east1
- **Database:** Cloud SQL PostgreSQL (`allotment-db` instance, `allotment_research` database)

See `CLOUD_RUN.md` for deployment commands, database access, log viewing, and rollback procedures.

## Data Fixes (May 2026)

Three fixes to the patent search and detail pages, resolving issues that affected tens of thousands of records:

### Patentee Names for 46,025 Non-BLM Patents
The `rails_patents` table (285,870 records imported from the IATH Rails admin) had no patentee name column — names lived in a separate `people` table in the Rails database that was not included in the original CSV export. This meant 46,025 patents that exist only in `rails_patents` (not in the BLM ArcGIS mirror) were unsearchable by name. The `all_patents` view returned `NULL` for their `full_name`.

**Fix:** Scraped all 285,736 patent records with patentee names from the IATH search at `land-sales.iath.virginia.edu` (286 paginated requests, ~10 minutes). Added a `full_name` column to `rails_patents`, populated 267,093 rows. Updated the `all_patents` view to use `COALESCE(bap.full_name, rp.full_name)` so non-BLM patents show the scraped name. Scraped data at `iath_patents_with_names.csv`.

### Patent Detail Routing for 15,432 ID Collisions
The patent detail route (`/patent/<id>`) checks `blm_allotment_patents.objectid` first, then falls back to `rails_patents.id`. Both are integers in overlapping ranges. For 15,432 non-BLM patents, `rails_patents.id` collides with a different person's `blm_allotment_patents.objectid` — clicking the link shows the wrong person's record.

**Fix:** Patent search results now append `?src=rails` to links for non-BLM patents (where `objectid` is null). The detail route checks this parameter and queries `all_patents` directly by `id` when present, skipping the BLM lookup. BLM-backed patents continue to use the normal route.

### GLO Links for 91,957 Non-Numeric Accession Numbers
The `glo_url()` function hardcoded `docClass=SER` (Serial Land Patent) for all GLO links. But 91,957 patents have non-Serial document classes — State Land Patents (`STA`), Indian Allotment Patents (`IA`), Miscellaneous Volume Patents (`MV`), etc. Links for these patents pointed to BLM with the wrong document class and failed to resolve.

**Fix:** `glo_url()` now accepts the patent's `document_code` (or maps `authority` names like "State Land Patent" to codes like "STA") and generates links with the correct `docClass` parameter. All 285,870 patents now produce valid GLO links.

## BIA File References (May 2026)

A new analytical primitive layered on top of the existing patent data: every BLM allotment patent that carries a BIA Central Classified Files reference is now indexed by that reference, with each file's full cluster of patents queryable as a single research object. **66,840 distinct file references** are linked to **159,477 patents** through **182,446 patent-reference connections**. The largest single cluster connects 4,544 Blackfeet 1922 trust patents to one 1921 BIA file.

### Why this matters

The BIA's Central Classified Files (CCF) is the universal subject correspondence archive of the Indian Office at the National Archives. Per [NARA's documentation](https://www.archives.gov/research/native-americans/central-classified-files), a complete CCF citation has four elements: `letter_number / year / decimal_classification / agency-or-jurisdiction` (example: `12540 / 1950 / 307.4 / Alaska`). Letter numbers run from single digits to six digits; the year is when the file was opened; the decimal class is the BIA's subject taxonomy; the agency is the BIA office responsible. The system was active from **1907 to 1975**, in three NARA-numbered series (121A: 1907–1939; 121B: 1940–1957; 121C: 1958–1975). NARA has digitized the index cards through 1942 ([catalog reference](https://www.archives.gov/research/native-americans/central-classified-files-index)); post-1942 index entries exist only on paper at Archives 1.

BLM allotment patents in the CCF era carry these references in the top-left of the printed form, sometimes labeled "I.O." (Indian Office), sometimes unlabeled. When a trust patent later converted to fee, a middle-page "Fee Patent Issued" stamp records the conversion's own administrative file reference. **The same BIA file appears on many patents** because BIA processed patents in batches under shared correspondence files — which means clustering patents by shared reference reveals the administrative episodes that produced them.

### Data sources

Two complementary capture mechanisms feed `patent_file_references`:

1. **BLM's structured columns** (the bulk). `rails_patents.misc_document_number` carries the I.O.-labeled reference; `rails_patents.document_number` carries the unlabeled reference when one is present. A direct backfill from these columns (no regex, no vision) produces ~65,540 of the 66,840 distinct references. This data was always in the database — it just hadn't been promoted into a queryable structure.

2. **Transcribed BLM remarks** (the original parse). `rails_patents.remarks` sometimes contains BLM operators' free-text annotations like `ADDITIONAL IO #60798-08` or `ADDITIONAL BIA #6744-49`. A regex pass (`scripts/extract_file_refs_from_remarks.py`) recovered the original 1,300 references — most of which are NOT in BLM's structured columns because they reference *additional* files (typically the BIA conversion-action file when a trust patent was stamped during fee conversion).

The two sources are merged into the same schema with provenance: `patent_file_ref_links.source_location` records `structured_misc_doc` / `structured_doc_number` / `remarks`, and `context_label` preserves the exact transcribed label.

### The I.O. labeling system

BLM placed I.O.-labeled CCF references in `misc_document_number` and unlabeled ones in `document_number` — a convention that holds for ~99.9% of distinct references. A corpus-wide audit found **80 "leaky" references** (0.12%) that appear in both columns across different patents; root causes include both BLM data-entry errors and genuine document-level labeling variation where the same file was marked I.O. on some patents but not others.

The schema records this faithfully:

- **Per-link `io_labeled`** (yes / no / unknown) on `patent_file_ref_links` records what each individual source said — `misc_document_number` → yes; `document_number` → no; `remarks` with an IO-family label → yes; `remarks` with a BIA / DOCUMENT label → unknown (those labels are operator convention, not document truth).
- **Per-reference `io_labeled` rollup** on `patent_file_references` aggregates across all links to that file:
  - `yes` (62,601 refs, 94%) — every link confirms I.O.-labeled
  - `no` (4,131 refs, 6%) — every link confirms unlabeled
  - `mixed` (80 refs, 0.12%) — both yes and no evidence exists; manual review recommended
  - `unknown` (28 refs, 0.04%) — only unlabeled-label remarks evidence (BIA / DOCUMENT family)

### Important caveat

**A reference being on a patent does not mean the underlying file is about that patent.** Direct PDF and NARA index card inspection confirms cases of both:

- *Subject-relevant*: CCF `73344-08 I.O.` appears on Aichikapomik's 1909 Turtle Mountain Chippewa trust patent, and the NARA card for that file reads "Relative allotments of Turtle Mountain Indians" (decimal 312, Fort Totten Agency) — directly relevant to her allotment.
- *Administratively-stamped-but-unrelated*: CCF `30429-09 I.O.` appears on Hannah Fights-the-Bear's 1910 Cheyenne River Sioux trust patent, but the NARA card for that file reads "Telegram from F. E. Leupp [BIA Commissioner] re: authority for wire screen for Phoenix School, all tuberculosis work suspended awaiting this material" (decimal 525, Schools) — has zero substantive connection to her allotment.

The reference's *subject relevance* requires reading the NARA card content. This project captures the reference; the relevance question lives downstream.

### Notable clusters

| Reference | Year | Patents | Tribe / State | Issued | Authority dominant |
|---|---|---|---|---|---|
| `25338-21` | 1921 | 4,544 | Blackfeet (MT) | 1922 | Trust |
| `67183-20` | 1920 | 2,966 | Gila River (AZ) | 1921 | (BLM authority blank) |
| `29450-23` | 1923 | 2,751 | Crow (MT) | 1923–24 | Trust + Homestead Trust |
| `79351-25` | 1925 | 2,487 | Standing Rock Sioux (SD/ND) | 1926 | Trust |
| `5426-08` / `119392-08` | 1908 | 2,375 each | Flathead (MT) | 1908 | Trust |
| `19162-26` | 1926 | 2,251 | Assiniboine & Gros Ventre (Fort Belknap, MT) | 1927 | Trust + Homestead Trust |
| `9834-10` | 1910 | 2,057 | Colville (WA) | 1917 | Trust |
| `87140-11` | 1911 | 1,980 | Assiniboine & Sioux (Fort Peck, MT) | 1913 | Trust |
| `37106-13` | 1913 | 1,837 | Shoshone & Bannock (Fort Hall, ID) | 1916 | Trust |
| `63889-19` | 1919 | 1,786 | White Earth Chippewa (MN) | 1919–20 | **Indian Fee Patent** |
| `6744-49` | 1949 | 171 | Pit River / Paiute / Wintu / Dixie Valley (CA) | 1950–52 | Indian Fee Patent (termination-era) |
| `14329-08` | 1908 | 4 | Leech Lake Chippewa (MN) | 1908 | Misc. Volume — Fred Nason family |

Every top cluster is **tribally and geographically homogeneous** — a single tribal allotment batch processed under one administrative file. The CCF year typically precedes patent issuance by 1–3 years (file opened, then patents flowed through later).

### Future verification: NARA Index Cards integration

UVA Law Library's [`uvalawlibrary/nara-index-cards`](https://github.com/uvalawlibrary/nara-index-cards) project (Loren S. Moulds, research partner) has extracted **~1.4 million NARA BIA Central Classified Files index cards** for the digitized 1907–1942 window, using vision-language models (Qwen2.5-VL-72B and Gemma 4 31B). Each extracted card has the letter number, year, decimal classification, agency, correspondent, and a one-line summary as structured fields. For the **683 of our 66,840 references that fall in the 1907–1942 window**, joining against Loren's data would resolve each ref from a partial citation (letter + year only) to the full four-element CCF citation, enriching every cluster page with subject classification and agency. Post-1942 references (in CCF series 121B / 121C) remain partial citations until either Loren's project extends forward in time or the paper index at NARA Archives 1 is consulted.

### Schema and scripts

- **`sql/create_patent_file_references.sql`** — original schema (now extended)
- **`sql/add_io_labeled_columns.sql`** — adds per-link / per-ref `io_labeled` text columns
- **`sql/add_file_ref_aggregates.sql`** — adds pre-computed aggregate columns (`patent_count`, `state_list`, `top_tribe`, `top_context_label`, `min_signature_date`, `max_signature_date`) so the server-side DataTables endpoint can paginate at scale without per-request aggregation
- **`scripts/extract_file_refs_from_remarks.py`** — regex-based capture from `remarks` field
- **`scripts/backfill_file_refs_from_structured.py`** — direct backfill from `misc_document_number` and `document_number`
- **`scripts/backfill_io_labeled_for_remarks.py`** — assigns per-link `io_labeled` to existing remarks-derived links based on the transcribed `context_label`
- **`scripts/compute_io_labeled_rollup.py`** — computes per-reference `io_labeled` rollup from all links
- **`scripts/compute_file_ref_aggregates.py`** — populates the pre-computed aggregate columns

Re-run order after any new ingest: `extract_file_refs_from_remarks.py` (if new remarks) → `backfill_file_refs_from_structured.py` (if new patents) → `backfill_io_labeled_for_remarks.py` → `compute_io_labeled_rollup.py` → `compute_file_ref_aggregates.py`.

## Trust → Fee Linkages from Remarks (May 2026)

A second recovery layer that pulls trust→fee patent linkages directly out of BLM patent records. **74,424 validated linkages** now sit in `trust_fee_linkages_recovered`, kept separate from the older `trust_fee_linkages` (29,229 rows, computed via allotment-number / tribe matching) so each table's provenance remains queryable.

The trigger for this work: BLM operators routinely typed pointers like `SEE SERIAL PATENT NR 75921-09 FOR FEE PATENT`, `FEE PATENT 720002`, or `PT NR 985654` into the remarks of trust patents that later converted. That data was always present — it just hadn't been parsed.

### Two sources

The recovered table is fed by two independent passes, distinguished by the `source` column so any linkage can be traced to how it was found:

| source | rows | how it works |
|---|---:|---|
| `remarks_regex_v2` | 65,381 | Parse cross-references out of `rails_patents.remarks`, then validate the extracted accession against the patent catalog (exact, normalized, or fuzzy match). |
| `parcel_match_v1` | 9,043 | Join trust patents to fee patents on shared PLSS parcel (state + county + township + range + section + aliquot) AND at least one shared allottee name token. Used to recover linkages the remarks layer cannot reach: BLM transcription typos in the cross-reference itself, and trust patents with no remarks at all. |

The two layers deduplicate on `(trust_accession, fee_accession)` so a linkage discovered by both methods only appears once.

### Why both layers are needed

The remarks layer is the canonical signal — BLM operators put the cross-reference there exactly because it's the conversion event being documented. But it has two known failure modes:

1. **Transcription typos.** Lizzie Dowd's 1891 trust `IA-0505-453` carries the remarks `CANCELED DOCUMENT  SEE MISCELLANEOUS VOLUME NR 0505-453 FOR FEE PATENT`. The cross-reference accession is wrong — it points to the trust patent itself instead of the real fee `MV-0580-454`. Regex extracts what's there; it cannot know the operator typoed.
2. **Empty remarks.** Lizzie Dowd's other 1891 trust `IA-0505-452`, on the same parcel, has no remarks at all. The conversion still happened — it's just not textually documented on the trust side.

The parcel layer covers both. It finds `0505-452 → 0580-454` and `0505-453 → 0580-454` (same Section 31, T5S R8W, Yamhill County, OR; trust 1891-06-13, fee 1906-10-29 issued to "GILMAN, LIZZIE D; DOWD, LIZZIE" — surname change matches the 15-year marriage gap).

### Match types

| Type | Rows | Meaning |
|---|---|---|
| `exact` | 21,165 | Remarks accession matches a known patent verbatim |
| `normalized` | 42,952 | Remarks match after stripping leading zeros / standardizing accession formatting |
| `fuzzy(d=1)` | 459 | Remarks match within edit distance 1 (single-digit transcription typos) |
| `fuzzy(d=2)` | 805 | Remarks match within edit distance 2 (two-character drift — usually a digit + format slip) |
| `parcel_name` | 9,043 | Trust and fee share PLSS parcel + at least one allottee name token |

Each row also carries:
- **`name_consistent`** — whether the trust and fee patentees share at least one name token (the strongest single confidence signal beyond accession match)
- **`date_gap_years`** — years between trust date and fee date (median across the corpus is 19 years)
- **`extracted_raw`** — the literal substring that produced the match (for remarks rows) or the literal `(parcel+name match)` marker for parcel rows
- **`source`** — `remarks_regex_v2` or `parcel_match_v1`

### Bugs the v2 regex fixes

A corpus-wide audit on 2026-05-21 surfaced three bugs in the original `remarks_regex_v1` pipeline:

| Bug | Linkages affected | Status |
|---|---:|---|
| The regex stopped at the first accession in `SEE SERIAL PATENT NR X AND Y FOR FEE PATENT` patterns, silently dropping Y. On reissue-trust patents the first number is often the patent's own accession, so we ended up with self-references instead of real linkages. | ~3,970 | **Fixed in v2.** The regex now captures every digit-bearing token inside a `NR ... FOR FEE PATENT` clause, and uses `finditer` to catch multiple clauses per remarks string. |
| One BLM operator typed the source accession in the cross-reference instead of the target (Lizzie Dowd case). | 1 | **Fixed via parcel layer.** |
| Trust patents with empty remarks (e.g., Lizzie Dowd's other 1891 trust) had no signal to parse. | unknown thousands | **Fixed via parcel layer.** |

A `CHECK (trust_accession <> fee_accession)` constraint now prevents self-references at the database level. The loader filters them out before insert too.

### Schema and scripts

- **`sql/create_trust_fee_linkages_recovered.sql`** — table schema with UNIQUE + CHECK constraints
- **`scripts/parse_remarks_fee_refs.py`** — v2 regex pass; emits one row per (trust, fee_ref) pair so multi-fee patents produce multiple candidates
- **`scripts/validate_remarks_extractions.py`** — match candidates against the patent catalog (exact / normalized / fuzzy with edit-distance cap of 2)
- **`scripts/recover_linkages_by_parcel.py`** — parcel + allottee name matcher; writes `data/parcel_match_candidates.csv`
- **`scripts/load_trust_fee_linkages_recovered.py`** — batched loader (`execute_values`, 1,000 rows per round-trip); accepts `--csv` and `--source` flags so both layers use the same script; idempotent via `ON CONFLICT DO NOTHING`

Re-run order after any catalog changes: `parse_remarks_fee_refs.py --full` → `validate_remarks_extractions.py` → `load_trust_fee_linkages_recovered.py --truncate` → `recover_linkages_by_parcel.py` → `load_trust_fee_linkages_recovered.py --csv data/parcel_match_candidates.csv --source parcel_match_v1`.

See [`AI_AS_RESEARCH_PARTNER.md`](AI_AS_RESEARCH_PARTNER.md) for the discovery story.

## IATH Source Database Access (May 2026)

Direct PostgreSQL access to the IATH Rails database at `land-sales.iath.virginia.edu` was obtained in May 2026, providing the authoritative source data behind the legacy site at `land-sales.iath.virginia.edu`.

**Connection:**
```
psql "host=land-sales.iath.virginia.edu port=5432 user=cwm6w password=land-sales-access dbname=land-sales"
```

**Exported tables** (CSV, at `~/Desktop/iath_export/`):

| Table | Rows | Description |
|-------|-----:|-------------|
| `patents` | 285,870 | Full patent catalog (same data as local `rails_patents`) |
| `patent_persons` | 371,582 | Join table linking patents to people — has `patent_id`, `person_id`, `patent_role_id` |
| `people` | 316,776 | Patentee names with structured fields: `glo_last_name`, `glo_first_name`, `glo_middle_name` |
| `patent_roles` | 1 | Role lookup |
| `fedreg` | 35,686 | Federal Register claims (authoritative source for local `federal_register_claims`) |
| `fedreg_table_of_contents` | 215 | FR document structure |
| `tribes` | 255 | Tribe lookup |
| `authorities` | 21 | Patent authority types |
| `glo_tribes` | 1,412 | GLO tribe name variants |

Export script: `export_iath_tables.sh`. User has read-only access (`SELECT` on tables; no `pg_dump` due to sequence permissions).

### What this improves over the scrape

The May 2026 patentee name fix scraped `land-sales.iath.virginia.edu` to populate the `full_name` column on `rails_patents`. That was a workaround for missing data. The IATH database export supersedes the scrape in three ways:

1. **Structured name fields.** The `people` table has `glo_last_name`, `glo_first_name`, `glo_middle_name` as separate columns. The scrape produced a single concatenated `full_name` string (e.g., "CHARLES FISH; MARY FISH; ELJAH FISH"). Structured fields are better for name matching — `glo_last_name = 'BISSONETTE'` is more reliable than `full_name ILIKE '%bissonette%'`.

2. **Multi-patentee records preserved.** The `patent_persons` join table has 371,582 rows for 285,870 patents — some patents have multiple patentees, each with their own person ID, sequence number, and role. The scrape collapsed these into semicolon-separated strings. The join table preserves them as separate queryable rows, enabling network queries like "find every patent where Philip Points appears."

3. **Authoritative Federal Register data.** The `fedreg` table (35,686 rows) is the canonical source for forced fee claims. Our `federal_register_claims` table was imported separately and may have diverged. The IATH version is the authoritative copy maintained by the legacy site.

### Per-person name search (June 2026)

The IATH person tables are now loaded into `allotment_research` and drive patent name search. Schema and load script: `sql/create_iath_people_tables.sql`.

| Table | Rows | Role |
|---|---:|---|
| `people` | 316,776 | One row per patentee, with structured `glo_first_name` / `glo_last_name` / `glo_middle_name` |
| `patent_persons` | 371,582 | Links `patent_id` (→ `rails_patents.id`) to `person_id` (→ `people.id`); preserves multi-patentee structure |
| `patent_roles` | 1 | Role lookup (everyone is `patentee`) |

**Why it matters.** BLM's `full_name` mashes every allottee on a patent into one string (`MARY CARTER; WILLIAM CARTER; CALEB CARTER`), so the old fuzzy search (trigram on `full_name`) let a single common word carry a multi-word query: "rush roberts" returned **302** results because every `<x> ROBERTS` cleared the surname trigram alone. `patent_name_fuzzy_clauses()` in `app.py` now matches first and last name *separately, against the same person*, via an `EXISTS` over `patent_persons`/`people` (not a JOIN, so a patent with two matching people is counted once), OR'd with a `full_name ILIKE %query%` universal fallback. The per-person predicates use the `%` operator so the `gin_trgm_ops` indexes on the name columns are usable. Verified against the IATH source site: **rush roberts → 6, caleb carter → 2**.

Search-box parsing: one token matches first OR last; two tokens match first AND last; three or more take the first token as the given name and the rest joined as the surname.

**Deliberately deferred** — handled only by the `full_name ILIKE` fallback for now, *not* by structured matching: non-Western name order, particles (`van` / `de` / `la`), and bracketed/hyphenated surname clusters such as `VANDERVART` / `VANDERWART`. A search like "mary little bear" routes "little bear" to the surname field, which matches the hyphenated `LITTLE-BEAR` form well enough but is not guaranteed complete for every particle case.

**Still pending:**
- **Cloud SQL is not updated.** The load and code change are local only; production (Cloud SQL + Cloud Run) is unchanged pending review and an explicit deploy.
- The `all_patents` view still exposes the scraped `full_name`; the rewrite reaches the person tables through the query's `EXISTS`, not through a view change. A future view-level join is optional, not required.
- `fedreg` has not been compared against `federal_register_claims` for discrepancies.
- The residual ~340–380 ms query latency is the `all_patents` view materialization (two seq-scan/hash-join branches over the full corpus), a pre-existing cost independent of name search — a separate optional optimization, not addressed here.

## Forced Fee & Related Claims Filter (June 2026)

The patents page used to expose a "Forced Fee Only" filter that matched a single `claim_type` pattern — `ILIKE '%FORCED FEE%'`. That collapsed the historical question ("which allotments were taken from their owners under the General Allotment Act?") onto a single 1983 administrative label, and missed the allotments that the BIA enumerated under thematically equivalent but differently-named claim types.

The clearest case is the Ponca Agency. Of the 1,881 Ponca allotment patents in the database, **463 are fee patents** — yet under the old filter, *zero* showed as Forced Fee. The Ponca Agency (`B07813`) submitted only 18 claims to the 1983 Federal Register notices: 14 under `RECOVERY OF TRUST OR RESTRICTED LAND`, 4 under various trespass types, and **none** under any "forced fee" label. The legal mechanism the BIA used to recover Ponca land was procedurally different — but the underlying phenomenon (loss of trust title) is the same as a forced fee patent. Tonkawa and Quapaw show the same pattern at smaller scale.

As of June 2026, the patents-page filter is **Forced Fee & Related Claims**, spanning seven thematically-related FR `claim_type` buckets — all of which represent loss of trust title:

| Bucket (FR `claim_type` ILIKE) | Rows | What it captures |
|---|---:|---|
| `%FORCED FEE%` | 9,649 | Fee patents issued without the allottee's consent |
| `%SECRETARIAL TRANSFER%` | 1,327 | Trust land transferred by Secretary's order |
| `%UNAPPROVED%` | 980 | Unapproved restricted land sale (incl. `%WITHOUT APPROVAL%` variants) |
| `%TAX FORFEITURE%` | 688 | Restricted land forfeited for unpaid taxes |
| `%TAXATION%` | 1,057 | Wrongful taxation of trust/restricted land |
| `%RECOVERY%` | 935 | Claim for recovery of trust/restricted land — the Ponca bucket |
| `%LAND SOLD WITHOUT APPROVAL%` | 264 | (subset of UNAPPROVED, kept explicit for clarity) |

Trespass (ROW, road, agricultural, grazing, building, fence, etc.), welfare payments, timber wrongfully removed, old-age-assistance, allotment-never-issued, and questionable-cancellation claims are **not** in this set — they describe use of allotment land or unrelated administrative actions, not loss of trust title.

The expansion adds **172 net new patents** flagged corpus-wide vs. the strict forced-fee-only filter. The tribes most affected:

| Tribe | Patents gained |
|---|---:|
| Kickapoo | 52 |
| Pawnee | 47 |
| Ponca | 43 |
| Wichita | 13 |
| Otoe and Missouria | 7 |
| Tonkawa | 3 |
| (others) | 7 |

The strict forced-fee-only view remains available on the claims page (`/claims`) dropdown ("Forced Fee Patent (all variants)").

### Implementation

The seven `ILIKE` patterns live in `DISPOSSESSION_CLAIM_PATTERNS` (and the `OR`-joined `DISPOSSESSION_WHERE_SQL`) in `app.py`, used by:

- `api_patents` — the patent-type=forced filter and the `is_dispossession_claim` SELECT subquery returned as the JSON `dispossession_claim` field
- `api_patents_csv` — the CSV export's "Forced Fee & Related Claim" column
- `patent_detail` — the route that returns all linked FR claims (not just one, as before), with per-row `is_dispossession` booleans

On `/patent/<id>` the banner now distinguishes the two cases:

- **Dispossession claim** linked → `alert-warning` banner reading "linked to a Forced Fee & Related dispossession claim", with a "Dispossession" pill next to each qualifying claim type
- **Non-dispossession claim** linked (e.g. trespass, welfare) → `alert-info` banner noting the claim type isn't in the dispossession set, with the actual `claim_type` printed in italics

The Patent Details card header badge previously rendered from the BLM `forced_fee` transcribed flag — explicitly forbidden as a source of truth by the rule in `CLAUDE.md`. It now renders from the same FR-derived `is_dispossession_claim` value, so the badge, the column flag, and the filter are all driven by one source.

## GitHub

https://github.com/cwmmwc/federal-register-forced-fee
