#!/usr/bin/env python3
"""Verify the authenticated Jefferson photo overlay in a real browser.

This test expects an already running local server whose document root is one
staged private review release. It does not test Cloudflare Access itself; the
Worker contract tests cover the gateway's fail-closed request boundary.
"""

from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = SCRIPT_DIR.parent
DEFAULT_PRIVATE_REVIEW_ROOT = REPOSITORY_ROOT / "research/jefferson/work/private-review"


class BrowserFailure(AssertionError):
    pass


def check(condition: bool, message: str) -> None:
    if not condition:
        raise BrowserFailure(message)


def is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def validate_screenshot_destination(destination: Path) -> Path:
    """Prevent private browser evidence from being written into public/tracked paths."""

    resolved = destination.expanduser().resolve(strict=False)
    repository_root = REPOSITORY_ROOT.resolve(strict=True)
    private_review_root = DEFAULT_PRIVATE_REVIEW_ROOT.resolve(strict=False)
    if is_within(resolved, repository_root) and not is_within(resolved, private_review_root):
        raise BrowserFailure(
            "Repository-local screenshots must remain beneath the ignored private-review root: "
            f"{DEFAULT_PRIVATE_REVIEW_ROOT}"
        )
    return resolved


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-url", required=True)
    parser.add_argument("--browser-channel", default="chrome")
    parser.add_argument("--screenshot")
    parser.add_argument("--timeout-ms", type=int, default=60_000)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    screenshot_destination = validate_screenshot_destination(Path(args.screenshot)) if args.screenshot else None
    try:
        from playwright.sync_api import sync_playwright
    except ImportError as error:
        raise SystemExit(f"Playwright is unavailable: {error}") from error

    target = args.base_url.rstrip("/") + "/?collection=jefferson&corpus=historical&order=sowerby"
    with sync_playwright() as playwright:
        browser_type = playwright.chromium
        launch_options = {"headless": True}
        if args.browser_channel:
            launch_options["channel"] = args.browser_channel
        browser = browser_type.launch(**launch_options)
        context = browser.new_context(
            viewport={"width": 1440, "height": 1000},
            reduced_motion="reduce",
            color_scheme="dark",
        )
        page = context.new_page()
        page.set_default_timeout(args.timeout_ms)
        errors: list[str] = []
        page.on("pageerror", lambda error: errors.append(f"pageerror: {error}"))
        page.on("console", lambda message: errors.append(f"console: {message.text}") if message.type == "error" else None)
        response = page.goto(target, wait_until="domcontentloaded")
        check(response is not None and response.ok, "Private review route did not return HTTP success")
        page.locator("#loadingScreen").wait_for(state="hidden")
        section = page.locator("#jeffersonFieldNotes")
        section.wait_for(state="visible")
        check(page.locator(".private-photo-card").count() == 4, "Expected exactly four authenticated photographs")
        images = page.locator(".private-photo-card img")
        for index in range(images.count()):
            image = images.nth(index)
            image.scroll_into_view_if_needed()
            image.evaluate("element => element.decode()")
        loaded = page.locator(".private-photo-card img").evaluate_all(
            "images => images.every(image => image.complete && image.naturalWidth === 1280 && image.naturalHeight === 960)"
        )
        check(loaded, "One or more private photographs failed to load at the expected dimensions")
        check(
            "visual context only" in page.locator(".private-photo-scope").inner_text(),
            "The evidence-scope warning is missing",
        )
        check(
            "Public reuse is not granted" in page.locator(".private-photo-rights").inner_text(),
            "The private-rights warning is missing",
        )
        check(
            page.locator('.authenticated-review-marker[role="status"]').count() == 1,
            "The persistent authenticated-review marker is missing",
        )
        check(not errors, "Browser emitted errors: " + " | ".join(errors))

        page.set_viewport_size({"width": 390, "height": 844})
        widths = page.locator(".private-photo-card").evaluate_all(
            "cards => cards.map(card => card.getBoundingClientRect().width)"
        )
        check(len(widths) == 4 and min(widths) > 320 and max(widths) < 390, "Private gallery did not collapse to a usable mobile column")
        if screenshot_destination:
            screenshot_destination.parent.mkdir(parents=True, exist_ok=True)
            section.screenshot(path=str(screenshot_destination))
        context.close()
        browser.close()

    print("[PASS] authenticated review gallery: four images, evidence labels, mobile layout, no browser errors")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
