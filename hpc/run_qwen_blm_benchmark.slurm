#!/bin/bash
#SBATCH -A LawData
#SBATCH --time=02:00:00
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=4
#SBATCH --partition=standard
#SBATCH --mem=16G
#SBATCH -J "qwen-blm-50"
#SBATCH -o /project/LawData/blm-extraction/logs/qwen_blm_client_%j.out
#SBATCH -e /project/LawData/blm-extraction/logs/qwen_blm_client_%j.err
#SBATCH --mail-type=BEGIN,END,FAIL
#SBATCH --mail-user=cwm6w@virginia.edu

# BLM patent 50-PDF Qwen2.5-VL-72B benchmark client.
#
# Transcribed from extraction-pipeline/hpc/run_qwen_vl_full_index_cards.slurm
# (Loren's proven client pattern). Differences from that original:
#   - reads the BLM-specific address file (qwen_vl_blm_address.txt)
#   - invokes our CSV-driven extract_annotations_qwen_vision.py client
#     instead of the NARA index-card client
#   - walltime is 2 hours (the 50-PDF benchmark is fast); use longer for
#     production runs
#
# Requires the qwen-vl-blm-server SLURM job to be running and to have
# written its address to /project/LawData/blm-extraction/logs/qwen_vl_blm_address.txt

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
CSV="${PROJECT_DIR}/blm_benchmark_50.csv"
PDF_DIR="${PROJECT_DIR}/blm_pdfs"
OUT_JSON="${PROJECT_DIR}/annotation_v5_qwen_50.json"
CLIENT="${PROJECT_DIR}/scripts/extract_annotations_qwen_vision.py"

echo "═══════════════════════════════════════════════"
echo "Qwen-VL BLM Benchmark Extraction (50 PDFs, v5 prompt)"
echo "Server: ${ADDR}"
echo "CSV:    ${CSV}"
echo "PDFs:   ${PDF_DIR}"
echo "Out:    ${OUT_JSON}"
echo "═══════════════════════════════════════════════"

VLLM_URL="http://${ADDR}/v1" \
PARALLEL=6 \
python3 "${CLIENT}" "${CSV}" "${PDF_DIR}" "${OUT_JSON}"
