#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import tempfile
import unittest

import build_jefferson_private_review_release as release_builder


def sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


class PrivateReviewReleaseTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.public = self.root / "docs"
        self.media = self.root / "media"
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
        items = []
        for index in range(4):
            body = f"private-jpeg-{index}".encode()
            digest = sha256_bytes(body)
            relative = f"private/jefferson/display/{digest.removeprefix('sha256:')}.jpg"
            path = self.media / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(body)
            items.append({
                "id": f"photo-{index}",
                "entity_type": "exhibition_context_photograph",
                "context_scope": "exhibition_context_only",
                "asset_path": relative,
                "bytes": len(body),
                "sha256": digest,
                "rights": {"public_reuse": "not_granted"},
            })
        manifest = {
            "schema": release_builder.MEDIA_SCHEMA,
            "collection_id": "jefferson",
            "audience": "authenticated_review",
            "items": items,
        }
        path = self.media / "data/collections/jefferson/media-authenticated.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(manifest), encoding="utf-8")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def build(self):
        return release_builder.build_release(
            self.public,
            self.media,
            self.assets,
            self.output,
            generated_at="2026-08-02T02:00:00Z",
        )

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
        manifest["items"][1]["sha256"] = manifest["items"][0]["sha256"]
        manifest["items"][1]["bytes"] = manifest["items"][0]["bytes"]
        manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
        with self.assertRaisesRegex(release_builder.ReleaseError, "four distinct image binaries"):
            self.build()

    def test_rejects_database_in_public_site(self) -> None:
        (self.public / "leak.sqlite").write_bytes(b"not a public projection")
        with self.assertRaisesRegex(release_builder.ReleaseError, "forbidden database"):
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
                self.assets,
                self.public / "private-release",
                generated_at="2026-08-02T02:00:00Z",
            )

    def test_rejects_modified_existing_release(self) -> None:
        release = self.build()
        index = self.output / "releases" / release["release_id"] / "site/index.html"
        index.write_text("tampered", encoding="utf-8")
        with self.assertRaisesRegex(release_builder.ReleaseError, "modified site content"):
            self.build()


if __name__ == "__main__":
    unittest.main()
