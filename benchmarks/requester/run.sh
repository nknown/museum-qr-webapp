#!/usr/bin/env bash
set -Eeuo pipefail

requester_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
benchmark_dir=$(cd -- "$requester_dir/.." && pwd)
project_root=$(cd -- "$benchmark_dir/.." && pwd)

config_file=${BENCHMARK_CONFIG:-$benchmark_dir/config/benchmark.env}
if [[ -f "$config_file" ]]; then
    # shellcheck disable=SC1090
    source "$config_file"
fi

base_url=${MIYP_BENCHMARK_BASE_URL:-}
if (( $# )) && [[ $1 == http://* || $1 == https://* ]]; then
    base_url=$1
    shift
fi
if [[ -z "$base_url" ]]; then
    printf '%s\n' \
        'Set MIYP_BENCHMARK_BASE_URL or pass the deployment URL as the first argument.' >&2
    exit 2
fi

presentations=("$@")
presentations_file=${PRESENTATIONS_FILE:-$benchmark_dir/config/presentations.txt}
if [[ "$presentations_file" != /* ]]; then
    presentations_file="$project_root/$presentations_file"
fi
if (( ${#presentations[@]} == 0 )) && [[ -f "$presentations_file" ]]; then
    while IFS= read -r presentation; do
        [[ -n "$presentation" && "$presentation" != \#* ]] && \
            presentations+=("$presentation")
    done < "$presentations_file"
fi
if (( ${#presentations[@]} == 0 )); then
    printf '%s\n' \
        'Pass at least one public /presentation/... path or create benchmarks/config/presentations.txt.' >&2
    exit 2
fi

python=${PYTHON:-python3}
command -v "$python" >/dev/null || {
    printf 'Python executable not found: %s\n' "$python" >&2
    exit 1
}
"$python" -c 'import requests' >/dev/null 2>&1 || {
    printf 'Install requester dependencies with: python -m pip install -r benchmarks/requirements.txt\n' >&2
    exit 1
}

run_id=$(date -u +'%Y%m%dT%H%M%SZ')
results=${RESULTS_DIR:-$benchmark_dir/results/requester/$run_id}
certificate=${MIYP_BENCHMARK_CERTIFICATE:-$project_root/global_files/certificates/miyp-selfsigned.crt}
if [[ "$certificate" != /* ]]; then
    certificate="$project_root/$certificate"
fi
mkdir -p "$results"

tls_load=()
tls_browser=()
curl_tls=()
if [[ "$base_url" == https://* ]]; then
    if [[ ${USE_SYSTEM_CA:-0} == 1 ]]; then
        tls_load=(--system-ca)
        tls_browser=(--system-ca)
    elif [[ -f "$certificate" ]]; then
        tls_load=(--ca-certificate "$certificate")
        tls_browser=(--certificate "$certificate")
        curl_tls=(--cacert "$certificate")
    else
        printf 'HTTPS certificate not found: %s\n' "$certificate" >&2
        printf 'Set MIYP_BENCHMARK_CERTIFICATE or USE_SYSTEM_CA=1.\n' >&2
        exit 1
    fi
fi

health_path=${BENCHMARK_HEALTH_PATH:-/}
printf 'Checking %s%s ...\n' "${base_url%/}" "$health_path"
curl --fail --silent --show-error --output /dev/null --max-time 15 \
    "${curl_tls[@]}" "${base_url%/}${health_path}"

chrome=''
if [[ ${SKIP_BROWSER_MEASUREMENT:-0} != 1 ]]; then
    "$python" -c 'import websocket' >/dev/null 2>&1 || {
        printf 'Browser measurement requires websocket-client from benchmarks/requirements.txt.\n' >&2
        exit 1
    }
    for candidate in google-chrome google-chrome-stable chromium chromium-browser; do
        if command -v "$candidate" >/dev/null; then
            chrome=$(command -v "$candidate")
            break
        fi
    done
    [[ -n "$chrome" ]] || {
        printf 'Chrome or Chromium is required unless SKIP_BROWSER_MEASUREMENT=1.\n' >&2
        exit 1
    }
fi

signal_finished() {
    local status=$1
    curl --silent --show-error --output /dev/null --max-time 15 \
        "${curl_tls[@]}" \
        "${base_url%/}/__miyp_benchmark_finished__/$status" || true
}

finish_run() {
    local status=$?
    trap - EXIT
    if (( status == 0 )); then
        signal_finished success
    else
        signal_finished failure
    fi
    exit "$status"
}
trap finish_run EXIT

load_targets=(--url "${presentations[0]}")
for presentation in "${presentations[@]:1}"; do
    load_targets+=(--additional-url "$presentation")
done

density_args=()
if [[ ${DENSITY_RAMP:-0} == 1 ]]; then
    density_args=(
        --density-ramp
        --density-initial-hold-seconds "${DENSITY_INITIAL_HOLD_SECONDS:-10}"
        --density-step-seconds "${DENSITY_STEP_SECONDS:-60}"
        --density-min-think-max "${DENSITY_MIN_THINK_MAX:-1}"
    )
fi

admission_args=()
if [[ ${ADMISSION_RAMP:-0} == 1 ]]; then
    admission_args=(
        --admission-ramp
        --admission-step-users "${ADMISSION_STEP_USERS:-1}"
        --admission-step-seconds "${ADMISSION_STEP_SECONDS:-60}"
        --admission-failure-stages "${ADMISSION_FAILURE_STAGES:-2}"
    )
fi

"$python" "$benchmark_dir/load_test.py" \
    --base-url "$base_url" \
    "${load_targets[@]}" \
    "${tls_load[@]}" \
    --levels "${LEVELS:-1,5,10,25,50}" \
    --repeats "${REPEATS:-3}" \
    --journeys-per-user "${JOURNEYS_PER_USER:-2}" \
    --think-min "${THINK_MIN:-3}" \
    --think-max "${THINK_MAX:-12}" \
    --navigation-changes-min "${NAVIGATION_CHANGES_MIN:-1}" \
    --navigation-changes-max "${NAVIGATION_CHANGES_MAX:-12}" \
    --journey-think-min "${JOURNEY_THINK_MIN:-5}" \
    --journey-think-max "${JOURNEY_THINK_MAX:-15}" \
    --arrival-gap-min "${ARRIVAL_GAP_MIN_SECONDS:-1}" \
    --arrival-gap-max "${ARRIVAL_GAP_MAX_SECONDS:-10}" \
    --hold-after-target-seconds "${HOLD_AFTER_TARGET_SECONDS:-0}" \
    --cooldown-seconds "${COOLDOWN_SECONDS:-10}" \
    "${density_args[@]}" \
    "${admission_args[@]}" \
    --output-dir "$results"

if [[ ${SKIP_BROWSER_MEASUREMENT:-0} != 1 ]]; then
    "$python" "$benchmark_dir/browser_data.py" \
        --base-url "$base_url" \
        --url "${presentations[0]}" \
        --chrome "$chrome" \
        "${tls_browser[@]}" \
        --output-dir "$results"
fi

validation_args=()
[[ ${ALLOW_LOAD_FAILURES:-0} == 1 ]] && validation_args+=(--allow-load-failures)
[[ ${SKIP_BROWSER_MEASUREMENT:-0} == 1 ]] && validation_args+=(--skip-browser)
"$python" "$benchmark_dir/validate_results.py" "$results" "${validation_args[@]}"

printf 'Requester measurements saved to %s\n' "$results"
