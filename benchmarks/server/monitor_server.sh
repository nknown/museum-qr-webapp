#!/usr/bin/env bash
set -Eeuo pipefail

bundle_dir=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
benchmark_dir=$(cd -- "$bundle_dir/.." && pwd)
project_root=$(cd -- "$benchmark_dir/.." && pwd)
config_file=${BENCHMARK_CONFIG:-$benchmark_dir/config/benchmark.env}
if [[ -f "$config_file" ]]; then
    # shellcheck disable=SC1090
    source "$config_file"
fi
run_id=$(date -u +'%Y%m%dT%H%M%SZ')
output_dir="$benchmark_dir/results/server/$run_id"
controller_log="$output_dir/MONITOR_SERVER.log"
interval=${SAMPLE_INTERVAL_SECONDS:-1}
final_idle_seconds=${FINAL_IDLE_SECONDS:-${IDLE_TIMEOUT_SECONDS:-60}}
compose_project=${COMPOSE_PROJECT_NAME:-$(basename "$project_root")}
web_service=${WEB_SERVICE:-web}
database_service=${DATABASE_SERVICE:-db}
proxy_service=${PROXY_SERVICE:-nginx}
database_user=${POSTGRES_USER:-miyp_user}
database_name=${POSTGRES_DB:-miyp_database}
service_names="$web_service,$database_service,$proxy_service"

mkdir -p "$output_dir"
: > "$controller_log"
exec > >(tee -a "$controller_log") 2>&1

failed_command=''
trap 'failed_command=$BASH_COMMAND' ERR
trap 'status=$?; if (( status != 0 )); then printf "ERROR! Server monitoring failed while running: %s\nFull output: %s\n" "$failed_command" "$controller_log"; fi' EXIT

used_sudo=0
python_command=(python3)
if ! docker info >/dev/null 2>&1; then
    command -v sudo >/dev/null || {
        printf 'sudo is required to read Docker statistics.\n' >&2
        exit 1
    }
    sudo -v
    python_command=(sudo python3)
    used_sudo=1
fi

printf 'Starting MIYP server monitoring.\n'
printf 'The requester must signal when the benchmark has finished.\n'
printf 'The monitor will then capture %s seconds of application inactivity.\n' \
    "$final_idle_seconds"
printf 'Samples will be written to %s/server-samples.csv\n\n' "$output_dir"
printf 'Compose project: %s; services: %s\n\n' "$compose_project" "$service_names"

"${python_command[@]}" - \
    "$output_dir" \
    "$interval" \
    "$final_idle_seconds" \
    "$compose_project" \
    "$service_names" \
    "$database_user" \
    "$database_name" <<'PY'
import csv
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import platform
import re
import signal
import subprocess
import sys
import time


output_dir = Path(sys.argv[1])
interval = float(sys.argv[2])
final_idle_seconds = float(sys.argv[3])
compose_project = sys.argv[4]
services = tuple(sys.argv[5].split(","))
database_user = sys.argv[6]
database_name = sys.argv[7]
if interval <= 0:
    raise SystemExit("SAMPLE_INTERVAL_SECONDS must be greater than zero")
if final_idle_seconds <= 0:
    raise SystemExit("FINAL_IDLE_SECONDS must be greater than zero")

csv_path = output_dir / "server-samples.csv"
metadata_path = output_dir / "server-metadata.json"
events_path = output_dir / "server-events.log"
if len(services) != 3 or any(not service for service in services):
    raise SystemExit("WEB_SERVICE, DATABASE_SERVICE, and PROXY_SERVICE are required")
web_service, database_service, proxy_service = services
running = True
stop_reason = "unknown"
sample_count = 0
request_log_lines = 0
last_request_monotonic = None
benchmark_finished_monotonic = None
benchmark_finish_status = None
current_density_phase = None
current_density_maximum_pause = None
current_admission_phase = None
current_admitted_users = None
log_cursor = datetime.now(timezone.utc)


def utc_now():
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def command(args, timeout=10):
    return subprocess.run(
        args,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        timeout=timeout,
    ).stdout.strip()


def record_event(message):
    with events_path.open("a", encoding="utf-8") as handle:
        handle.write(f"{utc_now()} {message}\n")


def stop_monitoring(signum, frame):
    del signum, frame
    global running, stop_reason
    running = False
    stop_reason = "manual_or_signal"


def cpu_totals():
    values = Path("/proc/stat").read_text(encoding="utf-8").splitlines()[0].split()
    ticks = [int(value) for value in values[1:]]
    idle = ticks[3] + (ticks[4] if len(ticks) > 4 else 0)
    return sum(ticks), idle


def memory_values():
    values = {}
    for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
        name, value = line.split(":", 1)
        values[name] = int(value.strip().split()[0])
    total_mib = values["MemTotal"] / 1024
    available_mib = values["MemAvailable"] / 1024
    return total_mib - available_mib, available_mib


UNIT_FACTORS = {
    "B": 1,
    "kB": 1000,
    "KB": 1000,
    "KiB": 1024,
    "MB": 1000 ** 2,
    "MiB": 1024 ** 2,
    "GB": 1000 ** 3,
    "GiB": 1024 ** 3,
    "TB": 1000 ** 4,
    "TiB": 1024 ** 4,
}


def quantity_bytes(value):
    match = re.fullmatch(r"\s*([0-9.]+)\s*([A-Za-z]+)\s*", value or "")
    if not match:
        return None
    factor = UNIT_FACTORS.get(match.group(2))
    return int(float(match.group(1)) * factor) if factor else None


def percentage(value):
    try:
        return float((value or "").strip().rstrip("%"))
    except ValueError:
        return None


def pair(value):
    parts = (value or "").split("/")
    if len(parts) != 2:
        return None, None
    return quantity_bytes(parts[0]), quantity_bytes(parts[1])


def container_ids():
    output = command(
        [
            "docker",
            "ps",
            "--filter",
            f"label=com.docker.compose.project={compose_project}",
            "--format",
            '{{.ID}}\t{{.Label "com.docker.compose.service"}}',
        ]
    )
    found = {}
    for line in output.splitlines():
        container_id, service = line.split("\t", 1)
        if service in services:
            found[service] = container_id
    return found


def container_statistics(ids):
    if not ids:
        return {}
    output = command(
        ["docker", "stats", "--no-stream", "--format", "{{json .}}"]
        + list(ids.values()),
        timeout=max(10, len(ids) * 5),
    )
    by_container = {}
    for line in output.splitlines():
        data = json.loads(line)
        container_id = data.get("Container", "")
        by_container[container_id] = data
    return {
        service: by_container.get(container_id, {})
        for service, container_id in ids.items()
    }


def database_statistics(database_id):
    if not database_id:
        return None, None, None
    sql = (
        "SELECT count(*), "
        "count(*) FILTER (WHERE state = 'active'), "
        "current_setting('max_connections') "
        "FROM pg_stat_activity;"
    )
    output = command(
        [
            "docker", "exec", database_id, "psql",
            "-U", database_user, "-d", database_name,
            "-At", "-F", ",", "-c", sql,
        ]
    )
    total, active, maximum = output.split(",")
    return int(total), int(active), int(maximum)


ACCESS_LOG_PATTERN = re.compile(
    r"\s(?:GET|POST|PUT|PATCH|DELETE|HEAD|OPTIONS)\s+/\S*\s+\d{3}\s"
)
FINISH_SIGNAL_PATTERN = re.compile(
    r"\sGET\s+/__miyp_benchmark_finished__/(success|failure)\s+\d{3}\s"
)
DENSITY_PHASE_PATTERN = re.compile(
    r"\sGET\s+/__miyp_benchmark_density__/(\d+)/([0-9.]+)/"
    r"([A-Za-z0-9_.-]+)\s+\d{3}\s"
)
ADMISSION_PHASE_PATTERN = re.compile(
    r"\sGET\s+/__miyp_benchmark_admission__/(\d+)/(\d+)/"
    r"([A-Za-z0-9_.-]+)\s+\d{3}\s"
)


def request_activity(nginx_id, since):
    checked_until = datetime.now(timezone.utc)
    if not nginx_id:
        return 0, [], [], [], checked_until
    output = command(
        [
            "docker", "logs", "--timestamps",
            "--since", since.isoformat(),
            "--until", checked_until.isoformat(),
            nginx_id,
        ]
    )
    application_requests = 0
    finish_signals = []
    density_signals = []
    admission_signals = []
    for line in output.splitlines():
        finish_match = FINISH_SIGNAL_PATTERN.search(line)
        density_match = DENSITY_PHASE_PATTERN.search(line)
        admission_match = ADMISSION_PHASE_PATTERN.search(line)
        if finish_match:
            finish_signals.append(finish_match.group(1))
        elif density_match:
            density_signals.append(
                (
                    int(density_match.group(1)),
                    float(density_match.group(2)),
                    density_match.group(3),
                )
            )
        elif admission_match:
            admission_signals.append(
                (
                    int(admission_match.group(1)),
                    int(admission_match.group(2)),
                    admission_match.group(3),
                )
            )
        elif ACCESS_LOG_PATTERN.search(line):
            application_requests += 1
    return (
        application_requests,
        finish_signals,
        density_signals,
        admission_signals,
        checked_until,
    )


fieldnames = [
    "timestamp_utc",
    "elapsed_seconds",
    "host_cpu_percent",
    "host_memory_used_mib",
    "host_memory_available_mib",
    "host_load_1m",
    "nginx_requests_since_previous_sample",
    "seconds_since_last_request",
    "density_phase",
    "density_maximum_pause_seconds",
    "admission_phase",
    "admitted_users",
]
for service in services:
    fieldnames.extend(
        [
            f"{service}_cpu_percent",
            f"{service}_memory_used_bytes",
            f"{service}_memory_limit_bytes",
            f"{service}_memory_percent",
            f"{service}_network_received_bytes",
            f"{service}_network_sent_bytes",
            f"{service}_block_read_bytes",
            f"{service}_block_written_bytes",
            f"{service}_pids",
        ]
    )
fieldnames.extend(
    [
        "postgres_connections_total",
        "postgres_connections_active",
        "postgres_max_connections",
    ]
)

started_at = utc_now()
started_monotonic = time.monotonic()
metadata = {
    "started_at_utc": started_at,
    "finished_at_utc": None,
    "sample_interval_seconds": interval,
    "final_idle_seconds": final_idle_seconds,
    "hostname": platform.node(),
    "platform": platform.platform(),
    "logical_cpus": os.cpu_count(),
    "total_memory_mib": round(
        int(
            next(
                line.split()[1]
                for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines()
                if line.startswith("MemTotal:")
            )
        ) / 1024,
        3,
    ),
    "docker_version": command(["docker", "--version"]),
    "clock_ntp_synchronized": "unavailable",
    "compose_project": compose_project,
    "services": {
        "web": web_service,
        "database": database_service,
        "proxy": proxy_service,
    },
    "database_name": database_name,
    "sample_count": 0,
    "measurement_scope": (
        "Whole-host /proc metrics, Docker container statistics, and PostgreSQL "
        "connection counts sampled on the MIYP application server."
    ),
    "activity_detection": (
        "Nginx access-log request lines. Automatic shutdown is armed only by "
        "the requester's explicit benchmark-finished signal, after which a "
        "full idle interval is recorded."
    ),
}
try:
    metadata["clock_ntp_synchronized"] = command(
        ["timedatectl", "show", "--property=NTPSynchronized", "--value"]
    ) or "unknown"
except Exception as exc:
    record_event(f"clock_status_unavailable {type(exc).__name__}: {exc}")
metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
events_path.write_text(f"{started_at} monitoring_started\n", encoding="utf-8")

signal.signal(signal.SIGINT, stop_monitoring)
signal.signal(signal.SIGTERM, stop_monitoring)
previous_total, previous_idle = cpu_totals()

with csv_path.open("w", newline="", encoding="utf-8") as handle:
    writer = csv.DictWriter(handle, fieldnames=fieldnames)
    writer.writeheader()
    handle.flush()

    while running:
        iteration_started = time.monotonic()
        current_total, current_idle = cpu_totals()
        total_delta = current_total - previous_total
        idle_delta = current_idle - previous_idle
        host_cpu = (
            0.0 if total_delta <= 0 else 100 * (1 - idle_delta / total_delta)
        )
        previous_total, previous_idle = current_total, current_idle
        memory_used, memory_available = memory_values()
        row = {
            "timestamp_utc": utc_now(),
            "elapsed_seconds": round(time.monotonic() - started_monotonic, 3),
            "host_cpu_percent": round(host_cpu, 3),
            "host_memory_used_mib": round(memory_used, 3),
            "host_memory_available_mib": round(memory_available, 3),
            "host_load_1m": round(os.getloadavg()[0], 3),
            "nginx_requests_since_previous_sample": 0,
            "seconds_since_last_request": None,
            "density_phase": current_density_phase,
            "density_maximum_pause_seconds": current_density_maximum_pause,
            "admission_phase": current_admission_phase,
            "admitted_users": current_admitted_users,
        }

        ids = {}
        try:
            ids = container_ids()
            stats = container_statistics(ids)
            for service in services:
                data = stats.get(service, {})
                memory_used_bytes, memory_limit_bytes = pair(data.get("MemUsage"))
                network_received, network_sent = pair(data.get("NetIO"))
                block_read, block_written = pair(data.get("BlockIO"))
                row.update(
                    {
                        f"{service}_cpu_percent": percentage(data.get("CPUPerc")),
                        f"{service}_memory_used_bytes": memory_used_bytes,
                        f"{service}_memory_limit_bytes": memory_limit_bytes,
                        f"{service}_memory_percent": percentage(data.get("MemPerc")),
                        f"{service}_network_received_bytes": network_received,
                        f"{service}_network_sent_bytes": network_sent,
                        f"{service}_block_read_bytes": block_read,
                        f"{service}_block_written_bytes": block_written,
                        f"{service}_pids": int(data["PIDs"]) if data.get("PIDs") else None,
                    }
                )
        except Exception as exc:
            record_event(f"container_sample_error {type(exc).__name__}: {exc}")

        try:
            total, active, maximum = database_statistics(ids.get(database_service))
            row.update(
                {
                    "postgres_connections_total": total,
                    "postgres_connections_active": active,
                    "postgres_max_connections": maximum,
                }
            )
        except Exception as exc:
            record_event(f"database_sample_error {type(exc).__name__}: {exc}")

        try:
            (
                requests_seen,
                finish_signals,
                density_signals,
                admission_signals,
                log_cursor,
            ) = request_activity(ids.get(proxy_service), log_cursor)
            row["nginx_requests_since_previous_sample"] = requests_seen
            if requests_seen:
                request_log_lines += requests_seen
                last_request_monotonic = time.monotonic()
                if request_log_lines == requests_seen:
                    record_event("request_activity_started")
            if finish_signals:
                benchmark_finish_status = finish_signals[-1]
                benchmark_finished_monotonic = time.monotonic()
                last_request_monotonic = benchmark_finished_monotonic
                record_event(
                    "benchmark_finished_signal "
                    f"status={benchmark_finish_status}"
                )
            if density_signals:
                _phase_number, current_density_maximum_pause, current_density_phase = (
                    density_signals[-1]
                )
                row["density_phase"] = current_density_phase
                row["density_maximum_pause_seconds"] = current_density_maximum_pause
                record_event(
                    "density_phase "
                    f"phase={current_density_phase} "
                    f"maximum_pause_seconds={current_density_maximum_pause}"
                )
            if admission_signals:
                _phase_number, current_admitted_users, current_admission_phase = (
                    admission_signals[-1]
                )
                row["admission_phase"] = current_admission_phase
                row["admitted_users"] = current_admitted_users
                record_event(
                    "admission_phase "
                    f"phase={current_admission_phase} "
                    f"admitted_users={current_admitted_users}"
                )
        except Exception as exc:
            record_event(f"request_activity_error {type(exc).__name__}: {exc}")

        if last_request_monotonic is not None:
            seconds_since_request = time.monotonic() - last_request_monotonic
            row["seconds_since_last_request"] = round(seconds_since_request, 3)
            if (
                benchmark_finished_monotonic is not None
                and seconds_since_request >= final_idle_seconds
            ):
                running = False
                stop_reason = "benchmark_finished_and_idle"
                record_event(
                    f"final_idle_complete requests_observed={request_log_lines} "
                    f"idle_seconds={seconds_since_request:.3f}"
                )

        writer.writerow(row)
        handle.flush()
        sample_count += 1
        if sample_count == 1 or sample_count % 10 == 0:
            print(
                f"{row['timestamp_utc']} samples={sample_count} "
                f"host_cpu={row['host_cpu_percent']:.1f}%",
                flush=True,
            )
        remaining = interval - (time.monotonic() - iteration_started)
        if remaining > 0:
            time.sleep(remaining)

finished_at = utc_now()
metadata["finished_at_utc"] = finished_at
metadata["sample_count"] = sample_count
metadata["nginx_request_log_lines_observed"] = request_log_lines
metadata["benchmark_finish_status"] = benchmark_finish_status
metadata["stop_reason"] = stop_reason
metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
record_event("monitoring_stopped")
print(f"Monitoring stopped after {sample_count} samples.", flush=True)
PY

if (( used_sudo )); then
    sudo chown -R "$(id -u):$(id -g)" "$output_dir"
fi

[[ -s "$output_dir/server-samples.csv" ]] || {
    printf 'No server samples were recorded.\n' >&2
    exit 1
}

printf '\nOK! Server measurements saved to %s\n' "$output_dir"
printf 'Retrieve this directory with the requester results.\n'
