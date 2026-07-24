#!/bin/bash
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "This uninstaller supports macOS only." >&2
    exit 1
fi

DOMAIN="gui/$(id -u)"
jobs=(
    collect
    device-realtime
    equipment
    switchbot
    daily-health
)
for job in "${jobs[@]}"; do
    for prefix in com.sumicore com.hedp; do
        label="${prefix}.${job}"
        plist_path="${HOME}/Library/LaunchAgents/${label}.plist"
        launchctl bootout "${DOMAIN}/${label}" 2>/dev/null || true
        rm -f -- "${plist_path}"
        echo "Uninstalled ${label}."
    done
done
