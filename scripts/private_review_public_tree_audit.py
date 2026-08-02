#!/usr/bin/env python3
"""Fail if authenticated-review artifacts are present in the public site."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from build_jefferson_private_review_release import REPOSITORY_ROOT, ReleaseError, validate_public_tree


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-root", type=Path, default=REPOSITORY_ROOT / "docs")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        validate_public_tree(args.public_root)
    except ReleaseError as error:
        print(f"error: {error}")
        return 2
    print(json.dumps({"public_root": str(args.public_root), "private_review_artifacts": 0}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
