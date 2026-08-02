#!/usr/bin/env python3

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import stat
import tempfile
import unittest

import build_jefferson_private_ocr_review as builder


@dataclass(frozen=True)
class Line:
    text: str
    left: int
    top: int
    right: int
    bottom: int
    page_width: int = 1000
    page_height: int = 2000
    confidence: float = 92.0


class PrivateOcrReviewTests(unittest.TestCase):
    def test_percent_region_is_padded_bounded_and_deterministic(self) -> None:
        region = builder.percent_region([
            Line("first", 100, 200, 500, 260),
            Line("second", 120, 300, 900, 380),
        ])
        self.assertEqual(region, {"x": 8.5, "y": 8.5, "width": 83.0, "height": 12.0})
        self.assertEqual(
            builder.iiif_region_url("https://tile.loc.gov/image-services/iiif/example", region),
            "https://tile.loc.gov/image-services/iiif/example/pct:8.5,8.5,83,12/1000,/0/default.jpg",
        )

    def test_percent_region_clamps_page_edges(self) -> None:
        region = builder.percent_region([Line("edge", 0, 0, 1000, 2000)])
        self.assertEqual(region, {"x": 0.0, "y": 0.0, "width": 100.0, "height": 100.0})

    def test_iiif_service_accepts_only_loc_image_groups(self) -> None:
        group = [
            {
                "mimetype": "image/jpeg",
                "height": 700,
                "width": 452,
                "url": "https://tile.loc.gov/image-services/iiif/service:test/full/pct:25/0/default.jpg",
            },
            {
                "mimetype": "image/jp2",
                "info": "https://tile.loc.gov/image-services/iiif/service:test/info.json",
            },
        ]
        self.assertEqual(
            builder.iiif_service_from_group(group),
            (
                "https://tile.loc.gov/image-services/iiif/service:test",
                "https://tile.loc.gov/image-services/iiif/service:test/full/pct:25/0/default.jpg",
            ),
        )
        with self.assertRaisesRegex(builder.PrivateOcrError, "no safe JPEG"):
            builder.iiif_service_from_group([{"mimetype": "image/jpeg", "url": "https://example.org/image.jpg"}])

    def test_transcript_is_bounded_without_rewriting_ocr(self) -> None:
        self.assertEqual(
            builder.normalized_transcript([
                Line("  First   line  ", 0, 0, 1, 1),
                Line("Second line", 0, 2, 1, 3),
            ]),
            "First line\nSecond line",
        )

    def test_invalid_timestamp_fails_closed(self) -> None:
        with self.assertRaisesRegex(builder.PrivateOcrError, "whole-second"):
            builder.validate_timestamp("2026-08-02")

    def test_repository_output_must_remain_in_ignored_private_workspace(self) -> None:
        with self.assertRaisesRegex(builder.PrivateOcrError, "git-ignored private-ocr workspace"):
            builder.validate_output_boundary(
                builder.REPOSITORY_ROOT / "docs/private-ocr",
                {"historical core projection": builder.DEFAULT_CORE},
            )

    def test_external_output_is_allowed_but_cannot_overlap_a_source(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "source.json"
            source.write_text("{}\n", encoding="utf-8")
            output = root / "output"
            self.assertEqual(
                builder.validate_output_boundary(output, {"fixture source": source}),
                output.resolve(),
            )
            with self.assertRaisesRegex(builder.PrivateOcrError, "cannot overlap fixture source"):
                builder.validate_output_boundary(source, {"fixture source": source})

    def test_symlink_escape_from_approved_workspace_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory(dir=builder.APPROVED_OUTPUT_ROOT.parent) as temporary:
            root = Path(temporary)
            outside = root / "outside"
            outside.mkdir()
            link = builder.APPROVED_OUTPUT_ROOT / f"unit-test-link-{outside.name}"
            try:
                link.symlink_to(outside, target_is_directory=True)
                with self.assertRaisesRegex(builder.PrivateOcrError, "git-ignored private-ocr workspace"):
                    builder.validate_output_boundary(
                        link / "latest",
                        {"historical core projection": builder.DEFAULT_CORE},
                    )
            finally:
                link.unlink(missing_ok=True)

    def test_private_output_permissions_are_owner_only(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            output = Path(temporary) / "private-ocr"
            target = output / "data/collections/jefferson/ocr-review.json"
            builder.prepare_private_output(output, target)
            builder.atomic_write(target, b"{}\n")
            self.assertEqual(stat.S_IMODE(output.stat().st_mode), 0o700)
            self.assertEqual(stat.S_IMODE(target.stat().st_mode), 0o600)


if __name__ == "__main__":
    unittest.main()
