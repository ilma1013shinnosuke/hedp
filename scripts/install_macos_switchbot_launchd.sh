#!/bin/bash
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "This installer supports macOS only." >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPOSITORY_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
RUN_SCRIPT="${SCRIPT_DIR}/run_switchbot_hourly.sh"
PLIST_PATH="${HOME}/Library/LaunchAgents/com.hedp.switchbot.plist"
LOG_DIRECTORY="${HOME}/Library/Logs/hedp"
LABEL="com.hedp.switchbot"
DOMAIN="gui/$(id -u)"

mkdir -p "$(dirname "${PLIST_PATH}")" "${LOG_DIRECTORY}"
chmod +x "${RUN_SCRIPT}"
umask 077
touch "${LOG_DIRECTORY}/switchbot.out.log" \
      "${LOG_DIRECTORY}/switchbot.err.log"
chmod 600 "${LOG_DIRECTORY}/switchbot.out.log" \
          "${LOG_DIRECTORY}/switchbot.err.log"
cat > "${PLIST_PATH}" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>Label</key><string>${LABEL}</string>
<key>ProgramArguments</key><array><string>${RUN_SCRIPT}</string></array>
<key>WorkingDirectory</key><string>${REPOSITORY_ROOT}</string>
<key>StartCalendarInterval</key><dict><key>Minute</key><integer>5</integer></dict>
<key>EnvironmentVariables</key><dict>
<key>HEDP_DATABASE_PATH</key><string>${REPOSITORY_ROOT}/hedp.db</string>
</dict>
<key>StandardOutPath</key><string>${LOG_DIRECTORY}/switchbot.out.log</string>
<key>StandardErrorPath</key><string>${LOG_DIRECTORY}/switchbot.err.log</string>
</dict></plist>
PLIST
chmod 600 "${PLIST_PATH}"
plutil -lint "${PLIST_PATH}"
launchctl bootout "${DOMAIN}/${LABEL}" 2>/dev/null || true
launchctl bootstrap "${DOMAIN}" "${PLIST_PATH}"
launchctl kickstart -k "${DOMAIN}/${LABEL}"
echo "Installed ${LABEL}."
