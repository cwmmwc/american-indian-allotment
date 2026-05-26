#!/bin/bash
# Push the Sonnet-candidate-hidden CSV + PDFs + SLURM client to HPC for
# the Qwen-VL cross-check. Run this in your own terminal (it will prompt
# for HPC credentials).
#
# Prerequisite: ./venv/bin/python3 scripts/stage_candidate_hidden_for_qwen.py
# (creates data/candidate_hidden/ locally)
set -e

LOCAL_DIR=~/projects/american-indian-allotment
HPC_USER=cwm6w
HPC_HOST=login.hpc.virginia.edu
HPC_DIR=/project/LawData/blm-extraction

# 1. Push the candidate_hidden/ subdir (CSV + PDFs)
rsync -av \
    "${LOCAL_DIR}/data/candidate_hidden/" \
    "${HPC_USER}@${HPC_HOST}:${HPC_DIR}/candidate_hidden/"

# 2. Push the new SLURM client (server SLURM was already pushed for the
#    50-PDF benchmark and is reused unchanged)
rsync -av \
    "${LOCAL_DIR}/hpc/run_qwen_candidate_hidden.slurm" \
    "${HPC_USER}@${HPC_HOST}:${HPC_DIR}/hpc/run_qwen_candidate_hidden.slurm"

echo
echo "Pushed. Next steps on HPC (in your own terminal):"
echo
echo "  ssh ${HPC_USER}@${HPC_HOST}"
echo "  # 1. (Re-)submit the Qwen server with a 2h walltime so it fits"
echo "  #    before the next maintenance window:"
echo "  bash ${HPC_DIR}/submit_qwen_server.sh    # already on HPC from prior run"
echo "  # 2. Wait until the server job is RUNNING (squeue -u \$USER),"
echo "  #    then submit the client:"
echo "  sbatch ${HPC_DIR}/hpc/run_qwen_candidate_hidden.slurm"
echo "  # 3. When the client job finishes (email), pull results:"
echo "  exit"
echo "  bash ${LOCAL_DIR}/pull_qwen_candidate_hidden.sh"
