# HPC scripts for the allotment-research project

Patterns borrowed from `~/projects/exhaustive-extraction-pipeline/hpc/`.
This directory is for SLURM jobs and HPC-side helpers specific to the BLM
patent vision-extraction work.

## What's here

| File | Purpose |
|---|---|
| `run_gemma_blm_benchmark.slurm` | Runs Gemma 3 27B vision extraction on the 50-PDF benchmark CSV. Single SLURM job that starts a vLLM server on 1×A100, waits for it to be ready, runs the extractor client, and tears the server down at the end. |

## Expected HPC layout

```
/project/LawData/blm-extraction/
├── blm_benchmark_50.csv
├── blm_pdfs/                    # rsync'd from local
│   ├── 5513.pdf
│   ├── ...
│   └── 1115224.pdf
├── scripts/
│   └── extract_annotations_gemma_vision.py
├── logs/                        # SLURM + vLLM server stdout/stderr
└── annotation_v5_gemma_50.json  # output (created by the job)
```

The vLLM container and the Gemma 3 27B model files live in the shared
`/project/LawData/models/` tree (already in place from the extraction-pipeline
project's prior runs):

```
/project/LawData/models/container/vllm_0.14.1-cu130.sif
/project/LawData/models/gemma-3-27b-it/      (HuggingFace download cache)
```

## Push-and-submit (run yourself in your own terminal)

```bash
# Push the benchmark CSV, the PDFs, and the scripts
rsync -av \
    ~/projects/american-indian-allotment/blm_benchmark_50.csv \
    cwm6w@login.hpc.virginia.edu:/project/LawData/blm-extraction/

rsync -av \
    ~/projects/american-indian-allotment/blm_pdfs/ \
    cwm6w@login.hpc.virginia.edu:/project/LawData/blm-extraction/blm_pdfs/

rsync -av \
    ~/projects/american-indian-allotment/scripts/extract_annotations_gemma_vision.py \
    cwm6w@login.hpc.virginia.edu:/project/LawData/blm-extraction/scripts/

rsync -av \
    ~/projects/american-indian-allotment/hpc/run_gemma_blm_benchmark.slurm \
    cwm6w@login.hpc.virginia.edu:/project/LawData/blm-extraction/hpc/

# Then on HPC (ssh in first):
ssh cwm6w@login.hpc.virginia.edu
cd /project/LawData/blm-extraction
sbatch hpc/run_gemma_blm_benchmark.slurm
```

The job logs go to `/project/LawData/blm-extraction/logs/gemma_blm_<jobid>.{out,err}`
and the vLLM server log goes to `logs/vllm_server_<jobid>.out`. The output
JSON is at `annotation_v5_gemma_50.json` in the project dir.

## When the job finishes

Pull the output back for comparison alongside the Sonnet v5 run:

```bash
rsync -av \
    cwm6w@login.hpc.virginia.edu:/project/LawData/blm-extraction/annotation_v5_gemma_50.json \
    ~/projects/american-indian-allotment/
```

## Why a single job (not a separate server job + client job)

The extraction-pipeline pattern (`start_qwen_vl_server.slurm` + a separate
client job) makes sense for long-running campaigns where the same server
serves many client runs over hours or days. For a 50-PDF benchmark, a single
self-contained job is simpler — start server, wait, run, done — and avoids
the coordination of pinning a client job to whichever node the server landed
on.
