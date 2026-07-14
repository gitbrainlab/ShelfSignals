#!/usr/bin/env python3
"""Build the compact public cover index and lazy provenance manifest.

The public interface needs a truthful visual state for every Clark record, but it
does not need optical analysis or detailed source evidence before first paint.
This generator therefore separates a small, all-record index from provenance
that is requested only when a researcher opens a record drawer.

The existing ``book_visuals.json`` file remains the exact-identifier migration
input. Its 13 legacy records have no named visual reviewer, so this script
publishes them only as clearly labeled provider references, never as reviewed
approvals. An optional ``shelfsignals-reviewed-cover-references@1`` input can
promote strictly validated, named provider approvals to verified. A separate
``shelfsignals-cleared-cover-references@1`` input admits only checksum-verified
local derivatives with explicit display and derivative authority. This script
does not discover covers or make network requests.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping

try:
    from cleared_cover_contract import (
        CLEARED_REFERENCES_SCHEMA,
        ClearedCoverError,
        validate_cleared_references,
    )
except ModuleNotFoundError:  # Supports ``python -m scripts.build_cover_index``.
    from scripts.cleared_cover_contract import (  # type: ignore
        CLEARED_REFERENCES_SCHEMA,
        ClearedCoverError,
        validate_cleared_references,
    )


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = ROOT / "docs/data/sekula_index.json"
DEFAULT_VISUALS = ROOT / "docs/data/book_visuals.json"
DEFAULT_INDEX = ROOT / "docs/data/cover_index.json"
DEFAULT_PROVENANCE = ROOT / "docs/data/cover_provenance.json"

INDEX_SCHEMA = "shelfsignals-cover-index@1"
PROVENANCE_SCHEMA = "shelfsignals-cover-provenance@1"
REVIEWED_REFERENCES_SCHEMA = "shelfsignals-reviewed-cover-references@1"
UNRESOLVED_LABEL = "Cover not yet verified for this edition"
OPEN_LIBRARY_LICENSE_URL = "https://openlibrary.org/developers/licensing"
PROVIDER_REFERENCE_LABEL = "Exact-ISBN provider cover · visual review pending"
REVIEWED_COVER_LABEL = "Human-reviewed exact-edition cover"
CLARK_COPY_COVER_LABEL = "Human-reviewed Clark-copy cover"
LICENSED_COVER_LABEL = "Human-reviewed rights-cleared exact-edition cover"
ISO_UTC_RE = re.compile(r"^20\d{2}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$", re.IGNORECASE)
DUMP_CHECKSUM_RE = re.compile(r"^(?:md5:[0-9a-f]{32}|sha256:[0-9a-f]{64})$", re.IGNORECASE)
OL_EDITION_RE = re.compile(r"^OL\d+M$")
OPEN_LIBRARY_COVER_RE = re.compile(
    r"^https://covers\.openlibrary\.org/b/id/(?P<cover_id>\d+)-(?P<size>[LM])\.jpg\?default=false$"
)


class CoverIndexError(RuntimeError):
    """The source inputs cannot produce a trustworthy public manifest."""


def sha256_bytes(data: bytes) -> str:
    return f"sha256:{hashlib.sha256(data).hexdigest()}"


def canonical_json_checksum(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return sha256_bytes(payload.encode("utf-8"))


def load_json(path: Path) -> tuple[Any, bytes]:
    raw = path.read_bytes()
    return json.loads(raw), raw


def normalized_isbn(value: Any) -> str:
    compact = re.sub(r"[^0-9X]", "", str(value or "").upper())
    if re.fullmatch(r"\d{9}[\dX]", compact):
        total = sum((10 if digit == "X" else int(digit)) * (10 - index) for index, digit in enumerate(compact))
        return compact if total % 11 == 0 else ""
    if re.fullmatch(r"\d{13}", compact):
        total = sum(int(digit) * (3 if index % 2 else 1) for index, digit in enumerate(compact))
        return compact if total % 10 == 0 else ""
    return ""


def canonical_isbn13(value: Any) -> str:
    """Return a comparison key while preserving the source identifier."""
    normalized = normalized_isbn(value)
    if len(normalized) == 13:
        return normalized
    if len(normalized) != 10:
        return ""
    body = f"978{normalized[:9]}"
    total = sum(int(digit) * (3 if index % 2 else 1) for index, digit in enumerate(body))
    return f"{body}{(10 - total % 10) % 10}"


def image_dimensions(visual: Mapping[str, Any]) -> tuple[int, int]:
    analysis = visual.get("image_analysis") if isinstance(visual.get("image_analysis"), Mapping) else {}
    pixels = analysis.get("source_pixels") if isinstance(analysis.get("source_pixels"), Mapping) else {}
    width = int(pixels.get("width") or 0)
    height = int(pixels.get("height") or 0)
    if width <= 0 or height <= 0:
        ratio = float(visual.get("aspect_ratio") or 0)
        if ratio > 0:
            height = 1000
            width = max(1, round(height * ratio))
    if width <= 0 or height <= 0:
        raise CoverIndexError("resolved cover lacks usable pixel dimensions")
    return width, height


def matched_identifiers(record: Mapping[str, Any], visual: Mapping[str, Any]) -> list[dict[str, str]]:
    method = str(visual.get("match_method") or "").lower()
    source_id = str(visual.get("source_id") or "").strip()
    if method in {"isbn", "isbn_exact"}:
        matched = normalized_isbn(source_id)
        matched_key = canonical_isbn13(matched)
        record_isbns = {canonical_isbn13(value) for value in record.get("isbns") or []}
        record_isbns.discard("")
        if not matched or not matched_key or matched_key not in record_isbns:
            raise CoverIndexError(f"{record.get('id')} cover ISBN does not match the Clark record")
        return [{"type": "isbn", "value": matched}]
    raise CoverIndexError(f"{record.get('id')} uses unsupported cover match method {method!r}")


def reviewed_matched_identifiers(record: Mapping[str, Any], reference: Mapping[str, Any]) -> list[dict[str, str]]:
    """Validate and retain the reviewed manifest's exact ISBN evidence."""

    raw = reference.get("matched_identifiers")
    if not isinstance(raw, list) or not raw:
        raise CoverIndexError(f"{record.get('id')} reviewed cover has no matched identifiers")
    record_isbns = {canonical_isbn13(value) for value in record.get("isbns") or []}
    record_isbns.discard("")
    result: list[dict[str, str]] = []
    for identifier in raw:
        if not isinstance(identifier, Mapping) or str(identifier.get("type") or "").lower() != "isbn":
            raise CoverIndexError(f"{record.get('id')} reviewed cover uses a non-ISBN match")
        value = normalized_isbn(identifier.get("value"))
        canonical = canonical_isbn13(value)
        if not value or canonical not in record_isbns:
            raise CoverIndexError(f"{record.get('id')} reviewed cover ISBN does not match the Clark record")
        item = {"type": "isbn", "value": value}
        if item not in result:
            result.append(item)
    return result


def positive_integer(value: Any, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise CoverIndexError(f"{label} must be a positive integer")
    return value


def validate_reviewed_references(
    reviewed: Mapping[str, Any],
    record_by_id: Mapping[str, Mapping[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Fail closed unless every reviewed reference matches the publisher contract."""

    if reviewed.get("schema") != REVIEWED_REFERENCES_SCHEMA:
        raise CoverIndexError(f"reviewed references must use {REVIEWED_REFERENCES_SCHEMA}")
    items = reviewed.get("items")
    if not isinstance(items, Mapping):
        raise CoverIndexError("reviewed references must contain an items object")
    policy = reviewed.get("policy") if isinstance(reviewed.get("policy"), Mapping) else {}
    if policy.get("unreviewed_candidates_included") is not False:
        raise CoverIndexError("reviewed references do not explicitly exclude unreviewed candidates")
    if policy.get("binary_images_included") is not False:
        raise CoverIndexError("reviewed references must not embed provider image binaries")
    summary = reviewed.get("summary") if isinstance(reviewed.get("summary"), Mapping) else {}
    published_count = summary.get("published")
    if isinstance(published_count, bool) or not isinstance(published_count, int) or published_count != len(items):
        raise CoverIndexError("reviewed reference summary does not match its item count")

    validated: dict[str, dict[str, Any]] = {}
    for raw_record_id, raw_reference in items.items():
        record_id = str(raw_record_id or "")
        record = record_by_id.get(record_id)
        if record is None:
            raise CoverIndexError(f"reviewed cover references unknown catalog ID {record_id!r}")
        if not isinstance(raw_reference, Mapping):
            raise CoverIndexError(f"{record_id} reviewed cover is not an object")
        reference = dict(raw_reference)
        required_states = {
            "status": "resolved",
            "lookup_status": "positive",
            "scope": "external_exact_edition",
            "source": "openlibrary",
            "match_method": "isbn_exact_human_reviewed",
        }
        for field, expected in required_states.items():
            if reference.get(field) != expected:
                raise CoverIndexError(f"{record_id} reviewed cover has invalid {field}")
        source_id = str(reference.get("source_id") or "")
        if not OL_EDITION_RE.fullmatch(source_id):
            raise CoverIndexError(f"{record_id} reviewed cover has an invalid Open Library edition ID")
        if reference.get("source_url") != f"https://openlibrary.org/books/{source_id}":
            raise CoverIndexError(f"{record_id} reviewed cover source URL does not match its edition ID")

        cover_id = positive_integer(reference.get("cover_id"), f"{record_id} cover_id")
        image_matches = {
            size: OPEN_LIBRARY_COVER_RE.fullmatch(str(reference.get(field) or ""))
            for size, field in (("L", "image_url"), ("M", "thumbnail_url"))
        }
        if any(match is None for match in image_matches.values()):
            raise CoverIndexError(f"{record_id} reviewed cover uses an invalid provider image URL")
        if any(
            match.group("size") != size or int(match.group("cover_id")) != cover_id
            for size, match in image_matches.items()
            if match is not None
        ):
            raise CoverIndexError(f"{record_id} reviewed cover URLs do not match cover_id {cover_id}")

        image = reference.get("image") if isinstance(reference.get("image"), Mapping) else {}
        width = positive_integer(image.get("width"), f"{record_id} reviewed cover width")
        height = positive_integer(image.get("height"), f"{record_id} reviewed cover height")
        identifiers = reviewed_matched_identifiers(record, reference)

        review = reference.get("review") if isinstance(reference.get("review"), Mapping) else {}
        reviewer = str(review.get("reviewer") or "").strip()
        reviewed_at = str(review.get("reviewed_at") or "")
        evidence_note = str(review.get("evidence_note") or "").strip()
        fingerprint = str(review.get("candidate_fingerprint") or "")
        if not reviewer or not ISO_UTC_RE.fullmatch(reviewed_at) or len(evidence_note) < 12:
            raise CoverIndexError(f"{record_id} reviewed cover lacks a complete human review")
        if not SHA256_RE.fullmatch(fingerprint):
            raise CoverIndexError(f"{record_id} reviewed cover has an invalid candidate fingerprint")

        gate_receipt = reference.get("gate_receipt") if isinstance(reference.get("gate_receipt"), Mapping) else {}
        gate_probe = gate_receipt.get("probe") if isinstance(gate_receipt.get("probe"), Mapping) else {}
        if (
            gate_receipt.get("exact_edition_confirmed") is not True
            or gate_receipt.get("visual_check") is not True
            or gate_receipt.get("rights_scope") != "remote_reference_only"
        ):
            raise CoverIndexError(f"{record_id} reviewed cover lacks the human confirmation gate receipt")
        if (
            gate_probe.get("status") != "positive"
            or gate_probe.get("bounded_probe") is not True
            or gate_probe.get("candidate_fingerprint") != fingerprint
        ):
            raise CoverIndexError(f"{record_id} reviewed cover lacks a current positive probe receipt")
        gate_probe_checked_at = str(gate_probe.get("checked_at") or "")
        if not ISO_UTC_RE.fullmatch(gate_probe_checked_at):
            raise CoverIndexError(f"{record_id} reviewed cover probe receipt lacks a valid timestamp")
        receipt_width = positive_integer(gate_probe.get("width"), f"{record_id} probe receipt width")
        receipt_height = positive_integer(gate_probe.get("height"), f"{record_id} probe receipt height")
        if receipt_width != width or receipt_height != height:
            raise CoverIndexError(f"{record_id} reviewed cover probe receipt dimensions conflict with its image evidence")

        rights = reference.get("rights") if isinstance(reference.get("rights"), Mapping) else {}
        if (
            rights.get("status") != "underlying_cover_rights_not_established"
            or rights.get("display_scope") != "provider_hosted_reference_only"
            or rights.get("binary_cache_allowed") is not False
            or rights.get("license_url") != OPEN_LIBRARY_LICENSE_URL
        ):
            raise CoverIndexError(f"{record_id} reviewed cover has an unsafe rights/cache scope")
        provenance = reference.get("provenance") if isinstance(reference.get("provenance"), Mapping) else {}
        checked_at = str(provenance.get("probe_checked_at") or "")
        if not ISO_UTC_RE.fullmatch(checked_at):
            raise CoverIndexError(f"{record_id} reviewed cover lacks a valid probe timestamp")
        if checked_at != gate_probe_checked_at:
            raise CoverIndexError(f"{record_id} reviewed cover probe receipt conflicts with provenance")
        dump_checksum = str(provenance.get("provider_dump_checksum") or "")
        if not DUMP_CHECKSUM_RE.fullmatch(dump_checksum):
            raise CoverIndexError(f"{record_id} reviewed cover lacks a valid provider dump checksum")
        expected_fingerprint = canonical_json_checksum({
            "catalog_id": record_id,
            "catalog_isbns": sorted({key for value in record.get("isbns") or [] if (key := canonical_isbn13(value))}),
            "matched_isbns": sorted({canonical_isbn13(identifier["value"]) for identifier in identifiers}),
            "provider": "openlibrary",
            "provider_edition_id": source_id,
            "cover_id": cover_id,
            "provider_dump_checksum": dump_checksum,
        })
        if fingerprint != expected_fingerprint:
            raise CoverIndexError(f"{record_id} reviewed cover fingerprint does not match its exact candidate evidence")

        reference["_validated_width"] = width
        reference["_validated_height"] = height
        reference["_validated_matched_identifiers"] = identifiers
        reference["_validated_gate_receipt"] = dict(gate_receipt)
        validated[record_id] = reference
    return validated


def resolved_index_item(visual: Mapping[str, Any], width: int, height: int) -> dict[str, Any]:
    return {
        "status": "provider_reference",
        "provider": "openlibrary",
        "scope": "exact_edition",
        "image": {
            "thumbnail_url": visual["thumbnail_url"],
            "image_url": visual["image_url"],
            "width": width,
            "height": height,
        },
        "rights": {
            "public_display": True,
            "basis": "provider_display_terms",
        },
        "cache_policy": "remote_only",
        "provenance_ref": "cover_provenance.json",
        "label": PROVIDER_REFERENCE_LABEL,
    }


def reviewed_index_item(reference: Mapping[str, Any]) -> dict[str, Any]:
    review = reference["review"]
    return {
        "status": "verified",
        "provider": "openlibrary",
        "scope": "exact_edition",
        "image": {
            "thumbnail_url": reference["thumbnail_url"],
            "image_url": reference["image_url"],
            "width": reference["_validated_width"],
            "height": reference["_validated_height"],
        },
        "rights": {
            "public_display": True,
            "basis": "provider_display_terms",
            "credit_line": "Cover reference served by Open Library",
            "derivatives_allowed": False,
            "license_url": OPEN_LIBRARY_LICENSE_URL,
        },
        "cache_policy": "remote_only",
        "provenance_ref": "cover_provenance.json",
        "review": {
            "status": "approved",
            "reviewer": str(review["reviewer"]).strip(),
            "reviewed_at": review["reviewed_at"],
            "evidence_note": str(review["evidence_note"]).strip(),
        },
        "label": REVIEWED_COVER_LABEL,
    }


def cleared_index_item(reference: Mapping[str, Any]) -> dict[str, Any]:
    """Compact first-paint entry for a rights-cleared local derivative."""

    review = reference["review"]
    rights = reference["rights"]
    display = reference["_display_derivative"]
    thumbnail = reference["_thumbnail_derivative"]
    scope = str(reference["scope"])
    return {
        "status": "verified",
        "provider": reference["provider"],
        "scope": scope,
        "image": {
            "thumbnail_url": thumbnail["url"],
            "image_url": display["url"],
            "width": display["width"],
            "height": display["height"],
        },
        "rights": {
            "public_display": True,
            "basis": rights["basis"],
            "credit_line": rights["credit_line"],
            "derivatives_allowed": True,
            "license_url": rights["evidence_url"],
        },
        "cache_policy": "local_derivatives",
        "provenance_ref": "cover_provenance.json",
        "review": {
            "status": "approved",
            "reviewer": review["reviewer"],
            "reviewed_at": review["reviewed_at"],
            "evidence_note": review["evidence_note"],
        },
        "label": CLARK_COPY_COVER_LABEL if scope == "clark_copy" else LICENSED_COVER_LABEL,
    }


def unresolved_index_item() -> dict[str, Any]:
    return {
        "status": "unresolved",
        "provider": None,
        "scope": "none",
        "image": None,
        "rights": {
            "public_display": False,
            "basis": "unknown",
        },
        "cache_policy": "none",
        "provenance_ref": None,
    }


def provenance_item(record: Mapping[str, Any], visual: Mapping[str, Any], width: int, height: int) -> dict[str, Any]:
    identifiers = matched_identifiers(record, visual)
    analysis = visual.get("image_analysis") if isinstance(visual.get("image_analysis"), Mapping) else {}
    checksum = analysis.get("source_pixels", {}).get("source_sha256")
    if not checksum:
        checksum = analysis.get("provenance", {}).get("source_sha256")
    if not checksum:
        checksum = analysis.get("source_sha256")
    # The committed analyzer stores the raster checksum at image_analysis.source_pixels.source_sha256
    # in newer snapshots and at image_analysis.source_sha256 in older ones.  A remote-only image may
    # retain a null checksum without implying that ShelfSignals cached the binary.
    if not checksum:
        checksum = analysis.get("stored_raster_sha256")
    return {
        "catalog_id": record["id"],
        "status": "provider_reference",
        "provider": "openlibrary",
        "scope": "exact_edition",
        "matched_identifiers": identifiers,
        "selection_rationale": "An exact ISBN on the Clark catalog record matched this legacy Open Library provider reference. The cover image still awaits named visual review.",
        "source": {
            "provider": "Open Library",
            "source_id": str(visual.get("source_id") or ""),
            "source_url": str(visual.get("source_url") or ""),
            "image_url": str(visual.get("image_url") or ""),
            "thumbnail_url": str(visual.get("thumbnail_url") or ""),
        },
        "image": {
            "thumbnail_url": str(visual.get("thumbnail_url") or ""),
            "image_url": str(visual.get("image_url") or ""),
            "width": width,
            "height": height,
            "checksum": checksum,
        },
        "rights": {
            "status": "provider_display_terms",
            "basis": "provider_display_terms",
            "public_display": True,
            "derivatives_allowed": False,
            "credit_line": str(visual.get("attribution") or "Cover reference served by Open Library"),
            "license_url": OPEN_LIBRARY_LICENSE_URL,
            "note": "Provider availability does not establish that the underlying cover artwork is openly licensed.",
        },
        "retrieved_at": str(visual.get("checked_at") or ""),
        "cache_policy": "remote_only",
        "review": {
            "status": "not_reviewed",
            "reviewer": None,
            "reviewed_at": None,
            "evidence_note": "Legacy exact-identifier reference; no structured human visual review is recorded.",
        },
        "image_analysis": analysis or None,
    }


def reviewed_provenance_item(record: Mapping[str, Any], reference: Mapping[str, Any]) -> dict[str, Any]:
    review = reference["review"]
    provenance = reference["provenance"]
    identifiers = reference["_validated_matched_identifiers"]
    return {
        "catalog_id": record["id"],
        "status": "verified",
        "provider": "openlibrary",
        "scope": "exact_edition",
        "matched_identifiers": identifiers,
        "selection_rationale": (
            "A named reviewer confirmed this provider cover as the front cover of the exact edition "
            "identified on the Clark catalog record."
        ),
        "source": {
            "provider": "Open Library",
            "source_id": reference["source_id"],
            "source_url": reference["source_url"],
            "cover_id": reference["cover_id"],
            "image_url": reference["image_url"],
            "thumbnail_url": reference["thumbnail_url"],
        },
        "image": {
            "thumbnail_url": reference["thumbnail_url"],
            "image_url": reference["image_url"],
            "width": reference["_validated_width"],
            "height": reference["_validated_height"],
            "checksum": None,
        },
        "rights": {
            "status": "provider_display_terms",
            "basis": "provider_display_terms",
            "public_display": True,
            "derivatives_allowed": False,
            "credit_line": "Cover reference served by Open Library",
            "license_url": OPEN_LIBRARY_LICENSE_URL,
            "note": "Provider availability does not establish that the underlying cover artwork is openly licensed.",
        },
        "retrieved_at": provenance["probe_checked_at"],
        "cache_policy": "remote_only",
        "review": {
            "status": "approved",
            "reviewer": str(review["reviewer"]).strip(),
            "reviewed_at": review["reviewed_at"],
            "evidence_note": str(review["evidence_note"]).strip(),
            "candidate_fingerprint": review["candidate_fingerprint"],
        },
        "gate_receipt": reference["_validated_gate_receipt"],
        "provider_snapshot": provenance.get("provider_snapshot"),
        "provider_dump_checksum": provenance.get("provider_dump_checksum"),
        "copy_scope": provenance.get("copy_scope"),
        "image_analysis": None,
    }


def cleared_provenance_item(record: Mapping[str, Any], reference: Mapping[str, Any]) -> dict[str, Any]:
    """Full auditable provenance for an approved local derivative set."""

    review = reference["review"]
    rights = reference["rights"]
    source = reference["source"]
    image = reference["image"]
    display = reference["_display_derivative"]
    thumbnail = reference["_thumbnail_derivative"]
    provenance = reference["provenance"]
    scope = str(reference["scope"])
    return {
        "catalog_id": record["id"],
        "status": "verified",
        "provider": reference["provider"],
        "scope": scope,
        "matched_identifiers": reference["matched_identifiers"],
        "selection_rationale": (
            "A named reviewer confirmed this photograph as the front cover of the Clark cataloged copy."
            if scope == "clark_copy"
            else "A named reviewer confirmed this rights-cleared photograph as the front cover of an exact edition identified on the Clark record."
        ),
        "source": {
            # Keep the machine provider token compatible with the browser
            # contract; the rights/source fields below carry the human-facing
            # institution, creator, and credit evidence.
            "provider": reference["provider"],
            "source_id": source["source_id"],
            "source_url": source["source_reference_url"],
            "creator": source["creator"],
            "source_date": source["source_date"],
        },
        "image": {
            "thumbnail_url": thumbnail["url"],
            "image_url": display["url"],
            "width": display["width"],
            "height": display["height"],
            "checksum": display["sha256"],
            "source": image["source"],
            "derivatives": image["derivatives"],
        },
        "rights": {
            "status": "cleared",
            "basis": rights["basis"],
            "public_display": True,
            "derivatives_allowed": True,
            "credit_line": rights["credit_line"],
            "license_url": rights["evidence_url"],
            "license_or_permission_reference": rights["license_or_permission_reference"],
            "rights_holder": rights["rights_holder"],
            "note": rights["evidence_note"],
        },
        "retrieved_at": provenance["ingested_at"],
        "cache_policy": "local_derivatives",
        "review": {
            "status": "approved",
            "reviewer": review["reviewer"],
            "reviewed_at": review["reviewed_at"],
            "evidence_note": review["evidence_note"],
            "candidate_fingerprint": review["candidate_fingerprint"],
        },
        "gate_receipt": reference["gate_receipt"],
        "catalog_identity": reference["catalog_identity"],
        "provenance": provenance,
        "image_analysis": None,
    }


def build_manifests(
    catalog: Iterable[Mapping[str, Any]],
    visuals: Mapping[str, Any],
    *,
    generated_at: str,
    dataset_sha256: str,
    reviewed_references: Mapping[str, Any] | None = None,
    reviewed_source_name: str | None = None,
    reviewed_source_sha256: str | None = None,
    cleared_references: Mapping[str, Any] | None = None,
    cleared_source_name: str | None = None,
    cleared_source_sha256: str | None = None,
    docs_root: Path | None = None,
) -> tuple[dict[str, Any], dict[str, Any]]:
    records = list(catalog)
    record_by_id = {str(record.get("id") or ""): record for record in records}
    if "" in record_by_id or len(record_by_id) != len(records):
        raise CoverIndexError("catalog IDs must be present and unique")
    raw_visual_items = visuals.get("items") if isinstance(visuals.get("items"), Mapping) else {}
    reviewed_items = (
        validate_reviewed_references(reviewed_references, record_by_id)
        if reviewed_references is not None
        else {}
    )
    if reviewed_references is not None:
        reviewed_source_name = reviewed_source_name or REVIEWED_REFERENCES_SCHEMA
        reviewed_source_sha256 = reviewed_source_sha256 or canonical_json_checksum(reviewed_references)
    if cleared_references is not None and docs_root is None:
        raise CoverIndexError("cleared cover references require docs_root so every local derivative can be reopened")
    try:
        cleared_items = (
            validate_cleared_references(
                cleared_references,
                catalog=records,
                catalog_sha256=dataset_sha256,
                docs_root=docs_root,
            )
            if cleared_references is not None
            else {}
        )
    except ClearedCoverError as exc:
        raise CoverIndexError(f"cleared cover references refused: {exc}") from exc
    if cleared_references is not None:
        cleared_source_name = cleared_source_name or CLEARED_REFERENCES_SCHEMA
        cleared_source_sha256 = cleared_source_sha256 or canonical_json_checksum(cleared_references)

    # The catalog already carries every record ID. Store only exceptions to the
    # unresolved default so first paint does not download thousands of repeated
    # placeholder objects.
    index_items: Dict[str, Any] = {}
    provenance_items: Dict[str, Any] = {}
    for record in records:
        record_id = str(record["id"])
        visual = raw_visual_items.get(record_id)
        if not isinstance(visual, Mapping) or visual.get("status") != "resolved":
            continue
        if str(visual.get("source") or "").lower() != "openlibrary":
            raise CoverIndexError(f"{record_id} uses an unsupported cover provider")
        width, height = image_dimensions(visual)
        # Validate the exact identifier before allowing the image into the first-paint index.
        matched_identifiers(record, visual)
        index_items[record_id] = resolved_index_item(visual, width, height)
        provenance_items[record_id] = provenance_item(record, visual, width, height)

    # Reviewed exact-edition references have strictly stronger evidence and
    # intentionally replace a legacy provider reference for the same record.
    for record_id, reference in reviewed_items.items():
        record = record_by_id[record_id]
        index_items[record_id] = reviewed_index_item(reference)
        provenance_items[record_id] = reviewed_provenance_item(record, reference)

    # Rights-cleared Clark-copy photography is the preferred source. A cleared
    # exact-edition photograph also outranks a provider-hosted reference. The
    # strict local contract above verifies both derivative bytes before either
    # can replace an existing record state.
    for record_id, reference in cleared_items.items():
        record = record_by_id[record_id]
        index_items[record_id] = cleared_index_item(reference)
        provenance_items[record_id] = cleared_provenance_item(record, reference)

    verified_count = sum(1 for item in index_items.values() if item.get("status") == "verified")
    provider_reference_count = len(provenance_items) - verified_count

    source = {
        "catalog": "Clark Library Catalog",
        "dataset": "sekula_index.json",
        "dataset_sha256": dataset_sha256,
        "record_count": len(records),
        "legacy_visual_source": "book_visuals.json",
        "reviewed_reference_source": reviewed_source_name if reviewed_references is not None else None,
        "reviewed_reference_sha256": reviewed_source_sha256 if reviewed_references is not None else None,
        "cleared_reference_source": cleared_source_name if cleared_references is not None else None,
        "cleared_reference_sha256": cleared_source_sha256 if cleared_references is not None else None,
        "policy": "Rights-cleared Clark-copy photography is preferred, followed by cleared or human-reviewed exact-edition references. Legacy provider references remain visibly marked as awaiting visual review; unresolved records retain an explicit surrogate state.",
    }
    index = {
        "schema": INDEX_SCHEMA,
        "version": "1.0.0",
        "generated_at": generated_at,
        "source": source,
        "unresolved_label": UNRESOLVED_LABEL,
        "unresolved_default": unresolved_index_item(),
        "summary": {
            "records": len(records),
            "verified": verified_count,
            "provider_references": provider_reference_count,
            "needs_review": 0,
            "unresolved": len(records) - len(provenance_items),
        },
        "items": index_items,
    }
    provenance = {
        "schema": PROVENANCE_SCHEMA,
        "version": "1.0.0",
        "generated_at": generated_at,
        "source": source,
        "items": provenance_items,
    }
    return index, provenance


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(encode_json(payload))


def encode_json(payload: Mapping[str, Any]) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, separators=(",", ":")) + "\n").encode("utf-8")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--visuals", type=Path, default=DEFAULT_VISUALS)
    parser.add_argument(
        "--reviewed-references",
        type=Path,
        help="optional reviewed-only output from scripts/cover_source_pipeline.py publish",
    )
    parser.add_argument(
        "--cleared-references",
        type=Path,
        help="optional derivative-only output from scripts/ingest_cleared_covers.py ingest",
    )
    parser.add_argument(
        "--docs-root",
        type=Path,
        default=ROOT / "docs",
        help="public docs root used to reopen and checksum local cleared-cover derivatives",
    )
    parser.add_argument("--index-output", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--provenance-output", type=Path, default=DEFAULT_PROVENANCE)
    parser.add_argument("--generated-at", default="")
    parser.add_argument(
        "--check",
        action="store_true",
        help="rebuild in memory with the committed generation time and fail if either output is stale",
    )
    parser.add_argument("--self-test", action="store_true")
    return parser.parse_args()


def run_self_test() -> None:
    record = {"id": "alma1", "isbns": ["978-0-374-22626-8"]}
    visual = {
        "status": "resolved",
        "source": "openlibrary",
        "source_id": "0374226261",
        "source_url": "https://openlibrary.org/isbn/0374226261",
        "image_url": "https://covers.openlibrary.org/b/isbn/0374226261-L.jpg?default=false",
        "thumbnail_url": "https://covers.openlibrary.org/b/isbn/0374226261-M.jpg?default=false",
        "match_method": "isbn",
        "checked_at": "2026-07-13T00:00:00Z",
        "image_analysis": {"source_pixels": {"width": 375, "height": 500}},
    }
    index, provenance = build_manifests([record], {"items": {"alma1": visual}}, generated_at="2026-07-13T00:00:00Z", dataset_sha256="sha256:" + "a" * 64)
    assert index["summary"] == {"records": 1, "verified": 0, "provider_references": 1, "needs_review": 0, "unresolved": 0}
    assert provenance["items"]["alma1"]["matched_identifiers"] == [{"type": "isbn", "value": "0374226261"}]
    assert index["items"]["alma1"]["cache_policy"] == "remote_only"
    assert index["items"]["alma1"]["status"] == "provider_reference"
    assert provenance["items"]["alma1"]["review"]["status"] == "not_reviewed"
    assert index["unresolved_default"]["status"] == "unresolved"

    reviewed_item = {
        "status": "resolved",
        "lookup_status": "positive",
        "scope": "external_exact_edition",
        "image_url": "https://covers.openlibrary.org/b/id/12345-L.jpg?default=false",
        "thumbnail_url": "https://covers.openlibrary.org/b/id/12345-M.jpg?default=false",
        "source": "openlibrary",
        "source_id": "OL123M",
        "source_url": "https://openlibrary.org/books/OL123M",
        "cover_id": 12345,
        "match_method": "isbn_exact_human_reviewed",
        "match_confidence": 1.0,
        "matched_identifiers": [{"type": "isbn", "value": "9780374226268"}],
        "image": {"width": 375, "height": 500, "aspect_ratio": 0.75},
        "review": {
            "reviewer": "Test reviewer",
            "reviewed_at": "2026-07-13T00:00:00Z",
            "evidence_note": "The ISBN, edition statement, and front-cover role were checked.",
            "candidate_fingerprint": "",
        },
        "gate_receipt": {
            "exact_edition_confirmed": True,
            "visual_check": True,
            "rights_scope": "remote_reference_only",
            "probe": {
                "status": "positive",
                "bounded_probe": True,
                "candidate_fingerprint": "",
                "checked_at": "2026-07-13T00:00:00Z",
                "width": 375,
                "height": 500,
            },
        },
        "rights": {
            "status": "underlying_cover_rights_not_established",
            "display_scope": "provider_hosted_reference_only",
            "binary_cache_allowed": False,
            "license_url": OPEN_LIBRARY_LICENSE_URL,
        },
        "provenance": {
            "catalog_url": "https://library.clarkart.edu/example",
            "provider_edition_url": "https://openlibrary.org/books/OL123M",
            "provider_snapshot": "2026-06-30",
            "provider_dump_checksum": "md5:" + "d" * 32,
            "probe_checked_at": "2026-07-13T00:00:00Z",
            "copy_scope": "External edition cover; not the Clark copy.",
        },
    }
    reviewed_item["review"]["candidate_fingerprint"] = canonical_json_checksum({
        "catalog_id": "alma1",
        "catalog_isbns": ["9780374226268"],
        "matched_isbns": ["9780374226268"],
        "provider": "openlibrary",
        "provider_edition_id": "OL123M",
        "cover_id": 12345,
        "provider_dump_checksum": "md5:" + "d" * 32,
    })
    reviewed_item["gate_receipt"]["probe"]["candidate_fingerprint"] = reviewed_item["review"]["candidate_fingerprint"]
    reviewed = {
        "schema": REVIEWED_REFERENCES_SCHEMA,
        "policy": {"unreviewed_candidates_included": False, "binary_images_included": False},
        "summary": {"published": 1},
        "items": {"alma1": reviewed_item},
    }
    verified_index, verified_provenance = build_manifests(
        [record],
        {"items": {"alma1": visual}},
        generated_at="2026-07-13T00:00:00Z",
        dataset_sha256="sha256:" + "a" * 64,
        reviewed_references=reviewed,
        reviewed_source_name="reviewed_cover_references.json",
        reviewed_source_sha256="sha256:" + "c" * 64,
    )
    assert verified_index["summary"] == {"records": 1, "verified": 1, "provider_references": 0, "needs_review": 0, "unresolved": 0}
    assert verified_index["items"]["alma1"]["status"] == "verified"
    assert verified_index["items"]["alma1"]["review"]["status"] == "approved"
    assert verified_provenance["items"]["alma1"]["source"]["source_id"] == "OL123M"
    assert verified_provenance["items"]["alma1"]["matched_identifiers"] == [{"type": "isbn", "value": "9780374226268"}]
    assert verified_provenance["items"]["alma1"]["review"]["candidate_fingerprint"] == reviewed_item["review"]["candidate_fingerprint"]
    assert verified_provenance["items"]["alma1"]["gate_receipt"]["probe"]["status"] == "positive"
    assert verified_index["source"]["reviewed_reference_sha256"] == "sha256:" + "c" * 64

    mismatched = json.loads(json.dumps(reviewed))
    mismatched["items"]["alma1"]["matched_identifiers"][0]["value"] = "9780520270947"
    try:
        build_manifests([record], {"items": {}}, generated_at="2026-07-13T00:00:00Z", dataset_sha256="sha256:" + "a" * 64, reviewed_references=mismatched)
        raise AssertionError("mismatched reviewed ISBN should fail")
    except CoverIndexError as exc:
        assert "does not match" in str(exc)

    unknown = json.loads(json.dumps(reviewed))
    unknown["items"]["outside"] = unknown["items"].pop("alma1")
    try:
        build_manifests([record], {"items": {}}, generated_at="2026-07-13T00:00:00Z", dataset_sha256="sha256:" + "a" * 64, reviewed_references=unknown)
        raise AssertionError("unknown reviewed ID should fail")
    except CoverIndexError as exc:
        assert "unknown catalog ID" in str(exc)

    stale = json.loads(json.dumps(reviewed))
    stale["items"]["alma1"]["review"]["candidate_fingerprint"] = "sha256:stale"
    try:
        build_manifests([record], {"items": {}}, generated_at="2026-07-13T00:00:00Z", dataset_sha256="sha256:" + "a" * 64, reviewed_references=stale)
        raise AssertionError("stale reviewed fingerprint should fail")
    except CoverIndexError as exc:
        assert "fingerprint" in str(exc)

    missing_receipt = json.loads(json.dumps(reviewed))
    del missing_receipt["items"]["alma1"]["gate_receipt"]
    try:
        build_manifests([record], {"items": {}}, generated_at="2026-07-13T00:00:00Z", dataset_sha256="sha256:" + "a" * 64, reviewed_references=missing_receipt)
        raise AssertionError("missing gate receipt should fail")
    except CoverIndexError as exc:
        assert "gate receipt" in str(exc)

    stale_probe_receipt = json.loads(json.dumps(reviewed))
    stale_probe_receipt["items"]["alma1"]["gate_receipt"]["probe"]["candidate_fingerprint"] = "sha256:" + "b" * 64
    try:
        build_manifests([record], {"items": {}}, generated_at="2026-07-13T00:00:00Z", dataset_sha256="sha256:" + "a" * 64, reviewed_references=stale_probe_receipt)
        raise AssertionError("stale probe receipt should fail")
    except CoverIndexError as exc:
        assert "positive probe receipt" in str(exc)

    conflicting_probe_dimensions = json.loads(json.dumps(reviewed))
    conflicting_probe_dimensions["items"]["alma1"]["gate_receipt"]["probe"]["width"] = 376
    try:
        build_manifests([record], {"items": {}}, generated_at="2026-07-13T00:00:00Z", dataset_sha256="sha256:" + "a" * 64, reviewed_references=conflicting_probe_dimensions)
        raise AssertionError("conflicting probe dimensions should fail")
    except CoverIndexError as exc:
        assert "dimensions conflict" in str(exc)

    conflicting_probe_time = json.loads(json.dumps(reviewed))
    conflicting_probe_time["items"]["alma1"]["gate_receipt"]["probe"]["checked_at"] = "2026-07-13T00:01:00Z"
    try:
        build_manifests([record], {"items": {}}, generated_at="2026-07-13T00:00:00Z", dataset_sha256="sha256:" + "a" * 64, reviewed_references=conflicting_probe_time)
        raise AssertionError("conflicting probe timestamp should fail")
    except CoverIndexError as exc:
        assert "conflicts with provenance" in str(exc)


def main() -> int:
    args = parse_args()
    if args.self_test and args.check:
        raise CoverIndexError("--self-test and --check cannot be combined")
    if args.self_test:
        run_self_test()
        print("cover-index self-test passed")
        return 0
    catalog, catalog_bytes = load_json(args.catalog)
    visuals, _ = load_json(args.visuals)
    if not isinstance(catalog, list) or not isinstance(visuals, Mapping):
        raise CoverIndexError("catalog must be an array and visual input must be an object")
    reviewed_references = None
    reviewed_source_name = None
    reviewed_source_sha256 = None
    if args.reviewed_references is not None:
        reviewed_references, reviewed_bytes = load_json(args.reviewed_references)
        if not isinstance(reviewed_references, Mapping):
            raise CoverIndexError("reviewed reference input must be an object")
        reviewed_source_name = args.reviewed_references.name
        reviewed_source_sha256 = sha256_bytes(reviewed_bytes)
    cleared_references = None
    cleared_source_name = None
    cleared_source_sha256 = None
    if args.cleared_references is not None:
        cleared_references, cleared_bytes = load_json(args.cleared_references)
        if not isinstance(cleared_references, Mapping):
            raise CoverIndexError("cleared reference input must be an object")
        cleared_source_name = args.cleared_references.name
        cleared_source_sha256 = sha256_bytes(cleared_bytes)
    generated_at = args.generated_at
    if args.check and not generated_at:
        committed_index, _ = load_json(args.index_output)
        if not isinstance(committed_index, Mapping):
            raise CoverIndexError("committed cover index must be an object")
        generated_at = str(committed_index.get("generated_at") or "")
        if not ISO_UTC_RE.fullmatch(generated_at):
            raise CoverIndexError("committed cover index has no valid generation time")
    if not generated_at:
        generated_at = datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    index, provenance = build_manifests(
        catalog,
        visuals,
        generated_at=generated_at,
        dataset_sha256=sha256_bytes(catalog_bytes),
        reviewed_references=reviewed_references,
        reviewed_source_name=reviewed_source_name,
        reviewed_source_sha256=reviewed_source_sha256,
        cleared_references=cleared_references,
        cleared_source_name=cleared_source_name,
        cleared_source_sha256=cleared_source_sha256,
        docs_root=args.docs_root if cleared_references is not None else None,
    )
    if args.check:
        expected = {
            args.index_output: encode_json(index),
            args.provenance_output: encode_json(provenance),
        }
        stale = []
        for path, rebuilt_bytes in expected.items():
            try:
                committed_bytes = path.read_bytes()
            except OSError as exc:
                raise CoverIndexError(f"cannot read committed output {path}: {exc}") from exc
            if committed_bytes != rebuilt_bytes:
                stale.append(str(path))
        if stale:
            raise CoverIndexError(f"stale generated cover output: {', '.join(stale)}")
        print(f"verified cover outputs ({index['summary']['verified']} verified, {index['summary']['provider_references']} provider references, {index['summary']['unresolved']} unresolved)")
        return 0
    write_json(args.index_output, index)
    write_json(args.provenance_output, provenance)
    print(f"wrote {args.index_output} ({index['summary']['verified']} verified, {index['summary']['provider_references']} provider references, {index['summary']['unresolved']} unresolved)")
    print(f"wrote {args.provenance_output} ({len(provenance['items'])} detailed records)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
