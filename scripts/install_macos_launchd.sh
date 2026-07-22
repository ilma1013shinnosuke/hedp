#!/bin/bash
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "This installer supports macOS only." >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
HEDP_COMMAND="${REPOSITORY_ROOT}/.venv/bin/hedp"
RUN_DAILY_SCRIPT="${SCRIPT_DIR}/run_daily.sh"
PLIST_PATH="${HOME}/Library/LaunchAgents/com.sumicore.collect.plist"
LOG_DIRECTORY="${HOME}/Library/Logs/hedp"
LABEL="com.sumicore.collect"
LEGACY_LABEL="com.hedp.collect"
DOMAIN="gui/$(id -u)"

if [[ ! -x "${HEDP_COMMAND}" ]]; then
    echo "Executable not found: ${HEDP_COMMAND}" >&2
    exit 1
fi

if [[ ! -f "${RUN_DAILY_SCRIPT}" ]]; then
    echo "Script not found: ${RUN_DAILY_SCRIPT}" >&2
    exit 1
fi
chmod +x "${RUN_DAILY_SCRIPT}"

: "${HEDP_FUSIONSOLAR_BASE_URL:?Set HEDP_FUSIONSOLAR_BASE_URL before installing.}"
: "${HEDP_FUSIONSOLAR_STATION_DN:?Set HEDP_FUSIONSOLAR_STATION_DN before installing.}"
: "${HEDP_FUSIONSOLAR_USERNAME:?Set HEDP_FUSIONSOLAR_USERNAME before installing.}"
if [[ -z "${HEDP_FUSIONSOLAR_PASSWORD:-}" ]]; then
    read -r -s -p "HEDP_FUSIONSOLAR_PASSWORD: " HEDP_FUSIONSOLAR_PASSWORD
    printf '\n'
fi
if [[ -z "${HEDP_FUSIONSOLAR_PASSWORD}" ]]; then
    echo "HEDP_FUSIONSOLAR_PASSWORD must not be empty." >&2
    exit 1
fi

xml_escape() {
    printf '%s' "$1" | sed \
        -e 's/&/\&amp;/g' \
        -e 's/</\&lt;/g' \
        -e 's/>/\&gt;/g' \
        -e 's/"/\&quot;/g' \
        -e "s/'/\&apos;/g"
}

REPOSITORY_ROOT_XML="$(xml_escape "${REPOSITORY_ROOT}")"
RUN_DAILY_SCRIPT_XML="$(xml_escape "${RUN_DAILY_SCRIPT}")"
BASE_URL_XML="$(xml_escape "${HEDP_FUSIONSOLAR_BASE_URL}")"
STATION_DN_XML="$(xml_escape "${HEDP_FUSIONSOLAR_STATION_DN}")"
USERNAME_XML="$(xml_escape "${HEDP_FUSIONSOLAR_USERNAME}")"
PASSWORD_XML="$(xml_escape "${HEDP_FUSIONSOLAR_PASSWORD}")"
DATABASE_PATH_XML="$(xml_escape "${REPOSITORY_ROOT}/hedp.db")"
OUT_LOG_XML="$(xml_escape "${LOG_DIRECTORY}/collect.out.log")"
ERR_LOG_XML="$(xml_escape "${LOG_DIRECTORY}/collect.err.log")"

mkdir -p "$(dirname "${PLIST_PATH}")" "${LOG_DIRECTORY}"
touch "${LOG_DIRECTORY}/collect.out.log" "${LOG_DIRECTORY}/collect.err.log"
chmod 600 "${LOG_DIRECTORY}/collect.out.log" "${LOG_DIRECTORY}/collect.err.log"

umask 077
{
    printf '%s\n' '<?xml version="1.0" encoding="UTF-8"?>'
    printf '%s\n' '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">'
    printf '%s\n' '<plist version="1.0">'
    printf '%s\n' '<dict>'
    printf '%s\n' '  <key>Label</key>' "  <string>${LABEL}</string>"
    printf '%s\n' '  <key>ProgramArguments</key>' '  <array>'
    printf '%s\n' "    <string>${RUN_DAILY_SCRIPT_XML}</string>" '  </array>'
    printf '%s\n' '  <key>WorkingDirectory</key>' "  <string>${REPOSITORY_ROOT_XML}</string>"
    printf '%s\n' '  <key>StartCalendarInterval</key>' '  <dict>'
    printf '%s\n' '    <key>Hour</key>' '    <integer>3</integer>'
    printf '%s\n' '    <key>Minute</key>' '    <integer>0</integer>' '  </dict>'
    printf '%s\n' '  <key>EnvironmentVariables</key>' '  <dict>'
    printf '%s\n' '    <key>HEDP_FUSIONSOLAR_BASE_URL</key>' "    <string>${BASE_URL_XML}</string>"
    printf '%s\n' '    <key>HEDP_FUSIONSOLAR_STATION_DN</key>' "    <string>${STATION_DN_XML}</string>"
    printf '%s\n' '    <key>HEDP_FUSIONSOLAR_USERNAME</key>' "    <string>${USERNAME_XML}</string>"
    printf '%s\n' '    <key>HEDP_FUSIONSOLAR_PASSWORD</key>' "    <string>${PASSWORD_XML}</string>"
    printf '%s\n' '    <key>HEDP_DATABASE_PATH</key>' "    <string>${DATABASE_PATH_XML}</string>" '  </dict>'
    printf '%s\n' '  <key>StandardOutPath</key>' "  <string>${OUT_LOG_XML}</string>"
    printf '%s\n' '  <key>StandardErrorPath</key>' "  <string>${ERR_LOG_XML}</string>"
    printf '%s\n' '</dict>' '</plist>'
} > "${PLIST_PATH}"
chmod 600 "${PLIST_PATH}"

"${SCRIPT_DIR}/switch_macos_launchd_job.sh" \
    "${LABEL}" "${PLIST_PATH}" "${LEGACY_LABEL}"

echo "Installed ${LABEL}."
