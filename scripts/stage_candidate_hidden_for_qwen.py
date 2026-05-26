"""
Stage the candidate-hidden-conversion PDFs and Qwen-client input CSV for HPC.

Reads data/vision_v5_sonnet_candidate_hidden.csv (Sonnet's candidate hidden
conversions, produced by extract_vision_v5_candidate_hidden.py), and produces:

  data/candidate_hidden/qwen_input.csv  — minimal CSV with the columns
      the Qwen client reads (accession_number, full_name, signature_date,
      state, county, authority).

  data/candidate_hidden/pdfs/<accession>.pdf  — copies of the 207 PDFs
      from blm_pdfs/, so the upload to HPC is one self-contained subdir.

Usage:
    ./venv/bin/python3 scripts/stage_candidate_hidden_for_qwen.py
"""
import csv
import os
import shutil
import sys

IN_CSV   = "data/vision_v5_sonnet_candidate_hidden.csv"
OUT_DIR  = "data/candidate_hidden"
OUT_CSV  = os.path.join(OUT_DIR, "qwen_input.csv")
OUT_PDFS = os.path.join(OUT_DIR, "pdfs")
PDF_SRC  = "blm_pdfs"


def main():
    if not os.path.exists(IN_CSV):
        sys.exit(f"missing {IN_CSV} — run extract_vision_v5_candidate_hidden.py first")
    if not os.path.isdir(PDF_SRC):
        sys.exit(f"missing {PDF_SRC}/ — PDFs not staged locally")

    os.makedirs(OUT_PDFS, exist_ok=True)

    n_pdf_ok, n_pdf_missing = 0, 0
    missing = []
    with open(IN_CSV) as f, open(OUT_CSV, "w", newline="") as g:
        reader = csv.DictReader(f)
        writer = csv.writer(g)
        writer.writerow([
            "accession_number", "full_name", "signature_date",
            "state", "county", "authority",
        ])
        for row in reader:
            acc = row["accession_number"]
            writer.writerow([
                acc,
                row.get("full_name") or "",
                row.get("signature_date") or "",
                row.get("state") or "",
                row.get("county") or "",
                row.get("authority") or "",
            ])
            src = os.path.join(PDF_SRC, f"{acc}.pdf")
            dst = os.path.join(OUT_PDFS, f"{acc}.pdf")
            if os.path.exists(src):
                if not os.path.exists(dst):
                    shutil.copy2(src, dst)
                n_pdf_ok += 1
            else:
                missing.append(acc)
                n_pdf_missing += 1

    print(f"wrote Qwen input CSV: {OUT_CSV}")
    print(f"staged PDFs:          {n_pdf_ok} in {OUT_PDFS}/")
    if n_pdf_missing:
        print(f"  WARNING: {n_pdf_missing} PDFs not found in {PDF_SRC}/:")
        for acc in missing[:10]:
            print(f"    {acc}")
        if len(missing) > 10:
            print(f"    ... and {len(missing) - 10} more")


if __name__ == "__main__":
    main()
