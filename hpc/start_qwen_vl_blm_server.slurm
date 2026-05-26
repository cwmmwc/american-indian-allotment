#!/bin/bash
#SBATCH -A LawData
#SBATCH --time=2-00:00:00
#SBATCH --nodes=1
#SBATCH --ntasks-per-node=1
#SBATCH --cpus-per-task=16
#SBATCH --gres=gpu:a100:4
#SBATCH --constraint=a100_80gb
#SBATCH --partition=gpu
#SBATCH --mem=120G
#SBATCH -J "qwen-vl-blm-server"
#SBATCH -o /project/LawData/blm-extraction/logs/qwen_vl_blm_%j.out
#SBATCH -e /project/LawData/blm-extraction/logs/qwen_vl_blm_%j.err
#SBATCH --mail-type=BEGIN,END,FAIL
#SBATCH --mail-user=cwm6w@virginia.edu

# Qwen2.5-VL-72B vLLM Server for BLM patent extraction.
# Transcribed line-for-line from extraction-pipeline/hpc/start_qwen_vl_server.slurm
# (Loren's proven config, validated on 760K NARA cards). The only changes are
# the log directory, the address-file path, and the job name; everything else
# (container, model path, apptainer flags, vllm serve invocation) is identical
# to the working production version.
set -euo pipefail

MODEL_PATH="/project/LawData/models/qwen2.5-vl-72b"
VLLM_PORT=8000

VLLM_SIF="/project/LawData/models/container/vllm_0.14.1-cu130.sif"

module purge
module load apptainer

mkdir -p /scratch/$USER/fakehome/.cache/{huggingface,vllm,flashinfer,triton}
mkdir -p /project/LawData/blm-extraction/logs

echo "═══════════════════════════════════════════════"
echo "Qwen2.5-VL-72B vLLM Server (BLM benchmark)"
echo "Model:    ${MODEL_PATH}"
echo "Container: ${VLLM_SIF}"
echo "GPUs:     4x A100 80GB"
echo "Node:     $(hostname)"
echo "Job ID:   ${SLURM_JOB_ID}"
echo "Port:     ${VLLM_PORT}"
echo "═══════════════════════════════════════════════"

echo "$(hostname):${VLLM_PORT}" > /project/LawData/blm-extraction/logs/qwen_vl_blm_address.txt
echo "Server address written"

apptainer exec --nv \
    --no-home \
    --bind /project/LawData:/project/LawData \
    --bind /scratch/$USER:/scratch/$USER \
    --bind /scratch/$USER/fakehome:/home/$USER \
    --env HOME=/home/$USER \
    --env XDG_CACHE_HOME=/home/$USER/.cache \
    --env HF_HOME=/home/$USER/.cache/huggingface \
    --env VLLM_DO_NOT_TRACK=1 \
    "$VLLM_SIF" \
    vllm serve "$MODEL_PATH" \
        --served-model-name qwen-vl-72b \
        --tensor-parallel-size 4 \
        --dtype auto \
        --host 0.0.0.0 \
        --port "$VLLM_PORT"
