#!/usr/bin/env bash
set -euo pipefail

board_root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${board_root}"

sha256sum -c assets.sha256
