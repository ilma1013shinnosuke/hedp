#!/bin/bash

sumicore_rotate_job_logs() {
    local job_name="$1"
    local maximum_bytes="${2:-5242880}"
    local generations="${3:-2}"
    local log_directory="${HOME}/Library/Logs/hedp"
    local stream log_path size generation

    [[ "${maximum_bytes}" =~ ^[1-9][0-9]*$ ]] || return 2
    [[ "${generations}" =~ ^[1-9][0-9]*$ ]] || return 2
    mkdir -p "${log_directory}"
    for stream in out err; do
        log_path="${log_directory}/${job_name}.${stream}.log"
        [[ -f "${log_path}" && ! -L "${log_path}" ]] || continue
        size="$(stat -f %z "${log_path}")"
        ((size > maximum_bytes)) || continue
        for ((generation = generations; generation > 1; generation--)); do
            if [[ -f "${log_path}.$((generation - 1))" ]]; then
                mv -f -- \
                    "${log_path}.$((generation - 1))" \
                    "${log_path}.${generation}"
            fi
        done
        mv -f -- "${log_path}" "${log_path}.1"
        : > "${log_path}"
        chmod 600 "${log_path}" "${log_path}.1"
    done
}
