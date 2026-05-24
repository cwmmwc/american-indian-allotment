# Opus vs. Sonnet — 6 disagreement cases from the 300-PDF benchmark

These are six patents from `blm_benchmark_300.csv` where Opus and Sonnet
extracted different values. The point of this folder is to let you, as the
researcher, look at each page and decide for yourself which extraction (if
either) matches what is on it. The PDF is the only ground truth here. The
filename of each PDF describes the *kind* of disagreement, not who is right.

| Patent | What to look at | Opus | Sonnet |
|---|---|---|---|
| **352410** | Top-left of the form. Note `4-1063-R.` is a printed form code in the header. | empty refs | `[1063]` |
| **1064487** | Top-left CCF reference, third digit. | `49611` | `49511` |
| **331690** | Top-left CCF reference, fourth digit. | `73347` | `73344` |
| **366509** | Middle-page fee patent stamp. Two numbers: a 5-digit value and a 7-digit value. | L=`22118` N=`1123473` | L=`1123473` N=`22118` |
| **192294** | Middle-page Misc. Letter No., third digit. | `62754` | `62254` |
| **480768** | Middle-page Patent No., trailing digit. | `544270` | `54420` |

## How to use this folder

Open each PDF and look at the region named in the filename. For each
disagreement, decide:

1. **Which reading (if either) matches the page?** Sometimes one model has it,
   sometimes the other, sometimes neither. Your reading is the arbiter.
2. **Is this disagreement of a kind that the prompt could fix?** Some are pure
   vision-reading (handwritten digit OCR). Some are structural (what counts as
   a CCF reference, which label maps to which JSON field). The latter category
   is what the v5 prompt revision targets.

## What the script reported, restated honestly

Across the 300-PDF sample, Opus and Sonnet agreed on the top-left letter
numbers in 89.9% of cases and on the fee-patent-issued bool in 99.7% of cases,
but agreed on the fee patent number in only 35.6% of cases where both said a
fee was issued. The 38 fee-number disagreements (and the 27 letter-number
disagreements) are listed in full by `scripts/compare_opus_vs_sonnet_300.py`.

That a model agrees with itself often or disagrees with another model often
does not, by itself, tell us which model is *correct*. It only tells us the
shape of the disagreement. The accuracy question requires looking at the
pages.

## Notes on patterns in the disagreements

These are *patterns* visible in the side-by-side outputs, not claims about
which model is right:

- Sonnet extracted the string `1063` as a top-left CCF reference on five
  different patents in the 300-PDF sample. All five use the same printed form
  template, which carries `4-1063-R.` in its header. Whether `1063` belongs in
  the CCF references list is a structural question about how the schema is
  defined, not a question about what is on the page.
- On the fee patent stamp (when both models said a fee was issued), there are
  cases where Opus and Sonnet have the *same two numbers* but placed them in
  opposite fields (`fee_letter_number` vs. `fee_patent_number`). Both models
  read the same page in those cases; they disagreed about which JSON field
  each value belongs in. This is also a structural question.
- The other disagreements involve single-digit differences in handwritten
  numbers (e.g. `49611` vs. `49511`, `73347` vs. `73344`). These are vision
  questions and have to be settled by reading the page.

The full list of disagreements is in the script output.
