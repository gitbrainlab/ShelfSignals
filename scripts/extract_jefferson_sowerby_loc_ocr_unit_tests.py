#!/usr/bin/env python3
"""Focused offline tests for the LOC Sowerby OCR pipeline."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import extract_jefferson_sowerby_loc_ocr as ocr


def line(text: str, *, left: int = 500, top: int = 500, right: int = 950, bottom: int = 530, confidence: float = 94.0) -> ocr.OcrLine:
    return ocr.OcrLine(text, left, top, right, bottom, 1000, 1500, confidence)


class LocSowerbyOcrTests(unittest.TestCase):
    def setUp(self) -> None:
        self.task = ocr.PageTask(1, 50, 240, 3, "base")
        self.sidecar = {"volume": 1, "pdf_page": 50, "dpi": 240, "psm": 3, "variant": "base"}

    def test_authoritative_numbering_has_three_gaps_and_4928_entries(self):
        self.assertEqual(ocr.EXPECTED_GAPS, {2323, 4707, 4708})
        self.assertEqual(ocr.EXPECTED_NUMBERED_ENTRY_COUNT, 4928)
        numbers = ocr.expected_numbers()
        self.assertEqual(len(numbers), 4928)
        self.assertEqual(numbers[0], 1)
        self.assertEqual(numbers[-1], 4931)
        self.assertFalse(set(numbers) & ocr.EXPECTED_GAPS)

    def test_parenthesized_publication_year_never_becomes_marker(self):
        false_year = line("Published at London (1751)")
        true_marker = line("historical note. [39]")
        trailing_text = line("historical note. [39] continued")
        self.assertEqual(ocr.candidates_from_line(self.task, self.sidecar, false_year), [])
        candidates = ocr.candidates_from_line(self.task, self.sidecar, true_marker)
        self.assertEqual([candidate.number for candidate in candidates], [39])
        self.assertGreater(candidates[0].score, 4)
        self.assertEqual(ocr.candidates_from_line(self.task, self.sidecar, trailing_text), [])

    def test_centered_footer_number_is_not_an_entry_marker(self):
        footer = line("[24]", left=470, right=530, top=1420, bottom=1450)
        self.assertEqual(ocr.candidates_from_line(self.task, self.sidecar, footer), [])

    def test_inline_j_heading_is_a_title(self):
        title, kind, creator, confidence = ocr.extract_title_from_lines([line("J. 39 Stanyan's Graecian history.", left=120, right=700)])
        self.assertEqual(title, "Stanyan's Graecian history")
        self.assertEqual(kind, "jefferson_catalog_heading_ocr")
        self.assertEqual(creator, "")
        self.assertEqual(confidence, 94.0)

    def test_split_j_heading_stays_unresolved_after_precision_audit(self):
        rows = [
            line("J. 39", left=150, top=400, right=250, bottom=435),
            line("Stanyan's Graecian history.", left=280, top=480, right=650, bottom=518),
        ]
        title, kind, creator, _ = ocr.extract_title_from_lines(rows)
        self.assertEqual(title, "")
        self.assertEqual(kind, "not_established")
        self.assertEqual(creator, "")

    def test_split_j_heading_uses_rightward_same_band_geometry(self):
        rows = [
            line("Stanyan's Graecian history.", left=455, top=322, right=850, bottom=356),
            line("J. 3", left=291, top=324, right=390, bottom=360),
        ]
        title, kind, creator, _ = ocr.extract_title_from_lines(rows)
        self.assertEqual(title, "Stanyan's Graecian history")
        self.assertEqual(kind, "jefferson_catalog_heading_geometry_ocr")
        self.assertEqual(creator, "")

    def test_same_band_geometry_rejects_distant_right_column(self):
        rows = [
            line("J. 3", left=110, top=324, right=190, bottom=360),
            line("Unrelated prose in the right column.", left=620, top=322, right=930, bottom=356),
        ]
        title, kind, creator, _ = ocr.extract_title_from_lines(rows)
        self.assertEqual((title, kind, creator), ("", "not_established", ""))

    def test_catalogue_evidence_with_punctuation_is_not_a_title_or_continuation(self):
        title, kind, _, _ = ocr.extract_title_from_lines([
            line("J. 3 1815, Catalogue, page 7.", left=100),
        ])
        self.assertEqual((title, kind), ("", "not_established"))
        rows = [
            line("A valid short title.", left=455, top=322, right=850, bottom=356),
            line("J. 3", left=291, top=324, right=390, bottom=360),
            line("1815, Catalogue, page 7.", left=455, top=362, right=850, bottom=396),
        ]
        title, kind, _, _ = ocr.extract_title_from_lines(rows)
        self.assertEqual((title, kind), ("A valid short title", "jefferson_catalog_heading_geometry_ocr"))

    def test_title_boundary_requires_immediately_preceding_source_entry(self):
        def marker(number: int, volume: int = 1) -> ocr.MarkerCandidate:
            return ocr.MarkerCandidate(
                number=number,
                suffix="",
                volume=volume,
                page=10,
                left=100,
                top=500,
                top_ratio=0.5,
                line_text=f"[{number}]",
                confidence=90.0,
                score=10.0,
                variant="base",
                sidecar={},
            )

        current = marker(4)
        self.assertTrue(ocr.has_exact_title_boundary(4, current, {3: marker(3), 4: current}))
        self.assertFalse(ocr.has_exact_title_boundary(4, current, {2: marker(2), 4: current}))
        self.assertFalse(ocr.has_exact_title_boundary(1, marker(1), {1: marker(1)}))
        gap_current = marker(4709, 5)
        self.assertTrue(ocr.has_exact_title_boundary(
            4709,
            gap_current,
            {4706: marker(4706, 5), 4709: gap_current},
        ))

    def test_uppercase_author_is_never_promoted_as_title(self):
        rows = [line("STANYAN, TEMPLE."), line("The Grecian history, from the original of Greece.", top=540, bottom=570)]
        title, kind, creator, _ = ocr.extract_title_from_lines(rows)
        self.assertEqual(title, "The Grecian history, from the original of Greece")
        self.assertEqual(kind, "bibliographic_title_after_first_creator_heading_ocr")
        self.assertEqual(creator, "STANYAN, TEMPLE.")
        title, kind, creator, _ = ocr.extract_title_from_lines([line("STANYAN, TEMPLE.")])
        self.assertEqual(title, "")
        self.assertEqual(kind, "not_established")
        self.assertEqual(creator, "STANYAN, TEMPLE.")

    def test_bracketed_creator_uses_immediate_bibliographic_title_not_heading(self):
        rows = [
            line("[ANNIUS, Johannes.]", left=90, top=300, right=420, bottom=335),
            line("Berosi sacerdotis Chaldaici, Antiqvitatvm Libri Qvinqve.", left=90, top=345, right=900, bottom=380),
            line("Old calf, with the Library of Congress bookplate.", left=90, top=800, right=900, bottom=835),
        ]
        title, kind, creator, _ = ocr.extract_title_from_lines(rows)
        self.assertEqual(title, "Berosi sacerdotis Chaldaici, Antiqvitatvm Libri Qvinqve")
        self.assertEqual(kind, "bibliographic_title_after_first_creator_heading_ocr")
        self.assertEqual(creator, "[ANNIUS, Johannes.]")

    def test_direct_j_title_rejects_notes_physical_fragments_and_call_numbers(self):
        for text in (
            "J. 2 First Edition, with notes.",
            "J. 7 3 vol. bound in calf.",
            "J. 27 of the other editions.",
            "J. 41 Second Edition.",
            "J. 54 Not in the Manuscript Catalogue.",
            "J. 461 1831 Catalogue, page 4.",
            "J. 1507 fol.",
            "J. 9 DS116 .J55",
            "J. 83 Tracts in Ethics. viz.",
            "J. 101 Political tracts",
            "J. 1853 inserted in ink by Jefferson. Reprinted in Hening. [1852]",
            "J. 500 Six tracts bound together in one volume, original calf, red silk bookmark.",
            "J. 501 68 leaves",
            "J. 502 [DAVIS, Matthew Livingston.]",
            "J. 503 ~=Not in the Manuscript Catalogue.",
            "J. 28 id. cum supplemento Freinshemii Delphini. 8°",
            "J. 80 Eng. by Gordon. 9 0",
            "J. 2891 Hakewell’s Modus tenendi Parl. | 6!",
            "J. 2159 Notin the Manuscript Catalogue",
            "J. 45 (some irregularities), Liber II, paged 1-210;",
            "J. 45 ; Liber LV, pp. 1-127; Lib. V, pp. 1~64; Lib",
            "J. 2039 Hobart . 3.4H1—29. fact",
            "J. 3213 BARLOW, Joet",
            "J. 3276 SUMNER, Cuartes Pinckney",
            "J. 3286 CARON DE BEAUMARCHAIS, Amétm Euctne",
        ):
            title, status, _, _ = ocr.extract_title_from_lines([line(text, left=100)])
            self.assertEqual((title, status), ("", "not_established"), text)

    def test_geometry_rejects_lowercase_prose_continuation(self):
        rows = [
            line("J. 133", left=291, top=324, right=390, bottom=360),
            line("newly founded Ecole Normale, where his colleagues, as", left=455, top=322, right=950, bottom=356),
        ]
        title, kind, creator, _ = ocr.extract_title_from_lines(rows)
        self.assertEqual((title, kind, creator), ("", "not_established", ""))

    def test_geometry_does_not_concatenate_multiple_possible_titles(self):
        rows = [
            line("J. 4200", left=291, top=324, right=390, bottom=360),
            line("Elementi di Architettura del Padre Sanvitali.", left=455, top=322, right=900, bottom=356),
            line("Elementi di Architettura del Preti.", left=455, top=362, right=900, bottom=396),
            line("Nuove ricerche sullequilibrio delle volte del Abate Mascheroni.", left=455, top=402, right=950, bottom=436),
        ]
        title, kind, creator, _ = ocr.extract_title_from_lines(rows)
        self.assertEqual((title, kind, creator), ("", "not_established", ""))

    def test_creator_heading_requires_name_shape_and_high_confidence_title(self):
        title, status, creator, _ = ocr.extract_title_from_lines([
            line("LES CANADIENS."),
            line("Noisy line", top=540, bottom=570),
        ])
        self.assertEqual((title, status, creator), ("", "not_established", "LES CANADIENS."))
        title, status, creator, _ = ocr.extract_title_from_lines([
            line("SMITH, JOHN."),
            line("Plausible but low-confidence title.", top=540, bottom=570, confidence=89.9),
        ])
        self.assertEqual((title, status, creator), ("", "not_established", "SMITH, JOHN."))
        for heading, continuation in (
            ("POMPADOUR, JEANNE ANTOINETTE MAR-", "QUISE DE"),
            ("DICK,", "historian"),
            ("MOST OF THE BOOKS IN THIS LIST ARE ENTERED,", "WITH THE PRICES PAID FOR THEM"),
        ):
            title, status, _, _ = ocr.extract_title_from_lines([
                line(heading),
                line(continuation, top=540, bottom=570),
            ])
            self.assertEqual((title, status), ("", "not_established"), heading)

    def test_page_selection_is_bounded_and_deterministic(self):
        tasks = ocr.page_tasks(["2:4-6", "1:9", "2:5"])
        self.assertEqual([(task.volume, task.page) for task in tasks], [(1, 9), (2, 4), (2, 5), (2, 6)])
        with self.assertRaisesRegex(ocr.OcrError, "Invalid --pages"):
            ocr.page_tasks(["volume-one"])

    def test_rights_evidence_requires_the_loc_warning(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "item.json"
            path.write_text(json.dumps({
                "item": {
                    "url": ocr.LOC_ITEM_URL,
                    "rights": [
                        "The Library of Congress is not aware of any U.S. copyright or any other restrictions. "
                        "The determination of the status of an item ultimately rests with the person desiring to reproduce or use the item. "
                        "Credit Line: Library of Congress, Rare Book and Special Collections Division"
                    ],
                }
            }), encoding="utf-8")
            evidence = ocr.rights_evidence(path)
            self.assertEqual(evidence["rights_statement_url"], ocr.LOC_ITEM_URL)
            self.assertRegex(evidence["rights_statement_sha256"], r"^sha256:[0-9a-f]{64}$")
            self.assertIn("not granted", evidence["rights_clearance"])
            path.write_text(json.dumps({"item": {"url": ocr.LOC_ITEM_URL, "rights": ["free"]}}), encoding="utf-8")
            with self.assertRaisesRegex(ocr.OcrError, "changed"):
                ocr.rights_evidence(path)

    def test_cached_page_hash_drift_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            paths = {
                "image": root / "page.jpg",
                "text": root / "page.txt",
                "tsv": root / "page.tsv",
                "sidecar": root / "page.json",
            }
            for key in ("image", "text", "tsv"):
                paths[key].write_bytes((key + "\n").encode())
            expected = {"schema": ocr.PAGE_SCHEMA, "volume": 1}
            sidecar = dict(expected)
            for field, key in (("render", "image"), ("text", "text"), ("tsv", "tsv")):
                sidecar[field] = {
                    "bytes": paths[key].stat().st_size,
                    "sha256": ocr.sha256_file(paths[key]),
                }
            paths["sidecar"].write_bytes(ocr.json_bytes(sidecar))
            self.assertEqual(ocr._validate_page_sidecar(paths, expected), sidecar)
            paths["text"].write_text("drift\n", encoding="utf-8")
            with self.assertRaisesRegex(ocr.OcrError, "hash drifted"):
                ocr._validate_page_sidecar(paths, expected)


if __name__ == "__main__":
    unittest.main()
