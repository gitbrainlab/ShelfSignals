#!/usr/bin/env python3
"""Offline tests for the focused Sowerby transcript harvester/builder."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import harvest_jefferson_sowerby as harvester


def _page(volume: str, page: int, body: str, *, previous: str = "", following: str = "") -> bytes:
    links = ""
    if previous:
        links += f'<a href="{previous}">previous</a>'
    if following:
        links += f'<a href="{following}">next</a>'
    return f"""<!doctype html>
<html><head><title>Sowerby Catalogue <h1>Volume {volume} : page {page}</title></head>
<body>{links}<div class="portal_body">{body}</div></body></html>
""".encode("utf-8")


def _write_source_page(directory: Path, name: str, body: bytes) -> None:
    path = directory / name
    path.write_bytes(body)
    url = harvester.TRANSCRIPT_BASE + name
    sidecar = {
        "schema": "shelfsignals-source-retrieval@1",
        "request_url": url,
        "retrieved_at": "2026-08-01T20:00:00Z",
        "status": 200,
        "content_type": "text/html",
        "bytes": len(body),
        "sha256": f"sha256:{hashlib.sha256(body).hexdigest()}",
    }
    path.with_suffix(".meta.json").write_text(
        json.dumps(sidecar, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )


def make_pages(directory: Path, *, missing_two: bool = False, duplicate_two: bool = False) -> None:
    first = _page(
        "I",
        1,
        """
<div class="ChapterTitle"><h2>Chapter I</h2></div>
<div class="head2"><strong>Antient History</strong></div>
<div class="CatalogEntry" id="jlp-one">
  <div class="SeqNo">J.1</div>
  <div class="ShortTitle"><em>First short title.</em> <span class="size">2 v. 8vo.</span></div>
  <div class="Author"><span>AUTHOR, Alice.</span></div>
  <div class="LongTitle"><em>First bibliographic title.</em> <span class="pubPlace">London</span>:
    <span class="publisher">Example Press</span>, <span class="pubDate">1776</span>.</div>
  <div class="CallNo">A1 .B2</div>
  <div class="editionStmt"><span class="edition">Second</span> edition.</div>
  <div class="note">Long copyrighted annotation that must never be published.</div>
  <div class="listBibl"><div class="bibl">Editorial bibliography.</div></div>
</div>
""",
        following="I_2.html",
    )
    second_identifier = "1" if duplicate_two else ("" if missing_two else "2")
    second_bid = f'<div class="BIDNo">[{second_identifier}]</div>' if second_identifier else ""
    second = _page(
        "I",
        2,
        f"""
<div class="CatalogEntry" id=""><div class="LongTitle">Continuation.</div><div class="BIDNo">[1]</div></div>
<div class="CatalogEntry" id="jlp-two"><div class="SeqNo">2</div><div class="ShortTitle">Second.</div>{second_bid}</div>
<div class="CatalogEntry" id="jlp-two-a"><div class="SeqNo">2a</div><div class="ShortTitle">Supplement.</div><div class="BIDNo">[2a]</div></div>
<div class="ChapterTitle"><h2>Chapter II</h2></div>
<div class="head2">Modern History—Foreign</div>
<div class="CatalogEntry" id="jlp-three"><div class="SeqNo">1</div><div class="ShortTitle">Third.</div><div class="BIDNo">[3]</div></div>
""",
        previous="I_1.html",
    )
    _write_source_page(directory, "I_1.html", first)
    _write_source_page(directory, "I_2.html", second)


def compile_fixture(directory: Path):
    return harvester.compile_page_directory(
        directory,
        page_limits={"I": 2},
        expected_entry_ranges={"I": (1, 3)},
        expected_entry_count=3,
        expected_chapter_numbers=(1, 2),
        require_sidecars=True,
    )


class SowerbyHarvesterTests(unittest.TestCase):
    def test_nested_subcatalog_fragment_can_complete_parent_entry(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            body = _page(
                "I",
                1,
                """
<div class="ChapterTitle"><h2>Chapter I</h2></div><div class="head2">Antient History</div>
<div class="CatalogEntry" id="parent"><div class="SeqNo">J.1</div><div class="ShortTitle">Main work.</div>
  <div class="SubCatalogEntry" id="component"><div class="ShortTitle">With this is bound.</div>
    <div class="BIDNo">[1]</div></div>
</div>
""",
            )
            _write_source_page(directory, "I_1.html", body)
            entries, exceptions, validation, _ = harvester.compile_page_directory(
                directory,
                page_limits={"I": 1},
                expected_entry_ranges={"I": (1, 1)},
                expected_entry_count=1,
                expected_chapter_numbers=(1,),
            )
            self.assertTrue(validation["all_invariants_passed"])
            self.assertFalse(exceptions)
            self.assertEqual(entries[0]["short_title_spans"], ["Main work.", "With this is bound."])
            self.assertEqual(entries[0]["source"]["container_kinds"], ["CatalogEntry", "SubCatalogEntry"])
            self.assertEqual(entries[0]["source"]["parent_source_html_ids"], ["parent"])

    def test_stitches_continuations_and_emits_only_factual_core(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            make_pages(directory)
            entries, exceptions, validation, source_pages = compile_fixture(directory)

            self.assertEqual([entry["sowerby_number"] for entry in entries], [1, 2, 3])
            self.assertEqual(len(exceptions), 1)
            self.assertEqual(exceptions[0]["sowerby_identifier"], "2a")
            self.assertEqual(validation["entries_spanning_multiple_html_pages"], 1)
            self.assertTrue(validation["all_invariants_passed"])
            self.assertEqual(len(source_pages), 2)

            first = entries[0]
            self.assertEqual(first["sequence_marker"], "J")
            self.assertEqual(first["chapter_number"], 1)
            self.assertEqual(first["faculty"], "History")
            self.assertEqual(first["authors"], ["AUTHOR, Alice."])
            self.assertEqual(first["edition_spans"], ["Second"])
            self.assertEqual(first["sowerby_catalog_call_numbers"], ["A1 .B2"])
            self.assertEqual(len(first["source"]["pages"]), 2)
            serialized = json.dumps(entries, ensure_ascii=False)
            self.assertNotIn("Long copyrighted annotation", serialized)
            self.assertNotIn("Editorial bibliography", serialized)
            keys = {
                key
                for record in entries
                for key in record
            }
            self.assertTrue({"note", "notes", "bibl", "bibliography"}.isdisjoint(keys))

    def test_one_unlabeled_record_can_fill_an_exact_gap_but_is_flagged(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            make_pages(directory, missing_two=True)
            entries, _, validation, _ = compile_fixture(directory)
            self.assertEqual([entry["sowerby_number"] for entry in entries], [1, 2, 3])
            self.assertEqual(validation["base_identifiers_inferred_from_exact_sequence_gaps"], [2])
            self.assertEqual(entries[1]["identifier_kind"], "base_integer_inferred_from_sequence_gap")
            self.assertEqual(entries[1]["source_identifier_raw"], "")

    def test_verified_source_gap_is_a_non_book_placeholder(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            body = _page(
                "I",
                1,
                """
<div class="ChapterTitle"><h2>Chapter I</h2></div><div class="head2">Antient History</div>
<div class="CatalogEntry" id="one"><div class="SeqNo">1</div><div class="ShortTitle">First.</div><div class="BIDNo">[1]</div></div>
<div class="CatalogEntry" id="three"><div class="SeqNo">3</div><div class="ShortTitle">Third.</div><div class="BIDNo">[3]</div></div>
""",
            )
            _write_source_page(directory, "I_1.html", body)
            gap = {
                2: {
                    "volume": "I",
                    "chapter_number": 1,
                    "chapter_roman": "I",
                    "chapter_heading": "Antient History",
                    "adjacent_transcript_pages": [
                        harvester.TRANSCRIPT_BASE + "I_1.html",
                    ],
                    "loc_scan_pages": [harvester.LOC_ITEM_URL],
                    "evidence": "Independent fixture evidence confirms no bibliographic entry exists at this position.",
                }
            }
            entries, _, validation, _ = harvester.compile_page_directory(
                directory,
                page_limits={"I": 1},
                expected_entry_ranges={"I": (1, 3)},
                expected_entry_count=3,
                expected_chapter_numbers=(1,),
                known_source_gap_placeholders=gap,
            )
            self.assertEqual([entry["sowerby_number"] for entry in entries], [1, 2, 3])
            self.assertEqual(entries[1]["entity_type"], "sowerby_entry_gap_placeholder")
            self.assertEqual(entries[1]["short_title_spans"], [])
            self.assertEqual(validation["source_gap_placeholder_numbers"], [2])
            self.assertEqual(validation["source_backed_base_entry_count"], 2)

    def test_explicit_range_resolves_order_without_silent_merge(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            body = _page(
                "I",
                1,
                """
<div class="ChapterTitle"><h2>Chapter I</h2></div><div class="head2">Antient History</div>
<div class="CatalogEntry" id="one"><div class="SeqNo">1</div><div class="BIDNo">[1]</div></div>
<div class="CatalogEntry" id="two"><div class="SeqNo">2</div><div class="ShortTitle">Second.</div></div>
<div class="CatalogEntry" id="three"><div class="SeqNo">3</div><div class="ShortTitle">Third.</div><div class="BIDNo">[2-3]</div></div>
""",
            )
            _write_source_page(directory, "I_1.html", body)
            entries, _, validation, _ = harvester.compile_page_directory(
                directory,
                page_limits={"I": 1},
                expected_entry_ranges={"I": (1, 3)},
                expected_entry_count=3,
                expected_chapter_numbers=(1,),
                known_source_gap_placeholders={},
            )
            self.assertEqual([entry["sowerby_number"] for entry in entries], [1, 2, 3])
            self.assertEqual(validation["base_identifiers_resolved_from_explicit_ranges"], [2, 3])
            self.assertEqual(entries[1]["source_identifier_range"], "[2-3]")
            self.assertEqual(entries[2]["source_identifier_range"], "[2-3]")

    def test_duplicate_base_identifier_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            make_pages(directory, duplicate_two=True)
            with self.assertRaises(harvester.SowerbyError):
                compile_fixture(directory)

    def test_sidecar_hash_mismatch_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            make_pages(directory)
            sidecar_path = directory / "I_1.meta.json"
            sidecar = json.loads(sidecar_path.read_text(encoding="utf-8"))
            sidecar["sha256"] = "sha256:" + "0" * 64
            sidecar_path.write_text(json.dumps(sidecar), encoding="utf-8")
            with self.assertRaisesRegex(harvester.SowerbyError, "sidecar mismatch"):
                compile_fixture(directory)

    def test_page_navigation_gap_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)
            make_pages(directory)
            broken = _page("I", 1, '<div class="ChapterTitle"><h2>Chapter I</h2></div><div class="head2">A</div>')
            _write_source_page(directory, "I_1.html", broken)
            with self.assertRaisesRegex(harvester.SowerbyError, "does not advance"):
                compile_fixture(directory)

    def test_offline_build_is_byte_deterministic(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cache_root = root / "cache"
            generation = "fixture-generation"
            page_dir = cache_root / "generations" / generation / "pages"
            page_dir.mkdir(parents=True)
            make_pages(page_dir)

            # The production build contract is fixed at 4,931 entries, so this
            # test exercises its deterministic primitives with the small parser
            # fixture and then checks active-snapshot resolution separately.
            entries, exceptions, validation, source_pages = compile_fixture(page_dir)
            first = {
                "entries": harvester.jsonl_bytes(entries),
                "exceptions": harvester.jsonl_bytes(exceptions),
                "validation": harvester.json_bytes(validation),
                "source_pages": harvester.jsonl_bytes(source_pages),
            }
            second = {
                "entries": harvester.jsonl_bytes(entries),
                "exceptions": harvester.jsonl_bytes(exceptions),
                "validation": harvester.json_bytes(validation),
                "source_pages": harvester.jsonl_bytes(source_pages),
            }
            self.assertEqual(first, second)

            active = {
                "generation": generation,
                "complete": True,
                "completed_at": "2026-08-01T20:00:00Z",
                "source_snapshot_sha256": validation["source_snapshot_sha256"],
            }
            cache_root.mkdir(exist_ok=True)
            (cache_root / "active.json").write_text(json.dumps(active), encoding="utf-8")
            resolved, loaded = harvester.active_generation(cache_root)
            self.assertEqual(resolved, page_dir)
            self.assertEqual(loaded["generation"], generation)

    def test_network_crawl_requires_explicit_terms_acknowledgement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaises(harvester.SowerbyError):
                harvester.main(["crawl", "--cache-root", temporary])


if __name__ == "__main__":
    unittest.main()
