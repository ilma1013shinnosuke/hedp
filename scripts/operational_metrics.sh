#!/bin/bash
# Shell boundary for anonymous operational metrics.  This file intentionally
# accepts only fixed, non-sensitive result fields; the Python recorder owns
# validation and persistence.  A recorder failure must never change the
# outcome of a collection job.

sumicore_record_operational_metric() {
    local operation="$1"
    local outcome="$2"
    local elapsed_seconds="$3"
    local failure_category="$4"

    if ! "${REPOSITORY_ROOT}/.venv/bin/python" \
        "${SCRIPT_DIR}/record_operational_metric.py" \
        operation "${operation}" "${outcome}" "${elapsed_seconds}" \
        "${failure_category}" >/dev/null 2>&1; then
        echo "Operational metric recording failed" >&2
    fi
}

sumicore_record_database_metric() {
    if ! "${REPOSITORY_ROOT}/.venv/bin/python" \
        "${SCRIPT_DIR}/record_operational_metric.py" database >/dev/null 2>&1; then
        echo "Operational metric recording failed" >&2
    fi
}
