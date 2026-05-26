#!/bin/bash
# Pull the Qwen-VL candidate-hidden cross-check results from HPC to local.
# Run in your own terminal (will prompt for HPC credentials).
set -e

rsync -av \
    cwm6w@login.hpc.virginia.edu:/project/LawData/blm-extraction/candidate_hidden/qwen_output.json \
    ~/projects/american-indian-allotment/annotation_v5_qwen_candidate_hidden.json

echo
echo "Pulled to: ~/projects/american-indian-allotment/annotation_v5_qwen_candidate_hidden.json"
ls -la ~/projects/american-indian-allotment/annotation_v5_qwen_candidate_hidden.json
echo
echo "Next: ./venv/bin/python3 scripts/compare_sonnet_qwen_candidate_hidden.py"
