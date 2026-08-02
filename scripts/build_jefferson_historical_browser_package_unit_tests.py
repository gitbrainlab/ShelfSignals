#!/usr/bin/env python3
"""Focused contract tests for the Jefferson historical browser builder."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import build_jefferson_historical_browser_package as builder


def sha_text(value: str) -> str:
    return f"sha256:{hashlib.sha256(value.encode()).hexdigest()}"


def roman(number: int) -> str:
    values = ((40, "XL"), (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"))
    result = ""
    for value, token in values:
        while number >= value:
            result += token
            number -= value
    return result


def write_json(path: Path, value) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(builder.json_bytes(value))


def write_jsonl(path: Path, values) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(b"".join(builder.json_bytes(value) for value in values))


def output_identity(path: Path) -> dict:
    return {"bytes": path.stat().st_size, "sha256": builder.sha256_file(path)}


def make_structure_fixture(root: Path) -> tuple[Path, dict[int, dict]]:
    expected = builder.expected_numbers()
    chunk, remainder = divmod(len(expected), 44)
    ranges = []
    structure = {}
    pages = []
    cursor = 0
    for chapter_number in range(1, 45):
        size = chunk + (1 if chapter_number <= remainder else 0)
        values = expected[cursor:cursor + size]
        cursor += size
        faculty = "History" if chapter_number <= 15 else "Philosophy" if chapter_number <= 29 else "Fine Arts"
        render_hash = sha_text(f"render-{chapter_number}")
        text_hash = sha_text(f"text-{chapter_number}")
        tsv_hash = sha_text(f"tsv-{chapter_number}")
        pdf_url = "https://tile.loc.gov/storage-services/service/rbc/fixture.pdf"
        row = {
            "chapter_number": chapter_number,
            "chapter_roman": roman(chapter_number),
            "faculty": faculty,
            "label": f"Chapter {chapter_number}",
            "toc_heading": f"Chapter {chapter_number}",
            "scan_heading": f"Chapter {chapter_number}",
            "start_identifier": values[0],
            "end_identifier": values[-1],
            "volume": 1,
            "heading_pdf_page": chapter_number,
            "first_marker_pdf_page": chapter_number,
            "first_marker_normalized_identifier": values[0],
            "printed_page": chapter_number,
            "pdf_url": pdf_url,
            "pdf_sha256": sha_text("fixture-pdf"),
            "source_url": f"{pdf_url}#page={chapter_number}",
            "first_marker_source_url": f"{pdf_url}#page={chapter_number}",
            "review_method": "manual_visual_loc_pdf_heading_and_first_entry_boundary",
            "review_status": "verified",
            "boundary_method": "chapter_heading_plus_first_entry_terminal_marker",
            "reviewed_at": "2026-08-01",
            "heading_page_sidecar_sha256": sha_text(f"sidecar-{chapter_number}"),
            "first_marker_page_sidecar_sha256": sha_text(f"sidecar-{chapter_number}"),
            "page_render_sha256": render_hash,
            "page_ocr_text_sha256": text_hash,
            "page_ocr_tsv_sha256": tsv_hash,
            "marker_page_render_sha256": render_hash,
            "marker_page_ocr_text_sha256": text_hash,
            "marker_page_ocr_tsv_sha256": tsv_hash,
        }
        row["evidence_sha256"] = builder._chapter_boundary_evidence_sha256(row)
        ranges.append(row)
        pages.append({
            "volume": 1,
            "pdf_page": chapter_number,
            "variant": "base",
            "render_sha256": render_hash,
            "ocr_text_sha256": text_hash,
            "ocr_tsv_sha256": tsv_hash,
        })
        for identifier in values:
            structure[identifier] = {"chapter_number": chapter_number, "faculty": faculty}
    self_artifact = root / "loc-sowerby-chapter-ranges.json"
    write_json(self_artifact, {
        "schema": "shelfsignals-loc-sowerby-chapter-ranges@1",
        "authority": "Library of Congress",
        "source_item_url": builder.LOC_ITEM_URL,
        "pdfs": [
            {
                "volume": volume,
                "pdf_url": "https://tile.loc.gov/storage-services/service/rbc/fixture.pdf",
                "pdf_sha256": sha_text("fixture-pdf"),
            }
            for volume in range(1, 6)
        ],
        "chapters": ranges,
    })
    write_jsonl(root / builder.OCR_FILES["pages"], pages)
    write_json(root / builder.LOC_REFERENCE_FILE, {
        "schema": "shelfsignals-loc-sowerby-reference@1",
        "source": {"authority": "Library of Congress"},
        "chapters": [
            {
                "chapter_number": number,
                "chapter_roman": roman(number),
                "faculty": "History" if number <= 15 else "Philosophy" if number <= 29 else "Fine Arts",
                "heading": f"Chapter {number}",
                "printed_page": number,
            }
            for number in range(1, 45)
        ],
    })
    private_rows = []
    for position in range(1, builder.EXPECTED_MAX_SERIAL + 1):
        if position in builder.EXPECTED_GAPS:
            private_rows.append({
                "sowerby_number": position,
                "historical_order": position,
                "entity_type": "sowerby_entry_gap_placeholder",
            })
        else:
            private_rows.append({
                "sowerby_number": position,
                "historical_order": position,
                "entity_type": "sowerby_entry",
                **structure[position],
            })
    write_jsonl(root / builder.STRUCTURE_FILES["entries"], private_rows)
    write_jsonl(root / builder.STRUCTURE_FILES["exceptions"], [])
    write_jsonl(root / builder.STRUCTURE_FILES["pages"], [])
    write_json(root / builder.STRUCTURE_FILES["validation"], {
        "all_invariants_passed": True,
        "source_gap_placeholder_numbers": list(builder.EXPECTED_GAPS),
    })
    manifest = {
        "publication_status": "research-only until Thomas Jefferson Foundation reuse permission is recorded",
        "terms_review_is_publication_permission": False,
        "factual_core_only": True,
        "outputs": {},
    }
    for key, filename in builder.STRUCTURE_FILES.items():
        if key != "manifest":
            manifest["outputs"][filename] = output_identity(root / filename)
    write_json(root / builder.STRUCTURE_FILES["manifest"], manifest)
    return self_artifact, structure


class HistoricalBuilderTests(unittest.TestCase):
    def test_loc_ranges_partition_spine_and_private_source_is_qa_only(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact, expected_structure = make_structure_fixture(root)
            structure, chapters, public_hashes = builder.load_structure(root, artifact)
            self.assertEqual(structure, expected_structure)
            self.assertEqual(len(structure), 4928)
            self.assertEqual(len(chapters), 44)
            self.assertEqual(
                set(public_hashes),
                {"loc_chapter_ranges_sha256", "loc_chapter_reference_sha256"},
            )
            self.assertTrue(chapters[1]["source_url"].endswith("#page=1"))
            self.assertRegex(chapters[1]["evidence_sha256"], r"^sha256:[0-9a-f]{64}$")

    def test_chapter_page_hash_drift_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact, _ = make_structure_fixture(root)
            value = json.loads(artifact.read_text(encoding="utf-8"))
            value["chapters"][0]["page_render_sha256"] = sha_text("tampered")
            value["chapters"][0]["evidence_sha256"] = builder._chapter_boundary_evidence_sha256(value["chapters"][0])
            write_json(artifact, value)
            with self.assertRaisesRegex(builder.BuildError, "page hash drifted"):
                builder.load_structure(root, artifact)

    def test_private_structure_disagreement_fails_without_becoming_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact, _ = make_structure_fixture(root)
            rows = [json.loads(line) for line in (root / builder.STRUCTURE_FILES["entries"]).read_text().splitlines()]
            rows[0]["chapter_number"] = 2
            rows[0]["faculty"] = "History"
            write_jsonl(root / builder.STRUCTURE_FILES["entries"], rows)
            manifest_path = root / builder.STRUCTURE_FILES["manifest"]
            manifest = json.loads(manifest_path.read_text())
            filename = builder.STRUCTURE_FILES["entries"]
            manifest["outputs"][filename] = output_identity(root / filename)
            write_json(manifest_path, manifest)
            with self.assertRaisesRegex(builder.BuildError, "Private equality QA disagrees"):
                builder.load_structure(root, artifact)

    def test_sequence_assertion_uses_source_serial_not_zero_based_rank(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            artifact, structure = make_structure_fixture(root)
            structure, chapters, _ = builder.load_structure(root, artifact)
            rights_hash = sha_text("rights")
            rows = []
            for number in builder.expected_numbers():
                rows.append({
                    "id": f"jefferson-sowerby-{number}",
                    "sowerby_number": number,
                    "sowerby_identifier": str(number),
                    "authority": "Library of Congress",
                    "publication_basis": "loc_scan_ocr_factual_extraction",
                    "rights_statement_sha256": rights_hash,
                    "title_status": "not_established",
                    "display_title": "",
                    "identifier_status": "aggregate_scan_spine_source_backed",
                    "evidence": {"evidence_sha256": sha_text(f"record-{number}")},
                })
            manifest = {
                "publication_basis": "loc_scan_ocr_factual_extraction",
                "generated_at": "2026-08-01T00:00:00Z",
                "rights_statement_url": builder.LOC_ITEM_URL,
                "rights_statement_sha256": rights_hash,
            }
            projected = builder.project_sources(rows, structure, chapters, manifest)
            detail = dict(zip(builder.DETAIL_FIELDS, projected[1]["detail"]))
            projected[1]["source_position"] = 2
            core = dict(zip(builder.CORE_FIELDS, builder.core_row(projected[1])))
            self.assertEqual(detail["material_type"], "")
            self.assertEqual(detail["formats"], [])
            self.assertEqual(core["material_type"], "")
            self.assertEqual(core["formats"], [])
            self.assertEqual(core["evidence_status"], "sowerby_entry_aggregate_spine")
            self.assertTrue(all(
                set(assertion) == {"field", "status", "value", "source", "source_url", "evidence_sha256", "as_of"}
                for assertion in detail["assertions"]
            ))
            sequence = next(row for row in detail["assertions"] if row["field"] == "historical_sequence")
            chapter = next(row for row in detail["assertions"] if row["field"] == "historical_chapter")
            self.assertEqual(sequence["value"], "2")
            self.assertEqual(sequence["evidence_sha256"], sha_text("record-2"))
            self.assertEqual(chapter["source_url"], chapters[structure[2]["chapter_number"]]["source_url"])
            self.assertEqual(chapter["evidence_sha256"], chapters[structure[2]["chapter_number"]]["evidence_sha256"])

    def test_core_budget_and_validation_schema_match_runtime_contract(self):
        self.assertEqual(builder.CORE_DECODED_BUDGET, 1_250_000)
        self.assertEqual(builder.VALIDATION_SCHEMA, "shelfsignals-jefferson-historical-validation@1")

    def test_assertions_fail_closed_on_missing_hash_or_foreign_url(self):
        valid = {
            "field": "historical_chapter",
            "status": "source_backed",
            "value": "1",
            "source": "Library of Congress Sowerby scan",
            "source_url": "https://tile.loc.gov/example.pdf#page=1",
            "evidence_sha256": sha_text("evidence"),
            "as_of": "2026-08-01",
        }
        builder.validate_assertion(valid, "fixture")
        missing = dict(valid)
        missing.pop("evidence_sha256")
        with self.assertRaisesRegex(builder.BuildError, "fields"):
            builder.validate_assertion(missing, "fixture")
        foreign = dict(valid, source_url="https://example.org/not-loc")
        with self.assertRaisesRegex(builder.BuildError, "loc.gov"):
            builder.validate_assertion(foreign, "fixture")


if __name__ == "__main__":
    unittest.main()
