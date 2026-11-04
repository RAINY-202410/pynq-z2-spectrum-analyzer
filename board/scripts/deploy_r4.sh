#!/usr/bin/env bash
set -euo pipefail

archive="${1:-spectrum_software_v1_r4_bplus_board.zip}"
destination="${2:-/home/xilinx/jupyter_notebooks}"

if [[ ! -f "${archive}" ]]; then
  echo "Archive not found: ${archive}" >&2
  exit 1
fi

if command -v ss >/dev/null 2>&1 && ss -lnt | grep -q ':8091 '; then
  echo "Port 8091 is in use. Stop the existing service first." >&2
  exit 1
fi

if [[ -e "${destination}/spectrum_software_v1_r4_bplus" ]]; then
  echo "Existing runtime directory detected; preserve it and reuse the existing service." >&2
  exit 1
fi
mkdir -p "${destination}"
python3 -m zipfile -e "${archive}" "${destination}"
test -f "${destination}/spectrum_software_v1_r4_bplus/software_manifest.json"
echo "Deployed to ${destination}/spectrum_software_v1_r4_bplus"
