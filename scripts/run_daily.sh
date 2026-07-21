#!/bin/bash
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
HEDP_COMMAND="${REPOSITORY_ROOT}/.venv/bin/hedp"
BACKUP_DIRECTORY="${REPOSITORY_ROOT}/backups"
LOCK_DIRECTORY="${TMPDIR:-/tmp}/com.hedp.daily.lock"
TIMEOUT_RUNNER="${SCRIPT_DIR}/run_with_timeout.py"
COMMAND_TIMEOUT_SECONDS="${HEDP_DAILY_COMMAND_TIMEOUT_SECONDS:-900}"
BACKFILL_DAYS="${HEDP_DAILY_BACKFILL_DAYS:-30}"

if ! mkdir "${LOCK_DIRECTORY}" 2>/dev/null; then
    echo "Daily job is already running; skipping this launch." >&2
    exit 0
fi
trap 'rmdir "${LOCK_DIRECTORY}" 2>/dev/null || true' EXIT

run_timed() {
    python3 "${TIMEOUT_RUNNER}" "${COMMAND_TIMEOUT_SECONDS}" "$@"
}

cd "${REPOSITORY_ROOT}"
status=0
run_timed "${HEDP_COMMAND}" collect || status=1
previous_date="$(TZ=Asia/Tokyo date -v-1d +%F)"
backfill_start="$(TZ=Asia/Tokyo date -v-"${BACKFILL_DAYS}"d +%F)"
run_timed "${HEDP_COMMAND}" backfill-missing --start "${backfill_start}" --end "${previous_date}" || status=1
run_timed "${HEDP_COMMAND}" backfill-energy-balance --start "${backfill_start}" --end "${previous_date}" || status=1
run_timed "${HEDP_COMMAND}" quality --start "${backfill_start}" --end "${previous_date}" || status=1
run_timed "${HEDP_COMMAND}" quality-energy-balance --start "${backfill_start}" --end "${previous_date}" || status=1
run_timed "${HEDP_COMMAND}" backup || status=1

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
