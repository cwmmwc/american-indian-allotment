# Indian Land Allotment Research

A Flask web application for researching the history of Indian allotment land dispossession — from the allotment era (1887–1934) through termination (1947–1957). Built at the [Institute for Advanced Technology in the Humanities](https://www.iath.virginia.edu/), University of Virginia, as part of the [Indian Land Allotment Research](https://land-sales.iath.virginia.edu/) project directed by Christian W. McMillen.

The site integrates four primary historical datasets — 285,870 BLM allotment patents, 10,976 Federal Register forced fee claims, the Wilson Report (1934), and the Murray Memorandum (1958) — into a searchable, cross-referenced research tool with an interactive allotment map and data visualizations.

## Site Structure

### Landing Page (`/`)
A splash page modeled after the [IATH main site](https://land-sales.iath.virginia.edu/), featuring full-width historical document images with clickable hotspots linking to high-resolution scans. Includes the Neda Laura Parker quote (Comanche, 1925) and links to the four primary datasets. Serves as the gateway to the research application.

### Research Home (`/home`)
Overview of the project's four datasets — BLM Patents, Federal Register Claims, the Wilson Report, and the Murray Memorandum — with summary statistics and navigation to all sections of the site.

### Allotment Map (`/map`)
Interactive Leaflet map displaying 239,845 allotment patents matched to Public Land Survey System (PLSS) parcels. Built on the Esri ArcGIS Feature Service. Features include:
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
Browse and search 285,870 BLM allotment patent records. Filter by name, tribe, state, patent type, date range, and map status (mappable vs. not mappable). Server-side pagination and CSV export. Each patent links to its detail page and, if mappable, directly to its parcel on the allotment map.

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

### About (`/about`)
Project background, methodology, data sources, and acknowledgments.

## The Data

### Federal Register Claims (1983)
In 1983, the Bureau of Indian Affairs published two Federal Register notices listing Indian allotment claims — documenting allotments where fee patents had been issued without the allottee's consent ("forced fee patents"), as well as secretarial transfers.

- **9,649** forced fee patent claims
- **1,327** secretarial transfers
- ~7,110 linked to BLM patent records; ~2,539 unlinked

**The Federal Register is the sole authoritative source for forced fee counts.** The BLM `forced_fee` flag inflates numbers through one-to-many patent matching and must not be used for this purpose.

### BLM Allotment Patents
**285,870** General Land Office patent records from the Bureau of Land Management, covering trust patents, fee patents, and other allotment-related patents across all tribes. Of these, **239,845** are matched to PLSS parcels and displayed on the interactive allotment map; the remaining **46,025** are searchable on the patents page but cannot be geocoded.

### Wilson Report (1934)
The Wilson Report documented the state of **212 Indian reservations** as of 1934, when the Indian Reorganization Act ended general allotment. Records original reservation areas, allotments made, and **23.2 million acres alienated** through sales and fee patents — the cumulative land loss of the allotment era.

### Murray Memorandum (1947–1957)
The Murray Memorandum documented a second wave of land loss during the termination era. Across **52 BIA agencies**, individual Indian trust land fell from **15.9 million acres (1947) to 12.6 million (1957)** — a net loss of 3.3 million acres through 18,546 trust removal transactions.

## Tech Stack

- **Backend**: Python 3, Flask, psycopg2
- **Database**: PostgreSQL (`allotment_research`)
- **Frontend**: Bootstrap 5, jQuery, DataTables
- **Map**: Leaflet.js, leaflet.heat, Esri ArcGIS Feature Service
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
| `trust_fee_linkages` | 29,229 | Trust-to-fee patent conversion records |
| `wilson_table_vi` | 212 | Wilson Report 1934 reservation baseline data |
| `wilson_annual_sales` | ~32 | Wilson Table VIII annual land sales 1903–1934 |
| `murray_comparative` | 52 | Murray Memorandum 1947 vs 1957 land by agency |
| `murray_transactions` | 520 | Murray trust removal transaction counts by agency and year |
| `murray_trust_removal` | 83 | Murray trust land removed by area office and year |
| `murray_agency_removal` | 41 | Murray total acres removed by agency |
| `murray_lands_acquired` | 23 | Federal lands acquired since 1930 |
| `parcels_patents_by_tribe` | 401,811 | PLSS legal land descriptions |

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

## GitHub

https://github.com/cwmmwc/federal-register-forced-fee
