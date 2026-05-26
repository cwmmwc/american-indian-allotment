#!/bin/bash
#SBATCH -A LawData
#SBATCH --time=02:00:00
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=4
#SBATCH --partition=standard
#SBATCH --mem=16G
#SBATCH -J "qwen-blm-cand-hid"
#SBATCH -o /project/LawData/blm-extraction/logs/qwen_blm_cand_hid_%j.out
#SBATCH -e /project/LawData/blm-extraction/logs/qwen_blm_cand_hid_%j.err
#SBATCH --mail-type=BEGIN,END,FAIL
#SBATCH --mail-user=cwm6w@virginia.edu

# Qwen2.5-VL-72B client for the Sonnet-candidate-hidden cross-check.
#
# Transcribed line-for-line from hpc/run_qwen_blm_benchmark.slurm
# (the proven 50-PDF benchmark client). Differences:
#   - reads candidate_hidden/qwen_input.csv  (the ~200 Sonnet candidates)
#   - reads PDFs from   candidate_hidden/pdfs/
#   - writes output to  candidate_hidden/qwen_output.json
#   - job name reflects the cross-check purpose
#
# Requires the qwen-vl-blm-server SLURM job to be running and to have
# written its address to /project/LawData/blm-extraction/logs/qwen_vl_blm_address.txt
# (the same server SLURM script used for the 50-PDF benchmark; no changes
# needed there).

set -euo pipefail

module purge
module load gcc/11.4.0 openmpi/4.1.4 python/3.11.4
source /scratch/$USER/model-compare-venv/bin/activate

ADDR_FILE="/project/LawData/blm-extraction/logs/qwen_vl_blm_address.txt"

# Wait up to 30 minutes for server to be reachable
for i in $(seq 1 180); do
    if [ -f "$ADDR_FILE" ]; then
        ADDR=$(cat "$ADDR_FILE" | tr -d '\n')
        if curl -s --max-time 5 "http://${ADDR}/health" > /dev/null 2>&1; then
            echo "Qwen-VL server ready at ${ADDR}"
            break
        fi
    fi
    if [ "$i" -eq 180 ]; then
        echo "ERROR: Server not ready after 30 minutes"
        exit 1
    fi
    if [ $((i % 30)) -eq 0 ]; then
        echo "  Waiting for server... ($((i * 10 / 60)) min)"
    fi
    sleep 10
done

# ── Paths ──────────────────────────────────────────────────────────────────
PROJECT_DIR="/project/LawData/blm-extraction"
CSV="${PROJECT_DIR}/candidate_hidden/qwen_input.csv"
PDF_DIR="${PROJECT_DIR}/candidate_hidden/pdfs"
OUT_JSON="${PROJECT_DIR}/candidate_hidden/qwen_output.json"
CLIENT="${PROJECT_DIR}/scripts/extract_annotations_qwen_vision.py"

echo "═══════════════════════════════════════════════"
echo "Qwen-VL Candidate-Hidden Cross-Check (v5 prompt)"
echo "Server: ${ADDR}"
echo "CSV:    ${CSV}"
echo "PDFs:   ${PDF_DIR}"
echo "Out:    ${OUT_JSON}"
echo "═══════════════════════════════════════════════"

VLLM_URL="http://${ADDR}/v1" \
PARALLEL=6 \
python3 "${CLIENT}" "${CSV}" "${PDF_DIR}" "${OUT_JSON}"
