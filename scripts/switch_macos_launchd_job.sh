#!/bin/bash
set -euo pipefail

if [[ "$(uname -s)" != "Darwin" ]]; then
    echo "This switcher supports macOS only." >&2
    exit 1
fi

if [[ "$#" -ne 3 ]]; then
    echo "Usage: $0 NEW_LABEL NEW_PLIST LEGACY_LABEL" >&2
    exit 2
fi

NEW_LABEL="$1"
NEW_PLIST="$2"
LEGACY_LABEL="$3"
DOMAIN="gui/$(id -u)"
LEGACY_PLIST="$(dirname "${NEW_PLIST}")/${LEGACY_LABEL}.plist"
LEGACY_WAS_LOADED=0

plutil -lint "${NEW_PLIST}" >/dev/null

if launchctl print "${DOMAIN}/${LEGACY_LABEL}" >/dev/null 2>&1; then
    LEGACY_WAS_LOADED=1
fi

restore_legacy() {
    launchctl bootout "${DOMAIN}/${NEW_LABEL}" >/dev/null 2>&1 || true
    if [[ "${LEGACY_WAS_LOADED}" -eq 1 && -f "${LEGACY_PLIST}" ]]; then
        launchctl bootstrap "${DOMAIN}" "${LEGACY_PLIST}"
        launchctl kickstart -k "${DOMAIN}/${LEGACY_LABEL}" >/dev/null 2>&1 || true
        echo "Restored ${LEGACY_LABEL} after ${NEW_LABEL} failed." >&2
    fi
}

launchctl bootout "${DOMAIN}/${NEW_LABEL}" >/dev/null 2>&1 || true
if [[ "${LEGACY_WAS_LOADED}" -eq 1 ]]; then
    launchctl bootout "${DOMAIN}/${LEGACY_LABEL}"
fi

if ! launchctl bootstrap "${DOMAIN}" "${NEW_PLIST}"; then
    restore_legacy
    exit 1
fi

if ! launchctl kickstart -k "${DOMAIN}/${NEW_LABEL}"; then
    restore_legacy
    exit 1
fi

launchctl print "${DOMAIN}/${NEW_LABEL}" >/dev/null

