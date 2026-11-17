#!/usr/bin/env bash
set -Eeuo pipefail

requester_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

export LEVELS=${ADMISSION_MAX_USERS:-1000}
export REPEATS=1
export JOURNEYS_PER_USER=1
export THINK_MIN=20
export THINK_MAX=30
export JOURNEY_THINK_MIN=20
export JOURNEY_THINK_MAX=30
export HOLD_AFTER_TARGET_SECONDS=0
export DENSITY_RAMP=0
export ADMISSION_RAMP=1
export ADMISSION_STEP_USERS=${ADMISSION_STEP_USERS:-1}
export ADMISSION_STEP_SECONDS=${ADMISSION_STEP_SECONDS:-60}
export ADMISSION_FAILURE_STAGES=${ADMISSION_FAILURE_STAGES:-2}
export ALLOW_LOAD_FAILURES=1
export SKIP_BROWSER_MEASUREMENT=1

printf '%s\n' \
    'Starting the progressive-admission experiment.' \
    "Adding ${ADMISSION_STEP_USERS} visitor(s) every ${ADMISSION_STEP_SECONDS} seconds." \
    "Safety ceiling: ${LEVELS} visitors."

exec bash "$requester_dir/run.sh" "$@"
