#!/usr/bin/env python3
"""Remove database activity created by a load_test.py run."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Delete MIYP benchmark PresentationSession rows and cascading accesses."
    )
    parser.add_argument("session_file", type=Path)
    parser.add_argument(
        "--confirm",
        action="store_true",
        help="Perform deletion. Without this flag the command is a dry run.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "global_files.settings")

    import django

    django.setup()
    from main_app.models import PresentationSession

    session_keys = {
        line.strip()
        for line in args.session_file.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    queryset = PresentationSession.objects.filter(session_key__in=session_keys)
    session_count = queryset.count()
    access_count = sum(session.accesses.count() for session in queryset.iterator())
    print(
        f"Matched {session_count} presentation sessions and "
        f"{access_count} presentation access rows."
    )
    if not args.confirm:
        print("Dry run only. Add --confirm to delete these rows.")
        return 0
    deleted_count, deleted_by_model = queryset.delete()
    print(f"Deleted {deleted_count} rows in total: {deleted_by_model}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
