#!/usr/bin/env python3
"""Strict contracts for locally photographed or otherwise cleared covers.

This module deliberately contains no image encoder and makes no network
requests.  It is shared by the ingest CLI and the public cover-index builder so
that a typo, stale catalog snapshot, altered derivative, or incomplete rights
record fails closed at both boundaries.
"""

from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime
from pathlib import Path, PurePosixPath
from typing import Any, Callable, Mapping, Sequence
from urllib.parse import urlparse


INTAKE_SCHEMA = "shelfsignals-cleared-cover-intake@1"
CLEARED_REFERENCES_SCHEMA = "shelfsignals-cleared-cover-references@1"
CONTRACT_VERSION = "1.0.0"
PUBLIC_COVER_PREFIX = "images/covers"
MAX_SOURCE_BYTES = 50 * 1024 * 1024
MAX_DERIVATIVE_BYTES = 10 * 1024 * 1024
MAX_SOURCE_PIXELS = 80_000_000
MAX_SOURCE_EDGE = 20_000
RIGHTS_BASES = frozenset({"institution_permission", "open_license", "public_domain"})
PROVIDERS = frozenset({"clark", "licensed"})
SCOPES = frozenset({"clark_copy", "exact_edition"})
PLACEHOLDER_NAMES = frozenset({"unknown", "tbd", "n/a", "none", "reviewer"})
SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
ISO_DATE_RE = re.compile(r"^20\d{2}-\d{2}-\d{2}$")
ISO_UTC_RE = re.compile(r"^20\d{2}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
CATALOG_ID_RE = re.compile(r"^alma\d{18}$")
ASSET_SET_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
LOCAL_COVER_RE = re.compile(
    r"^images/covers/(?P<catalog_id>alma\d{18})/(?P<asset>[0-9a-f]{20})/"
    r"cover-(?P<profile>thumbnail|display)\.webp$"
)

DERIVATIVE_PROFILES: tuple[dict[str, Any], ...] = (
    {"profile": "thumbnail", "max_width": 480, "max_height": 640, "quality": 82},
    {"profile": "display", "max_width": 1280, "max_height": 1600, "quality": 86},
)


class ClearedCoverError(RuntimeError):
    """A local cover cannot cross the public-display boundary safely."""


def sha256_bytes(data: bytes) -> str:
    return "sha256:" + hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return "sha256:" + digest.hexdigest()


def canonical_json_checksum(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256_bytes(payload.encode("utf-8"))


def _object(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ClearedCoverError(f"{label} must be an object")
    return value


def _array(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise ClearedCoverError(f"{label} must be an array")
    return value


def _strict_keys(value: Mapping[str, Any], required: set[str], label: str) -> None:
    actual = set(value)
    missing = sorted(required - actual)
    unknown = sorted(actual - required)
    if missing:
        raise ClearedCoverError(f"{label} is missing required fields: {', '.join(missing)}")
    if unknown:
        raise ClearedCoverError(f"{label} has unsupported fields: {', '.join(unknown)}")


def _text(value: Any, label: str, minimum: int = 1) -> str:
    if not isinstance(value, str) or len(value.strip()) < minimum:
        raise ClearedCoverError(f"{label} must be a nonblank string of at least {minimum} characters")
    return value.strip()


def _positive_integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ClearedCoverError(f"{label} must be a positive integer")
    return value


def _sha256(value: Any, label: str) -> str:
    text = str(value or "").lower()
    if not SHA256_RE.fullmatch(text):
        raise ClearedCoverError(f"{label} must be a lowercase sha256: checksum")
    return text


def _iso_date(value: Any, label: str) -> str:
    text = str(value or "")
    if not ISO_DATE_RE.fullmatch(text):
        raise ClearedCoverError(f"{label} must be YYYY-MM-DD")
    try:
        datetime.strptime(text, "%Y-%m-%d")
    except ValueError as exc:
        raise ClearedCoverError(f"{label} must be a real calendar date") from exc
    return text


def _iso_utc(value: Any, label: str) -> str:
    text = str(value or "")
    if not ISO_UTC_RE.fullmatch(text):
        raise ClearedCoverError(f"{label} must be a second-precision UTC timestamp")
    try:
        datetime.strptime(text, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise ClearedCoverError(f"{label} must be a real second-precision UTC timestamp") from exc
    return text


def _https_url(value: Any, label: str) -> str:
    text = _text(value, label)
    parsed = urlparse(text)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 443)
        or parsed.fragment
    ):
        raise ClearedCoverError(f"{label} must be a clean HTTPS URL")
    return text


def _named_person(value: Any, label: str) -> str:
    text = _text(value, label, 3)
    if text.casefold() in PLACEHOLDER_NAMES:
        raise ClearedCoverError(f"{label} must name the responsible person, not a placeholder")
    return text


def _safe_relative_file(value: Any, label: str) -> str:
    text = _text(value, label)
    path = PurePosixPath(text)
    if path.is_absolute() or ".." in path.parts or "." in path.parts or "\\" in text:
        raise ClearedCoverError(f"{label} must be a traversal-free relative POSIX path")
    return text


def resolve_source_file(source_root: Path, relative_path: str) -> Path:
    root = source_root.resolve()
    lexical_candidate = root / relative_path
    if lexical_candidate.is_symlink():
        raise ClearedCoverError(f"source_file may not be a symlink: {relative_path}")
    candidate = lexical_candidate.resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise ClearedCoverError(f"source_file escapes source root: {relative_path}") from exc
    if not candidate.is_file():
        raise ClearedCoverError(f"source_file is not a regular file: {relative_path}")
    size = candidate.stat().st_size
    if size <= 0 or size > MAX_SOURCE_BYTES:
        raise ClearedCoverError(f"source_file size must be between 1 and {MAX_SOURCE_BYTES} bytes: {relative_path}")
    return candidate


def load_catalog(path: Path) -> tuple[list[Mapping[str, Any]], bytes, str]:
    raw = path.read_bytes()
    payload = json.loads(raw)
    if not isinstance(payload, list):
        raise ClearedCoverError("catalog must be a JSON array")
    records: list[Mapping[str, Any]] = []
    ids: set[str] = set()
    for index, record in enumerate(payload):
        if not isinstance(record, Mapping):
            raise ClearedCoverError(f"catalog record {index} is not an object")
        record_id = str(record.get("id") or "")
        if not record_id or record_id in ids:
            raise ClearedCoverError("catalog IDs must be present and unique")
        ids.add(record_id)
        records.append(record)
    return records, raw, sha256_bytes(raw)


def _string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def catalog_identity_payload(record: Mapping[str, Any], dataset_sha256: str) -> dict[str, Any]:
    """Return the versioned, publication-relevant identity of one record."""

    return {
        "schema": "shelfsignals-catalog-cover-identity@1",
        "dataset_sha256": _sha256(dataset_sha256, "catalog dataset_sha256"),
        "catalog_id": str(record.get("id") or ""),
        "title": str(record.get("title") or ""),
        "authors": _string_list(record.get("authors")),
        "year": str(record.get("year") or ""),
        "call_number": str(record.get("call_number") or ""),
        "isbns": _string_list(record.get("isbns")),
        "oclc_numbers": _string_list(record.get("oclc_numbers")),
        "lccn": _string_list(record.get("lccn")),
        "record_url": str(record.get("record_url") or ""),
    }


def catalog_record_fingerprint(record: Mapping[str, Any], dataset_sha256: str) -> str:
    return canonical_json_checksum(catalog_identity_payload(record, dataset_sha256))


def public_catalog_identity(record: Mapping[str, Any], dataset_sha256: str) -> dict[str, str]:
    return {
        "title": str(record.get("title") or ""),
        "call_number": str(record.get("call_number") or ""),
        "record_url": str(record.get("record_url") or ""),
        "record_fingerprint": catalog_record_fingerprint(record, dataset_sha256),
    }


def _normalize_isbn(value: Any) -> str:
    compact = re.sub(r"[^0-9X]", "", str(value or "").upper())
    if re.fullmatch(r"\d{9}[\dX]", compact):
        total = sum((10 if digit == "X" else int(digit)) * (10 - index) for index, digit in enumerate(compact))
        return compact if total % 11 == 0 else ""
    if re.fullmatch(r"\d{13}", compact):
        total = sum(int(digit) * (3 if index % 2 else 1) for index, digit in enumerate(compact))
        return compact if total % 10 == 0 else ""
    return ""


def _canonical_isbn(value: Any) -> str:
    normalized = _normalize_isbn(value)
    if len(normalized) == 13:
        return normalized
    if len(normalized) != 10:
        return ""
    body = "978" + normalized[:9]
    total = sum(int(digit) * (3 if index % 2 else 1) for index, digit in enumerate(body))
    return body + str((10 - total % 10) % 10)


def _normalize_oclc(value: Any) -> str:
    match = re.search(r"(\d{4,})\s*$", str(value or ""))
    return str(int(match.group(1))) if match else ""


def _normalize_lccn(value: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(value or "").upper())


def _normalized_identifier(kind: str, value: Any) -> str:
    if kind == "isbn":
        return _canonical_isbn(value)
    if kind == "oclc":
        return _normalize_oclc(value)
    if kind == "lccn":
        return _normalize_lccn(value)
    return str(value or "").strip() if kind == "catalog_id" else ""


def _record_identifier_sets(record: Mapping[str, Any]) -> dict[str, set[str]]:
    return {
        "isbn": {value for raw in record.get("isbns") or [] if (value := _canonical_isbn(raw))},
        "oclc": {value for raw in record.get("oclc_numbers") or [] if (value := _normalize_oclc(raw))},
        "lccn": {value for raw in record.get("lccn") or [] if (value := _normalize_lccn(raw))},
    }


def validate_matched_identifiers(
    raw: Any,
    *,
    record: Mapping[str, Any],
    scope: str,
    label: str,
) -> list[dict[str, str]]:
    values = _array(raw, label)
    if not values:
        raise ClearedCoverError(f"{label} must not be empty")
    record_id = str(record.get("id") or "")
    if scope == "clark_copy":
        if values != [{"type": "catalog_id", "value": record_id}]:
            raise ClearedCoverError(f"{label} for Clark-copy evidence must be exactly the catalog ID")
        return [{"type": "catalog_id", "value": record_id}]

    record_sets = _record_identifier_sets(record)
    result: list[dict[str, str]] = []
    for index, candidate in enumerate(values):
        item = _object(candidate, f"{label}[{index}]")
        _strict_keys(item, {"type", "value"}, f"{label}[{index}]")
        kind = str(item.get("type") or "").lower()
        if kind not in {"isbn", "oclc", "lccn"}:
            raise ClearedCoverError(f"{label}[{index}].type is not an exact-edition identifier")
        normalized = _normalized_identifier(kind, item.get("value"))
        if not normalized or normalized not in record_sets[kind]:
            raise ClearedCoverError(f"{label}[{index}] does not match the canonical Clark record")
        normalized_item = {"type": kind, "value": str(item.get("value") or "").strip()}
        if normalized_item not in result:
            result.append(normalized_item)
    if not result:
        raise ClearedCoverError(f"{label} has no exact identifier match")
    return result


def _validate_catalog_identity(
    raw: Any,
    *,
    record: Mapping[str, Any],
    dataset_sha256: str,
    label: str,
) -> dict[str, str]:
    identity = _object(raw, label)
    _strict_keys(identity, {"title", "call_number", "record_url", "record_fingerprint"}, label)
    expected = public_catalog_identity(record, dataset_sha256)
    normalized = {
        "title": str(identity.get("title") or ""),
        "call_number": str(identity.get("call_number") or ""),
        "record_url": _https_url(identity.get("record_url"), f"{label}.record_url"),
        "record_fingerprint": _sha256(identity.get("record_fingerprint"), f"{label}.record_fingerprint"),
    }
    if normalized != expected:
        raise ClearedCoverError(f"{label} does not match the canonical catalog snapshot")
    return normalized


def _validate_source_declaration(raw: Any, label: str) -> dict[str, str]:
    source = _object(raw, label)
    _strict_keys(source, {"source_id", "source_reference_url", "creator", "source_date"}, label)
    return {
        "source_id": _text(source.get("source_id"), f"{label}.source_id", 3),
        "source_reference_url": _https_url(source.get("source_reference_url"), f"{label}.source_reference_url"),
        "creator": _text(source.get("creator"), f"{label}.creator", 3),
        "source_date": _iso_date(source.get("source_date"), f"{label}.source_date"),
    }


def _validate_rights(raw: Any, label: str) -> dict[str, Any]:
    rights = _object(raw, label)
    _strict_keys(
        rights,
        {
            "basis",
            "public_display",
            "derivatives_allowed",
            "license_or_permission_reference",
            "evidence_url",
            "rights_holder",
            "credit_line",
            "evidence_note",
        },
        label,
    )
    basis = str(rights.get("basis") or "")
    if basis not in RIGHTS_BASES:
        raise ClearedCoverError(f"{label}.basis must be an approved cleared-rights basis")
    if rights.get("public_display") is not True:
        raise ClearedCoverError(f"{label}.public_display must be explicitly true")
    if rights.get("derivatives_allowed") is not True:
        raise ClearedCoverError(f"{label}.derivatives_allowed must be explicitly true")
    return {
        "basis": basis,
        "public_display": True,
        "derivatives_allowed": True,
        "license_or_permission_reference": _text(
            rights.get("license_or_permission_reference"),
            f"{label}.license_or_permission_reference",
            8,
        ),
        "evidence_url": _https_url(rights.get("evidence_url"), f"{label}.evidence_url"),
        "rights_holder": _text(rights.get("rights_holder"), f"{label}.rights_holder", 3),
        "credit_line": _text(rights.get("credit_line"), f"{label}.credit_line", 3),
        "evidence_note": _text(rights.get("evidence_note"), f"{label}.evidence_note", 20),
    }


def _validate_review(raw: Any, label: str, *, require_status: bool) -> dict[str, str]:
    review = _object(raw, label)
    required = {"reviewer", "reviewed_at", "evidence_note"}
    if require_status:
        required |= {"status", "candidate_fingerprint"}
    _strict_keys(review, required, label)
    result = {
        "reviewer": _named_person(review.get("reviewer"), f"{label}.reviewer"),
        "reviewed_at": _iso_utc(review.get("reviewed_at"), f"{label}.reviewed_at"),
        "evidence_note": _text(review.get("evidence_note"), f"{label}.evidence_note", 20),
    }
    if require_status:
        if review.get("status") != "approved":
            raise ClearedCoverError(f"{label}.status must be approved")
        result["status"] = "approved"
        result["candidate_fingerprint"] = _sha256(
            review.get("candidate_fingerprint"), f"{label}.candidate_fingerprint"
        )
    return result


def _validate_image_declaration(raw: Any, label: str) -> dict[str, Any]:
    image = _object(raw, label)
    _strict_keys(image, {"sha256", "width", "height", "format", "bytes"}, label)
    width = _positive_integer(image.get("width"), f"{label}.width")
    height = _positive_integer(image.get("height"), f"{label}.height")
    byte_count = _positive_integer(image.get("bytes"), f"{label}.bytes")
    image_format = str(image.get("format") or "").lower()
    if image_format not in {"jpeg", "png", "tiff", "webp"}:
        raise ClearedCoverError(f"{label}.format must be jpeg, png, tiff, or webp")
    if width > MAX_SOURCE_EDGE or height > MAX_SOURCE_EDGE or width * height > MAX_SOURCE_PIXELS:
        raise ClearedCoverError(f"{label} exceeds the bounded source-image limits")
    if byte_count > MAX_SOURCE_BYTES:
        raise ClearedCoverError(f"{label}.bytes exceeds the bounded source-file limit")
    return {
        "sha256": _sha256(image.get("sha256"), f"{label}.sha256"),
        "width": width,
        "height": height,
        "format": image_format,
        "bytes": byte_count,
    }


def candidate_fingerprint(
    *,
    catalog_id: str,
    catalog_record_fingerprint_value: str,
    provider: str,
    scope: str,
    matched_identifiers: Sequence[Mapping[str, str]],
    source: Mapping[str, Any],
    source_image: Mapping[str, Any],
    rights: Mapping[str, Any],
    identity_attestation: str,
    review: Mapping[str, Any],
) -> str:
    payload = {
        "schema": "shelfsignals-cleared-cover-candidate@1",
        "catalog_id": catalog_id,
        "catalog_record_fingerprint": catalog_record_fingerprint_value,
        "provider": provider,
        "scope": scope,
        "matched_identifiers": sorted(
            ({"type": str(item["type"]), "value": str(item["value"])} for item in matched_identifiers),
            key=lambda item: (item["type"], item["value"]),
        ),
        "source": dict(source),
        "source_image": dict(source_image),
        "rights": dict(rights),
        "identity_attestation": identity_attestation,
        "reviewer": review["reviewer"],
        "reviewed_at": review["reviewed_at"],
        "review_evidence_note": review["evidence_note"],
    }
    return canonical_json_checksum(payload)


SourceProbe = Callable[[Path], Mapping[str, Any]]


def validate_intake_manifest(
    manifest: Any,
    *,
    catalog: Sequence[Mapping[str, Any]],
    catalog_sha256: str,
    source_root: Path | None = None,
    source_probe: SourceProbe | None = None,
) -> list[dict[str, Any]]:
    """Validate an operator intake; optionally verify every source file."""

    root = _object(manifest, "intake")
    _strict_keys(root, {"schema", "catalog", "items"}, "intake")
    if root.get("schema") != INTAKE_SCHEMA:
        raise ClearedCoverError(f"intake.schema must be {INTAKE_SCHEMA}")
    catalog_meta = _object(root.get("catalog"), "intake.catalog")
    _strict_keys(catalog_meta, {"dataset_sha256", "record_count"}, "intake.catalog")
    declared_sha = _sha256(catalog_meta.get("dataset_sha256"), "intake.catalog.dataset_sha256")
    if declared_sha != catalog_sha256:
        raise ClearedCoverError("intake catalog checksum is stale or belongs to another dataset")
    declared_count = catalog_meta.get("record_count")
    if isinstance(declared_count, bool) or not isinstance(declared_count, int) or declared_count != len(catalog):
        raise ClearedCoverError("intake catalog record_count does not match the canonical dataset")

    record_by_id = {str(record.get("id") or ""): record for record in catalog}
    raw_items = _array(root.get("items"), "intake.items")
    if not raw_items:
        raise ClearedCoverError("intake.items must contain at least one reviewed cover")
    validated: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, raw_item in enumerate(raw_items):
        label = f"intake.items[{index}]"
        item = _object(raw_item, label)
        _strict_keys(
            item,
            {
                "catalog_id",
                "catalog_identity",
                "provider",
                "scope",
                "source_file",
                "source",
                "identity",
                "image",
                "rights",
                "review",
            },
            label,
        )
        catalog_id = str(item.get("catalog_id") or "")
        if catalog_id in seen:
            raise ClearedCoverError(f"{label}.catalog_id duplicates {catalog_id}")
        seen.add(catalog_id)
        record = record_by_id.get(catalog_id)
        if record is None:
            raise ClearedCoverError(f"{label}.catalog_id is outside the canonical catalog")
        identity = _validate_catalog_identity(
            item.get("catalog_identity"), record=record, dataset_sha256=catalog_sha256, label=f"{label}.catalog_identity"
        )
        provider = str(item.get("provider") or "")
        scope = str(item.get("scope") or "")
        if provider not in PROVIDERS or scope not in SCOPES:
            raise ClearedCoverError(f"{label} has an unsupported provider or scope")
        if provider == "clark" and scope != "clark_copy":
            raise ClearedCoverError(f"{label}: Clark first-party assets must attest the Clark copy")

        source_file = _safe_relative_file(item.get("source_file"), f"{label}.source_file")
        source = _validate_source_declaration(item.get("source"), f"{label}.source")
        if provider == "clark" and source["source_reference_url"] != identity["record_url"]:
            raise ClearedCoverError(f"{label}: a Clark-copy source reference must be the exact catalog URL")
        identity_gate = _object(item.get("identity"), f"{label}.identity")
        _strict_keys(
            identity_gate,
            {"front_cover_confirmed", "copy_or_edition_confirmed", "attestation", "matched_identifiers"},
            f"{label}.identity",
        )
        if identity_gate.get("front_cover_confirmed") is not True:
            raise ClearedCoverError(f"{label}.identity.front_cover_confirmed must be explicitly true")
        if identity_gate.get("copy_or_edition_confirmed") is not True:
            raise ClearedCoverError(f"{label}.identity.copy_or_edition_confirmed must be explicitly true")
        attestation = _text(identity_gate.get("attestation"), f"{label}.identity.attestation", 24)
        identifiers = validate_matched_identifiers(
            identity_gate.get("matched_identifiers"), record=record, scope=scope, label=f"{label}.identity.matched_identifiers"
        )
        image = _validate_image_declaration(item.get("image"), f"{label}.image")
        rights = _validate_rights(item.get("rights"), f"{label}.rights")
        review = _validate_review(item.get("review"), f"{label}.review", require_status=False)

        source_path: Path | None = None
        if source_root is not None:
            source_path = resolve_source_file(source_root, source_file)
            actual_sha = sha256_file(source_path)
            if actual_sha != image["sha256"] or source_path.stat().st_size != image["bytes"]:
                raise ClearedCoverError(f"{label}.image does not match the source file bytes")
            if source_probe is None:
                raise ClearedCoverError("source_probe is required when source_root is supplied")
            probed = dict(source_probe(source_path))
            for field in ("width", "height", "format", "bytes", "sha256"):
                if probed.get(field) != image[field]:
                    raise ClearedCoverError(f"{label}.image.{field} does not match decoded source evidence")
            if probed.get("animated") is not False:
                raise ClearedCoverError(f"{label}.image must be a single-frame source")

        validated.append({
            "catalog_id": catalog_id,
            "catalog_identity": identity,
            "provider": provider,
            "scope": scope,
            "source_file": source_file,
            "source": source,
            "identity": {
                "front_cover_confirmed": True,
                "copy_or_edition_confirmed": True,
                "attestation": attestation,
                "matched_identifiers": identifiers,
            },
            "image": image,
            "rights": rights,
            "review": review,
            "_record": record,
            "_source_path": source_path,
        })
    return validated


def derivative_asset_set_fingerprint(source_image: Mapping[str, Any], pillow_version: str) -> str:
    return canonical_json_checksum({
        "schema": "shelfsignals-cover-derivative-plan@1",
        "source": dict(source_image),
        "encoder": "Pillow WebP",
        "encoder_version": pillow_version,
        "strip_metadata": True,
        "upscale": False,
        "profiles": list(DERIVATIVE_PROFILES),
    })


def _safe_local_cover_url(value: Any, *, catalog_id: str, profile: str, asset_fingerprint: str, label: str) -> str:
    text = _text(value, label)
    match = LOCAL_COVER_RE.fullmatch(text)
    expected_asset = asset_fingerprint.removeprefix("sha256:")[:20]
    if (
        match is None
        or match.group("catalog_id") != catalog_id
        or match.group("profile") != profile
        or match.group("asset") != expected_asset
    ):
        raise ClearedCoverError(f"{label} is outside the immutable local-cover path contract")
    return text


def webp_dimensions(data: bytes, label: str = "WebP derivative") -> tuple[int, int]:
    """Read dimensions from the three WebP bitstream headers without Pillow."""

    if len(data) < 25 or data[:4] != b"RIFF" or data[8:12] != b"WEBP":
        raise ClearedCoverError(f"{label} is not a WebP RIFF image")
    declared_size = int.from_bytes(data[4:8], "little") + 8
    if declared_size != len(data):
        raise ClearedCoverError(f"{label} has a malformed RIFF length")
    offset = 12
    while offset + 8 <= len(data):
        chunk = data[offset:offset + 4]
        size = int.from_bytes(data[offset + 4:offset + 8], "little")
        start = offset + 8
        end = start + size
        if end > len(data):
            raise ClearedCoverError(f"{label} has a truncated WebP chunk")
        payload = data[start:end]
        if chunk == b"VP8X":
            if len(payload) < 10:
                raise ClearedCoverError(f"{label} has a truncated VP8X header")
            if payload[0] & 0x02:
                raise ClearedCoverError(f"{label} may not be animated")
            return int.from_bytes(payload[4:7], "little") + 1, int.from_bytes(payload[7:10], "little") + 1
        if chunk == b"VP8 ":
            if len(payload) < 10 or payload[3:6] != b"\x9d\x01\x2a":
                raise ClearedCoverError(f"{label} has an invalid VP8 frame header")
            return int.from_bytes(payload[6:8], "little") & 0x3FFF, int.from_bytes(payload[8:10], "little") & 0x3FFF
        if chunk == b"VP8L":
            if len(payload) < 5 or payload[0] != 0x2F:
                raise ClearedCoverError(f"{label} has an invalid VP8L frame header")
            bits = int.from_bytes(payload[1:5], "little")
            return (bits & 0x3FFF) + 1, ((bits >> 14) & 0x3FFF) + 1
        offset = end + (size & 1)
    raise ClearedCoverError(f"{label} has no supported WebP image chunk")


def _validate_derivative(
    raw: Any,
    *,
    catalog_id: str,
    asset_fingerprint: str,
    profile: Mapping[str, Any],
    docs_root: Path | None,
    label: str,
) -> dict[str, Any]:
    derivative = _object(raw, label)
    _strict_keys(
        derivative,
        {"profile", "url", "width", "height", "format", "sha256", "bytes", "max_width", "max_height"},
        label,
    )
    profile_name = str(profile["profile"])
    if derivative.get("profile") != profile_name or derivative.get("format") != "webp":
        raise ClearedCoverError(f"{label} has the wrong derivative profile or format")
    max_width = _positive_integer(derivative.get("max_width"), f"{label}.max_width")
    max_height = _positive_integer(derivative.get("max_height"), f"{label}.max_height")
    if max_width != profile["max_width"] or max_height != profile["max_height"]:
        raise ClearedCoverError(f"{label} changes the bounded derivative profile")
    width = _positive_integer(derivative.get("width"), f"{label}.width")
    height = _positive_integer(derivative.get("height"), f"{label}.height")
    if width > max_width or height > max_height:
        raise ClearedCoverError(f"{label} exceeds its bounded dimensions")
    url = _safe_local_cover_url(
        derivative.get("url"),
        catalog_id=catalog_id,
        profile=profile_name,
        asset_fingerprint=asset_fingerprint,
        label=f"{label}.url",
    )
    checksum = _sha256(derivative.get("sha256"), f"{label}.sha256")
    byte_count = _positive_integer(derivative.get("bytes"), f"{label}.bytes")
    if byte_count > MAX_DERIVATIVE_BYTES:
        raise ClearedCoverError(f"{label}.bytes exceeds the local derivative limit")
    if docs_root is not None:
        root = docs_root.resolve()
        lexical_path = root / url
        if lexical_path.is_symlink():
            raise ClearedCoverError(f"{label}.url may not be a symlink")
        path = lexical_path.resolve()
        try:
            path.relative_to(root)
        except ValueError as exc:
            raise ClearedCoverError(f"{label}.url escapes docs root") from exc
        if not path.is_file() or path.is_symlink():
            raise ClearedCoverError(f"{label}.url does not resolve to a regular immutable derivative")
        data = path.read_bytes()
        if len(data) != byte_count or sha256_bytes(data) != checksum:
            raise ClearedCoverError(f"{label} bytes do not match the reviewed reference")
        if webp_dimensions(data, label) != (width, height):
            raise ClearedCoverError(f"{label} decoded dimensions do not match the reviewed reference")
    return {
        "profile": profile_name,
        "url": url,
        "width": width,
        "height": height,
        "format": "webp",
        "sha256": checksum,
        "bytes": byte_count,
        "max_width": max_width,
        "max_height": max_height,
    }


def validate_cleared_references(
    manifest: Any,
    *,
    catalog: Sequence[Mapping[str, Any]],
    catalog_sha256: str,
    docs_root: Path | None = None,
) -> dict[str, dict[str, Any]]:
    """Revalidate the reviewed local references and, optionally, their bytes."""

    root = _object(manifest, "cleared references")
    _strict_keys(root, {"schema", "version", "generated_at", "source", "policy", "summary", "items"}, "cleared references")
    if root.get("schema") != CLEARED_REFERENCES_SCHEMA or root.get("version") != CONTRACT_VERSION:
        raise ClearedCoverError(f"cleared references must use {CLEARED_REFERENCES_SCHEMA} version {CONTRACT_VERSION}")
    generated_at = _iso_utc(root.get("generated_at"), "cleared references.generated_at")
    source_meta = _object(root.get("source"), "cleared references.source")
    _strict_keys(
        source_meta,
        {"pipeline", "pipeline_version", "catalog_dataset_sha256", "catalog_record_count", "intake_sha256", "pillow_version"},
        "cleared references.source",
    )
    if source_meta.get("pipeline") != "ingest_cleared_covers.py" or source_meta.get("pipeline_version") != CONTRACT_VERSION:
        raise ClearedCoverError("cleared references have an unsupported ingest pipeline")
    if _sha256(source_meta.get("catalog_dataset_sha256"), "cleared references.source.catalog_dataset_sha256") != catalog_sha256:
        raise ClearedCoverError("cleared references are stale for the active catalog checksum")
    source_count = source_meta.get("catalog_record_count")
    if isinstance(source_count, bool) or not isinstance(source_count, int) or source_count != len(catalog):
        raise ClearedCoverError("cleared references catalog record count does not match")
    _sha256(source_meta.get("intake_sha256"), "cleared references.source.intake_sha256")
    pillow_version = _text(source_meta.get("pillow_version"), "cleared references.source.pillow_version")

    policy = _object(root.get("policy"), "cleared references.policy")
    _strict_keys(policy, {"unreviewed_items_included", "original_binaries_included", "local_derivatives_only"}, "cleared references.policy")
    if policy != {
        "unreviewed_items_included": False,
        "original_binaries_included": False,
        "local_derivatives_only": True,
    }:
        raise ClearedCoverError("cleared references policy does not prove reviewed derivative-only publication")
    summary = _object(root.get("summary"), "cleared references.summary")
    _strict_keys(summary, {"published", "clark_copy", "exact_edition"}, "cleared references.summary")
    items = _object(root.get("items"), "cleared references.items")
    for field in ("published", "clark_copy", "exact_edition"):
        value = summary.get(field)
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ClearedCoverError(f"cleared references.summary.{field} must be a non-negative integer")
    if summary.get("published") != len(items):
        raise ClearedCoverError("cleared reference summary does not match item count")

    record_by_id = {str(record.get("id") or ""): record for record in catalog}
    validated: dict[str, dict[str, Any]] = {}
    scope_counts = {"clark_copy": 0, "exact_edition": 0}
    for catalog_id, raw_item in items.items():
        label = f"cleared references.items.{catalog_id}"
        if not CATALOG_ID_RE.fullmatch(str(catalog_id)) or catalog_id not in record_by_id:
            raise ClearedCoverError(f"{label} is outside the canonical catalog")
        item = _object(raw_item, label)
        _strict_keys(
            item,
            {
                "status",
                "provider",
                "scope",
                "catalog_identity",
                "matched_identifiers",
                "source",
                "image",
                "rights",
                "review",
                "gate_receipt",
                "provenance",
            },
            label,
        )
        if item.get("status") != "resolved":
            raise ClearedCoverError(f"{label}.status must be resolved")
        record = record_by_id[catalog_id]
        identity = _validate_catalog_identity(
            item.get("catalog_identity"), record=record, dataset_sha256=catalog_sha256, label=f"{label}.catalog_identity"
        )
        provider = str(item.get("provider") or "")
        scope = str(item.get("scope") or "")
        if provider not in PROVIDERS or scope not in SCOPES or (provider == "clark" and scope != "clark_copy"):
            raise ClearedCoverError(f"{label} has an invalid provider/scope pairing")
        identifiers = validate_matched_identifiers(
            item.get("matched_identifiers"), record=record, scope=scope, label=f"{label}.matched_identifiers"
        )
        source = _validate_source_declaration(item.get("source"), f"{label}.source")
        if provider == "clark" and source["source_reference_url"] != identity["record_url"]:
            raise ClearedCoverError(f"{label} Clark-copy source does not cite the exact catalog record")
        rights = _validate_rights(item.get("rights"), f"{label}.rights")
        review = _validate_review(item.get("review"), f"{label}.review", require_status=True)

        image = _object(item.get("image"), f"{label}.image")
        _strict_keys(image, {"image_url", "thumbnail_url", "width", "height", "source", "derivatives"}, f"{label}.image")
        source_image = _validate_image_declaration(image.get("source"), f"{label}.image.source")
        asset_fingerprint = derivative_asset_set_fingerprint(source_image, pillow_version)
        raw_derivatives = _array(image.get("derivatives"), f"{label}.image.derivatives")
        if len(raw_derivatives) != len(DERIVATIVE_PROFILES):
            raise ClearedCoverError(f"{label}.image.derivatives must contain exactly the approved profiles")
        derivative_by_profile: dict[str, dict[str, Any]] = {}
        for derivative_index, profile in enumerate(DERIVATIVE_PROFILES):
            derivative = _validate_derivative(
                raw_derivatives[derivative_index],
                catalog_id=catalog_id,
                asset_fingerprint=asset_fingerprint,
                profile=profile,
                docs_root=docs_root,
                label=f"{label}.image.derivatives[{derivative_index}]",
            )
            derivative_by_profile[derivative["profile"]] = derivative
        display = derivative_by_profile["display"]
        thumbnail = derivative_by_profile["thumbnail"]
        for derivative in (thumbnail, display):
            if derivative["width"] > source_image["width"] or derivative["height"] > source_image["height"]:
                raise ClearedCoverError(f"{label}.image derivatives may not upscale the reviewed source")
            aspect_error = abs(
                derivative["width"] * source_image["height"]
                - derivative["height"] * source_image["width"]
            )
            if aspect_error > max(source_image["width"], source_image["height"]):
                raise ClearedCoverError(f"{label}.image derivative aspect ratio does not preserve the source")
        if display["width"] < thumbnail["width"] or display["height"] < thumbnail["height"]:
            raise ClearedCoverError(f"{label}.image display derivative may not be smaller than its thumbnail")
        if image.get("image_url") != display["url"] or image.get("thumbnail_url") != thumbnail["url"]:
            raise ClearedCoverError(f"{label}.image URLs do not select the reviewed derivative profiles")
        if image.get("width") != display["width"] or image.get("height") != display["height"]:
            raise ClearedCoverError(f"{label}.image dimensions do not match the display derivative")

        gate = _object(item.get("gate_receipt"), f"{label}.gate_receipt")
        _strict_keys(
            gate,
            {
                "front_cover_confirmed",
                "copy_or_edition_confirmed",
                "visual_check",
                "rights_scope",
                "identity_attestation",
                "candidate_fingerprint",
            },
            f"{label}.gate_receipt",
        )
        if (
            gate.get("front_cover_confirmed") is not True
            or gate.get("copy_or_edition_confirmed") is not True
            or gate.get("visual_check") is not True
            or gate.get("rights_scope") != "local_derivatives"
        ):
            raise ClearedCoverError(f"{label} lacks the full identity/visual/rights gate receipt")
        attestation = _text(gate.get("identity_attestation"), f"{label}.gate_receipt.identity_attestation", 24)
        gate_fingerprint = _sha256(gate.get("candidate_fingerprint"), f"{label}.gate_receipt.candidate_fingerprint")
        expected_fingerprint = candidate_fingerprint(
            catalog_id=catalog_id,
            catalog_record_fingerprint_value=identity["record_fingerprint"],
            provider=provider,
            scope=scope,
            matched_identifiers=identifiers,
            source=source,
            source_image=source_image,
            rights=rights,
            identity_attestation=attestation,
            review=review,
        )
        if gate_fingerprint != expected_fingerprint or review["candidate_fingerprint"] != expected_fingerprint:
            raise ClearedCoverError(f"{label} has a stale or edited candidate fingerprint")

        provenance = _object(item.get("provenance"), f"{label}.provenance")
        _strict_keys(
            provenance,
            {
                "catalog_url",
                "catalog_dataset_sha256",
                "catalog_record_fingerprint",
                "source_file_name",
                "source_id",
                "source_reference_url",
                "asset_set_fingerprint",
                "ingested_at",
            },
            f"{label}.provenance",
        )
        if (
            provenance.get("catalog_url") != identity["record_url"]
            or provenance.get("catalog_dataset_sha256") != catalog_sha256
            or provenance.get("catalog_record_fingerprint") != identity["record_fingerprint"]
            or provenance.get("source_id") != source["source_id"]
            or provenance.get("source_reference_url") != source["source_reference_url"]
            or provenance.get("asset_set_fingerprint") != asset_fingerprint
        ):
            raise ClearedCoverError(f"{label}.provenance conflicts with reviewed evidence")
        source_name = _text(provenance.get("source_file_name"), f"{label}.provenance.source_file_name")
        if Path(source_name).name != source_name:
            raise ClearedCoverError(f"{label}.provenance.source_file_name must not expose a filesystem path")
        if _iso_utc(provenance.get("ingested_at"), f"{label}.provenance.ingested_at") != generated_at:
            raise ClearedCoverError(f"{label}.provenance.ingested_at conflicts with manifest generation time")

        scope_counts[scope] += 1
        normalized = dict(item)
        normalized["_display_derivative"] = display
        normalized["_thumbnail_derivative"] = thumbnail
        normalized["_source_image"] = source_image
        normalized["_candidate_fingerprint"] = expected_fingerprint
        validated[catalog_id] = normalized

    if summary.get("clark_copy") != scope_counts["clark_copy"] or summary.get("exact_edition") != scope_counts["exact_edition"]:
        raise ClearedCoverError("cleared reference scope summary does not match its items")
    return validated


def minimal_webp_vp8x(width: int, height: int) -> bytes:
    """Create a header-only WebP for parser/contract tests, never publication."""

    if width <= 0 or height <= 0 or width > 0x1000000 or height > 0x1000000:
        raise ValueError("test dimensions out of range")
    payload = b"\x00\x00\x00\x00" + (width - 1).to_bytes(3, "little") + (height - 1).to_bytes(3, "little")
    chunk = b"VP8X" + len(payload).to_bytes(4, "little") + payload
    body = b"WEBP" + chunk
    return b"RIFF" + len(body).to_bytes(4, "little") + body
