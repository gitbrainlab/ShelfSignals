#!/usr/bin/env python3
"""Build a bounded, authenticated LOC Sowerby OCR evidence pilot.

The output is intentionally written beneath the ignored Jefferson research
workspace.  It contains machine OCR, source coordinates, and LOC IIIF region
URLs for a stratified three-entry-per-chapter review sample.  It never reads
the permission-gated Monticello/TJF transcription and must only be served by
the authenticated private-review gateway.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
import datetime as dt
import hashlib
import json
import os
from pathlib import Path
import re
import sys
from typing import Any, Mapping, Sequence

from jefferson_private_ocr_contract import (
    PrivateOcrContractError,
    SCHEMA,
    validate_manifest,
    validate_manifest_size,
)


SCRIPT_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = SCRIPT_DIR.parent
DEFAULT_CACHE_ROOT = REPOSITORY_ROOT / "research/jefferson/work/cache/loc_sowerby_ocr_v1"
DEFAULT_DATA_ROOT = REPOSITORY_ROOT / "research/jefferson/work/data"
DEFAULT_ITEM_JSON = REPOSITORY_ROOT / "research/jefferson/work/cache/loc_sowerby/item.json"
DEFAULT_CORE = REPOSITORY_ROOT / "docs/data/collections/jefferson/historical/catalog-core.json"
DEFAULT_INSIGHTS = REPOSITORY_ROOT / "docs/data/collections/jefferson/historical/insights.json"
DEFAULT_OUTPUT_ROOT = REPOSITORY_ROOT / "research/jefferson/work/private-ocr/latest"
APPROVED_OUTPUT_ROOT = REPOSITORY_ROOT / "research/jefferson/work/private-ocr"

SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
SAFE_RECORD_RE = re.compile(r"^jefferson-sowerby-(\d{1,4})$")
EXPECTED_CHAPTERS = 44
SAMPLE_PER_CHAPTER = 3
MAX_REGIONS_PER_ENTRY = 3
MAX_TRANSCRIPT_CHARACTERS = 12_000


class PrivateOcrError(RuntimeError):
    """Raised when a private OCR bundle cannot be built safely."""


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, allow_nan=False, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return f"sha256:{digest.hexdigest()}"


def validate_timestamp(value: str) -> str:
    if not UTC_RE.fullmatch(value):
        raise PrivateOcrError("generated_at must be a whole-second UTC timestamp")
    try:
        dt.datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as error:
        raise PrivateOcrError("generated_at is not a valid UTC timestamp") from error
    return value


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise PrivateOcrError(f"Unable to read JSON {path}: {error}") from error


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    try:
        with path.open(encoding="utf-8") as handle:
            for number, line in enumerate(handle, start=1):
                if line.strip():
                    value = json.loads(line)
                    if not isinstance(value, dict):
                        raise PrivateOcrError(f"JSONL row {number} in {path} is not an object")
                    rows.append(value)
    except (OSError, json.JSONDecodeError) as error:
        raise PrivateOcrError(f"Unable to read JSONL {path}: {error}") from error
    return rows


def resolved_path(path: Path, label: str, *, must_exist: bool) -> Path:
    try:
        return path.resolve(strict=must_exist)
    except OSError as error:
        raise PrivateOcrError(f"Unable to resolve {label} {path}: {error}") from error


def paths_overlap(first: Path, second: Path) -> bool:
    return first == second or first in second.parents or second in first.parents


def validate_output_boundary(output_root: Path, source_paths: Mapping[str, Path]) -> Path:
    """Keep private OCR derivatives out of tracked or public repository paths."""

    output = resolved_path(output_root, "private OCR output", must_exist=False)
    repository = resolved_path(REPOSITORY_ROOT, "repository root", must_exist=True)
    approved = resolved_path(APPROVED_OUTPUT_ROOT, "approved private OCR output", must_exist=False)
    if output.is_relative_to(repository) and not output.is_relative_to(approved):
        raise PrivateOcrError(
            "Private OCR output inside the repository must remain beneath the git-ignored private-ocr workspace"
        )
    for label, source_path in source_paths.items():
        source = resolved_path(source_path, label, must_exist=True)
        if paths_overlap(output, source):
            raise PrivateOcrError(f"Private OCR output cannot overlap {label}: {output}")
    return output


def atomic_write(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    try:
        temporary.write_bytes(body)
        temporary.chmod(0o600)
        os.replace(temporary, path)
    except OSError as error:
        try:
            temporary.unlink(missing_ok=True)
        except OSError:
            pass
        raise PrivateOcrError(f"Unable to write private OCR bundle {path}: {error}") from error


def prepare_private_output(output_root: Path, target: Path) -> None:
    target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    output_root.chmod(0o700)
    current = target.parent
    while current.is_relative_to(output_root):
        current.chmod(0o700)
        if current == output_root:
            break
        current = current.parent


def load_core_records(path: Path) -> dict[int, dict[str, Any]]:
    raw = load_json(path)
    if not isinstance(raw, dict) or not isinstance(raw.get("contract"), dict) or not isinstance(raw.get("items"), list):
        raise PrivateOcrError("Historical core projection is malformed")
    fields = raw["contract"].get("core_fields")
    if not isinstance(fields, list) or len(fields) < 10:
        raise PrivateOcrError("Historical core projection has no usable field contract")
    records: dict[int, dict[str, Any]] = {}
    for compact in raw["items"]:
        if not isinstance(compact, list) or len(compact) != len(fields):
            raise PrivateOcrError("Historical core projection contains an invalid compact row")
        record = dict(zip(fields, compact))
        match = SAFE_RECORD_RE.fullmatch(str(record.get("id") or ""))
        if not match or str(record.get("sowerby_identifier") or "") != match.group(1):
            raise PrivateOcrError("Historical core projection contains an invalid record identity")
        serial = int(match.group(1))
        if serial in records:
            raise PrivateOcrError("Historical core projection contains a duplicate Sowerby number")
        records[serial] = record
    return records


def _jpeg_url(group: Sequence[Mapping[str, Any]]) -> str:
    candidates = [
        item for item in group
        if isinstance(item, Mapping) and item.get("mimetype") == "image/jpeg" and str(item.get("url") or "").startswith("https://tile.loc.gov/")
    ]
    if not candidates:
        raise PrivateOcrError("LOC item resource has no safe JPEG representation")
    candidates.sort(key=lambda item: (int(item.get("height") or 0), int(item.get("width") or 0)))
    return str(candidates[-1]["url"])


def iiif_service_from_group(group: Sequence[Mapping[str, Any]]) -> tuple[str, str]:
    information = next((str(item.get("info")) for item in group if isinstance(item, Mapping) and item.get("info")), "")
    if information.startswith("https://tile.loc.gov/image-services/iiif/") and information.endswith("/info.json"):
        service = information.removesuffix("/info.json")
    else:
        jpeg = _jpeg_url(group)
        marker = "/full/"
        if marker not in jpeg:
            raise PrivateOcrError("LOC JPEG URL is not a recognizable IIIF image URL")
        service = jpeg.split(marker, 1)[0]
    return service, _jpeg_url(group)


def load_iiif_pages(item_path: Path) -> dict[tuple[int, int], tuple[str, str]]:
    raw = load_json(item_path)
    resources = raw.get("resources") if isinstance(raw, dict) else None
    if not isinstance(resources, list) or len(resources) != 5:
        raise PrivateOcrError("LOC item JSON does not contain the five expected volume resources")
    pages: dict[tuple[int, int], tuple[str, str]] = {}
    for volume, resource in enumerate(resources, start=1):
        groups = resource.get("files") if isinstance(resource, dict) else None
        if not isinstance(groups, list) or not groups:
            raise PrivateOcrError(f"LOC volume {volume} has no page-image groups")
        for page, group in enumerate(groups, start=1):
            if not isinstance(group, list):
                raise PrivateOcrError(f"LOC volume {volume} page {page} has an invalid image group")
            pages[(volume, page)] = iiif_service_from_group(group)
    return pages


def percent_region(lines: Sequence[Any], *, padding_percent: float = 1.5) -> dict[str, float]:
    if not lines:
        raise PrivateOcrError("Cannot create a source region without OCR lines")
    width = max(int(line.page_width) for line in lines)
    height = max(int(line.page_height) for line in lines)
    if width <= 0 or height <= 0:
        raise PrivateOcrError("OCR lines have invalid page dimensions")
    left = max(0.0, min(float(line.left) for line in lines) / width * 100 - padding_percent)
    top = max(0.0, min(float(line.top) for line in lines) / height * 100 - padding_percent)
    right = min(100.0, max(float(line.right) for line in lines) / width * 100 + padding_percent)
    bottom = min(100.0, max(float(line.bottom) for line in lines) / height * 100 + padding_percent)
    return {
        "x": round(left, 3),
        "y": round(top, 3),
        "width": round(max(0.1, right - left), 3),
        "height": round(max(0.1, bottom - top), 3),
    }


def iiif_region_url(service: str, region: Mapping[str, float]) -> str:
    coordinates = ",".join(f"{float(region[key]):.3f}".rstrip("0").rstrip(".") for key in ("x", "y", "width", "height"))
    return f"{service}/pct:{coordinates}/1000,/0/default.jpg"


def mean_confidence(lines: Sequence[Any]) -> float:
    values = [float(line.confidence) for line in lines if float(line.confidence) >= 0]
    return round(sum(values) / len(values), 3) if values else 0.0


def normalized_transcript(lines: Sequence[Any]) -> str:
    text = "\n".join(str(line.text or "").strip() for line in lines if str(line.text or "").strip())
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text[:MAX_TRANSCRIPT_CHARACTERS]


def event_contexts(insights: Mapping[str, Any], record_id: str, chapter: int) -> list[dict[str, Any]]:
    direct = {
        relation["event_id"]: relation
        for relation in insights.get("record_relations", [])
        if relation.get("record_id") == record_id
    }
    contexts: list[dict[str, Any]] = []
    for event in insights.get("events", []):
        group = next((group for group in event.get("chapter_groups", []) if chapter in group.get("chapters", [])), None)
        if not group:
            continue
        relation = direct.get(event.get("id"))
        contexts.append({
            "event_id": event["id"],
            "title": event["short_title"],
            "date_label": event["date_label"],
            "relationship": relation.get("relationship") if relation else group["relationship"],
            "context_score": int(relation.get("connection_score") if relation else group["context_score"]),
            "direct_relation": bool(relation),
            "event_use_status": relation.get("event_use_status") if relation else "not_established",
            "use_confidence_score": relation.get("use_confidence_score") if relation else None,
        })
    return sorted(contexts, key=lambda row: (not row["direct_relation"], -row["context_score"], row["event_id"]))


def candidate_order(
    records: Mapping[int, Mapping[str, Any]],
    entries: Mapping[int, Mapping[str, Any]],
    resolved: Mapping[int, Any],
    direct_record_ids: set[str],
    exact_boundary: Any,
) -> dict[int, list[int]]:
    chapters: dict[int, list[int]] = defaultdict(list)
    for serial, record in records.items():
        entry = entries.get(serial)
        marker = resolved.get(serial)
        chapter = record.get("chapter_number")
        if not entry or not marker or not isinstance(chapter, int) or not exact_boundary(serial, marker, resolved):
            continue
        chapters[chapter].append(serial)
    for serials in chapters.values():
        serials.sort(key=lambda serial: (
            str(records[serial]["id"]) not in direct_record_ids,
            entries[serial].get("title_status") != "source_backed",
            -float(entries[serial].get("ocr", {}).get("title_line_confidence") or 0),
            -float(entries[serial].get("ocr", {}).get("marker_line_confidence") or 0),
            serial,
        ))
    return chapters


def build_bundle(
    *,
    cache_root: Path,
    data_root: Path,
    item_json: Path,
    core_path: Path,
    insights_path: Path,
    generated_at: str,
) -> dict[str, Any]:
    generated_at = validate_timestamp(generated_at)
    sys.path.insert(0, str(SCRIPT_DIR))
    try:
        import extract_jefferson_sowerby_loc_ocr as ocr
    except ImportError as error:
        raise PrivateOcrError(f"Unable to load the LOC OCR pipeline: {error}") from error

    manifest_path = data_root / "sowerby_loc_ocr_manifest.json"
    ocr_manifest = load_json(manifest_path)
    counts = ocr_manifest.get("counts") if isinstance(ocr_manifest, dict) else None
    if not isinstance(counts, dict) or counts.get("selected_source_backed_identifier_count") != 4928:
        raise PrivateOcrError("LOC OCR manifest does not describe the expected 4,928-entry source corpus")
    source_identity = str(ocr_manifest.get("source_identity_sha256") or "")
    if not SHA256_RE.fullmatch(source_identity):
        raise PrivateOcrError("LOC OCR manifest has no valid source identity")

    active = load_json(cache_root / "active.json")
    if not isinstance(active, dict) or set(active) != {"schema", "generation", "source_identity_sha256"}:
        raise PrivateOcrError("The active LOC OCR generation pointer is malformed")
    generation = str(active.get("generation") or "")
    if (
        active.get("schema") != "shelfsignals-jefferson-loc-ocr-active@1"
        or not re.fullmatch(r"[0-9a-f]{20}", generation)
        or active.get("source_identity_sha256") != source_identity
        or not source_identity.removeprefix("sha256:").startswith(generation)
    ):
        raise PrivateOcrError("The active LOC OCR generation identity does not match its source manifest")
    generations_root = resolved_path(cache_root / "generations", "LOC OCR generations", must_exist=True)
    generation_root = resolved_path(generations_root / generation, "active LOC OCR generation", must_exist=True)
    if not generation_root.is_dir() or not generation_root.is_relative_to(generations_root):
        raise PrivateOcrError("The active LOC OCR generation escapes its cache boundary")
    generation_identity = load_json(generation_root / "generation.json")
    if (
        not isinstance(generation_identity, dict)
        or set(generation_identity) != {"schema", "generation", "source_identity_sha256", "generated_at"}
        or generation_identity.get("schema") != "shelfsignals-jefferson-loc-ocr-generation@1"
        or generation_identity.get("generation") != generation
        or generation_identity.get("source_identity_sha256") != source_identity
    ):
        raise PrivateOcrError("The active LOC OCR generation manifest is inconsistent")
    validate_timestamp(str(generation_identity.get("generated_at") or ""))

    entries_list = load_jsonl(data_root / "sowerby_loc_ocr_entries.jsonl")
    entries = {int(row["sowerby_number"]): row for row in entries_list}
    if len(entries) != 4928:
        raise PrivateOcrError("LOC OCR entry set is incomplete or contains duplicate identifiers")

    records = load_core_records(core_path)
    if set(records) != set(entries):
        raise PrivateOcrError("Historical browser projection and LOC OCR entry identities do not match")
    insights = load_json(insights_path)
    if not isinstance(insights, dict) or insights.get("collection_id") != "jefferson" or insights.get("corpus_id") != "historical":
        raise PrivateOcrError("Jefferson insight graph is unavailable or has the wrong identity")
    direct_ids = {str(row.get("record_id") or "") for row in insights.get("record_relations", [])}

    sidecars = ocr._all_cached_sidecars(generation_root, "base")
    for dpi, psm in ocr.FALLBACK_VARIANTS:
        sidecars.extend(ocr._all_cached_sidecars(generation_root, f"fallback-dpi{dpi}-psm{psm}"))
    resolved, _ = ocr.resolve_candidates(ocr.marker_candidates(generation_root, sidecars))
    pages = load_iiif_pages(item_json)
    candidates = candidate_order(records, entries, resolved, direct_ids, ocr.has_exact_title_boundary)
    if sorted(candidates) != list(range(1, EXPECTED_CHAPTERS + 1)):
        raise PrivateOcrError("OCR pilot candidates do not cover all 44 historical chapters")

    selected: list[dict[str, Any]] = []
    selected_ids: set[str] = set()
    for chapter in range(1, EXPECTED_CHAPTERS + 1):
        chapter_rows: list[dict[str, Any]] = []
        for serial in candidates[chapter]:
            marker = resolved[serial]
            lines = ocr.lines_for_marker(serial, marker, resolved, generation_root)
            transcript = normalized_transcript(lines)
            if len(transcript) < 40:
                continue
            by_page: dict[int, list[Any]] = defaultdict(list)
            for line in lines:
                by_page[int(line.pdf_page)].append(line)
            regions: list[dict[str, Any]] = []
            for page, page_lines in sorted(by_page.items())[:MAX_REGIONS_PER_ENTRY]:
                service, full_page_url = pages.get((marker.volume, page), ("", ""))
                if not service or not full_page_url:
                    raise PrivateOcrError(f"LOC IIIF source is missing for volume {marker.volume}, page {page}")
                region = percent_region(page_lines)
                regions.append({
                    "pdf_page": page,
                    "region_pct": region,
                    "image_url": iiif_region_url(service, region),
                    "full_page_image_url": full_page_url,
                    "line_count": len(page_lines),
                    "mean_confidence": mean_confidence(page_lines),
                })
            record = records[serial]
            entry = entries[serial]
            record_id = str(record["id"])
            row = {
                "record_id": record_id,
                "sowerby_number": serial,
                "title": str(record.get("title") or ""),
                "title_status": str(record.get("title_status") or "not_established"),
                "faculty": str(record.get("faculty") or ""),
                "chapter_number": chapter,
                "chapter_label": str(record.get("chapter_label") or ""),
                "volume": int(marker.volume),
                "terminal_pdf_page": int(marker.page),
                "pdf_url": str(entry.get("pdf_url") or ""),
                "section": {
                    "type": "sowerby_entry_block",
                    "classification_status": "machine_detected_unreviewed",
                    "transcript": transcript,
                    "transcript_truncated": len(transcript) >= MAX_TRANSCRIPT_CHARACTERS,
                    "line_count": len(lines),
                    "mean_confidence": mean_confidence(lines),
                    "marker_confidence": round(float(entry.get("ocr", {}).get("marker_line_confidence") or 0), 3),
                    "title_confidence": round(float(entry.get("ocr", {}).get("title_line_confidence") or 0), 3),
                },
                "snapshots": regions,
                "event_contexts": event_contexts(insights, record_id, chapter),
            }
            chapter_rows.append(row)
            selected_ids.add(record_id)
            if len(chapter_rows) == SAMPLE_PER_CHAPTER:
                break
        if len(chapter_rows) != SAMPLE_PER_CHAPTER:
            raise PrivateOcrError(f"Chapter {chapter} supplied only {len(chapter_rows)} usable OCR pilot entries")
        selected.extend(chapter_rows)

    if not direct_ids.issubset(selected_ids):
        missing = sorted(direct_ids - selected_ids)
        raise PrivateOcrError(f"OCR pilot omitted direct documentary graph records: {missing}")
    if len(selected) != EXPECTED_CHAPTERS * SAMPLE_PER_CHAPTER:
        raise PrivateOcrError("OCR pilot has an unexpected selected-entry count")

    section_regions = sum(len(row["snapshots"]) for row in selected)
    bundle = {
        "schema": SCHEMA,
        "collection_id": "jefferson",
        "corpus_id": "historical",
        "audience": "authenticated_review",
        "generated_at": generated_at,
        "source": {
            "authority": "Library of Congress",
            "item_url": str(ocr_manifest.get("loc_item_url") or ""),
            "rights_statement_url": str(ocr_manifest.get("rights_statement_url") or ""),
            "rights_clearance": str(ocr_manifest.get("rights_clearance") or ""),
            "source_identity_sha256": str(ocr_manifest.get("source_identity_sha256") or ""),
            "ocr_manifest_sha256": sha256_file(manifest_path),
            "historical_core_sha256": sha256_file(core_path),
            "insight_graph_sha256": sha256_file(insights_path),
        },
        "methodology": {
            "selection": "Three machine-readable, page-resolved entries per Sowerby chapter; direct documentary graph records are prioritized and required.",
            "sectioning": "Each section is the machine-detected OCR block between consecutive source-backed Sowerby entry terminators. It may contain bibliographic description, annotation, references, or copy notes and is not yet semantically subdivided.",
            "visual_evidence": "Each inline snapshot is a bounded region requested from the official Library of Congress IIIF image service using OCR coordinates.",
            "confidence": "OCR and marker confidence describe transcription mechanics, not bibliographic truth or evidence that Jefferson read a work.",
            "use_boundary": "Life-event context remains separate from documented record-level interaction. Unscored contextual links are not use claims.",
        },
        "coverage": {
            "historical_entries": int(counts["selected_source_backed_identifier_count"]),
            "page_resolved_entries": int(counts["page_resolved_identifier_count"]),
            "pilot_entries": len(selected),
            "chapters": EXPECTED_CHAPTERS,
            "entries_per_chapter": SAMPLE_PER_CHAPTER,
            "section_regions": section_regions,
            "source_backed_titles": sum(row["title_status"] == "source_backed" for row in selected),
            "direct_documentary_records": len(direct_ids),
        },
        "entries": selected,
    }
    for value in bundle["source"].values():
        if isinstance(value, str) and value.startswith("sha256:") and not SHA256_RE.fullmatch(value):
            raise PrivateOcrError("Private OCR source contains an invalid SHA-256 digest")
    try:
        validate_manifest(bundle)
        validate_manifest_size(json_bytes(bundle))
    except PrivateOcrContractError as error:
        raise PrivateOcrError(f"Generated private OCR manifest failed its release contract: {error}") from error
    return bundle


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT)
    parser.add_argument("--data-root", type=Path, default=DEFAULT_DATA_ROOT)
    parser.add_argument("--item-json", type=Path, default=DEFAULT_ITEM_JSON)
    parser.add_argument("--core", type=Path, default=DEFAULT_CORE)
    parser.add_argument("--insights", type=Path, default=DEFAULT_INSIGHTS)
    parser.add_argument("--output-root", type=Path, default=DEFAULT_OUTPUT_ROOT)
    parser.add_argument("--generated-at", required=True, help="Deterministic build timestamp, YYYY-MM-DDTHH:MM:SSZ")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        output_root = validate_output_boundary(args.output_root, {
            "LOC OCR cache": args.cache_root,
            "LOC OCR data": args.data_root,
            "LOC item metadata": args.item_json,
            "historical core projection": args.core,
            "historical insight graph": args.insights,
        })
        bundle = build_bundle(
            cache_root=args.cache_root,
            data_root=args.data_root,
            item_json=args.item_json,
            core_path=args.core,
            insights_path=args.insights,
            generated_at=args.generated_at,
        )
        target = output_root / "data/collections/jefferson/ocr-review.json"
        prepare_private_output(output_root, target)
        atomic_write(target, json_bytes(bundle))
    except PrivateOcrError as error:
        print(f"error: {error}", file=sys.stderr)
        return 2
    print(json.dumps({
        "output": str(target),
        "pilot_entries": bundle["coverage"]["pilot_entries"],
        "chapters": bundle["coverage"]["chapters"],
        "section_regions": bundle["coverage"]["section_regions"],
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
