#!/usr/bin/env python3
"""Focused tests for the ignored Jefferson private-media bundle."""

from __future__ import annotations

import base64
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from build_jefferson_private_media_bundle import (
    BUNDLE_SCHEMA,
    BundleError,
    build_bundle,
    jpeg_dimensions,
    sha256_file,
)


# A valid 1x1 JPEG; tests patch the external metadata-stripper so the contract
# remains runnable on systems that do not ship jpegtran.
JPEG_1X1 = base64.b64decode(
    "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////"
    "2wBDAf//////////////////////////////////////////////////////////////////////////////////////"
    "wAARCAABAAEDASIAAhEBAxEB/8QAFQABAQAAAAAAAAAAAAAAAAAAAAX/xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oADAMBAAIQAxAAAAF//8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABBQJ//8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAgBAwEBPwF//8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAgBAgEBPwF//8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQAGPwJ//8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPyF//9oADAMBAAIAAwAAABD/xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oACAEDAQE/EH//xAAUEQEAAAAAAAAAAAAAAAAAAAAA/9oACAECAQE/EH//xAAUEAEAAAAAAAAAAAAAAAAAAAAA/9oACAEBAAE/EH//2Q=="
)


class PrivateMediaBundleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.public = self.root / "docs"
        self.public.mkdir()
        (self.public / "index.html").write_text("public", encoding="utf-8")
        self.sources = []
        for index in range(4):
            path = self.root / f"source-{index + 1}.jpg"
            path.write_bytes(JPEG_1X1 + bytes([index]))
            self.sources.append(path)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def fake_sanitize(source: Path, destination: Path, *, jpegtran: str) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(source.read_bytes())

    @staticmethod
    def duplicate_sanitize(source: Path, destination: Path, *, jpegtran: str) -> None:
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(JPEG_1X1)

    def test_jpeg_dimensions_rejects_non_jpeg(self) -> None:
        valid = self.root / "valid.jpg"
        valid.write_bytes(JPEG_1X1)
        self.assertEqual(jpeg_dimensions(valid), (1, 1))
        invalid = self.root / "invalid.jpg"
        invalid.write_bytes(b"not a jpeg")
        with self.assertRaisesRegex(BundleError, "not a JPEG"):
            jpeg_dimensions(invalid)

    @mock.patch("build_jefferson_private_media_bundle.shutil.which", return_value="/test/jpegtran")
    @mock.patch("build_jefferson_private_media_bundle.sanitize_jpeg", side_effect=fake_sanitize.__func__)
    def test_build_is_private_hashed_and_annotation_free(self, _sanitize: mock.Mock, _which: mock.Mock) -> None:
        output = self.root / "private"
        release = build_bundle(
            self.sources,
            output,
            public_root=self.public,
            captured_on="2026-08-01",
            generated_at="2026-08-01T20:00:00Z",
            credit_line="Photograph by project contributor",
            jpegtran="jpegtran",
        )
        manifest = json.loads((output / "data/collections/jefferson/media-authenticated.json").read_text(encoding="utf-8"))
        self.assertEqual(manifest["schema"], BUNDLE_SCHEMA)
        self.assertEqual(manifest["audience"], "authenticated_review")
        self.assertEqual(len(manifest["items"]), 4)
        self.assertNotIn(str(self.root), json.dumps(manifest))
        self.assertTrue(all(item["rights"]["public_reuse"] == "not_granted" for item in manifest["items"]))
        self.assertTrue(all(item["evidence"]["book_level_matches"] == "not_established" for item in manifest["items"]))
        self.assertEqual(release["public_repository_audit"]["matching_private_hashes"], 0)
        self.assertTrue((output / "release.json").is_file())
        for item in manifest["items"]:
            asset = output / item["asset_path"]
            self.assertTrue(asset.is_file())
            self.assertEqual(sha256_file(asset), item["sha256"])

    @mock.patch("build_jefferson_private_media_bundle.shutil.which", return_value="/test/jpegtran")
    @mock.patch("build_jefferson_private_media_bundle.sanitize_jpeg", side_effect=fake_sanitize.__func__)
    def test_public_hash_leak_fails_closed(self, _sanitize: mock.Mock, _which: mock.Mock) -> None:
        (self.public / "leaked.jpg").write_bytes(self.sources[0].read_bytes())
        with self.assertRaisesRegex(BundleError, "present under docs"):
            build_bundle(
                self.sources,
                self.root / "private",
                public_root=self.public,
                captured_on="2026-08-01",
                generated_at="2026-08-01T20:00:00Z",
                credit_line="Photograph by project contributor",
                jpegtran="jpegtran",
            )

    def test_requires_exactly_four_distinct_sources(self) -> None:
        with self.assertRaisesRegex(BundleError, "Exactly 4"):
            build_bundle(
                self.sources[:3],
                self.root / "private",
                public_root=self.public,
                captured_on="2026-08-01",
                generated_at="2026-08-01T20:00:00Z",
                credit_line="Photograph by project contributor",
                jpegtran="jpegtran",
            )

    @mock.patch("build_jefferson_private_media_bundle.shutil.which", return_value="/test/jpegtran")
    @mock.patch("build_jefferson_private_media_bundle.sanitize_jpeg", side_effect=duplicate_sanitize.__func__)
    def test_rejects_duplicate_sanitized_binaries(self, _sanitize: mock.Mock, _which: mock.Mock) -> None:
        with self.assertRaisesRegex(BundleError, "four distinct image binaries"):
            build_bundle(
                self.sources,
                self.root / "private",
                public_root=self.public,
                captured_on="2026-08-01",
                generated_at="2026-08-01T20:00:00Z",
                credit_line="Photograph by project contributor",
                jpegtran="jpegtran",
            )

    @mock.patch("build_jefferson_private_media_bundle.shutil.which", return_value="/test/jpegtran")
    @mock.patch("build_jefferson_private_media_bundle.sanitize_jpeg", side_effect=fake_sanitize.__func__)
    def test_rejects_output_inside_public_site(self, _sanitize: mock.Mock, _which: mock.Mock) -> None:
        with self.assertRaisesRegex(BundleError, "cannot overlap the public site"):
            build_bundle(
                self.sources,
                self.public / "private-media",
                public_root=self.public,
                captured_on="2026-08-01",
                generated_at="2026-08-01T20:00:00Z",
                credit_line="Photograph by project contributor",
                jpegtran="jpegtran",
            )


if __name__ == "__main__":
    unittest.main()
