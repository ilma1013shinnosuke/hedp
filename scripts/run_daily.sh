#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
HEDP_COMMAND="${REPOSITORY_ROOT}/.venv/bin/hedp"
BACKUP_DIRECTORY="${REPOSITORY_ROOT}/backups"

cd "${REPOSITORY_ROOT}"
status=0
"${HEDP_COMMAND}" collect || status=1
previous_date="$(TZ=Asia/Tokyo date -v-1d +%F)"
"${HEDP_COMMAND}" collect-energy-balance --start "${previous_date}" --end "${previous_date}" || status=1
"${HEDP_COMMAND}" quality --start "${previous_date}" --end "${previous_date}" || status=1
"${HEDP_COMMAND}" backup || status=1

if [[ ! -d "${BACKUP_DIRECTORY}" ]]; then
    exit "${status}"
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

exit "${status}"
