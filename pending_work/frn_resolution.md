# FRN Resolution — State of Work

**Last updated**: 2026-06-01
**Working directory**: `~/projects/american-indian-allotment`
**Live app**: https://federal-register-app-996830241007.us-east1.run.app

This document captures the state of FRN-reduction work as of the date above
and the decisions still pending. Read this first when resuming the FRN
thread in a future session.

---

## 1. Conceptual model

FRN ("Further Research Needed") is a research-pending flag in the IATH tribe
crosswalk. It does NOT mean "no data." It means the historical name from
the BLM GLO record has been preserved, but the modern counterpart (or
asserted name) hasn't been determined.

Two distinct things are being tracked in our DB:

- **Historical preservation** — `rails_patents.glo_tribe_name` keeps what
  BLM wrote (INDIAN VALLEY, MONACHE, OTTER TAIL PILLAGER CHIPPEWA, etc.).
  Archival source data, never modified.
- **Modern-counterpart mapping** — `blm_allotment_patents.preferred_name`
  (resolved at IATH-crosswalk-build time) carries the contemporary name
  when one can be confidently asserted, FRN when the research question
  is still open.

### Working rule for relabeling (Christian's framing)

> Is there a coherent name we can attach to these records — historical or
> contemporary?

If yes, use it (possibly normalized, possibly with a modern referent like
DACOTAH → "Dacotah/Sioux Nation"). If no, FRN stays.

This is more permissive than "is there a modern federally-recognized
counterpart." It accepts coherent historical band names (OTTER TAIL
PILLAGER CHIPPEWA) and nation-level identifiers (Dacotah, Mono) without
requiring band-or-reservation-level resolution.

### A third axis: reservation known, tribe unknown

Some FRN records have a populated `preferred_reservation` (Warm Springs,
Wind River, Kiowa-Comanche-Apache). The reservation is known and asserted;
the specific tribe is genuinely uncertain because the reservation is
multi-tribal (Confederated Tribes of Warm Springs = Wasco + Walla
Walla/Tenino + Northern Paiute, etc.). The right move is to surface the
reservation in the UI while keeping the tribe flagged FRN — NOT to
relabel the tribe.

---

## 2. Current state (2026-06-01)

| metric | value |
|---|---|
| Total `all_patents` records | 286,442 |
| Records with specific tribe label | 221,763 |
| Records with NULL `preferred_name` | 54,042 |
| **FRN records remaining** | **9,999** |

Started this work at **10,637** FRN records. **638 have been resolved**
via the sibling-backfill mechanism (described below). The remaining 9,999
are distributed across several categories of pending decisions.

### Breakdown of the remaining 9,999

| n | category | next step |
|---|---|---|
| ~2,151 | reservation known, tribe genuinely FRN (Warm Springs / Wind River / KCA) | UI work: surface `preferred_reservation` |
| ~2,206 | named-modern-tribe GLO (SPOKANE, WALLA WALLA, WIND RIVER, UMPQUA, WALKER RIVER) | DACOTAH-style spreadsheet relabel decision |
| ~2,021 | named-historic-band (OTTER TAIL PILLAGER CHIPPEWA, BAD RIVER / LA POINTE variants, WHITE OAK POINT CHIPPEWA, WINNIBIGOSHISH variants) | spreadsheet relabel decision (preserve historical band term) |
| ~5,355 | nation-only (CHIPPEWA, MONO/MONACHE, residual SIOUX) | DACOTAH-style decision per cluster |
| ~700 | genuinely vague (INDIAN VALLEY, HAT CREEK, PALM SPRINGS, HUMBOLDT, SAN JOAQUIN, etc.) | stay FRN |

(Numbers approximate — some categorization calls are judgment-dependent.)

---

## 3. Mechanisms in place

Three resolution mechanisms are live in the codebase / DB. All are
**non-destructive**: source data (BLM tables, IATH crosswalk) is never
modified. Resolutions live in override layers and the `all_patents` view
COALESCEs them with documented precedence.

### Mechanism 1 — Document-class-level overrides (`document_class_metadata`)

A doc-class entry can declare a default tribe label that fires whenever
the otherwise-resolved `preferred_name` is FRN. Currently one row:

| doc_code | default_tribe_label |
|---|---|
| SS | Dacotah/Sioux Nation |

Built by `scripts/build_document_class_metadata.py`. Affects ~3,025 Sioux
Scrip Patents whose GLO was 'SIOUX'.

### Mechanism 2 — Per-record sibling backfill (`derived_tribe_labels`)

Per-accession overrides applied when a same-allotment + same-state
sibling record (often the trust patent) carries a specific tribe label
that the FRN record (often the fee patent) was missing because BLM's
GLO field dropped the band identification.

Schema:
```sql
CREATE TABLE derived_tribe_labels (
    accession_number       text PRIMARY KEY,
    derived_preferred_name text NOT NULL,
    source                 text NOT NULL,        -- 'sibling_backfill_v1'
    evidence_accession     text NOT NULL,        -- the sibling whose label we inherit
    name_similarity        numeric,
    parcel_match           boolean,
    tier                   text NOT NULL,        -- T1 / T2
    applied_at             timestamp DEFAULT now(),
    notes                  text
);
```

Built by `scripts/find_frn_backfill_candidates.py` (finds the candidate
pairs) and applied by `scripts/apply_sibling_backfill.py` (selects best
evidence per FRN record and inserts T1+T2 only). Current state: **638
rows** on local + Cloud SQL.

### Mechanism 3 — IATH spreadsheet (the canonical source)

`/Users/cwm6W/Library/CloudStorage/Box-Box/IATH/tribes/Tribes.xlsx` is
the human-curated source for `tribe_crosswalk`. Two columns matter for
this work:

- `Authoritative Tribe Name` — populated when the modern tribe can be
  asserted; "FRN" when not.
- `Authoritative Reservation Name` — populated when the reservation can
  be asserted independently of the tribe.

Editing this spreadsheet + running `scripts/build_tribe_crosswalk.py` +
propagating to `blm_allotment_patents.preferred_name` is how
"DACOTAH-style" cluster relabels happen.

### View precedence

`sql/update_all_patents_view_with_derived_tribe.sql` (applied to both
DBs on 2026-05-29). The `all_patents` view resolves `preferred_name` as:

```
COALESCE(
  derived_tribe_labels.derived_preferred_name,           -- per-record sibling backfill (highest)
  CASE WHEN base_preferred ILIKE 'Frn%' THEN
       document_class_metadata.default_tribe_label END,  -- doc-class default (only if otherwise FRN)
  base_preferred                                          -- IATH crosswalk value
)
```

Where `base_preferred` is `bap.preferred_name` for BLM-matched records
and `COALESCE(tnm.preferred_name, rp.glo_tribe_name)` for rails-only.

---

## 4. Done work (committed and deployed)

| date | commit | scope |
|---|---|---|
| 2026-05-28 | `b792ac3` | `document_class_metadata` + SS→Dacotah/Sioux Nation (3,025 records) |
| 2026-05-28 | `b792ac3` | DACOTAH-glo spreadsheet rows 325-327 → "Dacotah/Sioux Nation" (5 records: LaFramboise sisters MN MV + 3 SER) |
| 2026-05-28 | `78cc2fd` | pg_trgm fuzzy name search (search-time only — separate from FRN resolution but enables better catalog work) |
| 2026-05-28 | `2228eca` | DACOTAH spreadsheet update script (record-keeping) |
| 2026-05-29 | `9054ef9` | Sibling backfill apply: 638 FRN records resolved (T1+T2) |
| 2026-05-29 | `970a8e4` | SQL + CSV artifacts force-added (the view DDL and frozen candidate snapshots) |

All deployed to Cloud Run; DB changes applied to both local and Cloud
SQL.

### Distribution of the 638 sibling-backfill resolutions

| n | derived tribe label |
|---|---|
| 493 | White Earth Chippewa |
| 23 | Leech Lake Band of Ojibwe |
| 18 | Rosebud Sioux |
| 12 | Lower Brulé Sioux |
| 9 | Mille Lacs Band of Ojibwe |
| 9 | Gull Lake Band of Mississippi Chippewa |
| 9 | Shoshone |
| 7 | Turtle Mountain Band of Chippewa Indians |
| 7 | Arapaho |
| 6 | Fond du Lac Band of Lake Superior Chippewa |
| 5 | Manache |
| 4 | Agua Caliente Band of Cahuilla Indians |
| ~ | smaller clusters |

---

## 5. Held / waiting

### 5a. Sibling-backfill review queue

`data/frn_backfill_for_review.csv` — **174 pair-rows covering 147
distinct FRN records** that did not auto-apply because their evidence
fell below the T1+T2 threshold. Tier breakdown:

| tier | n records | description |
|---|---|---|
| T3 | 23 | low name-similarity (<0.7) + same parcel |
| T4 | 82 | exact name + DIFFERENT parcel (FALLIS / LAROCHE pattern — same person on a different parcel) |
| T5 | 41 | fuzzy name + different parcel |
| disagreement | 1 | siblings disagree on tribe label (WAY-O-ZHE-GWAN-ABE-E-QUAY — Mille Lacs vs White Earth) |

Walk these case-by-case. For T4 in particular, the question is whether
the trust patent on parcel A is good evidence for the tribe of the same
person's fee patent on parcel B (likely yes in most cases — they're the
same person on the same reservation — but you flagged this for human
judgment).

### 5b. UI work — surface `preferred_reservation`

**Scope agreed but not yet built.** Affects ~2,187 records where the
tribe is genuinely FRN but the reservation IS known (and explicitly
contains the word "reservation" in all cases — confirmed):

| n | reservation |
|---|---|
| 1,168 | Warm Springs Indian reservation |
| 934 | Wind River reservation |
| 85 | Kiowa, Comanche, and Apache Reservation |

What to build:
- Detail page (`templates/patent.html`): show "Reservation: Warm Springs
  Indian reservation" alongside "Tribe: Frn" when preferred_reservation
  is populated
- List view (`templates/patents.html`): show reservation as a small
  secondary line under "Frn" in the Tribe column
- Possibly a filter dropdown for reservation on the patents search page

Estimated effort: ~1 hour for detail + list view. Filter would add
another ~30 min.

---

## 6. Decisions pending — GLO cluster relabeling

The 7,701 records that aren't either (a) reservation-known-only or
(b) sibling-resolvable need a per-cluster DACOTAH-style decision.

### Clean coherent names (Christian's framing applies cleanly)

| n | GLO | candidate label | notes |
|---|---|---|---|
| 721 | SPOKANE | Spokane Tribe of Indians | modern federally-recognized |
| 509 | WALKER RIVER | Walker River Paiute Tribe (Nevada) | modern |
| 289 | WALLA WALLA | Confederated Tribes of the Umatilla Indian Reservation | modern |
| 213 | WIND RIVER (residual) | (use existing Wind River label) | confirm not double-mapping |
| 78 | UMPQUA | Cow Creek Band of Umpqua Tribe of Indians | modern |
| 72 | SPOKANE RESERVATION | (merge with #1 above) | likely same population |
| 32 | ROGUE RIVER | Confederated Tribes of the Grand Ronde / Siletz | could be either; needs decision |
| 28 | SHAWNEE | Eastern Shawnee Tribe of Oklahoma / Shawnee Tribe / Absentee-Shawnee | three modern successors |

### Named historic bands (preserve the historical name)

| n | GLO | candidate label | notes |
|---|---|---|---|
| 860 | OTTER TAIL PILLAGER CHIPPEWA | "Otter Tail Pillager Chippewa" (historical band name) | spreadsheet already notes this as research target |
| 290 | BAD RIVER OR LA POINTE | Bad River Band of Lake Superior Chippewa? | Lake Superior Chippewa identifier |
| 267 | WHITE OAK POINT CHIPPEWA | "White Oak Point Chippewa" (historical, succeeded by Leech Lake?) | spreadsheet notes this |
| 262 | LA POINTE OR BAD RIVER | (same as #2 — variant spelling) | merge |
| 141 | LAPOINTE OR BAD RIVER | (same as #2) | merge |
| 124 | WINNIBIGOSHISH | "Winnibigoshish Chippewa" or modern Leech Lake? | spreadsheet notes |
| 66 | WINNIBIGOSHISH RESERVATION | (merge with #6) | |
| 60 | WINNEBIGOSHISH | (variant spelling) | merge |

### Nation-only — the harder DACOTAH-style call

| n | GLO | candidate label | notes |
|---|---|---|---|
| 1,895 | CHIPPEWA | "Chippewa" / "Anishinaabe"? | too generic — many bands; risky to assert anything |
| 324 | CHIPPEWA RESERVATION | (same as #1) | also generic |
| 146 | MONO | "Mono" or "Western Mono" | multiple modern bands (Northfork, Cold Springs, Big Sandy, Dunlap) |
| 69 | MONACHE | (variant of #3) | |
| 31 | SIOUX (residual not in SS pool) | per-record decision | check whether SS doc-class override would help |

### Truly vague — stay FRN

| n | GLO | reason |
|---|---|---|
| 84 | INDIAN VALLEY | place name, multiple tribes historically |
| 71 | SONWAS OR FALL RIVER | location-only |
| 65 | HAT CREEK | location-only (could be Atsugewi but uncertain) |
| **58** | **PALM SPRINGS** | **explicitly held — see §8** |
| 37 | HUMBOLDT | location-only |
| 26 | SAN JOAQUIN | location-only |
| ~700 | residual long tail (200+ distinct GLO strings, 1-10 records each) | mixed: cryptic, person-names, single-word geography |

---

## 7. Catalog of manually-verified cases (research-quality examples)

These are the records Christian reviewed by PDF or by Cloud Run app
inspection during the session. They illustrate the pattern types.

### Trust specific → fee FRN (the dominant pattern, all on Lower Brulé Reservation, SD Lyman County)

All resolved via sibling backfill except as noted.

| name | allot | structure | status |
|---|---|---|---|
| MARY RENCOUNTRE | 410 | 1903 STA Lower Brulé Sioux + 1907 MV Frn | T1 — resolved |
| JOSEPH FALLIS | 59 | 1903 STA × 2 + 1907 MV trust + 1908 MV fee (cross-parcel) | T4 — in review CSV |
| LEON DESHEUQUETTE | 176 | 1904 STA + 1908 MV (1903 STA misspelled DESHENQUETTE) | T1 — resolved |
| ALEXANDER RENCOUNTRE | 392 | 1903 STA + 1908 MV | T1 — resolved |
| APEYOHA-TAHKA | 473 | 1903 STA (spelled TANKA) + 1908 MV (spelled TAHKA) | T2 — resolved via fuzzy match |
| WILLIAM SMITH | 505 | 1903 STA + 1908 MV | T1 — resolved |
| OLD-MAN-BEAR; MATO-WICARCA | 337 | 1903 STA (name order reversed) + 1908 MV | T1 — resolved (sibling found via fuzzy name match) |
| CHARLEY FORKED-BUTTE; PAHAJATA | 230 | 1903 STA + 1911 SER | T1 — resolved |
| WILLIAM FORKED-BUTTE; PAHAJATA | 236 | 1903 STA (spelled PAHA JATA) + 1911 SER (PAHAJATA) | T2 — resolved |
| P L. LAROCHE | 43 | 1903 STA × 2 + 1911 SER (same parcel) + 1908 SER (different parcel) | T1 same-parcel resolved; T4 cross-parcel in review |
| PHILIP ROSS | 812 | 1896 STA Crow Creek Sioux + 1908 MV Frn (spelled PHILLIP) | T2 — resolved |

### Reversed direction (rare, trust FRN → fee specific)

| name | allot | structure | status |
|---|---|---|---|
| BLACK-RAINBOW; WIGMUKE-SAPA | 6 | 1899 STA Frn + 1930 SER Santee Sioux (BEN FULWIDER added as primary) | NOT auto-caught — name structure change pushed similarity below threshold (0.519 vs 0.65 cutoff). Needs manual entry if you want it resolved. |

### Single-record FRN-with-rich-BLM-data (no sibling)

| name | acc | what's there |
|---|---|---|
| CHARLES LEONARD; CHARLES LENORIS | 0537-046 | BLM glo='MONACHE'. Sibling acc 1119890 (CHARLES LENORIS) → Manache. T2 — resolved. Same broader pattern affects 192 Mono/Monache records. |

### Single-day administrative batches (where BLM lost band identification uniformly)

- **1908-05-21 MV batch** (Lower Brulé): 6 records sequentially numbered
  `0776-348` through `0776-361`. Five resolved via sibling backfill; one
  (OLD-MAN-BEAR) needed fuzzy match.
- **1911-10-26 SER batch** (Lower Brulé): 3 records. All three resolved
  via sibling backfill.

These batch patterns are useful for future cluster identification:
sequentially-numbered fee patents on a single day are often the
trust→fee conversion event for a reservation. If we find more, the
sibling-backfill mechanism handles them automatically.

---

## 8. Open threads / parked decisions

### Palm Springs — held

64 records still show `Frn PALM SPRINGS` (compound legacy label).
Surrounding evidence (CA Riverside County, 1957–1960, Cahuilla family
names like Patencio/Saubel/Andreas/Welmas) strongly suggests Agua
Caliente Band of Cahuilla Indians. The 346 sibling records in this
geography already carry the Agua Caliente label.

**Christian's decision (2026-05-29): "keep as is, too many moving
pieces."** Records include some corporate buyers (FOUNTAIN ESTATES INC,
DON JA RAN CONSTRUCTION CO, PALM SPRINGS WATER COMPANY) which complicate
the relabeling logic — these are land transactions involving non-Indian
buyers, and FRN preserves epistemic caution.

To revisit: would need both spreadsheet relabel (PALM SPRINGS → Agua
Caliente Band Of Cahuilla Indians) and a downstream review of the
corporate-buyer records.

### 70 Sioux-FRN PDFs

We downloaded 70 PDFs of non-SS Sioux-FRN records in SD/NE/KS/MT.
Vision extraction probe on 5 records confirmed the recital text just
says "Sioux" with no band identification — so the PDFs themselves
don't help resolve these to specific bands.

Downloaded PDFs: `blm_pdfs/` (the 70 are a subset of ~9,200 there now).
Inventory CSV: `data/sioux_non_ss_frn_candidates.csv`.
Probe results: `data/sioux_recital_probe.json`.

Vision extraction work was paused after the probe. Not currently
expected to resume — the recital text doesn't carry the signal we'd
need.

### Reservation-only display

Build deferred per §5b. When built, will improve the visible
informativeness of 2,187 records without changing any tribe data.

---

## 9. Reference index

### Files committed

| path | purpose |
|---|---|
| `scripts/build_document_class_metadata.py` | Builds the doc-class override table (SS → Dacotah/Sioux Nation) |
| `scripts/update_dacotah_tribe_label.py` | One-shot spreadsheet edit for DACOTAH-glo rows |
| `scripts/find_frn_backfill_candidates.py` | Generates `data/frn_backfill_candidates.csv` from same-allotment+state sibling matching |
| `scripts/apply_sibling_backfill.py` | Applies T1+T2 rows from candidates CSV into `derived_tribe_labels` |
| `sql/update_all_patents_view_with_derived_tribe.sql` | View DDL with derived-tribe override layer |
| `sql/update_all_patents_view_with_tribe_override.sql` | Earlier view version (DACOTAH doc-class only) |
| `data/frn_backfill_candidates.csv` | Frozen snapshot of 891 candidate pairs (2026-05-29) |
| `data/frn_backfill_for_review.csv` | 174 rows for the 147 T3/T4/T5 + disagreement records |

### Files not committed (artifacts, can regenerate)

| path | purpose |
|---|---|
| `data/sioux_non_ss_frn_candidates.csv` | The 70 SD/NE/KS/MT records (+ 2 LaFramboise) |
| `data/sioux_recital_probe.csv` | 5-record probe sample |
| `data/sioux_recital_probe.json` | Vision extraction probe results |

### Tables (local + Cloud SQL)

| table | role |
|---|---|
| `rails_patents` | full patent catalog from Rails admin, includes `glo_tribe_name` (canonical historical name) |
| `blm_allotment_patents` | BLM mirror with mappable patents only, includes `preferred_name` and `preferred_reservation` (resolved at import) |
| `tribe_crosswalk` | rebuilt from IATH Tribes.xlsx by `build_tribe_crosswalk.py` |
| `tribe_name_map` | older lookup, used in the rails-only arm of the view |
| `document_class_metadata` | doc-class → default tribe label overrides |
| `derived_tribe_labels` | per-accession sibling-backfill overrides |
| `all_patents` (view) | unified read API with all overrides COALESCEd in precedence order |

### Key URLs

- Live app: https://federal-register-app-996830241007.us-east1.run.app
- Sample resolved case (LEON DESHEUQUETTE):
  https://federal-register-app-996830241007.us-east1.run.app/patents?name=leon&allotment=176
- IATH spreadsheet (Box-synced):
  `/Users/cwm6W/Library/CloudStorage/Box-Box/IATH/tribes/Tribes.xlsx`

---

## 10. How to resume

Pick from these depending on energy and intent:

### Smallest tractable next step
Walk through `data/frn_backfill_for_review.csv` (147 records, mostly
cross-parcel cases). For each, decide: inherit the sibling label or
stay FRN. Add accepted ones to `derived_tribe_labels` (using
`apply_sibling_backfill.py` as a template — extend it to read an
"approved" subset).

### Highest-impact single move
Build the UI work for `preferred_reservation` surfacing (§5b). Affects
2,187 records, no spreadsheet decisions needed, ~1 hour of work.

### Highest-leverage decision-driven work
Pick a clean-coherent-name cluster from §6 (SPOKANE, WALLA WALLA,
WALKER RIVER, OTTER TAIL PILLAGER CHIPPEWA are the biggest single
clusters with the least controversy) and do a DACOTAH-style
spreadsheet relabel:
1. Edit Tribes.xlsx for the relevant rows
2. Run `build_tribe_crosswalk.py` against local + Cloud SQL
3. Update `blm_allotment_patents.preferred_name` for affected records
   (small SQL UPDATE, see the DACOTAH precedent in earlier session)
4. Commit + push

### Cluster-by-cluster cleanup mode
Work through §6 top-down. Each cluster is ~5–15 min of focused work
once the call is made. The decisions are research judgments, not data
problems.

### To remember between sessions

- Christian's auto-memory has `project_allotment_research_db.md` and
  `project_allotment_open_threads.md` — both should be consulted when
  resuming any allotment work.
- The discipline of FRN is real: when in doubt, FRN stays. Don't
  reach for "looks plausible" when the evidence isn't there.
- Display-layer fixes are not the same as research resolutions —
  don't conflate "surface what we already know" with "we resolved this
  case."
