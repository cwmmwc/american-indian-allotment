#!/bin/bash
#SBATCH -A LawData
#SBATCH --time=2-00:00:00
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=8
#SBATCH --gres=gpu:a100:1
#SBATCH --constraint=a100_80gb
#SBATCH --partition=gpu
#SBATCH --mem=80G
#SBATCH -J "gemma-blm-50"
#SBATCH -o /project/LawData/blm-extraction/logs/gemma_blm_%j.out
#SBATCH -e /project/LawData/blm-extraction/logs/gemma_blm_%j.err
#SBATCH --mail-type=BEGIN,END,FAIL
#SBATCH --mail-user=cwm6w@virginia.edu

# Gemma 3 27B vision extraction on the 50-PDF BLM benchmark.
#
# Patterns borrowed from extraction-pipeline/hpc/start_qwen_vl_server.slurm:
#   - Loren's vLLM container
#   - vLLM server in the background, client in the foreground
#   - Single SLURM job does start-server + wait-ready + run-client + shutdown
#
# Outputs annotation_v5_gemma_50.json next to the benchmark CSV.

set -euo pipefail

# ─── Paths ──────────────────────────────────────────────────────────────────
PROJECT_DIR="/project/LawData/blm-extraction"
CSV="${PROJECT_DIR}/blm_benchmark_50.csv"
PDF_DIR="${PROJECT_DIR}/blm_pdfs"
OUT_JSON="${PROJECT_DIR}/annotation_v5_gemma_50.json"
EXTRACT_SCRIPT="${PROJECT_DIR}/scripts/extract_annotations_gemma_vision.py"

VLLM_SIF="/project/LawData/models/container/vllm_0.14.1-cu130.sif"
MODEL_PATH="/project/LawData/models/gemma-3-27b-it"
MODEL_SERVED_NAME="gemma-3-27b-it"
VLLM_PORT=8000

mkdir -p "${PROJECT_DIR}/logs"

# ─── Modules ────────────────────────────────────────────────────────────────
# Keep the environment minimal for the apptainer/vLLM server launch — host
# Python modules pollute LD_LIBRARY_PATH and break CUDA inside the container.
# The Python module is loaded later, after the server is up, only for the
# client invocation.
module purge
module load apptainer

mkdir -p /scratch/$USER/fakehome/.cache/{huggingface,vllm,flashinfer,triton}

echo "═══════════════════════════════════════════════"
echo "Gemma 3 27B BLM benchmark"
echo "Model path:        ${MODEL_PATH}"
echo "Served model name: ${MODEL_SERVED_NAME}"
echo "Container:         ${VLLM_SIF}"
echo "GPUs:              1x A100 80GB"
echo "Node:              $(hostname)"
echo "Job ID:            ${SLURM_JOB_ID}"
echo "Port:              ${VLLM_PORT}"
echo "CSV:               ${CSV}"
echo "Out:               ${OUT_JSON}"
echo "═══════════════════════════════════════════════"

# ─── Start vLLM server in the background ────────────────────────────────────
echo "Starting vLLM server (background)..."
apptainer exec --nv \
    --bind /project/LawData:/project/LawData \
    --bind /scratch/$USER/fakehome:/root \
    "${VLLM_SIF}" \
    python3 -m vllm.entrypoints.openai.api_server \
        --model "${MODEL_PATH}" \
        --served-model-name "${MODEL_SERVED_NAME}" \
        --port "${VLLM_PORT}" \
        --gpu-memory-utilization 0.92 \
        --tensor-parallel-size 1 \
        --max-model-len 8192 \
    > "${PROJECT_DIR}/logs/vllm_server_${SLURM_JOB_ID}.out" 2>&1 &

VLLM_PID=$!
echo "vLLM PID: ${VLLM_PID}"

# Ensure we tear it down on exit, even on failure.
trap "echo 'Stopping vLLM server (pid ${VLLM_PID})'; kill ${VLLM_PID} 2>/dev/null || true" EXIT

# ─── Wait for server to be ready ────────────────────────────────────────────
echo "Waiting for vLLM /health (timeout 15 min)..."
for i in $(seq 1 90); do
    if curl -s "http://localhost:${VLLM_PORT}/health" > /dev/null 2>&1; then
        echo "vLLM ready after ${i} × 10s = $((i*10)) seconds."
        break
    fi
    sleep 10
    if [ $i -eq 90 ]; then
        echo "vLLM did not come up within 15 minutes. Aborting."
        cat "${PROJECT_DIR}/logs/vllm_server_${SLURM_JOB_ID}.out" | tail -50
        exit 1
    fi
done

# ─── Load Python modules ONLY for the client (after server is up) ──────────
# Doing this here, not at the top of the script, so the apptainer-launched
# vLLM server gets a clean environment for its bundled CUDA stack. The host
# Python with pip-install --user'd pymupdf is only needed by the client.
echo ""
echo "Loading Python module for the client..."
module load gcc/11.4.0 openmpi/4.1.4 python/3.11.4

# ─── Run the extractor ──────────────────────────────────────────────────────
echo ""
echo "Running extraction client on ${CSV}..."
echo ""

cd "${PROJECT_DIR}"

# Query the server to see what model name it is actually serving under, since
# --served-model-name behavior varies across vLLM versions. Use whatever name
# the server reports rather than guessing.
SERVED_NAME=$(curl -s "http://localhost:${VLLM_PORT}/v1/models" \
              | python3 -c 'import sys, json; print(json.load(sys.stdin)["data"][0]["id"])')
echo "vLLM is serving model under name: ${SERVED_NAME}"

VLLM_URL="http://localhost:${VLLM_PORT}/v1" \
GEMMA_MODEL="${SERVED_NAME}" \
DPI=150 \
python3 "${EXTRACT_SCRIPT}" "${CSV}" "${PDF_DIR}" "${OUT_JSON}"

echo ""
echo "═══════════════════════════════════════════════"
echo "Extraction done. Output at ${OUT_JSON}"
echo "═══════════════════════════════════════════════"
