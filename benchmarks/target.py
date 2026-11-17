"""Shared deployment-independent target configuration for benchmark scripts."""

import os
from urllib.parse import urljoin, urlparse


def add_target_arguments(parser):
    parser.add_argument(
        "--base-url",
        default=os.environ.get("MIYP_BENCHMARK_BASE_URL"),
        help="Deployment origin, or MIYP_BENCHMARK_BASE_URL (e.g. https://server:8000).",
    )
    parser.add_argument(
        "--url",
        default=os.environ.get("MIYP_BENCHMARK_URL"),
        help="Full presentation URL or relative path; defaults to MIYP_BENCHMARK_URL.",
    )


def resolve_target(parser, args):
    if not args.url:
        parser.error("provide --url or set MIYP_BENCHMARK_URL")
    target = urlparse(args.url)
    if not target.scheme and not target.netloc:
        base = urlparse(args.base_url or "")
        if base.scheme not in {"http", "https"} or not base.netloc:
            parser.error("a relative --url requires --base-url or MIYP_BENCHMARK_BASE_URL")
        args.url = urljoin(args.base_url.rstrip("/") + "/", args.url)
    target = urlparse(args.url)
    if target.scheme not in {"http", "https"} or not target.netloc or "/presentation/" not in target.path:
        parser.error("target must be an HTTP(S) public presentation URL")
    return args
