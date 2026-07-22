#!/bin/bash
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "This installer supports macOS only." >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
source "${SCRIPT_DIR}/environment_compatibility.sh"
sumicore_apply_legacy_environment FUSIONSOLAR_DEVICE_DNS
RUN_SCRIPT="${SCRIPT_DIR}/run_daily_health.sh"
PLIST_PATH="${HOME}/Library/LaunchAgents/com.sumicore.daily-health.plist"
LOG_DIRECTORY="${HOME}/Library/Logs/hedp"
LABEL="com.sumicore.daily-health"
LEGACY_LABEL="com.hedp.daily-health"
DOMAIN="gui/$(id -u)"

: "${HEDP_FUSIONSOLAR_DEVICE_DNS:?Set HEDP_FUSIONSOLAR_DEVICE_DNS before installing.}"

xml_escape() { printf '%s' "$1" | sed -e 's/&/\&amp;/g' -e 's/</\&lt;/g' -e 's/>/\&gt;/g' -e 's/"/\&quot;/g' -e "s/'/\&apos;/g"; }

mkdir -p "$(dirname "${PLIST_PATH}")" "${LOG_DIRECTORY}"
touch "${LOG_DIRECTORY}/daily-health.out.log" \
      "${LOG_DIRECTORY}/daily-health.err.log"
chmod 600 "${LOG_DIRECTORY}/daily-health.out.log" \
          "${LOG_DIRECTORY}/daily-health.err.log"
chmod +x "${RUN_SCRIPT}"
umask 077
{
    printf '%s\n' '<?xml version="1.0" encoding="UTF-8"?>' '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">' '<plist version="1.0">' '<dict>'
    printf '  <key>Label</key><string>%s</string>\n' "${LABEL}"
    printf '  <key>ProgramArguments</key><array><string>%s</string></array>\n' "$(xml_escape "${RUN_SCRIPT}")"
    printf '  <key>WorkingDirectory</key><string>%s</string>\n' "$(xml_escape "${REPOSITORY_ROOT}")"
    printf '%s\n' '  <key>StartCalendarInterval</key><dict>' '    <key>Hour</key><integer>4</integer>' '    <key>Minute</key><integer>10</integer>' '  </dict>' '  <key>EnvironmentVariables</key><dict>'
    printf '    <key>HEDP_DATABASE_PATH</key><string>%s</string>\n' "$(xml_escape "${REPOSITORY_ROOT}/hedp.db")"
    printf '    <key>HEDP_FUSIONSOLAR_DEVICE_DNS</key><string>%s</string>\n' "$(xml_escape "${HEDP_FUSIONSOLAR_DEVICE_DNS}")"
    printf '%s\n' '  </dict>'
    printf '  <key>StandardOutPath</key><string>%s</string>\n' "$(xml_escape "${LOG_DIRECTORY}/daily-health.out.log")"
    printf '  <key>StandardErrorPath</key><string>%s</string>\n' "$(xml_escape "${LOG_DIRECTORY}/daily-health.err.log")"
    printf '%s\n' '</dict>' '</plist>'
} > "${PLIST_PATH}"
chmod 600 "${PLIST_PATH}"
"${SCRIPT_DIR}/switch_macos_launchd_job.sh" \
    "${LABEL}" "${PLIST_PATH}" "${LEGACY_LABEL}"
echo "Installed ${LABEL}."
