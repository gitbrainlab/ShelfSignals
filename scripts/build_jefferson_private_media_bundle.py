#!/usr/bin/env python3
"""Build a private, metadata-stripped Jefferson exhibition-photo bundle.

The bundle is deliberately emitted beneath the ignored research workspace, not
``docs/``.  It is suitable for upload to an authenticated object gateway, but
the bundle itself does not provide access control.  A recursive hash audit
fails the build if a source or sanitized photograph is already present in the
public static-site tree.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Iterable, Sequence

from jefferson_private_media_contract import (
    PrivateMediaContractError,
    SCHEMA as BUNDLE_SCHEMA,
    SECURITY_NOTICE,
    validate_manifest as validate_private_media_manifest,
)


SCRIPT_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = SCRIPT_DIR.parent
DEFAULT_PRIVATE_MEDIA_ROOT = REPOSITORY_ROOT / "research/jefferson/work/private-media"
DEFAULT_OUTPUT_DIR = DEFAULT_PRIVATE_MEDIA_ROOT / "latest"
DEFAULT_PUBLIC_ROOT = REPOSITORY_ROOT / "docs"

RELEASE_SCHEMA = "shelfsignals-private-release@1"
MAX_SOURCE_BYTES = 50 * 1024 * 1024
ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ISO_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")

PHOTO_COPY = (
    {
        "id": "jefferson-exhibition-01",
        "alt": "Leather-bound volumes in the reconstructed Thomas Jefferson library display, photographed through glass.",
        "caption": "Volumes in the reconstructed Thomas Jefferson library exhibition, including French-language works and multi-volume sets.",
    },
    {
        "id": "jefferson-exhibition-02",
        "alt": "Books displayed above the label Chapter XXX, Architecture, including leather bindings and red protective bindings.",
        "caption": "Chapter XXX, Architecture, in the reconstructed Jefferson library exhibition.",
    },
    {
        "id": "jefferson-exhibition-03",
        "alt": "A row of worn leather-bound volumes above a Fine Arts label in the reconstructed Jefferson library display.",
        "caption": "Fine Arts volumes in the reconstructed Jefferson library exhibition.",
    },
    {
        "id": "jefferson-exhibition-04",
        "alt": "An alternate view of the Chapter XXX, Architecture, display with leather-bound books and red protective bindings.",
        "caption": "Chapter XXX, Architecture, alternate exhibition view.",
    },
)


class BundleError(RuntimeError):
    """Raised when the private bundle cannot be built safely."""


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, allow_nan=False, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return f"sha256:{digest.hexdigest()}"


def jpeg_dimensions(path: Path) -> tuple[int, int]:
    """Read JPEG dimensions without loading image pixels or third-party code."""
    data = path.read_bytes()
    if len(data) < 4 or data[:2] != b"\xff\xd8":
        raise BundleError(f"{path.name} is not a JPEG")
    position = 2
    start_of_frame = {
        0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7,
        0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF,
    }
    while position < len(data):
        while position < len(data) and data[position] != 0xFF:
            position += 1
        while position < len(data) and data[position] == 0xFF:
            position += 1
        if position >= len(data):
            break
        marker = data[position]
        position += 1
        if marker in {0x01, *range(0xD0, 0xD9)}:
            continue
        if position + 2 > len(data):
            break
        segment_length = int.from_bytes(data[position:position + 2], "big")
        if segment_length < 2 or position + segment_length > len(data):
            raise BundleError(f"{path.name} has an invalid JPEG segment")
        if marker in start_of_frame:
            if segment_length < 7:
                raise BundleError(f"{path.name} has an invalid JPEG frame")
            height = int.from_bytes(data[position + 3:position + 5], "big")
            width = int.from_bytes(data[position + 5:position + 7], "big")
            if width <= 0 or height <= 0:
                raise BundleError(f"{path.name} has invalid dimensions")
            return width, height
        position += segment_length
    raise BundleError(f"{path.name} has no readable JPEG frame")


def validate_source(path: Path) -> Path:
    if path.is_symlink():
        raise BundleError(f"Source photographs cannot be symlinks: {path}")
    try:
        resolved = path.resolve(strict=True)
    except OSError as error:
        raise BundleError(f"Unable to resolve source photograph {path}: {error}") from error
    if not resolved.is_file():
        raise BundleError(f"Source photograph is not a regular file: {path}")
    size = resolved.stat().st_size
    if size <= 0 or size > MAX_SOURCE_BYTES:
        raise BundleError(f"Source photograph has an unsafe size: {path}")
    jpeg_dimensions(resolved)
    return resolved


def resolved_path(path: Path, label: str, *, must_exist: bool) -> Path:
    try:
        return path.resolve(strict=must_exist)
    except OSError as error:
        raise BundleError(f"Unable to resolve {label} {path}: {error}") from error


def paths_overlap(first: Path, second: Path) -> bool:
    return first == second or first in second.parents or second in first.parents


def validate_output_boundary(output_dir: Path, public_root: Path) -> None:
    output = resolved_path(output_dir, "private media output", must_exist=False)
    public = resolved_path(public_root, "public site", must_exist=True)
    if paths_overlap(output, public):
        raise BundleError(f"Private media output cannot overlap the public site: {output}")
    repository = resolved_path(REPOSITORY_ROOT, "repository root", must_exist=True)
    approved = resolved_path(DEFAULT_PRIVATE_MEDIA_ROOT, "approved private media output", must_exist=False)
    if output.is_relative_to(repository) and not output.is_relative_to(approved):
        raise BundleError(
            "Private media output inside the repository must remain beneath the git-ignored research workspace"
        )


def sanitize_jpeg(source: Path, destination: Path, *, jpegtran: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [jpegtran, "-copy", "none", "-optimize", "-progressive", "-outfile", str(destination), str(source)],
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        timeout=60,
    )
    if result.returncode != 0 or not destination.is_file():
        message = result.stderr.decode("utf-8", errors="replace").strip()
        raise BundleError(f"jpegtran failed for {source.name}: {message or 'no output produced'}")
    output = destination.read_bytes()
    forbidden_markers = (b"Exif\x00\x00", b"http://ns.adobe.com/xap", b"Photoshop 3.0", b"GPSLatitude", b"GPSLongitude")
    if any(marker in output for marker in forbidden_markers):
        raise BundleError(f"Metadata stripping failed for {source.name}")
    jpeg_dimensions(destination)
    destination.chmod(0o644)


def public_hash_matches(public_root: Path, forbidden_hashes: set[str]) -> list[str]:
    if not public_root.exists():
        raise BundleError(f"Public site root does not exist: {public_root}")
    matches: list[str] = []
    for path in sorted(public_root.rglob("*")):
        if path.is_symlink():
            raise BundleError(f"Public site contains a symlink and cannot be audited safely: {path}")
        if path.is_file() and sha256_file(path) in forbidden_hashes:
            matches.append(path.relative_to(public_root).as_posix())
    return matches


def file_inventory(root: Path) -> list[dict[str, Any]]:
    inventory: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise BundleError(f"Private bundle contains a symlink: {path}")
        if path.is_file() and path.name != "release.json":
            inventory.append({
                "path": path.relative_to(root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            })
    return inventory


def validate_timestamp(value: str) -> str:
    if not ISO_UTC_RE.fullmatch(value):
        raise BundleError("generated_at must be a whole-second UTC timestamp")
    try:
        dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as error:
        raise BundleError("generated_at is not a valid UTC timestamp") from error
    return value


def validate_capture_date(value: str) -> str:
    if not ISO_DATE_RE.fullmatch(value):
        raise BundleError("captured_on must use YYYY-MM-DD")
    try:
        dt.date.fromisoformat(value)
    except ValueError as error:
        raise BundleError("captured_on is not a valid date") from error
    return value


def build_bundle(
    sources: Sequence[Path],
    output_dir: Path,
    *,
    public_root: Path,
    captured_on: str,
    generated_at: str,
    credit_line: str,
    jpegtran: str,
) -> dict[str, Any]:
    if len(sources) != len(PHOTO_COPY):
        raise BundleError(f"Exactly {len(PHOTO_COPY)} source photographs are required")
    validate_output_boundary(output_dir, public_root)
    captured_on = validate_capture_date(captured_on)
    generated_at = validate_timestamp(generated_at)
    credit_line = str(credit_line).strip()
    if len(credit_line) < 3:
        raise BundleError("A meaningful credit line is required")
    executable = shutil.which(jpegtran)
    if not executable:
        raise BundleError(f"Required JPEG metadata-stripper is unavailable: {jpegtran}")
    resolved_sources = [validate_source(path) for path in sources]
    if len(set(resolved_sources)) != len(resolved_sources):
        raise BundleError("Source photographs must be distinct files")
    if output_dir.exists():
        raise BundleError(f"Output directory already exists: {output_dir}")
    output_parent = output_dir.parent
    output_parent.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="private-media-", dir=output_parent) as temporary:
        root = Path(temporary)
        media_root = root / "private/jefferson/display"
        items = []
        sanitized_hashes: set[str] = set()
        forbidden_hashes = {sha256_file(path) for path in resolved_sources}
        for source, copy in zip(resolved_sources, PHOTO_COPY, strict=True):
            staging_path = media_root / f"{copy['id']}.jpg"
            sanitize_jpeg(source, staging_path, jpegtran=executable)
            width, height = jpeg_dimensions(staging_path)
            asset_sha = sha256_file(staging_path)
            if asset_sha in sanitized_hashes:
                raise BundleError("Sanitized photographs must remain four distinct image binaries")
            sanitized_hashes.add(asset_sha)
            forbidden_hashes.add(asset_sha)
            final_name = f"{asset_sha.removeprefix('sha256:')}.jpg"
            final_path = media_root / final_name
            staging_path.replace(final_path)
            items.append({
                "id": copy["id"],
                "entity_type": "exhibition_context_photograph",
                "context_scope": "exhibition_context_only",
                "asset_path": f"private/jefferson/display/{final_name}",
                "thumbnail_path": f"private/jefferson/display/{final_name}",
                "mime_type": "image/jpeg",
                "bytes": final_path.stat().st_size,
                "sha256": asset_sha,
                "width": width,
                "height": height,
                "alt": copy["alt"],
                "caption": copy["caption"],
                "captured_on": captured_on,
                "creator": credit_line,
                "rights": {
                    "status": "contributor_authorized_private_review",
                    "public_reuse": "not_granted",
                    "credit_line": credit_line,
                },
                "evidence": {
                    "source": "project_contributor_upload",
                    "book_level_matches": "not_established",
                    "chapter_labels": "visible_in_photograph_only",
                },
            })

        leaked = public_hash_matches(public_root, forbidden_hashes)
        if leaked:
            raise BundleError(f"Private photograph content is present under docs/: {', '.join(leaked)}")

        media_manifest = {
            "schema": BUNDLE_SCHEMA,
            "collection_id": "jefferson",
            "audience": "authenticated_review",
            "generated_at": generated_at,
            "unit_of_count": "exhibition context photograph",
            "security_notice": SECURITY_NOTICE,
            "items": items,
        }
        try:
            validate_private_media_manifest(media_manifest)
        except PrivateMediaContractError as error:
            raise BundleError(f"Generated private media manifest failed its release contract: {error}") from error
        manifest_path = root / "data/collections/jefferson/media-authenticated.json"
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_bytes(json_bytes(media_manifest))

        inventory = file_inventory(root)
        release_basis = {
            "schema": RELEASE_SCHEMA,
            "collection_id": "jefferson",
            "generated_at": generated_at,
            "access": "authenticated_review",
            "files": inventory,
        }
        release_id = sha256_bytes(json_bytes(release_basis))
        release = {
            **release_basis,
            "release_id": release_id,
            "private_binary_count": len(items),
            "public_repository_audit": {
                "root": "docs",
                "matching_private_hashes": 0,
            },
        }
        (root / "release.json").write_bytes(json_bytes(release))
        output_dir.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(str(root), str(output_dir))
        return release


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", action="append", type=Path, required=True, help="Source JPEG in display order; repeat exactly four times")
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--public-root", type=Path, default=DEFAULT_PUBLIC_ROOT)
    parser.add_argument("--captured-on", required=True, help="Contributor-stated capture date, YYYY-MM-DD")
    parser.add_argument("--generated-at", required=True, help="Deterministic build timestamp, YYYY-MM-DDTHH:MM:SSZ")
    parser.add_argument("--credit-line", default="Photograph by Shelf Signals project contributor")
    parser.add_argument("--jpegtran", default="jpegtran")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        release = build_bundle(
            args.source,
            args.output_dir,
            public_root=args.public_root,
            captured_on=args.captured_on,
            generated_at=args.generated_at,
            credit_line=args.credit_line,
            jpegtran=args.jpegtran,
        )
    except BundleError as error:
        print(f"error: {error}", file=os.sys.stderr)
        return 2
    print(json.dumps({
        "output_dir": str(args.output_dir),
        "release_id": release["release_id"],
        "files": len(release["files"]) + 1,
        "private_binary_count": release["private_binary_count"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
