# 11 PDFs where Gemma says fee_patent_issued=true and Sonnet says false

These are the 11 *trust-class* (or unspecified-authority) patents from the 50-PDF Sonnet vs. Gemma benchmark where the two models disagreed on whether there is a fee-conversion stamp in the middle of the page. The other 9 disagreement patents are excluded because their `authority` field says they ARE themselves fee patents, which means by definition they cannot carry a 'Fee Patent Issued' conversion stamp — those 9 are almost certainly Gemma false positives, not worth your verification time.

For each of these 11, open the PDF and look at the **middle of the page** (between the printed land description and the printed 'NOW KNOW YE...' paragraph). The question to answer is binary:

- **Is there a 'Fee Patent Issued' (or 'Fee Pat. Issued') stamp/label/note in the middle of the page?**

If YES, Gemma found a real fee conversion that the database does not have a separate record for — a genuine hidden conversion (the original research question).

If NO, Gemma fabricated the stamp — consistent with the demonstrated `49611` hallucination on the top-left field.

Neither model is automatically right. The PDF is the only arbiter.

| Accession | Date | State | Authority | Sonnet | Gemma | Sonnet raw top-left | Patentee |
|---|---|---|---|---|---|---|---|
| `297305` | 1912-10-21 | MS | (not specified) | no stamp | STAMP | `CHOCTAW SCRIP.` |  |
| `815041` | 1921-07-22 | AZ | (not specified) | no stamp | STAMP | `969266 | 67183 | 1038` |  |
| `843353` | 1922-01-16 | NM | (not specified) | no stamp | STAMP | `Santa Fe 042524` |  |
| `920481` | 1923-10-12 | AZ | (not specified) | no stamp | STAMP | `Phoenix 055334 | 4-1063-R` |  |
| `976646` | 1926-03-25 | NM | Indian Trust Patent | no stamp | STAMP | `Santa Fe 011018` |  |
| `999292` | 1927-03-30 | NM | Indian Trust Patent | no stamp | STAMP | `Santa Fe 022396` |  |
| `1060548` | 1933-01-03 | SD | Indian Reissue Trust | no stamp | STAMP | `1475749 | 49187-32. I. O. | 5840-A.` | ROBERT HORSE; BROOKS HORSE |
| `1075343` | 1935-04-15 | NM | Indian Homestead Trust | no stamp | STAMP | `Santa Fe 058934.` |  |
| `1088244` | 1937-01-29 | ND | Indian Partition | no stamp | STAMP | `1668492 | 84251 I. O. | 1664 and 1074-A.` | GERTRUDE BURR; WOMAN-IN-THE-WATER; GERTRUDE BAD-GUN |
| `1089053` | 1938-07-19 | AZ | (not specified) | no stamp | STAMP | `1672211 | 11817  I. O. | 473` |  |
| `1112961` | 1942-01-26 | NM | (not specified) | no stamp | STAMP | `Santa Fe 011610` |  |

## How to score the results

After looking at all 11 PDFs, the counts that matter for the production-model decision:

- **How many of the 11 have an actual fee stamp?** That number is the count of hidden conversions Gemma found that Sonnet missed.
- **How many have no stamp?** That number is the count of Gemma hallucinations.

If the hidden-conversion count is meaningful (say 3+ of 11), Gemma is finding real research data Sonnet misses, and Gemma's over-eagerness is a useful trait at the cost of a verification pass. If most of them have no stamp, Sonnet's more conservative read is the better production choice.
