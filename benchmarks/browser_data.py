#!/usr/bin/env python3
"""Measure cold and warm presentation transfer through Chrome DevTools."""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import shutil
import socket
import subprocess
import tempfile
import time
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

try:
    import websocket
except ImportError:
    websocket = None


if __package__:
    from .target import add_target_arguments, resolve_target
else:
    from target import add_target_arguments, resolve_target

DEFAULT_CERTIFICATE = (
    Path(__file__).resolve().parents[1]
    / "global_files"
    / "certificates"
    / "miyp-selfsigned.crt"
)


def certificate_spki_sha256(certificate_path: Path) -> str:
    """Return Chrome's Base64-encoded SHA-256 SPKI allowlist value."""
    if not certificate_path.is_file():
        raise SystemExit(f"HTTPS certificate not found: {certificate_path}")
    openssl = shutil.which("openssl")
    if not openssl:
        raise SystemExit("OpenSSL is required to derive the certificate SPKI hash.")

    try:
        public_key = subprocess.run(
            [openssl, "x509", "-in", str(certificate_path), "-pubkey", "-noout"],
            check=True,
            capture_output=True,
        ).stdout
        public_key_der = subprocess.run(
            [openssl, "pkey", "-pubin", "-outform", "DER"],
            input=public_key,
            check=True,
            capture_output=True,
        ).stdout
    except subprocess.CalledProcessError as exc:
        detail = exc.stderr.decode("utf-8", errors="replace").strip()
        raise SystemExit(f"Could not read HTTPS certificate: {detail}") from exc

    return base64.b64encode(hashlib.sha256(public_key_der).digest()).decode("ascii")


class DevTools:
    def __init__(self, websocket_url: str) -> None:
        self.websocket = websocket.create_connection(
            websocket_url,
            timeout=0.25,
            origin="http://127.0.0.1",
        )
        self.next_id = 1
        self.buffered_events: list[dict] = []

    def close(self) -> None:
        self.websocket.close()

    def command(self, method: str, params: dict | None = None) -> dict:
        command_id = self.next_id
        self.next_id += 1
        self.websocket.send(
            json.dumps({"id": command_id, "method": method, "params": params or {}})
        )
        while True:
            try:
                message = json.loads(self.websocket.recv())
            except websocket.WebSocketTimeoutException:
                continue
            if message.get("id") == command_id:
                if "error" in message:
                    raise RuntimeError(f"Chrome DevTools error: {message['error']}")
                return message.get("result", {})
            if "method" in message:
                self.buffered_events.append(message)

    def receive_event(self, timeout: float = 0.25) -> dict | None:
        if self.buffered_events:
            return self.buffered_events.pop(0)
        self.websocket.settimeout(timeout)
        try:
            message = json.loads(self.websocket.recv())
        except websocket.WebSocketTimeoutException:
            return None
        return message if "method" in message else None

    def discard_events(self) -> None:
        self.buffered_events.clear()
        while self.receive_event(timeout=0.01):
            pass


def available_port() -> int:
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])


def wait_for_devtools(port: int, timeout: float = 10) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with urlopen(f"http://127.0.0.1:{port}/json/version", timeout=0.5):
                return
        except OSError:
            time.sleep(0.1)
    raise RuntimeError("Chrome DevTools did not become ready")


def create_target(port: int) -> str:
    request = Request(
        f"http://127.0.0.1:{port}/json/new?{quote('about:blank', safe=':/')}",
        method="PUT",
    )
    with urlopen(request, timeout=5) as response:
        target = json.load(response)
    return target["webSocketDebuggerUrl"]


def measure_page(
    devtools: DevTools,
    url: str,
    *,
    clear_cache: bool,
    settle_seconds: float,
    timeout_seconds: float,
) -> dict:
    if clear_cache:
        devtools.command("Network.clearBrowserCache")
    devtools.command("Network.setCacheDisabled", {"cacheDisabled": False})
    devtools.discard_events()
    devtools.command("Page.navigate", {"url": url})

    resources: dict[str, dict] = {}
    load_seen_at: float | None = None
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        event = devtools.receive_event()
        now = time.monotonic()
        if event is None:
            if load_seen_at is not None and now - load_seen_at >= settle_seconds:
                break
            continue

        method = event["method"]
        params = event.get("params", {})
        request_id = params.get("requestId")
        if method == "Page.loadEventFired":
            load_seen_at = now
        elif method == "Network.requestWillBeSent" and request_id:
            request_url = params.get("request", {}).get("url", "")
            if request_url.startswith(("http://", "https://")):
                resources[request_id] = {
                    "url": request_url,
                    "resource_type": params.get("type", ""),
                    "status": None,
                    "mime_type": "",
                    "from_disk_cache": False,
                    "from_service_worker": False,
                    "encoded_bytes": 0,
                    "failed": False,
                }
        elif method == "Network.responseReceived" and request_id in resources:
            response = params.get("response", {})
            resources[request_id].update(
                {
                    "status": int(response.get("status", 0)),
                    "mime_type": response.get("mimeType", ""),
                    "from_disk_cache": bool(response.get("fromDiskCache", False)),
                    "from_service_worker": bool(response.get("fromServiceWorker", False)),
                }
            )
        elif method == "Network.loadingFinished" and request_id in resources:
            resources[request_id]["encoded_bytes"] = int(
                round(float(params.get("encodedDataLength", 0)))
            )
        elif method == "Network.loadingFailed" and request_id in resources:
            resources[request_id]["failed"] = True
            resources[request_id]["error_text"] = params.get("errorText", "")

    if load_seen_at is None:
        raise RuntimeError(f"Page load did not complete within {timeout_seconds} seconds")

    resource_list = list(resources.values())
    by_host: dict[str, dict[str, int]] = defaultdict(
        lambda: {"requests": 0, "encoded_bytes": 0, "cache_hits": 0}
    )
    for resource in resource_list:
        host = urlparse(resource["url"]).hostname or "(unknown)"
        by_host[host]["requests"] += 1
        by_host[host]["encoded_bytes"] += resource["encoded_bytes"]
        if resource["from_disk_cache"] or resource["from_service_worker"]:
            by_host[host]["cache_hits"] += 1

    encoded_bytes = sum(resource["encoded_bytes"] for resource in resource_list)
    return {
        "request_count": len(resource_list),
        "failed_requests": sum(resource["failed"] for resource in resource_list),
        "cache_hits": sum(
            resource["from_disk_cache"] or resource["from_service_worker"]
            for resource in resource_list
        ),
        "encoded_transfer_bytes": encoded_bytes,
        "encoded_transfer_mib": round(encoded_bytes / (1024 * 1024), 4),
        "by_host": dict(sorted(by_host.items())),
        "resources": sorted(
            resource_list, key=lambda item: item["encoded_bytes"], reverse=True
        ),
        "measurement_scope": (
            "Network.loadingFinished encodedDataLength from the Chrome DevTools "
            "Protocol. Cache hits are identified from response metadata."
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Measure cold- and warm-cache MIYP presentation transfer."
    )
    add_target_arguments(parser)
    parser.add_argument("--chrome", default="google-chrome")
    parser.add_argument("--settle-seconds", type=float, default=3)
    parser.add_argument("--timeout-seconds", type=float, default=30)
    parser.add_argument("--output-dir", default="benchmarks/results")
    parser.add_argument(
        "--certificate",
        type=Path,
        default=DEFAULT_CERTIFICATE,
        help=(
            "Self-signed HTTPS certificate to trust in Chrome. Defaults to "
            "global_files/certificates/miyp-selfsigned.crt."
        ),
    )
    parser.add_argument(
        "--system-ca",
        action="store_true",
        help="Use only Chrome's normal certificate trust store.",
    )
    return resolve_target(parser, parser.parse_args())


def main() -> int:
    args = parse_args()
    if websocket is None:
        raise SystemExit(
            "browser_data.py requires websocket-client. "
            "Install benchmarks/requirements.txt first."
        )
    chrome = shutil.which(args.chrome)
    if not chrome:
        raise SystemExit(f"Chrome executable not found: {args.chrome}")
    parsed_url = urlparse(args.url)
    if parsed_url.scheme not in {"http", "https"} or "/presentation/" not in parsed_url.path:
        raise SystemExit("--url must be an HTTP(S) public presentation URL")

    certificate_path: Path | None = None
    certificate_spki: str | None = None
    if parsed_url.scheme == "https" and not args.system_ca:
        certificate_path = args.certificate.expanduser().resolve()
        certificate_spki = certificate_spki_sha256(certificate_path)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = output_dir / f"browser-transfer-{timestamp}.json"

    with tempfile.TemporaryDirectory(prefix="miyp-browser-benchmark-") as temp_dir:
        port = available_port()
        chrome_arguments = [
            chrome,
            "--headless",
            "--no-sandbox",
            "--disable-gpu",
            "--disable-background-networking",
            "--disable-component-update",
            "--disable-default-apps",
            "--disable-domain-reliability",
            "--disable-sync",
            "--metrics-recording-only",
            "--no-first-run",
            "--remote-allow-origins=*",
            f"--remote-debugging-port={port}",
            "--window-size=390,844",
            f"--user-data-dir={Path(temp_dir) / 'profile'}",
            "about:blank",
        ]
        if certificate_spki:
            chrome_arguments.insert(
                -1,
                f"--ignore-certificate-errors-spki-list={certificate_spki}",
            )

        chrome_process = subprocess.Popen(
            chrome_arguments,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        devtools = None
        try:
            wait_for_devtools(port)
            devtools = DevTools(create_target(port))
            devtools.command("Network.enable")
            devtools.command("Page.enable")
            measurements = {
                "cold": measure_page(
                    devtools,
                    args.url,
                    clear_cache=True,
                    settle_seconds=args.settle_seconds,
                    timeout_seconds=args.timeout_seconds,
                ),
                "warm": measure_page(
                    devtools,
                    args.url,
                    clear_cache=False,
                    settle_seconds=args.settle_seconds,
                    timeout_seconds=args.timeout_seconds,
                ),
            }
        finally:
            if devtools:
                devtools.close()
            chrome_process.terminate()
            try:
                chrome_process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                chrome_process.kill()
                chrome_process.wait(timeout=5)

    for cache_state, measurement in measurements.items():
        print(
            f"{cache_state}: {measurement['request_count']} requests, "
            f"{measurement['cache_hits']} cache hits, "
            f"{measurement['encoded_transfer_mib']:.4f} MiB encoded transfer"
        )

    output_path.write_text(
        json.dumps(
            {
                "measured_at_utc": timestamp,
                "target_url": args.url,
                "chrome": subprocess.check_output([chrome, "--version"], text=True).strip(),
                "viewport_css_pixels": {"width": 390, "height": 844},
                "settle_seconds": args.settle_seconds,
                "tls": {
                    "verification": (
                        "certificate-specific Chrome SPKI allowlist"
                        if certificate_spki
                        else "Chrome system trust store"
                    ),
                    "certificate_path": (
                        str(certificate_path) if certificate_path else None
                    ),
                    "certificate_spki_sha256": certificate_spki,
                },
                "measurements": measurements,
            },
            indent=2,
        ),
        encoding="utf-8",
    )
    print(f"Results: {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
