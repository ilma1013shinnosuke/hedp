#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
HEDP_COMMAND="${REPOSITORY_ROOT}/.venv/bin/hedp"
BACKUP_DIRECTORY="${REPOSITORY_ROOT}/backups"

cd "${REPOSITORY_ROOT}"
"${HEDP_COMMAND}" collect
"${HEDP_COMMAND}" backup

if [[ ! -d "${BACKUP_DIRECTORY}" ]]; then
    exit 0
fi

shopt -s nullglob
backup_files=()
for backup_file in "${BACKUP_DIRECTORY}"/hedp-[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]-[0-9][0-9][0-9][0-9][0-9][0-9].db; do
    if [[ -f "${backup_file}" && ! -L "${backup_file}" ]]; then
        backup_files+=("${backup_file}")
    fi
done

obsolete_count=$((${#backup_files[@]} - 30))
for ((index = 0; index < obsolete_count; index++)); do
    rm -- "${backup_files[index]}"
done
