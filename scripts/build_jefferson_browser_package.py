#!/usr/bin/env python3
"""Build the deterministic Phase 1 Jefferson browser package.

The ignored research package remains the evidence-bearing input.  This script
projects only an explicit public allowlist into ``docs/`` and never performs a
network request.  The resulting package represents current LOC catalog
instances carrying the exact Jefferson collection heading; it is not a
reconstruction of Jefferson's historical physical shelves.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import html
import json
import os
import re
import shutil
import sys
import tempfile
import unicodedata
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlparse


SCRIPT_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = SCRIPT_DIR.parent
DEFAULT_SOURCE_DIR = REPOSITORY_ROOT / "research/jefferson/work/data"
DEFAULT_OUTPUT_DIR = REPOSITORY_ROOT / "docs/data/collections/jefferson"

SHARD_COUNT = 64
COLLECTION_HEADING = "Thomas Jefferson Library Collection (Library of Congress)"
REVIEW_CODE_SHA256 = "sha256:867435d40522abb154a5a19761e38396af2c929ca712c80a57ccd7663fcd0d7e"
SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
UUID_RE = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$")
YEAR_RE = re.compile(r"(?<!\d)(1[0-9]{3}|20[0-9]{2})(?!\d)")
LC_CLASS_RE = re.compile(r"^([A-Za-z]{1,3})(?=\d)")

CORE_SCHEMA = "shelfsignals-browser-catalog@2"
SEARCH_SCHEMA = "shelfsignals-catalog-search@2"
DETAIL_SCHEMA = "shelfsignals-catalog-detail-shard@2"
DETAIL_INDEX_SCHEMA = "shelfsignals-catalog-detail-index@2"

CORE_FIELDS = [
    "id",
    "entity_type",
    "title",
    "authors",
    "year",
    "call_number",
    "material_type",
    "formats",
    "record_url",
    "facets",
    "orders",
    "evidence_status",
    "detail_shard",
]
SEARCH_FIELDS = ["id", "search_text"]
DETAIL_FIELDS = [
    "id",
    "entity_type",
    "full_title",
    "alternative_titles",
    "contributors",
    "publication",
    "languages",
    "subjects",
    "classifications",
    "modern_call_numbers",
    "holdings",
    "items",
    "identifiers",
    "lccns",
    "record_url",
    "relationship_to_jefferson",
    "ownership_or_reconstruction_status",
    "sowerby_numbers",
    "sowerby_evidence",
    "field_evidence",
    "source",
]
MEDIA_FIELDS = [
    "record_id",
    "digital_item_id",
    "url",
    "thumbnail_url",
    "rights_access",
    "review_status",
    "match_basis",
    "normalized_lccns",
    "sowerby_numbers",
]

REQUIRED_INPUTS = {
    "catalog_instances": "loc_catalog_instances.jsonl",
    "loc_sowerby_reference": "loc_sowerby_reference.json",
    "crosswalk": "sowerby_loc_crosswalk.jsonl",
    "digital_items": "loc_digital_items.jsonl",
    "manifest": "manifest.json",
    "validation": "validation.json",
}

EXPECTED_OUTPUT_HASH_KEYS = {
    "catalog_instances": "catalog_instances",
    "loc_sowerby_reference": "loc_sowerby_reference",
    "crosswalk": "crosswalk",
    "digital_items": "digital_items",
    "validation": "validation",
}

FORBIDDEN_PUBLIC_KEYS = {
    "barcode",
    "staffOnly",
    "staff_only",
    "administrativeNotes",
    "administrative_notes",
    "circulationNotes",
    "circulation_notes",
    "tags",
    "metadata",
    "effective_location_id",
    "permanent_location_id",
    "shelving_order",
}


class BuildError(RuntimeError):
    """Raised when an input or output contract fails closed."""


class _PlainTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def _clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _plain_text(value: Any) -> str:
    parser = _PlainTextParser()
    parser.feed(str(value or ""))
    parser.close()
    return _clean_text(html.unescape(" ".join(parser.parts)))


def _unique_strings(values: Iterable[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = _clean_text(value)
        if text and text not in seen:
            result.append(text)
            seen.add(text)
    return result


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return f"sha256:{digest.hexdigest()}"


def _load_json(path: Path) -> Any:
    try:
        with path.open("r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as error:
        raise BuildError(f"Unable to read JSON input {path.name}: {error}") from error


def _load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise BuildError(f"{path.name}:{line_number} is not a JSON object")
                rows.append(value)
    except (OSError, json.JSONDecodeError) as error:
        raise BuildError(f"Unable to read JSONL input {path.name}: {error}") from error
    return rows


def _require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BuildError(f"{label} must be an object")
    return value


def _require_list(value: Any, label: str) -> list[Any]:
    if not isinstance(value, list):
        raise BuildError(f"{label} must be an array")
    return value


def _validate_https_url(value: str, hosts: set[str], label: str, *, allow_blank: bool = False) -> str:
    if not value and allow_blank:
        return ""
    parsed = urlparse(value)
    if parsed.scheme != "https" or parsed.hostname not in hosts or parsed.username or parsed.password:
        raise BuildError(f"{label} is not an approved HTTPS URL")
    return value


def _validate_input_hashes(source_dir: Path, manifest: Mapping[str, Any]) -> dict[str, dict[str, Any]]:
    manifest_outputs = _require_object(manifest.get("outputs"), "Research manifest outputs")
    source_package: dict[str, dict[str, Any]] = {}
    for input_key, filename in REQUIRED_INPUTS.items():
        path = source_dir / filename
        if not path.is_file():
            raise BuildError(f"Required input is missing: {filename}")
        actual_hash = _sha256_file(path)
        actual_bytes = path.stat().st_size
        expected_key = EXPECTED_OUTPUT_HASH_KEYS.get(input_key)
        if expected_key:
            expected = _require_object(manifest_outputs.get(expected_key), f"Research manifest output {expected_key}")
            if expected.get("sha256") != actual_hash or expected.get("bytes") != actual_bytes:
                raise BuildError(f"Source hash/size mismatch for {filename}")
        source_package[input_key] = {"file": filename, "bytes": actual_bytes, "sha256": actual_hash}
    return source_package


def stable_shard(value: str, shard_count: int = SHARD_COUNT) -> int:
    """FNV-1a over Unicode code points, matching the browser contract."""

    hash_value = 2166136261
    for character in value:
        hash_value ^= ord(character)
        hash_value = (hash_value * 16777619) & 0xFFFFFFFF
    return hash_value % shard_count


def _browser_id(source_id: str, normalized: Mapping[str, Any]) -> str:
    uuid = _clean_text(normalized.get("instance_uuid"))
    if not UUID_RE.fullmatch(uuid):
        raise BuildError(f"Catalog entity {source_id!r} has an invalid instance UUID")
    if source_id != f"loc:instance:{uuid}":
        raise BuildError(f"Catalog entity ID and normalized UUID disagree: {source_id}")
    return f"jefferson-loc-{uuid}"


def _publication_rows(normalized: Mapping[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    seen: set[tuple[str, str, str]] = set()
    for raw in normalized.get("publication") or []:
        if not isinstance(raw, dict):
            continue
        row = {
            "date": _clean_text(raw.get("dateOfPublication")),
            "place": _clean_text(raw.get("place")),
            "publisher": _clean_text(raw.get("publisher")),
        }
        key = (row["date"], row["place"], row["publisher"])
        if any(key) and key not in seen:
            rows.append(row)
            seen.add(key)
    return rows


def _year(normalized: Mapping[str, Any], publication: Sequence[Mapping[str, str]]) -> str:
    marc = normalized.get("source_marc_metadata")
    if isinstance(marc, dict):
        marc_year = _clean_text(marc.get("year"))
        if marc_year:
            return marc_year
    for row in publication:
        if row["date"]:
            return row["date"]
    return ""


def _display_year(value: str) -> str:
    match = YEAR_RE.search(value)
    return match.group(1) if match else ""


def _display_title(normalized: Mapping[str, Any], full_title: str, limit: int = 180) -> str:
    """Return a compact source-backed title while retaining ``full_title`` in details."""

    candidate = _clean_text(normalized.get("index_title")) or full_title
    if len(candidate) <= limit:
        return candidate
    clipped = candidate[: limit - 1].rstrip()
    word_boundary = clipped.rfind(" ")
    if word_boundary >= int(limit * 0.7):
        clipped = clipped[:word_boundary].rstrip(" ,;:/")
    return f"{clipped}…"


def _decades(publication: Sequence[Mapping[str, str]], year: str) -> list[int]:
    candidates = [year, *(row["date"] for row in publication)]
    decades: list[int] = []
    for candidate in candidates:
        for match in YEAR_RE.finditer(candidate):
            decade = (int(match.group(1)) // 10) * 10
            if decade not in decades:
                decades.append(decade)
    return sorted(decades)


def _contributors(record: Mapping[str, Any]) -> tuple[list[dict[str, Any]], list[str]]:
    instance = _require_object(record.get("instance"), "Catalog instance")
    details: list[dict[str, Any]] = []
    authors: list[str] = []
    seen: set[tuple[str, bool]] = set()
    for raw in instance.get("contributors") or []:
        if not isinstance(raw, dict):
            continue
        name = _clean_text(raw.get("name"))
        primary = raw.get("primary") is True
        if not name:
            continue
        key = (name, primary)
        if key not in seen:
            details.append({"name": name, "primary": primary})
            seen.add(key)
        if primary and name.casefold() != COLLECTION_HEADING.casefold() and name not in authors:
            authors.append(name)
    return details, authors


def _call_number_rows(normalized: Mapping[str, Any]) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    classifications: list[dict[str, str]] = []
    modern_call_numbers: list[dict[str, str]] = []
    for raw in normalized.get("call_numbers") or []:
        if not isinstance(raw, dict):
            continue
        row = {
            "source": _clean_text(raw.get("source")),
            "type_id": _clean_text(raw.get("type_id")),
            "value": _clean_text(raw.get("value")),
        }
        if not row["value"]:
            continue
        target = classifications if row["source"] == "instance_classification" else modern_call_numbers
        if row not in target:
            target.append(row)
    return classifications, modern_call_numbers


def _preferred_call_number(
    classifications: Sequence[Mapping[str, str]], modern_call_numbers: Sequence[Mapping[str, str]]
) -> str:
    # Core carries a compact modern classification for rendering/sorting.  All
    # item-level call numbers remain separately labeled in the detail shard.
    if classifications:
        return max((row["value"] for row in classifications), key=lambda value: (len(value), value))
    if modern_call_numbers:
        return modern_call_numbers[0]["value"]
    return ""


def _lc_facets(classifications: Sequence[Mapping[str, str]]) -> list[str]:
    values: list[str] = []
    for row in classifications:
        match = LC_CLASS_RE.match(row["value"].replace(" ", ""))
        if match:
            value = match.group(1).upper()
            if value not in values:
                values.append(value)
    return sorted(values)


def _natural_sort_key(value: str) -> tuple[Any, ...]:
    normalized = unicodedata.normalize("NFKD", value).casefold()
    return tuple(int(part) if part.isdigit() else part for part in re.split(r"(\d+)", normalized))


def _subjects(normalized: Mapping[str, Any]) -> list[str]:
    return _unique_strings(
        raw.get("value") if isinstance(raw, dict) else raw for raw in (normalized.get("subjects") or [])
    )


def _holdings(normalized: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in normalized.get("holdings") or []:
        if not isinstance(raw, dict):
            continue
        rows.append(
            {
                "id": _clean_text(raw.get("id")),
                "hrid": _clean_text(raw.get("hrid")),
                "permanent_location": _clean_text(raw.get("permanent_location")),
                "discovery_suppress": raw.get("discovery_suppress") is True,
            }
        )
    return rows


def _items(normalized: Mapping[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for raw in normalized.get("items") or []:
        if not isinstance(raw, dict):
            continue
        rows.append(
            {
                "id": _clean_text(raw.get("id")),
                "hrid": _clean_text(raw.get("hrid")),
                "call_number": _clean_text(raw.get("call_number")),
                "effective_location": _clean_text(raw.get("effective_location")),
                "material_type": _clean_text(raw.get("material_type")),
                "status": _clean_text(raw.get("status")),
                "discovery_suppress": raw.get("discovery_suppress") is True,
            }
        )
    return rows


def _identifiers(normalized: Mapping[str, Any]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for raw in normalized.get("identifiers") or []:
        if not isinstance(raw, dict):
            continue
        row = {"type": _clean_text(raw.get("type")), "value": _clean_text(raw.get("value"))}
        if row["value"] and row not in rows:
            rows.append(row)
    return rows


def _search_text(parts: Iterable[Any]) -> str:
    flattened: list[str] = []

    def visit(value: Any) -> None:
        if isinstance(value, dict):
            for nested in value.values():
                visit(nested)
        elif isinstance(value, (list, tuple)):
            for nested in value:
                visit(nested)
        elif value is not None and not isinstance(value, bool):
            text = _clean_text(value)
            if text:
                flattened.append(text)

    for part in parts:
        visit(part)
    return _clean_text(" ".join(flattened)).casefold()


def _field_evidence(link: Mapping[str, Any] | None) -> dict[str, dict[str, str]]:
    if link:
        link_status = "bounded_evidence"
        link_assertion = _clean_text(link.get("catalog_assessment_status"))
        link_source = _clean_text((link.get("evidence") or [""])[0])
    else:
        link_status = "unresolved"
        link_assertion = "not_established_in_bounded_marc_sample"
        link_source = "Only 25 catalog instances were evidence-eligible in the bounded source-MARC sample."
    return {
        "collection_membership": {
            "status": "verified",
            "assertion": "exact_collection_heading_membership",
            "source": "Library of Congress catalog exact contributor-heading query",
        },
        "ownership_or_reconstruction_status": {
            "status": "unresolved",
            "assertion": "not_established",
            "source": "No curator-controlled copy-status source is included in this Phase 1 package.",
        },
        "sowerby_link": {"status": link_status, "assertion": link_assertion, "source": link_source},
    }


def _sowerby_evidence(link: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    if not link:
        return []
    scope = _require_object(link.get("assessment_scope"), "Sowerby assessment scope")
    number = link.get("sowerby_base_integer")
    if not isinstance(number, int) or number <= 0:
        raise BuildError("Established Sowerby evidence lacks a positive base integer")
    return [
        {
            "sowerby_number": number,
            "status": _clean_text(link.get("catalog_assessment_status")),
            "method": _clean_text(scope.get("method")),
            "evidence": _clean_text((link.get("evidence") or [""])[0]),
            "assessment_scope": {
                "selected_catalog_entity_count": scope.get("selected_catalog_entity_count"),
                "evidence_eligible_catalog_entity_count": scope.get("evidence_eligible_catalog_entity_count"),
                "catalog_entities_not_assessed": scope.get("catalog_entities_not_assessed"),
            },
        }
    ]


def _established_crosswalk(rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    by_catalog_id: dict[str, dict[str, Any]] = {}
    for row in rows:
        catalog_ids = _require_list(row.get("catalog_entity_ids"), "Crosswalk catalog_entity_ids")
        status = _clean_text(row.get("catalog_assessment_status"))
        if catalog_ids:
            if status != "one_candidate_in_bounded_marc_sample" or len(catalog_ids) != 1:
                raise BuildError("Only one-candidate bounded MARC links may enter the browser package")
            source_id = _clean_text(catalog_ids[0])
            if source_id in by_catalog_id:
                raise BuildError(f"Catalog entity has multiple established Sowerby links: {source_id}")
            by_catalog_id[source_id] = dict(row)
        elif status != "not_established_in_bounded_marc_sample":
            raise BuildError(f"Unsupported crosswalk status without catalog evidence: {status}")
    return by_catalog_id


def _source_identity(catalog_bytes: bytes, browser_ids: Sequence[str]) -> dict[str, Any]:
    return {
        "collection_id": "jefferson",
        "catalog": "Library of Congress Catalog",
        "dataset": "loc_catalog_instances.jsonl",
        "dataset_sha256": _sha256_bytes(catalog_bytes),
        "record_count": len(browser_ids),
        "id_set_sha256": _sha256_bytes(("\n".join(browser_ids) + "\n").encode("utf-8")),
    }


def _make_record_projection(
    record: Mapping[str, Any],
    source_index: int,
    link: Mapping[str, Any] | None,
) -> dict[str, Any]:
    source_id = _clean_text(record.get("id"))
    normalized = _require_object(record.get("normalized"), f"Normalized catalog record {source_id}")
    if record.get("entity_type") != "catalog_instance" or normalized.get("relationship_to_jefferson") != "exact_collection_heading_membership":
        raise BuildError(f"Catalog entity is not exact-heading catalog-instance evidence: {source_id}")
    if normalized.get("ownership_or_reconstruction_status") != "unresolved":
        raise BuildError(f"Phase 1 refuses inferred ownership/reconstruction status: {source_id}")

    browser_id = _browser_id(source_id, normalized)
    full_title = _clean_text(normalized.get("title"))
    if not full_title:
        raise BuildError(f"Catalog entity has no title: {source_id}")
    title = _display_title(normalized, full_title)
    publication = _publication_rows(normalized)
    contributors, authors = _contributors(record)
    classifications, modern_call_numbers = _call_number_rows(normalized)
    call_number = _preferred_call_number(classifications, modern_call_numbers)
    subjects = _subjects(normalized)
    holdings = _holdings(normalized)
    items = _items(normalized)
    identifiers = _identifiers(normalized)
    lccns = _unique_strings(normalized.get("lccns") or [])
    full_year = _year(normalized, publication)
    year = _display_year(full_year)
    record_url = _clean_text(normalized.get("record_url"))
    _validate_https_url(record_url, {"lccn.loc.gov"}, f"Catalog record URL for {source_id}", allow_blank=True)

    source_position = _require_object(record.get("source"), f"Catalog source {source_id}").get("position")
    if not isinstance(source_position, int) or source_position != source_index + 1:
        raise BuildError(f"Catalog source positions are not consecutive title order at {source_id}")

    sowerby_numbers = [link["sowerby_base_integer"]] if link else []
    normalized_sowerby = normalized.get("sowerby_numbers") or []
    if normalized_sowerby != sowerby_numbers:
        raise BuildError(f"Source/crosswalk Sowerby evidence disagrees for {source_id}")

    material_types = _unique_strings(normalized.get("source_types") or [])
    material_type = material_types[0] if material_types else _clean_text(normalized.get("instance_type"))
    formats = _unique_strings(normalized.get("instance_formats") or [])
    facets = {
        "lc": _lc_facets(classifications),
        "material": material_types or ([material_type] if material_type else []),
        "decade": _decades(publication, year),
    }
    orders = {"title": source_index, "lc": None, "sowerby": sowerby_numbers[0] if sowerby_numbers else None}
    evidence_status = "sowerby_510_exact_bounded" if link else "collection_heading_only"
    shard = stable_shard(browser_id)

    detail = [
        browser_id,
        "catalog_instance",
        full_title,
        _unique_strings(normalized.get("alternative_titles") or []),
        contributors,
        publication,
        _unique_strings(normalized.get("languages") or []),
        subjects,
        classifications,
        modern_call_numbers,
        holdings,
        items,
        identifiers,
        lccns,
        record_url,
        "exact_collection_heading_membership",
        "unresolved",
        sowerby_numbers,
        _sowerby_evidence(link),
        _field_evidence(link),
        {
            "authority": "Library of Congress",
            "catalog_entity_id": source_id,
            "record_sha256": _clean_text(record.get("record_sha256")),
            "source_position": source_position,
        },
    ]
    if not SHA256_RE.fullmatch(detail[-1]["record_sha256"]):
        raise BuildError(f"Catalog entity has an invalid record hash: {source_id}")

    search = _search_text(
        [
            full_title,
            authors,
            contributors,
            publication,
            normalized.get("languages") or [],
            subjects,
            classifications,
            modern_call_numbers,
            identifiers,
            material_types,
            formats,
            sowerby_numbers,
        ]
    )
    if not search:
        raise BuildError(f"Catalog entity has no searchable content: {source_id}")

    return {
        "source_id": source_id,
        "browser_id": browser_id,
        "title": title,
        "full_title": full_title,
        "authors": authors,
        "year": year,
        "call_number": call_number,
        "material_type": material_type,
        "formats": formats,
        "record_url": record_url,
        "facets": facets,
        "orders": orders,
        "evidence_status": evidence_status,
        "detail_shard": shard,
        "detail": detail,
        "search": search,
    }


def _assign_lc_ranks(projected: Sequence[dict[str, Any]]) -> None:
    ranked = sorted(
        (row for row in projected if row["call_number"]),
        key=lambda row: (_natural_sort_key(row["call_number"]), row["orders"]["title"]),
    )
    for rank, row in enumerate(ranked):
        row["orders"]["lc"] = rank


def _core_row(row: Mapping[str, Any]) -> list[Any]:
    return [
        row["browser_id"],
        "catalog_instance",
        row["title"],
        row["authors"],
        row["year"],
        row["call_number"],
        row["material_type"],
        row["formats"],
        row["record_url"],
        row["facets"],
        row["orders"],
        row["evidence_status"],
        row["detail_shard"],
    ]


def _hierarchy_payload(reference: Mapping[str, Any], generated_at: str, source_hash: str) -> dict[str, Any]:
    chapters = _require_list(reference.get("chapters"), "LOC Sowerby chapters")
    if len(chapters) != 44 or [row.get("chapter_number") for row in chapters] != list(range(1, 45)):
        raise BuildError("LOC Sowerby hierarchy must contain consecutive chapters 1 through 44")
    chapter_rows = [
        {
            "chapter_number": row.get("chapter_number"),
            "chapter_roman": _clean_text(row.get("chapter_roman")),
            "faculty": _clean_text(row.get("faculty")),
            "heading": _clean_text(row.get("heading")),
            "printed_page": row.get("printed_page"),
            "section": _clean_text(row.get("section")),
            "volume": _clean_text(row.get("volume")),
        }
        for row in chapters
    ]
    return {
        "schema": "shelfsignals-jefferson-hierarchy@1",
        "generated_at": generated_at,
        "collection_id": "jefferson",
        "source": {
            "authority": "Library of Congress",
            "dataset": "loc_sowerby_reference.json",
            "dataset_sha256": source_hash,
        },
        "unit": "Sowerby base-integer identifier",
        "base_integer_identifier_count": reference.get("base_integer_identifier_count"),
        "faculties": [
            {"name": "History", "chapter_start": 1, "chapter_end": 15},
            {"name": "Philosophy", "chapter_start": 16, "chapter_end": 29},
            {"name": "Fine Arts", "chapter_start": 30, "chapter_end": 44},
        ],
        "chapters": chapter_rows,
        "volume_ranges": reference.get("volume_ranges") or [],
        "coverage_notice": (
            "This is the 4,931-number Sowerby base-integer hierarchy, shown as a coverage preview. "
            "It does not establish catalog links or reconstruct Jefferson's physical shelving."
        ),
    }


def _digital_by_id(rows: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any]]:
    result: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        identifier = _clean_text(row.get("id"))
        if not identifier or identifier in result:
            raise BuildError(f"Digital item ID is missing or duplicated: {identifier!r}")
        result[identifier] = row
    return result


def _rights_are_explicitly_free(rights: Sequence[str]) -> bool:
    text = " ".join(_plain_text(value).casefold() for value in rights)
    return bool(re.search(r"\bfree (?:for|to) (?:use|reuse|use and reuse)\b|\bfree to use and reuse\b", text))


def _media_row(
    projected_by_source_id: Mapping[str, Mapping[str, Any]],
    digital_by_id: Mapping[str, Mapping[str, Any]],
    link: Mapping[str, Any],
) -> list[Any]:
    source_catalog_id = _clean_text(link.get("catalog_entity_id"))
    digital_id = _clean_text(link.get("digital_item_id"))
    projected = projected_by_source_id.get(source_catalog_id)
    digital = digital_by_id.get(digital_id)
    if not projected or not digital:
        raise BuildError("Exact catalog/digital relation references an unknown entity")
    detail = _require_object(digital.get("item_detail"), f"Digital detail {digital_id}")
    item = _require_object(detail.get("item"), f"Digital item {digital_id}")
    url = _clean_text(item.get("url"))
    images = _unique_strings(item.get("image_url") or [])
    thumbnail = images[0] if images else ""
    _validate_https_url(url, {"www.loc.gov", "loc.gov"}, f"Digital item URL {digital_id}")
    if thumbnail:
        _validate_https_url(thumbnail.split("#", 1)[0], {"tile.loc.gov"}, f"Digital thumbnail {digital_id}")
    rights = [_plain_text(value) for value in (item.get("rights") or []) if _plain_text(value)]
    lccns = _unique_strings(link.get("normalized_lccns") or [])
    if _clean_text(link.get("match_basis")) != "normalized LCCN exact" or not lccns:
        raise BuildError("Review media relation is not exact normalized-LCCN evidence")
    return [
        projected["browser_id"],
        digital_id,
        url,
        thumbnail,
        rights,
        "rights_review_required",
        "normalized LCCN exact",
        lccns,
        [projected["orders"]["sowerby"]],
    ]


def _media_payloads(
    crosswalk_rows: Sequence[Mapping[str, Any]],
    projected: Sequence[Mapping[str, Any]],
    digital_rows: Sequence[Mapping[str, Any]],
    generated_at: str,
    source_identity: Mapping[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    projected_by_source_id = {row["source_id"]: row for row in projected}
    digital = _digital_by_id(digital_rows)
    exact_links: list[tuple[Mapping[str, Any], Mapping[str, Any]]] = []
    for crosswalk in crosswalk_rows:
        for link in crosswalk.get("catalog_digital_links") or []:
            if not isinstance(link, dict):
                raise BuildError("Catalog/digital crosswalk links must be objects")
            exact_links.append((crosswalk, link))
    if len(exact_links) != 1:
        raise BuildError(f"Phase 1 expects exactly one exact catalog/digital relation, found {len(exact_links)}")

    crosswalk, link = exact_links[0]
    row = _media_row(projected_by_source_id, digital, link)
    expected_sowerby = crosswalk.get("sowerby_base_integer")
    if row[-1] != [expected_sowerby]:
        raise BuildError("Media relation Sowerby evidence disagrees with catalog projection")
    digital_detail = _require_object(digital[row[1]].get("item_detail"), f"Digital detail {row[1]}")
    digital_item = _require_object(digital_detail.get("item"), f"Digital item {row[1]}")
    rights = [_plain_text(value) for value in (digital_item.get("rights") or []) if _plain_text(value)]

    common = {
        "schema": "shelfsignals-media-manifest@1",
        "generated_at": generated_at,
        "collection_id": "jefferson",
        "source": dict(source_identity),
        "fields": MEDIA_FIELDS,
    }
    public = {
        **common,
        "audience": "public",
        "security_notice": "Only exact-linked media with an explicit free-use/reuse statement may appear here.",
        "items": [row[:5] + ["public_rights_reviewed"] + row[6:]]
        if _rights_are_explicitly_free(rights)
        else [],
    }
    review = {
        **common,
        "audience": "review",
        "security_notice": "Review mode is interface friction, not access control; every asset still requires item-level rights review.",
        "items": [row],
    }
    return public, review


def _featured_payload(projected: Sequence[Mapping[str, Any]], expected_link_count: int) -> dict[str, Any]:
    linked = [row["browser_id"] for row in projected if row["evidence_status"] == "sowerby_510_exact_bounded"]
    if len(linked) != expected_link_count:
        raise BuildError(
            f"Explicit Sowerby-linked record count disagrees with research validation: {len(linked)} != {expected_link_count}"
        )
    return {
        "schema": "shelfsignals-featured-items@1",
        "version": "1.0.0-beta",
        "hero": linked[:11],
        "highlights": linked[11:],
        "notes": (
            f"Deterministic interface-QA selection from the {expected_link_count} records carrying bounded source-MARC Sowerby evidence. "
            "Selection does not assert historical importance, ownership, survival, or reconstruction status."
        ),
    }


def _manifest_payload(
    source: Mapping[str, Any], historical_entry_count: int, established_sowerby_links: int
) -> dict[str, Any]:
    return {
        "schema": "shelfsignals-collection-manifest@1",
        "id": "jefferson",
        "copy": {
            "name": "Thomas Jefferson's Library",
            "short_name": "Jefferson",
            "institution": "Library of Congress",
            "status_label": "Catalog beta",
            "introduction": "Explore current Library of Congress catalog instances carrying the exact Jefferson collection heading.",
            "coverage_statement": (
                f"This beta contains {source['record_count']:,} current LOC catalog instances, not the complete "
                f"{historical_entry_count:,}-entry Sowerby corpus or the 6,487 physical volumes transferred in 1815. "
                f"Only {established_sowerby_links} Sowerby links are established by the bounded MARC sample."
            ),
            "source_label": "Library of Congress catalog",
        },
        "data": {
            "core": "catalog-core.json",
            "search": "catalog-search.json",
            "detail_template": "catalog-details/{shard}.json",
            "detail_index": "catalog-details/index.json",
            "hierarchy": "hierarchy.json",
            "featured": "featured_items.json",
            "public_media": "media-public.json",
            "validation": "validation.json",
            "review_media": "media-review.json",
        },
        "features": {
            "journeys": False,
            "placement": False,
            "photo_likelihood": False,
            "provider_editions": False,
            "curated_paths": False,
            "historical_hierarchy": True,
            "coverage_comparison": True,
            "reconstruction_status": True,
            "digital_surrogates": True,
            "evidence_ledger": True,
            "physical": False,
        },
        "coverage": {
            "status": "beta",
            "entity_type": "catalog_instance",
            "record_count": source["record_count"],
            "historical_entry_count": historical_entry_count,
            "historical_volume_count": 6487,
            "established_sowerby_links": established_sowerby_links,
        },
        "shelf": {"storage_key": "shelfsignals_shelf:jefferson", "receipt_name": "jefferson-shelf.json"},
        "facets": ["classes", "materials", "decades", "evidence_status"],
        "orders": [
            {"id": "title", "label": "Title"},
            {"id": "lc", "label": "Modern classification / call number"},
        ],
        "defaults": {"corpus": "catalog", "order": "title"},
        "review": {
            "enabled": True,
            "code_sha256": REVIEW_CODE_SHA256,
            "session_key": "shelfsignals_review:jefferson",
            "warning": "Review mode—not access controlled. Rights-pending media still requires item-level review.",
        },
    }


def _walk_keys(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for key, nested in value.items():
            yield key
            yield from _walk_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk_keys(nested)


def _validate_public_payloads(
    files: Mapping[str, bytes], source: Mapping[str, Any], *, historical_entry_count: int = 4931
) -> dict[str, Any]:
    decoded: dict[str, Any] = {}
    for path, data in files.items():
        try:
            decoded[path] = json.loads(data)
        except json.JSONDecodeError as error:
            raise BuildError(f"Generated output is not valid JSON: {path}: {error}") from error
        forbidden = sorted(set(_walk_keys(decoded[path])) & FORBIDDEN_PUBLIC_KEYS)
        if forbidden:
            raise BuildError(f"Generated output {path} contains forbidden keys: {', '.join(forbidden)}")
        text = data.decode("utf-8")
        if str(REPOSITORY_ROOT) in text or str(DEFAULT_SOURCE_DIR) in text:
            raise BuildError(f"Generated output {path} contains a local filesystem path")

    core = decoded["catalog-core.json"]
    search = decoded["catalog-search.json"]
    detail_index = decoded["catalog-details/index.json"]
    public_media = decoded["media-public.json"]
    review_media = decoded["media-review.json"]
    hierarchy = decoded["hierarchy.json"]
    if core.get("source") != source or search.get("source") != source:
        raise BuildError("Core/search source identity is not exact")
    if core.get("contract", {}).get("core_fields") != CORE_FIELDS:
        raise BuildError("Core field contract changed")
    if core.get("contract", {}).get("detail_fields") != DETAIL_FIELDS:
        raise BuildError("Detail field contract changed")
    if len(core.get("items") or []) != source["record_count"] or len(search.get("items") or []) != source["record_count"]:
        raise BuildError("Core/search record counts do not match source identity")
    if detail_index.get("shard_count") != SHARD_COUNT or len(detail_index.get("shards") or []) != SHARD_COUNT:
        raise BuildError("Detail index does not enumerate exactly 64 shards")
    if len(public_media.get("items") or []) > 1 or len(review_media.get("items") or []) != 1:
        raise BuildError("Media manifests violate the exact-link/public-rights contract")
    if hierarchy.get("base_integer_identifier_count") != historical_entry_count or len(hierarchy.get("chapters") or []) != 44:
        raise BuildError("Hierarchy coverage contract failed")

    core_bytes = len(files["catalog-core.json"])
    core_gzip_bytes = len(gzip.compress(files["catalog-core.json"], mtime=0))
    if core_bytes > 1_250_000 or core_gzip_bytes > 350_000:
        raise BuildError(
            f"Core performance budget exceeded ({core_bytes} decoded, {core_gzip_bytes} gzip; budgets 1250000/350000)"
        )
    return {"core_bytes": core_bytes, "core_gzip_bytes": core_gzip_bytes}


def build_package(source_dir: Path = DEFAULT_SOURCE_DIR) -> dict[str, bytes]:
    """Return every output path and byte-exact payload without writing files."""

    source_dir = Path(source_dir)
    research_manifest = _require_object(_load_json(source_dir / "manifest.json"), "Research manifest")
    research_validation = _require_object(_load_json(source_dir / "validation.json"), "Research validation")
    source_package = _validate_input_hashes(source_dir, research_manifest)
    invariants = _require_object(research_validation.get("invariants"), "Research validation invariants")
    if invariants.get("all_applicable_invariants_passed") is not True or invariants.get("failed_invariants"):
        raise BuildError("Research validation has failed applicable invariants")

    generated_at = _clean_text(research_manifest.get("generated_at"))
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", generated_at):
        raise BuildError("Research manifest has no deterministic whole-second UTC generation time")

    catalog_path = source_dir / REQUIRED_INPUTS["catalog_instances"]
    catalog_rows = _load_jsonl(catalog_path)
    crosswalk_rows = _load_jsonl(source_dir / REQUIRED_INPUTS["crosswalk"])
    digital_rows = _load_jsonl(source_dir / REQUIRED_INPUTS["digital_items"])
    sowerby_reference = _require_object(
        _load_json(source_dir / REQUIRED_INPUTS["loc_sowerby_reference"]), "LOC Sowerby reference"
    )

    expected_counts = _require_object(research_manifest.get("counts"), "Research manifest counts")
    if len(catalog_rows) != expected_counts.get("loc_exact_catalog_instances"):
        raise BuildError("Catalog record count disagrees with the research manifest")
    if len(digital_rows) != expected_counts.get("loc_digital_items"):
        raise BuildError("Digital record count disagrees with the research manifest")
    if len(crosswalk_rows) != expected_counts.get("loc_sowerby_base_integer_identifiers"):
        raise BuildError("Crosswalk row count disagrees with the research manifest")

    crosswalk_validation = _require_object(research_validation.get("crosswalk"), "Research crosswalk validation")
    expected_link_count = crosswalk_validation.get(
        "sowerby_references_with_one_catalog_candidate_in_bounded_sample"
    )
    assessed_catalog_count = crosswalk_validation.get("catalog_entities_assessed_in_bounded_marc_sample")
    exact_media_link_count = crosswalk_validation.get("catalog_digital_pair_count")
    if not isinstance(expected_link_count, int) or expected_link_count < 0:
        raise BuildError("Research validation has no usable established-Sowerby-link count")
    if not isinstance(assessed_catalog_count, int) or not 0 <= assessed_catalog_count <= len(catalog_rows):
        raise BuildError("Research validation has no usable bounded-MARC assessment count")
    if exact_media_link_count != 1:
        raise BuildError("Phase 1 requires exactly one exact catalog/digital relation")

    historical_entry_count = sowerby_reference.get("base_integer_identifier_count")
    if historical_entry_count != expected_counts.get("loc_sowerby_base_integer_identifiers"):
        raise BuildError("Sowerby reference count disagrees with the research manifest")

    links_by_source = _established_crosswalk(crosswalk_rows)
    projected = [
        _make_record_projection(row, index, links_by_source.get(_clean_text(row.get("id"))))
        for index, row in enumerate(catalog_rows)
    ]
    browser_ids = [row["browser_id"] for row in projected]
    if len(browser_ids) != len(set(browser_ids)):
        raise BuildError("Browser record IDs are duplicated")
    if len(links_by_source) != expected_link_count or sum(bool(row["orders"]["sowerby"]) for row in projected) != expected_link_count:
        raise BuildError("Explicit Sowerby links disagree with research validation")
    if any(row["detail"][2] != row["full_title"] for row in projected):
        raise BuildError("Full catalog titles did not survive the detail projection")
    _assign_lc_ranks(projected)

    source_identity = _source_identity(catalog_path.read_bytes(), browser_ids)
    shard_rows: list[list[list[Any]]] = [[] for _ in range(SHARD_COUNT)]
    for row in projected:
        shard_rows[row["detail_shard"]].append(row["detail"])

    core = {
        "schema": CORE_SCHEMA,
        "generated_at": generated_at,
        "source": source_identity,
        "contract": {
            "core_fields": CORE_FIELDS,
            "detail_fields": DETAIL_FIELDS,
            "detail_shard_count": SHARD_COUNT,
            "detail_path_template": "catalog-details/{shard}.json",
            "search_path": "catalog-search.json",
        },
        "items": [_core_row(row) for row in projected],
    }
    search = {
        "schema": SEARCH_SCHEMA,
        "generated_at": generated_at,
        "source": source_identity,
        "fields": SEARCH_FIELDS,
        "items": [[row["browser_id"], row["search"]] for row in projected],
    }
    detail_payloads = [
        {
            "schema": DETAIL_SCHEMA,
            "generated_at": generated_at,
            "source": source_identity,
            "shard": shard,
            "shard_count": SHARD_COUNT,
            "item_count": len(items),
            "fields": DETAIL_FIELDS,
            "items": items,
        }
        for shard, items in enumerate(shard_rows)
    ]

    files: dict[str, bytes] = {
        "catalog-core.json": _json_bytes(core),
        "catalog-search.json": _json_bytes(search),
    }
    for shard, payload in enumerate(detail_payloads):
        files[f"catalog-details/{shard:03d}.json"] = _json_bytes(payload)
    detail_index = {
        "schema": DETAIL_INDEX_SCHEMA,
        "generated_at": generated_at,
        "source": source_identity,
        "shard_count": SHARD_COUNT,
        "fields": DETAIL_FIELDS,
        "shards": [
            {
                "shard": shard,
                "file": f"{shard:03d}.json",
                "item_count": len(shard_rows[shard]),
                "bytes": len(files[f"catalog-details/{shard:03d}.json"]),
                "sha256": _sha256_bytes(files[f"catalog-details/{shard:03d}.json"]),
            }
            for shard in range(SHARD_COUNT)
        ],
    }
    files["catalog-details/index.json"] = _json_bytes(detail_index)
    files["hierarchy.json"] = _json_bytes(
        _hierarchy_payload(
            sowerby_reference,
            generated_at,
            source_package["loc_sowerby_reference"]["sha256"],
        )
    )
    files["featured_items.json"] = _json_bytes(_featured_payload(projected, expected_link_count))
    public_media, review_media = _media_payloads(
        crosswalk_rows, projected, digital_rows, generated_at, source_identity
    )
    files["media-public.json"] = _json_bytes(public_media)
    files["media-review.json"] = _json_bytes(review_media)

    performance = _validate_public_payloads(
        files, source_identity, historical_entry_count=historical_entry_count
    )
    output_checks = {
        path: {"bytes": len(data), "sha256": _sha256_bytes(data)} for path, data in sorted(files.items())
    }
    validation = {
        "schema": "shelfsignals-jefferson-browser-validation@1",
        "generated_at": generated_at,
        "collection_id": "jefferson",
        "source": source_identity,
        "source_package": source_package,
        "counts": {
            "catalog_instances": len(projected),
            "detail_shards": SHARD_COUNT,
            "sowerby_base_integer_target": historical_entry_count,
            "established_sowerby_links": expected_link_count,
            "catalog_instances_assessed_in_bounded_marc_sample": assessed_catalog_count,
            "catalog_instances_not_assessed_in_bounded_marc_sample": len(projected) - assessed_catalog_count,
            "exact_catalog_digital_links": len(review_media["items"]),
            "public_media_items": len(public_media["items"]),
            "review_media_items": len(review_media["items"]),
        },
        "checks": {
            "research_invariants_passed": True,
            "source_hashes_match_research_manifest": True,
            "exact_collection_heading_only": True,
            "ownership_and_reconstruction_unresolved": True,
            "sowerby_links_bounded_and_explicit": True,
            "record_urls_source_supplied_only": True,
            "full_titles_round_trip_in_detail_shards": True,
            "private_operational_fields_excluded": True,
            "media_relations_exact_lccn_only": True,
            "public_media_requires_explicit_free_reuse_language": True,
            "all_64_detail_shards_present": True,
        },
        "performance": {
            **performance,
            "core_decoded_budget_bytes": 1_250_000,
            "core_gzip_budget_bytes": 350_000,
        },
        "outputs": output_checks,
        "warnings": [
            f"This beta represents {len(projected):,} current LOC catalog instances, not {historical_entry_count:,} Sowerby entries or 6,487 historical volumes.",
            f"Only {assessed_catalog_count} catalog instances had bounded source-MARC evidence; {expected_link_count} have explicit Sowerby links.",
            "Ownership, survival, replacement, surrogate, missing, historical shelf order, and physical placement are not established.",
            "Attached holdings and items are current catalog inventory objects; they do not establish Jefferson ownership or reconstruction status.",
            "Review mode is not access control; its one exact-linked digital item still requires item-level rights review.",
        ],
    }
    files["validation.json"] = _json_bytes(validation)

    manifest = _manifest_payload(source_identity, historical_entry_count, expected_link_count)
    files["manifest.json"] = _json_bytes(manifest)
    _validate_public_payloads(files, source_identity, historical_entry_count=historical_entry_count)
    return dict(sorted(files.items()))


def _expected_paths(files: Mapping[str, bytes]) -> set[str]:
    return set(files)


def _owned_phase_one_path(relative: str) -> bool:
    """Phase 1 owns root catalog files, never the historical namespace."""

    return not relative.startswith("historical/")


def write_package(files: Mapping[str, bytes], output_dir: Path = DEFAULT_OUTPUT_DIR) -> None:
    """Write the package through a staging directory, then replace expected files."""

    output_dir = Path(output_dir)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".jefferson-browser-", dir=output_dir.parent))
    try:
        for relative, data in files.items():
            target = staging / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(data)
        if output_dir.exists():
            for path in sorted(output_dir.rglob("*"), reverse=True):
                if path.is_file() and path.relative_to(output_dir).as_posix() not in _expected_paths(files):
                    relative = path.relative_to(output_dir).as_posix()
                    if _owned_phase_one_path(relative):
                        path.unlink()
        output_dir.mkdir(parents=True, exist_ok=True)
        for relative in sorted(files):
            source = staging / relative
            target = output_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(source, target)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def check_package(files: Mapping[str, bytes], output_dir: Path = DEFAULT_OUTPUT_DIR) -> None:
    """Fail when committed output is missing, stale, or contains an extra JSON file."""

    output_dir = Path(output_dir)
    failures: list[str] = []
    expected = _expected_paths(files)
    for relative, data in files.items():
        path = output_dir / relative
        if not path.is_file():
            failures.append(f"missing: {relative}")
        elif path.read_bytes() != data:
            failures.append(f"stale: {relative}")
    actual = {
        path.relative_to(output_dir).as_posix()
        for path in output_dir.rglob("*")
        if path.is_file()
    } if output_dir.is_dir() else set()
    for relative in sorted(path for path in actual - expected if _owned_phase_one_path(path)):
        failures.append(f"unexpected: {relative}")
    if failures:
        raise BuildError("Jefferson browser package check failed:\n- " + "\n- ".join(failures))


def _parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true", help="Compare generated bytes with the committed package")
    mode.add_argument("--self-test", action="store_true", help="Build and validate fully in memory without writing")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = _parse_args(argv)
    try:
        files = build_package(args.source_dir)
        if args.check:
            check_package(files, args.output_dir)
            action = "checked"
        elif args.self_test:
            action = "validated in memory"
        else:
            write_package(files, args.output_dir)
            action = "wrote"
        total_bytes = sum(len(data) for data in files.values())
        print(f"Jefferson browser package {action}: {len(files)} files, {total_bytes} bytes, 2,748 catalog instances")
        return 0
    except BuildError as error:
        print(f"error: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
