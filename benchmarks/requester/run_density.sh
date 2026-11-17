#!/usr/bin/env bash
set -Eeuo pipefail

requester_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

export LEVELS=${DENSITY_USERS:-250}
export REPEATS=1
export JOURNEYS_PER_USER=1
export ARRIVAL_GAP_MIN_SECONDS=1
export ARRIVAL_GAP_MAX_SECONDS=1
export THINK_MIN=1
export THINK_MAX=14
export JOURNEY_THINK_MIN=1
export JOURNEY_THINK_MAX=14
export HOLD_AFTER_TARGET_SECONDS=0
export DENSITY_RAMP=1
export DENSITY_INITIAL_HOLD_SECONDS=${DENSITY_INITIAL_HOLD_SECONDS:-10}
export DENSITY_STEP_SECONDS=${DENSITY_STEP_SECONDS:-60}
export DENSITY_MIN_THINK_MAX=${DENSITY_MIN_THINK_MAX:-1}
export ALLOW_LOAD_FAILURES=1
export SKIP_BROWSER_MEASUREMENT=1

printf '%s\n' \
    'Starting the continuous click-density experiment.' \
    "Visitors arrive one per second until ${LEVELS} are active." \
    'The maximum pause then falls by one second per phase.'

exec bash "$requester_dir/run.sh" "$@"
