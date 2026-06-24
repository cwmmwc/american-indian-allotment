# IATH source-table consolidation (Murray & Wilson) — recap & open decision

**Status:** decision made (Option A). Raw `iath` research layer LOADED. Next step is the
`public` working-table rebuild.
**Started:** 2026-06-16. **Recap:** 2026-06-22. **Layer loaded:** 2026-06-22.

## Decision (2026-06-22): Option A — keep a raw research layer

Loaded the 15 Murray/Wilson source tables verbatim into a dedicated **`iath` schema** in
`allotment_research` (`scripts/load_iath_source_tables.sh`, streams straight from IATH; types
from the IATH catalog; idempotent). Verified: numeric columns aggregate, footnotes join by
`table_name`, and `public` is untouched (the six live pages still run on the old scrape).
`iath` is **local-only** — not pushed to Cloud SQL. See the `iath` schema section in
`DATABASE.md`.

**Still pending:** rebuild the `public` `murray_*`/`wilson_*` working tables *from* `iath` so
they carry full detail, add the never-captured tables (disposal mechanism, public takings,
Wilson state acreage) as new working tables/pages, keep the BLM-tribe join, then retire the
scrape scripts. The pages then get rebuilt on the complete data.

### First derived table built — trust-exit mechanisms (2026-06-22)

`public.murray_trust_exit_mechanisms` (194 rows) is built from `iath.murray_p081_87_t12`
(Table XII) by `scripts/build_trust_exit_mechanisms.py`. Historian-agreed taxonomy (2026-06-22):
fee patent / removal of restrictions / certificates of competency are **separate** families;
inheritance/heirship is **set apart** from dispossession (`set_apart=TRUE`). Carries the
per-agency reconciliation gap (the raw columns don't cleanly partition the total — 30/52
reconcile). Verified: 52 agencies, 33 BLM-mapped, dispossession 17,774 vs inheritance 564.
Documented in `DATABASE.md` (`iath` section).

**Page built (2026-06-22):** `/murray/mechanisms` ("How Land Left Trust", in the Visualizations
nav). Route `murray_mechanisms` in `app.py`; template `templates/murray_mechanisms.html`. Shows
the overall dispossession-mechanism ranking, inheritance set apart in its own panel, a
per-agency drill-down (keyed on agency — all 52, incl. multi-tribe agencies like Five Civilized
Tribes that don't map to one tribe; tribe cross-link where mapped), and the data caveats
(agency-reported synonyms, the per-agency reconciliation gap, the zero-disposal agencies).
Verified via Flask test client (200, all sections render). Not yet seen in a real browser /
not yet pushed to Cloud SQL.

### Wilson state page built (2026-06-23)

`/wilson/states` ("Indian Land by State (1934)", in the Visualizations nav). Route
`wilson_states` in `app.py`; template `templates/wilson_states.html`. Built two working tables
via `sql/build_wilson_state_tables.sql`: `public.wilson_land_loss_by_state` (Table VII) and
`public.wilson_ownership_1934_by_state` (Table V). The page leads with a **Leaflet US
choropleth** (states shaded by tribal acres removed / share removed / allotted-alienated, metric
toggle; hover shows full per-state breakdown), then per-state stacked bars for the deduction arc
(ceded/surplus/miscellaneous) and the 1934 ownership composition. New static asset:
`static/data/us-states.geojson` (87 KB, vendored from PublicaMundi MappingAPI). Leaflet 1.9.4 is
loaded on this page only (via `{% block head %}`), not in `base.html`. Verified via test client
(page 200; geojson 200 through basic auth). Not yet seen in a browser / not pushed to Cloud SQL.

### Murray working tables rebuilt from iath (2026-06-24)

All five scraped Murray working tables now rebuilt from the `iath` raw layer by
`scripts/rebuild_murray_from_iath.py` (reuses `MURRAY_TO_BLM`; verifies each against the
old scrape before swapping). The Murray scrape scripts (`scrape_murray_tables.py`,
`scrape_murray_t14.py`) are **retired** to `scripts/archive/`. `map_murray_to_blm.py` stays
(its dict is imported by the rebuild).

What changed vs the scrape (iath is authoritative):
- `murray_trust_removal`, `murray_agency_removal` — byte-identical, just re-sourced.
- `murray_comparative` — **restored 4 `tribal_acres_1947` values the scrape silently dropped**
  (footnote-annotated cells the position-parser missed): Hopi 2,472,166 · San Carlos 1,622,484 ·
  Uintah and Ouray 983,010.83 · Western Washington 29,552. These now show on `/murray` etc.
- `murray_transactions` — counts identical (scrape's `0` = iath `NULL`, COALESCEd to 0); 5
  agencies adopt iath's canonical names (Fort Belknap consolidated, Hoopa area field office,
  Quapaw area field office, Riverside area field office, Turtle Mountain consolidated) — BLM
  links preserved.
- `murray_lands_acquired` — keeps the 4 zero-acquisition rows (San Carlos, Riverside, Mescalero,
  Shawnee) the scrape had; values re-sourced from iath.

Verified: `/murray`, `/wilson`, `/patents/timeline`, `/murray/mechanisms`, `/wilson/states` all
render 200 after the swap.

### Wilson working tables rebuilt from iath (2026-06-24) — CONSOLIDATION COMPLETE

`wilson_annual_sales` (`rebuild_wilson_annual_sales.py`) — re-sourced from iath.wilson_t08,
dropping the grand-total row (sales_year=0) so page sums don't double-count; the only data diff
was a mis-parsed 1903 tract count (iath authoritative).

`wilson_table_vi` (`rebuild_wilson_table_vi.py`) — re-sourced from iath.wilson_t06. The composite
`reservation_name` reconstructs exactly from agency+reservation (verified: all 212 reproduce);
BLM links carried over by that key (deduped to avoid fan-out on the 5 duplicate names like
Northern Navajo×3). Restored 3 dropped reservations (Sacramento/Round Valley, Tomah/Winnebago,
Walker River/Scattered Indians) and **corrected corrupted HTML-parse totals**: Mission/Capitan
Grande tribal 159,903,940→19,930, Mission/Campo 1,493,560→14,995, Fort Apache govt 230,327→2,330,
Coeur d'Alene/Kalispel govt 409→49, and date "16 1894"→"1894". Remaining total diffs were all
benign 0-vs-NULL. All pages render 200.

**All IATH-website scrape scripts retired to `scripts/archive/`.** The iath→public consolidation
is done. (`scrape_blm_volume.py` stays — it scrapes BLM, not the IATH site.)

- (Deprioritized) public takings (`iath.murray_p046_48_t17_25`) — the one iath table with no
  working-table/page yet.
- **Production push** — `scripts/push_new_tables_to_cloudsql.sh` is ready; run it `gcloud`-authed
  to load `murray_trust_exit_mechanisms`, `wilson_land_loss_by_state`,
  `wilson_ownership_1934_by_state` into Cloud SQL, then `git push origin main` to deploy. NOTE:
  the 5 rebuilt Murray tables also changed locally (esp. the Hopi correction) — those need pushing
  to Cloud SQL too if production should reflect them.
- **Collaborator access** — `scripts/grant_collaborator_access.sh` + `scripts/grant_readonly.sql`
  ready (read-only, Google IAM); fill in the collaborator email and run `gcloud`-authed.

## How this started

The goal was to make sure we have a complete copy of every table in the upstream IATH
`land-sales` PostgreSQL database (`land-sales.iath.virginia.edu`, owner `land-sales`, 38
tables). That database is the original Rails-admin data store for the project; our local
`allotment_research` DB and the Flask app were built from pieces of it.

## What we did

1. **Exported the IATH database.** Rewrote `export_iath_tables.sh` to enumerate *all* public
   tables dynamically (instead of a hardcoded list of 9) and dump each to CSV in
   `~/Desktop/iath_export/`. Result: **36 of 38 tables** exported.
   - 2 refused by the read-only `cwm6w` user: `genders` (4-row lookup, target of
     `people.gender_id`) and `users` (empty anyway). Getting `genders` would need a
     `GRANT SELECT` on the IATH side.
   - These CSVs are a **transport snapshot only** — disposable once the real data is loaded.
     They are not a permanent home for anything.

2. **Inventoried local vs. source** (full verdict below). Most large tables are already in
   `allotment_research` in working form. The genuinely new material is small.

3. **Investigated the Murray/Wilson tables specifically** (see below) — this is where the
   real issue surfaced and where we paused.

## Redundancy verdict (36 exported CSVs vs. local `allotment_research`)

- **Already loaded, identical or local superset — ignore:** `patents` (⊂ `rails_patents`,
  286,442 rows), `people`, `patent_persons`, `patent_roles` (all loaded 2026-06-16).
- **Content already present in a reshaped local table:** `fedreg` → `federal_register_claims`;
  `parcels` + `parcel_patents` → `parcels_patents_by_tribe`; `parcel_points` → centroids in
  `blm_allotment_patents` (100% accession overlap, verified); the `murray_*`/`wilson_*`
  source tables → the scraped reshapes (the subject of this doc).
- **Genuinely new, no local equivalent:** IATH `tribes` (255 rows — *different* from local
  `tribes` (908); has `alternate_names`, `agency_id`), `fedreg_table_of_contents`,
  `glo_tribes`, `glo_county_lookups`, `authorities`, `public_lands`/`public_land_categories`,
  `groups`/`group_categories`, and Rails plumbing (`admin_users`, `schema_migrations`, etc.,
  no research value).

## The Murray/Wilson finding (the crux)

**What they are.** Two historical government documents on Indian land loss — the Murray
Memorandum (1947–57 trust-land disposal) and the Wilson Report (1934 reservation baseline,
1903–34 sales). The IATH DB holds clean, structured transcriptions of their tables.

**What our app has.** Local `murray_*`/`wilson_*` tables built by **scraping the rendered
HTML** of the IATH website (`land-sales.iath.virginia.edu/...php`) with a position-based
parser (`scripts/scrape_murray_tables.py`, `scrape_wilson_t06.py`, `scrape_murray_t14.py`,
etc.), then mapped to BLM tribe names (`map_murray_to_blm.py`, `map_wilson_to_blm.py`).
But those PHP pages are just a front-end for the **same database we now have direct access
to.** So the reshapes are a *partial, lossy hand-scrape of data that already exists cleanly
in the source.*

**Are the scrapes wrong?** No — accurate but incomplete. Spot-check: scraped
`murray_comparative` vs. authoritative source `murray_p100_112_q1_2_3` = 52 vs 52 rows,
identical keys, **zero value differences.** The problem is coverage, not correctness:
- **Whole tables never captured:** `murray_p081_87_t12` (the ~40-way breakdown of *how* land
  left trust status — fee patents, competency certificates, partition, public takings,
  escheat — the most analytically valuable table), `murray_p046_48_t17_25` (public takings
  vs. sales to tribe), `wilson_t05` and `wilson_t07` (state-level original tribal acreage and
  the deductions from it).
- **Columns dropped:** agency-level year detail in trust-removal (local has only
  area-office × year); the ceded / surplus-opened / miscellaneous 3-way land-loss split in
  Wilson Table VI (collapsed to one `total_reductions` column); all footnotes.

## What the Murray/Wilson data powers right now (6 live pages)

All linked in the main **Visualizations** dropdown (`templates/base.html`):

| Page / route | Tables read |
|---|---|
| `/wilson` ("1934 Reservation Baseline") + `/api/wilson` | `wilson_table_vi`, `murray_comparative`, `murray_transactions` |
| `/murray` ("Murray Memorandum") | `murray_comparative`, `murray_transactions`, `murray_agency_removal` |
| `/patents/timeline` ("All Patents Timeline") | `murray_trust_removal`, `wilson_annual_sales` |
| `/dubois` ("Du Bois Data Portraits") | `wilson_annual_sales` |
| `/tribe/<slug>` detail | `wilson_table_vi`, `murray_comparative`, `murray_transactions`, `murray_agency_removal` |
| `/sankey` | references present |

Every consumer reads the **aggregated, BLM-tribe-mapped** columns of the reshapes. Nothing in
the app touches the source detail the scrape dropped. So loading the source changes none of
the existing pages — it only enables *new* analysis. These pages have not been worked on in
months and are acknowledged as preliminary; the partial data is part of why.

## The problem in one sentence

We maintain a parallel data lineage (a partial HTML scrape) standing in for data that already
exists, complete and clean, in a database we now have direct access to.

## Recommended resolution (single source of truth)

1. Make the **IATH database the single source of truth**, reached by the reproducible
   `export_iath_tables.sh` pipeline. No more hand-scraping.
2. **Rebuild the Murray/Wilson working tables from that source — completely** — restoring the
   dropped detail (agency × year, the 3-way land-loss split, footnotes) and adding the tables
   the scrape never captured (disposal *mechanism* breakdown, public takings, Wilson state
   acreage). Keep the BLM-tribe-name join, layered on top of the authoritative source rather
   than baked into a scrape.
3. **Retire the scrape scripts** as the pipeline (keep as historical artifacts if desired).

This collapses three overlapping things into one lineage: *authoritative source → derived
working tables the app reads.* No parallel copies to keep in sync.

## DECISION — RESOLVED 2026-06-22: Option A (raw research layer, loaded)

Do we also want the **raw transcriptions queryable in the database as a research layer** — the
full source tables with footnotes, for doing history rather than driving a viz — **or only the
clean derived working tables**, with the raw kept solely as a regenerable export?

- **Raw research layer + working tables:** more useful to Christian as a historian; adds a
  clearly-labeled source layer (candidate: a dedicated `iath` schema so the app's `public`
  working tables never query it by accident).
- **Working tables only:** leanest possible schema; raw stays a regenerable CSV export.

Either way the scrape goes away and there is a single source of truth. Production note: any
new/rebuilt tables eventually need to reach Cloud SQL, not just local.

## Concrete current state (as of pause)

- `~/Desktop/iath_export/` — 36 CSVs (transport snapshot).
- `export_iath_tables.sh` — rewritten to dump all public tables dynamically (committed to
  working tree; not a feature, just the export helper).
- `scripts/load_iath_source_tables.sh` — rewritten to stream straight from IATH into the
  **`iath` schema** (no CSV intermediate) and **run successfully** on 2026-06-22; all 15
  source tables loaded.
- `allotment_research` Postgres — gained the `iath` schema (15 tables). `public` is unchanged;
  the original scraped `murray_*`/`wilson_*` working tables and the live pages still run as
  before. The rebuild that replaces them is the next step.
