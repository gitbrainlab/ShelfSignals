#!/usr/bin/env python3
"""Focused safety tests for private review browser evidence output."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import private_review_browser_test as browser_test


class PrivateReviewBrowserSafetyTests(unittest.TestCase):
    def test_allows_ignored_private_review_destination(self) -> None:
        destination = browser_test.DEFAULT_PRIVATE_REVIEW_ROOT / "evidence/gallery.png"
        self.assertEqual(browser_test.validate_screenshot_destination(destination), destination.resolve(strict=False))

    def test_allows_destination_outside_repository(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            destination = Path(temporary) / "gallery.png"
            self.assertEqual(browser_test.validate_screenshot_destination(destination), destination.resolve(strict=False))

    def test_rejects_public_or_tracked_repository_destination(self) -> None:
        for destination in (
            browser_test.REPOSITORY_ROOT / "docs/private-gallery.png",
            browser_test.REPOSITORY_ROOT / "scripts/private-gallery.png",
        ):
            with self.subTest(destination=destination):
                with self.assertRaisesRegex(browser_test.BrowserFailure, "ignored private-review root"):
                    browser_test.validate_screenshot_destination(destination)

    def test_rejects_external_symlink_that_resolves_into_public_site(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            link = Path(temporary) / "public"
            link.symlink_to(browser_test.REPOSITORY_ROOT / "docs", target_is_directory=True)
            with self.assertRaisesRegex(browser_test.BrowserFailure, "ignored private-review root"):
                browser_test.validate_screenshot_destination(link / "private-gallery.png")


if __name__ == "__main__":
    unittest.main()
