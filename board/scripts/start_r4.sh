#!/usr/bin/env bash
set -euo pipefail

root="${1:-/home/xilinx/jupyter_notebooks/spectrum_software_v1_r4_bplus}"
cd "${root}"

python3 spectrum_app.py \
  --mode live \
  --bind 0.0.0.0 \
  --port 8091
