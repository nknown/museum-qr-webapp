#!/usr/bin/env python3
"""Concurrent anonymous-presentation journey benchmark for MIYP."""

from __future__ import annotations

import argparse
import csv
import hashlib
import itertools
import json
import math
import os
import platform
import random
import re
import statistics
import subprocess
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Callable, Iterable
from urllib.parse import urljoin, urlparse

import requests


if __package__:
    from .target import add_target_arguments, resolve_target
else:
    from target import add_target_arguments, resolve_target

TRACKING_URL_RE = re.compile(
    r"""const\s+slideTrackingUrl\s*=\s*["']([^"']*)["']"""
)
SLIDE_INDEX_RE = re.compile(r"""data-slide-index=["'](\d+)["']""")
PRESENTATION_MARKER = 'data-presentation-type="user_device"'
DEFAULT_CA_CERTIFICATE = (
    Path(__file__).resolve().parents[1]
    / "global_files"
    / "certificates"
    / "miyp-selfsigned.crt"
)


@dataclass
class RequestMeasurement:
    level: int
    repeat: int
    user: int
    journey: int
    request_kind: str
    status_code: int
    duration_ms: float
    transferred_bytes: int
    ok: bool
    error: str = ""
    target_url: str = ""
    started_at_utc: str = ""
    finished_at_utc: str = ""
    slide_indices: list[int] | None = None


class HostSampler:
    """Samples whole-host CPU and available memory during a trial."""

    def __init__(self, interval: float = 0.25) -> None:
        self.interval = interval
        self.samples: list[dict[str, float]] = []
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    @staticmethod
    def _cpu_totals() -> tuple[int, int]:
        values = Path("/proc/stat").read_text(encoding="utf-8").splitlines()[0].split()
        ticks = [int(value) for value in values[1:]]
        idle = ticks[3] + (ticks[4] if len(ticks) > 4 else 0)
        return sum(ticks), idle

    @staticmethod
    def _available_memory_mib() -> float:
        for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
            if line.startswith("MemAvailable:"):
                return int(line.split()[1]) / 1024
        return 0.0

    def start(self) -> None:
        previous_total, previous_idle = self._cpu_totals()

        def sample() -> None:
            nonlocal previous_total, previous_idle
            while not self._stop.wait(self.interval):
                total, idle = self._cpu_totals()
                total_delta = total - previous_total
                idle_delta = idle - previous_idle
                cpu = 0.0 if total_delta <= 0 else 100 * (1 - idle_delta / total_delta)
                self.samples.append(
                    {
                        "cpu_percent": round(cpu, 3),
                        "memory_available_mib": round(self._available_memory_mib(), 3),
                    }
                )
                previous_total, previous_idle = total, idle

        self._thread = threading.Thread(target=sample, daemon=True)
        self._thread.start()

    def stop(self) -> dict[str, float | None]:
        self._stop.set()
        if self._thread:
            self._thread.join(timeout=2)
        cpu_values = [sample["cpu_percent"] for sample in self.samples]
        memory_values = [sample["memory_available_mib"] for sample in self.samples]
        return {
            "host_cpu_mean_percent": round(sum(cpu_values) / len(cpu_values), 3)
            if cpu_values
            else None,
            "host_cpu_peak_percent": round(max(cpu_values), 3) if cpu_values else None,
            "host_memory_min_available_mib": round(min(memory_values), 3)
            if memory_values
            else None,
        }


class ActiveUserTracker:
    """Track the number of virtual visitors whose journeys are in progress."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.active = 0
        self.peak = 0

    def enter(self) -> None:
        with self._lock:
            self.active += 1
            self.peak = max(self.peak, self.active)

    def leave(self) -> None:
        with self._lock:
            self.active -= 1


def sequential_arrival_offsets(
    visitor_count: int,
    minimum_gap: float,
    maximum_gap: float,
    seed: int,
) -> list[float]:
    """Return cumulative, reproducible arrival times for one trial."""
    random_generator = random.Random(seed)
    offsets: list[float] = []
    next_offset = 0.0
    for visitor_index in range(visitor_count):
        if visitor_index:
            next_offset += random_generator.uniform(minimum_gap, maximum_gap)
        offsets.append(next_offset)
    return offsets


def navigation_path(
    slide_indices: list[int],
    random_generator: random.Random,
    minimum_changes: int,
    maximum_changes: int,
) -> list[int]:
    """Model a bounded back-and-forth sequence of actual page changes."""
    if len(slide_indices) < 2:
        return []

    change_count = random_generator.randint(minimum_changes, maximum_changes)
    current_position = 0
    final_position = len(slide_indices) - 1
    direction = 1
    path: list[int] = []
    for _ in range(change_count):
        next_position = current_position + direction
        if next_position < 0 or next_position > final_position:
            direction *= -1
            next_position = current_position + direction
        current_position = next_position
        path.append(slide_indices[current_position])
    return path


def percentile(values: Iterable[float], percentage: float) -> float:
    ordered = sorted(values)
    if not ordered:
        return 0.0
    index = max(0, math.ceil((percentage / 100) * len(ordered)) - 1)
    return ordered[index]


def transferred_size(response: requests.Response) -> int:
    content_length = response.headers.get("Content-Length")
    if content_length and content_length.isdigit():
        return int(content_length)
    return len(response.content)


def clock_synchronization_status() -> str:
    try:
        return subprocess.run(
            ["timedatectl", "show", "--property=NTPSynchronized", "--value"],
            check=True,
            capture_output=True,
            text=True,
            timeout=5,
        ).stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unavailable"


def decode_javascript_string(value: str) -> str:
    """Decode Django escapejs output as a JavaScript/JSON string literal."""
    return json.loads(f'"{value}"')


def make_measurement(
    *,
    level: int,
    repeat: int,
    user: int,
    journey: int,
    request_kind: str,
    started_at: float,
    started_at_utc: str,
    target_url: str,
    response: requests.Response | None = None,
    error: Exception | None = None,
    slide_indices: list[int] | None = None,
) -> RequestMeasurement:
    duration_ms = (time.perf_counter() - started_at) * 1000
    finished_at_utc = datetime.now(timezone.utc).isoformat()
    if response is None:
        return RequestMeasurement(
            level=level,
            repeat=repeat,
            user=user,
            journey=journey,
            request_kind=request_kind,
            status_code=0,
            duration_ms=duration_ms,
            transferred_bytes=0,
            ok=False,
            error=str(error) if error else "no response",
            target_url=target_url,
            started_at_utc=started_at_utc,
            finished_at_utc=finished_at_utc,
            slide_indices=slide_indices,
        )
    return RequestMeasurement(
        level=level,
        repeat=repeat,
        user=user,
        journey=journey,
        request_kind=request_kind,
        status_code=response.status_code,
        duration_ms=duration_ms,
        transferred_bytes=transferred_size(response),
        ok=response.status_code == 200,
        error="" if response.status_code == 200 else f"HTTP {response.status_code}",
        target_url=target_url,
        started_at_utc=started_at_utc,
        finished_at_utc=finished_at_utc,
        slide_indices=slide_indices,
    )


def run_user(
    *,
    presentation_urls: list[str],
    start_index: int,
    level: int,
    repeat: int,
    user_number: int,
    journeys: int,
    timeout: float,
    think_min: float,
    think_max: float,
    journey_think_min: float,
    journey_think_max: float,
    navigation_changes_min: int,
    navigation_changes_max: int,
    stop_at_monotonic: float | None = None,
    density_ramp_start_monotonic: float | None = None,
    density_step_seconds: float = 60,
    density_min_think_max: float = 1,
    stop_event: threading.Event | None = None,
    measurement_callback: Callable[[RequestMeasurement], None] | None = None,
    synthetic_slide_events: int = 0,
    tracking_batch_size: int = 20,
    tls_verify: bool | str = True,
) -> tuple[list[RequestMeasurement], list[str]]:
    measurements: list[RequestMeasurement] = []
    session_keys: list[str] = []
    session = requests.Session()
    session.verify = tls_verify
    session.headers.update(
        {
            "User-Agent": "MIYP-Academic-Benchmark/1.0",
            "Accept": "text/html,application/xhtml+xml",
        }
    )
    random_generator = random.Random(
        level * 1_000_000 + repeat * 10_000 + user_number
    )

    def record(measurement: RequestMeasurement) -> None:
        measurements.append(measurement)
        if measurement_callback is not None:
            measurement_callback(measurement)

    def should_stop() -> bool:
        return (
            (stop_event is not None and stop_event.is_set())
            or (
                stop_at_monotonic is not None
                and time.perf_counter() >= stop_at_monotonic
            )
        )

    def interruptible_wait(wait_seconds: float) -> bool:
        if should_stop():
            return False
        if stop_at_monotonic is not None:
            wait_seconds = min(
                wait_seconds,
                max(0.0, stop_at_monotonic - time.perf_counter()),
            )
        if stop_event is not None:
            stop_event.wait(wait_seconds)
        else:
            time.sleep(wait_seconds)
        return not should_stop()

    def current_maximum(initial_maximum: float) -> float:
        if (
            density_ramp_start_monotonic is None
            or time.perf_counter() < density_ramp_start_monotonic
        ):
            return initial_maximum
        completed_steps = int(
            (time.perf_counter() - density_ramp_start_monotonic)
            // density_step_seconds
        ) + 1
        return max(density_min_think_max, initial_maximum - completed_steps)

    def wait_until_action(wait_seconds: float) -> bool:
        """Wait for an action unless the shared sustained-trial deadline arrives."""
        return interruptible_wait(wait_seconds)

    journey_numbers: Iterable[int] = (
        range(1, journeys + 1)
        if stop_at_monotonic is None and stop_event is None
        else itertools.count(1)
    )
    for journey in journey_numbers:
        if should_stop():
            break
        if journey > 1 and journey_think_max > 0:
            current_journey_max = current_maximum(journey_think_max)
            if not wait_until_action(
                random_generator.uniform(
                    min(journey_think_min, current_journey_max),
                    current_journey_max,
                )
            ):
                break
        target_url = presentation_urls[
            (start_index + journey - 1) % len(presentation_urls)
        ]
        request_started_at_utc = datetime.now(timezone.utc).isoformat()
        started_at = time.perf_counter()
        try:
            response = session.get(target_url, timeout=timeout)
            measurement = make_measurement(
                level=level,
                repeat=repeat,
                user=user_number,
                journey=journey,
                request_kind="presentation",
                started_at=started_at,
                started_at_utc=request_started_at_utc,
                target_url=target_url,
                response=response,
            )
        except requests.RequestException as exc:
            record(
                make_measurement(
                    level=level,
                    repeat=repeat,
                    user=user_number,
                    journey=journey,
                    request_kind="presentation",
                    started_at=started_at,
                    started_at_utc=request_started_at_utc,
                    target_url=target_url,
                    error=exc,
                )
            )
            continue

        if measurement.ok and PRESENTATION_MARKER not in response.text:
            measurement.ok = False
            measurement.error = "response was not a user-device presentation"
        record(measurement)
        if not measurement.ok:
            continue
        if should_stop():
            break

        session_cookie = session.cookies.get("sessionid")
        if session_cookie:
            session_keys.append(session_cookie)

        tracking_match = TRACKING_URL_RE.search(response.text)
        slide_indices = sorted({int(value) for value in SLIDE_INDEX_RE.findall(response.text)})
        if not tracking_match or not tracking_match.group(1):
            validation_timestamp = datetime.now(timezone.utc).isoformat()
            record(
                RequestMeasurement(
                    level=level,
                    repeat=repeat,
                    user=user_number,
                    journey=journey,
                    request_kind="validation",
                    status_code=0,
                    duration_ms=0,
                    transferred_bytes=0,
                    ok=False,
                    error="slide tracking URL was not present",
                    target_url=target_url,
                    started_at_utc=validation_timestamp,
                    finished_at_utc=validation_timestamp,
                )
            )
            continue

        try:
            tracking_path = decode_javascript_string(tracking_match.group(1))
        except (json.JSONDecodeError, UnicodeDecodeError) as exc:
            validation_timestamp = datetime.now(timezone.utc).isoformat()
            record(
                RequestMeasurement(
                    level=level,
                    repeat=repeat,
                    user=user_number,
                    journey=journey,
                    request_kind="validation",
                    status_code=0,
                    duration_ms=0,
                    transferred_bytes=0,
                    ok=False,
                    error=f"invalid JavaScript tracking URL: {exc}",
                    target_url=target_url,
                    started_at_utc=validation_timestamp,
                    finished_at_utc=validation_timestamp,
                )
            )
            continue
        tracking_url = urljoin(response.url, tracking_path)
        presentation_origin = urlparse(response.url)
        event_indices = navigation_path(
            slide_indices,
            random_generator,
            navigation_changes_min,
            navigation_changes_max,
        )
        if synthetic_slide_events:
            # Alternate indexes to model distinct page transitions without
            # changing curator-managed benchmark content.
            event_indices = [
                1 + (index % 2)
                for index in range(synthetic_slide_events)
            ]

        pending_slide_events: list[dict[str, int | str]] = []
        tracking_flush_due: float | None = None

        def flush_slide_tracking() -> None:
            nonlocal tracking_flush_due
            event_batch = pending_slide_events[:tracking_batch_size]
            del pending_slide_events[:tracking_batch_size]
            request_started_at_utc = datetime.now(timezone.utc).isoformat()
            started_at = time.perf_counter()
            try:
                slide_response = session.post(
                    tracking_url,
                    json={"events": event_batch},
                    headers={
                        "Accept": "application/json",
                        "X-CSRFToken": session.cookies.get("csrftoken", ""),
                        # HTTPS CSRF validation also checks the request origin.
                        "Origin": (
                            f"{presentation_origin.scheme}://"
                            f"{presentation_origin.netloc}"
                        ),
                        "Referer": response.url,
                    },
                    timeout=timeout,
                )
                record(
                    make_measurement(
                        level=level,
                        repeat=repeat,
                        user=user_number,
                        journey=journey,
                        request_kind="slide_tracking",
                        started_at=started_at,
                        started_at_utc=request_started_at_utc,
                        target_url=target_url,
                        response=slide_response,
                        slide_indices=[
                            int(event["slide_index"])
                            for event in event_batch
                        ],
                    )
                )
            except requests.RequestException as exc:
                record(
                    make_measurement(
                        level=level,
                        repeat=repeat,
                        user=user_number,
                        journey=journey,
                        request_kind="slide_tracking",
                        started_at=started_at,
                        started_at_utc=request_started_at_utc,
                        target_url=target_url,
                        error=exc,
                        slide_indices=[
                            int(event["slide_index"])
                            for event in event_batch
                        ],
                    )
                )
            tracking_flush_due = (
                time.perf_counter() + random_generator.uniform(0.25, 0.75)
                if pending_slide_events
                else None
            )

        def wait_while_flushing(wait_seconds: float) -> bool:
            end_time = time.perf_counter() + wait_seconds
            if stop_at_monotonic is not None:
                end_time = min(end_time, stop_at_monotonic)
            while (
                tracking_flush_due is not None
                and tracking_flush_due <= end_time
            ):
                remaining = tracking_flush_due - time.perf_counter()
                if remaining > 0 and not interruptible_wait(remaining):
                    return False
                flush_slide_tracking()
            remaining = end_time - time.perf_counter()
            if remaining > 0 and not interruptible_wait(remaining):
                return False
            return not should_stop()

        deadline_reached = False
        for slide_index in event_indices:
            if think_max > 0:
                current_think_max = current_maximum(think_max)
                if not wait_while_flushing(
                    random_generator.uniform(
                        min(think_min, current_think_max),
                        current_think_max,
                    )
                ):
                    deadline_reached = True
                    break
            elif should_stop():
                deadline_reached = True
                break
            pending_slide_events.append(
                {
                    "slide_index": slide_index,
                    "occurred_at": datetime.now(timezone.utc).isoformat(),
                }
            )
            if tracking_flush_due is None:
                # Matches the public presentation's non-urgent tracking delay.
                tracking_flush_due = time.perf_counter() + random_generator.uniform(
                    2.5, 6.0
                )

        while pending_slide_events:
            if should_stop():
                pending_slide_events.clear()
                deadline_reached = True
                break
            if stop_at_monotonic is not None:
                # Moving to another presentation (or ending at the shared
                # deadline) hides the page, so the browser flushes immediately.
                flush_slide_tracking()
                if should_stop():
                    deadline_reached = True
                continue
            if not wait_while_flushing(
                max(0.0, (tracking_flush_due or time.perf_counter()) - time.perf_counter())
            ):
                deadline_reached = True
        if deadline_reached:
            break
    return measurements, session_keys


def summarize_trial(
    measurements: list[RequestMeasurement],
    *,
    level: int,
    repeat: int,
    elapsed_seconds: float,
    host_metrics: dict[str, float | None],
    started_at_utc: str,
    finished_at_utc: str,
    peak_active_users: int,
    hold_after_target_seconds: float,
) -> dict[str, float | int | str | None]:
    request_rows = [row for row in measurements if row.request_kind != "validation"]
    durations = [row.duration_ms for row in request_rows]
    failures = [row for row in measurements if not row.ok]
    return {
        "scheduled_visitors": level,
        "peak_active_users": peak_active_users,
        "hold_after_target_seconds": hold_after_target_seconds,
        "repeat": repeat,
        "started_at_utc": started_at_utc,
        "finished_at_utc": finished_at_utc,
        "elapsed_seconds": round(elapsed_seconds, 3),
        "requests": len(request_rows),
        "failures": len(failures),
        "error_rate_percent": round(100 * len(failures) / max(len(measurements), 1), 3),
        "throughput_requests_per_second": round(
            len(request_rows) / max(elapsed_seconds, 0.000001), 3
        ),
        "latency_median_ms": round(percentile(durations, 50), 3),
        "latency_p95_ms": round(percentile(durations, 95), 3),
        "latency_p99_ms": round(percentile(durations, 99), 3),
        "transferred_bytes": sum(row.transferred_bytes for row in request_rows),
        **host_metrics,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Benchmark real MIYP anonymous user-device presentation journeys."
    )
    add_target_arguments(parser)
    parser.add_argument(
        "--additional-url",
        action="append",
        default=[],
        help=(
            "Another public presentation URL or relative path. Repeat this option "
            "to spread virtual users across several presentations."
        ),
    )
    parser.add_argument("--levels", default="1,5,10,25,50")
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--journeys-per-user", type=int, default=2)
    parser.add_argument("--think-min", type=float, default=3)
    parser.add_argument("--think-max", type=float, default=12)
    parser.add_argument(
        "--navigation-changes-min",
        type=int,
        default=1,
        help="Minimum page changes made during each presentation journey.",
    )
    parser.add_argument(
        "--navigation-changes-max",
        type=int,
        default=12,
        help="Maximum page changes made during each presentation journey.",
    )
    parser.add_argument(
        "--journey-think-min",
        type=float,
        default=5,
        help="Minimum pause before a visitor opens its next presentation.",
    )
    parser.add_argument(
        "--journey-think-max",
        type=float,
        default=15,
        help="Maximum pause before a visitor opens its next presentation.",
    )
    parser.add_argument(
        "--arrival-gap-min",
        type=float,
        default=1,
        help="Minimum seconds between consecutive visitor arrivals.",
    )
    parser.add_argument(
        "--arrival-gap-max",
        type=float,
        default=10,
        help="Maximum seconds between consecutive visitor arrivals.",
    )
    parser.add_argument(
        "--hold-after-target-seconds",
        type=float,
        default=0,
        help=(
            "Keep every visitor active through the ramp and stop this many "
            "seconds after the final visitor arrives. Zero uses finite journeys."
        ),
    )
    parser.add_argument(
        "--density-ramp",
        action="store_true",
        help=(
            "After reaching the target and the initial hold, lower the maximum "
            "random action pause by one second after every density step."
        ),
    )
    parser.add_argument(
        "--density-initial-hold-seconds",
        type=float,
        default=10,
        help="Seconds to retain the initial pause range after the final arrival.",
    )
    parser.add_argument(
        "--density-step-seconds",
        type=float,
        default=60,
        help="Seconds spent at each progressively lower maximum pause.",
    )
    parser.add_argument(
        "--density-min-think-max",
        type=float,
        default=1,
        help="Final maximum random pause in the density ramp.",
    )
    parser.add_argument(
        "--admission-ramp",
        action="store_true",
        help=(
            "Keep existing visitors active while adding visitors in stages, and "
            "stop after consecutive stages with completed requests but no successes."
        ),
    )
    parser.add_argument(
        "--admission-step-users",
        type=int,
        default=1,
        help="Visitors added at the start of each admission stage.",
    )
    parser.add_argument(
        "--admission-step-seconds",
        type=float,
        default=60,
        help="Observation time after each admission stage.",
    )
    parser.add_argument(
        "--admission-failure-stages",
        type=int,
        default=2,
        help=(
            "Consecutive stages with at least one completed request and zero "
            "successful requests required to stop."
        ),
    )
    parser.add_argument(
        "--cooldown-seconds",
        type=float,
        default=10,
        help="Pause between trials so transient work can settle.",
    )
    parser.add_argument("--timeout", type=float, default=15)
    parser.add_argument(
        "--synthetic-slide-events",
        type=int,
        default=0,
        help="Override discovered slides with this many alternating transition events.",
    )
    parser.add_argument(
        "--tracking-batch-size",
        type=int,
        default=20,
        help="Maximum slide events sent in each tracking request.",
    )
    parser.add_argument("--output-dir", default="benchmarks/results")
    parser.add_argument(
        "--ca-certificate",
        type=Path,
        default=DEFAULT_CA_CERTIFICATE,
        help=(
            "CA or self-signed certificate used to verify HTTPS. Defaults to "
            "global_files/certificates/miyp-selfsigned.crt."
        ),
    )
    parser.add_argument(
        "--system-ca",
        action="store_true",
        help="Use the operating system CA store instead of --ca-certificate.",
    )
    return resolve_target(parser, parser.parse_args())


def main() -> int:
    args = parse_args()
    parsed_url = urlparse(args.url)
    if parsed_url.scheme not in {"http", "https"} or "/presentation/" not in parsed_url.path:
        raise SystemExit("--url must be an HTTP(S) public presentation URL")
    target_urls = [args.url]
    for value in args.additional_url:
        candidate = urlparse(value)
        if not candidate.scheme and not candidate.netloc:
            additional_base = urlparse(args.base_url or "")
            if additional_base.scheme not in {"http", "https"} or not additional_base.netloc:
                raise SystemExit(
                    "a relative --additional-url requires --base-url"
                )
            candidate_url = urljoin(args.base_url.rstrip("/") + "/", value)
        else:
            candidate_url = value
        candidate = urlparse(candidate_url)
        if (
            candidate.scheme not in {"http", "https"}
            or not candidate.netloc
            or "/presentation/" not in candidate.path
        ):
            raise SystemExit(
                "--additional-url values must be HTTP(S) public presentation URLs"
            )
        if (candidate.scheme, candidate.netloc) != (parsed_url.scheme, parsed_url.netloc):
            raise SystemExit("all presentation URLs must use the same MIYP server")
        if candidate_url not in target_urls:
            target_urls.append(candidate_url)

    if args.think_min < 0 or args.think_max < args.think_min:
        raise SystemExit("think times must satisfy 0 <= think-min <= think-max")
    if (
        args.navigation_changes_min < 1
        or args.navigation_changes_max < args.navigation_changes_min
    ):
        raise SystemExit(
            "navigation changes must satisfy "
            "1 <= navigation-changes-min <= navigation-changes-max"
        )
    if (
        args.journey_think_min < 0
        or args.journey_think_max < args.journey_think_min
    ):
        raise SystemExit(
            "journey think times must satisfy "
            "0 <= journey-think-min <= journey-think-max"
        )
    if args.arrival_gap_min < 0 or args.arrival_gap_max < args.arrival_gap_min:
        raise SystemExit(
            "arrival gaps must satisfy "
            "0 <= arrival-gap-min <= arrival-gap-max"
        )
    if args.hold_after_target_seconds < 0:
        raise SystemExit("--hold-after-target-seconds must be non-negative")
    if args.density_ramp:
        if args.density_initial_hold_seconds < 0:
            raise SystemExit("--density-initial-hold-seconds must be non-negative")
        if args.density_step_seconds <= 0:
            raise SystemExit("--density-step-seconds must be greater than zero")
        if not 0 <= args.density_min_think_max < args.think_max:
            raise SystemExit(
                "--density-min-think-max must be non-negative and below --think-max"
            )
        if (args.think_max - args.density_min_think_max) % 1:
            raise SystemExit(
                "density ramp requires a whole number of one-second reductions"
            )
    if args.admission_ramp:
        if args.density_ramp or args.hold_after_target_seconds > 0:
            raise SystemExit(
                "--admission-ramp cannot be combined with density or fixed-hold modes"
            )
        if args.admission_step_users < 1:
            raise SystemExit("--admission-step-users must be positive")
        if args.admission_step_seconds <= 0:
            raise SystemExit("--admission-step-seconds must be greater than zero")
        if args.admission_failure_stages < 1:
            raise SystemExit("--admission-failure-stages must be positive")
    if args.cooldown_seconds < 0:
        raise SystemExit("--cooldown-seconds must be non-negative")
    if args.synthetic_slide_events < 0:
        raise SystemExit("--synthetic-slide-events must be non-negative")
    if not 1 <= args.tracking_batch_size <= 20:
        raise SystemExit("--tracking-batch-size must be between 1 and 20")

    levels = [int(value.strip()) for value in args.levels.split(",") if value.strip()]
    if not levels or min(levels) < 1:
        raise SystemExit("--levels must contain positive integers")
    if args.admission_ramp and (len(levels) != 1 or args.repeats != 1):
        raise SystemExit(
            "admission mode requires one maximum in --levels and --repeats 1"
        )

    tls_verify: bool | str = True
    tls_configuration: dict[str, str] = {
        "verification": (
            "system CA store"
            if parsed_url.scheme == "https"
            else "not applicable (HTTP)"
        )
    }
    if parsed_url.scheme == "https" and not args.system_ca:
        certificate_path = args.ca_certificate.expanduser().resolve()
        if not certificate_path.is_file():
            raise SystemExit(
                f"HTTPS certificate not found: {certificate_path}. "
                "Start the Nginx service first or pass --system-ca."
            )
        tls_verify = str(certificate_path)
        tls_configuration = {
            "verification": "explicit CA certificate",
            "certificate_path": str(certificate_path),
            "certificate_sha256": hashlib.sha256(
                certificate_path.read_bytes()
            ).hexdigest(),
        }

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_id = f"load-{timestamp}"
    all_measurements: list[RequestMeasurement] = []
    trial_summaries: list[dict[str, float | int | str | None]] = []
    all_session_keys: set[str] = set()
    density_phase_rows: list[dict[str, object]] = []
    admission_phase_rows: list[dict[str, object]] = []
    admission_stop_reason: str | None = None

    total_trials = len(levels) * args.repeats
    trial_number = 0
    for level in levels:
        for repeat in range(1, args.repeats + 1):
            trial_number += 1
            if args.admission_ramp:
                active_users = ActiveUserTracker()
                sampler = HostSampler()
                sampler.start()
                stop_event = threading.Event()
                live_measurements: list[tuple[float, RequestMeasurement]] = []
                live_lock = threading.Lock()

                def capture_measurement(measurement: RequestMeasurement) -> None:
                    if measurement.request_kind == "validation":
                        return
                    with live_lock:
                        live_measurements.append((time.perf_counter(), measurement))

                trial_started_wallclock = datetime.now(timezone.utc)
                trial_started_at_utc = trial_started_wallclock.isoformat()
                trial_started = time.perf_counter()
                trial_measurements: list[RequestMeasurement] = []
                futures = []
                admitted_users = 0
                consecutive_failed_stages = 0
                admission_stop_reason = "maximum_visitor_guard_reached"

                with ThreadPoolExecutor(max_workers=level) as executor:
                    phase_number = 0
                    phase_measurement_start = 0
                    try:
                        while admitted_users < level:
                            phase_number += 1
                            phase_started = time.perf_counter()
                            phase_started_wallclock = datetime.now(timezone.utc)
                            visitors_added = min(
                                args.admission_step_users,
                                level - admitted_users,
                            )
                            for _ in range(visitors_added):
                                admitted_users += 1
                                user_number = admitted_users
                                active_users.enter()
                                try:
                                    future = executor.submit(
                                        run_user,
                                        presentation_urls=target_urls,
                                        start_index=(user_number + repeat - 2)
                                        % len(target_urls),
                                        level=level,
                                        repeat=repeat,
                                        user_number=user_number,
                                        journeys=args.journeys_per_user,
                                        timeout=args.timeout,
                                        think_min=args.think_min,
                                        think_max=args.think_max,
                                        journey_think_min=args.journey_think_min,
                                        journey_think_max=args.journey_think_max,
                                        navigation_changes_min=args.navigation_changes_min,
                                        navigation_changes_max=args.navigation_changes_max,
                                        stop_event=stop_event,
                                        measurement_callback=capture_measurement,
                                        synthetic_slide_events=args.synthetic_slide_events,
                                        tracking_batch_size=args.tracking_batch_size,
                                        tls_verify=tls_verify,
                                    )
                                except Exception:
                                    active_users.leave()
                                    raise
                                future.add_done_callback(
                                    lambda _future: active_users.leave()
                                )
                                futures.append(future)

                            print(
                                "ADMISSION PHASE "
                                f"{phase_started_wallclock.isoformat()} "
                                f"admitted_users={admitted_users} "
                                f"observation_seconds={args.admission_step_seconds:g}",
                                flush=True,
                            )
                            try:
                                requests.get(
                                    urljoin(
                                        f"{parsed_url.scheme}://{parsed_url.netloc}/",
                                        "__miyp_benchmark_admission__/"
                                        f"{phase_number}/{admitted_users}/stabilization",
                                    ),
                                    timeout=5,
                                    verify=tls_verify,
                                )
                            except requests.RequestException as exc:
                                print(
                                    f"WARNING: admission phase marker failed: {exc}",
                                    flush=True,
                                )

                            # Give the newly admitted population a complete
                            # observation minute after the phase marker is sent.
                            time.sleep(args.admission_step_seconds)
                            phase_finished = time.perf_counter()
                            phase_finished_wallclock = datetime.now(timezone.utc)
                            with live_lock:
                                phase_measurement_end = len(live_measurements)
                                phase_measurements = [
                                    measurement
                                    for _completed_at, measurement in live_measurements[
                                        phase_measurement_start:phase_measurement_end
                                    ]
                                ]
                                phase_measurement_start = phase_measurement_end
                            successful_requests = sum(
                                measurement.ok for measurement in phase_measurements
                            )
                            failed_requests = (
                                len(phase_measurements) - successful_requests
                            )
                            durations = [
                                measurement.duration_ms
                                for measurement in phase_measurements
                            ]
                            stage_failed_completely = bool(phase_measurements) and not bool(
                                successful_requests
                            )
                            consecutive_failed_stages = (
                                consecutive_failed_stages + 1
                                if stage_failed_completely
                                else 0
                            )
                            admission_phase_rows.append(
                                {
                                    "repeat": repeat,
                                    "phase_number": phase_number,
                                    "phase": "population_stabilization",
                                    "visitors_added": visitors_added,
                                    "admitted_users": admitted_users,
                                    "phase_start_utc": phase_started_wallclock.isoformat(),
                                    "phase_end_utc": phase_finished_wallclock.isoformat(),
                                    "elapsed_seconds": round(
                                        phase_finished - phase_started, 3
                                    ),
                                    "completed_requests": len(phase_measurements),
                                    "successful_requests": successful_requests,
                                    "failed_requests": failed_requests,
                                    "error_rate_percent": round(
                                        100
                                        * failed_requests
                                        / max(len(phase_measurements), 1),
                                        3,
                                    ),
                                    "latency_p95_ms": round(
                                        percentile(durations, 95), 3
                                    ),
                                    "consecutive_completely_failed_stages": (
                                        consecutive_failed_stages
                                    ),
                                }
                            )
                            print(
                                f"admitted={admitted_users:>4} "
                                f"requests={len(phase_measurements):>4} "
                                f"successes={successful_requests:>4} "
                                f"errors={100 * failed_requests / max(len(phase_measurements), 1):>6.2f}% "
                                f"p95={percentile(durations, 95):>8.1f} ms",
                                flush=True,
                            )
                            if (
                                consecutive_failed_stages
                                >= args.admission_failure_stages
                            ):
                                admission_stop_reason = (
                                    "consecutive_stages_without_success"
                                )
                                print(
                                    "STOP: the service completed no successful "
                                    f"requests during {consecutive_failed_stages} "
                                    "consecutive observation stages.",
                                    flush=True,
                                )
                                break

                    finally:
                        stop_event.set()
                    for future in as_completed(futures):
                        measurements, session_keys = future.result()
                        trial_measurements.extend(measurements)
                        all_session_keys.update(session_keys)

                elapsed = time.perf_counter() - trial_started
                trial_finished_at_utc = datetime.now(timezone.utc).isoformat()
                host_metrics = sampler.stop()
                all_measurements.extend(trial_measurements)
                trial_summary = summarize_trial(
                    trial_measurements,
                    level=level,
                    repeat=repeat,
                    elapsed_seconds=elapsed,
                    host_metrics=host_metrics,
                    started_at_utc=trial_started_at_utc,
                    finished_at_utc=trial_finished_at_utc,
                    peak_active_users=active_users.peak,
                    hold_after_target_seconds=0,
                )
                trial_summary["admitted_users_at_stop"] = admitted_users
                trial_summary["admission_stop_reason"] = admission_stop_reason
                trial_summaries.append(trial_summary)
                print(
                    f"Admission experiment stopped at {admitted_users} visitors: "
                    f"{admission_stop_reason}.",
                    flush=True,
                )
                continue

            arrival_offsets = sequential_arrival_offsets(
                level,
                args.arrival_gap_min,
                args.arrival_gap_max,
                seed=level * 1_000_000 + repeat * 10_000 + 7_919,
            )
            active_users = ActiveUserTracker()
            sampler = HostSampler()
            sampler.start()
            trial_started_wallclock = datetime.now(timezone.utc)
            trial_started_at_utc = trial_started_wallclock.isoformat()
            trial_started = time.perf_counter()
            density_ramp_start_monotonic = None
            trial_hold_seconds = args.hold_after_target_seconds
            if args.density_ramp:
                reduction_count = int(
                    args.think_max - args.density_min_think_max
                )
                trial_hold_seconds = (
                    args.density_initial_hold_seconds
                    + reduction_count * args.density_step_seconds
                )
                density_ramp_start_monotonic = (
                    trial_started
                    + arrival_offsets[-1]
                    + args.density_initial_hold_seconds
                )
            stop_at_monotonic = (
                trial_started + arrival_offsets[-1] + trial_hold_seconds
                if trial_hold_seconds > 0
                else None
            )

            if args.density_ramp:
                target_offset = arrival_offsets[-1]
                phase_specs = [
                    ("arrival_ramp", args.think_max, 0.0, target_offset),
                    (
                        "full_population_stabilization",
                        args.think_max,
                        target_offset,
                        target_offset + args.density_initial_hold_seconds,
                    ),
                ]
                phase_start = target_offset + args.density_initial_hold_seconds
                for maximum_pause in range(
                    int(args.think_max) - 1,
                    int(args.density_min_think_max) - 1,
                    -1,
                ):
                    phase_specs.append(
                        (
                            f"maximum_pause_{maximum_pause}_seconds",
                            float(maximum_pause),
                            phase_start,
                            phase_start + args.density_step_seconds,
                        )
                    )
                    phase_start += args.density_step_seconds

                trial_phase_rows = []
                for phase_number, (name, maximum_pause, start_offset, end_offset) in enumerate(
                    phase_specs, start=1
                ):
                    row = {
                        "repeat": repeat,
                        "phase_number": phase_number,
                        "phase": name,
                        "maximum_random_pause_seconds": maximum_pause,
                        "phase_start_offset_seconds": round(start_offset, 3),
                        "phase_end_offset_seconds": round(end_offset, 3),
                        "phase_start_utc": (
                            trial_started_wallclock + timedelta(seconds=start_offset)
                        ).isoformat(),
                        "phase_end_utc": (
                            trial_started_wallclock + timedelta(seconds=end_offset)
                        ).isoformat(),
                        "target_visitors": level,
                    }
                    density_phase_rows.append(row)
                    trial_phase_rows.append(row)

                def log_density_phases() -> None:
                    for phase in trial_phase_rows:
                        wait = (
                            trial_started
                            + float(phase["phase_start_offset_seconds"])
                            - time.perf_counter()
                        )
                        if wait > 0:
                            time.sleep(wait)
                        print(
                            "DENSITY PHASE "
                            f"{phase['phase_start_utc']} "
                            f"phase={phase['phase']} "
                            f"maximum_pause={phase['maximum_random_pause_seconds']}s",
                            flush=True,
                        )
                        try:
                            requests.get(
                                urljoin(
                                    f"{parsed_url.scheme}://{parsed_url.netloc}/",
                                    "__miyp_benchmark_density__/"
                                    f"{phase['phase_number']}/"
                                    f"{phase['maximum_random_pause_seconds']}/"
                                    f"{phase['phase']}",
                                ),
                                timeout=5,
                                verify=tls_verify,
                            )
                        except requests.RequestException as exc:
                            print(
                                f"WARNING: density phase marker failed: {exc}",
                                flush=True,
                            )

                phase_logger = threading.Thread(target=log_density_phases, daemon=True)
                phase_logger.start()
            else:
                phase_logger = None
            trial_measurements: list[RequestMeasurement] = []
            with ThreadPoolExecutor(max_workers=level) as executor:
                futures = []
                for user_number, arrival_offset in enumerate(
                    arrival_offsets, start=1
                ):
                    remaining = trial_started + arrival_offset - time.perf_counter()
                    if remaining > 0:
                        time.sleep(remaining)
                    active_users.enter()
                    try:
                        future = executor.submit(
                            run_user,
                            presentation_urls=target_urls,
                            start_index=(user_number + repeat - 2)
                            % len(target_urls),
                            level=level,
                            repeat=repeat,
                            user_number=user_number,
                            journeys=args.journeys_per_user,
                            timeout=args.timeout,
                            think_min=args.think_min,
                            think_max=args.think_max,
                            journey_think_min=args.journey_think_min,
                            journey_think_max=args.journey_think_max,
                            navigation_changes_min=args.navigation_changes_min,
                            navigation_changes_max=args.navigation_changes_max,
                            stop_at_monotonic=stop_at_monotonic,
                            density_ramp_start_monotonic=density_ramp_start_monotonic,
                            density_step_seconds=args.density_step_seconds,
                            density_min_think_max=args.density_min_think_max,
                            synthetic_slide_events=args.synthetic_slide_events,
                            tracking_batch_size=args.tracking_batch_size,
                            tls_verify=tls_verify,
                        )
                    except Exception:
                        active_users.leave()
                        raise
                    future.add_done_callback(lambda _future: active_users.leave())
                    futures.append(future)
                for future in as_completed(futures):
                    measurements, session_keys = future.result()
                    trial_measurements.extend(measurements)
                    all_session_keys.update(session_keys)
            if phase_logger:
                phase_logger.join(timeout=2)
            elapsed = time.perf_counter() - trial_started
            trial_finished_at_utc = datetime.now(timezone.utc).isoformat()
            host_metrics = sampler.stop()
            all_measurements.extend(trial_measurements)
            trial_summary = summarize_trial(
                trial_measurements,
                level=level,
                repeat=repeat,
                elapsed_seconds=elapsed,
                host_metrics=host_metrics,
                started_at_utc=trial_started_at_utc,
                finished_at_utc=trial_finished_at_utc,
                peak_active_users=active_users.peak,
                hold_after_target_seconds=trial_hold_seconds,
            )
            trial_summaries.append(trial_summary)
            print(
                f"visitors={level:>3} peak_active={active_users.peak:>3} "
                f"repeat={repeat} "
                f"p95={trial_summary['latency_p95_ms']:>8.1f} ms "
                f"errors={trial_summary['error_rate_percent']:>6.2f}% "
                f"throughput={trial_summary['throughput_requests_per_second']:>7.2f} req/s"
            )
            if trial_number < total_trials and args.cooldown_seconds > 0:
                print(
                    f"cooldown={args.cooldown_seconds:.1f}s before the next trial"
                )
                time.sleep(args.cooldown_seconds)

    configuration = {
        "run_id": run_id,
        "started_at_utc": timestamp,
        "finished_at_utc": datetime.now(timezone.utc).isoformat(),
        "clock_ntp_synchronized": clock_synchronization_status(),
        "target_url": args.url,
        "target_url_sha256": hashlib.sha256(args.url.encode("utf-8")).hexdigest(),
        "target_urls": target_urls,
        "target_url_sha256s": [
            hashlib.sha256(url.encode("utf-8")).hexdigest()
            for url in target_urls
        ],
        "target_distribution": (
            "round-robin by virtual user, repeat, and journey; each visitor "
            "keeps one HTTP session while moving between presentations"
        ),
        "levels": levels,
        "repeats": args.repeats,
        "journeys_per_user": args.journeys_per_user,
        "think_min_seconds": args.think_min,
        "think_max_seconds": args.think_max,
        "navigation_model": (
            "starts on the first slide, moves forward, and reverses direction "
            "whenever it reaches either end"
        ),
        "navigation_changes_min": args.navigation_changes_min,
        "navigation_changes_max": args.navigation_changes_max,
        "navigation_change_count_distribution": "uniform random integer",
        "journey_think_min_seconds": args.journey_think_min,
        "journey_think_max_seconds": args.journey_think_max,
        "arrival_gap_min_seconds": args.arrival_gap_min,
        "arrival_gap_max_seconds": args.arrival_gap_max,
        "arrival_distribution": (
            "sequential cumulative arrivals with a uniform pseudo-random gap "
            "between consecutive visitors"
        ),
        "workload_mode": (
            "progressive admission until complete service failure"
            if args.admission_ramp
            else "continuous click-density ramp"
            if args.density_ramp
            else "sustained ramp to target active visitors"
            if args.hold_after_target_seconds > 0
            else "finite journeys per visitor"
        ),
        "hold_after_target_seconds": (
            args.density_initial_hold_seconds
            + (args.think_max - args.density_min_think_max)
            * args.density_step_seconds
            if args.density_ramp
            else args.hold_after_target_seconds
        ),
        "density_ramp": {
            "enabled": args.density_ramp,
            "initial_hold_seconds": args.density_initial_hold_seconds,
            "step_seconds": args.density_step_seconds,
            "maximum_pause_reduction_seconds_per_step": 1,
            "minimum_maximum_pause_seconds": args.density_min_think_max,
            "phase_schedule_file": f"{run_id}-density-phases.csv"
            if args.density_ramp
            else None,
        },
        "admission_ramp": {
            "enabled": args.admission_ramp,
            "maximum_visitors_guard": levels[0]
            if args.admission_ramp
            else None,
            "visitors_added_per_stage": args.admission_step_users,
            "stage_observation_seconds": args.admission_step_seconds,
            "consecutive_completely_failed_stages_to_stop": (
                args.admission_failure_stages
            ),
            "failure_definition": (
                "at least one request completed during the stage and none succeeded"
            ),
            "stop_reason": admission_stop_reason,
            "phase_file": f"{run_id}-admission-phases.csv"
            if args.admission_ramp
            else None,
        },
        "finite_journeys_ignored_in_sustained_mode": (
            args.hold_after_target_seconds > 0
            or args.density_ramp
            or args.admission_ramp
        ),
        "cooldown_seconds": args.cooldown_seconds,
        "pacing_random_seed": (
            "deterministic: level*1000000 + repeat*10000 + user_number"
        ),
        "timeout_seconds": args.timeout,
        "synthetic_slide_events": args.synthetic_slide_events,
        "tracking_batch_size": args.tracking_batch_size,
        "tracking_flush_delay_seconds": {
            "minimum": 2.5,
            "maximum": 6.0,
            "source": "public presentation browser implementation",
        },
        "tls": tls_configuration,
        "load_generator": {
            "hostname": platform.node(),
            "platform": platform.platform(),
            "python": platform.python_version(),
            "logical_cpus": os.cpu_count(),
            "total_memory_mib": round(
                next(
                    int(line.split()[1])
                    for line in Path("/proc/meminfo")
                    .read_text(encoding="utf-8")
                    .splitlines()
                    if line.startswith("MemTotal:")
                )
                / 1024,
                1,
            ),
        },
    }
    result_path = output_dir / f"{run_id}.json"
    result_path.write_text(
        json.dumps(
            {
                "configuration": configuration,
                "trials": trial_summaries,
                "requests": [asdict(row) for row in all_measurements],
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    csv_path = output_dir / f"{run_id}-trials.csv"
    with csv_path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(trial_summaries[0]))
        writer.writeheader()
        writer.writerows(trial_summaries)

    session_path = output_dir / f"{run_id}-session-keys.txt"
    session_path.write_text("\n".join(sorted(all_session_keys)) + "\n", encoding="utf-8")
    if density_phase_rows:
        phase_path = output_dir / f"{run_id}-density-phases.csv"
        with phase_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle, fieldnames=list(density_phase_rows[0])
            )
            writer.writeheader()
            writer.writerows(density_phase_rows)
        print(f"Density phases: {phase_path}")
    if admission_phase_rows:
        admission_path = output_dir / f"{run_id}-admission-phases.csv"
        with admission_path.open("w", newline="", encoding="utf-8") as handle:
            writer = csv.DictWriter(
                handle, fieldnames=list(admission_phase_rows[0])
            )
            writer.writeheader()
            writer.writerows(admission_phase_rows)
        print(f"Admission phases: {admission_path}")
    print(f"Results: {result_path}")
    print(f"Trial CSV: {csv_path}")
    print(f"Benchmark session keys: {session_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
