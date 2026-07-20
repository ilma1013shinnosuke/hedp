#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

cd "${REPOSITORY_ROOT}"
exec "${REPOSITORY_ROOT}/.venv/bin/hedp" daily-health --json
