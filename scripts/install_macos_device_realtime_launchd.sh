#!/bin/bash
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "This installer supports macOS only." >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
RUN_SCRIPT="${SCRIPT_DIR}/run_device_realtime.sh"
PLIST_PATH="${HOME}/Library/LaunchAgents/com.sumicore.device-realtime.plist"
LOG_DIRECTORY="${HOME}/Library/Logs/hedp"
LABEL="com.sumicore.device-realtime"
LEGACY_LABEL="com.hedp.device-realtime"
DOMAIN="gui/$(id -u)"

: "${HEDP_FUSIONSOLAR_BASE_URL:?Set HEDP_FUSIONSOLAR_BASE_URL before installing.}"
: "${HEDP_FUSIONSOLAR_STATION_DN:?Set HEDP_FUSIONSOLAR_STATION_DN before installing.}"
: "${HEDP_FUSIONSOLAR_USERNAME:?Set HEDP_FUSIONSOLAR_USERNAME before installing.}"
: "${HEDP_FUSIONSOLAR_DEVICE_DNS:?Set HEDP_FUSIONSOLAR_DEVICE_DNS before installing.}"
: "${HEDP_FUSIONSOLAR_BATTERY_DN:?Set HEDP_FUSIONSOLAR_BATTERY_DN before installing.}"
: "${HEDP_FUSIONSOLAR_BATTERY_SIGIDS:?Set HEDP_FUSIONSOLAR_BATTERY_SIGIDS before installing.}"
if [[ -z "${HEDP_FUSIONSOLAR_PASSWORD:-}" ]]; then
    read -r -s -p "HEDP_FUSIONSOLAR_PASSWORD: " HEDP_FUSIONSOLAR_PASSWORD
    printf '\n'
fi
: "${HEDP_FUSIONSOLAR_PASSWORD:?Password must not be empty.}"

xml_escape() { printf '%s' "$1" | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g' -e 's/"/\&quot;/g' -e "s/'/\&apos;/g"; }

mkdir -p "$(dirname "${PLIST_PATH}")" "${LOG_DIRECTORY}"
touch "${LOG_DIRECTORY}/device-realtime.out.log" \
      "${LOG_DIRECTORY}/device-realtime.err.log"
chmod 600 "${LOG_DIRECTORY}/device-realtime.out.log" \
          "${LOG_DIRECTORY}/device-realtime.err.log"
chmod +x "${RUN_SCRIPT}"
umask 077
{
    printf '%s\n' '<?xml version="1.0" encoding="UTF-8"?>' '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">' '<plist version="1.0">' '<dict>'
    printf '  <key>Label</key><string>%s</string>\n' "${LABEL}"
    printf '  <key>ProgramArguments</key><array><string>%s</string></array>\n' "$(xml_escape "${RUN_SCRIPT}")"
    printf '  <key>WorkingDirectory</key><string>%s</string>\n' "$(xml_escape "${REPOSITORY_ROOT}")"
    printf '%s\n' '  <key>StartInterval</key><integer>300</integer>' '  <key>EnvironmentVariables</key><dict>'
    for name in HEDP_FUSIONSOLAR_BASE_URL HEDP_FUSIONSOLAR_STATION_DN HEDP_FUSIONSOLAR_USERNAME HEDP_FUSIONSOLAR_PASSWORD HEDP_FUSIONSOLAR_DEVICE_DNS HEDP_FUSIONSOLAR_BATTERY_DN HEDP_FUSIONSOLAR_BATTERY_SIGIDS; do
        printf '    <key>%s</key><string>%s</string>\n' "${name}" "$(xml_escape "${!name}")"
    done
    printf '    <key>HEDP_DATABASE_PATH</key><string>%s</string>\n' "$(xml_escape "${REPOSITORY_ROOT}/hedp.db")"
    printf '%s\n' '  </dict>'
    printf '  <key>StandardOutPath</key><string>%s</string>\n' "$(xml_escape "${LOG_DIRECTORY}/device-realtime.out.log")"
    printf '  <key>StandardErrorPath</key><string>%s</string>\n' "$(xml_escape "${LOG_DIRECTORY}/device-realtime.err.log")"
    printf '%s\n' '</dict>' '</plist>'
} > "${PLIST_PATH}"
chmod 600 "${PLIST_PATH}"
"${SCRIPT_DIR}/switch_macos_launchd_job.sh" \
    "${LABEL}" "${PLIST_PATH}" "${LEGACY_LABEL}"
echo "Installed ${LABEL}."
