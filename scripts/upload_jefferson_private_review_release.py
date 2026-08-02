#!/usr/bin/env python3
"""Upload and verify one immutable private-review release with Wrangler.

The uploader trusts only the ignored ``active.json`` pointer and the release
manifest produced by ``build_jefferson_private_review_release.py``.  It first
proves that the local release is canonical, content-addressed, complete, and
unchanged.  Only then does it upload the explicitly declared objects to R2 and
download every object into a private temporary directory for byte-count and
SHA-256 verification.

Wrangler owns authentication.  This script never accepts, stores, or prints a
Cloudflare token or S3 credential.
"""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import datetime as dt
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import subprocess
import tempfile
from typing import Any, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = SCRIPT_DIR.parent
DEFAULT_ACTIVE_MANIFEST = REPOSITORY_ROOT / "research/jefferson/work/private-review/active.json"
DEFAULT_WRANGLER = (
    REPOSITORY_ROOT
    / "infrastructure/private-review/cloudflare/node_modules/.bin/wrangler"
)
DEFAULT_WRANGLER_CWD = REPOSITORY_ROOT / "infrastructure/private-review/cloudflare"

ACTIVE_SCHEMA = "shelfsignals-private-site-active@1"
RELEASE_SCHEMA = "shelfsignals-private-site-release@1"
ACTIVE_KEYS = frozenset({"schema", "release_id", "release_path"})
RELEASE_KEYS = frozenset({
    "schema",
    "collection_id",
    "generated_at",
    "access",
    "public_manifest_sha256",
    "private_media_manifest_sha256",
    "site_files",
    "release_id",
    "site_file_count",
    "site_bytes",
    "private_photo_count",
})
RELEASE_BASIS_KEYS = (
    "schema",
    "collection_id",
    "generated_at",
    "access",
    "public_manifest_sha256",
    "private_media_manifest_sha256",
    "site_files",
)
SITE_FILE_KEYS = frozenset({"path", "bytes", "sha256"})

RELEASE_ID_RE = re.compile(r"^[0-9a-f]{64}$")
SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
BUCKET_RE = re.compile(r"^[a-z0-9](?:[a-z0-9-]{1,61}[a-z0-9])$")
UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
MAX_MANIFEST_BYTES = 16 * 1024 * 1024
MAX_R2_KEY_BYTES = 1024
COMMAND_TIMEOUT_SECONDS = 600
COPY_BLOCK_BYTES = 1024 * 1024


class UploadError(RuntimeError):
    """Raised when a release cannot be safely uploaded or verified."""


class DuplicateJsonKey(ValueError):
    """Raised when a JSON object contains a duplicate member name."""


@dataclass(frozen=True)
class ObjectSpec:
    source: Path
    key: str
    bytes: int
    sha256: str


@dataclass(frozen=True)
class UploadPlan:
    bucket: str
    release_id: str
    site_file_count: int
    site_bytes: int
    objects: tuple[ObjectSpec, ...]

    @property
    def remote_prefix(self) -> str:
        return f"releases/{self.release_id}/"

    @property
    def total_bytes(self) -> int:
        return sum(item.bytes for item in self.objects)


def canonical_json(value: Any) -> bytes:
    return (
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        + "\n"
    ).encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for block in iter(lambda: handle.read(COPY_BLOCK_BYTES), b""):
                digest.update(block)
    except OSError as error:
        raise UploadError(f"Unable to hash {path}: {error}") from error
    return f"sha256:{digest.hexdigest()}"


def unique_json_object(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise DuplicateJsonKey(key)
        result[key] = value
    return result


def read_json_document(path: Path, label: str) -> tuple[Any, bytes]:
    try:
        metadata = path.lstat()
    except OSError as error:
        raise UploadError(f"Unable to inspect {label} {path}: {error}") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise UploadError(f"{label} must be a regular non-symlink file: {path}")
    if metadata.st_size > MAX_MANIFEST_BYTES:
        raise UploadError(f"{label} is unexpectedly large: {metadata.st_size} bytes")
    try:
        body = path.read_bytes()
        value = json.loads(body.decode("utf-8"), object_pairs_hook=unique_json_object)
    except DuplicateJsonKey as error:
        raise UploadError(f"{label} contains duplicate JSON key {str(error)!r}") from error
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise UploadError(f"Unable to read {label} {path}: {error}") from error
    return value, body


def require_exact_keys(value: Any, expected: frozenset[str], label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise UploadError(f"{label} must be a JSON object")
    actual = frozenset(value)
    if actual != expected:
        missing = sorted(expected - actual)
        unexpected = sorted(actual - expected)
        raise UploadError(
            f"{label} has unexpected keys (missing={missing}, unexpected={unexpected})"
        )
    return value


def require_nonnegative_integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise UploadError(f"{label} must be a non-negative integer")
    return value


def validate_bucket_name(value: str) -> str:
    if not isinstance(value, str) or not BUCKET_RE.fullmatch(value):
        raise UploadError(
            "R2 bucket name must be 3-63 lowercase letters, numbers, or hyphens "
            "and must start and end with a letter or number"
        )
    return value


def validate_release_id(value: Any, label: str = "release ID") -> str:
    if not isinstance(value, str) or not RELEASE_ID_RE.fullmatch(value):
        raise UploadError(f"{label} must be exactly 64 lowercase hexadecimal characters")
    return value


def validate_sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise UploadError(f"{label} must be a lowercase sha256:<64-hex> digest")
    return value


def validate_timestamp(value: Any) -> str:
    if not isinstance(value, str) or not UTC_RE.fullmatch(value):
        raise UploadError("release generated_at must be a whole-second UTC timestamp")
    try:
        dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as error:
        raise UploadError("release generated_at is not a valid UTC timestamp") from error
    return value


def validate_site_path(value: Any, label: str = "site file path") -> str:
    if not isinstance(value, str) or not value:
        raise UploadError(f"{label} must be a non-empty string")
    if "\\" in value or any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise UploadError(f"{label} contains an unsafe character: {value!r}")
    path = PurePosixPath(value)
    if (
        path.is_absolute()
        or value != path.as_posix()
        or any(part in {"", ".", ".."} for part in path.parts)
    ):
        raise UploadError(f"{label} is unsafe: {value!r}")
    return value


def site_path_sort_key(value: str) -> tuple[str, ...]:
    """Match pathlib's component-wise ordering used by the release builder."""
    return PurePosixPath(value).parts


def validate_object_key(value: str, release_id: str) -> str:
    prefix = f"releases/{release_id}/"
    if not value.startswith(prefix):
        raise UploadError(f"R2 object key escaped the immutable release prefix: {value!r}")
    validate_site_path(value, "R2 object key")
    if len(value.encode("utf-8")) > MAX_R2_KEY_BYTES:
        raise UploadError(f"R2 object key exceeds {MAX_R2_KEY_BYTES} UTF-8 bytes: {value!r}")
    return value


def validate_regular_file(path: Path, label: str) -> os.stat_result:
    try:
        metadata = path.lstat()
    except OSError as error:
        raise UploadError(f"Unable to inspect {label} {path}: {error}") from error
    if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISREG(metadata.st_mode):
        raise UploadError(f"{label} must be a regular non-symlink file: {path}")
    return metadata


def site_inventory(site_root: Path) -> dict[str, Path]:
    if site_root.is_symlink() or not site_root.is_dir():
        raise UploadError(f"Release site must be a non-symlink directory: {site_root}")
    files: dict[str, Path] = {}

    def walk_error(error: OSError) -> None:
        raise UploadError(f"Unable to inspect release site {site_root}: {error}") from error

    for directory, directory_names, file_names in os.walk(
        site_root, topdown=True, followlinks=False, onerror=walk_error
    ):
        directory_names.sort()
        file_names.sort()
        current = Path(directory)
        for name in directory_names:
            child = current / name
            try:
                metadata = child.lstat()
            except OSError as error:
                raise UploadError(f"Unable to inspect release directory {child}: {error}") from error
            if stat.S_ISLNK(metadata.st_mode) or not stat.S_ISDIR(metadata.st_mode):
                raise UploadError(f"Release site contains an unsafe directory entry: {child}")
            validate_site_path(child.relative_to(site_root).as_posix(), "site directory path")
        for name in file_names:
            child = current / name
            validate_regular_file(child, "Release site entry")
            relative = validate_site_path(
                child.relative_to(site_root).as_posix(), "site file path"
            )
            if relative in files:
                raise UploadError(f"Release site contains a duplicate path: {relative}")
            files[relative] = child
    return dict(sorted(files.items(), key=lambda item: site_path_sort_key(item[0])))


def validate_release_root(release_root: Path) -> tuple[Path, Path]:
    if release_root.is_symlink() or not release_root.is_dir():
        raise UploadError(f"Release root must be a non-symlink directory: {release_root}")
    try:
        children = {path.name: path for path in release_root.iterdir()}
    except OSError as error:
        raise UploadError(f"Unable to inspect release root {release_root}: {error}") from error
    if frozenset(children) != frozenset({"release.json", "site"}):
        raise UploadError(
            "Release root must contain exactly release.json and site; "
            f"found {sorted(children)}"
        )
    release_manifest = children["release.json"]
    site_root = children["site"]
    validate_regular_file(release_manifest, "Release manifest")
    if site_root.is_symlink() or not site_root.is_dir():
        raise UploadError(f"Release site must be a non-symlink directory: {site_root}")
    return release_manifest, site_root


def build_upload_plan(active_manifest: Path, bucket: str) -> UploadPlan:
    bucket = validate_bucket_name(bucket)
    active_raw, active_body = read_json_document(active_manifest, "Active release manifest")
    active = require_exact_keys(active_raw, ACTIVE_KEYS, "Active release manifest")
    if active_body != canonical_json(active):
        raise UploadError("Active release manifest is not canonical builder output")
    if active.get("schema") != ACTIVE_SCHEMA:
        raise UploadError("Active release manifest schema is unsupported")
    release_id = validate_release_id(active.get("release_id"), "active release ID")
    expected_release_path = f"releases/{release_id}"
    if active.get("release_path") != expected_release_path:
        raise UploadError(
            f"Active release path must be exactly {expected_release_path!r}"
        )

    try:
        private_root = active_manifest.parent.resolve(strict=True)
        release_root = (private_root / expected_release_path).resolve(strict=True)
    except OSError as error:
        raise UploadError(f"Unable to resolve active release: {error}") from error
    if not release_root.is_relative_to(private_root) or release_root.name != release_id:
        raise UploadError("Active release resolved outside the private-review workspace")
    release_manifest_path, site_root = validate_release_root(release_root)

    release_raw, release_body = read_json_document(release_manifest_path, "Release manifest")
    release = require_exact_keys(release_raw, RELEASE_KEYS, "Release manifest")
    if release_body != canonical_json(release):
        raise UploadError("Release manifest is not canonical builder output")
    if release.get("schema") != RELEASE_SCHEMA:
        raise UploadError("Release manifest schema is unsupported")
    if release.get("collection_id") != "jefferson":
        raise UploadError("Release manifest collection_id must be 'jefferson'")
    if release.get("access") != "cloudflare_access_authenticated_review":
        raise UploadError("Release manifest access boundary is unsupported")
    validate_timestamp(release.get("generated_at"))
    public_manifest_hash = validate_sha256(
        release.get("public_manifest_sha256"), "public manifest hash"
    )
    private_media_manifest_hash = validate_sha256(
        release.get("private_media_manifest_sha256"), "private media manifest hash"
    )
    manifest_release_id = validate_release_id(release.get("release_id"), "manifest release ID")
    if manifest_release_id != release_id:
        raise UploadError("Active and release manifest IDs do not match")
    private_photo_count = require_nonnegative_integer(
        release.get("private_photo_count"), "private_photo_count"
    )
    if private_photo_count != 4:
        raise UploadError("Release manifest must retain exactly four private photographs")

    site_files_raw = release.get("site_files")
    if not isinstance(site_files_raw, list) or not site_files_raw:
        raise UploadError("Release manifest site_files must be a non-empty array")
    declared_paths: list[str] = []
    declared: list[tuple[str, int, str]] = []
    for index, raw_entry in enumerate(site_files_raw):
        entry = require_exact_keys(raw_entry, SITE_FILE_KEYS, f"site_files[{index}]")
        relative = validate_site_path(entry.get("path"), f"site_files[{index}].path")
        size = require_nonnegative_integer(entry.get("bytes"), f"site_files[{index}].bytes")
        digest = validate_sha256(entry.get("sha256"), f"site_files[{index}].sha256")
        declared_paths.append(relative)
        declared.append((relative, size, digest))
    if declared_paths != sorted(declared_paths, key=site_path_sort_key):
        raise UploadError("Release manifest site_files must be sorted by path")
    if len(declared_paths) != len(set(declared_paths)):
        raise UploadError("Release manifest site_files contains duplicate paths")
    if "index.html" not in set(declared_paths):
        raise UploadError("Release manifest does not declare site/index.html")
    declared_hashes = {path: digest for path, _, digest in declared}
    expected_manifest_hashes = {
        "data/collections/jefferson/manifest.json": public_manifest_hash,
        "data/collections/jefferson/media-authenticated.json": private_media_manifest_hash,
    }
    for relative, expected_hash in expected_manifest_hashes.items():
        if declared_hashes.get(relative) != expected_hash:
            raise UploadError(
                f"Release manifest hash does not match its declared site file: {relative}"
            )

    site_file_count = require_nonnegative_integer(
        release.get("site_file_count"), "site_file_count"
    )
    site_bytes = require_nonnegative_integer(release.get("site_bytes"), "site_bytes")
    if site_file_count != len(declared):
        raise UploadError("Release manifest site_file_count does not match site_files")
    if site_bytes != sum(size for _, size, _ in declared):
        raise UploadError("Release manifest site_bytes does not match site_files")

    release_basis = {key: release[key] for key in RELEASE_BASIS_KEYS}
    computed_release_id = sha256_bytes(canonical_json(release_basis)).removeprefix("sha256:")
    if computed_release_id != release_id:
        raise UploadError("Release ID does not match the canonical release manifest basis")

    actual_files = site_inventory(site_root)
    if list(actual_files) != declared_paths:
        missing = sorted(set(declared_paths) - set(actual_files))
        unexpected = sorted(set(actual_files) - set(declared_paths))
        raise UploadError(
            f"Release site inventory mismatch (missing={missing}, unexpected={unexpected})"
        )

    objects: list[ObjectSpec] = []
    for relative, expected_bytes, expected_hash in declared:
        source = actual_files[relative]
        metadata = validate_regular_file(source, f"Declared site file {relative}")
        if metadata.st_size != expected_bytes:
            raise UploadError(f"Byte-count mismatch for declared site file {relative}")
        if sha256_file(source) != expected_hash:
            raise UploadError(f"SHA-256 mismatch for declared site file {relative}")
        key = validate_object_key(
            f"releases/{release_id}/site/{relative}", release_id
        )
        objects.append(ObjectSpec(source, key, expected_bytes, expected_hash))

    release_key = validate_object_key(f"releases/{release_id}/release.json", release_id)
    objects.append(
        ObjectSpec(
            release_manifest_path,
            release_key,
            len(release_body),
            sha256_bytes(release_body),
        )
    )
    return UploadPlan(
        bucket=bucket,
        release_id=release_id,
        site_file_count=site_file_count,
        site_bytes=site_bytes,
        objects=tuple(objects),
    )


def copy_verified(source: ObjectSpec, destination: Path) -> ObjectSpec:
    destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    flags = os.O_RDONLY
    if hasattr(os, "O_NOFOLLOW"):
        flags |= os.O_NOFOLLOW
    try:
        descriptor = os.open(source.source, flags)
    except OSError as error:
        raise UploadError(f"Unable to open declared object {source.key}: {error}") from error
    digest = hashlib.sha256()
    copied = 0
    try:
        with os.fdopen(descriptor, "rb") as input_handle, destination.open("xb") as output_handle:
            metadata = os.fstat(input_handle.fileno())
            if not stat.S_ISREG(metadata.st_mode):
                raise UploadError(f"Declared object became non-regular: {source.key}")
            for block in iter(lambda: input_handle.read(COPY_BLOCK_BYTES), b""):
                output_handle.write(block)
                digest.update(block)
                copied += len(block)
    except UploadError:
        raise
    except OSError as error:
        raise UploadError(f"Unable to stage declared object {source.key}: {error}") from error
    staged_hash = f"sha256:{digest.hexdigest()}"
    if copied != source.bytes or staged_hash != source.sha256:
        raise UploadError(f"Declared object changed while staging: {source.key}")
    return ObjectSpec(destination, source.key, source.bytes, source.sha256)


def stage_upload(plan: UploadPlan, root: Path) -> tuple[ObjectSpec, ...]:
    staged: list[ObjectSpec] = []
    for item in plan.objects:
        relative = PurePosixPath(item.key)
        destination = root.joinpath(*relative.parts)
        staged.append(copy_verified(item, destination))
    return tuple(staged)


def resolve_wrangler(path: Path) -> Path:
    try:
        executable = path.resolve(strict=True)
    except OSError as error:
        raise UploadError(f"Unable to resolve Wrangler executable {path}: {error}") from error
    if not executable.is_file() or not os.access(executable, os.X_OK):
        raise UploadError(f"Wrangler executable is not an executable file: {executable}")
    return executable


def run_wrangler(
    wrangler: Path,
    arguments: Sequence[str],
    *,
    cwd: Path,
    operation: str,
    key: str,
) -> None:
    command = [str(wrangler), *arguments]
    try:
        completed = subprocess.run(
            command,
            cwd=cwd,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
            timeout=COMMAND_TIMEOUT_SECONDS,
        )
    except subprocess.TimeoutExpired as error:
        raise UploadError(
            f"Wrangler {operation} timed out for {key} after {COMMAND_TIMEOUT_SECONDS}s"
        ) from error
    except OSError as error:
        raise UploadError(f"Unable to run Wrangler {operation} for {key}: {error}") from error
    if completed.returncode != 0:
        raise UploadError(
            f"Wrangler {operation} failed for {key} with exit code {completed.returncode}"
        )


def verify_download(path: Path, expected: ObjectSpec) -> None:
    metadata = validate_regular_file(path, f"Downloaded object {expected.key}")
    if metadata.st_size != expected.bytes:
        raise UploadError(f"Remote byte-count mismatch for {expected.key}")
    if sha256_file(path) != expected.sha256:
        raise UploadError(f"Remote SHA-256 mismatch for {expected.key}")


def upload_and_verify(plan: UploadPlan, wrangler_path: Path) -> None:
    wrangler = resolve_wrangler(wrangler_path)
    if not DEFAULT_WRANGLER_CWD.is_dir():
        raise UploadError(f"Wrangler working directory is unavailable: {DEFAULT_WRANGLER_CWD}")
    try:
        with tempfile.TemporaryDirectory(prefix="shelfsignals-r2-upload-") as temporary:
            workspace = Path(temporary)
            os.chmod(workspace, 0o700)
            staged = stage_upload(plan, workspace / "upload")

            print(
                f"Uploading {len(staged)} manifest-locked objects to {plan.bucket}/"
                f"{plan.remote_prefix}",
                file=os.sys.stderr,
            )
            for index, item in enumerate(staged, start=1):
                run_wrangler(
                    wrangler,
                    [
                        "r2",
                        "object",
                        "put",
                        f"{plan.bucket}/{item.key}",
                        "--remote",
                        "--storage-class",
                        "Standard",
                        "--force",
                        "--file",
                        str(item.source),
                    ],
                    cwd=DEFAULT_WRANGLER_CWD,
                    operation="put",
                    key=item.key,
                )
                if index % 25 == 0 or index == len(staged):
                    print(
                        f"Uploaded {index}/{len(staged)} objects",
                        file=os.sys.stderr,
                    )

            print(
                f"Downloading and verifying {len(staged)} remote objects",
                file=os.sys.stderr,
            )
            download_root = workspace / "download"
            for index, item in enumerate(staged, start=1):
                relative = PurePosixPath(item.key)
                destination = download_root.joinpath(*relative.parts)
                destination.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
                run_wrangler(
                    wrangler,
                    [
                        "r2",
                        "object",
                        "get",
                        f"{plan.bucket}/{item.key}",
                        "--remote",
                        "--file",
                        str(destination),
                    ],
                    cwd=DEFAULT_WRANGLER_CWD,
                    operation="get",
                    key=item.key,
                )
                verify_download(destination, item)
                if index % 25 == 0 or index == len(staged):
                    print(
                        f"Verified {index}/{len(staged)} remote objects",
                        file=os.sys.stderr,
                    )
    except UploadError:
        raise
    except OSError as error:
        raise UploadError(f"Unable to create or clean private temporary workspace: {error}") from error


def summary(plan: UploadPlan, *, dry_run: bool, verified: bool) -> dict[str, Any]:
    return {
        "bucket": plan.bucket,
        "dry_run": dry_run,
        "object_count": len(plan.objects),
        "release_id": plan.release_id,
        "remote_prefix": plan.remote_prefix,
        "site_bytes": plan.site_bytes,
        "site_file_count": plan.site_file_count,
        "total_bytes": plan.total_bytes,
        "verified": verified,
    }


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bucket", required=True, help="Existing private R2 bucket name")
    parser.add_argument(
        "--active-manifest",
        type=Path,
        default=DEFAULT_ACTIVE_MANIFEST,
        help="Ignored active.json emitted by the private-review release builder",
    )
    parser.add_argument(
        "--wrangler",
        type=Path,
        default=DEFAULT_WRANGLER,
        help="Wrangler executable (defaults to the pinned local installation)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Complete local validation and print the plan without any network calls",
    )
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        plan = build_upload_plan(args.active_manifest, args.bucket)
        if args.dry_run:
            print(json.dumps(summary(plan, dry_run=True, verified=False), sort_keys=True))
            return 0
        upload_and_verify(plan, args.wrangler)
    except UploadError as error:
        print(f"error: {error}", file=os.sys.stderr)
        return 2
    print(json.dumps(summary(plan, dry_run=False, verified=True), sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
