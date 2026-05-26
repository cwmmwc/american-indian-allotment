#!/bin/bash
# Pull the Qwen-VL vision extraction results from HPC to local.
set -e
rsync -av \
    cwm6w@login.hpc.virginia.edu:/project/LawData/blm-extraction/annotation_v5_qwen_50.json \
    ~/projects/american-indian-allotment/

echo
echo "Pulled to: ~/projects/american-indian-allotment/annotation_v5_qwen_50.json"
ls -la ~/projects/american-indian-allotment/annotation_v5_qwen_50.json
