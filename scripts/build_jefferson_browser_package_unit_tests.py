#!/usr/bin/env python3
"""Offline unit and contract tests for the Jefferson browser-package builder."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import build_jefferson_browser_package as builder


def _json_bytes(value):
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _write_json(path: Path, value) -> None:
    path.write_bytes(_json_bytes(value))


def _write_jsonl(path: Path, values) -> None:
    path.write_bytes(b"".join(_json_bytes(value) for value in values))


def _sha(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def _catalog_record(uuid: str, position: int, *, linked: bool, blank_url: bool = False):
    full_title = (
        "A deliberately extensive source title describing the history, form, publication, interpretation, "
        "circulation, reception, and documentary context of a volume in the Library of Congress catalog "
        "with additional words proving that the lossless title remains available after compact projection"
        if position == 1
        else "A short second title"
    )
    source_id = f"loc:instance:{uuid}"
    return {
        "entity_type": "catalog_instance",
        "id": source_id,
        "instance": {
            "contributors": [
                {"name": COLLECTION_HEADING, "primary": False},
                {"name": f"Primary Author {position}", "primary": True},
                {"name": f"Secondary Contributor {position}", "primary": False},
            ]
        },
        "normalized": {
            "instance_uuid": uuid,
            "title": full_title,
            "index_title": full_title.replace(" with additional words", ""),
            "alternative_titles": [f"Alternative {position}"],
            "call_numbers": [
                {"source": "instance_classification", "type_id": "lc-type", "value": f"A{position} .B{position}"},
                {"source": "item_effective_call_number", "type_id": "item-type", "value": f"A{position} .B{position} Jefferson Coll"},
            ],
            "source_marc_metadata": {"year": f"17{position:02d}"},
            "publication": [{"dateOfPublication": f"17{position:02d}", "place": "Philadelphia", "publisher": "Printer"}],
            "languages": ["eng"],
            "subjects": [{"value": "History--Sources"}],
            "holdings": [
                {
                    "id": f"holding-{position}",
                    "hrid": f"h-{position}",
                    "permanent_location": "Rare Book Reading Room",
                    "discovery_suppress": False,
                }
            ],
            "items": [
                {
                    "id": f"item-{position}",
                    "hrid": f"i-{position}",
                    "call_number": f"A{position} .B{position} Jefferson Coll",
                    "effective_location": "Rare Book Reading Room",
                    "material_type": "Book",
                    "status": "Available",
                    "discovery_suppress": False,
                }
            ],
            "identifiers": [{"type": "LCCN", "value": f"0000000{position}"}],
            "lccns": [f"0000000{position}"],
            "source_types": ["Book"],
            "instance_formats": ["unmediated -- volume"],
            "relationship_to_jefferson": "exact_collection_heading_membership",
            "ownership_or_reconstruction_status": "unresolved",
            "record_url": "" if blank_url else f"https://lccn.loc.gov/0000000{position}",
            "sowerby_numbers": [2] if linked else [],
        },
        "record_sha256": f"sha256:{position:064x}",
        "source": {"position": position, "sort": "title ascending"},
    }


COLLECTION_HEADING = builder.COLLECTION_HEADING


def make_fixture(root: Path, *, explicitly_free: bool = False) -> tuple[Path, str]:
    source = root / "source"
    source.mkdir()
    first_uuid = "11111111-1111-4111-8111-111111111111"
    second_uuid = "22222222-2222-4222-8222-222222222222"
    catalog = [
        _catalog_record(first_uuid, 1, linked=True),
        _catalog_record(second_uuid, 2, linked=False, blank_url=True),
    ]
    _write_jsonl(source / "loc_catalog_instances.jsonl", catalog)

    scope = {
        "selected_catalog_entity_count": 2,
        "evidence_eligible_catalog_entity_count": 1,
        "catalog_entities_not_assessed": 1,
        "method": "one plain base-integer identifier in source MARC 510 subfield c",
    }
    crosswalk = []
    for number in range(1, 6):
        linked = number == 2
        crosswalk.append(
            {
                "assessment_scope": scope,
                "catalog_assessment_status": (
                    "one_candidate_in_bounded_marc_sample" if linked else "not_established_in_bounded_marc_sample"
                ),
                "catalog_digital_links": (
                    [
                        {
                            "catalog_entity_id": f"loc:instance:{first_uuid}",
                            "digital_item_id": "loc:digital:00000001",
                            "match_basis": "normalized LCCN exact",
                            "normalized_lccns": ["00000001"],
                        }
                    ]
                    if linked
                    else []
                ),
                "catalog_entity_ids": [f"loc:instance:{first_uuid}"] if linked else [],
                "digital_item_ids": ["loc:digital:00000001"] if linked else [],
                "evidence": [
                    "source MARC 510 with one plain base-integer identifier"
                    if linked
                    else "not established in bounded sample"
                ],
                "sowerby_base_integer": number,
                "sowerby_reference_id": f"sowerby:{number}",
            }
        )
    _write_jsonl(source / "sowerby_loc_crosswalk.jsonl", crosswalk)

    rights = (
        "This item is free to use and reuse with attribution."
        if explicitly_free
        else "The user is responsible for determining copyright status before reuse."
    )
    _write_jsonl(
        source / "loc_digital_items.jsonl",
        [
            {
                "entity_type": "digital_item",
                "id": "loc:digital:00000001",
                "item_detail": {
                    "item": {
                        "url": "https://www.loc.gov/item/00000001/",
                        "image_url": ["https://tile.loc.gov/example/preview.jpg"],
                        "rights": [rights],
                    },
                    "resources": [],
                },
            }
        ],
    )

    chapters = []
    for number in range(1, 45):
        faculty = "History" if number <= 15 else "Philosophy" if number <= 29 else "Fine Arts"
        chapters.append(
            {
                "chapter_number": number,
                "chapter_roman": str(number),
                "faculty": faculty,
                "heading": f"Chapter {number}",
                "printed_page": number,
                "section": faculty,
                "volume": "I",
            }
        )
    _write_json(
        source / "loc_sowerby_reference.json",
        {
            "base_integer_identifier_count": 5,
            "chapters": chapters,
            "volume_ranges": [
                {"entry_count": 5, "first_sowerby_number": 1, "last_sowerby_number": 5, "volume": "I"}
            ],
        },
    )
    validation = {
        "invariants": {"all_applicable_invariants_passed": True, "failed_invariants": []},
        "crosswalk": {
            "sowerby_references_with_one_catalog_candidate_in_bounded_sample": 1,
            "catalog_entities_assessed_in_bounded_marc_sample": 1,
            "catalog_digital_pair_count": 1,
        },
    }
    _write_json(source / "validation.json", validation)

    manifest_outputs = {}
    key_to_file = {
        "catalog_instances": "loc_catalog_instances.jsonl",
        "loc_sowerby_reference": "loc_sowerby_reference.json",
        "crosswalk": "sowerby_loc_crosswalk.jsonl",
        "digital_items": "loc_digital_items.jsonl",
        "validation": "validation.json",
    }
    for key, filename in key_to_file.items():
        path = source / filename
        manifest_outputs[key] = {"bytes": path.stat().st_size, "sha256": _sha(path)}
    _write_json(
        source / "manifest.json",
        {
            "generated_at": "2026-08-01T17:30:00Z",
            "counts": {
                "loc_exact_catalog_instances": 2,
                "loc_digital_items": 1,
                "loc_sowerby_base_integer_identifiers": 5,
            },
            "outputs": manifest_outputs,
        },
    )
    return source, first_uuid


class JeffersonBrowserPackageTests(unittest.TestCase):
    def test_build_is_deterministic_and_lossless(self):
        with tempfile.TemporaryDirectory() as directory:
            source, first_uuid = make_fixture(Path(directory))
            first = builder.build_package(source)
            second = builder.build_package(source)
            self.assertEqual(first, second)
            self.assertEqual(len(first), 73)

            core = json.loads(first["catalog-core.json"])
            self.assertEqual(core["contract"]["core_fields"], builder.CORE_FIELDS)
            self.assertEqual(core["contract"]["detail_fields"], builder.DETAIL_FIELDS)
            self.assertEqual(core["source"]["record_count"], 2)
            self.assertEqual(len(core["items"]), 2)
            self.assertEqual(core["items"][0][0], f"jefferson-loc-{first_uuid}")
            self.assertLessEqual(len(core["items"][0][2]), 180)
            self.assertEqual(core["items"][0][3], ["Primary Author 1"])
            self.assertEqual(core["items"][1][8], "")
            self.assertEqual(core["items"][0][11], "sowerby_510_exact_bounded")
            self.assertEqual(core["items"][1][11], "collection_heading_only")

            shard = core["items"][0][-1]
            details = json.loads(first[f"catalog-details/{shard:03d}.json"])
            row = next(item for item in details["items"] if item[0] == f"jefferson-loc-{first_uuid}")
            self.assertIn("additional words proving", row[2])
            self.assertEqual(row[16], "unresolved")
            self.assertEqual(row[17], [2])
            self.assertTrue(row[18])
            self.assertEqual(row[8][0]["source"], "instance_classification")
            self.assertEqual(row[9][0]["source"], "item_effective_call_number")

            validation = json.loads(first["validation.json"])
            self.assertTrue(validation["checks"]["full_titles_round_trip_in_detail_shards"])
            self.assertLessEqual(validation["performance"]["core_bytes"], 1_250_000)
            self.assertLessEqual(validation["performance"]["core_gzip_bytes"], 350_000)

    def test_manifest_and_media_are_explicit(self):
        with tempfile.TemporaryDirectory() as directory:
            source, first_uuid = make_fixture(Path(directory))
            files = builder.build_package(source)
            manifest = json.loads(files["manifest.json"])
            self.assertEqual(manifest["defaults"], {"corpus": "catalog", "order": "title"})
            self.assertEqual(manifest["shelf"]["storage_key"], "shelfsignals_shelf:jefferson")
            self.assertFalse(manifest["features"]["physical"])
            self.assertFalse(manifest["features"]["placement"])
            self.assertEqual(manifest["review"]["code_sha256"], builder.REVIEW_CODE_SHA256)
            self.assertIn("2 current LOC catalog instances", manifest["copy"]["coverage_statement"])

            public = json.loads(files["media-public.json"])
            review = json.loads(files["media-review.json"])
            self.assertEqual(public["items"], [])
            self.assertEqual(len(review["items"]), 1)
            self.assertEqual(review["items"][0][0], f"jefferson-loc-{first_uuid}")
            self.assertEqual(review["items"][0][5], "rights_review_required")
            self.assertEqual(review["items"][0][6], "normalized LCCN exact")
            self.assertFalse(any(str(Path(directory)) in data.decode() for data in files.values()))

    def test_explicit_free_reuse_language_can_enter_public_media(self):
        with tempfile.TemporaryDirectory() as directory:
            source, _ = make_fixture(Path(directory), explicitly_free=True)
            public = json.loads(builder.build_package(source)["media-public.json"])
            self.assertEqual(len(public["items"]), 1)
            self.assertEqual(public["items"][0][5], "public_rights_reviewed")

    def test_check_detects_stale_and_unexpected_outputs(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source, _ = make_fixture(root)
            output = root / "output"
            files = builder.build_package(source)
            builder.write_package(files, output)
            builder.check_package(files, output)
            (output / "catalog-core.json").write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(builder.BuildError, "stale: catalog-core.json"):
                builder.check_package(files, output)
            builder.write_package(files, output)
            (output / "catalog-details/stray.txt").write_text("unexpected\n", encoding="utf-8")
            with self.assertRaisesRegex(builder.BuildError, "unexpected: catalog-details/stray.txt"):
                builder.check_package(files, output)

    def test_source_hash_mismatch_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            source, _ = make_fixture(Path(directory))
            with (source / "loc_catalog_instances.jsonl").open("ab") as handle:
                handle.write(b"\n")
            with self.assertRaisesRegex(builder.BuildError, "Source hash/size mismatch"):
                builder.build_package(source)

    def test_inferred_copy_status_fails_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            source, _ = make_fixture(Path(directory))
            records = [json.loads(line) for line in (source / "loc_catalog_instances.jsonl").read_text().splitlines()]
            records[0]["normalized"]["ownership_or_reconstruction_status"] = "original"
            _write_jsonl(source / "loc_catalog_instances.jsonl", records)
            manifest = json.loads((source / "manifest.json").read_text())
            path = source / "loc_catalog_instances.jsonl"
            manifest["outputs"]["catalog_instances"] = {"bytes": path.stat().st_size, "sha256": _sha(path)}
            _write_json(source / "manifest.json", manifest)
            with self.assertRaisesRegex(builder.BuildError, "refuses inferred ownership"):
                builder.build_package(source)

    def test_shards_and_rights_helpers_are_stable(self):
        identifier = "jefferson-loc-11111111-1111-4111-8111-111111111111"
        self.assertEqual(builder.stable_shard(identifier), builder.stable_shard(identifier))
        self.assertTrue(builder._rights_are_explicitly_free(["Free to use and reuse."]))
        self.assertFalse(builder._rights_are_explicitly_free(["User must determine reuse rights."]))
        self.assertEqual(builder.REVIEW_CODE_SHA256, f"sha256:{hashlib.sha256(b'TJ1815').hexdigest()}")


if __name__ == "__main__":
    unittest.main()
