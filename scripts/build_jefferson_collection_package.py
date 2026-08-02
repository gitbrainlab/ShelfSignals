#!/usr/bin/env python3
"""Own the complete two-corpus Jefferson browser package and @2 manifest.

The catalog and historical builders remain independently testable, but this is
the only writer for a public dual-corpus release.  It prevents either builder
from treating the other corpus as an unexpected file and makes the manifest a
deterministic function of both validated packages.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any, Mapping, Sequence

import build_jefferson_browser_package as catalog_builder
import build_jefferson_historical_browser_package as historical_builder


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SOURCE_DIR = REPOSITORY_ROOT / "research/jefferson/work/data"
DEFAULT_OUTPUT_DIR = REPOSITORY_ROOT / "docs/data/collections/jefferson"
DEFAULT_CHAPTER_RANGES = REPOSITORY_ROOT / "research/jefferson/loc-sowerby-chapter-ranges.json"
MANIFEST_SCHEMA = "shelfsignals-collection-manifest@2"
SOURCE_BACKED_ENTRY_COUNT = 4928
HISTORICAL_POSITION_COUNT = 4931
HISTORICAL_VOLUME_COUNT = 6487


class BuildError(RuntimeError):
    """Raised when the aggregate collection package is inconsistent."""


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def decode_json(body: bytes, label: str) -> dict[str, Any]:
    try:
        value = json.loads(body)
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise BuildError(f"{label} is not valid JSON: {error}") from error
    if not isinstance(value, dict):
        raise BuildError(f"{label} must be a JSON object")
    return value


def corpus_copy(copy: Mapping[str, Any]) -> dict[str, str]:
    fields = ("status_label", "introduction", "coverage_statement", "source_label")
    result = {field: str(copy.get(field) or "").strip() for field in fields}
    if any(not value for value in result.values()):
        raise BuildError("Catalog manifest has incomplete corpus copy")
    return result


def build_combined_manifest(
    catalog_manifest: Mapping[str, Any],
    historical_validation: Mapping[str, Any],
) -> dict[str, Any]:
    if catalog_manifest.get("schema") != "shelfsignals-collection-manifest@1" or catalog_manifest.get("id") != "jefferson":
        raise BuildError("Catalog builder did not produce the expected Jefferson @1 manifest")
    if historical_validation.get("schema") != "shelfsignals-jefferson-historical-validation@1":
        raise BuildError("Historical builder validation identity is invalid")
    historical_counts = historical_validation.get("counts")
    if not isinstance(historical_counts, dict) or historical_counts.get("source_backed_entries") != SOURCE_BACKED_ENTRY_COUNT:
        raise BuildError("Historical package does not attest exactly 4,928 source-backed entries")
    source_backed_titles = historical_counts.get("source_backed_titles")
    titles_not_established = historical_counts.get("titles_not_established")
    page_resolved_identifiers = historical_counts.get("page_resolved_identifiers")
    aggregate_spine_identifiers = historical_counts.get("aggregate_spine_identifiers")
    if (
        not all(isinstance(value, int) and value >= 0 for value in (
            source_backed_titles,
            titles_not_established,
            page_resolved_identifiers,
            aggregate_spine_identifiers,
        ))
        or source_backed_titles + titles_not_established != SOURCE_BACKED_ENTRY_COUNT
        or page_resolved_identifiers + aggregate_spine_identifiers != SOURCE_BACKED_ENTRY_COUNT
    ):
        raise BuildError("Historical title and page-evidence counts do not reconcile to 4,928 entries")

    original_copy = dict(catalog_manifest.get("copy") or {})
    catalog_copy = corpus_copy(original_copy)
    catalog_record_count = int((catalog_manifest.get("coverage") or {}).get("record_count") or 0)
    established_links = int((catalog_manifest.get("coverage") or {}).get("established_sowerby_links") or 0)
    if catalog_record_count <= 0 or established_links < 0:
        raise BuildError("Catalog manifest coverage is invalid")
    catalog_copy["coverage_statement"] = (
        f"This beta contains {catalog_record_count:,} current LOC catalog instances, separate from the "
        f"{SOURCE_BACKED_ENTRY_COUNT:,}-entry historical Sowerby layer across {HISTORICAL_POSITION_COUNT:,} "
        f"source positions and from the {HISTORICAL_VOLUME_COUNT:,} physical volumes transferred in 1815. "
        "The catalog and historical layers overlap and must not be added as unique books. "
        f"Only {established_links} Sowerby links are established by the bounded MARC sample."
    )
    catalog_coverage = {
        "status": "beta",
        "entity_type": "catalog_instance",
        "record_count": catalog_record_count,
        "historical_entry_count": SOURCE_BACKED_ENTRY_COUNT,
        "historical_position_count": HISTORICAL_POSITION_COUNT,
        "historical_volume_count": HISTORICAL_VOLUME_COUNT,
        "established_sowerby_links": established_links,
    }
    catalog_data = {
        field: value for field, value in dict(catalog_manifest.get("data") or {}).items()
        if field != "hierarchy"
    }
    catalog_corpus = {
        "id": "catalog",
        "label": "Current LOC catalog",
        "record_id_prefix": "jefferson-loc-",
        "copy": catalog_copy,
        "coverage": catalog_coverage,
        "data": catalog_data,
        "features": dict(catalog_manifest.get("features") or {}),
        "facets": list(catalog_manifest.get("facets") or []),
        "orders": list(catalog_manifest.get("orders") or []),
        "default_order": "title",
    }

    historical_copy = {
        "status_label": "Historical corpus beta",
        "introduction": "Explore source-backed Sowerby entries in historical catalog order.",
        "coverage_statement": (
            f"This corpus contains {SOURCE_BACKED_ENTRY_COUNT:,} source-backed entries across "
            f"{HISTORICAL_POSITION_COUNT:,} Sowerby source positions. {source_backed_titles:,} entries have "
            f"conservative scan-OCR display titles; {titles_not_established:,} titles remain not established. "
            f"{page_resolved_identifiers:,} entries resolve to exact LOC PDF pages; "
            f"{aggregate_spine_identifiers:,} retain aggregate scan-spine support. Serials 2323, 4707, "
            "and 4708 are documented source-number gaps, not books."
        ),
        "source_label": "Library of Congress Sowerby scans",
    }
    historical_coverage = {
        "status": "beta",
        "entity_type": "sowerby_entry",
        "record_count": SOURCE_BACKED_ENTRY_COUNT,
        "historical_entry_count": SOURCE_BACKED_ENTRY_COUNT,
        "historical_position_count": HISTORICAL_POSITION_COUNT,
        "historical_volume_count": HISTORICAL_VOLUME_COUNT,
        "established_sowerby_links": 0,
    }
    historical_features = {
        "journeys": False,
        "placement": False,
        "photo_likelihood": False,
        "provider_editions": False,
        "curated_paths": False,
        "historical_hierarchy": True,
        "coverage_comparison": True,
        "reconstruction_status": True,
        "digital_surrogates": False,
        "evidence_ledger": True,
        "physical": False,
    }
    historical_corpus = {
        "id": "historical",
        "label": "Historical Sowerby corpus",
        "record_id_prefix": "jefferson-sowerby-",
        "copy": historical_copy,
        "coverage": historical_coverage,
        "data": {
            "core": "historical/catalog-core.json",
            "search": "historical/catalog-search.json",
            "detail_template": "historical/catalog-details/{shard}.json",
            "detail_index": "historical/catalog-details/index.json",
            "validation": "historical/validation.json",
        },
        "features": historical_features,
        "facets": ["evidence_status"],
        "orders": [
            {"id": "sowerby", "label": "Sowerby order"},
            {"id": "title", "label": "Title"},
        ],
        "default_order": "sowerby",
    }

    top_copy = dict(original_copy)
    top_copy.update(catalog_copy)
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "id": "jefferson",
        "copy": top_copy,
        "data": dict(catalog_manifest.get("data") or {}),
        "features": dict(catalog_corpus["features"]),
        "coverage": dict(catalog_coverage),
        "shelf": dict(catalog_manifest.get("shelf") or {}),
        "facets": list(catalog_corpus["facets"]),
        "orders": list(catalog_corpus["orders"]),
        "defaults": {"corpus": "catalog", "order": "title"},
        "corpora": [catalog_corpus, historical_corpus],
    }
    if "review" in catalog_manifest:
        manifest["review"] = dict(catalog_manifest["review"])
    validate_combined_manifest(manifest)
    return manifest


def validate_combined_manifest(manifest: Mapping[str, Any]) -> None:
    if manifest.get("schema") != MANIFEST_SCHEMA or manifest.get("id") != "jefferson":
        raise BuildError("Combined manifest identity is invalid")
    corpora = manifest.get("corpora")
    if not isinstance(corpora, list) or [row.get("id") for row in corpora if isinstance(row, dict)] != ["catalog", "historical"]:
        raise BuildError("Combined manifest must declare catalog then historical corpora exactly")
    catalog, historical = corpora
    if manifest.get("coverage") != catalog.get("coverage") or manifest.get("features") != catalog.get("features"):
        raise BuildError("Top-level manifest does not describe the default catalog corpus")
    if manifest.get("facets") != catalog.get("facets") or manifest.get("orders") != catalog.get("orders"):
        raise BuildError("Top-level catalog controls drifted from the default corpus")
    if historical.get("coverage", {}).get("record_count") != SOURCE_BACKED_ENTRY_COUNT:
        raise BuildError("Historical manifest count drifted")
    catalog_paths = set((catalog.get("data") or {}).values())
    historical_paths = set((historical.get("data") or {}).values())
    if catalog_paths & historical_paths or any(not str(path).startswith("historical/") for path in historical_paths):
        raise BuildError("Corpus data paths overlap or escape the historical namespace")


def validate_shared_hierarchy(hierarchy_body: bytes, chapter_ranges_path: Path) -> None:
    hierarchy = decode_json(hierarchy_body, "Shared hierarchy")
    try:
        artifact = json.loads(Path(chapter_ranges_path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BuildError(f"Unable to read tracked LOC chapter ranges: {error}") from error
    if not isinstance(artifact, dict) or artifact.get("schema") != "shelfsignals-loc-sowerby-chapter-ranges@1":
        raise BuildError("Tracked LOC chapter-range identity is invalid")
    hierarchy_rows = hierarchy.get("chapters")
    artifact_rows = artifact.get("chapters")
    if (
        hierarchy.get("schema") != "shelfsignals-jefferson-hierarchy@1"
        or not isinstance(hierarchy_rows, list)
        or not isinstance(artifact_rows, list)
        or len(hierarchy_rows) != 44
        or len(artifact_rows) != 44
    ):
        raise BuildError("Shared hierarchy and LOC artifact must each contain 44 chapters")
    optional_ranges = (
        "start_identifier", "end_identifier", "heading_pdf_page", "first_marker_pdf_page",
        "source_url", "evidence_sha256",
    )
    for hierarchy_row, artifact_row in zip(hierarchy_rows, artifact_rows, strict=True):
        for hierarchy_field, artifact_field in (
            ("chapter_number", "chapter_number"),
            ("chapter_roman", "chapter_roman"),
            ("faculty", "faculty"),
            ("heading", "label"),
            ("printed_page", "printed_page"),
        ):
            if hierarchy_row.get(hierarchy_field) != artifact_row.get(artifact_field):
                raise BuildError(
                    f"Shared hierarchy drifted from LOC chapter ranges at chapter "
                    f"{artifact_row.get('chapter_number')}: {hierarchy_field}"
                )
        for field in optional_ranges:
            if field in hierarchy_row and hierarchy_row.get(field) != artifact_row.get(field):
                raise BuildError(
                    f"Shared hierarchy range evidence drifted at chapter {artifact_row.get('chapter_number')}: {field}"
                )
    faculties = hierarchy.get("faculties")
    expected_faculties = [
        {"name": "History", "chapter_start": 1, "chapter_end": 15},
        {"name": "Philosophy", "chapter_start": 16, "chapter_end": 29},
        {"name": "Fine Arts", "chapter_start": 30, "chapter_end": 44},
    ]
    if faculties != expected_faculties:
        raise BuildError("Shared hierarchy faculty boundaries drifted from the LOC range artifact")
    if hierarchy.get("base_integer_identifier_count") != HISTORICAL_POSITION_COUNT:
        raise BuildError("Shared hierarchy position count drifted from the LOC range artifact")


def build_package(
    source_dir: Path = DEFAULT_SOURCE_DIR,
    chapter_ranges_path: Path = DEFAULT_CHAPTER_RANGES,
) -> dict[str, bytes]:
    catalog_files = catalog_builder.build_package(source_dir)
    historical_files = historical_builder.build_package(source_dir, chapter_ranges_path)
    validate_shared_hierarchy(catalog_files["hierarchy.json"], chapter_ranges_path)
    catalog_manifest = decode_json(catalog_files["manifest.json"], "Catalog manifest")
    historical_validation = decode_json(historical_files["validation.json"], "Historical validation")
    manifest = build_combined_manifest(catalog_manifest, historical_validation)
    files = {path: body for path, body in catalog_files.items() if path != "manifest.json"}
    for path, body in historical_files.items():
        routed = f"historical/{path}"
        if routed in files:
            raise BuildError(f"Aggregate output collision: {routed}")
        files[routed] = body
    files["manifest.json"] = json_bytes(manifest)
    return dict(sorted(files.items()))


def write_package(files: Mapping[str, bytes], output_dir: Path = DEFAULT_OUTPUT_DIR) -> None:
    output_dir = Path(output_dir)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(tempfile.mkdtemp(prefix=".jefferson-combined-", dir=output_dir.parent))
    try:
        for relative, body in files.items():
            target = staging / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(body)
        output_dir.mkdir(parents=True, exist_ok=True)
        expected = set(files)
        for path in sorted(output_dir.rglob("*"), reverse=True):
            if path.is_file() and path.relative_to(output_dir).as_posix() not in expected:
                path.unlink()
        for relative in sorted(files):
            target = output_dir / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            os.replace(staging / relative, target)
    finally:
        shutil.rmtree(staging, ignore_errors=True)


def check_package(files: Mapping[str, bytes], output_dir: Path = DEFAULT_OUTPUT_DIR) -> None:
    output_dir = Path(output_dir)
    failures = []
    for relative, body in files.items():
        path = output_dir / relative
        if not path.is_file():
            failures.append(f"missing: {relative}")
        elif path.read_bytes() != body:
            failures.append(f"stale: {relative}")
    actual = {
        path.relative_to(output_dir).as_posix()
        for path in output_dir.rglob("*") if path.is_file()
    } if output_dir.is_dir() else set()
    failures.extend(f"unexpected: {path}" for path in sorted(actual - set(files)))
    if failures:
        raise BuildError("Combined Jefferson package check failed:\n- " + "\n- ".join(failures))


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, default=DEFAULT_SOURCE_DIR)
    parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    parser.add_argument("--chapter-ranges", type=Path, default=DEFAULT_CHAPTER_RANGES)
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
            raise BuildError("Combined Jefferson package is not deterministic across two builds")
        if args.check:
            check_package(first, args.output_dir)
            action = "checked"
        elif args.self_test:
            action = "validated in memory"
        else:
            write_package(first, args.output_dir)
            action = "wrote"
        print(f"Combined Jefferson package {action}: {len(first)} files, {sum(map(len, first.values()))} bytes")
        return 0
    except (BuildError, catalog_builder.BuildError, historical_builder.BuildError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
