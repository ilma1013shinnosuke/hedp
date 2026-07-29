#!/bin/bash

# FusionSolar / SmartLogger collection is deliberately bounded.  The interval
# remains a local runtime setting, while the supported range guarantees that a
# scheduled collector cannot exceed 288 runs per day.

sumicore_fusionsolar_collection_interval_seconds() {
    local value="${SUMICORE_FUSIONSOLAR_COLLECTION_INTERVAL_SECONDS:-${HEDP_FUSIONSOLAR_COLLECTION_INTERVAL_SECONDS:-300}}"

    if ! [[ "${value}" =~ ^[0-9]+$ ]]; then
        echo "FusionSolar collection interval must be a whole number of seconds" >&2
        return 2
    fi
    if ((value < 300 || value > 3600)); then
        echo "FusionSolar collection interval must be between 300 and 3600 seconds" >&2
        return 2
    fi
    printf '%s\n' "${value}"
}

sumicore_fusionsolar_max_scheduled_samples_per_day() {
    local interval
    interval="$(sumicore_fusionsolar_collection_interval_seconds)" || return
    printf '%s\n' "$(((86400 + interval - 1) / interval))"
}
