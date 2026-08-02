#!/usr/bin/env python3
"""Build the deterministic Jefferson historical browser projections.

Public display text comes only from the official Library of Congress Sowerby
scan OCR (or a future LOC-authorized export).  The restricted TJF/Monticello
research snapshot is used solely to validate entry-to-chapter structure; none
of its title, author, imprint, annotation, URL, or prose fields may enter the
browser package.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import unicodedata
from typing import Any, Iterable, Mapping, Sequence
from urllib.parse import urlparse


SCRIPT_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = SCRIPT_DIR.parent
DEFAULT_SOURCE_DIR = REPOSITORY_ROOT / "research/jefferson/work/data"
DEFAULT_OUTPUT_DIR = REPOSITORY_ROOT / "docs/data/collections/jefferson/historical"
DEFAULT_CHAPTER_RANGES = REPOSITORY_ROOT / "research/jefferson/loc-sowerby-chapter-ranges.json"

LOC_ITEM_URL = "https://www.loc.gov/item/52060000/"
PUBLICATION_BASES = {"loc_scan_ocr_factual_extraction", "loc_authorized_export"}
EXPECTED_MAX_SERIAL = 4931
EXPECTED_GAPS = (2323, 4707, 4708)
EXPECTED_RECORD_COUNT = 4928
SHARD_COUNT = 64
CORE_DECODED_BUDGET = 1_250_000
CORE_GZIP_BUDGET = 350_000
SEARCH_DECODED_BUDGET = 3_500_000
SEARCH_GZIP_BUDGET = 900_000
DETAIL_SHARD_DECODED_BUDGET = 600_000
DETAIL_SHARD_GZIP_BUDGET = 150_000

CORE_SCHEMA = "shelfsignals-browser-historical@1"
SEARCH_SCHEMA = "shelfsignals-historical-search@1"
DETAIL_SCHEMA = "shelfsignals-historical-detail-shard@1"
DETAIL_INDEX_SCHEMA = "shelfsignals-historical-detail-index@1"
VALIDATION_SCHEMA = "shelfsignals-jefferson-historical-validation@1"

CORE_FIELDS = [
    "id", "entity_type", "sowerby_identifier", "title", "title_status", "creators", "date",
    "material_type", "formats", "source_url", "faculty", "chapter_number", "chapter_label",
    "orders", "evidence_status", "detail_shard",
]
SEARCH_FIELDS = ["id", "search_text"]
DETAIL_FIELDS = [
    "id", "entity_type", "sowerby_identifier", "full_title", "title_status", "alternative_titles",
    "creators", "contributors", "publication", "languages", "subjects", "formats", "material_type",
    "faculty", "chapter_number", "chapter_label", "source_url", "relationship_to_jefferson",
    "ownership_or_reconstruction_status", "links", "assertions", "source",
]

OCR_FILES = {
    "entries": "sowerby_loc_ocr_entries.jsonl",
    "unresolved": "sowerby_loc_ocr_unresolved.jsonl",
    "pages": "sowerby_loc_ocr_pages.jsonl",
    "validation": "sowerby_loc_ocr_validation.json",
    "manifest": "sowerby_loc_ocr_manifest.json",
}
STRUCTURE_FILES = {
    "entries": "sowerby_entries.jsonl",
    "exceptions": "sowerby_entry_exceptions.jsonl",
    "pages": "sowerby_source_pages.jsonl",
    "validation": "sowerby_validation.json",
    "manifest": "sowerby_manifest.json",
}
LOC_REFERENCE_FILE = "loc_sowerby_reference.json"
SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
SAFE_ID_RE = re.compile(r"^[A-Za-z0-9._~-]+$")
RESTRICTED_TEXT_RE = re.compile(
    r"(?:https?://)?(?:www\.|tjlibraries\.)?monticello\.org|thomas jefferson foundation",
    re.I,
)
FORBIDDEN_PUBLIC_KEYS = {
    "annotations", "annotation", "notes", "note", "bibliography", "bibliographies", "identifier_evidence",
    "unit_statement", "call_number_scope", "source_html_ids", "source_container_html_ids",
    "parent_source_html_ids", "terms", "service", "barcode", "staffOnly", "staff_only",
}
ASSERTION_FIELDS = frozenset({"field", "status", "value", "source", "source_url", "evidence_sha256", "as_of"})


class BuildError(RuntimeError):
    """Raised when a source or public projection contract fails closed."""


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


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


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BuildError(f"Unable to read JSON {path.name}: {error}") from error


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8") as handle:
            for line_number, line in enumerate(handle, 1):
                if not line.strip():
                    continue
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise BuildError(f"{path.name}:{line_number} is not an object")
                result.append(value)
    except (OSError, json.JSONDecodeError) as error:
        raise BuildError(f"Unable to read JSONL {path.name}: {error}") from error
    return result


def require_object(value: Any, label: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise BuildError(f"{label} must be an object")
    return value


def string_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise BuildError(f"{label} must be a string array")
    return [clean_text(item) for item in value if clean_text(item)]


def validate_loc_url(value: Any, label: str) -> str:
    url = clean_text(value)
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or (host != "loc.gov" and not host.endswith(".loc.gov")) or parsed.username or parsed.password:
        raise BuildError(f"{label} must be an approved loc.gov HTTPS URL")
    return url


def validate_assertion(value: Any, label: str) -> None:
    assertion = require_object(value, label)
    if set(assertion) != ASSERTION_FIELDS:
        raise BuildError(f"{label} fields are incomplete or unknown")
    if not re.fullmatch(r"[a-z][a-z0-9_]*", clean_text(assertion.get("field"))):
        raise BuildError(f"{label} field name is invalid")
    if not clean_text(assertion.get("status")) or not isinstance(assertion.get("value"), str):
        raise BuildError(f"{label} status/value is invalid")
    if clean_text(assertion.get("source")) != "Library of Congress Sowerby scan":
        raise BuildError(f"{label} source label is invalid")
    validate_loc_url(assertion.get("source_url"), f"{label} source URL")
    if not SHA256_RE.fullmatch(clean_text(assertion.get("evidence_sha256"))):
        raise BuildError(f"{label} evidence hash is invalid")
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", clean_text(assertion.get("as_of"))):
        raise BuildError(f"{label} as-of date is invalid")


def expected_numbers() -> list[int]:
    gaps = set(EXPECTED_GAPS)
    return [number for number in range(1, EXPECTED_MAX_SERIAL + 1) if number not in gaps]


def stable_shard(value: str, shard_count: int = SHARD_COUNT) -> int:
    hash_value = 2166136261
    for character in value:
        hash_value ^= ord(character)
        hash_value = (hash_value * 16777619) & 0xFFFFFFFF
    return hash_value % shard_count


def sort_key(value: str) -> str:
    decomposed = unicodedata.normalize("NFKD", value).casefold()
    return " ".join(re.findall(r"[a-z0-9]+", decomposed))


def _validate_hashed_outputs(source_dir: Path, manifest: Mapping[str, Any], files: Mapping[str, str]) -> dict[str, Any]:
    outputs = require_object(manifest.get("outputs"), "Source manifest outputs")
    result: dict[str, Any] = {}
    for key, filename in files.items():
        if key == "manifest":
            continue
        path = source_dir / filename
        expected = require_object(outputs.get(filename), f"Source manifest output {filename}")
        actual = {"bytes": path.stat().st_size if path.is_file() else -1, "sha256": sha256_file(path) if path.is_file() else ""}
        if actual != expected:
            raise BuildError(f"Source hash/size mismatch for {filename}")
        result[key] = {"file": filename, **actual}
    return result


def load_ocr_source(source_dir: Path) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any], dict[str, Any]]:
    manifest = require_object(load_json(source_dir / OCR_FILES["manifest"]), "LOC OCR manifest")
    validation = require_object(load_json(source_dir / OCR_FILES["validation"]), "LOC OCR validation")
    if manifest.get("schema") != "shelfsignals-jefferson-loc-ocr-package@1" or manifest.get("authority") != "Library of Congress":
        raise BuildError("LOC OCR manifest identity is invalid")
    if manifest.get("publication_basis") not in PUBLICATION_BASES:
        raise BuildError("LOC OCR publication basis is not approved")
    generated_at = clean_text(manifest.get("generated_at"))
    if not UTC_RE.fullmatch(generated_at):
        raise BuildError("LOC OCR manifest has no stable whole-second UTC timestamp")
    rights_url = validate_loc_url(manifest.get("rights_statement_url"), "LOC rights statement")
    rights_hash = clean_text(manifest.get("rights_statement_sha256"))
    if not SHA256_RE.fullmatch(rights_hash) or "not granted" not in clean_text(manifest.get("rights_clearance")).casefold():
        raise BuildError("LOC OCR rights evidence is incomplete or implies clearance")
    hashes = _validate_hashed_outputs(source_dir, manifest, OCR_FILES)
    if validation.get("schema") != "shelfsignals-jefferson-loc-ocr-validation@1":
        raise BuildError("LOC OCR validation schema is invalid")
    checks = require_object(validation.get("checks"), "LOC OCR validation checks")
    required_checks = (
        "monticello_text_was_not_read_or_copied",
        "no_gap_rows_were_invented",
        "selected_identifiers_are_unique",
        "full_base_page_coverage",
        "complete_aggregate_spine_identifier_coverage",
    )
    failed_checks = [field for field in required_checks if checks.get(field) is not True]
    if failed_checks:
        raise BuildError(f"LOC OCR validation failed required checks: {failed_checks}")
    counts = require_object(validation.get("counts"), "LOC OCR validation counts")
    if counts.get("selected_source_backed_identifier_count") != EXPECTED_RECORD_COUNT:
        raise BuildError("LOC OCR validation does not attest the exact aggregate spine count")
    entries = load_jsonl(source_dir / OCR_FILES["entries"])
    if len(entries) != EXPECTED_RECORD_COUNT:
        raise BuildError(f"LOC OCR normalized spine must contain exactly {EXPECTED_RECORD_COUNT} entries")
    return entries, manifest, validation, hashes


def _private_structure_equality_qa(
    source_dir: Path,
    public_structure: Mapping[int, Mapping[str, Any]],
) -> None:
    """Cross-check ranges without making the restricted source public evidence."""

    manifest = require_object(load_json(source_dir / STRUCTURE_FILES["manifest"]), "Private structure manifest")
    validation = require_object(load_json(source_dir / STRUCTURE_FILES["validation"]), "Private structure validation")
    _validate_hashed_outputs(source_dir, manifest, STRUCTURE_FILES)
    if manifest.get("publication_status") != "research-only until Thomas Jefferson Foundation reuse permission is recorded":
        raise BuildError("Private structure source status changed unexpectedly")
    if manifest.get("terms_review_is_publication_permission") is not False or manifest.get("factual_core_only") is not True:
        raise BuildError("Private structure source cannot be treated as publication permission")
    if validation.get("all_invariants_passed") is not True or validation.get("source_gap_placeholder_numbers") != list(EXPECTED_GAPS):
        raise BuildError("Private structural numbering validation failed")
    rows = load_jsonl(source_dir / STRUCTURE_FILES["entries"])
    if len(rows) != EXPECTED_MAX_SERIAL:
        raise BuildError("Private structural spine must retain exactly 4,931 positions")
    for position, row in enumerate(rows, 1):
        if row.get("sowerby_number") != position or row.get("historical_order") != position:
            raise BuildError(f"Private structural spine is out of order at {position}")
        if position in EXPECTED_GAPS:
            if row.get("entity_type") != "sowerby_entry_gap_placeholder":
                raise BuildError(f"Expected LOC-confirmed gap is not a placeholder: {position}")
            continue
        if row.get("entity_type") != "sowerby_entry":
            raise BuildError(f"Source-backed spine position is not a Sowerby entry: {position}")
        chapter_number = row.get("chapter_number")
        faculty = clean_text(row.get("faculty"))
        if not isinstance(chapter_number, int) or not 1 <= chapter_number <= 44:
            raise BuildError(f"Structural chapter is invalid at Sowerby {position}")
        expected_faculty = "History" if chapter_number <= 15 else "Philosophy" if chapter_number <= 29 else "Fine Arts"
        if faculty != expected_faculty:
            raise BuildError(f"Structural faculty boundary is invalid at Sowerby {position}")
        public = public_structure.get(position)
        if not public or public.get("chapter_number") != chapter_number or public.get("faculty") != faculty:
            raise BuildError(f"Private equality QA disagrees with LOC scan-audited range at Sowerby {position}")


def _chapter_boundary_evidence_sha256(row: Mapping[str, Any]) -> str:
    fields = (
        "chapter_number", "chapter_roman", "faculty", "label", "toc_heading", "scan_heading",
        "start_identifier", "end_identifier", "volume", "heading_pdf_page", "first_marker_pdf_page",
        "first_marker_normalized_identifier", "printed_page", "pdf_url", "pdf_sha256", "source_url",
        "first_marker_source_url", "review_method", "review_status", "heading_page_sidecar_sha256",
        "first_marker_page_sidecar_sha256", "page_render_sha256", "page_ocr_text_sha256",
        "page_ocr_tsv_sha256", "marker_page_render_sha256", "marker_page_ocr_text_sha256",
        "marker_page_ocr_tsv_sha256", "boundary_method", "reviewed_at",
    )
    return sha256_bytes(json_bytes({field: row.get(field) for field in fields}))


def load_structure(
    source_dir: Path,
    chapter_ranges_path: Path = DEFAULT_CHAPTER_RANGES,
) -> tuple[dict[int, dict[str, Any]], dict[int, dict[str, Any]], dict[str, Any]]:
    """Load public hierarchy solely from official LOC scan-audited ranges."""

    reference = require_object(load_json(source_dir / LOC_REFERENCE_FILE), "LOC chapter reference")
    if reference.get("schema") != "shelfsignals-loc-sowerby-reference@1" or reference.get("source", {}).get("authority") != "Library of Congress":
        raise BuildError("LOC chapter reference identity is invalid")
    chapter_rows = reference.get("chapters")
    if not isinstance(chapter_rows, list) or [row.get("chapter_number") for row in chapter_rows] != list(range(1, 45)):
        raise BuildError("LOC chapter reference does not contain chapters 1..44 exactly")
    reference_chapters: dict[int, dict[str, Any]] = {}
    for row in chapter_rows:
        number = row["chapter_number"]
        faculty = "History" if number <= 15 else "Philosophy" if number <= 29 else "Fine Arts"
        heading = clean_text(row.get("heading"))
        if clean_text(row.get("faculty")) != faculty or not heading:
            raise BuildError(f"LOC chapter/faculty evidence is invalid at chapter {number}")
        reference_chapters[number] = {
            "chapter_number": number,
            "chapter_roman": clean_text(row.get("chapter_roman")),
            "faculty": faculty,
            "label": heading,
            "printed_page": row.get("printed_page"),
        }

    artifact = require_object(load_json(Path(chapter_ranges_path)), "LOC scan-audited chapter ranges")
    if artifact.get("schema") != "shelfsignals-loc-sowerby-chapter-ranges@1":
        raise BuildError("LOC chapter-range artifact schema is invalid")
    if artifact.get("authority") != "Library of Congress" or artifact.get("source_item_url") != LOC_ITEM_URL:
        raise BuildError("LOC chapter-range artifact identity is invalid")
    artifact_pdfs = artifact.get("pdfs")
    if not isinstance(artifact_pdfs, list) or [row.get("volume") for row in artifact_pdfs if isinstance(row, dict)] != list(range(1, 6)):
        raise BuildError("LOC chapter-range artifact does not identify all five official PDFs")
    pdfs: dict[int, tuple[str, str]] = {}
    for pdf in artifact_pdfs:
        pdf_url = validate_loc_url(pdf.get("pdf_url"), f"LOC chapter artifact volume {pdf.get('volume')}")
        pdf_sha256 = clean_text(pdf.get("pdf_sha256"))
        if not SHA256_RE.fullmatch(pdf_sha256):
            raise BuildError(f"LOC chapter artifact PDF hash is invalid for volume {pdf.get('volume')}")
        pdfs[pdf["volume"]] = (pdf_url, pdf_sha256)
    range_rows = artifact.get("chapters")
    if not isinstance(range_rows, list) or [row.get("chapter_number") for row in range_rows if isinstance(row, dict)] != list(range(1, 45)):
        raise BuildError("LOC chapter-range artifact does not contain chapters 1..44 exactly")

    page_rows = load_jsonl(source_dir / OCR_FILES["pages"])
    base_pages: dict[tuple[int, int], Mapping[str, Any]] = {}
    for page in page_rows:
        if page.get("variant") != "base":
            continue
        key = (page.get("volume"), page.get("pdf_page"))
        if key in base_pages:
            raise BuildError(f"LOC OCR page evidence is duplicated: {key}")
        base_pages[key] = page

    expected = expected_numbers()
    expected_index = {number: index for index, number in enumerate(expected)}
    structure: dict[int, dict[str, Any]] = {}
    chapters: dict[int, dict[str, Any]] = {}
    prior_end_index = -1
    for row in range_rows:
        number = row["chapter_number"]
        reference_row = reference_chapters[number]
        expected_faculty = "History" if number <= 15 else "Philosophy" if number <= 29 else "Fine Arts"
        if clean_text(row.get("chapter_roman")) != reference_row["chapter_roman"]:
            raise BuildError(f"LOC chapter roman numeral drifted at chapter {number}")
        if clean_text(row.get("faculty")) != expected_faculty or clean_text(row.get("label")) != reference_row["label"]:
            raise BuildError(f"LOC chapter label/faculty drifted at chapter {number}")
        if clean_text(row.get("toc_heading")) != reference_row["label"] or not clean_text(row.get("scan_heading")):
            raise BuildError(f"LOC TOC/scan headings are incomplete at chapter {number}")
        if row.get("printed_page") != reference_row["printed_page"]:
            raise BuildError(f"LOC chapter printed-page evidence drifted at chapter {number}")
        start = row.get("start_identifier")
        end = row.get("end_identifier")
        if start not in expected_index or end not in expected_index or expected_index[start] > expected_index[end]:
            raise BuildError(f"LOC chapter identifier range is invalid at chapter {number}")
        if expected_index[start] != prior_end_index + 1:
            raise BuildError(f"LOC chapter ranges are not contiguous at chapter {number}")
        prior_end_index = expected_index[end]
        volume = row.get("volume")
        pdf_page = row.get("heading_pdf_page")
        page = base_pages.get((volume, pdf_page))
        if not page:
            raise BuildError(f"LOC chapter heading page is absent from hashed OCR evidence at chapter {number}")
        for artifact_field, page_field in (
            ("page_render_sha256", "render_sha256"),
            ("page_ocr_text_sha256", "ocr_text_sha256"),
            ("page_ocr_tsv_sha256", "ocr_tsv_sha256"),
        ):
            if row.get(artifact_field) != page.get(page_field) or not SHA256_RE.fullmatch(clean_text(row.get(artifact_field))):
                raise BuildError(f"LOC chapter page hash drifted at chapter {number}: {artifact_field}")
        source_url = validate_loc_url(row.get("source_url"), f"LOC chapter source {number}")
        if source_url != f"{row.get('pdf_url')}#page={pdf_page}":
            raise BuildError(f"LOC chapter source URL is not the exact heading page at chapter {number}")
        marker_pdf_page = row.get("first_marker_pdf_page")
        marker_page = base_pages.get((volume, marker_pdf_page))
        if not marker_page:
            raise BuildError(f"LOC chapter first-marker page is absent from hashed OCR evidence at chapter {number}")
        for artifact_field, page_field in (
            ("marker_page_render_sha256", "render_sha256"),
            ("marker_page_ocr_text_sha256", "ocr_text_sha256"),
            ("marker_page_ocr_tsv_sha256", "ocr_tsv_sha256"),
        ):
            if row.get(artifact_field) != marker_page.get(page_field) or not SHA256_RE.fullmatch(clean_text(row.get(artifact_field))):
                raise BuildError(f"LOC chapter marker-page hash drifted at chapter {number}: {artifact_field}")
        marker_source_url = validate_loc_url(row.get("first_marker_source_url"), f"LOC chapter first marker {number}")
        if marker_source_url != f"{row.get('pdf_url')}#page={marker_pdf_page}":
            raise BuildError(f"LOC chapter first-marker URL is not exact at chapter {number}")
        for sidecar_field in ("heading_page_sidecar_sha256", "first_marker_page_sidecar_sha256"):
            if not SHA256_RE.fullmatch(clean_text(row.get(sidecar_field))):
                raise BuildError(f"LOC chapter sidecar audit hash is invalid at chapter {number}: {sidecar_field}")
        if row.get("review_method") != "manual_visual_loc_pdf_heading_and_first_entry_boundary" or row.get("review_status") != "verified":
            raise BuildError(f"LOC chapter boundary lacks the required review attestation at chapter {number}")
        if row.get("first_marker_normalized_identifier") != start:
            raise BuildError(f"LOC chapter first-marker identifier drifted at chapter {number}")
        if row.get("boundary_method") != "chapter_heading_plus_first_entry_terminal_marker" or row.get("reviewed_at") != "2026-08-01":
            raise BuildError(f"LOC chapter boundary method/review date is invalid at chapter {number}")
        if not SHA256_RE.fullmatch(clean_text(row.get("pdf_sha256"))):
            raise BuildError(f"LOC chapter PDF hash is invalid at chapter {number}")
        if pdfs.get(volume) != (clean_text(row.get("pdf_url")), clean_text(row.get("pdf_sha256"))):
            raise BuildError(f"LOC chapter PDF identity drifted at chapter {number}")
        evidence_sha256 = clean_text(row.get("evidence_sha256"))
        if evidence_sha256 != _chapter_boundary_evidence_sha256(row):
            raise BuildError(f"LOC chapter boundary evidence hash drifted at chapter {number}")
        chapter = {
            "chapter_number": number,
            "faculty": expected_faculty,
            "label": reference_row["label"],
            "source_url": source_url,
            "evidence_sha256": evidence_sha256,
        }
        chapters[number] = chapter
        for identifier in expected[expected_index[start]: expected_index[end] + 1]:
            if identifier in structure:
                raise BuildError(f"LOC chapter ranges overlap at Sowerby {identifier}")
            structure[identifier] = {"chapter_number": number, "faculty": expected_faculty}
    if prior_end_index != len(expected) - 1 or sorted(structure) != expected:
        raise BuildError("LOC chapter ranges do not partition the exact source-backed spine")

    _private_structure_equality_qa(source_dir, structure)
    return structure, chapters, {
        "loc_chapter_ranges_sha256": sha256_file(Path(chapter_ranges_path)),
        "loc_chapter_reference_sha256": sha256_file(source_dir / LOC_REFERENCE_FILE),
    }


def project_sources(
    ocr_rows: Sequence[Mapping[str, Any]],
    structure: Mapping[int, Mapping[str, Any]],
    chapters: Mapping[int, Mapping[str, Any]],
    manifest: Mapping[str, Any],
) -> list[dict[str, Any]]:
    by_number: dict[int, Mapping[str, Any]] = {}
    for row in ocr_rows:
        number = row.get("sowerby_number")
        if not isinstance(number, int) or number in by_number or number not in structure or number in EXPECTED_GAPS:
            raise BuildError(f"LOC OCR entry identity is invalid or duplicated: {number!r}")
        if row.get("id") != f"jefferson-sowerby-{number}" or row.get("sowerby_identifier") != str(number):
            raise BuildError(f"LOC OCR namespace is invalid at {number}")
        if row.get("authority") != "Library of Congress" or row.get("publication_basis") != manifest.get("publication_basis"):
            raise BuildError(f"LOC OCR provenance is invalid at {number}")
        if row.get("rights_statement_sha256") != manifest.get("rights_statement_sha256"):
            raise BuildError(f"LOC OCR rights evidence drifted at {number}")
        if RESTRICTED_TEXT_RE.search(json.dumps(row, ensure_ascii=False)):
            raise BuildError(f"Restricted transcript identity leaked into LOC OCR row {number}")
        title_status = clean_text(row.get("title_status"))
        title = clean_text(row.get("display_title"))
        if title_status not in {"source_backed", "not_established"} or (title_status == "source_backed") != bool(title):
            raise BuildError(f"LOC OCR title status is inconsistent at {number}")
        identifier_status = clean_text(row.get("identifier_status"))
        if identifier_status == "page_resolved_ocr":
            pdf_page = row.get("pdf_page")
            if not isinstance(pdf_page, int) or pdf_page < 1:
                raise BuildError(f"LOC OCR resolved source has no valid PDF page at {number}")
            source_url = validate_loc_url(f"{row.get('pdf_url')}#page={pdf_page}", f"LOC OCR source {number}")
        elif identifier_status == "aggregate_scan_spine_source_backed":
            source_url = LOC_ITEM_URL
        else:
            raise BuildError(f"LOC OCR identifier status is invalid at {number}")
        evidence_hash = clean_text(row.get("evidence", {}).get("evidence_sha256"))
        if not SHA256_RE.fullmatch(evidence_hash):
            raise BuildError(f"LOC OCR evidence hash is invalid at {number}")
        by_number[number] = row | {"_source_url": source_url, "_evidence_hash": evidence_hash}
    if sorted(by_number) != expected_numbers():
        raise BuildError("LOC OCR spine identifiers are not exactly 1..4931 minus the three source gaps")

    projected: list[dict[str, Any]] = []
    as_of = clean_text(manifest["generated_at"])[:10]
    for source_position, number in enumerate(expected_numbers(), 1):
        row = by_number[number]
        structure_row = structure[number]
        chapter = chapters[structure_row["chapter_number"]]
        title = clean_text(row.get("display_title"))
        title_status = clean_text(row.get("title_status"))
        identifier_status = clean_text(row.get("identifier_status"))
        source_url = row["_source_url"]
        source_label = "Library of Congress Sowerby scan"
        assertions = [
            {
                "field": "title", "status": title_status, "value": title, "source": source_label,
                "source_url": source_url, "evidence_sha256": row["_evidence_hash"], "as_of": as_of,
            },
            {
                "field": "historical_catalog_membership",
                "status": "page_resolved_ocr" if identifier_status == "page_resolved_ocr" else "aggregate_spine_source_backed",
                "value": str(number), "source": source_label, "source_url": source_url,
                "evidence_sha256": row["_evidence_hash"], "as_of": as_of,
            },
            {
                "field": "historical_chapter", "status": "source_backed", "value": str(chapter["chapter_number"]),
                "source": source_label, "source_url": chapter["source_url"],
                "evidence_sha256": chapter["evidence_sha256"], "as_of": as_of,
            },
            {
                "field": "historical_sequence", "status": "source_backed", "value": str(number),
                "source": source_label, "source_url": source_url,
                "evidence_sha256": row["_evidence_hash"], "as_of": as_of,
            },
            {
                "field": "ownership_or_reconstruction_status", "status": "not_established", "value": "",
                "source": source_label, "source_url": source_url,
                "evidence_sha256": row["_evidence_hash"], "as_of": as_of,
            },
        ]
        identifier = str(number)
        browser_id = f"jefferson-sowerby-{identifier}"
        detail = {
            "id": browser_id,
            "entity_type": "sowerby_entry",
            "sowerby_identifier": identifier,
            "full_title": title,
            "title_status": title_status,
            "alternative_titles": [],
            "creators": [],
            "contributors": [],
            "publication": {"date": "", "places": [], "publishers": []},
            "languages": [],
            "subjects": [],
            "formats": [],
            "material_type": "",
            "faculty": chapter["faculty"],
            "chapter_number": chapter["chapter_number"],
            "chapter_label": chapter["label"],
            "source_url": source_url,
            "relationship_to_jefferson": "historical_catalog_membership",
            "ownership_or_reconstruction_status": "not_established",
            "links": {
                "catalog_instances": [], "editions": [], "volumes": [], "physical_copies": [],
                "holdings": [], "digital_objects": [],
            },
            "assertions": assertions,
            "source": {
                "authority": "Library of Congress",
                "publication_basis": manifest["publication_basis"],
                "rights_statement_url": manifest["rights_statement_url"],
                "rights_statement_sha256": manifest["rights_statement_sha256"],
                "sowerby_identifier": identifier,
                "source_url": source_url,
                "record_sha256": row["_evidence_hash"],
                "source_position": source_position,
            },
        }
        projected.append({
            "id": browser_id,
            "number": number,
            "identifier": identifier,
            "identifier_status": identifier_status,
            "title": title,
            "title_status": title_status,
            "source_url": source_url,
            "chapter": chapter,
            "detail_shard": stable_shard(browser_id),
            "detail": [detail[field] for field in DETAIL_FIELDS],
            "search": clean_text(f"Sowerby {identifier} {title} {chapter['faculty']} chapter {chapter['chapter_number']} {chapter['label']}").casefold(),
        })
    title_sorted = sorted(projected, key=lambda row: (row["title_status"] != "source_backed", sort_key(row["title"]), row["number"]))
    for rank, row in enumerate(title_sorted):
        row["title_rank"] = rank
    return projected


def source_identity(projected: Sequence[Mapping[str, Any]], manifest: Mapping[str, Any]) -> dict[str, Any]:
    ids = [str(row["id"]) for row in projected]
    dataset_basis = [
        [row["id"], row["title"], row["title_status"], row["chapter"]["chapter_number"], row["source_url"], row["detail"][-1]["record_sha256"]]
        for row in projected
    ]
    return {
        "collection_id": "jefferson",
        "corpus_id": "historical",
        "authority": "Library of Congress",
        "publication_basis": manifest["publication_basis"],
        "rights_statement_url": manifest["rights_statement_url"],
        "rights_statement_sha256": manifest["rights_statement_sha256"],
        "dataset": "loc_sowerby_scan_ocr_historical_projection.jsonl",
        "dataset_sha256": sha256_bytes(json_bytes(dataset_basis)),
        "record_count": len(projected),
        "id_set_sha256": sha256_bytes(("\n".join(ids) + "\n").encode("utf-8")),
    }


def core_row(row: Mapping[str, Any]) -> list[Any]:
    chapter = row["chapter"]
    values = {
        "id": row["id"], "entity_type": "sowerby_entry", "sowerby_identifier": row["identifier"],
        "title": row["title"], "title_status": row["title_status"], "creators": [], "date": "",
        # Keep the initial projection within budget; exact page evidence is in
        # the lazy detail assertion/source objects.
        "material_type": "", "formats": [], "source_url": LOC_ITEM_URL,
        "faculty": chapter["faculty"], "chapter_number": chapter["chapter_number"], "chapter_label": chapter["label"],
        "orders": {"sowerby": row["source_position"] - 1, "title": row["title_rank"]},
        "evidence_status": (
            "sowerby_entry_page_resolved"
            if row["identifier_status"] == "page_resolved_ocr"
            else "sowerby_entry_aggregate_spine"
        ),
        "detail_shard": row["detail_shard"],
    }
    return [values[field] for field in CORE_FIELDS]


def _walk_keys(value: Any) -> Iterable[str]:
    if isinstance(value, dict):
        for key, nested in value.items():
            yield key
            yield from _walk_keys(nested)
    elif isinstance(value, list):
        for nested in value:
            yield from _walk_keys(nested)


def validate_public(files: Mapping[str, bytes], source: Mapping[str, Any]) -> dict[str, int]:
    decoded: dict[str, Any] = {}
    for path, body in files.items():
        try:
            decoded[path] = json.loads(body)
        except json.JSONDecodeError as error:
            raise BuildError(f"Generated output is invalid JSON: {path}: {error}") from error
        forbidden = sorted(set(_walk_keys(decoded[path])) & FORBIDDEN_PUBLIC_KEYS)
        if forbidden:
            raise BuildError(f"Generated output {path} contains forbidden keys: {forbidden}")
        text = body.decode("utf-8")
        if RESTRICTED_TEXT_RE.search(text) or str(REPOSITORY_ROOT) in text:
            raise BuildError(f"Generated output {path} contains restricted source identity or a local path")
    core = decoded.get("catalog-core.json", {})
    search = decoded.get("catalog-search.json", {})
    index = decoded.get("catalog-details/index.json", {})
    if core.get("source") != source or search.get("source") != source or index.get("source") != source:
        raise BuildError("Historical outputs do not share exact source identity")
    if len(core.get("items") or []) != EXPECTED_RECORD_COUNT or len(search.get("items") or []) != EXPECTED_RECORD_COUNT:
        raise BuildError("Historical core/search counts are incomplete")
    ids = [row[0] for row in core["items"]]
    if len(ids) != len(set(ids)) or ids != [f"jefferson-sowerby-{number}" for number in expected_numbers()]:
        raise BuildError("Historical core IDs are duplicated, missing, or out of Sowerby order")
    if index.get("shard_count") != SHARD_COUNT or len(index.get("shards") or []) != SHARD_COUNT:
        raise BuildError("Historical detail index does not enumerate all shards")
    detail_ids: list[str] = []
    for shard in range(SHARD_COUNT):
        payload = decoded[f"catalog-details/{shard:03d}.json"]
        if payload.get("source") != source or payload.get("shard") != shard:
            raise BuildError(f"Historical detail shard identity failed: {shard}")
        for row in payload.get("items") or []:
            if stable_shard(row[0]) != shard:
                raise BuildError(f"Historical detail is assigned to the wrong shard: {row[0]}")
            if row[18] != "not_established" or any(row[19][field] for field in row[19]):
                raise BuildError(f"Historical detail flattened a modern/copy relation: {row[0]}")
            if not isinstance(row[20], list) or not row[20]:
                raise BuildError(f"Historical detail has no evidence assertions: {row[0]}")
            for index, assertion in enumerate(row[20]):
                validate_assertion(assertion, f"Historical detail {row[0]} assertion {index}")
            detail_ids.append(row[0])
    if sorted(detail_ids) != sorted(ids):
        raise BuildError("Historical details do not cover the exact core ID set")
    core_bytes = len(files["catalog-core.json"])
    core_gzip = len(gzip.compress(files["catalog-core.json"], mtime=0))
    search_bytes = len(files["catalog-search.json"])
    search_gzip = len(gzip.compress(files["catalog-search.json"], mtime=0))
    max_detail = max(len(files[f"catalog-details/{shard:03d}.json"]) for shard in range(SHARD_COUNT))
    max_detail_gzip = max(len(gzip.compress(files[f"catalog-details/{shard:03d}.json"], mtime=0)) for shard in range(SHARD_COUNT))
    budgets = (
        (core_bytes, CORE_DECODED_BUDGET, "core decoded"), (core_gzip, CORE_GZIP_BUDGET, "core gzip"),
        (search_bytes, SEARCH_DECODED_BUDGET, "search decoded"), (search_gzip, SEARCH_GZIP_BUDGET, "search gzip"),
        (max_detail, DETAIL_SHARD_DECODED_BUDGET, "detail shard decoded"),
        (max_detail_gzip, DETAIL_SHARD_GZIP_BUDGET, "detail shard gzip"),
    )
    for actual, budget, label in budgets:
        if actual > budget:
            raise BuildError(f"Historical {label} budget exceeded: {actual} > {budget}")
    return {
        "core_bytes": core_bytes, "core_gzip_bytes": core_gzip,
        "search_bytes": search_bytes, "search_gzip_bytes": search_gzip,
        "max_detail_shard_bytes": max_detail, "max_detail_shard_gzip_bytes": max_detail_gzip,
    }


def build_package(
    source_dir: Path = DEFAULT_SOURCE_DIR,
    chapter_ranges_path: Path = DEFAULT_CHAPTER_RANGES,
) -> dict[str, bytes]:
    source_dir = Path(source_dir)
    ocr_rows, ocr_manifest, ocr_validation, ocr_hashes = load_ocr_source(source_dir)
    structure, chapters, hierarchy_hashes = load_structure(source_dir, chapter_ranges_path)
    projected = project_sources(ocr_rows, structure, chapters, ocr_manifest)
    if len(projected) != EXPECTED_RECORD_COUNT:
        raise BuildError("Projected historical corpus is not exactly 4,928 entries")
    for source_position, row in enumerate(projected, 1):
        row["source_position"] = source_position
    source = source_identity(projected, ocr_manifest)
    generated_at = ocr_manifest["generated_at"]
    shards: list[list[list[Any]]] = [[] for _ in range(SHARD_COUNT)]
    for row in projected:
        shards[row["detail_shard"]].append(row["detail"])
    core = {
        "schema": CORE_SCHEMA,
        "generated_at": generated_at,
        "source": source,
        "numbering": {
            "max_source_serial": EXPECTED_MAX_SERIAL,
            "source_backed_entry_count": EXPECTED_RECORD_COUNT,
            "gaps": [
                {
                    "identifier": str(number), "status": "source_number_absent",
                    "evidence": f"LOC-confirmed non-book source-number gap {number}.", "source_url": LOC_ITEM_URL,
                }
                for number in EXPECTED_GAPS
            ],
        },
        "contract": {
            "core_fields": CORE_FIELDS, "detail_fields": DETAIL_FIELDS, "detail_shard_count": SHARD_COUNT,
            "detail_path_template": "historical/catalog-details/{shard}.json",
            "search_path": "historical/catalog-search.json", "record_id_prefix": "jefferson-sowerby-",
        },
        "items": [core_row(row) for row in projected],
    }
    search = {
        "schema": SEARCH_SCHEMA, "generated_at": generated_at, "source": source,
        "fields": SEARCH_FIELDS, "items": [[row["id"], row["search"]] for row in projected],
    }
    files: dict[str, bytes] = {
        "catalog-core.json": json_bytes(core),
        "catalog-search.json": json_bytes(search),
    }
    for shard, rows in enumerate(shards):
        files[f"catalog-details/{shard:03d}.json"] = json_bytes({
            "schema": DETAIL_SCHEMA, "generated_at": generated_at, "source": source,
            "shard": shard, "shard_count": SHARD_COUNT, "item_count": len(rows),
            "fields": DETAIL_FIELDS, "items": rows,
        })
    index = {
        "schema": DETAIL_INDEX_SCHEMA, "generated_at": generated_at, "source": source,
        "shard_count": SHARD_COUNT, "fields": DETAIL_FIELDS,
        "shards": [
            {
                "shard": shard, "file": f"{shard:03d}.json", "item_count": len(shards[shard]),
                "bytes": len(files[f"catalog-details/{shard:03d}.json"]),
                "sha256": sha256_bytes(files[f"catalog-details/{shard:03d}.json"]),
            }
            for shard in range(SHARD_COUNT)
        ],
    }
    files["catalog-details/index.json"] = json_bytes(index)
    performance = validate_public(files, source)
    title_count = sum(row["title_status"] == "source_backed" for row in projected)
    page_resolved_count = sum(row["identifier_status"] == "page_resolved_ocr" for row in projected)
    aggregate_spine_count = sum(row["identifier_status"] == "aggregate_scan_spine_source_backed" for row in projected)
    if page_resolved_count + aggregate_spine_count != EXPECTED_RECORD_COUNT:
        raise BuildError("Historical identifier evidence levels do not partition the source-backed corpus")
    if page_resolved_count != ocr_validation.get("counts", {}).get("page_resolved_identifier_count"):
        raise BuildError("Historical page-resolved identifier count drifted from OCR validation")
    validation = {
        "schema": VALIDATION_SCHEMA,
        "generated_at": generated_at,
        "collection_id": "jefferson", "corpus_id": "historical", "source": source,
        "source_package": {
            "ocr": ocr_hashes,
            "ocr_source_identity_sha256": ocr_manifest["source_identity_sha256"],
            "ocr_validation_sha256": sha256_file(source_dir / OCR_FILES["validation"]),
            **hierarchy_hashes,
        },
        "counts": {
            "source_backed_entries": EXPECTED_RECORD_COUNT, "max_source_serial": EXPECTED_MAX_SERIAL,
            "source_number_gaps": len(EXPECTED_GAPS), "source_backed_titles": title_count,
            "titles_not_established": EXPECTED_RECORD_COUNT - title_count,
            "page_resolved_identifiers": page_resolved_count,
            "aggregate_spine_identifiers": aggregate_spine_count,
            "chapters": len(chapters), "detail_shards": SHARD_COUNT,
        },
        "checks": {
            "loc_publication_basis_only": True, "loc_rights_evidence_retained": True,
            "restricted_transcript_text_excluded": True, "exact_4928_source_entry_ids": True,
            "source_gaps_excluded_as_records": True, "all_44_chapters_validated": True,
            "faculty_boundaries_validated": True, "title_status_never_synthesizes_source_text": True,
            "modern_catalog_copy_holding_and_digital_links_empty": True,
            "ownership_and_reconstruction_status_not_established": True,
            "identifier_evidence_levels_preserved": True,
            "all_assertions_source_date_and_hash_bound": True, "detail_shards_complete_and_hash_bound": True,
        },
        "performance": {
            **performance,
            "core_decoded_budget_bytes": CORE_DECODED_BUDGET, "core_gzip_budget_bytes": CORE_GZIP_BUDGET,
            "search_decoded_budget_bytes": SEARCH_DECODED_BUDGET, "search_gzip_budget_bytes": SEARCH_GZIP_BUDGET,
            "detail_shard_decoded_budget_bytes": DETAIL_SHARD_DECODED_BUDGET,
            "detail_shard_gzip_budget_bytes": DETAIL_SHARD_GZIP_BUDGET,
        },
        "warnings": [
            "This package represents 4,928 source-backed Sowerby entries, not 4,931 books; serials 2323, 4707, and 4708 are source-number gaps.",
            "Blank titles are explicitly not established; the interface supplies only a visibly qualified fallback label.",
            "OCR-derived titles require bibliographic review. Ownership, survival, replacement, holdings, copy, and digital-object relations are not established.",
            "Page-resolved and aggregate scan-spine identifier evidence remain distinct in the public projection.",
            "LOC item-level rights evidence is retained and does not grant blanket reuse clearance.",
        ],
        "outputs": {
            path: {"bytes": len(body), "sha256": sha256_bytes(body)} for path, body in sorted(files.items())
        },
    }
    files["validation.json"] = json_bytes(validation)
    validate_public(files, source)
    return dict(sorted(files.items()))


def write_package(files: Mapping[str, bytes], output_dir: Path = DEFAULT_OUTPUT_DIR) -> None:
    output_dir = Path(output_dir)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".jefferson-historical-", dir=output_dir.parent))
    try:
        for relative, body in files.items():
            target = staging / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(body)
        output_dir.mkdir(parents=True, exist_ok=True)
        for path in sorted(output_dir.rglob("*"), reverse=True):
            if path.is_file() and path.relative_to(output_dir).as_posix() not in files:
                path.unlink()
        for relative in sorted(files):
            target = output_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staging / relative, target)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def check_package(files: Mapping[str, bytes], output_dir: Path = DEFAULT_OUTPUT_DIR) -> None:
    output_dir = Path(output_dir)
    failures: list[str] = []
    for relative, body in files.items():
        path = output_dir / relative
        if not path.is_file():
            failures.append(f"missing: {relative}")
        elif path.read_bytes() != body:
            failures.append(f"stale: {relative}")
    actual = {path.relative_to(output_dir).as_posix() for path in output_dir.rglob("*") if path.is_file()} if output_dir.is_dir() else set()
    for relative in sorted(actual - set(files)):
        failures.append(f"unexpected: {relative}")
    if failures:
        raise BuildError("Historical browser package check failed:\n- " + "\n- ".join(failures))


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--chapter-ranges", type=Path, default=DEFAULT_CHAPTER_RANGES)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--check", action="store_true")
    mode.add_argument("--self-test", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        first = build_package(args.source_dir, args.chapter_ranges)
        second = build_package(args.source_dir, args.chapter_ranges)
        if first != second:
            raise BuildError("Historical browser package is not deterministic across two builds")
        if args.check:
            check_package(first, args.output_dir)
            action = "checked"
        elif args.self_test:
            action = "validated in memory"
        else:
            write_package(first, args.output_dir)
            action = "wrote"
        print(f"Jefferson historical browser package {action}: {len(first)} files, {sum(map(len, first.values()))} bytes, 4,928 entries")
        return 0
    except BuildError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
