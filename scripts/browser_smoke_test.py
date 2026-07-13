#!/usr/bin/env python3
"""Browser smoke tests for the primary ShelfSignals static interface.

The suite can either start an isolated static server rooted at ``docs`` or test an
already-running deployment::

    python scripts/browser_smoke_test.py --start-server
    python scripts/browser_smoke_test.py --base-url http://127.0.0.1:8000/

Playwright is intentionally optional for the project. This script never installs
it or its browser; instead, it exits with status 2 and an actionable diagnostic
when either dependency is missing.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import socket
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin
from urllib.request import urlopen


DOCS_DIR = Path(__file__).resolve().parents[1] / "docs"
SHELF_STORAGE_KEY = "shelfsignals_shelf"


class SmokeFailure(AssertionError):
    """An application behavior failed its smoke assertion."""


class DependencyFailure(RuntimeError):
    """The optional browser-test runtime is unavailable."""


def check(condition: bool, message: str) -> None:
    if not condition:
        raise SmokeFailure(message)


def report(label: str) -> None:
    print(f"[PASS] {label}", flush=True)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run browser smoke tests against the primary ShelfSignals interface."
    )
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument(
        "--start-server",
        action="store_true",
        help="Start python -m http.server with ShelfSignals/docs as its root.",
    )
    target.add_argument(
        "--base-url",
        help="Expect an existing static server at this base URL (for example, http://127.0.0.1:8000/).",
    )
    parser.add_argument(
        "--host",
        default="127.0.0.1",
        help="Bind host for --start-server (default: 127.0.0.1).",
    )
    parser.add_argument(
        "--port",
        type=int,
        default=0,
        help="Bind port for --start-server; 0 chooses an available port (default: 0).",
    )
    parser.add_argument(
        "--timeout-ms",
        type=int,
        default=60_000,
        help="Per-operation browser timeout in milliseconds (default: 60000).",
    )
    parser.add_argument(
        "--headed",
        action="store_true",
        help="Show Chromium instead of running headless.",
    )
    parser.add_argument(
        "--browser-channel",
        default=os.environ.get("SHELFSIGNALS_BROWSER_CHANNEL"),
        help="Use an installed Playwright browser channel such as 'chrome' instead of bundled Chromium.",
    )
    parser.add_argument(
        "--screenshot-dir",
        help="After tests pass, capture 1440x900, 1024x768, and 390x844 PNGs in this directory.",
    )
    args = parser.parse_args(argv)
    if not 0 <= args.port <= 65_535:
        parser.error("--port must be between 0 and 65535")
    if args.timeout_ms <= 0:
        parser.error("--timeout-ms must be positive")
    return args


def normalize_base_url(value: str) -> str:
    return value.rstrip("/") + "/"


def route_url(base_url: str, route: str = "") -> str:
    return urljoin(normalize_base_url(base_url), route.lstrip("/"))


def choose_port(host: str) -> int:
    family = socket.AF_INET6 if ":" in host else socket.AF_INET
    with socket.socket(family, socket.SOCK_STREAM) as listener:
        listener.bind((host, 0))
        return int(listener.getsockname()[1])


def browser_host(host: str) -> str:
    if host in {"0.0.0.0", "::", "::0"}:
        return "127.0.0.1"
    return f"[{host}]" if ":" in host and not host.startswith("[") else host


def start_static_server(host: str, port: int) -> Tuple[subprocess.Popen[Any], str]:
    if not DOCS_DIR.is_dir():
        raise SmokeFailure(f"Static document root does not exist: {DOCS_DIR}")
    selected_port = port or choose_port(host)
    command = [
        sys.executable,
        "-m",
        "http.server",
        str(selected_port),
        "--bind",
        host,
        "--directory",
        str(DOCS_DIR),
    ]
    process = subprocess.Popen(
        command,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    return process, f"http://{browser_host(host)}:{selected_port}/"


def stop_static_server(process: Optional[subprocess.Popen[Any]]) -> None:
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait(timeout=5)


def wait_for_server(
    url: str,
    timeout_seconds: float,
    process: Optional[subprocess.Popen[Any]] = None,
) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error: Optional[BaseException] = None
    while time.monotonic() < deadline:
        if process is not None and process.poll() is not None:
            raise SmokeFailure(
                f"Static server exited with status {process.returncode} before {url} became ready."
            )
        try:
            with urlopen(url, timeout=min(2.0, timeout_seconds)) as response:
                if 200 <= response.status < 400:
                    return
                last_error = RuntimeError(f"HTTP {response.status}")
        except (HTTPError, URLError, OSError, TimeoutError) as error:
            last_error = error
        time.sleep(0.1)
    raise SmokeFailure(
        f"Static server did not become ready at {url} within {timeout_seconds:.1f}s"
        + (f": {last_error}" if last_error else ".")
    )


def load_json_url(url: str, timeout_seconds: float) -> Any:
    try:
        with urlopen(url, timeout=timeout_seconds) as response:
            check(response.status == 200, f"Expected HTTP 200 for {url}, got {response.status}.")
            return json.loads(response.read().decode("utf-8"))
    except SmokeFailure:
        raise
    except (HTTPError, URLError, OSError, TimeoutError, UnicodeDecodeError, json.JSONDecodeError) as error:
        raise SmokeFailure(f"Could not load required JSON from {url}: {error}") from error


def collection_records(raw: Any) -> List[Dict[str, Any]]:
    records = raw if isinstance(raw, list) else raw.get("items", []) if isinstance(raw, dict) else []
    valid = [
        record
        for record in records
        if isinstance(record, dict) and record.get("id") and record.get("title")
    ]
    check(bool(valid), "The served ShelfSignals collection has no usable records.")
    return valid


def featured_record(
    records: Sequence[Dict[str, Any]], featured: Any
) -> Dict[str, Any]:
    by_id = {str(record["id"]): record for record in records}
    configured_ids = featured.get("hero", []) if isinstance(featured, dict) else []
    for record_id in configured_ids:
        record = by_id.get(str(record_id))
        if record and str(record.get("record_url", "")).startswith(
            "https://library.clarkart.edu/"
        ):
            return record
    raise SmokeFailure(
        "No configured hero record resolves to a Clark catalog record in the served dataset."
    )


def edition_enrichment_record(
    records: Sequence[Dict[str, Any]], manifest: Any
) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    check(
        isinstance(manifest, dict)
        and manifest.get("schema") == "shelfsignals-edition-enrichment@1"
        and isinstance(manifest.get("items"), dict),
        "The served edition-enrichment manifest is missing or incompatible.",
    )
    by_id = {str(record["id"]): record for record in records}
    items = manifest["items"]
    priorities = ("physical_dimensions", "physical_format", "number_of_pages", None)
    for field in priorities:
        for record_id, item in items.items():
            record = by_id.get(str(record_id))
            if not record or not isinstance(item, dict) or not item.get("candidates"):
                continue
            resolved = item.get("resolved", {})
            if field and field not in resolved:
                continue
            if field == "physical_dimensions":
                formats = string_values(record.get("formats"))
                if any(re.search(r"\d\s*[x×X]\s*\d[^;]*\bcm\b", value) for value in formats):
                    continue
            return record, item
    raise SmokeFailure(
        "No valid exact-edition record is available for enrichment browser testing."
    )


def string_values(value: Any) -> List[str]:
    if isinstance(value, list):
        return [str(item) for item in value if item]
    return [str(value)] if value else []


def short_display_title(title: Any, maximum: int = 92) -> str:
    clean = " ".join(str(title or "Untitled").split())
    responsibility = clean.find(" / ")
    candidate = clean[:responsibility] if responsibility > 10 else clean
    if len(candidate) <= maximum:
        return candidate
    clipped = re.sub(r"\s+\S*$", "", candidate[: maximum - 1]).strip()
    return f"{clipped or candidate[: maximum - 1]}…"


def integer_text(value: str) -> int:
    digits = re.sub(r"\D", "", value)
    check(bool(digits), f"Expected an integer in text, got {value!r}.")
    return int(digits)


def summary_count(value: str) -> int:
    match = re.search(r"([\d,]+)\s+of\s+[\d,]+\s+records", value)
    check(bool(match), f"Unexpected result summary: {value!r}.")
    return int(match.group(1).replace(",", ""))


class BrowserErrors:
    """Collect JavaScript console errors and uncaught page exceptions."""

    def __init__(self, page: Any) -> None:
        self.errors: List[str] = []
        page.on("console", self._on_console)
        page.on("pageerror", self._on_page_error)

    def _on_console(self, message: Any) -> None:
        if message.type == "error":
            source_page = getattr(message, "page", None)
            source_url = source_page.url if source_page is not None else "unknown URL"
            self.errors.append(f"console error at {source_url}: {message.text}")

    def _on_page_error(self, error: Any) -> None:
        self.errors.append(f"uncaught page error: {error}")

    def assert_clean(self, label: str) -> None:
        if self.errors:
            details = "\n  - ".join(self.errors)
            raise SmokeFailure(f"{label} emitted browser errors:\n  - {details}")
        report(f"{label}: no console errors or uncaught page errors")


def assert_response(response: Any, label: str) -> None:
    check(response is not None, f"{label} navigation returned no main-document response.")
    check(response.ok, f"{label} returned HTTP {response.status}.")


def wait_for_primary_app(page: Any, base_url: str, timeout_ms: int) -> None:
    response = page.goto(
        route_url(base_url), wait_until="domcontentloaded", timeout=timeout_ms
    )
    assert_response(response, "Primary route")
    page.locator("#collectionGrid .book-card").first.wait_for(
        state="visible", timeout=timeout_ms
    )
    page.locator("#loadingScreen").wait_for(state="hidden", timeout=timeout_ms)


def run_primary_flow(
    browser: Any,
    base_url: str,
    records: Sequence[Dict[str, Any]],
    hero_record: Dict[str, Any],
    timeout_ms: int,
) -> None:
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    page = context.new_page()
    page.set_default_timeout(timeout_ms)
    errors = BrowserErrors(page)
    try:
        wait_for_primary_app(page, base_url, timeout_ms)
        check("ShelfSignals" in page.title(), "Primary route title does not identify ShelfSignals.")
        check(
            page.locator('button[role="listitem"]').count() == 0,
            "Primary route assigns the prohibited listitem role to native buttons.",
        )
        check(
            page.evaluate(
                "['detailDrawer', 'shelfDrawer'].every(id => document.getElementById(id)?.inert)"
            ),
            "A closed primary drawer remains keyboard-focusable.",
        )
        check(
            page.evaluate(
                "['detailDrawer', 'shelfDrawer'].every(id => { const el = document.getElementById(id); return el?.getAttribute('role') === 'dialog' && el?.getAttribute('aria-modal') === 'true'; })"
            ),
            "Primary drawers do not expose modal dialog semantics.",
        )
        check(
            page.locator("#activeFilters").get_attribute("role") == "group",
            "Active filters do not expose a valid labelled group role.",
        )
        report("primary ARIA roles and closed-drawer focus isolation are valid")
        displayed_total = integer_text(page.locator("#collectionCount").inner_text())
        check(
            displayed_total == len(records),
            f"Primary route reports {displayed_total} records; served dataset has {len(records)}.",
        )
        report(f"primary route loaded all {displayed_total:,} served records")

        title = str(hero_record["title"])
        authors = string_values(hero_record.get("authors"))
        expected_aria = f"Open {title}" + (f" by {authors[0]}" if authors else "")
        first_hero = page.locator("#heroStage .hero-book").first
        check(
            first_hero.get_attribute("aria-label") == expected_aria,
            "First hero book does not expose the configured dataset title and author.",
        )
        check(
            page.locator("#heroFocusTitle").inner_text().strip()
            == short_display_title(title),
            "Hero focus title does not match the configured dataset record.",
        )
        hero_meta = page.locator("#heroFocusMeta").inner_text().strip()
        if authors:
            check(
                authors[0].casefold() in hero_meta.casefold(),
                "Hero focus omits the dataset author.",
            )
        call_number = str(hero_record.get("call_number") or "")
        if call_number:
            check(call_number in hero_meta, "Hero focus omits the dataset call number.")
        report("hero title, author, and call number come from the served dataset")

        image_signal = page.locator('#signalFilters input[value="image"]')
        check(image_signal.count() == 1, "The Image signal filter was not rendered.")
        image_signal.check()
        page.wait_for_function(
            """total => {
              const match = document.querySelector('#resultSummary')?.textContent.match(/^([\\d,]+) of/);
              return match && Number(match[1].replaceAll(',', '')) > 0
                && Number(match[1].replaceAll(',', '')) < total;
            }""",
            arg=displayed_total,
            timeout=timeout_ms,
        )
        filtered_count = summary_count(page.locator("#resultSummary").inner_text())
        check(
            0 < filtered_count < displayed_total,
            "Applying the Image signal did not change the record count.",
        )
        report(f"signal filter changed count from {displayed_total:,} to {filtered_count:,}")
        page.locator("#resetFilters").click()
        page.wait_for_function(
            """total => {
              const match = document.querySelector('#resultSummary')?.textContent.match(/^([\\d,]+) of/);
              return match && Number(match[1].replaceAll(',', '')) === total;
            }""",
            arg=displayed_total,
            timeout=timeout_ms,
        )

        page.locator('.view-button[data-view="spines"]').click()
        page.locator("#collectionGrid .spine-book").first.wait_for(
            state="visible", timeout=timeout_ms
        )
        check(
            page.locator("#profileMethod").is_visible(),
            "Physical view does not disclose its catalog/estimate method.",
        )
        check(
            "modeled" in page.locator("#profileMethod").inner_text().casefold(),
            "Physical view does not disclose its modeled spine depth.",
        )
        first_spine_width = page.locator("#collectionGrid .spine-book").first.evaluate(
            "element => element.style.getPropertyValue('--spine-width')"
        )
        check(
            bool(re.fullmatch(r"\d+px", first_spine_width)),
            "Physical shelf did not receive a bounded profile width.",
        )
        page.locator('.view-button[data-view="covers"]').click()
        page.locator("#collectionGrid .book-card").first.wait_for(
            state="visible", timeout=timeout_ms
        )
        report("Physical view discloses provenance and renders profile-based shelf geometry")

        record_id = str(hero_record["id"])
        page.locator("#collectionSearch").fill(record_id)
        result_card = page.locator(
            f'#collectionGrid .book-card[data-record-id="{record_id}"]'
        )
        result_card.wait_for(state="visible", timeout=timeout_ms)
        searched_count = summary_count(page.locator("#resultSummary").inner_text())
        check(
            0 < searched_count < displayed_total,
            "Searching a real catalog identifier did not narrow the collection.",
        )
        check(
            page.locator("#collectionSearch").input_value() == record_id,
            "Collection search did not retain the real catalog identifier query.",
        )
        report(f"search located dataset record {record_id}")

        result_card.click()
        drawer = page.locator("#detailDrawer")
        drawer.wait_for(state="visible", timeout=timeout_ms)
        check(
            drawer.get_attribute("aria-hidden") == "false",
            "Record detail drawer did not expose its open state.",
        )
        check(
            not drawer.evaluate("element => element.inert"),
            "Open record detail drawer is still inert.",
        )
        page.wait_for_function(
            "document.activeElement?.id === 'closeDetail'", timeout=timeout_ms
        )
        check(
            page.evaluate(
                "[document.querySelector('.site-header'), document.querySelector('main'), document.querySelector('.site-footer')].every(element => element?.inert)"
            ),
            "Open detail drawer does not isolate the background page.",
        )
        check(
            page.locator("#detailVisual .book-object").get_attribute("aria-hidden") == "true",
            "Decorative detail book repeats the record's accessible title and metadata.",
        )
        check(
            page.locator("#detailTitle").inner_text().strip() == title,
            "Detail drawer title does not exactly match the dataset record.",
        )
        if call_number:
            check(
                call_number in page.locator("#detailKicker").inner_text(),
                "Detail drawer omits the dataset call number.",
            )
        record_url = str(hero_record.get("record_url") or "")
        check(
            record_url.startswith("https://library.clarkart.edu/"),
            "Selected dataset record does not have a Clark catalog URL.",
        )
        rendered_catalog_url = page.locator("#catalogLink").evaluate(
            "element => element.href"
        )
        check(
            rendered_catalog_url == record_url,
            "Clark catalog link differs from the record_url in the served dataset:\n"
            f"  rendered: {rendered_catalog_url}\n  dataset:  {record_url}",
        )
        report("detail drawer exposes exact dataset metadata and Clark record_url")

        physical_formats = string_values(hero_record.get("formats"))
        check(
            page.locator("#physicalMetrics").is_visible(),
            "Detail drawer does not expose the physical profile.",
        )
        physical_metrics_text = page.locator("#physicalMetrics").inner_text()
        check(
            "clark catalog" in physical_metrics_text.casefold(),
            "Physical profile does not identify catalog-stated measurements: "
            f"{physical_metrics_text!r}",
        )
        if physical_formats:
            check(
                physical_formats[0] in page.locator("#physicalEvidence").inner_text(),
                "Physical evidence does not preserve the served catalog description.",
            )
        check(
            "estimated from extent" in physical_metrics_text.casefold(),
            "Physical depth is not explicitly labeled as estimated from extent: "
            f"{physical_metrics_text!r}",
        )
        report("detail physical profile preserves Clark evidence and estimation labels")

        page.locator("#detailShelfButton").click()
        page.locator("#shelfCount").wait_for(state="visible", timeout=timeout_ms)
        page.wait_for_function(
            "document.querySelector('#shelfCount')?.textContent === '1'",
            timeout=timeout_ms,
        )
        page.reload(wait_until="domcontentloaded", timeout=timeout_ms)
        page.locator("#collectionGrid .book-card").first.wait_for(
            state="visible", timeout=timeout_ms
        )
        page.locator("#loadingScreen").wait_for(state="hidden", timeout=timeout_ms)
        page.wait_for_function(
            "document.querySelector('#shelfCount')?.textContent === '1'",
            timeout=timeout_ms,
        )
        saved_ids = page.evaluate(
            "key => JSON.parse(localStorage.getItem(key) || '[]')", SHELF_STORAGE_KEY
        )
        check(saved_ids == [record_id], "My Shelf localStorage did not survive reload.")
        if page.locator("#detailDrawer").get_attribute("aria-hidden") == "false":
            page.locator("#closeDetail").click()
            check(
                page.locator("#detailDrawer").evaluate("element => element.inert"),
                "Closed record detail drawer remains focusable.",
            )
        page.locator("#openShelf").click()
        page.locator("#shelfDrawer").wait_for(state="visible", timeout=timeout_ms)
        check(
            not page.locator("#shelfDrawer").evaluate("element => element.inert"),
            "Open My Shelf drawer is still inert.",
        )
        check(
            page.locator("#shelfList .shelf-item").count() == 1,
            "Reloaded My Shelf does not render the saved record.",
        )
        check(
            page.locator("#shelfList .shelf-item strong").inner_text().strip()
            == short_display_title(title),
            "Reloaded My Shelf entry does not match the saved dataset title.",
        )
        report("My Shelf persists the selected real record across reload")
        errors.assert_clean("primary browsing flow")
    finally:
        context.close()


def run_reduced_motion_flow(browser: Any, base_url: str, timeout_ms: int) -> None:
    context = browser.new_context(
        viewport={"width": 1280, "height": 900}, reduced_motion="reduce"
    )
    page = context.new_page()
    page.set_default_timeout(timeout_ms)
    errors = BrowserErrors(page)
    try:
        wait_for_primary_app(page, base_url, timeout_ms)
        check(
            page.evaluate("matchMedia('(prefers-reduced-motion: reduce)').matches"),
            "Chromium context did not expose the reduced-motion preference.",
        )
        transition_ms = page.locator("#detailDrawer").evaluate(
            """element => Math.max(...getComputedStyle(element).transitionDuration
              .split(',').map(value => value.trim().endsWith('ms')
                ? Number.parseFloat(value)
                : Number.parseFloat(value) * 1000))"""
        )
        check(
            transition_ms <= 0.01,
            f"Reduced-motion detail transition is still {transition_ms}ms.",
        )
        focused_transform = page.locator("#heroStage .hero-book.is-focused").evaluate(
            "element => getComputedStyle(element).transform"
        )
        check(
            focused_transform == "none",
            f"Reduced-motion focused hero book still transforms ({focused_transform}).",
        )
        report("reduced-motion preference suppresses cinematic transitions and transforms")
        errors.assert_clean("reduced-motion flow")
    finally:
        context.close()


def run_cover_failure_flow(
    browser: Any, base_url: str, hero_record: Dict[str, Any], timeout_ms: int
) -> None:
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    page = context.new_page()
    page.set_default_timeout(timeout_ms)
    page.route("https://covers.openlibrary.org/**", lambda route: route.abort())
    errors = BrowserErrors(page)
    try:
        wait_for_primary_app(page, base_url, timeout_ms)
        record_id = str(hero_record["id"])
        page.locator("#collectionSearch").fill(record_id)
        card = page.locator(f'#collectionGrid .book-card[data-record-id="{record_id}"]')
        card.wait_for(state="visible", timeout=timeout_ms)
        book = card.locator(".book-object")
        page.wait_for_function(
            "element => !element.classList.contains('has-cover')",
            arg=book.element_handle(),
            timeout=timeout_ms,
        )
        check(
            book.locator(".book-cover-title").inner_text().strip()
            == short_display_title(hero_record["title"]),
            "Failed remote cover did not preserve the metadata-derived fallback title.",
        )
        report("remote cover failure falls back to the real metadata-derived book object")
        unexpected = [
            error for error in errors.errors if "net::ERR_FAILED" not in error
        ]
        check(
            not unexpected,
            f"Cover failure flow emitted errors unrelated to the intentionally aborted images: {unexpected}",
        )
        report("cover failure flow emitted only the intentionally aborted image requests")
    finally:
        context.close()


def run_edition_enrichment_flow(
    browser: Any,
    base_url: str,
    record: Dict[str, Any],
    manifest_item: Dict[str, Any],
    timeout_ms: int,
) -> None:
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    page = context.new_page()
    page.set_default_timeout(timeout_ms)
    errors = BrowserErrors(page)
    try:
        wait_for_primary_app(page, base_url, timeout_ms)
        record_id = str(record["id"])
        page.locator("#collectionSearch").fill(record_id)
        page.locator('.view-button[data-view="spines"]').click()
        spine = page.locator(
            f'#collectionGrid .spine-book[data-record-id="{record_id}"]'
        )
        spine.wait_for(state="visible", timeout=timeout_ms)
        page.wait_for_function(
            "element => element.classList.contains('has-edition-evidence')",
            arg=spine.element_handle(),
            timeout=timeout_ms,
        )
        check(
            spine.locator(".spine-title").inner_text().strip()
            == short_display_title(record["title"]),
            "Enriched spine title does not match the served catalog record.",
        )
        check(
            spine.locator(".spine-evidence").count() == 1,
            "Exact-edition spine does not expose its evidence marker.",
        )
        check(
            spine.locator(".spine-meta").count() == 1,
            "Enriched spine does not expose real compact catalog metadata.",
        )
        spine.click()
        page.locator("#detailDrawer").wait_for(state="visible", timeout=timeout_ms)
        page.locator("#detailEdition").wait_for(state="visible", timeout=timeout_ms)
        note = page.locator("#editionEvidenceNote").inner_text().casefold()
        check(
            "provider edition" in note and "not evidence about the clark copy" in note,
            f"External-edition disclosure is incomplete: {note!r}",
        )
        source_url = page.locator("#editionEvidenceLink").get_attribute("href") or ""
        check(
            bool(re.fullmatch(r"https://openlibrary\.org/books/OL\d+M", source_url)),
            f"External-edition link is not a validated Open Library edition URL: {source_url!r}",
        )
        metadata_text = page.locator("#editionMetadata").inner_text().casefold()
        check(
            "exact" in metadata_text and "open library id" in metadata_text,
            "External-edition panel omits its match method or provider record ID.",
        )
        formats = string_values(record.get("formats"))
        dimensions_fill_a_gap = (
            "physical_dimensions" in manifest_item.get("resolved", {})
            and not any(
                re.search(r"\d\s*[x×X]\s*\d[^;]*\bcm\b", value)
                for value in formats
            )
        )
        if dimensions_fill_a_gap:
            check(
                "open library edition" in page.locator("#physicalMetrics").inner_text().casefold(),
                "A gap-filling exact-edition dimension is not labeled Open Library edition.",
            )
        report(
            "exact-edition metadata enriches the real spine and detail with copy-scope disclosure"
        )
        errors.assert_clean("edition enrichment flow")
    finally:
        context.close()


def run_edition_failure_flow(
    browser: Any, base_url: str, timeout_ms: int
) -> None:
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    page = context.new_page()
    page.set_default_timeout(timeout_ms)
    page.route(route_url(base_url, "data/book_editions.json"), lambda route: route.abort())
    errors = BrowserErrors(page)
    try:
        wait_for_primary_app(page, base_url, timeout_ms)
        page.wait_for_timeout(1800)
        page.locator('.view-button[data-view="spines"]').click()
        page.locator("#collectionGrid .spine-book").first.wait_for(
            state="visible", timeout=timeout_ms
        )
        check(
            page.locator("#collectionGrid .spine-book").count() > 0,
            "The Clark-only shelf disappeared when external enrichment failed.",
        )
        check(
            page.locator("#collectionGrid .spine-book.has-edition-evidence").count() == 0,
            "A failed manifest request left an unverified edition-evidence marker.",
        )
        report("edition-manifest failure preserves the complete Clark-only browser")
        unexpected = [error for error in errors.errors if "net::ERR_FAILED" not in error]
        check(
            not unexpected,
            "Edition failure flow emitted errors unrelated to the intentionally aborted manifest: "
            f"{unexpected}",
        )
        report("edition failure flow emitted only the intentionally aborted manifest request")
    finally:
        context.close()


def run_mobile_flow(browser: Any, base_url: str, timeout_ms: int) -> None:
    context = browser.new_context(
        viewport={"width": 390, "height": 844},
        device_scale_factor=2,
        is_mobile=True,
        has_touch=True,
    )
    page = context.new_page()
    page.set_default_timeout(timeout_ms)
    errors = BrowserErrors(page)
    try:
        wait_for_primary_app(page, base_url, timeout_ms)
        check(page.locator("#heroTitle").is_visible(), "Mobile hero heading is not visible.")
        check(
            page.locator("#heroStage .hero-book").count() > 0,
            "Mobile hero has no browsable books.",
        )
        check(
            page.locator(".primary-nav").evaluate(
                "element => getComputedStyle(element).display"
            )
            == "none",
            "Desktop primary navigation remains visible at the mobile breakpoint.",
        )
        filter_toggle = page.locator("#toggleFilters")
        check(filter_toggle.is_visible(), "Mobile filter disclosure is not visible.")
        check(
            filter_toggle.get_attribute("aria-expanded") == "false"
            and page.locator(".filters-panel").evaluate(
                "element => element.classList.contains('mobile-collapsed')"
            ),
            "Mobile filters are not collapsed by default.",
        )
        filter_toggle.click()
        check(
            filter_toggle.get_attribute("aria-expanded") == "true"
            and page.locator("#collectionSearch").is_visible(),
            "Mobile filter disclosure does not reveal its controls.",
        )
        target_heights = page.locator(".filter-heading button, .filter-options label").evaluate_all(
            "elements => elements.map(element => element.getBoundingClientRect().height)"
        )
        check(
            target_heights and min(target_heights) >= 24,
            f"Mobile filter targets fall below 24 CSS pixels: {min(target_heights) if target_heights else 'none'}.",
        )
        filter_toggle.click()
        columns = page.locator("#collectionGrid").evaluate(
            "element => getComputedStyle(element).gridTemplateColumns.split(/\\s+/).filter(Boolean).length"
        )
        check(columns == 2, f"Mobile cover grid renders {columns} columns instead of 2.")
        check(
            page.evaluate(
                "document.documentElement.scrollWidth <= document.documentElement.clientWidth + 2"
            ),
            "Primary route has document-level horizontal overflow at 390px.",
        )
        mobile_metrics = page.evaluate(
            """() => {
              const title = document.querySelector('#heroTitle').getBoundingClientRect();
              const wordmark = document.querySelector('.wordmark').getBoundingClientRect();
              return { width: innerWidth, scrollX, titleLeft: title.left, titleRight: title.right,
                wordmarkLeft: wordmark.left, wordmarkRight: wordmark.right };
            }"""
        )
        check(
            mobile_metrics["scrollX"] == 0
            and mobile_metrics["titleLeft"] >= -1
            and mobile_metrics["titleRight"] <= mobile_metrics["width"] + 1
            and mobile_metrics["wordmarkLeft"] >= -1
            and mobile_metrics["wordmarkRight"] <= mobile_metrics["width"] + 1,
            f"Mobile heading or wordmark is clipped: {mobile_metrics}",
        )
        report("mobile viewport renders collapsible filters, responsive hero, and two-column collection")
        errors.assert_clean("mobile flow")
    finally:
        context.close()


def run_compatibility_routes(browser: Any, base_url: str, timeout_ms: int) -> None:
    routes = [
        ("legacy/", "ShelfSignals Legacy", "#loadingOverlay", "#shelfRows > *"),
        ("preview/", "ShelfSignals Preview", "#loadingOverlay", "#shelfRows > *"),
        ("preview/exhibit/", "ShelfSignals Exhibit", "#loadingOverlay", "#pathsGrid > *"),
    ]
    for route, expected_title, loader, content in routes:
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        page = context.new_page()
        page.set_default_timeout(timeout_ms)
        errors = BrowserErrors(page)
        try:
            response = page.goto(
                route_url(base_url, route),
                wait_until="domcontentloaded",
                timeout=timeout_ms,
            )
            assert_response(response, f"{expected_title} route")
            check(
                expected_title in page.title(),
                f"{route} title does not identify {expected_title}.",
            )
            page.locator(loader).wait_for(state="hidden", timeout=timeout_ms)
            page.locator(content).first.wait_for(state="visible", timeout=timeout_ms)
            if route == "legacy/":
                check(
                    page.locator("#deprecationNotice").evaluate(
                        "element => element.tagName === 'ASIDE'"
                    ),
                    "Legacy archive notice is outside a landmark.",
                )
            elif route == "preview/":
                check(
                    page.locator('.spines[role="group"]').count() > 0
                    and page.locator('.spines[role="list"]').count() == 0,
                    "Preview shelves expose an invalid list without listitem children.",
                )
            elif route == "preview/exhibit/":
                check(
                    page.locator(".action-card").evaluate_all(
                        "elements => elements.length === 3 && elements.every(element => element.tagName === 'BUTTON')"
                    ),
                    "Exhibit primary actions are not native keyboard-operable buttons.",
                )
                check(
                    page.evaluate(
                        "['detailsDrawer', 'shelfPanel'].every(id => document.getElementById(id)?.inert)"
                    ),
                    "A closed Exhibit drawer remains keyboard-focusable.",
                )
            report(f"{expected_title} compatibility route loaded")
            errors.assert_clean(f"{expected_title} route")
        finally:
            context.close()


def capture_qa_screenshots(
    browser: Any, base_url: str, output_dir: str, timeout_ms: int
) -> None:
    directory = Path(output_dir).expanduser().resolve()
    directory.mkdir(parents=True, exist_ok=True)
    targets = [
        ("desktop", 1440, 900, False),
        ("tablet", 1024, 768, False),
        ("mobile", 390, 844, True),
    ]
    for label, width, height, mobile in targets:
        context = browser.new_context(
            viewport={"width": width, "height": height},
            device_scale_factor=1,
            is_mobile=mobile,
            has_touch=mobile,
        )
        page = context.new_page()
        page.set_default_timeout(timeout_ms)
        try:
            wait_for_primary_app(page, base_url, timeout_ms)
            page.screenshot(
                path=str(directory / f"cinematic-{label}.png"),
                full_page=False,
                animations="disabled",
            )
            page.locator('.view-button[data-view="spines"]').click()
            page.locator("#collectionTitle").evaluate(
                "element => window.scrollTo(0, element.getBoundingClientRect().top + scrollY - 84)"
            )
            page.wait_for_timeout(80)
            page.locator("#collectionGrid .spine-book").first.wait_for(
                state="visible", timeout=timeout_ms
            )
            page.screenshot(
                path=str(directory / f"physical-{label}.png"),
                full_page=False,
                animations="disabled",
            )
            if label == "desktop":
                page.locator("#collectionGrid .spine-book").first.click()
                page.locator("#detailDrawer").wait_for(state="visible", timeout=timeout_ms)
                page.locator("#detailPhysical").scroll_into_view_if_needed()
                page.screenshot(
                    path=str(directory / "physical-detail-desktop.png"),
                    full_page=False,
                    animations="disabled",
                )
        finally:
            context.close()
    legacy_context = browser.new_context(viewport={"width": 1440, "height": 900})
    legacy_page = legacy_context.new_page()
    legacy_page.set_default_timeout(timeout_ms)
    try:
        response = legacy_page.goto(
            route_url(base_url, "legacy/"),
            wait_until="domcontentloaded",
            timeout=timeout_ms,
        )
        assert_response(response, "Legacy screenshot route")
        legacy_page.locator("#loadingOverlay").wait_for(state="hidden", timeout=timeout_ms)
        legacy_page.screenshot(
            path=str(directory / "legacy-before.png"),
            full_page=False,
            animations="disabled",
        )
    finally:
        legacy_context.close()
    report(f"captured visual QA screenshots in {directory}")


def load_playwright() -> Tuple[Any, Any]:
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ModuleNotFoundError as error:
        raise DependencyFailure(
            "Python Playwright is not installed. Install the optional test dependency with "
            "`python -m pip install playwright`, then install Chromium with "
            "`python -m playwright install chromium`."
        ) from error
    return sync_playwright, PlaywrightError


def is_missing_browser_error(error: BaseException) -> bool:
    message = str(error).lower()
    return any(
        phrase in message
        for phrase in (
            "executable doesn't exist",
            "executable does not exist",
            "please run the following command to download new browsers",
            "playwright install",
        )
    )


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    server: Optional[subprocess.Popen[Any]] = None
    browser = None
    try:
        sync_playwright, PlaywrightError = load_playwright()
        with sync_playwright() as playwright:
            chromium_path = playwright.chromium.executable_path
            if not args.browser_channel and (not chromium_path or not os.path.isfile(chromium_path)):
                raise DependencyFailure(
                    "Playwright Chromium is not installed at its expected path "
                    f"({chromium_path or 'unknown'}). Run "
                    "`python -m playwright install chromium` before this smoke test."
                )

            if args.start_server:
                server, base_url = start_static_server(args.host, args.port)
            else:
                base_url = normalize_base_url(args.base_url)

            timeout_seconds = max(1.0, args.timeout_ms / 1000)
            wait_for_server(
                route_url(base_url), timeout_seconds=timeout_seconds, process=server
            )
            records = collection_records(
                load_json_url(
                    route_url(base_url, "data/sekula_index.json"), timeout_seconds
                )
            )
            featured = load_json_url(
                route_url(base_url, "data/featured_items.json"), timeout_seconds
            )
            hero_record = featured_record(records, featured)
            visual_manifest = load_json_url(
                route_url(base_url, "data/book_visuals.json"), timeout_seconds
            )
            edition_manifest = load_json_url(
                route_url(base_url, "data/book_editions.json"), timeout_seconds
            )
            edition_record, edition_item = edition_enrichment_record(
                records, edition_manifest
            )
            by_id = {str(record["id"]): record for record in records}
            cover_record = next(
                (
                    by_id[record_id]
                    for record_id, visual in visual_manifest.get("items", {}).items()
                    if record_id in by_id and visual.get("status") == "resolved"
                ),
                None,
            )
            check(cover_record is not None, "No resolved cover record is available for failure testing.")

            try:
                launch_options = {"headless": not args.headed}
                if args.browser_channel:
                    launch_options["channel"] = args.browser_channel
                browser = playwright.chromium.launch(**launch_options)
            except PlaywrightError as error:
                if is_missing_browser_error(error):
                    raise DependencyFailure(
                        "Playwright could not launch Chromium because the browser binary is missing. "
                        "Run `python -m playwright install chromium` before this smoke test."
                    ) from error
                raise

            try:
                run_primary_flow(browser, base_url, records, hero_record, args.timeout_ms)
                run_reduced_motion_flow(browser, base_url, args.timeout_ms)
                run_cover_failure_flow(browser, base_url, cover_record, args.timeout_ms)
                run_edition_enrichment_flow(
                    browser,
                    base_url,
                    edition_record,
                    edition_item,
                    args.timeout_ms,
                )
                run_edition_failure_flow(browser, base_url, args.timeout_ms)
                run_mobile_flow(browser, base_url, args.timeout_ms)
                run_compatibility_routes(browser, base_url, args.timeout_ms)
                if args.screenshot_dir:
                    capture_qa_screenshots(
                        browser, base_url, args.screenshot_dir, args.timeout_ms
                    )
            finally:
                browser.close()
                browser = None
            print("[PASS] ShelfSignals browser smoke suite completed", flush=True)
            return 0
    except DependencyFailure as error:
        print(f"[DEPENDENCY ERROR] {error}", file=sys.stderr)
        return 2
    except SmokeFailure as error:
        print(f"[SMOKE FAILURE] {error}", file=sys.stderr)
        return 1
    except Exception as error:
        if is_missing_browser_error(error):
            print(
                "[DEPENDENCY ERROR] Playwright Chromium is missing. Run "
                "`python -m playwright install chromium` before this smoke test.",
                file=sys.stderr,
            )
            return 2
        print(
            f"[SMOKE ERROR] {error.__class__.__name__}: {error}", file=sys.stderr
        )
        return 1
    finally:
        stop_static_server(server)


if __name__ == "__main__":
    raise SystemExit(main())
