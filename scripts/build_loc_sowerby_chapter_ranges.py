#!/usr/bin/env python3
"""Materialize the reviewed LOC-only Sowerby chapter-range evidence artifact."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
import sys
from typing import Any, Sequence

import build_jefferson_historical_browser_package as historical


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_REFERENCE = REPOSITORY_ROOT / "research/jefferson/work/data/loc_sowerby_reference.json"
DEFAULT_GENERATION = (
    REPOSITORY_ROOT
    / "research/jefferson/work/cache/loc_sowerby_ocr_v1/generations/bc060911efd03aba698e"
)
DEFAULT_OUTPUT = REPOSITORY_ROOT / "research/jefferson/loc-sowerby-chapter-ranges.json"
REVIEWED_AT = "2026-08-01"
SOURCE_IDENTITY = "sha256:bc060911efd03aba698e261a74cc25c6e2214e48fe718f8892a1c578af03259b"

# Independently reviewed against the official LOC page images. Tuples are
# chapter, first serial, last serial, volume, chapter-heading PDF page, and the
# PDF page carrying the first entry's terminal global Sowerby marker.
REVIEWED_RANGES = (
    (1, 1, 132, 1, 27, 27),
    (2, 133, 324, 1, 88, 88),
    (3, 325, 442, 1, 165, 165),
    (4, 443, 602, 1, 222, 223),
    (5, 603, 627, 1, 312, 312),
    (6, 628, 688, 1, 323, 323),
    (7, 689, 822, 1, 349, 349),
    (8, 823, 853, 1, 400, 400),
    (9, 854, 860, 1, 417, 417),
    (10, 861, 994, 1, 421, 421),
    (11, 995, 1005, 1, 476, 476),
    (12, 1006, 1052, 1, 482, 482),
    (13, 1053, 1088, 1, 505, 505),
    (14, 1089, 1093, 1, 522, 522),
    (15, 1094, 1237, 1, 525, 525),
    (16, 1238, 1453, 2, 9, 9),
    (17, 1454, 1715, 2, 97, 97),
    (18, 1716, 1765, 2, 202, 202),
    (19, 1766, 2098, 2, 220, 220),
    (20, 2099, 2108, 2, 371, 372),
    (21, 2109, 2135, 2, 377, 377),
    (22, 2136, 2154, 2, 390, 390),
    (23, 2155, 2322, 2, 398, 398),
    (24, 2324, 3662, 3, 9, 10),
    (25, 3663, 3700, 4, 11, 11),
    (26, 3701, 3718, 4, 30, 30),
    (27, 3719, 3779, 4, 37, 37),
    (28, 3780, 3817, 4, 75, 75),
    (29, 3818, 4172, 4, 95, 95),
    (30, 4173, 4224, 4, 374, 374),
    (31, 4225, 4249, 4, 401, 401),
    (32, 4250, 4261, 4, 416, 416),
    (33, 4262, 4304, 4, 426, 428),
    (34, 4305, 4377, 4, 449, 449),
    (35, 4378, 4455, 4, 483, 483),
    (36, 4456, 4519, 4, 515, 515),
    (37, 4520, 4570, 4, 543, 543),
    (38, 4571, 4615, 4, 563, 563),
    (39, 4616, 4641, 5, 13, 13),
    (40, 4642, 4691, 5, 25, 25),
    (41, 4692, 4706, 5, 50, 50),
    (42, 4709, 4733, 5, 56, 56),
    (43, 4734, 4888, 5, 71, 71),
    (44, 4889, 4931, 5, 155, 162),
)

SCAN_HEADINGS = (
    "Ancient History",
    "Modern History—Foreign",
    "Modern History—British",
    "Modern History—American",
    "Ecclesiastical History",
    "Natural Philosophy",
    "Agriculture",
    "Chemistry",
    "Surgery",
    "Medicine",
    "Anatomy",
    "Zoology",
    "Botany",
    "Mineralogy",
    "Technical Arts",
    "Ethics",
    "Religion",
    "Equity",
    "Common Law",
    "Law—Merchant",
    "Law—Maritime",
    "Law—Ecclesiastical",
    "Foreign Law",
    "Politics",
    "Mathematics—Pure—Arithmetic",
    "Mathematics—Pure—Geometry",
    "Physico-Mathematics",
    "Astronomy",
    "Geography",
    "Architecture",
    "Gardening, Painting, Sculpture",
    "Music",
    "Poetry—Epic",
    "Romance—Tales—Fables",
    "Pastorals—Odes—Elegies",
    "Didactic",
    "Tragedy",
    "Comedy",
    "Dialogue—Epistolary",
    "Logic—Rhetoric—Orations",
    "Criticism",
    "Criticism",
    "Criticism",
    "Polygraphical",
)


class RangeError(RuntimeError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise RangeError(f"Unable to read {path}: {error}") from error
    if not isinstance(value, dict):
        raise RangeError(f"{path} must contain an object")
    return value


def sidecar(generation: Path, volume: int, page: int) -> tuple[Path, dict[str, Any]]:
    path = generation / f"base/volume-{volume}/page-{page:04d}.json"
    value = load_json(path)
    if (
        value.get("schema") != "shelfsignals-jefferson-loc-ocr-page@1"
        or value.get("source_identity_sha256") != SOURCE_IDENTITY
        or value.get("volume") != volume
        or value.get("pdf_page") != page
        or value.get("variant") != "base"
    ):
        raise RangeError(f"OCR sidecar identity drifted: {path}")
    return path, value


def artifact(reference_path: Path, generation: Path) -> dict[str, Any]:
    reference = load_json(reference_path)
    chapters = reference.get("chapters")
    if (
        reference.get("schema") != "shelfsignals-loc-sowerby-reference@1"
        or not isinstance(chapters, list)
        or [row.get("chapter_number") for row in chapters if isinstance(row, dict)] != list(range(1, 45))
    ):
        raise RangeError("LOC chapter reference identity/count drifted")
    generation_identity = load_json(generation / "generation.json")
    if generation_identity.get("source_identity_sha256") != SOURCE_IDENTITY:
        raise RangeError("LOC OCR generation source identity drifted")

    expected = historical.expected_numbers()
    ranges_union: list[int] = []
    rows = []
    pdfs: dict[int, dict[str, Any]] = {}
    for reviewed, scan_heading, reference_row in zip(REVIEWED_RANGES, SCAN_HEADINGS, chapters, strict=True):
        chapter_number, start, end, volume, heading_page, marker_page = reviewed
        if reference_row.get("chapter_number") != chapter_number:
            raise RangeError(f"LOC chapter reference order drifted at {chapter_number}")
        heading_path, heading = sidecar(generation, volume, heading_page)
        marker_path, marker = sidecar(generation, volume, marker_page)
        if heading.get("pdf_url") != marker.get("pdf_url") or heading.get("pdf_sha256") != marker.get("pdf_sha256"):
            raise RangeError(f"Chapter {chapter_number} heading/marker PDF identity differs")
        pdfs.setdefault(volume, {
            "volume": volume,
            "pdf_url": heading["pdf_url"],
            "pdf_sha256": heading["pdf_sha256"],
        })
        if pdfs[volume]["pdf_url"] != heading["pdf_url"] or pdfs[volume]["pdf_sha256"] != heading["pdf_sha256"]:
            raise RangeError(f"Volume {volume} PDF identity changed within the audited pages")
        row = {
            "chapter_number": chapter_number,
            "chapter_roman": reference_row.get("chapter_roman"),
            "faculty": reference_row.get("faculty"),
            "label": reference_row.get("heading"),
            "toc_heading": reference_row.get("heading"),
            "scan_heading": scan_heading,
            "start_identifier": start,
            "end_identifier": end,
            "volume": volume,
            "heading_pdf_page": heading_page,
            "first_marker_pdf_page": marker_page,
            "first_marker_normalized_identifier": start,
            "printed_page": reference_row.get("printed_page"),
            "pdf_url": heading["pdf_url"],
            "pdf_sha256": heading["pdf_sha256"],
            "source_url": f"{heading['pdf_url']}#page={heading_page}",
            "first_marker_source_url": f"{marker['pdf_url']}#page={marker_page}",
            "review_method": "manual_visual_loc_pdf_heading_and_first_entry_boundary",
            "review_status": "verified",
            "boundary_method": "chapter_heading_plus_first_entry_terminal_marker",
            "reviewed_at": REVIEWED_AT,
            "heading_page_sidecar_sha256": historical.sha256_file(heading_path),
            "first_marker_page_sidecar_sha256": historical.sha256_file(marker_path),
            "page_render_sha256": heading["render"]["sha256"],
            "page_ocr_text_sha256": heading["text"]["sha256"],
            "page_ocr_tsv_sha256": heading["tsv"]["sha256"],
            "marker_page_render_sha256": marker["render"]["sha256"],
            "marker_page_ocr_text_sha256": marker["text"]["sha256"],
            "marker_page_ocr_tsv_sha256": marker["tsv"]["sha256"],
        }
        row["evidence_sha256"] = historical._chapter_boundary_evidence_sha256(row)
        rows.append(row)
        ranges_union.extend(number for number in expected if start <= number <= end)
    if sorted(ranges_union) != expected or len(ranges_union) != len(set(ranges_union)):
        raise RangeError("Reviewed chapter ranges do not partition the 4,928-entry source spine")
    if sorted(pdfs) != list(range(1, 6)):
        raise RangeError("Reviewed chapter pages do not cover all five official PDFs")
    result = {
        "schema": "shelfsignals-loc-sowerby-chapter-ranges@1",
        "authority": "Library of Congress",
        "source_item_url": historical.LOC_ITEM_URL,
        "source_identity_sha256": SOURCE_IDENTITY,
        "reviewed_at": REVIEWED_AT,
        "review_method": "manual_visual_loc_pdf_heading_and_first_entry_boundary",
        "loc_reference": {
            "file": "loc_sowerby_reference.json",
            "sha256": historical.sha256_file(reference_path),
            "table_of_contents_url": reference.get("source", {}).get("table_of_contents", ""),
        },
        "numbering": {
            "max_source_serial": historical.EXPECTED_MAX_SERIAL,
            "source_backed_entry_count": historical.EXPECTED_RECORD_COUNT,
            "confirmed_absent_numbers": list(historical.EXPECTED_GAPS),
        },
        "pdfs": [pdfs[volume] for volume in sorted(pdfs)],
        "methodology": [
            "Locate each chapter's Roman-numeral opening and displayed heading in the official LOC scan.",
            "Associate the first local catalog item with its terminal global Sowerby marker; visually verify OCR anomalies.",
            "End each range immediately before the next verified start, excluding only the three LOC-confirmed absent numbers.",
            "Require 44 monotonic non-overlapping ranges whose union is exactly 4,928 source-backed identifiers.",
        ],
        "chapters": rows,
    }
    serialized = json.dumps(result, ensure_ascii=False)
    if re.search(r"tjlibraries|monticello\.org|thomas jefferson foundation", serialized, re.I):
        raise RangeError("Restricted source identity entered the LOC-only chapter artifact")
    return result


def body(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--reference", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--generation", type=Path, default=DEFAULT_GENERATION)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        data = body(artifact(args.reference, args.generation))
        if args.check:
            if not args.output.is_file() or args.output.read_bytes() != data:
                raise RangeError(f"Tracked LOC chapter artifact is missing or stale: {args.output}")
            action = "checked"
        else:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            temporary = args.output.with_name(f".{args.output.name}.tmp")
            temporary.write_bytes(data)
            temporary.replace(args.output)
            action = "wrote"
        print(f"LOC Sowerby chapter ranges {action}: 44 chapters, 4,928 source-backed entries")
        return 0
    except RangeError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
