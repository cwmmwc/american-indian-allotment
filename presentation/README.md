# How AI Reads Government Forms — Presentation

A fifteen-slide walkthrough of the vision-extraction part of the allotment-research
project, written to be shared with someone curious about whether AI tools could
be useful in their own work. Built with [Reveal.js](https://revealjs.com/) — a
single HTML page you open in a browser, no build step.

## Opening it

```bash
open presentation/index.html
```

or just double-click `index.html`. Reveal.js loads from a CDN. Arrow keys to
navigate, `Esc` for the overview, `?` for keybindings.

## What's in the deck

| # | Slide | Visual asset |
|---|-------|--------------|
| 1 | Title | none |
| 2 | The research (includes trust/fee context) | none |
| 3 | The database | none |
| 4 | What a patent looks like (Bridget Silk, 1910) | `img/full_patent_bridget_silk.png` ✓ |
| 5 | Annotation region 1 — top-left CCF file reference | `img/topleft_ccf_reference.png` ✓ |
| 6 | Annotation region 2 — middle-page fee patent stamp | `img/middle_fee_stamp.png` ✓ |
| 7 | The scale problem | none |
| 8 | How the AI reads a form (prompt + output) | none |
| 9 | The model is general; the pipeline isn't (concept) | none |
| 10 | Why we are on v4 (the prompt-refinement table) | none |
| 11 | An API is a contract (concept) | none |
| 12 | The two API calls per patent (pipeline + numbers) | none |
| 13 | Lizzie Dowd, recovered | none |
| 14 | The honest takeaway | none |
| 15 | How to start | none |

All three images are committed to `img/`. They were rendered from PDFs in
`blm_pdfs/` using `pdftoppm`; see "Reproducing the images" below if you ever
want to regenerate or replace them.

## What patents were used

| Image | Source PDF | Patent | Why |
|-------|-----------|--------|-----|
| `full_patent_bridget_silk.png` | `blm_pdfs/100449.pdf` | Bridget Silk, Standing Rock Sioux, Indian Trust Patent, 1-6-1910 | Clean printed-form patent with all the labelable parts visible — name, date, legal description, authority — and a clear top-left CCF block so slides 3 and 4 use the same document. |
| `topleft_ccf_reference.png` | `blm_pdfs/100449.pdf` (same) | (crop) | Shows three stacked references — `87941-09`, `91014-09 I.O.`, and `3569` — including one explicitly labeled "I.O." (Indian Office). A textbook example of the upper-left form block. |
| `middle_fee_stamp.png` | `blm_pdfs/5515.pdf` | Tipiwastewin, or Good House Woman, Crow Creek Sioux, Indian Reissue Trust 1908 → Fee Patent 2-14-1960 | The "FEE PATENT ISSUED" stamp is clean and complete (Misc. Letter No., Patent No., Date). The trust-to-fee gap of 52 years is itself a striking historical fact — long after the original 25-year trust period would have expired. |

The slide text refers to the patents by name and number so anyone reading
the deck can pull the originals from BLM and verify.

## Reproducing the images

The current images were rendered using `pdftoppm` (from Poppler — installed
via Homebrew). To regenerate from the existing PDFs:

```bash
# Full page of Bridget Silk (slide 3) — 200 dpi
pdftoppm -r 200 -singlefile -png \
    blm_pdfs/100449.pdf presentation/img/full_patent_bridget_silk

# Top-left crop of Bridget Silk (slide 4) — 300 dpi, top-left 1300×550 px
pdftoppm -r 300 -x 0 -y 50 -W 1300 -H 550 -singlefile -png \
    blm_pdfs/100449.pdf presentation/img/topleft_ccf_reference

# Middle fee stamp on Good House Woman (slide 5) — 300 dpi, x=200 y=1300 W=1400 H=500
pdftoppm -r 300 -x 200 -y 1300 -W 1400 -H 500 -singlefile -png \
    blm_pdfs/5515.pdf presentation/img/middle_fee_stamp
```

To use different source patents, replace the input PDF and adjust the `-x -y
-W -H` flags for the crop region. The `-x -y -W -H` numbers are in pixels at
the rendered resolution.

To do this in **Preview** instead of `pdftoppm`: open the PDF in Preview,
use the selection tool to drag a rectangle, ⌘C to copy, ⌘N for a new image
from the clipboard, then `File → Export…` as PNG with the filename above.

## Tone

This deck is for a non-academic, non-technical reader. It uses "I" / "my,"
keeps jargon to a minimum, and treats the AI as a tool rather than a
mystery. Edit the prose freely if your friend would respond better to a
slightly different voice. The CSS (`styles.css`) keeps the visual register
restrained: serif type, no animations, no transitions.

## Editing

Each `<section>` is one slide. Speaker notes have been stripped — this deck
is meant to be clicked through and read on its own, not presented. To add
notes back, wrap them in `<aside class="notes">` blocks inside a section.
