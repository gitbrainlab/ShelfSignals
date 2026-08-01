#!/usr/bin/env python3
"""Resumable Thomas Jefferson Library metadata extractor.

This research utility keeps the Library of Congress source responses, parses
their ordered MARC fields in the ignored evidence cache, and builds a searchable
index from an explicit public-safe MARC projection.  It can also collect the
loc.gov digital subset and the Thomas Jefferson Foundation's structured Sowerby
transcription.  The latter is deliberately kept as a separate source layer: it
is not represented as LOC metadata.

The default output root is ``research/jefferson/work``.  Raw responses are
cached so interrupted harvests can resume without repeating successful
requests.
"""

from __future__ import annotations

import argparse
import hashlib
import http.client
import http.cookiejar
import json
import os
import re
import sqlite3
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Callable, Iterable, Iterator, Mapping, Sequence


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_ROOT = REPOSITORY_ROOT / "research" / "jefferson" / "work"

SRU_ENDPOINT = "http://lx2.loc.gov:210/lcdb"
SRU_QUERY = 'dc.author="Thomas Jefferson Library Collection"'
SRU_SCHEMA = "marcxml"
# The migrated LCDB SRU service currently reports 3,128 matches but returned a
# diagnostic for the second page when maximumRecords=50. Ten-record pages have
# been verified at positions near the beginning, middle, and end of the result
# set. Keep the conservative size explicit and snapshot it with the cache.
SRU_PAGE_SIZE = 10

CATALOG_API_BASE = "https://search.catalog.loc.gov/api"
CATALOG_TENANT = "ltl1000001"
CATALOG_EXACT_QUERY = 'contributors == "Thomas Jefferson Library Collection (Library of Congress)"'
CATALOG_SORTED_QUERY = CATALOG_EXACT_QUERY + " sortby title/sort.ascending"
CATALOG_EXACT_HEADING = "Thomas Jefferson Library Collection (Library of Congress)"
CATALOG_PAGE_SIZE = 25

LOC_DIGITAL_ENDPOINT = "https://www.loc.gov/books/"
LOC_DIGITAL_FACET = "contributor:thomas jefferson library collection (library of congress)"
LOC_DIGITAL_PAGE_SIZE = 100

SOWERBY_BASE = "https://tjlibraries.monticello.org/transcripts/sowerby/"
SOWERBY_TOC = urllib.parse.urljoin(SOWERBY_BASE, "sowerby.html")
SOWERBY_LOC_ITEM = "https://www.loc.gov/item/52060000/"
SOWERBY_LOC_MANIFEST = "https://www.loc.gov/item/52060000/manifest.json"
SOWERBY_VOLUMES = ("I", "II", "III", "IV", "V")
LOC_SOWERBY_ITEM_JSON = "https://www.loc.gov/item/52060000/?fo=json&at=item,resources"
LOC_SOWERBY_TOC = "https://catdir.loc.gov/catdir/toc/becites/main/jefferson/52060000.toc.html"
LOC_SOWERBY_INDEX = "https://catdir.loc.gov/catdir/toc/becites/main/jefferson/52060000.idx.html"

USER_AGENT = "ShelfSignals-Jefferson-Research/0.1 (+https://github.com/gitbrainlab/ShelfSignals)"
UTC_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
SOWERBY_PAGE_PATTERN = re.compile(r"^(I|II|III|IV|V)_(\d+)\.html$")
ROMAN_VALUE = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}

SRU_NS = "http://www.loc.gov/zing/srw/"
MARC_NS = "http://www.loc.gov/MARC21/slim"
NS = {"zs": SRU_NS, "marc": MARC_NS}

# Raw source records remain in the ignored evidence cache. Only these MARC21
# bibliographic fields may enter derivatives. In particular, local 9XX fields
# (including FOLIO UUID/workflow fields) and a private 541/561/583 are excluded.
# Subfield 9 is local data even when attached to an otherwise allowed tag.
PUBLIC_MARC_CONTROL_TAGS = frozenset({"001", "006", "007", "008"})
PUBLIC_MARC_DATA_TAGS = frozenset("""
010 013 015 016 017 020 022 024 025 026 027 028 030 031 032 033 034 035 037 038
040 041 042 043 044 045 046 047 048
050 051 052 055 060 061 066 070 071 072 074 080 082 083 084 085 086 088 090
100 110 111 130 210 222 240 242 243 245 246 247 250 251 254 255 256 257 258
260 263 264 300 306 307 310 321 336 337 338 340 341 342 343 344 345 346 347 348
351 352 353 355 357 362 363 365 366 370 377 380 381 382 383 384 385 386 388
490 500 501 502 504 505 506 507 508 510 511 513 514 515 516 518 520 521 522
524 525 526 530 533 534 535 536 538 540 541 542 544 545 546 547 550 552 555
556 561 562 563 565 567 580 581 583 584 585 586 588
600 610 611 630 647 648 650 651 653 654 655 656 657 658 662 688
700 710 711 720 730 740 751 752 753 754 758 760 762 765 767 770 772 773 774
775 776 777 780 785 786 787 800 810 811 830 856 880
""".split())
PUBLIC_MARC_PRIVATE_NOTE_TAGS = frozenset({"541", "561", "583"})
PUBLIC_MARC_PROJECTION_POLICY = "loc-public-bibliographic-marc-allowlist@1"


class ExtractionError(RuntimeError):
    """Raised when source evidence or a generated contract is invalid."""


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def sha256_bytes(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def normalized_space(value: str) -> str:
    return " ".join((value or "").split())


def stable_unique(values: Iterable[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        cleaned = normalized_space(value)
        if cleaned and cleaned not in seen:
            result.append(cleaned)
            seen.add(cleaned)
    return result


def atomic_write_bytes(path: Path, value: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp-{os.getpid()}")
    temporary.write_bytes(value)
    os.replace(temporary, path)


def atomic_write_json(path: Path, value: Any, *, pretty: bool = True) -> None:
    if pretty:
        payload = (json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")
    else:
        payload = canonical_json_bytes(value)
    atomic_write_bytes(path, payload)


def atomic_write_jsonl(path: Path, values: Iterable[Any]) -> int:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp-{os.getpid()}")
    count = 0
    with temporary.open("w", encoding="utf-8", newline="\n") as handle:
        for value in values:
            handle.write(json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")))
            handle.write("\n")
            count += 1
    os.replace(temporary, path)
    return count


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def file_evidence(path: Path, root: Path | None = None) -> dict[str, Any]:
    raw = path.read_bytes()
    return {
        "path": str(path.relative_to(root)) if root else str(path),
        "bytes": len(raw),
        "sha256": sha256_bytes(raw),
    }


@dataclass
class FetchEvent:
    request_url: str
    cache_path: str
    fetched_at: str
    bytes: int
    sha256: str
    cache_hit: bool
    status: int
    content_type: str = ""
    final_url: str = ""

    def as_dict(self) -> dict[str, Any]:
        return dict(self.__dict__)


class CachedFetcher:
    """Small polite HTTP client with raw-response caching and retries."""

    def __init__(
        self,
        *,
        min_interval: float,
        retries: int = 4,
        timeout: float = 90.0,
        refresh: bool = False,
        sleep_fn: Callable[[float], None] = time.sleep,
        monotonic_fn: Callable[[], float] = time.monotonic,
    ) -> None:
        self.min_interval = max(0.0, min_interval)
        self.retries = max(1, retries)
        self.timeout = timeout
        self.refresh = refresh
        self.sleep_fn = sleep_fn
        self.monotonic_fn = monotonic_fn
        self.last_request_at: float | None = None
        self.events: list[FetchEvent] = []

    def _wait(self) -> None:
        if self.last_request_at is None:
            return
        remaining = self.min_interval - (self.monotonic_fn() - self.last_request_at)
        if remaining > 0:
            self.sleep_fn(remaining)

    def fetch(
        self,
        url: str,
        cache_path: Path,
        *,
        opener: urllib.request.OpenerDirector | None = None,
        headers: Mapping[str, str] | None = None,
    ) -> bytes:
        meta_path = cache_path.with_name(cache_path.name + ".meta.json")
        if cache_path.exists() and not self.refresh:
            meta: Mapping[str, Any] = load_json(meta_path) if meta_path.exists() else {}
            if meta_path.exists():
                cached_url = meta.get("request_url")
                if cached_url and cached_url != url:
                    raise ExtractionError(f"Cache URL mismatch for {cache_path}: {cached_url!r} != {url!r}")
            raw = cache_path.read_bytes()
            if meta_path.exists():
                recorded_bytes = meta.get("bytes")
                recorded_sha256 = meta.get("sha256")
                actual_sha256 = sha256_bytes(raw)
                if recorded_bytes != len(raw) or recorded_sha256 != actual_sha256:
                    raise ExtractionError(
                        f"Cached source evidence does not match its sidecar: {cache_path}"
                    )
            event = FetchEvent(
                request_url=url,
                cache_path=str(cache_path),
                fetched_at=str(meta.get("fetched_at", "")),
                bytes=len(raw),
                sha256=sha256_bytes(raw),
                cache_hit=True,
                status=200,
                content_type=str(meta.get("content_type", "")),
                final_url=str(meta.get("final_url", url)),
            )
            self.events.append(event)
            return raw

        cache_path.parent.mkdir(parents=True, exist_ok=True)
        for attempt in range(1, self.retries + 1):
            self._wait()
            request_headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
            request_headers.update(headers or {})
            request = urllib.request.Request(url, headers=request_headers)
            try:
                open_request = opener.open if opener is not None else urllib.request.urlopen
                with open_request(request, timeout=self.timeout) as response:
                    raw = response.read()
                    status = int(getattr(response, "status", 200))
                    final_url = response.geturl()
                    content_type = response.headers.get("Content-Type", "")
                self.last_request_at = self.monotonic_fn()
                fetched_at = utc_now()
                evidence = {
                    "request_url": url,
                    "final_url": final_url,
                    "fetched_at": fetched_at,
                    "status": status,
                    "content_type": content_type,
                    "bytes": len(raw),
                    "sha256": sha256_bytes(raw),
                    "user_agent": USER_AGENT,
                }
                atomic_write_bytes(cache_path, raw)
                atomic_write_json(meta_path, evidence)
                self.events.append(FetchEvent(cache_hit=False, cache_path=str(cache_path), **{
                    key: evidence[key] for key in (
                        "request_url", "fetched_at", "bytes", "sha256", "status", "content_type", "final_url"
                    )
                }))
                return raw
            except urllib.error.HTTPError as exc:
                # HTTPError also wraps an open response body. Close it on every
                # path so repeated transient failures cannot leak descriptors.
                try:
                    self.last_request_at = self.monotonic_fn()
                    if exc.code == 404:
                        raise
                    retryable = exc.code in {408, 425, 429} or 500 <= exc.code <= 599
                    if not retryable or attempt == self.retries:
                        raise ExtractionError(f"HTTP {exc.code} for {url}") from exc
                    retry_after = exc.headers.get("Retry-After") if exc.headers else None
                    delay = float(retry_after) if retry_after and retry_after.isdigit() else min(60.0, 2.0 ** attempt)
                    self.sleep_fn(delay)
                finally:
                    exc.close()
            except (OSError, TimeoutError, urllib.error.URLError, http.client.HTTPException) as exc:
                self.last_request_at = self.monotonic_fn()
                if attempt == self.retries:
                    raise ExtractionError(f"Request failed after {attempt} attempts: {url}: {exc}") from exc
                self.sleep_fn(min(60.0, 2.0 ** attempt))
        raise ExtractionError(f"Unreachable fetch failure for {url}")


class CatalogGuestSession:
    """Anonymous in-memory session for the current LOC catalog application.

    The short-lived guest credential is never written to the cache, logs, or
    generated manifests. Only source response bodies from catalog endpoints are
    retained.
    """

    def __init__(self, fetcher: CachedFetcher) -> None:
        self.fetcher = fetcher
        self.cookies = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.cookies))
        self.authenticated = False

    @property
    def headers(self) -> dict[str, str]:
        return {"X-Okapi-Tenant": CATALOG_TENANT, "Accept": "application/json"}

    def authenticate(self) -> None:
        request = urllib.request.Request(
            CATALOG_API_BASE + "/opac-auth/guest-token",
            headers={"User-Agent": USER_AGENT, **self.headers},
        )
        try:
            with self.opener.open(request, timeout=self.fetcher.timeout) as response:
                # Consume, but deliberately do not retain or print, the token response.
                response.read()
        except urllib.error.HTTPError as exc:
            try:
                raise ExtractionError(f"LOC catalog guest authentication failed: {exc}") from exc
            finally:
                exc.close()
        except (OSError, urllib.error.URLError) as exc:
            raise ExtractionError(f"LOC catalog guest authentication failed: {exc}") from exc
        if not list(self.cookies):
            raise ExtractionError("LOC catalog guest authentication returned no session cookie")
        self.authenticated = True

    def fetch(self, url: str, cache_path: Path) -> bytes:
        if cache_path.exists() and not self.fetcher.refresh:
            return self.fetcher.fetch(url, cache_path)
        if not self.authenticated:
            self.authenticate()
        return self.fetcher.fetch(url, cache_path, opener=self.opener, headers=self.headers)


def catalog_search_url(offset: int, limit: int = CATALOG_PAGE_SIZE) -> str:
    params = {
        "query": CATALOG_SORTED_QUERY,
        "limit": str(limit),
        "offset": str(offset),
        "expandAll": "true",
    }
    return CATALOG_API_BASE + "/search/instances?" + urllib.parse.urlencode(params)


def catalog_reference_url(name: str) -> str:
    return CATALOG_API_BASE + f"/opac-inventory/{name}?limit=1000"


def catalog_source_record_url(instance_id: str) -> str:
    return CATALOG_API_BASE + "/opac-inventory/source-records/" + urllib.parse.quote(instance_id)


def generation_id() -> str:
    return utc_now().replace("-", "").replace(":", "").replace("T", "-").removesuffix("Z") + f"-{os.getpid()}"


def harvest_exact_catalog(
    root: Path,
    *,
    refresh: bool,
    delay: float,
    page_size: int = CATALOG_PAGE_SIZE,
    source_marc_limit: int = 0,
) -> list[FetchEvent]:
    if page_size < 1 or page_size > 100:
        raise ExtractionError("exact catalog page size must be from 1 to 100")
    cache_root = root / "cache" / "loc_catalog_exact"
    active_path = cache_root / "active.json"
    pending_path = cache_root / "pending.json"
    active = load_json(active_path) if active_path.exists() else {}
    pending = load_json(pending_path) if pending_path.exists() else {}
    if refresh:
        if (
            pending.get("query") == CATALOG_SORTED_QUERY
            and pending.get("page_size") == page_size
            and pending.get("cache_directory")
        ):
            generation = pending
        else:
            identifier = generation_id()
            base = cache_root / "generations" / identifier
            generation = {
                "schema": "shelfsignals-loc-catalog-pending@1",
                "query": CATALOG_SORTED_QUERY,
                "page_size": page_size,
                "cache_directory": str((base / "search").relative_to(root)),
                "reference_directory": str((base / "reference").relative_to(root)),
                "source_marc_directory": str((base / "source_marc").relative_to(root)),
            }
            atomic_write_json(pending_path, generation)
    elif active.get("cache_directory"):
        if (
            int(active.get("page_size") or page_size) != page_size
            or active.get("query", CATALOG_SORTED_QUERY) != CATALOG_SORTED_QUERY
        ):
            raise ExtractionError("Active exact-catalog snapshot uses different query/page settings; use --refresh")
        generation = active
    else:
        # Backwards-compatible first activation of a pre-generation cache.
        generation = {
            "cache_directory": str((cache_root / f"search-title-p{page_size:03d}").relative_to(root)),
            "reference_directory": str((cache_root / "reference").relative_to(root)),
            "source_marc_directory": str((cache_root / "source_marc").relative_to(root)),
        }
    search_dir = root / generation["cache_directory"]
    reference_dir = root / generation.get("reference_directory", str((cache_root / "reference").relative_to(root)))
    source_dir = root / generation.get("source_marc_directory", str((cache_root / "source_marc").relative_to(root)))
    active_source_ids = list(active.get("source_marc_instance_ids", [])) if not refresh else []

    active_payload = {
        "schema": "shelfsignals-loc-catalog-cache@1",
        "api_base": CATALOG_API_BASE,
        "tenant": CATALOG_TENANT,
        "filter_query": CATALOG_EXACT_QUERY,
        "query": CATALOG_SORTED_QUERY,
        "stable_sort": "title ascending",
        "expand_all": True,
        "page_size": page_size,
        "cache_directory": str(search_dir.relative_to(root)),
        "reference_directory": str(reference_dir.relative_to(root)),
        "source_marc_directory": str(source_dir.relative_to(root)),
        "credential_retained": False,
    }
    # New generations are empty and failed refreshes resume from pending files;
    # never overwrite the previously active snapshot in place.
    fetcher = CachedFetcher(min_interval=delay, refresh=False)
    session = CatalogGuestSession(fetcher)
    first = json.loads(session.fetch(catalog_search_url(0, page_size), search_dir / "offset-000000.json"))
    total = int(first.get("totalRecords") or 0)
    if total < 1:
        raise ExtractionError("Exact LOC catalog query returned no instances")
    if not isinstance(first.get("instances"), list):
        raise ExtractionError("Exact LOC catalog response has no instances array")
    for offset in range(page_size, total, page_size):
        payload = json.loads(session.fetch(catalog_search_url(offset, page_size), search_dir / f"offset-{offset:06d}.json"))
        if int(payload.get("totalRecords") or 0) != total:
            raise ExtractionError(f"Exact catalog total changed during harvest at offset {offset}")
        if not payload.get("instances"):
            raise ExtractionError(f"Exact catalog returned no instances at offset {offset} before total {total}")

    for name in ("locations", "identifier-types"):
        session.fetch(catalog_reference_url(name), reference_dir / f"{name}.json")

    all_instances: list[dict[str, Any]] = []
    for offset in range(0, total, page_size):
        payload = load_json(search_dir / f"offset-{offset:06d}.json")
        all_instances.extend(payload.get("instances", []))
    instance_ids = [str(instance.get("id") or "") for instance in all_instances]
    hrids = [str(instance.get("hrid") or "") for instance in all_instances]
    exact_heading = normalized_space(CATALOG_EXACT_HEADING).casefold()
    heading_misses = [
        instance_id
        for instance_id, instance in zip(instance_ids, all_instances)
        if not any(
            normalized_space(str(contributor.get("name") or "")).casefold() == exact_heading
            for contributor in instance.get("contributors", [])
        )
    ]
    if len(all_instances) != total:
        raise ExtractionError(f"Exact catalog generation has {len(all_instances)} rows, expected {total}")
    if not all(instance_ids) or len(instance_ids) != len(set(instance_ids)):
        raise ExtractionError("Exact catalog generation contains missing or duplicate instance UUIDs")
    nonempty_hrids = [value for value in hrids if value]
    if len(nonempty_hrids) != len(set(nonempty_hrids)):
        raise ExtractionError("Exact catalog generation contains duplicate HRIDs")
    if heading_misses:
        raise ExtractionError(f"Exact catalog generation has {len(heading_misses)} exact-heading misses")

    source_ids = active_source_ids
    if source_marc_limit > 0:
        candidates = [instance for instance in all_instances if instance.get("id")]
        source_ids = [str(instance["id"]) for instance in candidates[:source_marc_limit]]
        for instance in candidates[:source_marc_limit]:
            instance_id = str(instance["id"])
            session.fetch(catalog_source_record_url(instance_id), source_dir / f"{instance_id}.json")
    active_payload.update({
        "complete": True,
        "reported_instance_count": total,
        "expected_page_count": (total + page_size - 1) // page_size,
        "source_marc_instance_ids": source_ids,
        "source_marc_selection": "first N instances in explicit title/sort.ascending order",
        "source_marc_limit": len(source_ids),
    })
    atomic_write_json(active_path, active_payload)
    if pending_path.exists() and generation.get("cache_directory") == pending.get("cache_directory"):
        pending_path.unlink()
    return fetcher.events


def count_restricted_markers(value: Any, stats: Counter[str]) -> None:
    """Count restricted markers nested inside a field removed as one unit."""
    if isinstance(value, dict):
        if value.get("staffOnly") is True:
            stats["staff_only_nodes_removed"] += 1
        for key, child in value.items():
            if key in {"createdByUserId", "updatedByUserId"}:
                stats["internal_user_identifiers_removed"] += 1
            else:
                count_restricted_markers(child, stats)
    elif isinstance(value, list):
        for child in value:
            count_restricted_markers(child, stats)


def strip_staff_only(value: Any, stats: Counter[str]) -> Any:
    """Remove restricted catalog fields from research derivatives.

    The ignored raw snapshot remains the evidence-preserving source layer. The
    derivative must not make staff-only nodes, internal workflow notes, item
    barcodes, or circulation fields easier to redistribute merely because the
    public catalog application happened to return them.
    """
    if isinstance(value, dict):
        if value.get("staffOnly") is True:
            stats["staff_only_nodes_removed"] += 1
            for key, child in value.items():
                if key not in {"staffOnly"}:
                    count_restricted_markers({key: child}, stats)
            return None
        if value.get("staffSuppress") is True or value.get("discoverySuppress") is True:
            stats["suppressed_catalog_nodes_removed"] += 1
            return None
        result = {}
        for key, child in value.items():
            if key in {"createdByUserId", "updatedByUserId"}:
                stats["internal_user_identifiers_removed"] += 1
                continue
            if key == "barcode":
                stats["item_barcode_fields_removed"] += 1
                continue
            if key == "administrativeNotes":
                stats["administrative_note_fields_removed"] += 1
                count_restricted_markers(child, stats)
                continue
            if key == "circulationNotes":
                stats["circulation_note_fields_removed"] += 1
                count_restricted_markers(child, stats)
                continue
            if key == "tags":
                stats["internal_tag_fields_removed"] += 1
                count_restricted_markers(child, stats)
                continue
            cleaned = strip_staff_only(child, stats)
            if cleaned is not None:
                result[key] = cleaned
        return result
    if isinstance(value, list):
        result = []
        for child in value:
            cleaned = strip_staff_only(child, stats)
            if cleaned is not None:
                result.append(cleaned)
        return result
    return value


CATALOG_INSTANCE_DERIVATIVE_KEYS = {
    "id", "hrid", "title", "indexTitle", "contributors", "identifiers", "languages", "subjects", "notes",
    "alternativeTitles", "classifications", "publication", "editions", "series", "sourceTypes", "instanceType",
    "instanceFormats", "electronicAccess", "holdings", "items", "isBoundWith", "oclcs", "staffSuppress",
    "discoverySuppress",
}
CATALOG_HOLDING_DERIVATIVE_KEYS = {
    "id", "hrid", "formerIds", "holdingsTypeId", "permanentLocationId", "notes", "electronicAccess",
    "discoverySuppress",
}
CATALOG_ITEM_DERIVATIVE_KEYS = {
    "id", "hrid", "status", "materialType", "effectiveLocationId", "effectiveCallNumberComponents",
    "effectiveShelvingOrder", "notes", "electronicAccess", "formerIds", "discoverySuppress",
}


def public_catalog_instance_projection(instance: Mapping[str, Any], stats: Counter[str]) -> dict[str, Any]:
    """Apply an explicit publication allowlist after restricted-node removal."""
    result = {key: value for key, value in instance.items() if key in CATALOG_INSTANCE_DERIVATIVE_KEYS}
    stats["unallowlisted_instance_fields_removed"] += sum(
        1 for key in instance if key not in CATALOG_INSTANCE_DERIVATIVE_KEYS
    )
    holdings = []
    for holding in instance.get("holdings", []):
        if not isinstance(holding, dict):
            continue
        holdings.append({key: value for key, value in holding.items() if key in CATALOG_HOLDING_DERIVATIVE_KEYS})
        stats["unallowlisted_holding_fields_removed"] += sum(
            1 for key in holding if key not in CATALOG_HOLDING_DERIVATIVE_KEYS
        )
    items = []
    for item in instance.get("items", []):
        if not isinstance(item, dict):
            continue
        items.append({key: value for key, value in item.items() if key in CATALOG_ITEM_DERIVATIVE_KEYS})
        stats["unallowlisted_item_fields_removed"] += sum(
            1 for key in item if key not in CATALOG_ITEM_DERIVATIVE_KEYS
        )
    result["holdings"] = holdings
    result["items"] = items
    return result


def folio_source_to_marc(payload: Mapping[str, Any]) -> dict[str, Any]:
    """Convert FOLIO's parsed source-record JSON to the lossless MARC shape."""
    content = payload.get("parsedRecord", {}).get("content", {})
    leader = str(content.get("leader") or "")
    control: list[dict[str, str]] = []
    data: list[dict[str, Any]] = []
    for wrapper in content.get("fields", []):
        if not isinstance(wrapper, dict) or len(wrapper) != 1:
            continue
        tag, value = next(iter(wrapper.items()))
        tag = str(tag)
        if tag.lower() in {"leader", "ldr"}:
            leader = str(value)
        elif isinstance(value, dict):
            subfields = []
            for subfield in value.get("subfields", []):
                if isinstance(subfield, dict):
                    for code, text_value in subfield.items():
                        subfields.append({"code": str(code), "value": str(text_value)})
            data.append({
                "tag": tag,
                "ind1": str(value.get("ind1", " ")),
                "ind2": str(value.get("ind2", " ")),
                "subfields": subfields,
            })
        else:
            control.append({"tag": tag, "value": str(value)})
    return {"leader": leader, "control_fields": control, "data_fields": data}


def public_marc_projection(
    marc: Mapping[str, Any],
    stats: Counter[str] | None = None,
) -> dict[str, Any]:
    """Return the ordered, publication-safe subset of a raw MARC record.

    Lossless source records stay in the ignored cache. Derivatives use this
    allowlist so local workflow fields and private provenance notes cannot be
    republished merely because an unauthenticated source endpoint returned them.
    """
    counts = stats if stats is not None else Counter()
    control_fields = []
    for field in marc.get("control_fields", []):
        tag = str(field.get("tag") or "")
        if tag not in PUBLIC_MARC_CONTROL_TAGS:
            counts["marc_unallowlisted_control_fields_removed"] += 1
            continue
        control_fields.append({"tag": tag, "value": str(field.get("value") or "")})

    data_fields = []
    for field in marc.get("data_fields", []):
        tag = str(field.get("tag") or "")
        if tag.startswith("9"):
            counts["marc_local_9xx_fields_removed"] += 1
            continue
        if tag not in PUBLIC_MARC_DATA_TAGS:
            counts["marc_unallowlisted_data_fields_removed"] += 1
            continue
        indicator_one = str(field.get("ind1", " "))
        if tag in PUBLIC_MARC_PRIVATE_NOTE_TAGS and indicator_one == "0":
            counts["marc_private_note_fields_removed"] += 1
            continue
        subfields = []
        for subfield in field.get("subfields", []):
            code = str(subfield.get("code") or "")
            if code == "9":
                counts["marc_local_subfield_9_values_removed"] += 1
                continue
            subfields.append({"code": code, "value": str(subfield.get("value") or "")})
        data_fields.append({
            "tag": tag,
            "ind1": indicator_one,
            "ind2": str(field.get("ind2", " ")),
            "subfields": subfields,
        })
    return {
        "leader": str(marc.get("leader") or ""),
        "control_fields": control_fields,
        "data_fields": data_fields,
    }


def reference_map(root: Path, filename: str, list_key: str, label_key: str = "name") -> dict[str, str]:
    cache_root = root / "cache" / "loc_catalog_exact"
    active_path = cache_root / "active.json"
    active = load_json(active_path) if active_path.exists() else {}
    directory = root / active.get("reference_directory", str((cache_root / "reference").relative_to(root)))
    path = directory / filename
    if not path.exists():
        return {}
    payload = load_json(path)
    return {
        str(item.get("id")): str(item.get(label_key) or item.get("discoveryDisplayName") or item.get("code") or "")
        for item in payload.get(list_key, [])
        if item.get("id")
    }


def nested_strings(value: Any) -> Iterator[str]:
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for child in value.values():
            yield from nested_strings(child)
    elif isinstance(value, list):
        for child in value:
            yield from nested_strings(child)


def normalize_exact_instance(
    instance: Mapping[str, Any],
    *,
    identifier_types: Mapping[str, str],
    locations: Mapping[str, str],
    source_marc_projection: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    identifiers = []
    typed_identifiers: dict[str, list[str]] = defaultdict(list)
    for identifier in instance.get("identifiers", []):
        type_id = str(identifier.get("identifierTypeId") or "")
        type_name = identifier_types.get(type_id, "")
        value = normalized_space(str(identifier.get("value") or ""))
        if not value:
            continue
        identifiers.append({"value": value, "type_id": type_id, "type": type_name})
        typed_identifiers[type_name.casefold() or type_id].append(value)
    lccns = stable_unique(
        normalize_lccn(value)
        for key, values in typed_identifiers.items()
        if "lccn" in key
        for value in values
    )
    contributors = stable_unique(str(value.get("name") or "") for value in instance.get("contributors", []))
    notes = stable_unique(
        str(note.get("note") or "")
        for note in instance.get("notes", [])
        if isinstance(note, dict) and note.get("staffOnly") is not True
    )
    # Untyped expanded notes contain ranges, page/volume references, negations,
    # correction dates, and suffixed identifiers. Preserve them for review, but
    # never turn the first nearby integer into a Sowerby-entry relationship.
    sowerby_note_candidates = stable_unique(
        value for value in nested_strings(instance) if "sowerby" in value.casefold()
    )
    sowerby_numbers: list[int] = []
    source_marc_normalized = None
    if source_marc_projection is not None:
        source_marc_normalized = normalize_marc_record(source_marc_projection)
        if source_marc_normalized.get("sowerby_numbers"):
            sowerby_numbers = source_marc_normalized["sowerby_numbers"]
        if source_marc_normalized.get("identifiers", {}).get("lccn"):
            lccns = source_marc_normalized["identifiers"]["lccn"]
    call_numbers = []
    for classification in instance.get("classifications", []):
        value = normalized_space(str(classification.get("classificationNumber") or ""))
        if value:
            call_numbers.append({"source": "instance_classification", "value": value, "type_id": classification.get("classificationTypeId", "")})
    item_rows = []
    for item in instance.get("items", []):
        components = item.get("effectiveCallNumberComponents") or {}
        value = normalized_space(" ".join(str(components.get(key) or "") for key in ("prefix", "callNumber", "suffix")))
        if value:
            call_numbers.append({"source": "item_effective_call_number", "value": value, "type_id": components.get("typeId", "")})
        location_id = str(item.get("effectiveLocationId") or "")
        item_rows.append({
            "id": item.get("id", ""),
            "hrid": item.get("hrid", ""),
            "status": (item.get("status") or {}).get("name", ""),
            "material_type": (item.get("materialType") or {}).get("name", ""),
            "effective_location_id": location_id,
            "effective_location": locations.get(location_id, ""),
            "call_number": value,
            "shelving_order": item.get("effectiveShelvingOrder", ""),
            "discovery_suppress": bool(item.get("discoverySuppress")),
        })
    holding_rows = []
    for holding in instance.get("holdings", []):
        location_id = str(holding.get("permanentLocationId") or "")
        holding_rows.append({
            "id": holding.get("id", ""),
            "hrid": holding.get("hrid", ""),
            "permanent_location_id": location_id,
            "permanent_location": locations.get(location_id, ""),
            "discovery_suppress": bool(holding.get("discoverySuppress")),
        })
    normalized = {
        "instance_uuid": str(instance.get("id") or ""),
        "hrid": str(instance.get("hrid") or ""),
        "title": normalized_space(str(instance.get("title") or "")),
        "index_title": normalized_space(str(instance.get("indexTitle") or "")),
        "alternative_titles": stable_unique(str(value.get("alternativeTitle") or value.get("title") or "") for value in instance.get("alternativeTitles", [])),
        "contributors": contributors,
        "publication": list(instance.get("publication", [])),
        "editions": list(instance.get("editions", [])),
        "series": list(instance.get("series", [])),
        "languages": stable_unique(str(value) for value in instance.get("languages", [])),
        "subjects": list(instance.get("subjects", [])),
        "source_types": list(instance.get("sourceTypes", [])),
        "instance_type": str(instance.get("instanceType") or ""),
        "instance_formats": list(instance.get("instanceFormats", [])),
        "identifiers": identifiers,
        "identifier_groups": dict(sorted(typed_identifiers.items())),
        "lccn": lccns[0] if lccns else "",
        "lccns": lccns,
        "record_url": f"https://lccn.loc.gov/{urllib.parse.quote(lccns[0])}" if lccns else "",
        "notes": notes,
        "call_numbers": call_numbers,
        "sowerby_numbers": sowerby_numbers,
        "sowerby_evidence": "source MARC 510 with one plain base-integer identifier" if sowerby_numbers else "",
        "sowerby_note_candidates_unparsed": sowerby_note_candidates,
        # Exact collection-heading membership is not ownership evidence. Even
        # apparently direct copy notes need a reviewed status vocabulary before
        # they can support an original/replacement/surrogate assertion.
        "relationship_to_jefferson": "exact_collection_heading_membership",
        "relationship_evidence": [CATALOG_EXACT_HEADING],
        "ownership_or_reconstruction_status": "unresolved",
        "ownership_or_reconstruction_evidence": [],
        "holdings": holding_rows,
        "items": item_rows,
        "holding_count": len(holding_rows),
        "item_count": len(item_rows),
        "staff_suppress": bool(instance.get("staffSuppress")),
        "discovery_suppress": bool(instance.get("discoverySuppress")),
        "public_index_eligible": not bool(instance.get("staffSuppress")) and not bool(instance.get("discoverySuppress")),
    }
    if source_marc_normalized is not None:
        normalized["source_marc_metadata"] = source_marc_normalized
    return normalized


def load_exact_catalog_instances(root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cache_root = root / "cache" / "loc_catalog_exact"
    active_path = cache_root / "active.json"
    if not active_path.exists():
        return [], {"available": False, "reason": "no cached exact catalog pages"}
    active = load_json(active_path)
    if active.get("complete") is False:
        raise ExtractionError("Exact catalog active snapshot is not marked complete")
    search_dir = root / active["cache_directory"]
    first_path = search_dir / "offset-000000.json"
    if not first_path.exists():
        return [], {"available": False, "reason": "no cached exact catalog pages"}
    first_payload = load_json(first_path)
    total_from_first = int(first_payload.get("totalRecords") or 0)
    page_size = int(active.get("page_size") or CATALOG_PAGE_SIZE)
    pages = [search_dir / f"offset-{offset:06d}.json" for offset in range(0, total_from_first, page_size)]
    missing_pages = [path.name for path in pages if not path.exists()]
    if missing_pages:
        raise ExtractionError(f"Exact catalog active snapshot is missing pages: {missing_pages[:10]}")
    expected_names = {path.name for path in pages}
    unexpected_pages = sorted(
        path.name
        for path in search_dir.glob("offset-*.json")
        if not path.name.endswith(".meta.json") and path.name not in expected_names
    )
    if unexpected_pages:
        raise ExtractionError(f"Exact catalog active snapshot has unexpected pages: {unexpected_pages[:10]}")
    reported_totals: set[int] = set()
    source_instances: list[dict[str, Any]] = []
    for path in pages:
        payload = load_json(path)
        reported_totals.add(int(payload.get("totalRecords") or 0))
        source_instances.extend(payload.get("instances", []))
    if len(reported_totals) != 1:
        raise ExtractionError(f"Exact catalog pages disagree on totalRecords: {sorted(reported_totals)}")
    total = next(iter(reported_totals))
    identifier_types = reference_map(root, "identifier-types.json", "identifierTypes")
    reference_directory = root / active.get(
        "reference_directory", str((cache_root / "reference").relative_to(root))
    )
    location_path = reference_directory / "locations.json"
    locations: dict[str, str] = {}
    if location_path.exists():
        for location in load_json(location_path).get("locations", []):
            if location.get("id"):
                locations[str(location["id"])] = str(location.get("discoveryDisplayName") or location.get("name") or location.get("code") or "")
    source_directory = root / active.get(
        "source_marc_directory", str((cache_root / "source_marc").relative_to(root))
    )
    active_source_id_values = [str(value) for value in active.get("source_marc_instance_ids", [])]
    active_source_ids = set(active_source_id_values)
    missing_source_marc_ids = sorted(
        instance_id for instance_id in active_source_ids if not (source_directory / f"{instance_id}.json").exists()
    )
    staff_stats: Counter[str] = Counter()
    ids: Counter[str] = Counter()
    hrids: Counter[str] = Counter()
    holding_ids: Counter[str] = Counter()
    item_ids: Counter[str] = Counter()
    exact_heading_misses = []
    assembled = []
    source_marc_count = 0
    for position, source_instance in enumerate(source_instances, 1):
        instance_id = str(source_instance.get("id") or f"position-{position}")
        ids[instance_id] += 1
        hrid = str(source_instance.get("hrid") or "")
        if hrid:
            hrids[hrid] += 1
        contributor_names = [str(value.get("name") or "") for value in source_instance.get("contributors", [])]
        normalized_heading = normalized_space(CATALOG_EXACT_HEADING).casefold()
        if not any(normalized_space(value).casefold() == normalized_heading for value in contributor_names):
            exact_heading_misses.append(instance_id)
        source_path = source_directory / f"{instance_id}.json"
        if instance_id not in active_source_ids:
            source_path = source_directory / "__inactive__" / f"{instance_id}.json"
        raw_source_marc = folio_source_to_marc(load_json(source_path)) if source_path.exists() else None
        source_marc_projection = (
            public_marc_projection(raw_source_marc, staff_stats) if raw_source_marc is not None else None
        )
        if source_marc_projection is not None:
            source_marc_count += 1
        sanitized = strip_staff_only(source_instance, staff_stats)
        if not isinstance(sanitized, dict):
            # The source row remains hashed in the ignored snapshot, while no
            # suppressed instance is promoted into a derivative.
            continue
        derivative_instance = public_catalog_instance_projection(sanitized, staff_stats)
        normalized = normalize_exact_instance(
            derivative_instance,
            identifier_types=identifier_types,
            locations=locations,
            source_marc_projection=source_marc_projection,
        )
        holding_ids.update(str(item["id"]) for item in normalized["holdings"] if item.get("id"))
        item_ids.update(str(item["id"]) for item in normalized["items"] if item.get("id"))
        identity = instance_id if ids[instance_id] == 1 else f"{instance_id}:duplicate-{ids[instance_id]}"
        payload = {
            "schema": "shelfsignals-loc-catalog-instance@1",
            "id": f"loc:instance:{identity}",
            "entity_type": "catalog_instance",
            "source": {
                "authority": "Library of Congress",
                "service": "current catalog search API",
                "filter_query": CATALOG_EXACT_QUERY,
                "query": CATALOG_SORTED_QUERY,
                "sort": "title ascending",
                "query_relation": "exact contributor heading",
                "position": position,
                "raw_contains_staff_only_fields": True,
                "derived_staff_only_fields_removed": True,
                "derivative_uses_explicit_field_allowlist": True,
                "source_marc_projection_policy": PUBLIC_MARC_PROJECTION_POLICY,
            },
            "instance": derivative_instance,
            "normalized": normalized,
        }
        if source_marc_projection is not None:
            payload["source_marc_projection"] = source_marc_projection
        payload["record_sha256"] = sha256_bytes(canonical_json_bytes(payload))
        assembled.append(payload)
    for key in (
        "staff_only_nodes_removed", "suppressed_catalog_nodes_removed", "internal_user_identifiers_removed",
        "item_barcode_fields_removed", "administrative_note_fields_removed", "circulation_note_fields_removed",
        "internal_tag_fields_removed", "unallowlisted_instance_fields_removed",
        "unallowlisted_holding_fields_removed", "unallowlisted_item_fields_removed",
        "marc_unallowlisted_control_fields_removed", "marc_local_9xx_fields_removed",
        "marc_unallowlisted_data_fields_removed", "marc_private_note_fields_removed",
        "marc_local_subfield_9_values_removed",
    ):
        staff_stats.setdefault(key, 0)
    validation = {
        "available": True,
        "filter_query": CATALOG_EXACT_QUERY,
        "query": CATALOG_SORTED_QUERY,
        "reported_instance_count": total,
        "parsed_instance_count": len(assembled),
        "instance_count_matches": total == len(assembled),
        "cached_page_count": len(pages),
        "expected_page_count": (total + int(active["page_size"]) - 1) // int(active["page_size"]),
        "duplicate_instance_uuids": {key: count for key, count in ids.items() if count > 1},
        "duplicate_hrids": {key: count for key, count in hrids.items() if count > 1},
        "duplicate_holding_ids": {key: count for key, count in holding_ids.items() if count > 1},
        "duplicate_item_ids": {key: count for key, count in item_ids.items() if count > 1},
        "holdings_without_ids": sum(
            1 for record in assembled for item in record["normalized"]["holdings"] if not item.get("id")
        ),
        "items_without_ids": sum(
            1 for record in assembled for item in record["normalized"]["items"] if not item.get("id")
        ),
        "exact_heading_misses": exact_heading_misses,
        "holdings": sum(item["normalized"]["holding_count"] for item in assembled),
        "items": sum(item["normalized"]["item_count"] for item in assembled),
        "instances_without_holdings": sum(1 for item in assembled if not item["normalized"]["holdings"]),
        "instances_without_items": sum(1 for item in assembled if not item["normalized"]["items"]),
        "staff_suppressed_instances": sum(1 for item in assembled if item["normalized"]["staff_suppress"]),
        "discovery_suppressed_instances": sum(1 for item in assembled if item["normalized"]["discovery_suppress"]),
        "source_marc_records_present": source_marc_count,
        "expected_source_marc_records": len(active_source_id_values),
        "duplicate_source_marc_instance_ids": {
            key: count for key, count in Counter(active_source_id_values).items() if count > 1
        },
        "missing_source_marc_instance_ids": missing_source_marc_ids,
        "source_marc_instance_ids_outside_snapshot": sorted(active_source_ids - set(ids)),
        "unsafe_source_marc_projection_ids": [
            record["id"]
            for record in assembled
            if record.get("source_marc_projection") is not None
            and public_marc_projection(record["source_marc_projection"]) != record["source_marc_projection"]
        ],
        **dict(staff_stats),
    }
    return assembled, validation


def sru_url(start_record: int, maximum_records: int = SRU_PAGE_SIZE) -> str:
    params = {
        "version": "1.1",
        "operation": "searchRetrieve",
        "query": SRU_QUERY,
        "startRecord": str(start_record),
        "maximumRecords": str(maximum_records),
        "recordSchema": SRU_SCHEMA,
    }
    return SRU_ENDPOINT + "?" + urllib.parse.urlencode(params)


def element_text(element: ET.Element | None) -> str:
    return "" if element is None else "".join(element.itertext())


def parse_marc_record(element: ET.Element) -> dict[str, Any]:
    leader_element = element.find(f"{{{MARC_NS}}}leader")
    control_fields: list[dict[str, str]] = []
    data_fields: list[dict[str, Any]] = []
    for child in list(element):
        local_name = child.tag.rsplit("}", 1)[-1]
        if local_name == "controlfield":
            control_fields.append({"tag": child.attrib.get("tag", ""), "value": child.text or ""})
        elif local_name == "datafield":
            data_fields.append({
                "tag": child.attrib.get("tag", ""),
                "ind1": child.attrib.get("ind1", " "),
                "ind2": child.attrib.get("ind2", " "),
                "subfields": [
                    {"code": subfield.attrib.get("code", ""), "value": subfield.text or ""}
                    for subfield in list(child)
                    if subfield.tag.rsplit("}", 1)[-1] == "subfield"
                ],
            })
    return {
        "leader": element_text(leader_element),
        "control_fields": control_fields,
        "data_fields": data_fields,
    }


def parse_sru_page(raw: bytes) -> dict[str, Any]:
    try:
        root = ET.fromstring(raw)
    except ET.ParseError as exc:
        raise ExtractionError(f"Invalid SRU XML: {exc}") from exc
    diagnostics = [
        normalized_space(element_text(node))
        for node in root.iter()
        if node.tag.rsplit("}", 1)[-1] == "message"
    ]
    if diagnostics:
        raise ExtractionError("SRU diagnostic: " + "; ".join(diagnostics))
    total_text = root.findtext("zs:numberOfRecords", default="", namespaces=NS)
    if not total_text.isdigit():
        raise ExtractionError("SRU response has no valid numberOfRecords")
    records: list[dict[str, Any]] = []
    for record_node in root.findall(".//zs:records/zs:record", NS):
        record_data = record_node.find("zs:recordData", NS)
        marc = None if record_data is None else record_data.find("marc:record", NS)
        if marc is None:
            raise ExtractionError("SRU record has no MARCXML recordData")
        position_text = record_node.findtext("zs:recordPosition", default="", namespaces=NS)
        records.append({
            "record_schema": record_node.findtext("zs:recordSchema", default="", namespaces=NS),
            "record_packing": record_node.findtext("zs:recordPacking", default="", namespaces=NS),
            "record_identifier": record_node.findtext("zs:recordIdentifier", default="", namespaces=NS),
            "record_position": int(position_text) if position_text.isdigit() else None,
            "marc": parse_marc_record(marc),
        })
    next_text = root.findtext("zs:nextRecordPosition", default="", namespaces=NS)
    return {
        "number_of_records": int(total_text),
        "next_record_position": int(next_text) if next_text.isdigit() else None,
        "records": records,
    }


def control_values(marc: Mapping[str, Any], tag: str) -> list[str]:
    return [field.get("value", "") for field in marc.get("control_fields", []) if field.get("tag") == tag]


def data_fields(marc: Mapping[str, Any], tags: Iterable[str]) -> list[dict[str, Any]]:
    wanted = set(tags)
    return [field for field in marc.get("data_fields", []) if field.get("tag") in wanted]


def subfield_values(field: Mapping[str, Any], codes: Iterable[str] | None = None) -> list[str]:
    wanted = None if codes is None else set(codes)
    return [
        subfield.get("value", "")
        for subfield in field.get("subfields", [])
        if wanted is None or subfield.get("code") in wanted
    ]


def display_field(field: Mapping[str, Any], codes: Iterable[str] | None = None) -> str:
    return normalized_space(" ".join(subfield_values(field, codes)))


def display_fields(marc: Mapping[str, Any], tags: Iterable[str], codes: Iterable[str] | None = None) -> list[str]:
    return stable_unique(display_field(field, codes) for field in data_fields(marc, tags))


def first_display(marc: Mapping[str, Any], tags: Iterable[str], codes: Iterable[str] | None = None) -> str:
    values = display_fields(marc, tags, codes)
    return values[0] if values else ""


def normalize_lccn(value: str) -> str:
    value = re.sub(r"\s+", "", value or "")
    return value.strip()


def language_codes(marc: Mapping[str, Any]) -> list[str]:
    values: list[str] = []
    fixed = next(iter(control_values(marc, "008")), "")
    if len(fixed) >= 38:
        code = fixed[35:38].strip()
        if code and code != "|||":
            values.append(code)
    for field_value in (
        value for field in data_fields(marc, {"041"}) for value in subfield_values(field, {"a", "b", "d", "e", "f", "g", "h", "j"})
    ):
        compact = re.sub(r"[^A-Za-z]", "", field_value).lower()
        if compact and len(compact) % 3 == 0:
            values.extend(compact[index:index + 3] for index in range(0, len(compact), 3))
        elif compact:
            values.append(compact)
    return stable_unique(values)


def call_number_objects(marc: Mapping[str, Any]) -> list[dict[str, str]]:
    schemes = {"050": "lc", "051": "lc_copy", "060": "nlm", "070": "nal", "080": "udc", "082": "dewey", "090": "local_lc"}
    result: list[dict[str, str]] = []
    for field in data_fields(marc, schemes):
        value = display_field(field, {"a", "b", "c", "d"})
        if value:
            result.append({"tag": field["tag"], "scheme": schemes[field["tag"]], "value": value})
    return result


def note_objects(marc: Mapping[str, Any]) -> list[dict[str, str]]:
    result = []
    for field in marc.get("data_fields", []):
        tag = field.get("tag", "")
        if len(tag) == 3 and tag.startswith("5"):
            result.append({"tag": tag, "value": display_field(field)})
    return [value for value in result if value["value"]]


def subject_objects(marc: Mapping[str, Any]) -> list[dict[str, str]]:
    result = []
    for field in marc.get("data_fields", []):
        tag = field.get("tag", "")
        if len(tag) == 3 and tag.startswith("6"):
            result.append({"tag": tag, "value": display_field(field)})
    return [value for value in result if value["value"]]


def sowerby_references(marc: Mapping[str, Any]) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for field in data_fields(marc, {"510"}):
        citation = display_field(field)
        if "sowerby" not in citation.casefold():
            continue
        raw_numbers = subfield_values(field, {"c"})
        identifiers: list[str] = []
        numbers: list[int] = []
        for value in raw_numbers:
            identifiers.extend(re.findall(r"(?<!\d)(\d{1,4}[a-z]?)(?![\da-z])", value, re.IGNORECASE))
            match = re.fullmatch(r"\s*(?:no\.?\s*)?(\d{1,4})[.,;:]?\s*", value, re.IGNORECASE)
            if match and 1 <= int(match.group(1)) <= 4931:
                numbers.append(int(match.group(1)))
        result.append({
            "tag": "510",
            "citation": citation,
            "raw_numbers": raw_numbers,
            "identifiers": stable_unique(identifiers),
            "numbers": list(dict.fromkeys(numbers)),
        })
    return result


def identifier_object(marc: Mapping[str, Any]) -> dict[str, list[str]]:
    lccn = stable_unique(value for field in data_fields(marc, {"010"}) for value in subfield_values(field, {"a", "b"}))
    isbn = stable_unique(value for field in data_fields(marc, {"020"}) for value in subfield_values(field, {"a", "z"}))
    issn = stable_unique(value for field in data_fields(marc, {"022"}) for value in subfield_values(field, {"a", "l", "m", "y", "z"}))
    other = stable_unique(display_field(field) for field in data_fields(marc, {"024", "028"}))
    system = stable_unique(value for field in data_fields(marc, {"035"}) for value in subfield_values(field, {"a", "z"}))
    oclc = stable_unique(value for value in system if "(OCoLC)" in value or value.lower().startswith("ocm") or value.lower().startswith("ocn"))
    return {
        "lccn": [normalize_lccn(value) for value in lccn if normalize_lccn(value)],
        "isbn": isbn,
        "issn": issn,
        "oclc": oclc,
        "other": other,
        "system_control_numbers": system,
    }


def relationship_evidence(marc: Mapping[str, Any]) -> tuple[list[dict[str, str]], str]:
    evidence: list[dict[str, str]] = []
    owned = False
    collection_membership = False
    for field in data_fields(marc, {"561"}):
        value = display_field(field)
        if value:
            evidence.append({"tag": "561", "kind": "ownership_or_custodial_history", "value": value})
    for field in data_fields(marc, {"500"}):
        value = display_field(field)
        folded = value.casefold()
        if "jefferson" in folded:
            evidence.append({"tag": "500", "kind": "jefferson_copy_or_exhibit_note", "value": value})
    for field in data_fields(marc, {"700"}):
        value = display_field(field)
        folded = value.casefold()
        roles = " ".join(subfield_values(field, {"e", "4"})).casefold()
        if "jefferson, thomas" in folded and ("former owner" in roles or "fmo" in roles):
            evidence.append({"tag": "700", "kind": "former_owner_access_point", "value": value})
            owned = True
    for field in data_fields(marc, {"710"}):
        value = display_field(field)
        if "thomas jefferson library collection" in value.casefold():
            evidence.append({"tag": "710", "kind": "collection_access_point", "value": value})
            collection_membership = True
    relationship = "catalog_asserts_jefferson_former_owner_access_point" if owned else (
        "collection_membership_only" if collection_membership else (
            "provenance_evidence_requires_review" if evidence else "no_normalized_relationship_assertion"
        )
    )
    return evidence, relationship


def normalize_marc_record(marc: Mapping[str, Any]) -> dict[str, Any]:
    control_number = next(iter(control_values(marc, "001")), "")
    identifiers = identifier_object(marc)
    title = first_display(marc, {"245"}, {"a", "b", "n", "p"})
    if not title:
        title = first_display(marc, {"130", "240", "246"}, {"a", "n", "p"})
    authors = display_fields(marc, {"100", "110", "111"})
    contributors = display_fields(marc, {"700", "710", "711", "720"})
    publication = display_fields(marc, {"260", "264"})
    fixed = next(iter(control_values(marc, "008")), "")
    date_one = fixed[7:11].strip() if len(fixed) >= 11 else ""
    date_two = fixed[11:15].strip() if len(fixed) >= 15 else ""
    year_candidates = [value for value in (date_one, date_two) if re.fullmatch(r"\d{4}", value)]
    if not year_candidates:
        year_candidates = re.findall(r"(?<!\d)(1[0-9]{3}|20[0-9]{2})(?!\d)", " ".join(publication))
    notes = note_objects(marc)
    subjects = subject_objects(marc)
    references = sowerby_references(marc)
    evidence, relationship = relationship_evidence(marc)
    links = []
    for field in data_fields(marc, {"856"}):
        uris = subfield_values(field, {"u"})
        labels = subfield_values(field, {"y", "3"})
        for uri in uris:
            links.append({"url": normalized_space(uri), "label": normalized_space(" ".join(labels)), "tag": "856"})
    lccn = identifiers["lccn"][0] if identifiers["lccn"] else ""
    return {
        "loc_control_number": normalized_space(control_number),
        "lccn": lccn,
        "record_url": f"https://lccn.loc.gov/{urllib.parse.quote(lccn)}" if lccn else "",
        "title": title,
        "uniform_titles": display_fields(marc, {"130", "240"}, {"a", "d", "f", "g", "k", "l", "m", "n", "o", "p", "r", "s"}),
        "alternative_titles": display_fields(marc, {"246", "247"}, {"a", "b", "n", "p"}),
        "authors": authors,
        "contributors": contributors,
        "edition_statements": display_fields(marc, {"250"}),
        "publication_statements": publication,
        "publishers": display_fields(marc, {"260", "264"}, {"b"}),
        "places": display_fields(marc, {"260", "264"}, {"a"}),
        "dates": display_fields(marc, {"260", "264"}, {"c"}),
        "year": year_candidates[0] if year_candidates else "",
        "languages": language_codes(marc),
        "physical_descriptions": display_fields(marc, {"300"}),
        "content_types": display_fields(marc, {"336"}),
        "media_types": display_fields(marc, {"337"}),
        "carrier_types": display_fields(marc, {"338"}),
        "series": display_fields(marc, {"490", "800", "810", "811", "830"}),
        "notes": notes,
        "provenance_notes": [item for item in notes if item["tag"] in {"541", "561", "562", "563", "583"}],
        "subjects": subjects,
        "genres": [item["value"] for item in subjects if item["tag"] == "655"],
        "call_numbers": call_number_objects(marc),
        "identifiers": identifiers,
        "sowerby_references": references,
        "sowerby_numbers": list(dict.fromkeys(number for reference in references for number in reference["numbers"])),
        "relationship_to_jefferson": relationship,
        "relationship_evidence": evidence,
        "collection_access_points": [
            value for value in display_fields(marc, {"710"}) if "thomas jefferson library collection" in value.casefold()
        ],
        "links": links,
        "marc_projection_policy": PUBLIC_MARC_PROJECTION_POLICY,
    }


def harvest_sru_catalog(root: Path, *, refresh: bool, delay: float, page_size: int = SRU_PAGE_SIZE) -> list[FetchEvent]:
    cache_root = root / "cache" / "loc_sru"
    cache_dir = cache_root / f"marcxml-p{page_size:03d}"
    atomic_write_json(cache_root / "active.json", {
        "schema": "shelfsignals-loc-sru-cache@1",
        "endpoint": SRU_ENDPOINT,
        "query": SRU_QUERY,
        "record_schema": SRU_SCHEMA,
        "page_size": page_size,
        "cache_directory": str(cache_dir.relative_to(root)),
    })
    fetcher = CachedFetcher(min_interval=delay, refresh=refresh)
    start = 1
    total: int | None = None
    while total is None or start <= total:
        path = cache_dir / f"{start:06d}.xml"
        raw = fetcher.fetch(sru_url(start, page_size), path)
        parsed = parse_sru_page(raw)
        if total is None:
            total = parsed["number_of_records"]
        elif total != parsed["number_of_records"]:
            raise ExtractionError(f"SRU total changed during harvest: {total} -> {parsed['number_of_records']}")
        if not parsed["records"]:
            raise ExtractionError(f"SRU returned no records at startRecord={start} before total={total}")
        next_position = parsed["next_record_position"]
        computed = start + len(parsed["records"])
        start = next_position if next_position and next_position > start else computed
    return fetcher.events


def load_sru_records(root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cache_root = root / "cache" / "loc_sru"
    active_path = cache_root / "active.json"
    if active_path.exists():
        active = load_json(active_path)
        cache_dir = root / active["cache_directory"]
        pages = sorted(cache_dir.glob("*.xml"))
    else:
        # Backwards-compatible fixture path for no-network contract tests.
        pages = sorted(cache_root.glob("*.xml"))
    if not pages:
        return [], {"available": False, "reason": "no cached SRU pages"}
    records: list[dict[str, Any]] = []
    totals: set[int] = set()
    positions: list[int] = []
    for page in pages:
        try:
            parsed = parse_sru_page(page.read_bytes())
        except ExtractionError as exc:
            return [], {
                "available": False,
                "incomplete": True,
                "reason": str(exc),
                "cached_page_count": len(pages),
                "failed_page": page.name,
                "raw_evidence_retained": True,
            }
        totals.add(parsed["number_of_records"])
        for record in parsed["records"]:
            record["source_page"] = page.name
            records.append(record)
            if record["record_position"] is not None:
                positions.append(record["record_position"])
    if len(totals) != 1:
        raise ExtractionError(f"Cached SRU pages disagree on numberOfRecords: {sorted(totals)}")
    total = next(iter(totals))
    seen_ids: Counter[str] = Counter()
    assembled: list[dict[str, Any]] = []
    missing_control = 0
    projection_stats: Counter[str] = Counter()
    for source_record in records:
        marc_projection = public_marc_projection(source_record["marc"], projection_stats)
        normalized = normalize_marc_record(marc_projection)
        base = normalized["loc_control_number"] or f"sru-position-{source_record['record_position'] or 'unknown'}"
        seen_ids[base] += 1
        suffix = "" if seen_ids[base] == 1 else f":duplicate-{seen_ids[base]}"
        record_id = f"loc:catalog:{base}{suffix}"
        if not normalized["loc_control_number"]:
            missing_control += 1
        payload = {
            "schema": "shelfsignals-loc-marc-record@1",
            "id": record_id,
            "entity_type": "catalog_record",
            "source": {
                "authority": "Library of Congress",
                "service": "LCDB SRU",
                "query": SRU_QUERY,
                "record_schema": source_record["record_schema"],
                "record_position": source_record["record_position"],
                "source_page": source_record["source_page"],
                "raw_marc_retained_only_in_ignored_cache": True,
                "marc_projection_policy": PUBLIC_MARC_PROJECTION_POLICY,
            },
            "marc_projection": marc_projection,
            "normalized": normalized,
        }
        payload["record_sha256"] = sha256_bytes(canonical_json_bytes(payload))
        assembled.append(payload)
    duplicate_bases = {key: count for key, count in seen_ids.items() if count > 1}
    expected_positions = set(range(1, total + 1))
    actual_positions = set(positions)
    validation = {
        "available": True,
        "reported_record_count": total,
        "parsed_record_count": len(assembled),
        "record_count_matches": len(assembled) == total,
        "cached_page_count": len(pages),
        "positions_present": len(actual_positions),
        "missing_positions": sorted(expected_positions - actual_positions)[:100],
        "duplicate_positions": sorted(value for value, count in Counter(positions).items() if count > 1)[:100],
        "missing_control_numbers": missing_control,
        "duplicate_control_numbers": duplicate_bases,
        "unsafe_marc_projection_ids": [
            record["id"]
            for record in assembled
            if public_marc_projection(record["marc_projection"]) != record["marc_projection"]
        ],
        **dict(projection_stats),
    }
    return assembled, validation


def digital_search_url(page: int) -> str:
    params = {
        "fa": LOC_DIGITAL_FACET,
        "fo": "json",
        "c": str(LOC_DIGITAL_PAGE_SIZE),
        "sp": str(page),
        "at": "pagination,results",
    }
    return LOC_DIGITAL_ENDPOINT + "?" + urllib.parse.urlencode(params)


def loc_item_id(value: Mapping[str, Any]) -> str:
    url = value.get("url") or value.get("id") or ""
    path = urllib.parse.urlparse(str(url)).path.rstrip("/")
    return path.rsplit("/", 1)[-1] if path else ""


def harvest_digital(
    root: Path,
    *,
    refresh: bool,
    delay: float,
    item_details: bool,
    item_delay: float,
) -> list[FetchEvent]:
    cache_root = root / "cache" / "loc_digital"
    active_path = cache_root / "active.json"
    pending_path = cache_root / "pending.json"
    active = load_json(active_path) if active_path.exists() else {}
    pending = load_json(pending_path) if pending_path.exists() else {}
    if refresh:
        if pending.get("search_facet") == LOC_DIGITAL_FACET and pending.get("search_directory"):
            generation = pending
        else:
            identifier = generation_id()
            base = cache_root / "generations" / identifier
            generation = {
                "schema": "shelfsignals-loc-digital-pending@1",
                "search_facet": LOC_DIGITAL_FACET,
                "search_directory": str((base / "search").relative_to(root)),
                "detail_directory": str((base / "items").relative_to(root)),
                "failure_directory": str((base / "failures").relative_to(root)),
            }
            atomic_write_json(pending_path, generation)
    elif active.get("search_directory"):
        if active.get("search_facet", LOC_DIGITAL_FACET) != LOC_DIGITAL_FACET:
            raise ExtractionError("Active digital snapshot uses a different facet; use --refresh")
        generation = active
    else:
        generation = {
            "search_directory": str((cache_root / "search").relative_to(root)),
            "detail_directory": str((cache_root / "items").relative_to(root)),
            "failure_directory": str((cache_root / "failures").relative_to(root)),
        }
    search_dir = root / generation["search_directory"]
    detail_dir = root / generation["detail_directory"]
    failure_dir = root / generation["failure_directory"]
    fetcher = CachedFetcher(min_interval=delay, refresh=False)
    first = json.loads(fetcher.fetch(digital_search_url(1), search_dir / "0001.json"))
    pagination = first.get("pagination", {})
    pages = int(pagination.get("total") or 1)
    results = list(first.get("results", []))
    for page in range(2, pages + 1):
        payload = json.loads(fetcher.fetch(digital_search_url(page), search_dir / f"{page:04d}.json"))
        if int((payload.get("pagination") or {}).get("of") or 0) != int(pagination.get("of") or 0):
            raise ExtractionError(f"loc.gov digital total changed during harvest at page {page}")
        results.extend(payload.get("results", []))
    reported_total = int(pagination.get("of") or 0)
    item_ids = [loc_item_id(result) for result in results]
    if len(results) != reported_total:
        raise ExtractionError(f"loc.gov digital generation has {len(results)} rows, expected {reported_total}")
    if not all(item_ids) or len(item_ids) != len(set(item_ids)):
        raise ExtractionError("loc.gov digital generation contains missing or duplicate item IDs")
    details_required = bool(item_details or (not refresh and active.get("item_details_requested")))
    if item_details:
        detail_fetcher = CachedFetcher(min_interval=max(item_delay, 3.05), refresh=False)
        for index, result in enumerate(results, 1):
            item_id = loc_item_id(result)
            if not item_id:
                raise ExtractionError(f"Digital result {index} has no stable LOC item URL")
            item_url = f"https://www.loc.gov/item/{urllib.parse.quote(item_id)}/?fo=json&at=item,resources"
            try:
                detail_fetcher.fetch(item_url, detail_dir / f"{item_id}.json")
            except (ExtractionError, urllib.error.HTTPError) as exc:
                failure_path = failure_dir / f"{item_id}.json"
                atomic_write_json(failure_path, {
                    "schema": "shelfsignals-loc-digital-fetch-failure@1",
                    "item_id": item_id,
                    "request_url": item_url,
                    "failed_at": utc_now(),
                    "error": str(exc),
                    "search_result_retained": True,
                    "retry_on_next_run": True,
                })
                print(f"warning: digital item detail unavailable after retries: {item_id}: {exc}", file=sys.stderr, flush=True)
        fetcher.events.extend(detail_fetcher.events)
    missing_detail_ids = [item_id for item_id in item_ids if not (detail_dir / f"{item_id}.json").exists()]
    if details_required and missing_detail_ids:
        raise ExtractionError(
            f"Refusing to activate digital snapshot with {len(missing_detail_ids)} missing requested item details"
        )
    active_payload = {
        "schema": "shelfsignals-loc-digital-cache@1",
        "complete": True,
        "search_facet": LOC_DIGITAL_FACET,
        "search_directory": str(search_dir.relative_to(root)),
        "detail_directory": str(detail_dir.relative_to(root)),
        "failure_directory": str(failure_dir.relative_to(root)),
        "reported_item_count": reported_total,
        "expected_search_pages": pages,
        "item_details_requested": details_required,
        "item_ids": item_ids,
    }
    atomic_write_json(active_path, active_payload)
    if pending_path.exists() and generation.get("search_directory") == pending.get("search_directory"):
        pending_path.unlink()
    return fetcher.events


def load_digital_items(root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    cache_root = root / "cache" / "loc_digital"
    active_path = cache_root / "active.json"
    active = load_json(active_path) if active_path.exists() else {}
    if active.get("complete") is False:
        raise ExtractionError("loc.gov digital active snapshot is not marked complete")
    search_dir = root / active.get("search_directory", str((cache_root / "search").relative_to(root)))
    first_path = search_dir / "0001.json"
    if not first_path.exists():
        return [], {"available": False, "reason": "no cached loc.gov result pages"}
    first_payload = load_json(first_path)
    first_pagination = first_payload.get("pagination", {})
    expected_pages = int(first_pagination.get("total") or 0)
    search_pages = [search_dir / f"{page:04d}.json" for page in range(1, expected_pages + 1)]
    missing_pages = [path.name for path in search_pages if not path.exists()]
    if missing_pages:
        raise ExtractionError(f"loc.gov digital active snapshot is missing pages: {missing_pages[:10]}")
    expected_names = {path.name for path in search_pages}
    unexpected_pages = sorted(
        path.name
        for path in search_dir.glob("*.json")
        if not path.name.endswith(".meta.json") and path.name not in expected_names
    )
    if unexpected_pages:
        raise ExtractionError(f"loc.gov digital active snapshot has unexpected pages: {unexpected_pages[:10]}")
    results: list[dict[str, Any]] = []
    reported_totals: set[int] = set()
    reported_page_totals: set[int] = set()
    for page in search_pages:
        payload = load_json(page)
        pagination = payload.get("pagination", {})
        reported_totals.add(int(pagination.get("of") or 0))
        reported_page_totals.add(int(pagination.get("total") or 0))
        results.extend(payload.get("results", []))
    if len(reported_totals) != 1 or reported_page_totals != {expected_pages}:
        raise ExtractionError("loc.gov digital cached pages disagree on pagination totals")
    reported_total = next(iter(reported_totals))
    details_dir = root / active.get("detail_directory", str((cache_root / "items").relative_to(root)))
    seen: Counter[str] = Counter()
    assembled = []
    detail_count = 0
    detail_with_rights = 0
    detail_with_resources = 0
    for position, result in enumerate(results, 1):
        item_id = loc_item_id(result) or f"position-{position}"
        seen[item_id] += 1
        identity = item_id if seen[item_id] == 1 else f"{item_id}:duplicate-{seen[item_id]}"
        detail_path = details_dir / f"{item_id}.json"
        detail = load_json(detail_path) if detail_path.exists() else None
        if detail is not None:
            detail_count += 1
            if (detail.get("item") or {}).get("rights"):
                detail_with_rights += 1
            if detail.get("resources"):
                detail_with_resources += 1
        assembled.append({
            "schema": "shelfsignals-loc-digital-item@1",
            "id": f"loc:digital:{identity}",
            "entity_type": "digital_object_or_item_record",
            "source": {
                "authority": "Library of Congress",
                "service": "loc.gov JSON API",
                "search_facet": LOC_DIGITAL_FACET,
                "item_id": item_id,
            },
            "search_result": result,
            "item_detail": detail,
        })
    validation = {
        "available": True,
        "reported_item_count": reported_total,
        "parsed_item_count": len(assembled),
        "item_count_matches": reported_total == len(assembled),
        "expected_search_pages": expected_pages,
        "cached_search_pages": len(search_pages),
        "item_details_present": detail_count,
        "item_details_with_nonempty_item_rights": detail_with_rights,
        "item_details_with_nonempty_resources": detail_with_resources,
        "duplicate_item_ids": {key: count for key, count in seen.items() if count > 1},
        "active_item_ids_match": (
            not active.get("item_ids")
            or list(active.get("item_ids", [])) == [loc_item_id(result) for result in results]
        ),
        "item_details_requested": bool(active.get("item_details_requested")),
    }
    return assembled, validation


class PreformattedTextParser(HTMLParser):
    """Extract text inside PRE while preserving source line boundaries."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.in_pre = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() == "pre":
            self.in_pre += 1
        elif self.in_pre and tag.lower() in {"br", "p"}:
            self.parts.append("\n")

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() == "pre" and self.in_pre:
            self.in_pre -= 1
        elif self.in_pre and tag.lower() in {"p"}:
            self.parts.append("\n")

    def handle_data(self, data: str) -> None:
        if self.in_pre:
            self.parts.append(data)

    def value(self) -> str:
        return "".join(self.parts).replace("\r\n", "\n").replace("\r", "\n")


def preformatted_text(raw: bytes) -> str:
    parser = PreformattedTextParser()
    parser.feed(raw.decode("utf-8", errors="replace"))
    parser.close()
    return parser.value()


def parse_loc_sowerby_toc(raw: bytes) -> dict[str, Any]:
    text = preformatted_text(raw)
    volume_ranges = []
    for roman, first, last in re.findall(
        r"Volume\s+([IVX]+)\s+contains entries\s+(\d+)\s*-\s*(\d+)", text, re.IGNORECASE
    ):
        volume_ranges.append({
            "volume": roman.upper(),
            "first_sowerby_number": int(first),
            "last_sowerby_number": int(last),
            "entry_count": int(last) - int(first) + 1,
        })
    chapters: list[dict[str, Any]] = []
    current_volume = ""
    current_section = ""
    for raw_line in text.splitlines():
        line = raw_line.strip()
        volume_match = re.fullmatch(r"Volume\s+([IVX]+)", line, re.IGNORECASE)
        if volume_match:
            current_volume = volume_match.group(1).upper()
            continue
        upper = normalized_space(line).upper()
        if upper in {
            "HISTORY - CIVIL", "HISTORY - NATURAL", "PHILOSOPY - MORAL", "PHILOSOPHY - MORAL",
            "PHILOSOPHY", "FINE ARTS", "FINE ARTS [CONCLUDED]",
        }:
            current_section = normalized_space(line)
            continue
        match = re.match(r"^([IVXLCDM]+)\s+(.+?)\s*$", line)
        if not match:
            continue
        roman = match.group(1).upper()
        number = roman_to_int(roman)
        if number is None or not 1 <= number <= 44:
            continue
        remainder = normalized_space(match.group(2))
        page_match = re.match(r"^(.*?)(?:\s+(\d+))?$", remainder)
        assert page_match
        heading = normalized_space(page_match.group(1))
        page = int(page_match.group(2)) if page_match.group(2) else None
        chapters.append({
            "chapter_roman": roman,
            "chapter_number": number,
            "heading": heading,
            "printed_page": page,
            "volume": current_volume,
            "section": current_section,
            "faculty": faculty_for_chapter(number),
        })
    # The TOC has exactly one principal row for each chapter; keep source order
    # and expose any parsing discrepancy rather than inventing rows.
    return {"volume_ranges": volume_ranges, "chapters": chapters, "preformatted_text_sha256": sha256_bytes(text.encode("utf-8"))}


def parse_loc_index_references(value: str) -> list[dict[str, Any]]:
    references: list[dict[str, Any]] = []
    occupied: set[tuple[int, int]] = set()
    for match in re.finditer(r"\b([IVX]+)\s*,?\s*p\.?\s*(\d+)\b", value, re.IGNORECASE):
        references.append({"type": "volume_page", "volume": match.group(1).upper(), "page": int(match.group(2)), "raw": match.group(0)})
        occupied.add(match.span())
    for match in re.finditer(r"\b([IVX]+)\s*,\s*(\d{1,4}[a-z]?)\b", value, re.IGNORECASE):
        references.append({"type": "volume_reference", "volume": match.group(1).upper(), "reference": match.group(2), "raw": match.group(0)})
        occupied.add(match.span())
    for match in re.finditer(r"(?<![\w(])(\d{1,4})([a-z]?)(?!\w)", value, re.IGNORECASE):
        if any(start <= match.start() and match.end() <= end for start, end in occupied):
            continue
        number = int(match.group(1))
        if not 1 <= number <= 4931:
            continue
        # Parenthesized numerals in index terms are normally publication years
        # or edition labels, not Sowerby serial references.
        if match.start() > 0 and value[match.start() - 1] == "(":
            continue
        references.append({
            "type": "serial_suffix" if match.group(2) else "serial",
            "sowerby_number": number,
            "suffix": match.group(2).lower(),
            "raw": match.group(0),
        })
    see_match = re.search(r";?\s+see(?:\s+also)?\s+(.+)$", value, re.IGNORECASE)
    if see_match:
        references.append({
            "type": "see_also" if "see also" in see_match.group(0).casefold() else "see",
            "target": normalized_space(see_match.group(1)),
            "raw": normalized_space(see_match.group(0)),
        })
    return references


def parse_loc_sowerby_index(raw: bytes) -> list[dict[str, Any]]:
    text = preformatted_text(raw)
    logical_lines: list[str] = []
    current = ""
    for line in text.splitlines():
        if not line.strip():
            if current:
                logical_lines.append(normalized_space(current))
                current = ""
            continue
        stripped = line.strip()
        if len(stripped) == 1 and stripped.isalpha():
            if current:
                logical_lines.append(normalized_space(current))
                current = ""
            continue
        if line[:1].isspace() and current:
            current += " " + stripped
        else:
            if current:
                logical_lines.append(normalized_space(current))
            current = stripped
    if current:
        logical_lines.append(normalized_space(current))
    entries = []
    for position, value in enumerate(logical_lines, 1):
        candidates = parse_loc_index_references(value)
        entries.append({
            "id": f"loc:sowerby-index:{position}",
            "position": position,
            "term_and_context": value,
            # Numeric typography in the printed index is not machine-regular:
            # dates, ranges, shorthand ranges, suffixes, OCR confusions, and
            # volume/page references overlap. Keep parser output quarantined as
            # candidates; no candidate is an asserted Sowerby-entry edge.
            "references": [],
            "reference_candidates_unvalidated": candidates,
            "reference_parsing_status": "unvalidated; not used for crosswalks or counts",
            "source_url": LOC_SOWERBY_INDEX,
        })
    return entries


def harvest_loc_sowerby_reference(root: Path, *, refresh: bool, delay: float) -> list[FetchEvent]:
    cache_dir = root / "cache" / "loc_sowerby"
    fetcher = CachedFetcher(min_interval=max(delay, 1.0), refresh=refresh)
    sources = (
        (LOC_SOWERBY_ITEM_JSON, cache_dir / "item.json"),
        (LOC_SOWERBY_TOC, cache_dir / "toc.html"),
        (LOC_SOWERBY_INDEX, cache_dir / "index.html"),
    )
    for url, path in sources:
        fetcher.fetch(url, path)
    try:
        fetcher.fetch(SOWERBY_LOC_MANIFEST, cache_dir / "manifest.json")
    except (ExtractionError, urllib.error.HTTPError) as exc:
        atomic_write_json(cache_dir / "manifest-unavailable.json", {
            "schema": "shelfsignals-loc-source-unavailable@1",
            "request_url": SOWERBY_LOC_MANIFEST,
            "failed_at": utc_now(),
            "error": str(exc),
            "required_for_toc_or_index_extraction": False,
            "retry_on_next_run": True,
        })
        print(f"warning: LOC Sowerby IIIF manifest unavailable: {exc}", file=sys.stderr, flush=True)
    return fetcher.events


def load_loc_sowerby_reference(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    cache_dir = root / "cache" / "loc_sowerby"
    required = {name: cache_dir / name for name in ("item.json", "toc.html", "index.html")}
    missing = [name for name, path in required.items() if not path.exists()]
    if missing:
        return {}, [], {"available": False, "reason": "missing LOC Sowerby reference files", "missing": missing}
    item_payload = load_json(required["item.json"])
    toc = parse_loc_sowerby_toc(required["toc.html"].read_bytes())
    index_entries = parse_loc_sowerby_index(required["index.html"].read_bytes())
    resource_summaries = []
    for resource in item_payload.get("resources", []):
        if not isinstance(resource, dict):
            continue
        files = resource.get("files")
        file_count = len(files) if isinstance(files, list) else (int(files) if isinstance(files, int) else None)
        resource_summaries.append({
            key: resource.get(key)
            for key in ("url", "pdf", "fulltext_file", "image", "caption", "version")
            if resource.get(key) is not None
        } | ({"file_count": file_count} if file_count is not None else {}))
    rights = item_payload.get("item", {}).get("rights") or item_payload.get("rights") or []
    reference = {
        "schema": "shelfsignals-loc-sowerby-reference@1",
        "source": {
            "authority": "Library of Congress",
            "item_json": LOC_SOWERBY_ITEM_JSON,
            "iiif_manifest": SOWERBY_LOC_MANIFEST,
            "table_of_contents": LOC_SOWERBY_TOC,
            "alphabetical_index": LOC_SOWERBY_INDEX,
        },
        "base_integer_identifier_count": sum(item["entry_count"] for item in toc["volume_ranges"]),
        "volume_ranges": toc["volume_ranges"],
        "chapters": toc["chapters"],
        "resources": resource_summaries,
        "rights": rights,
        "index_role": "Alphabetical access-point rows retained verbatim; numeric reference candidates are unvalidated and are not crosswalk edges or replacement bibliographic records",
    }
    validation = {
        "available": True,
        "iiif_manifest_available": (cache_dir / "manifest.json").exists(),
        "base_integer_identifier_count": reference["base_integer_identifier_count"],
        "volume_range_count": len(toc["volume_ranges"]),
        "volume_ranges_cover_1_through_4931": (
            len(toc["volume_ranges"]) == 5
            and toc["volume_ranges"][0]["first_sowerby_number"] == 1
            and toc["volume_ranges"][-1]["last_sowerby_number"] == 4931
            and all(
                left["last_sowerby_number"] + 1 == right["first_sowerby_number"]
                for left, right in zip(toc["volume_ranges"], toc["volume_ranges"][1:])
            )
        ),
        "chapter_count": len(toc["chapters"]),
        "chapter_numbers": [item["chapter_number"] for item in toc["chapters"]],
        "chapters_cover_1_through_44": [item["chapter_number"] for item in toc["chapters"]] == list(range(1, 45)),
        "chapter_faculties_match_documented_boundaries": all(
            (1 <= item.get("chapter_number", 0) <= 15 and item.get("faculty") == "History")
            or (16 <= item.get("chapter_number", 0) <= 29 and item.get("faculty") == "Philosophy")
            or (30 <= item.get("chapter_number", 0) <= 44 and item.get("faculty") == "Fine Arts")
            for item in toc["chapters"]
        ),
        "index_logical_rows": len(index_entries),
        "index_logical_rows_with_unvalidated_reference_candidates": sum(
            bool(item.get("reference_candidates_unvalidated")) for item in index_entries
        ),
        "index_reference_candidates_are_crosswalk_edges": False,
    }
    return reference, index_entries, validation


def build_loc_sowerby_spine(reference: Mapping[str, Any]) -> list[dict[str, Any]]:
    """Expand authoritative TOC ranges into identifier-only entry references."""
    result = []
    for volume in reference.get("volume_ranges", []):
        first = int(volume["first_sowerby_number"])
        last = int(volume["last_sowerby_number"])
        for number in range(first, last + 1):
            result.append({
                "schema": "shelfsignals-loc-sowerby-entry-reference@1",
                "id": f"sowerby:{number}",
                "entity_type": "sowerby_entry_reference",
                "sowerby_number": number,
                "identifier_kind": "base_integer_serial",
                "sowerby_volume": volume["volume"],
                "source": {
                    "authority": "Library of Congress",
                    "url": LOC_SOWERBY_TOC,
                    "evidence": "published volume entry range",
                },
                "metadata_status": "base-integer identifier spine only; suffixed/addition identifiers are not represented, and no title, edition, volume count, copy, holding, or reconstruction status is asserted",
            })
    return result


@dataclass
class HtmlNode:
    tag: str
    attrs: dict[str, str]
    children: list[Any] = field(default_factory=list)

    @property
    def classes(self) -> set[str]:
        return set(self.attrs.get("class", "").split())

    def text(self) -> str:
        if self.tag in {"script", "style"}:
            return ""
        return normalized_space(" ".join(child.text() if isinstance(child, HtmlNode) else str(child) for child in self.children))

    def descendants(self) -> Iterator["HtmlNode"]:
        for child in self.children:
            if isinstance(child, HtmlNode):
                yield child
                yield from child.descendants()


class HtmlTreeParser(HTMLParser):
    VOID_TAGS = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = HtmlNode("document", {})
        self.stack = [self.root]

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        node = HtmlNode(tag.lower(), {key: value or "" for key, value in attrs})
        self.stack[-1].children.append(node)
        if tag.lower() not in self.VOID_TAGS:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if tag.lower() not in self.VOID_TAGS:
            self.handle_endtag(tag)

    def handle_endtag(self, tag: str) -> None:
        tag = tag.lower()
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == tag:
                del self.stack[index:]
                return

    def handle_data(self, data: str) -> None:
        if data:
            self.stack[-1].children.append(data)


def parse_html_tree(raw: bytes) -> HtmlNode:
    parser = HtmlTreeParser()
    parser.feed(raw.decode("utf-8", errors="replace"))
    parser.close()
    return parser.root


def nodes_with_class(root: HtmlNode, class_name: str) -> list[HtmlNode]:
    return [node for node in root.descendants() if class_name in node.classes]


def first_class_text(root: HtmlNode, class_name: str) -> str:
    nodes = nodes_with_class(root, class_name)
    return nodes[0].text() if nodes else ""


def roman_to_int(value: str) -> int | None:
    value = value.upper().strip()
    if not value or any(char not in ROMAN_VALUE for char in value):
        return None
    total = 0
    previous = 0
    for char in reversed(value):
        current = ROMAN_VALUE[char]
        total += -current if current < previous else current
        previous = max(previous, current)
    return total


def parse_sowerby_page(raw: bytes, *, volume: str, page: int, source_url: str) -> dict[str, Any]:
    tree = parse_html_tree(raw)
    chapter_label = first_class_text(tree, "ChapterTitle")
    chapter_match = re.search(r"Chapter\s+([IVXLCDM]+)", chapter_label, re.IGNORECASE)
    chapter_roman = chapter_match.group(1).upper() if chapter_match else ""
    chapter_number = roman_to_int(chapter_roman) if chapter_roman else None
    chapter_heading = first_class_text(tree, "head2") if chapter_label else ""
    entries = []
    for fragment_position, entry_node in enumerate(nodes_with_class(tree, "CatalogEntry"), 1):
        class_values: dict[str, list[str]] = defaultdict(list)
        for node in entry_node.descendants():
            value = node.text()
            for class_name in node.classes:
                if value and value not in class_values[class_name]:
                    class_values[class_name].append(value)
        global_text = (class_values.get("BIDNo") or [""])[0]
        number_match = re.search(r"(?<!\d)(\d{1,4})(?!\d)", global_text)
        sequence = (class_values.get("SeqNo") or [""])[0]
        entries.append({
            "schema": "shelfsignals-sowerby-transcription-fragment@1",
            "id": f"sowerby:fragment:{volume}:{page}:{fragment_position:03d}",
            "entity_type": "sowerby_transcription_fragment",
            "sowerby_number": int(number_match.group(1)) if number_match else None,
            "sequence_number": sequence,
            "sequence_marker": "J" if sequence.upper().startswith("J.") else "",
            "html_id": entry_node.attrs.get("id", ""),
            "fragment_position": fragment_position,
            "short_title": (class_values.get("ShortTitle") or [""])[0],
            "alternate_title_location": (class_values.get("AltTitleLoc") or [""])[0],
            "authors": class_values.get("Author", []),
            "long_title": (class_values.get("LongTitle") or [""])[0],
            "call_numbers": class_values.get("CallNo", []),
            "edition_statements": class_values.get("editionStmt", []),
            "bibliography": class_values.get("bibl", []),
            "notes": class_values.get("note", []),
            "publication_places": class_values.get("pubPlace", []),
            "publishers": class_values.get("publisher", []),
            "publication_dates": class_values.get("pubDate", []),
            "formats_or_sizes": class_values.get("size", []),
            "edition_labels": class_values.get("edition", []),
            "class_text": dict(sorted(class_values.items())),
            "source": {
                "authority": "Thomas Jefferson Foundation",
                "service": "Thomas Jefferson's Libraries Sowerby HTML transcription",
                "url": source_url,
                "volume": volume,
                "page": page,
                "loc_scan_item": SOWERBY_LOC_ITEM,
                "loc_iiif_manifest": SOWERBY_LOC_MANIFEST,
            },
        })
    next_pages: list[tuple[str, int]] = []
    for node in tree.descendants():
        if node.tag != "a":
            continue
        href = node.attrs.get("href", "")
        match = SOWERBY_PAGE_PATTERN.match(Path(urllib.parse.urlparse(href).path).name)
        if match:
            next_pages.append((match.group(1), int(match.group(2))))
    return {
        "volume": volume,
        "page": page,
        "chapter_roman": chapter_roman,
        "chapter_number": chapter_number,
        "chapter_heading": chapter_heading,
        "entries": entries,
        "linked_pages": sorted(set(next_pages)),
    }


def harvest_sowerby(
    root: Path,
    *,
    refresh: bool,
    delay: float,
    max_pages_per_volume: int,
) -> list[FetchEvent]:
    cache_dir = root / "cache" / "sowerby_transcription"
    fetcher = CachedFetcher(min_interval=delay, refresh=refresh)
    fetcher.fetch(SOWERBY_TOC, cache_dir / "sowerby.html")
    for volume in SOWERBY_VOLUMES:
        page = 1
        visited: set[int] = set()
        while True:
            if page in visited:
                raise ExtractionError(f"Sowerby navigation loop in volume {volume} at page {page}")
            if len(visited) >= max_pages_per_volume:
                raise ExtractionError(f"Sowerby volume {volume} exceeded safety limit of {max_pages_per_volume} pages")
            visited.add(page)
            filename = f"{volume}_{page}.html"
            url = urllib.parse.urljoin(SOWERBY_BASE, filename)
            raw = fetcher.fetch(url, cache_dir / filename)
            parsed = parse_sowerby_page(raw, volume=volume, page=page, source_url=url)
            forward = sorted(number for linked_volume, number in parsed["linked_pages"] if linked_volume == volume and number > page)
            if not forward:
                break
            if forward[0] != page + 1:
                raise ExtractionError(f"Sowerby volume {volume} jumps from page {page} to {forward[0]}")
            page = forward[0]
    return fetcher.events


def sowerby_page_sort(path: Path) -> tuple[int, int]:
    match = SOWERBY_PAGE_PATTERN.match(path.name)
    if not match:
        return (999, 999999)
    return (SOWERBY_VOLUMES.index(match.group(1)), int(match.group(2)))


def faculty_for_chapter(number: int | None) -> str:
    if number is None:
        return ""
    if 1 <= number <= 15:
        return "History"
    if 16 <= number <= 29:
        return "Philosophy"
    if 30 <= number <= 44:
        return "Fine Arts"
    return ""


def load_sowerby_entries(root: Path) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    pages = sorted((root / "cache" / "sowerby_transcription").glob("*.html"), key=sowerby_page_sort)
    pages = [page for page in pages if SOWERBY_PAGE_PATTERN.match(page.name)]
    if not pages:
        return [], {"available": False, "reason": "no cached Sowerby transcription pages"}
    entries: list[dict[str, Any]] = []
    current_chapter: dict[str, Any] = {volume: {"roman": "", "number": None, "heading": ""} for volume in SOWERBY_VOLUMES}
    pages_by_volume: Counter[str] = Counter()
    for path in pages:
        match = SOWERBY_PAGE_PATTERN.match(path.name)
        assert match
        volume, page_text = match.groups()
        page = int(page_text)
        pages_by_volume[volume] += 1
        url = urllib.parse.urljoin(SOWERBY_BASE, path.name)
        parsed = parse_sowerby_page(path.read_bytes(), volume=volume, page=page, source_url=url)
        if parsed["chapter_number"] is not None:
            current_chapter[volume] = {
                "roman": parsed["chapter_roman"],
                "number": parsed["chapter_number"],
                "heading": parsed["chapter_heading"],
            }
        chapter = current_chapter[volume]
        for entry in parsed["entries"]:
            entry["historical_order"] = {
                "source": "Sowerby reconstructed catalogue sequence",
                "faculty": faculty_for_chapter(chapter["number"]),
                "chapter_roman": chapter["roman"],
                "chapter_number": chapter["number"],
                "chapter_heading": chapter["heading"],
                "volume": volume,
                "page": page,
            }
            entries.append(entry)
    numbers = [entry["sowerby_number"] for entry in entries if entry["sowerby_number"] is not None]
    counter = Counter(numbers)
    maximum = max(numbers, default=0)
    validation = {
        "available": True,
        "parsed_fragment_count": len(entries),
        "fragments_with_sowerby_number": len(numbers),
        "minimum_sowerby_number": min(numbers, default=None),
        "maximum_sowerby_number": maximum or None,
        "missing_numbers_through_maximum": [number for number in range(1, maximum + 1) if number not in counter],
        "duplicate_sowerby_numbers": {str(number): count for number, count in counter.items() if count > 1},
        "j_marked_entries": sum(1 for entry in entries if entry["sequence_marker"] == "J"),
        "cached_pages_by_volume": dict(sorted(pages_by_volume.items())),
    }
    return entries, validation


def digital_lccns(item: Mapping[str, Any]) -> list[str]:
    result = item.get("search_result", {})
    values = result.get("number_lccn") or []
    if isinstance(values, str):
        values = [values]
    return stable_unique(normalize_lccn(value) for value in values)


def build_crosswalk(
    catalog_entities: Sequence[Mapping[str, Any]],
    sowerby_entries: Sequence[Mapping[str, Any]],
    digital_items: Sequence[Mapping[str, Any]],
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    catalog_by_sowerby: dict[int, list[str]] = defaultdict(list)
    catalog_by_lccn: dict[str, list[str]] = defaultdict(list)
    catalog_lccns_by_id: dict[str, list[str]] = defaultdict(list)
    catalog_evidence_by_sowerby: dict[int, set[str]] = defaultdict(set)
    digital_by_lccn: dict[str, list[str]] = defaultdict(list)
    evidence_eligible_catalog_ids = {
        str(record["id"])
        for record in catalog_entities
        if record.get("source_marc_projection") is not None or record.get("marc_projection") is not None
    }
    for record in catalog_entities:
        normalized = record["normalized"]
        for number in normalized.get("sowerby_numbers", []):
            catalog_by_sowerby[int(number)].append(record["id"])
            catalog_evidence_by_sowerby[int(number)].add(
                normalized.get("sowerby_evidence") or "explicit MARC 510 Sowerby citation"
            )
        lccns = normalized.get("lccns", [])
        if not lccns and isinstance(normalized.get("identifiers"), dict):
            lccns = normalized.get("identifiers", {}).get("lccn", [])
        for lccn in lccns:
            catalog_by_lccn[normalize_lccn(lccn)].append(record["id"])
            catalog_lccns_by_id[record["id"]].append(normalize_lccn(lccn))
    for item in digital_items:
        for lccn in digital_lccns(item):
            digital_by_lccn[lccn].append(item["id"])
    assessment_scope = {
        "method": "one plain base-integer identifier in source MARC 510 subfield c",
        "selected_catalog_entity_count": len(catalog_entities),
        "evidence_eligible_catalog_entity_count": len(evidence_eligible_catalog_ids),
        "catalog_entities_not_assessed": len(catalog_entities) - len(evidence_eligible_catalog_ids),
    }
    crosswalk = []
    for entry in sowerby_entries:
        number = entry.get("sowerby_number")
        catalog_ids = sorted(set(catalog_by_sowerby.get(number, []))) if number is not None else []
        pair_lccns: dict[tuple[str, str], set[str]] = defaultdict(set)
        for catalog_id in catalog_ids:
            for lccn in catalog_lccns_by_id.get(catalog_id, []):
                for digital_id in digital_by_lccn.get(lccn, []):
                    pair_lccns[(catalog_id, digital_id)].add(lccn)
        catalog_digital_links = [
            {
                "catalog_entity_id": catalog_id,
                "digital_item_id": digital_id,
                "match_basis": "normalized LCCN exact",
                "normalized_lccns": sorted(lccns),
            }
            for (catalog_id, digital_id), lccns in sorted(pair_lccns.items())
        ]
        digital_ids = sorted({link["digital_item_id"] for link in catalog_digital_links})
        evidence_values = sorted(catalog_evidence_by_sowerby.get(number, set())) if number is not None else []
        status = (
            "not_established_in_bounded_marc_sample"
            if not catalog_ids
            else ("one_candidate_in_bounded_marc_sample" if len(catalog_ids) == 1 else "multiple_candidates_in_bounded_marc_sample")
        )
        crosswalk.append({
            "sowerby_reference_id": entry["id"],
            "sowerby_base_integer": number,
            "catalog_entity_ids": catalog_ids,
            "digital_item_ids": digital_ids,
            "catalog_digital_links": catalog_digital_links,
            "catalog_assessment_status": status,
            "assessment_scope": assessment_scope,
            "evidence": evidence_values if catalog_ids else [
                "not established by a qualifying source-MARC 510 in the bounded evidence-eligible sample; the remaining selected catalog entities were not assessed"
            ],
        })
    eligible_with_reference = len({
        record["id"]
        for record in catalog_entities
        if record["id"] in evidence_eligible_catalog_ids and record["normalized"].get("sowerby_numbers")
    })
    stats = {
        "sowerby_reference_rows": len(sowerby_entries),
        "sowerby_references_with_one_catalog_candidate_in_bounded_sample": sum(
            1 for item in crosswalk if item["catalog_assessment_status"] == "one_candidate_in_bounded_marc_sample"
        ),
        "sowerby_references_with_multiple_catalog_candidates_in_bounded_sample": sum(
            1 for item in crosswalk if item["catalog_assessment_status"] == "multiple_candidates_in_bounded_marc_sample"
        ),
        "sowerby_references_not_established_in_bounded_sample": sum(
            1 for item in crosswalk if item["catalog_assessment_status"] == "not_established_in_bounded_marc_sample"
        ),
        "selected_catalog_entity_count": len(catalog_entities),
        "catalog_entities_assessed_in_bounded_marc_sample": len(evidence_eligible_catalog_ids),
        "catalog_entities_not_assessed": len(catalog_entities) - len(evidence_eligible_catalog_ids),
        "assessed_catalog_entities_with_qualifying_sowerby_reference": eligible_with_reference,
        "assessed_catalog_entities_without_qualifying_sowerby_reference": len(evidence_eligible_catalog_ids) - eligible_with_reference,
        "digital_items_with_lccn": len({item_id for ids in digital_by_lccn.values() for item_id in ids}),
        "digital_items_linked_to_sowerby_crosswalk": len({
            item_id for item in crosswalk for item_id in item.get("digital_item_ids", [])
        }),
        "catalog_digital_pair_count": sum(len(item.get("catalog_digital_links", [])) for item in crosswalk),
        "catalog_digital_pairs_without_lccn_evidence": sum(
            1
            for item in crosswalk
            for link in item.get("catalog_digital_links", [])
            if link.get("match_basis") != "normalized LCCN exact" or not link.get("normalized_lccns")
        ),
    }
    return crosswalk, stats


def search_text(record: Mapping[str, Any]) -> str:
    normalized = record["normalized"]
    values: list[str] = [normalized.get("title", ""), normalized.get("lccn", ""), normalized.get("year", "")]
    for key in ("uniform_titles", "alternative_titles", "authors", "contributors", "publication_statements", "languages", "series"):
        values.extend(str(item) for item in normalized.get(key, []))
    values.extend(item.get("value", "") if isinstance(item, dict) else str(item) for item in normalized.get("notes", []))
    values.extend(item.get("value", "") if isinstance(item, dict) else str(item) for item in normalized.get("subjects", []))
    values.extend(item.get("value", "") if isinstance(item, dict) else str(item) for item in normalized.get("call_numbers", []))
    values.extend(str(value) for value in normalized.get("sowerby_numbers", []))
    identifiers = normalized.get("identifiers", {})
    if isinstance(identifiers, dict):
        for group in identifiers.values():
            values.extend(str(item) for item in group)
    else:
        values.extend(str(item.get("value", "")) if isinstance(item, dict) else str(item) for item in identifiers)
    return normalized_space(" ".join(values))


def write_sqlite(
    path: Path,
    generated_at: str,
    catalog_instances: Sequence[Mapping[str, Any]],
    sru_records: Sequence[Mapping[str, Any]],
    digital_items: Sequence[Mapping[str, Any]],
    sowerby_entries: Sequence[Mapping[str, Any]],
    loc_sowerby_spine: Sequence[Mapping[str, Any]],
    loc_sowerby_index: Sequence[Mapping[str, Any]],
    crosswalk: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + f".tmp-{os.getpid()}")
    if temporary.exists():
        temporary.unlink()
    connection = sqlite3.connect(temporary)
    fts_enabled = True
    try:
        connection.executescript(
            """
            PRAGMA journal_mode=DELETE;
            PRAGMA synchronous=FULL;
            CREATE TABLE metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
            CREATE TABLE catalog_instances (
              id TEXT PRIMARY KEY,
              instance_uuid TEXT,
              hrid TEXT,
              lccn TEXT,
              title TEXT,
              relationship_to_jefferson TEXT,
              sowerby_numbers_json TEXT NOT NULL,
              holding_count INTEGER NOT NULL,
              item_count INTEGER NOT NULL,
              public_index_eligible INTEGER NOT NULL,
              normalized_json TEXT NOT NULL,
              instance_json TEXT NOT NULL,
              source_marc_projection_json TEXT,
              record_sha256 TEXT NOT NULL
            );
            CREATE TABLE holdings (
              id TEXT PRIMARY KEY,
              catalog_instance_id TEXT NOT NULL,
              hrid TEXT,
              location_id TEXT,
              location_name TEXT,
              discovery_suppress INTEGER NOT NULL,
              source_json TEXT NOT NULL
            );
            CREATE TABLE items (
              id TEXT PRIMARY KEY,
              catalog_instance_id TEXT NOT NULL,
              hrid TEXT,
              status TEXT,
              material_type TEXT,
              location_id TEXT,
              location_name TEXT,
              call_number TEXT,
              shelving_order TEXT,
              discovery_suppress INTEGER NOT NULL,
              source_json TEXT NOT NULL
            );
            CREATE TABLE catalog_records (
              id TEXT PRIMARY KEY,
              loc_control_number TEXT,
              lccn TEXT,
              title TEXT,
              year TEXT,
              relationship_to_jefferson TEXT,
              sowerby_numbers_json TEXT NOT NULL,
              normalized_json TEXT NOT NULL,
              marc_projection_json TEXT NOT NULL,
              record_sha256 TEXT NOT NULL
            );
            CREATE TABLE digital_items (
              id TEXT PRIMARY KEY,
              item_id TEXT,
              lccns_json TEXT NOT NULL,
              title TEXT,
              source_json TEXT NOT NULL
            );
            CREATE TABLE sowerby_entries (
              id TEXT PRIMARY KEY,
              sowerby_number INTEGER,
              sequence_number TEXT,
              title TEXT,
              author_text TEXT,
              chapter_number INTEGER,
              chapter_heading TEXT,
              source_json TEXT NOT NULL
            );
            CREATE TABLE sowerby_entry_spine (
              id TEXT PRIMARY KEY,
              sowerby_number INTEGER NOT NULL UNIQUE,
              sowerby_volume TEXT NOT NULL,
              metadata_status TEXT NOT NULL,
              source_json TEXT NOT NULL
            );
            CREATE TABLE sowerby_index_terms (
              id TEXT PRIMARY KEY,
              position INTEGER NOT NULL,
              term_and_context TEXT NOT NULL,
              references_json TEXT NOT NULL,
              source_url TEXT NOT NULL
            );
            CREATE TABLE crosswalk (
              sowerby_reference_id TEXT NOT NULL,
              sowerby_base_integer INTEGER,
              catalog_entity_id TEXT,
              digital_item_id TEXT,
              catalog_assessment_status TEXT NOT NULL,
              assessment_scope_json TEXT NOT NULL,
              evidence TEXT NOT NULL
            );
            CREATE INDEX instance_lccn ON catalog_instances(lccn);
            CREATE INDEX holding_instance ON holdings(catalog_instance_id);
            CREATE INDEX item_instance ON items(catalog_instance_id);
            CREATE INDEX catalog_lccn ON catalog_records(lccn);
            CREATE INDEX sowerby_number ON sowerby_entries(sowerby_number);
            CREATE INDEX sowerby_spine_number ON sowerby_entry_spine(sowerby_number);
            CREATE INDEX sowerby_index_position ON sowerby_index_terms(position);
            CREATE INDEX crosswalk_sowerby ON crosswalk(sowerby_base_integer);
            CREATE INDEX crosswalk_catalog ON crosswalk(catalog_entity_id);
            """
        )
        try:
            connection.execute(
                "CREATE VIRTUAL TABLE instance_fts USING fts5(id UNINDEXED, title, creators, subjects, notes, identifiers, call_numbers, sowerby_numbers, all_text)"
            )
            connection.execute(
                "CREATE VIRTUAL TABLE sowerby_index_fts USING fts5(id UNINDEXED, term_and_context, references)"
            )
            connection.execute(
                "CREATE VIRTUAL TABLE catalog_fts USING fts5(id UNINDEXED, title, creators, subjects, notes, identifiers, call_numbers, sowerby_numbers, all_text)"
            )
        except sqlite3.OperationalError:
            fts_enabled = False
            connection.execute(
                "CREATE TABLE IF NOT EXISTS instance_fts (id TEXT PRIMARY KEY, title TEXT, creators TEXT, subjects TEXT, notes TEXT, identifiers TEXT, call_numbers TEXT, sowerby_numbers TEXT, all_text TEXT)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS sowerby_index_fts (id TEXT PRIMARY KEY, term_and_context TEXT, references TEXT)"
            )
            connection.execute(
                "CREATE TABLE IF NOT EXISTS catalog_fts (id TEXT PRIMARY KEY, title TEXT, creators TEXT, subjects TEXT, notes TEXT, identifiers TEXT, call_numbers TEXT, sowerby_numbers TEXT, all_text TEXT)"
            )
        connection.executemany("INSERT INTO metadata(key, value) VALUES (?, ?)", [
            ("schema", "shelfsignals-jefferson-sqlite@1"),
            ("generated_at", generated_at),
            ("catalog_unit", "LOC FOLIO instance returned by the exact contributor-heading query"),
            ("sru_unit", "broad LOC SRU MARC record retained as a separate evidence layer"),
            ("loc_sowerby_spine_unit", "LOC-published Sowerby base-integer identifier; not a complete entry, title, edition, volume, copy, or holding"),
            ("loc_sowerby_index_unit", "logical text row from LOC's alphabetical Sowerby index; numeric candidates are unvalidated"),
            ("monticello_sowerby_fragment_unit", "optional Thomas Jefferson Foundation HTML transcription fragment; absent from the current snapshot"),
            ("crosswalk_unit", "Sowerby base-integer reference assessed only against the declared bounded source-MARC sample"),
            ("crosswalk_assessment_scope_json", json.dumps(
                crosswalk[0].get("assessment_scope", {}) if crosswalk else {},
                ensure_ascii=False,
                sort_keys=True,
            )),
        ])
        for record in catalog_instances:
            normalized = record["normalized"]
            connection.execute(
                "INSERT INTO catalog_instances VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record["id"], normalized.get("instance_uuid", ""), normalized.get("hrid", ""), normalized.get("lccn", ""),
                    normalized.get("title", ""), normalized.get("relationship_to_jefferson", ""),
                    json.dumps(normalized.get("sowerby_numbers", []), ensure_ascii=False), normalized.get("holding_count", 0),
                    normalized.get("item_count", 0), int(bool(normalized.get("public_index_eligible"))),
                    json.dumps(normalized, ensure_ascii=False, sort_keys=True),
                    json.dumps(record.get("instance", {}), ensure_ascii=False, sort_keys=True),
                    json.dumps(record.get("source_marc_projection"), ensure_ascii=False, sort_keys=True)
                    if record.get("source_marc_projection") else None,
                    record["record_sha256"],
                ),
            )
            creators = " | ".join(normalized.get("contributors", []))
            subjects = " | ".join(str(item) for item in normalized.get("subjects", []))
            notes = " | ".join(normalized.get("notes", []))
            identifiers = " | ".join(str(item.get("value", "")) for item in normalized.get("identifiers", []))
            calls = " | ".join(str(item.get("value", "")) for item in normalized.get("call_numbers", []))
            connection.execute(
                "INSERT INTO instance_fts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record["id"], normalized.get("title", ""), creators, subjects, notes, identifiers, calls,
                    " ".join(str(value) for value in normalized.get("sowerby_numbers", [])), search_text(record),
                ),
            )
            source_holdings = {str(item.get("id") or ""): item for item in record.get("instance", {}).get("holdings", [])}
            for holding in normalized.get("holdings", []):
                holding_id = str(holding.get("id") or "")
                if not holding_id:
                    continue
                connection.execute(
                    "INSERT INTO holdings VALUES (?, ?, ?, ?, ?, ?, ?)",
                    (
                        holding_id, record["id"], holding.get("hrid", ""), holding.get("permanent_location_id", ""),
                        holding.get("permanent_location", ""), int(bool(holding.get("discovery_suppress"))),
                        json.dumps(source_holdings.get(holding_id, holding), ensure_ascii=False, sort_keys=True),
                    ),
                )
            source_items = {str(item.get("id") or ""): item for item in record.get("instance", {}).get("items", [])}
            for item in normalized.get("items", []):
                item_id = str(item.get("id") or "")
                if not item_id:
                    continue
                connection.execute(
                    "INSERT INTO items VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        item_id, record["id"], item.get("hrid", ""), item.get("status", ""), item.get("material_type", ""),
                        item.get("effective_location_id", ""), item.get("effective_location", ""), item.get("call_number", ""),
                        item.get("shelving_order", ""), int(bool(item.get("discovery_suppress"))),
                        json.dumps(source_items.get(item_id, item), ensure_ascii=False, sort_keys=True),
                    ),
                )
        for record in sru_records:
            normalized = record["normalized"]
            connection.execute(
                "INSERT INTO catalog_records VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record["id"], normalized.get("loc_control_number", ""), normalized.get("lccn", ""),
                    normalized.get("title", ""), normalized.get("year", ""), normalized.get("relationship_to_jefferson", ""),
                    json.dumps(normalized.get("sowerby_numbers", []), ensure_ascii=False),
                    json.dumps(normalized, ensure_ascii=False, sort_keys=True),
                    json.dumps(record["marc_projection"], ensure_ascii=False, sort_keys=True), record["record_sha256"],
                ),
            )
            connection.execute(
                "INSERT INTO catalog_fts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    record["id"], normalized.get("title", ""), " | ".join(normalized.get("authors", []) + normalized.get("contributors", [])),
                    " | ".join(item["value"] for item in normalized.get("subjects", [])),
                    " | ".join(item["value"] for item in normalized.get("notes", [])),
                    " | ".join(value for group in normalized.get("identifiers", {}).values() for value in group),
                    " | ".join(item["value"] for item in normalized.get("call_numbers", [])),
                    " ".join(str(value) for value in normalized.get("sowerby_numbers", [])), search_text(record),
                ),
            )
        for item in digital_items:
            result = item.get("search_result", {})
            connection.execute(
                "INSERT INTO digital_items VALUES (?, ?, ?, ?, ?)",
                (item["id"], item["source"].get("item_id", ""), json.dumps(digital_lccns(item)), result.get("title", ""), json.dumps(item, ensure_ascii=False, sort_keys=True)),
            )
        for entry in sowerby_entries:
            order = entry.get("historical_order", {})
            connection.execute(
                "INSERT INTO sowerby_entries VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    entry["id"], entry.get("sowerby_number"), entry.get("sequence_number", ""),
                    entry.get("short_title", ""), " | ".join(entry.get("authors", [])), order.get("chapter_number"),
                    order.get("chapter_heading", ""), json.dumps(entry, ensure_ascii=False, sort_keys=True),
                ),
            )
        for entry in loc_sowerby_spine:
            connection.execute(
                "INSERT INTO sowerby_entry_spine VALUES (?, ?, ?, ?, ?)",
                (
                    entry["id"], entry["sowerby_number"], entry["sowerby_volume"],
                    entry["metadata_status"], json.dumps(entry["source"], ensure_ascii=False, sort_keys=True),
                ),
            )
        for entry in loc_sowerby_index:
            references_json = json.dumps(entry.get("references", []), ensure_ascii=False, sort_keys=True)
            connection.execute(
                "INSERT INTO sowerby_index_terms VALUES (?, ?, ?, ?, ?)",
                (
                    entry["id"], entry.get("position", 0), entry.get("term_and_context", ""),
                    references_json, entry.get("source_url", ""),
                ),
            )
            connection.execute(
                "INSERT INTO sowerby_index_fts VALUES (?, ?, ?)",
                (entry["id"], entry.get("term_and_context", ""), references_json),
            )
        for link in crosswalk:
            catalog_ids = link.get("catalog_entity_ids") or [None]
            digital_links_by_catalog: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
            for digital_link in link.get("catalog_digital_links", []):
                digital_links_by_catalog[str(digital_link["catalog_entity_id"])].append(digital_link)
            for catalog_id in catalog_ids:
                related_digital = digital_links_by_catalog.get(str(catalog_id), []) if catalog_id else []
                if not related_digital:
                    related_digital = [None]
                for digital_link in related_digital:
                    connection.execute(
                        "INSERT INTO crosswalk VALUES (?, ?, ?, ?, ?, ?, ?)",
                        (
                            link["sowerby_reference_id"],
                            link.get("sowerby_base_integer"),
                            catalog_id,
                            digital_link.get("digital_item_id") if digital_link else None,
                            link["catalog_assessment_status"],
                            json.dumps(link["assessment_scope"], ensure_ascii=False, sort_keys=True),
                            json.dumps({
                                "sowerby_catalog": link["evidence"],
                                "catalog_digital": digital_link or None,
                            }, ensure_ascii=False, sort_keys=True),
                        ),
                    )
        connection.commit()
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        if integrity != "ok":
            raise ExtractionError(f"SQLite integrity check failed: {integrity}")
    finally:
        connection.close()
    os.replace(temporary, path)
    return {"fts5_enabled": fts_enabled, "integrity_check": "ok"}


def verify_cache_sidecars(root: Path) -> dict[str, Any]:
    """Verify cached response bodies against the retrieval evidence sidecars."""
    cache_root = root / "cache"
    if not cache_root.exists():
        return {
            "applicable": False,
            "sidecars_checked": 0,
            "mismatched_or_invalid_sidecars": [],
            "unattested_cache_files": [],
        }
    meta_paths = sorted(cache_root.rglob("*.meta.json"))
    if not meta_paths:
        # Supports small no-network fixtures and hand-authored research inputs.
        # Real network harvests always create sidecars atomically with bodies.
        return {
            "applicable": False,
            "sidecars_checked": 0,
            "mismatched_or_invalid_sidecars": [],
            "unattested_cache_files": [],
        }
    problems = []
    attested_paths: set[Path] = set()
    for meta_path in meta_paths:
        body_path = meta_path.with_name(meta_path.name.removesuffix(".meta.json"))
        attested_paths.add(body_path)
        relative = str(body_path.relative_to(root))
        try:
            meta = load_json(meta_path)
            raw = body_path.read_bytes()
        except (OSError, ValueError, TypeError) as exc:
            problems.append({"path": relative, "reason": f"unreadable body or sidecar: {type(exc).__name__}"})
            continue
        actual_sha256 = sha256_bytes(raw)
        if meta.get("bytes") != len(raw) or meta.get("sha256") != actual_sha256:
            problems.append({
                "path": relative,
                "reason": "recorded byte count or SHA-256 does not match cached body",
            })
    unattested = []
    for path in sorted(cache_root.rglob("*")):
        if not path.is_file() or path.name.endswith(".meta.json") or path in attested_paths:
            continue
        relative = str(path.relative_to(root))
        is_local_control = path.name in {"active.json", "pending.json"}
        is_failure_ledger = path.name.endswith("-unavailable.json") or "/failures/" in "/" + relative
        if not is_local_control and not is_failure_ledger:
            unattested.append(relative)
    return {
        "applicable": True,
        "sidecars_checked": len(meta_paths),
        "mismatched_or_invalid_sidecars": problems,
        "unattested_cache_files": unattested,
    }


def raw_source_files(root: Path) -> list[dict[str, Any]]:
    cache_root = root / "cache"
    values = []
    if not cache_root.exists():
        return values
    exact_active_directory = ""
    exact_reference_directory = ""
    exact_source_directory = ""
    exact_source_ids: set[str] = set()
    exact_active = cache_root / "loc_catalog_exact" / "active.json"
    if exact_active.exists():
        exact_control = load_json(exact_active)
        exact_active_directory = str(exact_control.get("cache_directory") or "")
        exact_reference_directory = str(exact_control.get("reference_directory") or "")
        exact_source_directory = str(exact_control.get("source_marc_directory") or "")
        exact_source_ids = {str(value) for value in exact_control.get("source_marc_instance_ids", [])}
    digital_active = cache_root / "loc_digital" / "active.json"
    digital_control = load_json(digital_active) if digital_active.exists() else {}
    digital_directories = {
        str(digital_control.get(key) or "")
        for key in ("search_directory", "detail_directory")
        if digital_control.get(key)
    }
    _, sru_status = load_sru_records(root)
    for path in sorted(cache_root.rglob("*")):
        if not path.is_file() or path.name.endswith(".meta.json"):
            continue
        evidence = file_evidence(path, root)
        relative = str(path.relative_to(root))
        role = "primary_source"
        if relative in {
            "cache/loc_catalog_exact/active.json", "cache/loc_catalog_exact/pending.json",
            "cache/loc_digital/active.json", "cache/loc_digital/pending.json",
        }:
            role = "local_control_manifest"
        elif relative.startswith("cache/loc_catalog_exact/"):
            active_catalog_file = (
                (exact_active_directory and relative.startswith(exact_active_directory + "/"))
                or (exact_reference_directory and relative.startswith(exact_reference_directory + "/"))
                or (
                    exact_source_directory
                    and relative.startswith(exact_source_directory + "/")
                    and path.stem in exact_source_ids
                )
            )
            if not active_catalog_file:
                role = "diagnostic_inactive_catalog_generation"
        elif relative.startswith("cache/loc_digital/"):
            active_digital_file = any(relative.startswith(directory + "/") for directory in digital_directories)
            if not active_digital_file:
                role = "diagnostic_inactive_digital_generation"
        elif "/loc_sru/" in "/" + relative and not sru_status.get("available"):
            role = "diagnostic_incomplete_broad_sru_attempt"
        elif "/failures/" in "/" + relative or path.name.endswith("-unavailable.json"):
            role = "diagnostic_source_unavailable"
        evidence["role"] = role
        meta_path = path.with_name(path.name + ".meta.json")
        if meta_path.exists():
            meta = load_json(meta_path)
            evidence.update({
                "request_url": meta.get("request_url", ""),
                "final_url": meta.get("final_url", ""),
                "fetched_at": meta.get("fetched_at", ""),
                "content_type": meta.get("content_type", ""),
                "retrieval_sidecar_integrity_verified": True,
            })
        values.append(evidence)
    return values


def combined_snapshot_hash(files: Sequence[Mapping[str, Any]]) -> str:
    digest = hashlib.sha256()
    for item in files:
        digest.update(str(item["path"]).encode("utf-8"))
        digest.update(b"\0")
        digest.update(str(item["sha256"]).encode("ascii"))
        digest.update(b"\n")
    return "sha256:" + digest.hexdigest()


def build_invariant_report(
    cache_provenance: Mapping[str, Any],
    exact_catalog: Mapping[str, Any],
    sru: Mapping[str, Any],
    digital: Mapping[str, Any],
    loc_sowerby: Mapping[str, Any],
    loc_sowerby_spine: Sequence[Mapping[str, Any]],
    crosswalk: Mapping[str, Any],
) -> dict[str, Any]:
    """Evaluate source-layer invariants before any new package is published."""
    checks: dict[str, dict[str, Any]] = {}

    def add(name: str, applicable: bool, passed: bool, details: Mapping[str, Any]) -> None:
        checks[name] = {
            "status": "not_applicable" if not applicable else ("pass" if passed else "fail"),
            "details": dict(details),
        }

    available_layers = {
        "exact_catalog": bool(exact_catalog.get("available")),
        "broad_sru": bool(sru.get("available")),
        "digital": bool(digital.get("available")),
        "loc_sowerby": bool(loc_sowerby.get("available")),
    }
    add("minimum_source_package", True, any(available_layers.values()), available_layers)
    cache_provenance_applicable = bool(cache_provenance.get("applicable"))
    add(
        "cache_retrieval_provenance",
        cache_provenance_applicable,
        not cache_provenance.get("mismatched_or_invalid_sidecars")
        and not cache_provenance.get("unattested_cache_files"),
        cache_provenance,
    )

    exact_available = bool(exact_catalog.get("available"))
    exact_passed = (
        exact_catalog.get("instance_count_matches") is True
        and exact_catalog.get("cached_page_count") == exact_catalog.get("expected_page_count")
        and not exact_catalog.get("duplicate_instance_uuids")
        and not exact_catalog.get("duplicate_hrids")
        and not exact_catalog.get("duplicate_holding_ids")
        and not exact_catalog.get("duplicate_item_ids")
        and not exact_catalog.get("holdings_without_ids")
        and not exact_catalog.get("items_without_ids")
        and not exact_catalog.get("exact_heading_misses")
        and not exact_catalog.get("suppressed_catalog_nodes_removed")
        and exact_catalog.get("source_marc_records_present") == exact_catalog.get("expected_source_marc_records")
        and not exact_catalog.get("duplicate_source_marc_instance_ids")
        and not exact_catalog.get("missing_source_marc_instance_ids")
        and not exact_catalog.get("source_marc_instance_ids_outside_snapshot")
        and not exact_catalog.get("unsafe_source_marc_projection_ids")
    )
    add("exact_catalog_snapshot", exact_available, exact_passed, {
        key: exact_catalog.get(key)
        for key in (
            "reported_instance_count", "parsed_instance_count", "cached_page_count", "expected_page_count",
            "duplicate_instance_uuids", "duplicate_hrids", "duplicate_holding_ids", "duplicate_item_ids",
            "holdings_without_ids", "items_without_ids", "exact_heading_misses", "suppressed_catalog_nodes_removed",
            "source_marc_records_present", "expected_source_marc_records", "duplicate_source_marc_instance_ids",
            "missing_source_marc_instance_ids", "source_marc_instance_ids_outside_snapshot",
            "unsafe_source_marc_projection_ids", "marc_local_9xx_fields_removed",
            "marc_private_note_fields_removed", "marc_local_subfield_9_values_removed",
        )
    })

    sru_available = bool(sru.get("available"))
    sru_passed = (
        sru.get("record_count_matches") is True
        and not sru.get("missing_positions")
        and not sru.get("duplicate_positions")
        and not sru.get("duplicate_control_numbers")
        and not sru.get("unsafe_marc_projection_ids")
    )
    add("broad_sru_evidence_snapshot", sru_available, sru_passed, {
        key: sru.get(key)
        for key in (
            "reported_record_count", "parsed_record_count", "missing_positions", "duplicate_positions",
            "duplicate_control_numbers", "unsafe_marc_projection_ids", "marc_local_9xx_fields_removed",
            "marc_private_note_fields_removed", "marc_local_subfield_9_values_removed",
        )
    })

    digital_available = bool(digital.get("available"))
    digital_passed = (
        digital.get("item_count_matches") is True
        and digital.get("cached_search_pages") == digital.get("expected_search_pages")
        and not digital.get("duplicate_item_ids")
        and digital.get("active_item_ids_match") is True
        and (
            not digital.get("item_details_requested")
            or digital.get("item_details_present") == digital.get("parsed_item_count")
        )
    )
    add("digital_snapshot", digital_available, digital_passed, {
        key: digital.get(key)
        for key in (
            "reported_item_count", "parsed_item_count", "cached_search_pages", "expected_search_pages",
            "duplicate_item_ids", "active_item_ids_match", "item_details_requested", "item_details_present",
        )
    })

    sowerby_available = bool(loc_sowerby.get("available"))
    spine_numbers = [item.get("sowerby_number") for item in loc_sowerby_spine]
    sowerby_passed = (
        loc_sowerby.get("volume_ranges_cover_1_through_4931") is True
        and loc_sowerby.get("chapters_cover_1_through_44") is True
        and loc_sowerby.get("chapter_faculties_match_documented_boundaries") is True
        and spine_numbers == list(range(1, 4932))
    )
    add("loc_sowerby_reference", sowerby_available, sowerby_passed, {
        "volume_ranges_cover_1_through_4931": loc_sowerby.get("volume_ranges_cover_1_through_4931"),
        "chapters_cover_1_through_44": loc_sowerby.get("chapters_cover_1_through_44"),
        "chapter_faculties_match_documented_boundaries": loc_sowerby.get("chapter_faculties_match_documented_boundaries"),
        "spine_record_count": len(loc_sowerby_spine),
    })

    crosswalk_applicable = bool(loc_sowerby_spine)
    crosswalk_passed = (
        crosswalk.get("sowerby_reference_rows") == len(loc_sowerby_spine)
        and not crosswalk.get("catalog_digital_pairs_without_lccn_evidence")
    )
    add("crosswalk_evidence", crosswalk_applicable, crosswalk_passed, {
        "sowerby_reference_rows": crosswalk.get("sowerby_reference_rows"),
        "expected_sowerby_reference_rows": len(loc_sowerby_spine),
        "catalog_digital_pair_count": crosswalk.get("catalog_digital_pair_count"),
        "catalog_digital_pairs_without_lccn_evidence": crosswalk.get("catalog_digital_pairs_without_lccn_evidence"),
    })

    failures = [name for name, result in checks.items() if result["status"] == "fail"]
    return {
        "all_applicable_invariants_passed": not failures,
        "failed_invariants": failures,
        "checks": checks,
    }


def build_outputs(root: Path, *, generated_at: str | None = None) -> dict[str, Any]:
    generated_at = generated_at or utc_now()
    if not UTC_PATTERN.match(generated_at):
        raise ExtractionError("generated_at must be a whole-second UTC timestamp")
    data_dir = root / "data"
    cache_provenance = verify_cache_sidecars(root)
    if cache_provenance.get("applicable") and (
        cache_provenance.get("mismatched_or_invalid_sidecars")
        or cache_provenance.get("unattested_cache_files")
    ):
        raise ExtractionError("Refusing to build from cache files that do not match retrieval sidecars")
    catalog_instances, exact_catalog_validation = load_exact_catalog_instances(root)
    sru_records, sru_validation = load_sru_records(root)
    digital_items, digital_validation = load_digital_items(root)
    loc_sowerby_reference, loc_sowerby_index, loc_sowerby_validation = load_loc_sowerby_reference(root)
    loc_sowerby_spine = build_loc_sowerby_spine(loc_sowerby_reference)
    sowerby_entries, sowerby_validation = load_sowerby_entries(root)
    crosswalk_source = catalog_instances if catalog_instances else sru_records
    crosswalk_targets = loc_sowerby_spine if loc_sowerby_spine else sowerby_entries
    crosswalk, crosswalk_stats = build_crosswalk(crosswalk_source, crosswalk_targets, digital_items)
    invariant_report = build_invariant_report(
        cache_provenance,
        exact_catalog_validation,
        sru_validation,
        digital_validation,
        loc_sowerby_validation,
        loc_sowerby_spine,
        crosswalk_stats,
    )
    if not invariant_report["all_applicable_invariants_passed"]:
        raise ExtractionError(
            "Refusing to build from an invalid source snapshot: "
            + ", ".join(invariant_report["failed_invariants"])
        )

    data_dir.mkdir(parents=True, exist_ok=True)
    for stale_name in ("loc_catalog_records.jsonl", "sowerby_entries.jsonl", "sowerby_index.json"):
        stale_path = data_dir / stale_name
        if stale_path.exists():
            stale_path.unlink()

    output_paths = {
        "catalog_instances": data_dir / "loc_catalog_instances.jsonl",
        "catalog_index": data_dir / "loc_catalog_index.json",
        "sru_records": data_dir / "loc_sru_marc_records.jsonl",
        "sru_index": data_dir / "loc_sru_broad_index.json",
        "digital_items": data_dir / "loc_digital_items.jsonl",
        "loc_sowerby_reference": data_dir / "loc_sowerby_reference.json",
        "loc_sowerby_spine": data_dir / "loc_sowerby_entry_spine.jsonl",
        "loc_sowerby_index": data_dir / "loc_sowerby_index_terms.jsonl",
        "sowerby_entries": data_dir / "monticello_sowerby_fragments.jsonl",
        "sowerby_index": data_dir / "monticello_sowerby_fragment_index.json",
        "crosswalk": data_dir / "sowerby_loc_crosswalk.jsonl",
        "sqlite": data_dir / "jefferson_catalog.sqlite",
        "source_files": data_dir / "source_files.jsonl",
        "validation": data_dir / "validation.json",
        "manifest": data_dir / "manifest.json",
    }
    atomic_write_jsonl(output_paths["catalog_instances"], catalog_instances)
    atomic_write_jsonl(output_paths["sru_records"], sru_records)
    if catalog_instances:
        catalog_unit = "Library of Congress FOLIO instance returned by the exact contributor-heading query; holdings and items are separate nested entities and the count is not a Sowerby-entry, title, edition, volume, copy, or digital-object count"
        catalog_source = {
            "authority": "Library of Congress",
            "service": "current catalog search API",
            "api_base": CATALOG_API_BASE,
            "filter_query": CATALOG_EXACT_QUERY,
            "query": CATALOG_SORTED_QUERY,
            "sort": "title ascending",
            "query_relation": "exact contributor heading",
            "expanded_holdings_and_items": True,
            "guest_credential_retained": False,
            "staff_only_fields_in_derivative": False,
            "explicit_derivative_field_allowlist": True,
        }
        catalog_items = catalog_instances
    else:
        catalog_unit = "Broad LOC SRU bibliographic MARC result used only as a fallback evidence layer; not an exact corpus definition or a Sowerby-entry, title, edition, volume, copy, holding, or digital-object count"
        catalog_source = {
            "authority": "Library of Congress",
            "service": "LCDB SRU",
            "endpoint": SRU_ENDPOINT,
            "query": SRU_QUERY,
            "record_schema": SRU_SCHEMA,
            "warning": "phrase query is broad and has known false positives",
        }
        catalog_items = sru_records
    catalog_index = {
        "schema": "shelfsignals-jefferson-loc-catalog-index@1",
        "generated_at": generated_at,
        "unit_of_count": catalog_unit,
        "source": catalog_source,
        "record_count": len(catalog_items),
        "items": [dict(record["normalized"], id=record["id"], record_sha256=record["record_sha256"]) for record in catalog_items],
    }
    atomic_write_json(output_paths["catalog_index"], catalog_index, pretty=False)
    atomic_write_json(output_paths["sru_index"], {
        "schema": "shelfsignals-jefferson-loc-sru-broad-index@1",
        "generated_at": generated_at,
        "unit_of_count": "LOC bibliographic MARC result from a broad phrase query; evidence/enrichment candidates only",
        "source": {"endpoint": SRU_ENDPOINT, "query": SRU_QUERY, "record_schema": SRU_SCHEMA},
        "record_count": len(sru_records),
        "items": [dict(record["normalized"], id=record["id"], record_sha256=record["record_sha256"]) for record in sru_records],
    }, pretty=False)
    atomic_write_jsonl(output_paths["digital_items"], digital_items)
    atomic_write_json(output_paths["loc_sowerby_reference"], loc_sowerby_reference)
    atomic_write_jsonl(output_paths["loc_sowerby_spine"], loc_sowerby_spine)
    atomic_write_jsonl(output_paths["loc_sowerby_index"], loc_sowerby_index)
    atomic_write_jsonl(output_paths["sowerby_entries"], sowerby_entries)
    atomic_write_json(output_paths["sowerby_index"], {
        "schema": "shelfsignals-sowerby-transcription-fragment-index@1",
        "generated_at": generated_at,
        "unit_of_count": "HTML transcription fragment, not canonical Sowerby entry; continuations, nested entries, ranges, suffixes, duplicates, and gaps require reconciliation before entry-level use",
        "source": {
            "transcription_authority": "Thomas Jefferson Foundation",
            "transcription_url": SOWERBY_TOC,
            "underlying_loc_scan_item": SOWERBY_LOC_ITEM,
            "underlying_loc_iiif_manifest": SOWERBY_LOC_MANIFEST,
        },
        "fragment_count": len(sowerby_entries),
        "items": sowerby_entries,
    }, pretty=False)
    atomic_write_jsonl(output_paths["crosswalk"], crosswalk)
    sqlite_validation = write_sqlite(
        output_paths["sqlite"], generated_at, catalog_instances, sru_records, digital_items, sowerby_entries,
        loc_sowerby_spine, loc_sowerby_index, crosswalk
    )
    source_files = raw_source_files(root)
    atomic_write_jsonl(output_paths["source_files"], source_files)
    validation = {
        "schema": "shelfsignals-jefferson-extract-validation@1",
        "generated_at": generated_at,
        "catalog_exact": exact_catalog_validation,
        "catalog_sru_broad": sru_validation,
        "digital": digital_validation,
        "loc_sowerby_reference": loc_sowerby_validation,
        "loc_sowerby_spine": {
            "record_count": len(loc_sowerby_spine),
            "numbers_cover_1_through_4931": [item["sowerby_number"] for item in loc_sowerby_spine] == list(range(1, 4932)),
            "identifier_only": True,
        },
        "sowerby": sowerby_validation,
        "crosswalk": crosswalk_stats,
        "sqlite": sqlite_validation,
        "invariants": invariant_report,
    }
    atomic_write_json(output_paths["validation"], validation)
    output_evidence = {
        key: file_evidence(path, root)
        for key, path in output_paths.items()
        if key not in {"manifest"} and path.exists()
    }
    manifest = {
        "schema": "shelfsignals-jefferson-extract@1",
        "generated_at": generated_at,
        "scope": (
            "Research extraction of the exact current LOC catalog contributor-heading result set with expanded holdings/items, "
            "a separately labeled broad SRU/MARC evidence layer when present, the loc.gov digital subset, and LOC's Sowerby "
            "TOC/index/base-integer spine. "
            + ("A separately attributed Monticello transcription-fragment layer is present. " if sowerby_entries else "No Monticello transcription is included. ")
            + "It is not an authoritative copy/status inventory of the complete 1815 physical library."
        ),
        "counts": {
            "loc_exact_catalog_instances": len(catalog_instances),
            "loc_exact_catalog_holdings": exact_catalog_validation.get("holdings", 0),
            "loc_exact_catalog_items": exact_catalog_validation.get("items", 0),
            "loc_broad_sru_marc_records": len(sru_records),
            "loc_digital_items": len(digital_items),
            "loc_sowerby_base_integer_identifiers": loc_sowerby_reference.get("base_integer_identifier_count", 0),
            "loc_sowerby_entry_spine": len(loc_sowerby_spine),
            "loc_sowerby_index_terms": len(loc_sowerby_index),
            "monticello_sowerby_transcription_fragments": len(sowerby_entries),
        },
        "source_snapshot": {
            "file_count": len(source_files),
            "bytes": sum(item["bytes"] for item in source_files),
            "combined_sha256": combined_snapshot_hash(source_files),
            "primary_file_count": sum(1 for item in source_files if item.get("role") == "primary_source"),
            "primary_bytes": sum(item["bytes"] for item in source_files if item.get("role") == "primary_source"),
            "primary_combined_sha256": combined_snapshot_hash([
                item for item in source_files if item.get("role") == "primary_source"
            ]),
            "diagnostic_file_count": sum(1 for item in source_files if item.get("role") != "primary_source"),
            "file_manifest": str(output_paths["source_files"].relative_to(root)),
        },
        "outputs": output_evidence,
        "validation": str(output_paths["validation"].relative_to(root)),
        "caveats": [
            "The exact catalog result count is a count of current LOC FOLIO instances carrying the exact contributor heading, not a count of Sowerby entries or physical volumes.",
            "Attached holdings and items can include inventory objects outside the Jefferson collection and must not be treated as collection-size or copy-status totals.",
            f"Complete ordered raw source MARC is retained only in the ignored cache for {exact_catalog_validation.get('source_marc_records_present', 0)} stable title-sorted sample records; derivatives contain an allowlisted public-safe projection.",
            "The current catalog API is used by LOC's public catalog application but is not documented as a supported bulk API; confirm access, rate, and reuse expectations with LOC before production use.",
            "Raw expanded catalog pages and raw source MARC can contain restricted operational metadata. They remain only in the ignored local source snapshot; staff-only/suppressed nodes, internal user UUIDs, administrative/circulation notes, barcodes, tags, MARC 9XX/local subfield 9 data, private MARC notes, and fields outside explicit derivative allowlists are excluded from JSON, SQLite, and index projections.",
            "The SRU phrase query is broad and includes false positives; it is never used as the primary corpus definition. Raw SRU MARC remains in ignored XML cache files; generated derivatives contain only the public-safe MARC projection.",
            "The loc.gov JSON facet represents the online/digital subset and is not a complete catalog inventory.",
            f"Of {digital_validation.get('item_details_present', 0)} digital detail responses, {digital_validation.get('item_details_with_nonempty_item_rights', 0)} contain nonempty item rights metadata and {digital_validation.get('item_details_with_nonempty_resources', 0)} contain resources; missing fields require review.",
            "The LOC Sowerby spine represents consecutive base integers only. Suffixed/addition identifiers and alphabetical-index numeric candidates are not promoted to crosswalk edges.",
            "The optional Monticello Sowerby HTML layer is not included in this snapshot; acknowledging terms in the CLI is not reuse permission.",
            "No replacement/surrogate/missing reconstruction status is inferred when the catalog supplies no explicit evidence.",
        ],
    }
    atomic_write_json(output_paths["manifest"], manifest)
    return manifest


def print_fetch_summary(label: str, events: Sequence[FetchEvent]) -> None:
    fetched = sum(1 for event in events if not event.cache_hit)
    cached = len(events) - fetched
    total_bytes = sum(event.bytes for event in events if not event.cache_hit)
    print(f"{label}: {len(events)} responses ({fetched} fetched, {cached} cached; {total_bytes:,} new bytes)", flush=True)


def parse_args(argv: Sequence[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("catalog", "sru", "digital", "loc-sowerby", "sowerby", "build", "all"))
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help=f"Cache/output root (default: {DEFAULT_ROOT})")
    parser.add_argument("--refresh", action="store_true", help="Fetch an isolated source generation and activate it only after validation")
    parser.add_argument("--generated-at", default="", help="Whole-second UTC timestamp for deterministic builds")
    parser.add_argument("--catalog-delay", type=float, default=0.8, help="Minimum seconds between uncached current-catalog API requests")
    parser.add_argument("--catalog-page-size", type=int, default=CATALOG_PAGE_SIZE)
    parser.add_argument("--source-marc-limit", type=int, default=0, help="Fetch source MARC for the first N stable title-sorted exact instances (0 preserves the active sample unless refreshing)")
    parser.add_argument("--sru-delay", type=float, default=0.8, help="Minimum seconds between uncached broad SRU evidence requests")
    parser.add_argument("--sru-page-size", type=int, default=SRU_PAGE_SIZE)
    parser.add_argument("--include-broad-sru", action="store_true", help="With all, also harvest the known-broad 3,128-result SRU phrase query")
    parser.add_argument("--digital-delay", type=float, default=3.1, help="Minimum seconds between loc.gov API requests")
    parser.add_argument("--item-details", action="store_true", help="Fetch each loc.gov item's full item/resources JSON")
    parser.add_argument("--loc-reference-delay", type=float, default=3.1, help="Minimum seconds between LOC Sowerby reference requests")
    parser.add_argument("--sowerby-delay", type=float, default=0.35, help="Minimum seconds between transcription page requests")
    parser.add_argument("--sowerby-max-pages", type=int, default=800, help="Per-volume crawl safety limit")
    parser.add_argument("--include-sowerby-transcription", action="store_true", help="With all, also crawl the copyrighted Monticello transcription after acknowledging its terms")
    parser.add_argument("--acknowledge-monticello-terms", action="store_true", help="Self-attest that terms were reviewed; this flag is not reuse permission")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv if argv is not None else sys.argv[1:])
    root = args.root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    if args.catalog_page_size < 1 or args.catalog_page_size > 100:
        raise ExtractionError("catalog page size must be from 1 to 100")
    if args.sru_page_size < 1 or args.sru_page_size > 10:
        raise ExtractionError("SRU page size must be from 1 to 10; larger migrated-LCDB pages have failed during pagination")
    if args.source_marc_limit < 0:
        raise ExtractionError("source MARC limit cannot be negative")
    if args.command in {"catalog", "all"}:
        events = harvest_exact_catalog(
            root,
            refresh=args.refresh,
            delay=args.catalog_delay,
            page_size=args.catalog_page_size,
            source_marc_limit=args.source_marc_limit,
        )
        print_fetch_summary("LOC exact catalog", events)
    if args.command == "sru" or (args.command == "all" and args.include_broad_sru):
        events = harvest_sru_catalog(root, refresh=args.refresh, delay=args.sru_delay, page_size=args.sru_page_size)
        print_fetch_summary("LOC broad SRU", events)
    if args.command in {"digital", "all"}:
        events = harvest_digital(
            root,
            refresh=args.refresh,
            delay=args.digital_delay,
            item_details=args.item_details,
            item_delay=args.digital_delay,
        )
        print_fetch_summary("loc.gov digital", events)
    if args.command in {"loc-sowerby", "all"}:
        events = harvest_loc_sowerby_reference(
            root, refresh=args.refresh, delay=args.loc_reference_delay
        )
        print_fetch_summary("LOC Sowerby reference", events)
    if args.command == "sowerby" or (args.command == "all" and args.include_sowerby_transcription):
        if not args.acknowledge_monticello_terms:
            raise ExtractionError(
                "Monticello's transcript is copyrighted and reuse-limited; pass --acknowledge-monticello-terms only when local use is permitted or permission has been secured"
            )
        events = harvest_sowerby(
            root,
            refresh=args.refresh,
            delay=args.sowerby_delay,
            max_pages_per_volume=args.sowerby_max_pages,
        )
        print_fetch_summary("Sowerby transcription", events)
    if args.command in {"catalog", "sru", "digital", "loc-sowerby", "sowerby", "build", "all"}:
        manifest = build_outputs(root, generated_at=args.generated_at or None)
        print(json.dumps({"root": str(root), "counts": manifest["counts"], "snapshot": manifest["source_snapshot"]}, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ExtractionError, ValueError, json.JSONDecodeError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2)
