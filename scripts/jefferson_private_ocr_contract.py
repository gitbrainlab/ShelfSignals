#!/usr/bin/env python3
"""Strict contract for authenticated Jefferson OCR-review manifests."""

from __future__ import annotations

from collections import Counter
import datetime as dt
import math
import re
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit


SCHEMA = "shelfsignals-jefferson-private-ocr-review@1"
EXPECTED_ENTRIES = 132
EXPECTED_CHAPTERS = 44
EXPECTED_ENTRIES_PER_CHAPTER = 3
EXPECTED_DIRECT_RECORDS = 5
MAX_TRANSCRIPT_CHARACTERS = 12_000
MAX_MANIFEST_BYTES = 4 * 1024 * 1024

SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
RECORD_ID_RE = re.compile(r"^jefferson-sowerby-([1-9]\d{0,3})$")
EVENT_ID_RE = re.compile(r"^[a-z][a-z0-9-]{1,63}$")
CONTROL_RE = re.compile(r"[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]")
REGION_PATH_RE = re.compile(r"/pct:([^/]+)/1000,/0/default\.jpg$")

ROOT_FIELDS = {
    "schema", "collection_id", "corpus_id", "audience", "generated_at",
    "source", "methodology", "coverage", "entries",
}
SOURCE_FIELDS = {
    "authority", "item_url", "rights_statement_url", "rights_clearance",
    "source_identity_sha256", "ocr_manifest_sha256", "historical_core_sha256",
    "insight_graph_sha256",
}
METHODOLOGY_FIELDS = {"selection", "sectioning", "visual_evidence", "confidence", "use_boundary"}
COVERAGE_FIELDS = {
    "historical_entries", "page_resolved_entries", "pilot_entries", "chapters",
    "entries_per_chapter", "section_regions", "source_backed_titles",
    "direct_documentary_records",
}
ENTRY_FIELDS = {
    "record_id", "sowerby_number", "title", "title_status", "faculty",
    "chapter_number", "chapter_label", "volume", "terminal_pdf_page", "pdf_url",
    "section", "snapshots", "event_contexts",
}
SECTION_FIELDS = {
    "type", "classification_status", "transcript", "transcript_truncated",
    "line_count", "mean_confidence", "marker_confidence", "title_confidence",
}
SNAPSHOT_FIELDS = {
    "pdf_page", "region_pct", "image_url", "full_page_image_url", "line_count",
    "mean_confidence",
}
REGION_FIELDS = {"x", "y", "width", "height"}
EVENT_FIELDS = {
    "event_id", "title", "date_label", "relationship", "context_score",
    "direct_relation", "event_use_status", "use_confidence_score",
}

LOC_ITEM_URL = "https://www.loc.gov/item/52060000/"
LOC_PDF_URLS = {
    volume: (
        "https://tile.loc.gov/storage-services/service/rbc/rbc0001/2007/"
        f"2007jeffcat{volume}/2007jeffcat{volume}.pdf"
    )
    for volume in range(1, 6)
}
EVENT_USE_STATUSES = {
    "not_established", "documented_interaction", "documented_excerpting",
    "documented_correspondence_context",
}


class PrivateOcrContractError(ValueError):
    """Raised when a private OCR manifest violates its release contract."""


def _object(value: Any, fields: set[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise PrivateOcrContractError(f"{label} must contain exactly the declared fields")
    return value


def _integer(value: Any, minimum: int, maximum: int, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise PrivateOcrContractError(f"{label} is outside its integer bounds")
    return value


def _score(value: Any, label: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 100:
        raise PrivateOcrContractError(f"{label} must be a finite score from 0 to 100")
    return float(value)


def _text(value: Any, label: str, *, maximum: int, allow_empty: bool = False) -> str:
    if not isinstance(value, str) or len(value) > maximum or CONTROL_RE.search(value):
        raise PrivateOcrContractError(f"{label} is not safe bounded text")
    if not allow_empty and not value.strip():
        raise PrivateOcrContractError(f"{label} cannot be empty")
    return value


def _https_loc_url(value: Any, label: str, *, hostname: str | None = None) -> str:
    text = _text(value, label, maximum=2_048)
    try:
        parsed = urlsplit(text)
        port = parsed.port
    except ValueError as error:
        raise PrivateOcrContractError(f"{label} is not a valid LOC URL") from error
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or port is not None
        or parsed.hostname not in {"www.loc.gov", "tile.loc.gov"}
        or (hostname is not None and parsed.hostname != hostname)
        or parsed.query
        or parsed.fragment
    ):
        raise PrivateOcrContractError(f"{label} must be an uncredentialed canonical HTTPS LOC URL")
    return text


def _region(value: Any, label: str) -> tuple[float, float, float, float]:
    region = _object(value, REGION_FIELDS, label)
    values: list[float] = []
    for field in ("x", "y", "width", "height"):
        number = region[field]
        if isinstance(number, bool) or not isinstance(number, (int, float)) or not math.isfinite(number):
            raise PrivateOcrContractError(f"{label}.{field} is not finite")
        values.append(float(number))
    x, y, width, height = values
    if x < 0 or y < 0 or width <= 0 or height <= 0 or x + width > 100.002 or y + height > 100.002:
        raise PrivateOcrContractError(f"{label} lies outside the source page")
    return x, y, width, height


def _snapshot(value: Any, *, volume: int, terminal_page: int, label: str) -> Mapping[str, Any]:
    snapshot = _object(value, SNAPSHOT_FIELDS, label)
    _integer(snapshot["pdf_page"], 1, terminal_page, f"{label}.pdf_page")
    coordinates = _region(snapshot["region_pct"], f"{label}.region_pct")
    image_url = _https_loc_url(snapshot["image_url"], f"{label}.image_url", hostname="tile.loc.gov")
    full_page_url = _https_loc_url(
        snapshot["full_page_image_url"], f"{label}.full_page_image_url", hostname="tile.loc.gov"
    )
    image_path = urlsplit(image_url).path
    full_page_path = urlsplit(full_page_url).path
    volume_marker = f":2007jeffcat{volume}:"
    match = REGION_PATH_RE.search(image_path)
    if not image_path.startswith("/image-services/iiif/") or volume_marker not in image_path or not match:
        raise PrivateOcrContractError(f"{label}.image_url is not a bounded LOC IIIF region for its volume")
    try:
        encoded_coordinates = tuple(float(part) for part in match.group(1).split(","))
    except ValueError as error:
        raise PrivateOcrContractError(f"{label}.image_url has invalid IIIF coordinates") from error
    if len(encoded_coordinates) != 4 or any(abs(left - right) > 0.0006 for left, right in zip(encoded_coordinates, coordinates)):
        raise PrivateOcrContractError(f"{label}.image_url does not match region_pct")
    if (
        not full_page_path.startswith("/image-services/iiif/")
        or volume_marker not in full_page_path
        or not full_page_path.endswith("/full/pct:100/0/default.jpg")
    ):
        raise PrivateOcrContractError(f"{label}.full_page_image_url is not the matching LOC volume service")
    if image_path.split("/pct:", 1)[0] != full_page_path.split("/full/", 1)[0]:
        raise PrivateOcrContractError(f"{label} pairs source images from different LOC IIIF pages")
    _integer(snapshot["line_count"], 1, 10_000, f"{label}.line_count")
    _score(snapshot["mean_confidence"], f"{label}.mean_confidence")
    return snapshot


def _event(value: Any, label: str) -> Mapping[str, Any]:
    event = _object(value, EVENT_FIELDS, label)
    event_id = _text(event["event_id"], f"{label}.event_id", maximum=64)
    if not EVENT_ID_RE.fullmatch(event_id):
        raise PrivateOcrContractError(f"{label}.event_id is invalid")
    for field, maximum in (("title", 200), ("date_label", 100), ("relationship", 200)):
        _text(event[field], f"{label}.{field}", maximum=maximum)
    _score(event["context_score"], f"{label}.context_score")
    if not isinstance(event["direct_relation"], bool) or event["event_use_status"] not in EVENT_USE_STATUSES:
        raise PrivateOcrContractError(f"{label} has an invalid relationship state")
    use_score = event["use_confidence_score"]
    if use_score is not None:
        _score(use_score, f"{label}.use_confidence_score")
    if not event["direct_relation"] and (event["event_use_status"] != "not_established" or use_score is not None):
        raise PrivateOcrContractError(f"{label} turns contextual evidence into an unsupported use claim")
    if event["event_use_status"] == "not_established" and use_score is not None:
        raise PrivateOcrContractError(f"{label} scores use even though use is not established")
    if event["event_use_status"] != "not_established" and use_score is None:
        raise PrivateOcrContractError(f"{label} omits the confidence score for a documented use status")
    return event


def _entry(value: Any, index: int) -> Mapping[str, Any]:
    label = f"entries[{index}]"
    entry = _object(value, ENTRY_FIELDS, label)
    record_id = _text(entry["record_id"], f"{label}.record_id", maximum=64)
    match = RECORD_ID_RE.fullmatch(record_id)
    serial = _integer(entry["sowerby_number"], 1, 4_931, f"{label}.sowerby_number")
    if not match or int(match.group(1)) != serial:
        raise PrivateOcrContractError(f"{label} has an inconsistent record identity")
    title_status = entry["title_status"]
    if title_status not in {"source_backed", "not_established"}:
        raise PrivateOcrContractError(f"{label}.title_status is unsupported")
    title = _text(entry["title"], f"{label}.title", maximum=1_000, allow_empty=True)
    if (title_status == "source_backed") != bool(title.strip()):
        raise PrivateOcrContractError(f"{label}.title does not match title_status")
    faculty = _text(entry["faculty"], f"{label}.faculty", maximum=100)
    if faculty not in {"History", "Philosophy", "Fine Arts"}:
        raise PrivateOcrContractError(f"{label}.faculty is unsupported")
    _integer(entry["chapter_number"], 1, 44, f"{label}.chapter_number")
    _text(entry["chapter_label"], f"{label}.chapter_label", maximum=200)
    volume = _integer(entry["volume"], 1, 5, f"{label}.volume")
    terminal_page = _integer(entry["terminal_pdf_page"], 1, 700, f"{label}.terminal_pdf_page")
    pdf_url = _https_loc_url(entry["pdf_url"], f"{label}.pdf_url", hostname="tile.loc.gov")
    if pdf_url != LOC_PDF_URLS[volume]:
        raise PrivateOcrContractError(f"{label}.pdf_url does not match its Sowerby volume")

    section = _object(entry["section"], SECTION_FIELDS, f"{label}.section")
    if section["type"] != "sowerby_entry_block" or section["classification_status"] != "machine_detected_unreviewed":
        raise PrivateOcrContractError(f"{label}.section has an unsupported classification")
    transcript = _text(
        section["transcript"], f"{label}.section.transcript", maximum=MAX_TRANSCRIPT_CHARACTERS
    )
    if not isinstance(section["transcript_truncated"], bool):
        raise PrivateOcrContractError(f"{label}.section.transcript_truncated must be boolean")
    if section["transcript_truncated"] and len(transcript) != MAX_TRANSCRIPT_CHARACTERS:
        raise PrivateOcrContractError(f"{label}.section transcript truncation is inconsistent")
    _integer(section["line_count"], 1, 100_000, f"{label}.section.line_count")
    for field in ("mean_confidence", "marker_confidence", "title_confidence"):
        _score(section[field], f"{label}.section.{field}")

    snapshots = entry["snapshots"]
    if not isinstance(snapshots, list) or not 1 <= len(snapshots) <= 3:
        raise PrivateOcrContractError(f"{label}.snapshots must contain one to three regions")
    validated_snapshots = [
        _snapshot(snapshot, volume=volume, terminal_page=terminal_page, label=f"{label}.snapshots[{offset}]")
        for offset, snapshot in enumerate(snapshots)
    ]
    page_numbers = [snapshot["pdf_page"] for snapshot in validated_snapshots]
    if page_numbers != sorted(set(page_numbers)):
        raise PrivateOcrContractError(f"{label}.snapshots contain duplicate or unsorted pages")

    events = entry["event_contexts"]
    if not isinstance(events, list) or not 1 <= len(events) <= 9:
        raise PrivateOcrContractError(f"{label}.event_contexts must contain one to nine contexts")
    validated_events = [_event(event, f"{label}.event_contexts[{offset}]") for offset, event in enumerate(events)]
    event_ids = [event["event_id"] for event in validated_events]
    if len(event_ids) != len(set(event_ids)):
        raise PrivateOcrContractError(f"{label}.event_contexts contains duplicate events")
    return entry


def validate_manifest(raw: Any) -> Mapping[str, Any]:
    manifest = _object(raw, ROOT_FIELDS, "Private OCR manifest")
    if manifest["schema"] != SCHEMA or manifest["collection_id"] != "jefferson" or manifest["corpus_id"] != "historical" or manifest["audience"] != "authenticated_review":
        raise PrivateOcrContractError("Private OCR manifest has the wrong identity")
    generated_at = _text(manifest["generated_at"], "generated_at", maximum=20)
    if not UTC_RE.fullmatch(generated_at):
        raise PrivateOcrContractError("generated_at must be a whole-second UTC timestamp")
    try:
        dt.datetime.strptime(generated_at, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as error:
        raise PrivateOcrContractError("generated_at is not a valid UTC timestamp") from error

    source = _object(manifest["source"], SOURCE_FIELDS, "source")
    if source["authority"] != "Library of Congress" or source["item_url"] != LOC_ITEM_URL or source["rights_statement_url"] != LOC_ITEM_URL:
        raise PrivateOcrContractError("Private OCR source is not the declared LOC Sowerby item")
    _https_loc_url(source["item_url"], "source.item_url", hostname="www.loc.gov")
    _https_loc_url(source["rights_statement_url"], "source.rights_statement_url", hostname="www.loc.gov")
    if source["rights_clearance"] != "not granted; item-level assessment remains required":
        raise PrivateOcrContractError("Private OCR source rights status was weakened")
    for field in ("source_identity_sha256", "ocr_manifest_sha256", "historical_core_sha256", "insight_graph_sha256"):
        if not isinstance(source[field], str) or not SHA256_RE.fullmatch(source[field]):
            raise PrivateOcrContractError(f"source.{field} is not a SHA-256 digest")

    methodology = _object(manifest["methodology"], METHODOLOGY_FIELDS, "methodology")
    for field in METHODOLOGY_FIELDS:
        _text(methodology[field], f"methodology.{field}", maximum=2_000)

    coverage = _object(manifest["coverage"], COVERAGE_FIELDS, "coverage")
    expected = {
        "historical_entries": 4_928,
        "page_resolved_entries": 4_675,
        "pilot_entries": EXPECTED_ENTRIES,
        "chapters": EXPECTED_CHAPTERS,
        "entries_per_chapter": EXPECTED_ENTRIES_PER_CHAPTER,
        "direct_documentary_records": EXPECTED_DIRECT_RECORDS,
    }
    for field, value in expected.items():
        if coverage[field] != value:
            raise PrivateOcrContractError(f"coverage.{field} must equal {value}")
    _integer(coverage["section_regions"], EXPECTED_ENTRIES, EXPECTED_ENTRIES * 3, "coverage.section_regions")
    _integer(coverage["source_backed_titles"], 0, EXPECTED_ENTRIES, "coverage.source_backed_titles")

    entries = manifest["entries"]
    if not isinstance(entries, list) or len(entries) != EXPECTED_ENTRIES:
        raise PrivateOcrContractError(f"Private OCR manifest must contain exactly {EXPECTED_ENTRIES} entries")
    validated_entries = [_entry(entry, index) for index, entry in enumerate(entries)]
    ids = [entry["record_id"] for entry in validated_entries]
    if len(ids) != len(set(ids)):
        raise PrivateOcrContractError("Private OCR manifest contains duplicate record IDs")
    chapters = Counter(entry["chapter_number"] for entry in validated_entries)
    if chapters != Counter({chapter: EXPECTED_ENTRIES_PER_CHAPTER for chapter in range(1, EXPECTED_CHAPTERS + 1)}):
        raise PrivateOcrContractError("Private OCR manifest does not cover all chapters equally")
    if sum(len(entry["snapshots"]) for entry in validated_entries) != coverage["section_regions"]:
        raise PrivateOcrContractError("Private OCR snapshot count does not reconcile")
    if sum(entry["title_status"] == "source_backed" for entry in validated_entries) != coverage["source_backed_titles"]:
        raise PrivateOcrContractError("Private OCR title count does not reconcile")
    direct_records = sum(any(context["direct_relation"] for context in entry["event_contexts"]) for entry in validated_entries)
    if direct_records != coverage["direct_documentary_records"]:
        raise PrivateOcrContractError("Private OCR direct-documentary count does not reconcile")
    return manifest


def validate_manifest_size(raw_bytes: bytes) -> None:
    if len(raw_bytes) > MAX_MANIFEST_BYTES:
        raise PrivateOcrContractError("Private OCR manifest exceeds its release-size budget")
