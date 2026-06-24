# Archived scrape scripts (superseded)

These scripts built the Murray working tables by scraping the rendered HTML of the
IATH website (land-sales.iath.virginia.edu/...php). They are **retired**: the working
tables are now rebuilt directly from the authoritative `iath` raw-source schema by
`scripts/rebuild_murray_from_iath.py`. The HTML scrape was found to silently drop
footnote-annotated values (e.g. Hopi's 2,472,166 tribal acres). Kept here for history
only — do not run them as the data pipeline.

`map_murray_to_blm.py` is NOT archived — its `MURRAY_TO_BLM` dict is still the canonical
agency→BLM-tribe map, now imported by the rebuild script.

## Wilson scrapes (added 2026-06-24)
`scrape_wilson_t06.py`, `scrape_wilson_t08.py` — retired. Wilson working tables now rebuilt
from iath by `rebuild_wilson_table_vi.py` and `rebuild_wilson_annual_sales.py`. The scrape had
corrupted totals (e.g. Capitan Grande tribal 159,903,940 vs correct 19,930) and dropped 3
reservations + the wilson_t08 grand-total handling. `map_wilson_to_blm.py` is NOT archived.
