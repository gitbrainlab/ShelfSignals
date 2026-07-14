#!/usr/bin/env python3
"""Pillow-free fail-closed tests for cleared local cover ingestion."""

from __future__ import annotations

import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from build_cover_index import CoverIndexError, build_manifests
from cleared_cover_contract import (
    CLEARED_REFERENCES_SCHEMA,
    CONTRACT_VERSION,
    DERIVATIVE_PROFILES,
    INTAKE_SCHEMA,
    ClearedCoverError,
    candidate_fingerprint,
    derivative_asset_set_fingerprint,
    minimal_webp_vp8x,
    public_catalog_identity,
    sha256_bytes,
    sha256_file,
    validate_cleared_references,
    validate_intake_manifest,
)


class ClearedCoverIngestTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.docs_root = self.root / "docs"
        self.source_root = self.root / "private"
        self.source_root.mkdir()
        self.source_path = self.source_root / "front-cover.jpg"
        self.source_path.write_bytes(b"private fixture bytes; never published")
        self.catalog_sha = "sha256:" + "a" * 64
        self.record = {
            "id": "alma991000000000000001",
            "title": "Fixture book",
            "authors": ["Fixture Author"],
            "year": "2001",
            "call_number": "N1 .F59",
            "isbns": ["978-0-374-22626-8"],
            "oclc_numbers": ["(ocolc)123456"],
            "lccn": ["2001-12345"],
            "record_url": "https://library.clarkart.edu/fixture",
        }
        self.source_image = {
            "sha256": sha256_file(self.source_path),
            "width": 640,
            "height": 960,
            "format": "jpeg",
            "bytes": self.source_path.stat().st_size,
        }
        self.intake = self._make_intake()

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def _make_intake(self) -> dict:
        return {
            "schema": INTAKE_SCHEMA,
            "catalog": {"dataset_sha256": self.catalog_sha, "record_count": 1},
            "items": [{
                "catalog_id": self.record["id"],
                "catalog_identity": public_catalog_identity(self.record, self.catalog_sha),
                "provider": "clark",
                "scope": "clark_copy",
                "source_file": self.source_path.name,
                "source": {
                    "source_id": "CLARK-CAPTURE-0001",
                    "source_reference_url": self.record["record_url"],
                    "creator": "Fixture Photographer",
                    "source_date": "2026-07-14",
                },
                "identity": {
                    "front_cover_confirmed": True,
                    "copy_or_edition_confirmed": True,
                    "attestation": "Shelf label and catalog ID were compared with the photographed object.",
                    "matched_identifiers": [{"type": "catalog_id", "value": self.record["id"]}],
                },
                "image": deepcopy(self.source_image),
                "rights": {
                    "basis": "institution_permission",
                    "public_display": True,
                    "derivatives_allowed": True,
                    "license_or_permission_reference": "CLARK-COVER-PERMISSION-0001",
                    "evidence_url": "https://www.clarkart.edu/fixture-rights",
                    "rights_holder": "Fixture Rights Holder",
                    "credit_line": "Fixture credit line",
                    "evidence_note": "Written permission authorizes public display and local WebP derivatives.",
                },
                "review": {
                    "reviewer": "Fixture Reviewer",
                    "reviewed_at": "2026-07-14T00:00:00Z",
                    "evidence_note": "Front-cover role, exact Clark-copy identity, and rights evidence were compared.",
                },
            }],
        }

    def _fake_probe(self, _: Path) -> dict:
        return {**self.source_image, "animated": False}

    def _validated_intake(self) -> list[dict]:
        return validate_intake_manifest(
            self.intake,
            catalog=[self.record],
            catalog_sha256=self.catalog_sha,
            source_root=self.source_root,
            source_probe=self._fake_probe,
        )

    def _make_reference_manifest(self) -> dict:
        intake_item = self._validated_intake()[0]
        pillow_version = "fixture-pillow-1"
        asset_fingerprint = derivative_asset_set_fingerprint(self.source_image, pillow_version)
        asset_key = asset_fingerprint.removeprefix("sha256:")[:20]
        sizes = {"thumbnail": (320, 480), "display": (640, 960)}
        derivatives = []
        for profile in DERIVATIVE_PROFILES:
            profile_name = profile["profile"]
            width, height = sizes[profile_name]
            payload = minimal_webp_vp8x(width, height)
            url = f"images/covers/{self.record['id']}/{asset_key}/cover-{profile_name}.webp"
            path = self.docs_root / url
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
            derivatives.append({
                "profile": profile_name,
                "url": url,
                "width": width,
                "height": height,
                "format": "webp",
                "sha256": sha256_bytes(payload),
                "bytes": len(payload),
                "max_width": profile["max_width"],
                "max_height": profile["max_height"],
            })
        by_profile = {entry["profile"]: entry for entry in derivatives}
        fingerprint = candidate_fingerprint(
            catalog_id=self.record["id"],
            catalog_record_fingerprint_value=intake_item["catalog_identity"]["record_fingerprint"],
            provider=intake_item["provider"],
            scope=intake_item["scope"],
            matched_identifiers=intake_item["identity"]["matched_identifiers"],
            source=intake_item["source"],
            source_image=intake_item["image"],
            rights=intake_item["rights"],
            identity_attestation=intake_item["identity"]["attestation"],
            review=intake_item["review"],
        )
        item = {
            "status": "resolved",
            "provider": "clark",
            "scope": "clark_copy",
            "catalog_identity": intake_item["catalog_identity"],
            "matched_identifiers": intake_item["identity"]["matched_identifiers"],
            "source": intake_item["source"],
            "image": {
                "image_url": by_profile["display"]["url"],
                "thumbnail_url": by_profile["thumbnail"]["url"],
                "width": by_profile["display"]["width"],
                "height": by_profile["display"]["height"],
                "source": deepcopy(self.source_image),
                "derivatives": derivatives,
            },
            "rights": intake_item["rights"],
            "review": {
                "status": "approved",
                **intake_item["review"],
                "candidate_fingerprint": fingerprint,
            },
            "gate_receipt": {
                "front_cover_confirmed": True,
                "copy_or_edition_confirmed": True,
                "visual_check": True,
                "rights_scope": "local_derivatives",
                "identity_attestation": intake_item["identity"]["attestation"],
                "candidate_fingerprint": fingerprint,
            },
            "provenance": {
                "catalog_url": self.record["record_url"],
                "catalog_dataset_sha256": self.catalog_sha,
                "catalog_record_fingerprint": intake_item["catalog_identity"]["record_fingerprint"],
                "source_file_name": self.source_path.name,
                "source_id": intake_item["source"]["source_id"],
                "source_reference_url": intake_item["source"]["source_reference_url"],
                "asset_set_fingerprint": asset_fingerprint,
                "ingested_at": "2026-07-14T01:00:00Z",
            },
        }
        return {
            "schema": CLEARED_REFERENCES_SCHEMA,
            "version": CONTRACT_VERSION,
            "generated_at": "2026-07-14T01:00:00Z",
            "source": {
                "pipeline": "ingest_cleared_covers.py",
                "pipeline_version": CONTRACT_VERSION,
                "catalog_dataset_sha256": self.catalog_sha,
                "catalog_record_count": 1,
                "intake_sha256": "sha256:" + "b" * 64,
                "pillow_version": pillow_version,
            },
            "policy": {
                "unreviewed_items_included": False,
                "original_binaries_included": False,
                "local_derivatives_only": True,
            },
            "summary": {"published": 1, "clark_copy": 1, "exact_edition": 0},
            "items": {self.record["id"]: item},
        }

    def _as_licensed_exact(self, references: dict) -> dict:
        value = deepcopy(references)
        item = value["items"][self.record["id"]]
        item["provider"] = "licensed"
        item["scope"] = "exact_edition"
        item["matched_identifiers"] = [{"type": "isbn", "value": "9780374226268"}]
        item["source"]["source_reference_url"] = "https://example.edu/fixture-exact-edition"
        value["summary"] = {"published": 1, "clark_copy": 0, "exact_edition": 1}
        review = item["review"]
        fingerprint = candidate_fingerprint(
            catalog_id=self.record["id"],
            catalog_record_fingerprint_value=item["catalog_identity"]["record_fingerprint"],
            provider=item["provider"],
            scope=item["scope"],
            matched_identifiers=item["matched_identifiers"],
            source=item["source"],
            source_image=item["image"]["source"],
            rights=item["rights"],
            identity_attestation=item["gate_receipt"]["identity_attestation"],
            review=review,
        )
        item["review"]["candidate_fingerprint"] = fingerprint
        item["gate_receipt"]["candidate_fingerprint"] = fingerprint
        item["provenance"]["source_reference_url"] = item["source"]["source_reference_url"]
        return value

    def test_intake_rebinds_catalog_file_dimensions_and_human_evidence(self) -> None:
        validated = self._validated_intake()
        self.assertEqual(validated[0]["catalog_id"], self.record["id"])
        self.assertEqual(validated[0]["_source_path"], self.source_path.resolve())

    def test_intake_fails_closed_on_each_publication_gate(self) -> None:
        mutations = [
            (lambda value: value["catalog"].__setitem__("dataset_sha256", "sha256:" + "f" * 64), "catalog checksum"),
            (lambda value: value["items"][0]["catalog_identity"].__setitem__("title", "Wrong title"), "catalog snapshot"),
            (lambda value: value["items"][0]["identity"].__setitem__("front_cover_confirmed", False), "front_cover_confirmed"),
            (lambda value: value["items"][0]["rights"].__setitem__("public_display", False), "public_display"),
            (lambda value: value["items"][0]["rights"].__setitem__("derivatives_allowed", False), "derivatives_allowed"),
            (lambda value: value["items"][0]["review"].__setitem__("reviewer", "TBD"), "responsible person"),
            (lambda value: value["items"][0]["image"].__setitem__("width", 641), "decoded source evidence"),
        ]
        for mutate, message in mutations:
            with self.subTest(message=message):
                value = deepcopy(self.intake)
                mutate(value)
                with self.assertRaisesRegex(ClearedCoverError, message):
                    validate_intake_manifest(
                        value,
                        catalog=[self.record],
                        catalog_sha256=self.catalog_sha,
                        source_root=self.source_root,
                        source_probe=self._fake_probe,
                    )

    def test_intake_rejects_unknown_fields_and_path_traversal(self) -> None:
        unknown = deepcopy(self.intake)
        unknown["items"][0]["rights"]["probably_allowed"] = True
        with self.assertRaisesRegex(ClearedCoverError, "unsupported fields"):
            validate_intake_manifest(unknown, catalog=[self.record], catalog_sha256=self.catalog_sha)
        traversal = deepcopy(self.intake)
        traversal["items"][0]["source_file"] = "../front-cover.jpg"
        with self.assertRaisesRegex(ClearedCoverError, "traversal-free"):
            validate_intake_manifest(traversal, catalog=[self.record], catalog_sha256=self.catalog_sha)

    def test_exact_edition_requires_a_real_record_identifier(self) -> None:
        licensed = deepcopy(self.intake)
        item = licensed["items"][0]
        item["provider"] = "licensed"
        item["scope"] = "exact_edition"
        item["source"]["source_reference_url"] = "https://example.edu/exact-edition"
        item["identity"]["matched_identifiers"] = [{"type": "isbn", "value": "9780374226268"}]
        validated = validate_intake_manifest(licensed, catalog=[self.record], catalog_sha256=self.catalog_sha)
        self.assertEqual(validated[0]["scope"], "exact_edition")
        item["identity"]["matched_identifiers"] = [{"type": "isbn", "value": "9780520270947"}]
        with self.assertRaisesRegex(ClearedCoverError, "does not match"):
            validate_intake_manifest(licensed, catalog=[self.record], catalog_sha256=self.catalog_sha)

    def test_reference_contract_reopens_derivatives_and_builds_verified_clark_state(self) -> None:
        references = self._make_reference_manifest()
        validated = validate_cleared_references(
            references,
            catalog=[self.record],
            catalog_sha256=self.catalog_sha,
            docs_root=self.docs_root,
        )
        self.assertEqual(validated[self.record["id"]]["_display_derivative"]["width"], 640)
        index, provenance = build_manifests(
            [self.record],
            {"items": {}},
            generated_at="2026-07-14T02:00:00Z",
            dataset_sha256=self.catalog_sha,
            cleared_references=references,
            docs_root=self.docs_root,
        )
        item = index["items"][self.record["id"]]
        self.assertEqual(item["status"], "verified")
        self.assertEqual(item["provider"], "clark")
        self.assertEqual(item["scope"], "clark_copy")
        self.assertEqual(item["cache_policy"], "local_derivatives")
        self.assertTrue(item["rights"]["derivatives_allowed"])
        self.assertEqual(index["summary"]["verified"], 1)
        public_provenance = provenance["items"][self.record["id"]]
        self.assertEqual(public_provenance["image"]["source"]["sha256"], self.source_image["sha256"])
        self.assertEqual(public_provenance["source"]["provider"], "clark")

    def test_rights_cleared_exact_edition_builds_as_licensed_local_derivative(self) -> None:
        references = self._as_licensed_exact(self._make_reference_manifest())
        index, provenance = build_manifests(
            [self.record],
            {"items": {}},
            generated_at="2026-07-14T02:00:00Z",
            dataset_sha256=self.catalog_sha,
            cleared_references=references,
            docs_root=self.docs_root,
        )
        item = index["items"][self.record["id"]]
        self.assertEqual((item["provider"], item["scope"]), ("licensed", "exact_edition"))
        self.assertEqual(item["label"], "Human-reviewed rights-cleared exact-edition cover")
        self.assertEqual(provenance["items"][self.record["id"]]["matched_identifiers"], [{"type": "isbn", "value": "9780374226268"}])

    def test_reference_and_builder_reject_tampering(self) -> None:
        references = self._make_reference_manifest()
        with self.assertRaisesRegex(CoverIndexError, "require docs_root"):
            build_manifests(
                [self.record],
                {"items": {}},
                generated_at="2026-07-14T02:00:00Z",
                dataset_sha256=self.catalog_sha,
                cleared_references=references,
            )
        item = references["items"][self.record["id"]]
        display_url = item["image"]["image_url"]
        (self.docs_root / display_url).write_bytes(b"tampered")
        with self.assertRaisesRegex(ClearedCoverError, "bytes do not match"):
            validate_cleared_references(
                references,
                catalog=[self.record],
                catalog_sha256=self.catalog_sha,
                docs_root=self.docs_root,
            )
        # Rebuild a clean fixture, then alter the human gate fingerprint.
        references = self._make_reference_manifest()
        references["items"][self.record["id"]]["review"]["candidate_fingerprint"] = "sha256:" + "f" * 64
        with self.assertRaisesRegex(CoverIndexError, "stale or edited candidate fingerprint"):
            build_manifests(
                [self.record],
                {"items": {}},
                generated_at="2026-07-14T02:00:00Z",
                dataset_sha256=self.catalog_sha,
                cleared_references=references,
                docs_root=self.docs_root,
            )


if __name__ == "__main__":
    unittest.main(verbosity=2)
