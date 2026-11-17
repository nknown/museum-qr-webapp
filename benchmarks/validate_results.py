#!/usr/bin/env python3
"""Validate the files and request outcomes produced by a benchmark run."""

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="Requester result directory.")
    parser.add_argument(
        "--allow-load-failures",
        action="store_true",
        help="Retain HTTP failures as measured saturation data.",
    )
    parser.add_argument(
        "--skip-browser",
        action="store_true",
        help="Do not require browser-transfer output.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    load_files = sorted(args.directory.glob("load-*.json"))
    browser_files = sorted(args.directory.glob("browser-transfer-*.json"))
    if not load_files or (not args.skip_browser and not browser_files):
        raise SystemExit("Expected load and browser result files were not produced")

    load = json.loads(load_files[-1].read_text(encoding="utf-8"))
    requests = load.get("requests", [])
    failures = [row for row in requests if not row.get("ok")]
    if failures:
        if args.allow_load_failures:
            print(
                f"Load test recorded {len(failures)} failed requests; retained as "
                "an expected measurement of the density boundary."
            )
        else:
            raise SystemExit(
                f"Load test contains {len(failures)} failed requests: {failures[:3]}"
            )
    if not any(row.get("request_kind") == "slide_tracking" for row in requests):
        raise SystemExit("The selected presentation did not exercise slide tracking")

    if not args.skip_browser:
        browser = json.loads(browser_files[-1].read_text(encoding="utf-8"))
        failed_resources = []
        for cache_state, measurement in browser.get("measurements", {}).items():
            for resource in measurement.get("resources", []):
                if resource.get("failed") or (resource.get("status") or 0) >= 400:
                    failed_resources.append(
                        (cache_state, resource.get("status"), resource.get("url"))
                    )
        if failed_resources:
            raise SystemExit(
                f"Browser measurement contains {len(failed_resources)} failed "
                f"resources: {failed_resources[:3]}"
            )

    if failures and args.skip_browser:
        print("Load failures remain in the density result data for analysis.")
    elif failures:
        print("Browser resources passed; load failures remain in the result data.")
    elif args.skip_browser:
        print("All recorded density-test requests passed.")
    else:
        print("All recorded requests and browser resources passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
