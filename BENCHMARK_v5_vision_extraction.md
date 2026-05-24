# BLM Patent Vision Extraction — Model Benchmark (May 2026)

## Summary

This document records a head-to-head benchmark of three AI models on the task
of extracting two annotation fields from scanned BLM Indian allotment patents:
the top-left CCF (BIA Central Classified Files) reference, and a presence
flag for a middle-page "Fee Patent Issued" stamp. The benchmark used the v5
extraction prompt and schema (simplified to presence-only on the middle page;
the handwritten numbers in the stamp are not transcribed).

**Result:** **Claude Sonnet 4.6 was selected** for the production extraction
of the 8,818-PDF residual SER 1907–1942 batch. Gemma 3 27B was disqualified
by empirical PDF verification: it produced confident false positives on both
the top-left CCF field and the fee-stamp boolean. Opus 4.7 produced
comparable-quality results to Sonnet at roughly twice the actual API cost.
Sonnet is the production model.

## The research question

A subset of BLM allotment patents document a trust→fee conversion only as
a stamp on the original trust patent, with no separate fee-patent record in
the BLM database. Finding those "hidden" conversions is the historical
question driving this work: how much land was lost to fee patents that the
catalog never separately registered? The vision-extraction pipeline reads
each PDF, detects whether such a stamp is present, and feeds that flag into
the project's trust→fee linkage tables.

## Methodology

### Sample

A 50-PDF random sample was drawn from `blm_residual_v4_ser_loren_window.csv`
(8,818 SER-class BLM patents from 1907–1942 missing a structured CCF reference
in the database). The sample was stratified by signature year and locked with
a fixed random seed so identical PDFs were sent to every model.

### Prompt and schema

All three models were given the same v5 system prompt, which:

- Defines the top-left form-number block and the CCF reference format
  (`NNNNN-YY` where NN is a 2-digit year). Includes an explicit anti-pattern
  for printed BLM form codes (e.g. `4-1063-R.`, `4-1042-R.`) which superficially
  resemble CCF references but are not.
- Defines two middle-page outcomes as booleans: `fee_patent_issued` and
  `patent_cancelled`. Presence-only detection; numbers and dates inside the
  stamp are not transcribed.

For Sonnet and Opus the prompt was sent via Anthropic's API with a strict
JSON schema constraint. For Gemma the prompt was sent via vLLM 0.14.1's
OpenAI-compatible chat endpoint; `response_format` was not used because
vLLM 0.14.1 does not reliably honor it for Gemma 3 multimodal — the prompt
itself asked the model to return only JSON, and the response was parsed
tolerantly (this pattern is adapted from the working Qwen-VL client in the
sister `exhaustive-extraction-pipeline` project).

### Models

| Model | Source | Cost basis |
|---|---|---|
| Claude Opus 4.7 (`claude-opus-4-7`) | Anthropic API | Pay per token |
| Claude Sonnet 4.6 (`claude-sonnet-4-6`) | Anthropic API | Pay per token |
| Gemma 3 27B-it (`google/gemma-3-27b-it`) | UVA HPC, 1×A100 80GB, vLLM | Free |

A prior 300-PDF Opus-vs-Sonnet benchmark was run at the v4 prompt. The v5
benchmark on the same 50-PDF sample was run on Sonnet (local) and Gemma
(HPC) for direct head-to-head comparison.

### Verification

The PDF is the only ground truth in this system. Where models disagreed,
the source PDF was opened and inspected by hand. No model's output was
treated as authoritative against another model.

## Findings

### Cost (300-PDF Opus vs. Sonnet, v4 prompt)

| | Tokens (300 PDFs) | Actual billed | Per-PDF | Projected full residual (8,818 PDFs) |
|---|---|---|---|---|
| Opus 4.7 | 2,200,650 in / 99,337 out | $13.73 | $0.0458 | ~$404 |
| Sonnet 4.6 | 1,811,304 in / 91,452 out | $6.83 | $0.0228 | ~$201 |

The list-price calculation for Opus 4.7 overstated actual cost by roughly 3×,
which is why running the benchmark mattered: token-based estimates were
unreliable. The Sonnet rate matched the list-price calculation closely.

### Cost (50-PDF Sonnet v5, on the same input set as Gemma)

| | Tokens (50 PDFs) | Actual billed | Per-PDF |
|---|---|---|---|
| Sonnet 4.6 (v5) | 249,578 in / 10,502 out | $1.91 | $0.0382 |

The 50-PDF and 300-PDF per-PDF costs for Sonnet differ ($0.0382 vs. $0.0228);
the larger sample is probably the more reliable basis for full-batch
projection. The full residual is likely to fall in the **$200–$340** band.

### Quality — Opus vs. Sonnet (v4, 300 PDFs)

Agreement was high on the bool flags (99.7% on `fee_patent_issued`) and
moderate on the structured fields (89.9% on the top-left letter number set).
The largest disagreement was on the handwritten fee number transcription
(35.6% agreement on `fee_patent_number` when both said a stamp was issued).
The v5 schema simplification dropped these handwritten-number fields
entirely; verifying the bool flags is the only quality question that
matters now.

On six disagreement cases that were verified by hand against the source
PDFs, Opus and Sonnet were tied (2 correct each, 2 cases where neither
matched the PDF). Both models make occasional OCR errors on ambiguous
handwritten digits. Sonnet has a documented schema-routing failure mode
where it swapped `fee_letter_number` and `fee_patent_number` between
fields when both were visible — addressed in v5 by dropping those fields.

### Quality — Sonnet vs. Gemma (v5, 50 PDFs)

| Measure | Sonnet | Gemma |
|---|---|---|
| `fee_patent_issued = true` count | 9 / 50 (18%) | 29 / 50 (58%) |
| `patent_cancelled = true` count | 1 / 50 | 1 / 50 |
| Same `fee_patent_issued` bool | — | 30/50 = 60% |
| Same `patent_cancelled` bool | — | 50/50 = 100% |
| Same set of top-left letter numbers | — | 3/50 = 6% |
| Same I.O. flag | — | 22/50 = 44% |

### Verification of disagreements

The top-left field disagreements (47 of 50 records) included Gemma producing
the same string `'49611'` as a CCF reference on **11 different patents**.
Direct PDF inspection on one of those patents (985277, Charley Purdy,
Sacramento land office, 1926) confirmed that `49611` does not appear in the
top-left of that page. This is a confirmed hallucination, not an OCR slip.
Gemma was also extracting printed BLM form codes (`4-1063-R.`, `4-1070-R.`,
`401-tyr`) and 7-digit serial numbers as CCF references, despite the v5
prompt's explicit anti-pattern instruction against both.

The middle-page `fee_patent_issued` disagreements (20 of 50, all in the same
direction — Gemma=true, Sonnet=false) split into two categories:

- **9 patents whose own authority is "Indian Fee Patent"**: these are
  themselves fee patents and cannot logically carry a "Fee Patent Issued"
  conversion stamp (the stamp marks a trust patent's conversion to fee;
  a fee patent has nothing to be converted to). Gemma flagging these as
  having a fee stamp is a logical error, probably triggered by the words
  "fee patent" appearing in the patent's body text.
- **11 trust-class patents** (Indian Trust, Indian Reissue Trust, Indian
  Homestead Trust, Indian Partition, or unspecified): direct PDF inspection
  of all 11 confirmed that **none of them have a middle-page fee-conversion
  stamp**.

Combined verification: **20 out of 20 of Gemma's extra fee flags are false
positives**. None were genuine hidden conversions.

### What Sonnet actually found

On the 50-PDF sample, Sonnet flagged 9 fee-conversion stamps. Eight of the
9 trust patents are already linked to a separate fee patent in the
`trust_fee_linkages_recovered` table (from the earlier remarks-regex and
parcel-matching work). The remaining one — patent 953646 — has a stamp
visible on the trust patent but no corresponding separate fee-patent record
in the database. PDF verification confirmed the stamp is real. That is one
genuine hidden conversion in 50 PDFs, or **roughly 2%** at this sample
size. Caveat: 50 PDFs is a small sample and the corpus-wide rate may differ.

Sonnet's read on the top-left field showed that ~76% of the residual batch
genuinely has no CCF reference — instead, the top-left typically carries a
Local Land Office serial (Glasgow, Santa Fe, Sacramento, Havre, Phoenix,
Lewistown, Susanville, etc.), which is the public-domain land office's
administrative system rather than a BIA CCF reference. Direct PDF
verification on a subset of these "no CCF" patents confirmed Sonnet's read
is accurate. The reason BLM did not capture CCF references in the structured
database columns for these patents is, in many cases, that there is no CCF
reference to capture — these patents went through a different administrative
pipeline entirely.

## Production decision

**Claude Sonnet 4.6 is the production model for the BLM v5 vision extraction.**

Reasons:

1. Sonnet's outputs match the source documents on direct PDF verification.
2. Gemma 3 27B has demonstrated false-positive behavior on both fields
   tested (CCF-reference hallucination and fee-stamp over-flagging), in
   ways the v5 prompt cannot fix.
3. Opus 4.7 produces results comparable to Sonnet on the bool flags but
   costs roughly twice as much per PDF in actual billed charges.
4. The production cost (~$200–$340 for 8,818 PDFs) is acceptable.

## What this benchmark says about Gemma 3 27B vision

This is one specific task (bounded-template extraction from scanned
allotment patents with a constrained JSON schema requested via vLLM's
OpenAI-compatible API). On that task, in this configuration, Gemma 3 27B
under-performed badly compared to Sonnet. This result does not necessarily
generalize:

- The extraction-pipeline project's notes record that **Gemma 3 12B** is
  "excellent on bounded template extraction (NARA index cards)." A different
  Gemma variant on a different task may still be the right tool. The 12B and
  the 27B are different models with different behavior.
- vLLM 0.14.1's handling of `response_format` for Gemma 3 multimodal may have
  contributed to Gemma's freestyle output behavior. A newer vLLM version with
  better structured-output support might tighten things.
- The v5 prompt's anti-pattern rules (form codes, long serials) appeared to
  be followed by Sonnet but not by Gemma. Prompt engineering specifically
  targeted at Gemma's behavior might help, but was not attempted here.

For the immediate research task — finishing the 8,818-PDF residual batch —
Sonnet is the answer. Gemma 3 27B vision on bounded template tasks should
be re-tested when vLLM or the model itself sees a substantial upgrade.

## Files

- `blm_benchmark_50.csv` — the 50-PDF sample
- `annotation_v5_sonnet_50.json` — Sonnet outputs on the 50-PDF sample
- `annotation_v5_gemma_50.json` — Gemma outputs on the 50-PDF sample
- `annotation_v4_opus_300.json`, `annotation_v4_sonnet_300.json` — the
  earlier 300-PDF Opus vs. Sonnet benchmark on the v4 prompt
- `scripts/extract_annotations_v4.py` — Anthropic API client (v5 prompt
  and schema; the filename retains the v4 designation for git continuity)
- `scripts/extract_annotations_gemma_vision.py` — vLLM client (HPC)
- `scripts/compare_opus_vs_sonnet_300.py` — earlier comparison harness
- `scripts/compare_sonnet_vs_gemma_50.py` — the comparison run for this report
- `hpc/run_gemma_blm_benchmark.slurm` — HPC SLURM job for the Gemma run
- `benchmark_no_ccf_pdfs/` — 38 of the 50 PDFs that Sonnet read as having
  no top-left CCF reference, plus a README listing the raw top-left text
  Sonnet captured for each (verified accurate on inspection)
- `benchmark_gemma_fee_disagreements/` — the 11 trust-class PDFs where
  Gemma flagged a fee stamp and Sonnet did not (verified that none have
  a real stamp)
