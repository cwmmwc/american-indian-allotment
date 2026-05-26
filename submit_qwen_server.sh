#!/bin/bash
# Submit the Qwen-VL server with a short walltime so it fits before the
# 2026-05-26 06:00 maintenance window. Run this on HPC after scancel'ing
# the original server submission.
sbatch --time=02:00:00 /project/LawData/blm-extraction/hpc/start_qwen_vl_blm_server.slurm
