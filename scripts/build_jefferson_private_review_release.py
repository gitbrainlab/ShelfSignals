#!/usr/bin/env python3
"""Build an immutable authenticated Jefferson review-site release.

The output combines the public static site with the separately built private
photo bundle and a small same-origin gallery overlay. It stays beneath the
git-ignored research workspace and must be served through the fail-closed
Cloudflare Access + Worker + private R2 gateway.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import tempfile
from typing import Any, Mapping, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = SCRIPT_DIR.parent
DEFAULT_PUBLIC_ROOT = REPOSITORY_ROOT / "docs"
DEFAULT_MEDIA_ROOT = REPOSITORY_ROOT / "research/jefferson/work/private-media/latest"
DEFAULT_OUTPUT_ROOT = REPOSITORY_ROOT / "research/jefferson/work/private-review"
DEFAULT_ASSET_ROOT = REPOSITORY_ROOT / "infrastructure/private-review/site-assets"

RELEASE_SCHEMA = "shelfsignals-private-site-release@1"
MEDIA_SCHEMA = "shelfsignals-private-media-bundle@1"
SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
ASSET_PATH_RE = re.compile(r"^private/jefferson/display/[0-9a-f]{64}\.jpg$")
HTML_HEAD_MARKER = '<link rel="stylesheet" href="./private-review/private-review.css">'
HTML_BODY_MARKER = '<script type="module" src="./private-review/private-review.js"></script>'
FORBIDDEN_PUBLIC_SUFFIXES = {".db", ".sqlite", ".sqlite3"}


class ReleaseError(RuntimeError):
    """Raised when an authenticated release cannot be built safely."""


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return f"sha256:{digest.hexdigest()}"


def validate_timestamp(value: str) -> str:
    if not UTC_RE.fullmatch(value):
        raise ReleaseError("generated_at must be a whole-second UTC timestamp")
    try:
        dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as error:
        raise ReleaseError("generated_at is not a valid UTC timestamp") from error
    return value


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise ReleaseError(f"Unable to read JSON {path}: {error}") from error


def reject_symlinks(root: Path, label: str) -> None:
    if root.is_symlink():
        raise ReleaseError(f"{label} cannot be a symlink: {root}")
    if not root.is_dir():
        raise ReleaseError(f"{label} is not a directory: {root}")
    for path in root.rglob("*"):
        if path.is_symlink():
            raise ReleaseError(f"{label} contains a symlink: {path}")


def resolved_path(path: Path, label: str, *, must_exist: bool) -> Path:
    try:
        return path.resolve(strict=must_exist)
    except OSError as error:
        raise ReleaseError(f"Unable to resolve {label} {path}: {error}") from error


def paths_overlap(first: Path, second: Path) -> bool:
    return first == second or first in second.parents or second in first.parents


def validate_output_boundary(
    output_root: Path,
    *,
    public_root: Path,
    media_root: Path,
    asset_root: Path,
) -> None:
    output = resolved_path(output_root, "private review output", must_exist=False)
    sources = {
        "public site": resolved_path(public_root, "public site", must_exist=True),
        "private media bundle": resolved_path(media_root, "private media bundle", must_exist=True),
        "private review overlay": resolved_path(asset_root, "private review overlay", must_exist=True),
    }
    for label, source in sources.items():
        if paths_overlap(output, source):
            raise ReleaseError(f"Private review output cannot overlap the {label}: {output}")
    repository = resolved_path(REPOSITORY_ROOT, "repository root", must_exist=True)
    approved = resolved_path(DEFAULT_OUTPUT_ROOT, "approved private review output", must_exist=False)
    if output.is_relative_to(repository) and not output.is_relative_to(approved):
        raise ReleaseError(
            "Private review output inside the repository must remain beneath the git-ignored research workspace"
        )


def safe_relative_path(value: Any) -> str:
    text = str(value or "")
    if not ASSET_PATH_RE.fullmatch(text):
        raise ReleaseError(f"Private media path is unsafe: {text!r}")
    path = PurePosixPath(text)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise ReleaseError(f"Private media path is unsafe: {text!r}")
    return text


def validate_media_bundle(media_root: Path) -> tuple[Mapping[str, Any], list[tuple[Path, str]]]:
    manifest_path = media_root / "data/collections/jefferson/media-authenticated.json"
    raw = load_json(manifest_path)
    if not isinstance(raw, dict) or raw.get("schema") != MEDIA_SCHEMA:
        raise ReleaseError("Private media manifest schema is unsupported")
    if raw.get("collection_id") != "jefferson" or raw.get("audience") != "authenticated_review":
        raise ReleaseError("Private media manifest has the wrong collection or audience")
    items = raw.get("items")
    if not isinstance(items, list) or len(items) != 4:
        raise ReleaseError("Private media manifest must contain exactly four photographs")
    ids: set[str] = set()
    asset_paths: set[str] = set()
    asset_hashes: set[str] = set()
    files: list[tuple[Path, str]] = []
    for index, item in enumerate(items):
        if not isinstance(item, dict):
            raise ReleaseError(f"Private media item {index} is invalid")
        identifier = str(item.get("id") or "")
        if not identifier or identifier in ids:
            raise ReleaseError(f"Private media item {index} has a missing or duplicate ID")
        ids.add(identifier)
        if item.get("entity_type") != "exhibition_context_photograph" or item.get("context_scope") != "exhibition_context_only":
            raise ReleaseError(f"Private media item {identifier} has an unsafe evidence scope")
        if item.get("rights", {}).get("public_reuse") != "not_granted":
            raise ReleaseError(f"Private media item {identifier} must retain its private-use rights status")
        relative = safe_relative_path(item.get("asset_path"))
        source = media_root / relative
        if not source.is_file() or source.is_symlink():
            raise ReleaseError(f"Private media asset is unavailable: {relative}")
        expected_hash = str(item.get("sha256") or "")
        if not SHA256_RE.fullmatch(expected_hash) or sha256_file(source) != expected_hash:
            raise ReleaseError(f"Private media asset hash mismatch: {relative}")
        if relative in asset_paths or expected_hash in asset_hashes:
            raise ReleaseError("Private media manifest must reference four distinct image binaries")
        asset_paths.add(relative)
        asset_hashes.add(expected_hash)
        if source.stat().st_size != item.get("bytes"):
            raise ReleaseError(f"Private media asset byte count mismatch: {relative}")
        files.append((source, relative))
    return raw, files


def copy_public_site(source: Path, destination: Path) -> None:
    reject_symlinks(source, "Public site")
    if not (source / "index.html").is_file():
        raise ReleaseError("Public site does not contain index.html")
    for path in sorted(source.rglob("*")):
        relative = path.relative_to(source)
        target = destination / relative
        if path.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            continue
        if path.suffix.lower() in FORBIDDEN_PUBLIC_SUFFIXES:
            raise ReleaseError(f"Public site contains a forbidden database file: {relative}")
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)


def inject_overlay(index_path: Path) -> None:
    try:
        source = index_path.read_text(encoding="utf-8")
    except OSError as error:
        raise ReleaseError(f"Unable to read staged index.html: {error}") from error
    if HTML_HEAD_MARKER in source or HTML_BODY_MARKER in source:
        raise ReleaseError("Public index.html already contains the private review overlay")
    if "</head>" not in source or "</body>" not in source:
        raise ReleaseError("Public index.html is missing required closing tags")
    source = source.replace("</head>", f"  {HTML_HEAD_MARKER}\n</head>", 1)
    source = source.replace("</body>", f"  {HTML_BODY_MARKER}\n</body>", 1)
    index_path.write_text(source, encoding="utf-8")


def inventory(root: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise ReleaseError(f"Staged release contains a symlink: {path}")
        if path.is_file():
            result.append({
                "path": path.relative_to(root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            })
    return result


def validate_existing_release(
    release_root: Path,
    *,
    release_document: bytes,
    expected_site_files: Sequence[Mapping[str, Any]],
) -> None:
    reject_symlinks(release_root, "Existing private review release")
    top_level = {path.name for path in release_root.iterdir()}
    if top_level != {"release.json", "site"}:
        raise ReleaseError("Existing release contains unexpected or missing top-level content")
    existing_document = release_root / "release.json"
    if not existing_document.is_file() or existing_document.read_bytes() != release_document:
        raise ReleaseError(f"Release ID already exists with different metadata: {release_root.name}")
    site = release_root / "site"
    reject_symlinks(site, "Existing private review site")
    if inventory(site) != list(expected_site_files):
        raise ReleaseError(f"Release ID already exists with modified site content: {release_root.name}")


def atomic_write(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(body)
    os.replace(temporary, path)


def build_release(
    public_root: Path,
    media_root: Path,
    asset_root: Path,
    output_root: Path,
    *,
    generated_at: str,
) -> dict[str, Any]:
    generated_at = validate_timestamp(generated_at)
    validate_output_boundary(
        output_root,
        public_root=public_root,
        media_root=media_root,
        asset_root=asset_root,
    )
    reject_symlinks(media_root, "Private media bundle")
    reject_symlinks(asset_root, "Private review overlay")
    media_manifest, media_files = validate_media_bundle(media_root)
    required_overlay = [asset_root / "private-review.css", asset_root / "private-review.js"]
    if any(not path.is_file() for path in required_overlay):
        raise ReleaseError("Private review overlay assets are incomplete")
    output_root.mkdir(parents=True, exist_ok=True)

    with tempfile.TemporaryDirectory(prefix="private-review-site-", dir=output_root) as temporary:
        staging = Path(temporary)
        site = staging / "site"
        copy_public_site(public_root, site)
        manifest_target = site / "data/collections/jefferson/media-authenticated.json"
        manifest_target.parent.mkdir(parents=True, exist_ok=True)
        manifest_target.write_bytes(json_bytes(media_manifest))
        for source, relative in media_files:
            target = site / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
        overlay_target = site / "private-review"
        overlay_target.mkdir(parents=True, exist_ok=True)
        for source in required_overlay:
            shutil.copyfile(source, overlay_target / source.name)
        inject_overlay(site / "index.html")

        site_files = inventory(site)
        release_basis = {
            "schema": RELEASE_SCHEMA,
            "collection_id": "jefferson",
            "generated_at": generated_at,
            "access": "cloudflare_access_authenticated_review",
            "public_manifest_sha256": sha256_file(public_root / "data/collections/jefferson/manifest.json"),
            "private_media_manifest_sha256": sha256_file(manifest_target),
            "site_files": site_files,
        }
        release_id = sha256_bytes(json_bytes(release_basis)).removeprefix("sha256:")
        release = {
            **release_basis,
            "release_id": release_id,
            "site_file_count": len(site_files),
            "site_bytes": sum(item["bytes"] for item in site_files),
            "private_photo_count": len(media_files),
        }
        release_root = output_root / "releases" / release_id
        release_document = json_bytes(release)
        if release_root.exists():
            validate_existing_release(
                release_root,
                release_document=release_document,
                expected_site_files=site_files,
            )
        else:
            release_root.parent.mkdir(parents=True, exist_ok=True)
            (staging / "release.json").write_bytes(release_document)
            os.replace(staging, release_root)

        active = {
            "schema": "shelfsignals-private-site-active@1",
            "release_id": release_id,
            "release_path": f"releases/{release_id}",
        }
        atomic_write(output_root / "active.json", json_bytes(active))
        return release


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--public-root", type=Path, default=DEFAULT_PUBLIC_ROOT)
    parser.add_argument("--media-root", type=Path, default=DEFAULT_MEDIA_ROOT)
    parser.add_argument("--asset-root", type=Path, default=DEFAULT_ASSET_ROOT)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--generated-at", required=True, help="Deterministic build timestamp, YYYY-MM-DDTHH:MM:SSZ")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        release = build_release(
            args.public_root,
            args.media_root,
            args.asset_root,
            args.output_root,
            generated_at=args.generated_at,
        )
    except ReleaseError as error:
        print(f"error: {error}", file=os.sys.stderr)
        return 2
    print(json.dumps({
        "release_id": release["release_id"],
        "release_root": str(args.output_root / "releases" / release["release_id"]),
        "site_file_count": release["site_file_count"],
        "site_bytes": release["site_bytes"],
        "private_photo_count": release["private_photo_count"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
