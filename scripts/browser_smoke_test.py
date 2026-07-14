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


def wait_for_exact_record_filter(page: Any, record_id: str, timeout_ms: int) -> None:
    page.wait_for_function(
        """recordId => {
          const match = document.querySelector('#resultSummary')?.textContent.match(/^([\\d,]+) of/);
          return match
            && Number(match[1].replaceAll(',', '')) === 1
            && new URL(location.href).searchParams.get('q') === recordId;
        }""",
        arg=record_id,
        timeout=timeout_ms,
    )


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
        check(
            page.locator("body").get_attribute("data-app-state") == "ready",
            "Primary route did not leave its explicit application-loading state.",
        )
        check(
            not page.locator("main").evaluate("element => element.inert"),
            "Primary content remained inert after initialization completed.",
        )
        deferred_resources = page.evaluate(
            "performance.getEntriesByType('resource').map(entry => entry.name).filter(name => "
            "name.includes('/data/journeys/aerospace-folktales.json') || "
            "name.includes('/data/spine_index.json') || name.includes('/data/book_editions.json') || "
            "name.includes('/data/sekula_index.json') || name.includes('/data/catalog-search.json') || "
            "name.includes('/data/catalog-details/'))"
        )
        check(
            deferred_resources == [],
            f"First paint fetched below-fold or evidence-only data: {deferred_resources}",
        )
        core_requests = page.evaluate(
            "performance.getEntriesByType('resource').filter(entry => entry.name.includes('/data/catalog-core.json')).length"
        )
        check(core_requests == 1, f"First paint loaded the compact core catalog {core_requests} times instead of once.")
        check(
            page.locator("#collectionGrid .book-card").count() == min(72, len(records)),
            "Initial collection render exceeded or missed its bounded 72-record page.",
        )
        report("first paint keeps below-fold journey and physical/provider evidence deferred")
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
        hero_aria = first_hero.get_attribute("aria-label") or ""
        check(
            hero_aria.startswith(expected_aria) and "cover" in hero_aria.casefold(),
            "First hero book does not expose the configured dataset title, author, and cover scope.",
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

        first_card = page.locator("#collectionGrid .book-card").first
        first_card.evaluate("element => { element.dataset.paginationSentinel = 'preserved'; }")
        page.locator("#loadMore").click()
        expected_rendered = min(144, displayed_total)
        page.wait_for_function(
            "expected => document.querySelectorAll('#collectionGrid .book-card').length === expected",
            arg=expected_rendered,
            timeout=timeout_ms,
        )
        check(
            page.locator('#collectionGrid .book-card[data-pagination-sentinel="preserved"]').count() == 1,
            "Reveal more rebuilt the existing page instead of appending the next bounded records.",
        )
        check(
            page.locator("#collectionGrid").get_attribute("aria-busy") == "false",
            "Collection did not clear its accessible busy state after appending records.",
        )
        report(f"pagination appended records 73–{expected_rendered} without rebuilding the first page")

        initial_heavy_resources = page.evaluate(
            "performance.getEntriesByType('resource').map(entry => entry.name).filter(name => /(?:spine_index|book_editions)\\.json/.test(name))"
        )
        check(
            initial_heavy_resources == [],
            f"Default cover view eagerly loaded physical/edition data: {initial_heavy_resources}",
        )
        page.locator('.view-button[data-view="spines"]').click()
        page.locator("#collectionGrid .spine-book").first.wait_for(
            state="visible", timeout=timeout_ms
        )
        page.locator('#collectionGrid .spine-entry[data-spine-status="indexed"]').first.wait_for(
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
        check(
            not page.evaluate(
                "performance.getEntriesByType('resource').some(entry => entry.name.includes('/data/book_editions.json'))"
            ),
            "Physical view fetched the 17 MB provider-edition manifest before a detail request.",
        )
        placement_box = page.locator("#collectionGrid .spine-placement").first.bounding_box()
        check(
            placement_box is not None
            and placement_box["width"] >= 24
            and placement_box["height"] >= 24,
            f"Physical placement target is below 24×24 CSS px: {placement_box}",
        )
        page.locator('.view-button[data-view="covers"]').click()
        page.locator("#collectionGrid .book-card").first.wait_for(
            state="visible", timeout=timeout_ms
        )
        report("Physical view lazily loads strict Clark geometry with accessible placement targets")

        record_id = str(hero_record["id"])
        page.locator("#collectionSearch").fill(record_id)
        wait_for_exact_record_filter(page, record_id, timeout_ms)
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
        search_requests = page.evaluate(
            "performance.getEntriesByType('resource').filter(entry => entry.name.includes('/data/catalog-search.json')).length"
        )
        check(search_requests == 1, f"Full-field search projection loaded {search_requests} times instead of once.")
        report(f"search located dataset record {record_id}")

        result_card.click()
        drawer = page.locator("#detailDrawer")
        drawer.wait_for(state="visible", timeout=timeout_ms)
        page.locator("#detailLoading").wait_for(state="hidden", timeout=timeout_ms)
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

        detail_requests = page.evaluate(
            "performance.getEntriesByType('resource').filter(entry => entry.name.includes('/data/catalog-details/')).length"
        )
        check(detail_requests == 1, f"Opening one record loaded {detail_requests} detail shards instead of one.")
        page.locator("#closeDetail").click()
        result_card.click()
        page.locator("#detailLoading").wait_for(state="hidden", timeout=timeout_ms)
        reused_detail_requests = page.evaluate(
            "performance.getEntriesByType('resource').filter(entry => entry.name.includes('/data/catalog-details/')).length"
        )
        check(
            reused_detail_requests == detail_requests,
            "Reopening a hydrated record refetched its catalog detail shard.",
        )
        report("detail hydration loads one deterministic shard and reuses it without refetching")

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
        shelf_open = page.locator("#shelfList .shelf-item-open")
        check(shelf_open.count() == 1, "My Shelf entry has no native open-record control.")
        shelf_open.focus()
        page.keyboard.press("Enter")
        page.locator("#detailDrawer").wait_for(state="visible", timeout=timeout_ms)
        check(
            page.locator("#detailTitle").inner_text().strip() == title,
            "Keyboard activation of My Shelf did not open the saved record.",
        )
        report("My Shelf persists the selected real record across reload")
        errors.assert_clean("primary browsing flow")
    finally:
        context.close()


def run_journey_flow(
    browser: Any,
    base_url: str,
    records: Sequence[Dict[str, Any]],
    timeout_ms: int,
) -> None:
    context = browser.new_context(viewport={"width": 1440, "height": 1000})
    page = context.new_page()
    page.set_default_timeout(timeout_ms)
    errors = BrowserErrors(page)
    try:
        response = page.goto(
            route_url(base_url, "?journey=aerospace-folktales&cluster=domestic-interior"),
            wait_until="domcontentloaded",
            timeout=timeout_ms,
        )
        assert_response(response, "Aerospace Folktales journey route")
        page.locator("#journeyReader").wait_for(state="visible", timeout=timeout_ms)
        page.locator("#loadingScreen").wait_for(state="hidden", timeout=timeout_ms)
        check(
            page.locator("#journeyReaderTitle").inner_text().strip()
            == "Aerospace Folktales",
            "Direct journey URL did not resolve the expected real work title.",
        )
        check(
            page.locator("#journeyClusters .journey-cluster").count() == 5,
            "Aerospace Folktales did not render all five cited photo movements.",
        )
        check(
            page.locator("#journeyTimeline button[data-cluster-id]").count() == 5
            and page.locator("#journeyTimeline").evaluate(
                "element => getComputedStyle(element).position"
            ) == "sticky",
            "Journey does not expose its sticky five-movement timeline.",
        )
        check(
            page.locator("#journeyMosaic .journey-mosaic-card").count() == 5,
            "Journey does not expose its five-movement photo mosaic.",
        )
        check(
            page.locator("#journeyClusters .journey-cluster-media.is-withheld").count()
            == 5,
            "Rights-pending work images were not kept as metadata-only frames.",
        )
        check(
            page.locator("#journeyClusters img").count() == 0,
            "The photo sequence exposed an image without public-display permission.",
        )
        check(
            page.locator("#journeyHeroImage img").count() == 1
            and "Library context only"
            in page.locator("#journeyHeroImage figcaption").inner_text(),
            "The open-license library photograph is not scoped as contextual imagery.",
        )
        check(
            page.locator("#journeyPhaseShelves .journey-phase").count() == 4,
            "Journey shelf does not expose the four editorial phases.",
        )
        check(
            page.locator("#journeyPhaseShelves .journey-book-card").count() == 1,
            "The journey should publish only its catalog identity anchor before review.",
        )
        by_id = {str(record["id"]): record for record in records}
        anchor = by_id.get("alma991002293459708431")
        check(anchor is not None, "Aerospace Folktales anchor is absent from the catalog.")
        check(
            short_display_title(anchor["title"])
            in page.locator("#journeyPhaseShelves .journey-book-card").inner_text(),
            "The direct-alignment shelf does not use the real Clark title.",
        )
        check(
            "original sekula placement not supplied in this record"
            in page.locator("#journeyPhaseShelves .journey-book-card").inner_text().casefold(),
            "The identity anchor invents an original shelf placement.",
        )
        check(
            page.locator('#journeyEvidenceBody a[href="./review.html"]').count() == 1,
            "The journey evidence ledger does not link to the local-only review handoff.",
        )
        check(
            page.locator('#journeyEvidenceBody a[href="https://creativecommons.org/licenses/by-sa/4.0/"]').count() == 1,
            "The displayed context image does not expose its direct license link.",
        )
        page.locator("#openSearch").click()
        page.locator("#searchDialog").wait_for(state="visible", timeout=timeout_ms)
        page.keyboard.press("Escape")
        page.locator("#searchDialog").wait_for(state="hidden", timeout=timeout_ms)
        check(
            page.locator("#journeyReader").is_visible()
            and "journey=aerospace-folktales" in page.url,
            "Closing the search dialog also closed the active journey.",
        )
        report(
            "direct journey + cluster URL renders a sticky timeline, rights-gated mosaic, and four evidence-safe shelves"
        )

        page.wait_for_function(
            "new URL(location.href).searchParams.get('cluster') === 'domestic-interior'",
            timeout=timeout_ms,
        )
        domestic = page.locator("#journey-cluster-domestic-interior")
        check(domestic.is_visible(), "Direct cluster URL did not resolve its cited movement.")
        page.reload(wait_until="domcontentloaded", timeout=timeout_ms)
        page.locator("#journeyReader").wait_for(state="visible", timeout=timeout_ms)
        page.locator("#loadingScreen").wait_for(state="hidden", timeout=timeout_ms)
        page.wait_for_function(
            "new URL(location.href).searchParams.get('cluster') === 'domestic-interior' && scrollY > 0",
            timeout=timeout_ms,
        )
        check(
            page.locator('#journeyTimeline button[data-cluster-id="domestic-interior"]').get_attribute("aria-current") == "step",
            "Reload did not restore the active cluster timeline state.",
        )

        page.locator('#journeyTimeline button[data-cluster-id="ordered-world"]').click()
        page.wait_for_function(
            "new URL(location.href).searchParams.get('cluster') === 'ordered-world'",
            timeout=timeout_ms,
        )
        page.wait_for_timeout(750)
        ordered_scroll = page.evaluate("scrollY")
        check(ordered_scroll > 0, "Timeline navigation did not scroll to the selected movement.")
        page.go_back(wait_until="domcontentloaded", timeout=timeout_ms)
        page.wait_for_function(
            "new URL(location.href).searchParams.get('cluster') === 'domestic-interior'",
            timeout=timeout_ms,
        )
        page.go_forward(wait_until="domcontentloaded", timeout=timeout_ms)
        page.wait_for_function(
            "new URL(location.href).searchParams.get('cluster') === 'ordered-world'",
            timeout=timeout_ms,
        )
        check(
            abs(page.evaluate("scrollY") - ordered_scroll) < 180,
            "Browser Forward did not restore the selected cluster scroll position.",
        )

        page.locator("#closeJourney").click()
        page.wait_for_function(
            "!new URL(location.href).searchParams.has('journey')",
            timeout=timeout_ms,
        )
        check(page.locator("#journeyReader").is_hidden(), "Journey close did not restore the collection view.")
        page.wait_for_function(
            "document.activeElement?.classList.contains('journey-open')",
            timeout=timeout_ms,
        )
        page.go_back(wait_until="domcontentloaded", timeout=timeout_ms)
        page.locator("#journeyReader").wait_for(state="visible", timeout=timeout_ms)
        check(
            "journey=aerospace-folktales" in page.url
            and "cluster=ordered-world" in page.url,
            "Browser Back did not restore the journey + cluster deep link.",
        )
        restored_scroll = page.evaluate("scrollY")
        restored_history = page.evaluate("history.state")
        check(
            abs(restored_scroll - ordered_scroll) < 180,
            "Browser Back did not restore the journey cluster scroll position "
            f"(expected about {ordered_scroll}, got {restored_scroll}; state={restored_history!r}).",
        )
        page.go_forward(wait_until="domcontentloaded", timeout=timeout_ms)
        page.wait_for_function(
            "!new URL(location.href).searchParams.has('journey')",
            timeout=timeout_ms,
        )
        check(page.locator("#journeyReader").is_hidden(), "Browser Forward did not restore the closed journey state.")
        report("journey reload, close, Back/Forward, focus, and cluster scroll state restore correctly")
        errors.assert_clean("journey flow")
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
    aborted_cover_requests: List[str] = []

    def abort_cover(route: Any) -> None:
        aborted_cover_requests.append(route.request.url)
        route.abort()

    page.route("https://covers.openlibrary.org/**", abort_cover)
    errors = BrowserErrors(page)
    try:
        wait_for_primary_app(page, base_url, timeout_ms)
        record_id = str(hero_record["id"])
        page.locator("#collectionSearch").fill(record_id)
        wait_for_exact_record_filter(page, record_id, timeout_ms)
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
        object_cover_label = book.locator(".cover-state-label").inner_text().strip()
        card_cover_label = card.locator(".book-card-cover-scope").inner_text().strip()
        check(
            object_cover_label == "Cover not yet verified for this edition"
            and card_cover_label == "Cover not yet verified for this edition",
            "Failed remote cover retained a reviewed/provider-reference label on its surrogate "
            f"(object={object_cover_label!r}; card={card_cover_label!r}).",
        )
        failed_request_count = len(aborted_cover_requests)
        check(failed_request_count > 0, "Cover failure test did not intercept a provider request.")
        page.locator('.view-button[data-view="list"]').click()
        page.locator('.view-button[data-view="covers"]').click()
        card.wait_for(state="visible", timeout=timeout_ms)
        page.wait_for_timeout(150)
        check(
            len(aborted_cover_requests) == failed_request_count,
            "A known failed provider cover was requested again after the collection rerendered.",
        )
        card.click()
        page.locator("#detailDrawer").wait_for(state="visible", timeout=timeout_ms)
        page.locator("#detailLoading").wait_for(state="hidden", timeout=timeout_ms)
        cover_evidence = page.locator("#detailCoverEvidenceBody").inner_text().casefold()
        check(
            "cover not yet verified for this edition" in cover_evidence
            and "compact cover is available" not in cover_evidence,
            "A failed provider image left contradictory available-cover evidence in the drawer.",
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


def run_search_failure_flow(browser: Any, base_url: str, timeout_ms: int) -> None:
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    page = context.new_page()
    page.set_default_timeout(timeout_ms)
    failed_requests: List[str] = []

    def abort_search(route: Any) -> None:
        failed_requests.append(route.request.url)
        route.abort()

    page.route(route_url(base_url, "data/catalog-search.json"), abort_search)
    errors = BrowserErrors(page)
    try:
        wait_for_primary_app(page, base_url, timeout_ms)
        page.locator("#collectionSearch").fill("harbor")
        page.wait_for_function(
            "!document.querySelector('#resultSummary')?.textContent.includes('Preparing')",
            timeout=timeout_ms,
        )
        page.locator("#collectionSearch").fill("capital")
        page.wait_for_timeout(350)
        check(
            len(failed_requests) == 1,
            f"A failed full-field search was retried on later keystrokes ({len(failed_requests)} requests).",
        )
        check(
            page.locator("#collectionGrid .book-card").count() > 0,
            "Search-projection failure removed the core catalog fallback.",
        )
        report("failed full-field search falls back once without repeated 11 MB requests")
        unexpected = [error for error in errors.errors if "net::ERR_FAILED" not in error]
        check(not unexpected, f"Search failure flow emitted unrelated errors: {unexpected}")
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
        wait_for_exact_record_filter(page, record_id, timeout_ms)
        page.locator('.view-button[data-view="spines"]').click()
        spine = page.locator(
            f'#collectionGrid .spine-book[data-record-id="{record_id}"]'
        )
        spine.wait_for(state="visible", timeout=timeout_ms)
        page.locator(f'#collectionGrid .spine-entry[data-record-id="{record_id}"][data-spine-status="indexed"]').wait_for(
            state="visible", timeout=timeout_ms
        )
        check(
            not page.evaluate(
                "performance.getEntriesByType('resource').some(entry => entry.name.includes('/data/book_editions.json'))"
            ),
            "Provider-edition manifest loaded before the reader requested record detail.",
        )
        check(
            spine.locator(".spine-title").inner_text().strip()
            == short_display_title(record["title"]),
            "Enriched spine title does not match the served catalog record.",
        )
        check(
            spine.locator(".spine-meta").count() == 1,
            "Strict spine does not expose real compact catalog metadata.",
        )
        spine.click()
        page.locator("#detailDrawer").wait_for(state="visible", timeout=timeout_ms)
        page.locator("#detailLoading").wait_for(state="hidden", timeout=timeout_ms)
        check(
            not page.evaluate(
                "performance.getEntriesByType('resource').some(entry => entry.name.includes('/data/book_editions.json'))"
            ),
            "Opening detail automatically fetched the optional 17 MB provider snapshot.",
        )
        check(
            "17 mb" in page.locator("#loadEditionEvidence").inner_text().casefold(),
            "Optional provider-evidence control does not disclose its transfer size.",
        )
        page.locator("#loadEditionEvidence").click()
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
                "open library edition" not in page.locator("#physicalMetrics").inner_text().casefold()
                and "clark" in page.locator("#physicalMetrics").inner_text().casefold(),
                "Provider-edition geometry leaked into the Clark-only physical contract.",
            )
        report(
            "exact-edition metadata loads only on explicit request and remains separate from Clark spine geometry"
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
        page.locator('.view-button[data-view="spines"]').click()
        page.locator("#collectionGrid .spine-book").first.wait_for(
            state="visible", timeout=timeout_ms
        )
        page.locator('#collectionGrid .spine-entry[data-spine-status="indexed"]').first.wait_for(
            state="visible", timeout=timeout_ms
        )
        page.locator("#collectionGrid .spine-book").first.click()
        page.locator("#detailDrawer").wait_for(state="visible", timeout=timeout_ms)
        page.locator("#detailLoading").wait_for(state="hidden", timeout=timeout_ms)
        page.locator("#loadEditionEvidence").click()
        page.wait_for_function(
            "document.querySelector('#editionLoaderStatus')?.textContent.toLowerCase().includes('could not be loaded')",
            timeout=timeout_ms,
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


def run_spine_failure_flow(
    browser: Any, base_url: str, timeout_ms: int
) -> None:
    context = browser.new_context(viewport={"width": 1280, "height": 900})
    page = context.new_page()
    page.set_default_timeout(timeout_ms)
    page.route(route_url(base_url, "data/spine_index.json"), lambda route: route.abort())
    errors = BrowserErrors(page)
    try:
        wait_for_primary_app(page, base_url, timeout_ms)
        page.locator('.view-button[data-view="spines"]').click()
        unavailable = page.locator(
            '#collectionGrid .spine-entry[data-spine-status="unavailable"]'
        )
        unavailable.first.wait_for(state="visible", timeout=timeout_ms)
        check(
            unavailable.count() == page.locator("#collectionGrid .spine-entry").count() > 0,
            "A rejected spine index left ordinary indexed-looking shelf entries.",
        )
        first = unavailable.first
        marker = first.locator(".spine-status-marker")
        marker_text = " ".join((marker.text_content() or "").split()).casefold()
        check(
            marker.is_visible() and "evidence unavailable" in marker_text,
            "Fail-closed spine has no visible unavailable-evidence marker.",
        )
        check(
            marker.evaluate(
                "element => element.scrollHeight <= element.clientHeight + 1 && element.scrollWidth <= element.clientWidth + 1"
            ),
            "Fail-closed spine unavailable-evidence marker is clipped.",
        )
        background = first.locator(".spine-book").evaluate(
            "element => getComputedStyle(element).backgroundImage"
        )
        check(
            "repeating-linear-gradient" in background,
            f"Fail-closed spine still looks like ordinary validated geometry: {background!r}",
        )
        check(
            not first.locator(".spine-book").evaluate(
                "element => element.classList.contains('has-cover') || Boolean(element.style.getPropertyValue('--cover-image'))"
            ),
            "Fail-closed physical placeholder consumed cover evidence.",
        )
        first.locator(".spine-book").click()
        page.locator("#detailDrawer").wait_for(state="visible", timeout=timeout_ms)
        page.wait_for_function(
            "document.querySelector('#physicalEvidence')?.textContent.toLowerCase().includes('failed')",
            timeout=timeout_ms,
        )
        check(
            "neutral placeholder" in page.locator("#physicalMetrics").inner_text().casefold(),
            "Physical drawer asserted geometry after spine source validation failed.",
        )
        report("spine-index failure is visibly neutral, cover-independent, and fail-closed")
        unexpected = [error for error in errors.errors if "net::ERR_FAILED" not in error]
        check(
            not unexpected,
            f"Spine failure flow emitted unrelated errors: {unexpected}",
        )
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
            reduced_motion="reduce",
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
            page.locator("#collectionTitle").evaluate(
                "element => { document.documentElement.style.scrollBehavior = 'auto'; "
                "window.scrollTo(0, element.getBoundingClientRect().top + scrollY - 84); }"
            )
            page.wait_for_timeout(80)
            page.screenshot(
                path=str(directory / f"covers-{label}.png"),
                full_page=False,
                animations="disabled",
            )
            response = page.goto(
                route_url(
                    base_url,
                    "?journey=aerospace-folktales",
                ),
                wait_until="domcontentloaded",
                timeout=timeout_ms,
            )
            assert_response(response, "Journey screenshot route")
            page.locator("#journeyReader").wait_for(
                state="visible", timeout=timeout_ms
            )
            page.locator("#loadingScreen").wait_for(
                state="hidden", timeout=timeout_ms
            )
            page.locator("#journeyReader").evaluate(
                "element => { document.documentElement.style.scrollBehavior = 'auto'; "
                "window.scrollTo(0, element.offsetTop); }"
            )
            page.screenshot(
                path=str(directory / f"journey-{label}.png"),
                full_page=False,
                animations="disabled",
            )
            if label == "desktop":
                page.locator("#journeyPhaseShelves").scroll_into_view_if_needed()
                page.screenshot(
                    path=str(directory / "journey-shelves-desktop.png"),
                    full_page=False,
                    animations="disabled",
                )
            wait_for_primary_app(page, base_url, timeout_ms)
            page.locator('.view-button[data-view="spines"]').click()
            page.locator("#collectionTitle").evaluate(
                "element => { document.documentElement.style.scrollBehavior = 'auto'; "
                "window.scrollTo(0, element.getBoundingClientRect().top + scrollY - 84); }"
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
    association_queue = (
        DOCS_DIR.parent
        / "research"
        / "review-queues"
        / "aerospace-folktales.json"
    )
    if association_queue.is_file():
        review_context = browser.new_context(viewport={"width": 1440, "height": 900})
        review_page = review_context.new_page()
        review_page.set_default_timeout(timeout_ms)
        try:
            response = review_page.goto(
                route_url(base_url, "review.html"),
                wait_until="domcontentloaded",
                timeout=timeout_ms,
            )
            assert_response(response, "Local review screenshot route")
            review_page.locator("#candidateFile").set_input_files(
                str(association_queue)
            )
            review_page.locator(".review-card").first.wait_for(
                state="visible", timeout=timeout_ms
            )
            review_page.screenshot(
                path=str(directory / "association-review-desktop.png"),
                full_page=False,
                animations="disabled",
            )
            review_page.locator(".review-card").first.evaluate(
                "element => { document.documentElement.style.scrollBehavior = 'auto'; "
                "window.scrollTo(0, element.getBoundingClientRect().top + scrollY - 84); }"
            )
            review_page.screenshot(
                path=str(directory / "association-review-queue-desktop.png"),
                full_page=False,
                animations="disabled",
            )
        finally:
            review_context.close()
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
                run_journey_flow(browser, base_url, records, args.timeout_ms)
                run_reduced_motion_flow(browser, base_url, args.timeout_ms)
                run_cover_failure_flow(browser, base_url, cover_record, args.timeout_ms)
                run_search_failure_flow(browser, base_url, args.timeout_ms)
                run_edition_enrichment_flow(
                    browser,
                    base_url,
                    edition_record,
                    edition_item,
                    args.timeout_ms,
                )
                run_edition_failure_flow(browser, base_url, args.timeout_ms)
                run_spine_failure_flow(browser, base_url, args.timeout_ms)
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
