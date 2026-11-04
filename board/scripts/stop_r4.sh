#!/usr/bin/env bash
set -euo pipefail

root="${1:-/home/xilinx/jupyter_notebooks/spectrum_software_v1_r4_bplus}"
port="${2:-8091}"
cd "${root}"
python3 spectrum_service.py stop --port "${port}"
