#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import build_jefferson_private_review_release as release_builder
import jefferson_private_ocr_contract as ocr_contract


def sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def valid_ocr_manifest() -> dict:
    digest = f"sha256:{'a' * 64}"
    entries = []
    for chapter in range(1, 45):
        for offset in range(3):
            serial = (chapter - 1) * 3 + offset + 1
            direct = serial <= 5
            entries.append({
                "record_id": f"jefferson-sowerby-{serial}",
                "sowerby_number": serial,
                "title": f"Source title {serial}",
                "title_status": "source_backed",
                "faculty": "History" if chapter <= 15 else "Philosophy" if chapter <= 29 else "Fine Arts",
                "chapter_number": chapter,
                "chapter_label": f"Chapter {chapter}",
                "volume": 1,
                "terminal_pdf_page": 50,
                "pdf_url": ocr_contract.LOC_PDF_URLS[1],
                "section": {
                    "type": "sowerby_entry_block",
                    "classification_status": "machine_detected_unreviewed",
                    "transcript": f"Machine OCR evidence for Sowerby entry {serial}.",
                    "transcript_truncated": False,
                    "line_count": 2,
                    "mean_confidence": 91.2,
                    "marker_confidence": 94.1,
                    "title_confidence": 90.0,
                },
                "snapshots": [{
                    "pdf_page": 50,
                    "region_pct": {"x": 1, "y": 2, "width": 50, "height": 20},
                    "image_url": "https://tile.loc.gov/image-services/iiif/service:rbc:rbc0001:2007:2007jeffcat1:00551029/pct:1,2,50,20/1000,/0/default.jpg",
                    "full_page_image_url": "https://tile.loc.gov/image-services/iiif/service:rbc:rbc0001:2007:2007jeffcat1:00551029/full/pct:100/0/default.jpg",
                    "line_count": 2,
                    "mean_confidence": 91.2,
                }],
                "event_contexts": [{
                    "event_id": f"event-{chapter}",
                    "title": "Event",
                    "date_label": "1776",
                    "relationship": "documented_interaction" if direct else "chapter_context",
                    "context_score": 95 if direct else 70,
                    "direct_relation": direct,
                    "event_use_status": "documented_interaction" if direct else "not_established",
                    "use_confidence_score": 90 if direct else None,
                }],
            })
    return {
        "schema": ocr_contract.SCHEMA,
        "collection_id": "jefferson",
        "corpus_id": "historical",
        "audience": "authenticated_review",
        "generated_at": "2026-08-02T14:10:00Z",
        "source": {
            "authority": "Library of Congress",
            "item_url": ocr_contract.LOC_ITEM_URL,
            "rights_statement_url": ocr_contract.LOC_ITEM_URL,
            "rights_clearance": "not granted; item-level assessment remains required",
            "source_identity_sha256": digest,
            "ocr_manifest_sha256": digest,
            "historical_core_sha256": digest,
            "insight_graph_sha256": digest,
        },
        "methodology": {
            "selection": "Three entries per chapter.",
            "sectioning": "Machine detected.",
            "visual_evidence": "LOC IIIF regions.",
            "confidence": "OCR mechanics only.",
            "use_boundary": "Context is not use.",
        },
        "coverage": {
            "historical_entries": 4928,
            "page_resolved_entries": 4675,
            "pilot_entries": 132,
            "chapters": 44,
            "entries_per_chapter": 3,
            "section_regions": 132,
            "source_backed_titles": 132,
            "direct_documentary_records": 5,
        },
        "entries": entries,
    }


class PrivateReviewReleaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.public = self.root / "docs"
        self.media = self.root / "media"
        self.ocr = self.root / "ocr"
        self.assets = self.root / "assets"
        self.output = self.root / "output"
        (self.public / "data/collections/jefferson").mkdir(parents=True)
        (self.public / "index.html").write_text(
            '<!doctype html><html><head></head><body><section id="jeffersonOverview"></section></body></html>',
            encoding="utf-8",
        )
        (self.public / "data/collections/jefferson/manifest.json").write_text("{}\n", encoding="utf-8")
        self.assets.mkdir()
        (self.assets / "private-review.css").write_text(".private{}\n", encoding="utf-8")
        (self.assets / "private-review.js").write_text("export {};\n", encoding="utf-8")
        (self.assets / "private-ocr-contract.js").write_text("export {};\n", encoding="utf-8")
        items = []
        for index in range(4):
            body = f"private-jpeg-{index}".encode()
            digest = sha256_bytes(body)
            relative = f"private/jefferson/display/{digest.removeprefix('sha256:')}.jpg"
            path = self.media / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
            items.append({
                "id": f"jefferson-exhibition-{index + 1:02d}",
                "entity_type": "exhibition_context_photograph",
                "context_scope": "exhibition_context_only",
                "asset_path": relative,
                "thumbnail_path": relative,
                "mime_type": "image/jpeg",
                "bytes": len(body),
                "sha256": digest,
                "width": 1280,
                "height": 960,
                "alt": f"Private exhibition photograph {index + 1}.",
                "caption": f"Private exhibition context {index + 1}.",
                "captured_on": "2026-08-01",
                "creator": "Photograph by project contributor",
                "rights": {
                    "status": "contributor_authorized_private_review",
                    "public_reuse": "not_granted",
                    "credit_line": "Photograph by project contributor",
                },
                "evidence": {
                    "source": "project_contributor_upload",
                    "book_level_matches": "not_established",
                    "chapter_labels": "visible_in_photograph_only",
                },
            })
        manifest = {
            "schema": release_builder.MEDIA_SCHEMA,
            "collection_id": "jefferson",
            "audience": "authenticated_review",
            "generated_at": "2026-08-02T01:50:17Z",
            "unit_of_count": "exhibition context photograph",
            "security_notice": "This manifest requires gateway authentication. Possession of this bundle is not access control or public-reuse permission.",
            "items": items,
        }
        path = self.media / "data/collections/jefferson/media-authenticated.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(manifest), encoding="utf-8")
        self.ocr_path = self.ocr / "data/collections/jefferson/ocr-review.json"
        self.ocr_path.parent.mkdir(parents=True, exist_ok=True)
        self.write_ocr(valid_ocr_manifest())

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def build(self):
        return release_builder.build_release(
            self.public,
            self.media,
            self.ocr,
            self.assets,
            self.output,
            generated_at="2026-08-02T02:00:00Z",
        )

    def read_ocr(self) -> dict:
        return json.loads(self.ocr_path.read_text(encoding="utf-8"))

    def write_ocr(self, manifest: dict) -> None:
        self.ocr_path.write_text(json.dumps(manifest, sort_keys=True), encoding="utf-8")

    def test_builds_deterministic_immutable_release_with_overlay(self) -> None:
        first = self.build()
        second = self.build()
        self.assertEqual(first, second)
        release_root = self.output / "releases" / first["release_id"]
        staged_index = (release_root / "site/index.html").read_text(encoding="utf-8")
        self.assertIn(release_builder.HTML_HEAD_MARKER, staged_index)
        self.assertIn(release_builder.HTML_BODY_MARKER, staged_index)
        active = json.loads((self.output / "active.json").read_text(encoding="utf-8"))
        self.assertEqual(active["release_id"], first["release_id"])
        self.assertEqual(first["private_photo_count"], 4)
        self.assertTrue((release_root / "site/data/collections/jefferson/ocr-review.json").is_file())
        self.assertTrue((release_root / "site/private-review/private-ocr-contract.js").is_file())

    def test_rejects_tampered_private_asset(self) -> None:
        manifest_path = self.media / "data/collections/jefferson/media-authenticated.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        (self.media / manifest["items"][0]["asset_path"]).write_bytes(b"tampered")
        with self.assertRaisesRegex(release_builder.ReleaseError, "hash mismatch"):
            self.build()

    def test_rejects_duplicate_private_binary_references(self) -> None:
        manifest_path = self.media / "data/collections/jefferson/media-authenticated.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["items"][1]["asset_path"] = manifest["items"][0]["asset_path"]
        manifest["items"][1]["thumbnail_path"] = manifest["items"][0]["thumbnail_path"]
        manifest["items"][1]["sha256"] = manifest["items"][0]["sha256"]
        manifest["items"][1]["bytes"] = manifest["items"][0]["bytes"]
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(release_builder.ReleaseError, "unique declared identities and binaries"):
            self.build()

    def test_rejects_unknown_private_media_fields_and_local_paths(self) -> None:
        manifest_path = self.media / "data/collections/jefferson/media-authenticated.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest["items"][0]["local_source_path"] = "/Users/private/reviewer.jpg"
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(release_builder.ReleaseError, "exactly the declared fields"):
            self.build()
        self.assertFalse(self.output.exists())

    def test_rejects_database_in_public_site(self) -> None:
        (self.public / "leak.sqlite").write_bytes(b"not a public projection")
        with self.assertRaisesRegex(release_builder.ReleaseError, "forbidden database"):
            self.build()

    def test_rejects_reserved_private_path_in_public_site(self) -> None:
        leaked = self.public / "data/collections/jefferson/ocr-review.json"
        leaked.write_text('{"private":"leak"}\n', encoding="utf-8")
        with self.assertRaisesRegex(release_builder.ReleaseError, "reserved authenticated-review path"):
            self.build()

    def test_rejects_public_site_symlink(self) -> None:
        target = self.public / "target.txt"
        target.write_text("target", encoding="utf-8")
        (self.public / "linked.txt").symlink_to(target)
        with self.assertRaisesRegex(release_builder.ReleaseError, "symlink"):
            self.build()

    def test_rejects_output_inside_public_site(self) -> None:
        with self.assertRaisesRegex(release_builder.ReleaseError, "cannot overlap the public site"):
            release_builder.build_release(
                self.public,
                self.media,
                self.ocr,
                self.assets,
                self.public / "private-release",
                generated_at="2026-08-02T02:00:00Z",
            )

    def test_rejects_incomplete_private_ocr_bundle(self) -> None:
        manifest = self.read_ocr()
        manifest["entries"].pop()
        self.write_ocr(manifest)
        with self.assertRaisesRegex(release_builder.ReleaseError, "exactly 132"):
            self.build()

    def test_rejects_unknown_fields_and_local_paths_before_release(self) -> None:
        manifest = self.read_ocr()
        manifest["entries"][0]["reviewer_path"] = "/Users/private/reviewer.txt"
        self.write_ocr(manifest)
        with self.assertRaisesRegex(release_builder.ReleaseError, "exactly the declared fields"):
            self.build()
        self.assertFalse(self.output.exists())

    def test_rejects_duplicate_json_keys_before_release(self) -> None:
        source = self.ocr_path.read_text(encoding="utf-8")
        needle = '"title": "Source title 1"'
        self.assertIn(needle, source)
        self.ocr_path.write_text(
            source.replace(needle, '"title": "/Users/private/reviewer.txt", "title": "Source title 1"', 1),
            encoding="utf-8",
        )
        with self.assertRaisesRegex(release_builder.ReleaseError, "Duplicate JSON key"):
            self.build()
        self.assertFalse(self.output.exists())

    def test_rejects_external_source_pdf_and_snapshot_urls(self) -> None:
        mutations = (
            lambda manifest: manifest["source"].__setitem__("item_url", "https://evil.example/item"),
            lambda manifest: manifest["entries"][0].__setitem__("pdf_url", "https://evil.example/book.pdf"),
            lambda manifest: manifest["entries"][0]["snapshots"][0].__setitem__("image_url", "https://evil.example/exfil.jpg"),
        )
        original = valid_ocr_manifest()
        for mutate in mutations:
            with self.subTest(mutation=mutate):
                manifest = json.loads(json.dumps(original))
                mutate(manifest)
                self.write_ocr(manifest)
                with self.assertRaisesRegex(release_builder.ReleaseError, "strict release contract"):
                    self.build()
                self.assertFalse(self.output.exists())

    def test_rejects_mismatched_loc_snapshot_page_services(self) -> None:
        manifest = self.read_ocr()
        manifest["entries"][0]["snapshots"][0]["full_page_image_url"] = (
            "https://tile.loc.gov/image-services/iiif/"
            "service:rbc:rbc0001:2007:2007jeffcat1:00561030/full/pct:100/0/default.jpg"
        )
        self.write_ocr(manifest)
        with self.assertRaisesRegex(release_builder.ReleaseError, "different LOC IIIF pages"):
            self.build()

    def test_rejects_malformed_digest(self) -> None:
        manifest = self.read_ocr()
        manifest["source"]["historical_core_sha256"] = "sha256:not-a-digest"
        self.write_ocr(manifest)
        with self.assertRaisesRegex(release_builder.ReleaseError, "SHA-256"):
            self.build()

    def test_rejects_duplicate_snapshot_and_event_evidence(self) -> None:
        for field in ("snapshots", "event_contexts"):
            with self.subTest(field=field):
                manifest = valid_ocr_manifest()
                manifest["entries"][0][field].append(dict(manifest["entries"][0][field][0]))
                manifest["coverage"]["section_regions"] += field == "snapshots"
                self.write_ocr(manifest)
                with self.assertRaisesRegex(release_builder.ReleaseError, "duplicate"):
                    self.build()

    def test_rejects_modified_existing_release(self) -> None:
        release = self.build()
        index = self.output / "releases" / release["release_id"] / "site/index.html"
        index.write_text("tampered", encoding="utf-8")
        with self.assertRaisesRegex(release_builder.ReleaseError, "modified site content"):
            self.build()


if __name__ == "__main__":
    unittest.main()
