#!/bin/bash

sumicore_apply_legacy_environment() {
    local suffix current_name legacy_name current_value
    for suffix in "$@"; do
        current_name="SUMICORE_${suffix}"
        legacy_name="HEDP_${suffix}"
        current_value="${!current_name:-}"
        if [[ -n "${current_value}" ]]; then
            printf -v "${legacy_name}" '%s' "${current_value}"
            export "${legacy_name}"
        fi
    done
}
