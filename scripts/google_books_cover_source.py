#!/usr/bin/env python3
"""Discover exact-ISBN Google Books cover leads without publishing them.

This is deliberately a *private and temporary* research workflow.  Google API
content is retained only while the response cache headers grant positive
freshness, the queue contains remote references rather than image binaries,
and no candidate is eligible for public display.  The existing public cover
publisher is intentionally not called or modified here.

An API key is read from ``GOOGLE_BOOKS_API_KEY`` (or another explicitly named
environment variable).  It is never accepted as a command-line value, written
to a URL in an output file, or included in diagnostics.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Callable, Mapping, MutableMapping, Optional, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlparse
from urllib.request import Request, urlopen


VERSION = "1.0.0"
PLAN_SCHEMA = "shelfsignals-google-books-cover-plan@1"
STATE_SCHEMA = "shelfsignals-google-books-cover-discovery-state@1"
QUEUE_SCHEMA = "shelfsignals-google-books-cover-review-queue@1"

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = ROOT / "docs/data/sekula_index.json"
DEFAULT_PLAN = ROOT / ".cache/google-books-cover-source/plan.json"
DEFAULT_STATE = ROOT / ".cache/google-books-cover-source/state.json"
DEFAULT_QUEUE = ROOT / ".cache/google-books-cover-source/candidates.json"

API_ENDPOINT = "https://www.googleapis.com/books/v1/volumes"
API_DOCUMENTATION = "https://developers.google.com/books/docs/v1/using"
VOLUME_DOCUMENTATION = "https://developers.google.com/books/docs/v1/reference/volumes"
PERFORMANCE_DOCUMENTATION = "https://developers.google.com/books/docs/v1/performance"
BOOKS_TERMS = "https://developers.google.com/books/terms"
API_TERMS = "https://developers.google.com/terms"
BRANDING_GUIDELINES = "https://developers.google.com/books/branding"

DEFAULT_API_KEY_ENV = "GOOGLE_BOOKS_API_KEY"
MAX_QUERIES_PER_RUN = 50
DEFAULT_QUERY_LIMIT = 10
MIN_INTERVAL_SECONDS = 1.0
DEFAULT_INTERVAL_SECONDS = 2.0
MAX_RESULTS_PER_QUERY = 10
MAX_RESPONSE_BYTES = 1_000_000
MAX_CACHE_SECONDS = 24 * 60 * 60
USER_AGENT = "ShelfSignals-Google-Books-review/1.0 (gzip; +https://github.com/gitbrainlab/ShelfSignals)"

FIELDS = (
    "totalItems,items(id,etag,selfLink,volumeInfo(title,subtitle,authors,publisher,"
    "publishedDate,industryIdentifiers,pageCount,dimensions,printType,imageLinks,"
    "language,previewLink,infoLink,canonicalVolumeLink),accessInfo(country,viewability,publicDomain))"
)

ISBN_TYPES = {"ISBN_10", "ISBN_13"}
GOOGLE_BOOK_HOSTS = {"books.google.com", "www.google.com"}
GOOGLE_IMAGE_HOST_SUFFIXES = (".google.com", ".googleusercontent.com", ".gstatic.com")
VOLUME_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,128}$")
SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
ISO_UTC_RE = re.compile(r"^20\d{2}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class SourceError(RuntimeError):
    """A concise failure that can be shown without leaking credentials."""


class ApiError(SourceError):
    def __init__(self, message: str, *, status: int = 0, transient: bool = False) -> None:
        super().__init__(message)
        self.status = status
        self.transient = transient


def utc_now() -> str:
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    moment = datetime.fromtimestamp(int(epoch), timezone.utc) if epoch else datetime.now(timezone.utc)
    return moment.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_utc(value: str) -> datetime:
    if not ISO_UTC_RE.fullmatch(str(value or "")):
        raise SourceError(f"invalid UTC timestamp: {value!r}")
    return datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)


def format_utc(value: datetime) -> str:
    return value.astimezone(timezone.utc).replace(microsecond=0).strftime("%Y-%m-%dT%H:%M:%SZ")


def canonical_checksum(value: Any) -> str:
    rendered = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(rendered.encode("utf-8")).hexdigest()


def bytes_checksum(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def file_checksum(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(chunk)
    return "sha256:" + digest.hexdigest()


def read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise SourceError(f"could not read {path}: {exc}") from exc


def ensure_private_path(path: Path) -> None:
    """Refuse accidental output to the deployed site or tracked research tree."""

    resolved = path.resolve()
    try:
        relative = resolved.relative_to(ROOT.resolve())
    except ValueError:
        return
    if ".cache" not in relative.parts:
        raise SourceError("private Google Books workflow only writes beneath .cache inside the repository")


def write_json(path: Path, payload: Any) -> None:
    ensure_private_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    rendered = json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as handle:
        handle.write(rendered)
        temporary = Path(handle.name)
    temporary.replace(path)


def _values(value: Any) -> list[Any]:
    return value if isinstance(value, list) else ([] if value in (None, "") else [value])


def _isbn_checksum_valid(compact: str) -> bool:
    if len(compact) == 10 and re.fullmatch(r"\d{9}[\dX]", compact):
        return sum(
            (10 - index) * (10 if character == "X" else int(character))
            for index, character in enumerate(compact)
        ) % 11 == 0
    if len(compact) == 13 and compact.isdigit():
        return sum(
            int(character) * (1 if index % 2 == 0 else 3)
            for index, character in enumerate(compact)
        ) % 10 == 0
    return False


def normalize_isbn(value: Any) -> str:
    compact = re.sub(r"[^0-9X]", "", str(value or "").upper())
    return compact if _isbn_checksum_valid(compact) else ""


def canonical_isbn(value: Any) -> str:
    normalized = normalize_isbn(value)
    if len(normalized) == 13:
        return normalized
    if len(normalized) != 10:
        return ""
    body = "978" + normalized[:9]
    total = sum(int(character) * (1 if index % 2 == 0 else 3) for index, character in enumerate(body))
    return body + str((-total) % 10)


def catalog_isbns(record: Mapping[str, Any]) -> list[str]:
    return sorted({item for raw in _values(record.get("isbns")) if (item := canonical_isbn(raw))})


def load_catalog(path: Path) -> list[Mapping[str, Any]]:
    payload = read_json(path)
    if not isinstance(payload, list):
        raise SourceError("catalog must be a JSON array")
    records: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    for index, record in enumerate(payload):
        if not isinstance(record, Mapping):
            raise SourceError(f"catalog record {index} is not an object")
        record_id = str(record.get("id") or "").strip()
        if not record_id or record_id in seen:
            raise SourceError(f"catalog record {index} has a missing or duplicate id")
        seen.add(record_id)
        records.append(record)
    return records


def _strings(value: Any, *, limit: int = 8, length: int = 1000) -> list[str]:
    result: list[str] = []
    for raw in _values(value):
        text = str(raw or "").strip()
        if text and len(text) <= length and text not in result:
            result.append(text)
        if len(result) >= limit:
            break
    return result


def _catalog_summary(record: Mapping[str, Any], normalized_isbns: Sequence[str]) -> dict[str, Any]:
    return {
        "title": str(record.get("title") or "Untitled").strip()[:4000],
        "authors": _strings(record.get("authors"), limit=8),
        "year": str(record.get("year") or "").strip()[:500],
        "call_number": str(record.get("call_number") or "").strip()[:1000],
        "normalized_isbns": list(normalized_isbns),
        "catalog_url": str(record.get("record_url") or "").strip()[:4000],
    }


def query_fingerprint(query: Mapping[str, Any]) -> str:
    return canonical_checksum({
        "catalog_id": query.get("catalog_id"),
        "isbn": query.get("isbn"),
        "catalog_isbns": query.get("catalog", {}).get("normalized_isbns", []),
    })


def build_plan(
    records: Sequence[Mapping[str, Any]],
    catalog_path: Path,
    *,
    generated_at: Optional[str] = None,
) -> dict[str, Any]:
    queries: list[dict[str, Any]] = []
    records_with_isbn = 0
    for record in sorted(records, key=lambda item: str(item.get("id") or "")):
        record_id = str(record.get("id") or "").strip()
        isbns = catalog_isbns(record)
        if not isbns:
            continue
        records_with_isbn += 1
        catalog = _catalog_summary(record, isbns)
        for isbn in isbns:
            query = {
                "query_key": f"{record_id}:{isbn}",
                "catalog_id": record_id,
                "isbn": isbn,
                "catalog": catalog,
                "request_url_without_credentials": build_query_url(isbn),
            }
            query["query_fingerprint"] = query_fingerprint(query)
            queries.append(query)

    inputs = {
        "catalog_file": catalog_path.name,
        "catalog_sha256": file_checksum(catalog_path),
        "catalog_records": len(records),
    }
    identity = {
        "inputs": inputs,
        "queries": [
            {key: query[key] for key in ("query_key", "catalog_id", "isbn", "query_fingerprint")}
            for query in queries
        ],
    }
    plan = {
        "schema": PLAN_SCHEMA,
        "generated_at": generated_at or utc_now(),
        "inputs": inputs,
        "provider": provider_contract(),
        "policy": policy_contract(),
        "queries": queries,
        "summary": {
            "catalog_records": len(records),
            "records_with_valid_isbn": records_with_isbn,
            "exact_isbn_queries": len(queries),
            "publication_effect": "none",
        },
    }
    plan["plan_fingerprint"] = canonical_checksum(identity)
    return plan


def validate_plan(
    plan: Mapping[str, Any],
    records: Sequence[Mapping[str, Any]],
    catalog_path: Path,
) -> None:
    if plan.get("schema") != PLAN_SCHEMA:
        raise SourceError(f"plan must use {PLAN_SCHEMA}")
    expected = build_plan(records, catalog_path, generated_at=str(plan.get("generated_at") or utc_now()))
    if plan.get("inputs") != expected["inputs"]:
        raise SourceError("plan is stale for the current catalog input")
    if plan.get("plan_fingerprint") != expected["plan_fingerprint"]:
        raise SourceError("plan fingerprint does not match the current exact-ISBN query set")
    if plan.get("queries") != expected["queries"]:
        raise SourceError("plan queries were changed, reordered, or truncated")


def provider_contract() -> dict[str, Any]:
    return {
        "key": "google_books",
        "name": "Google Books",
        "api": API_DOCUMENTATION,
        "volume_resource": VOLUME_DOCUMENTATION,
        "performance_guidance": PERFORMANCE_DOCUMENTATION,
        "books_terms": BOOKS_TERMS,
        "api_terms": API_TERMS,
        "branding_guidelines": BRANDING_GUIDELINES,
        "discovery_method": "google_books_volumes_q_isbn_exact",
    }


def policy_contract() -> dict[str, Any]:
    return {
        "private_research_queue_only": True,
        "unreviewed_display_allowed": False,
        "auto_publication_allowed": False,
        "image_binaries_downloaded_or_cached": False,
        "remote_references_only": True,
        "title_or_author_match_allowed": False,
        "exact_catalog_isbn_required_in_provider_identifiers": True,
        "provider_cache_headers_control_retention": True,
        "retention_hard_cap_seconds": MAX_CACHE_SECONDS,
        "underlying_cover_rights": "not_established",
        "physical_evidence_scope": "provider_volume_metadata_only_not_clark_copy",
        "pixel_inference_of_texture_or_thickness_allowed": False,
    }


def build_query_url(isbn: str, api_key: str = "") -> str:
    normalized = canonical_isbn(isbn)
    if not normalized:
        raise SourceError("Google Books query requires a valid canonical ISBN")
    params = {
        "q": f"isbn:{normalized}",
        "printType": "books",
        # pageCount and physical dimensions are not documented as LITE fields;
        # a narrow fields selector keeps the full projection bounded.
        "projection": "full",
        "maxResults": str(MAX_RESULTS_PER_QUERY),
        "fields": FIELDS,
    }
    if api_key:
        params["key"] = api_key
    return API_ENDPOINT + "?" + urlencode(params)


def _headers_lower(headers: Mapping[str, Any]) -> dict[str, str]:
    return {str(key).lower(): str(value).strip() for key, value in headers.items()}


def cache_policy(headers: Mapping[str, Any], fetched_at: str) -> Optional[dict[str, Any]]:
    """Return positive freshness evidence, or None when persistence is unsafe."""

    lowered = _headers_lower(headers)
    cache_control = lowered.get("cache-control", "")
    directives = {part.strip().lower() for part in cache_control.split(",") if part.strip()}
    if "no-store" in directives or "no-cache" in directives or lowered.get("pragma", "").lower() == "no-cache":
        return None
    seconds: Optional[int] = None
    for directive in directives:
        match = re.fullmatch(r"max-age\s*=\s*\"?(\d+)\"?", directive)
        if match:
            seconds = int(match.group(1))
            break
    fetched = parse_utc(fetched_at)
    if seconds is None:
        raw_expires = lowered.get("expires", "")
        if raw_expires:
            try:
                expires = parsedate_to_datetime(raw_expires)
                if expires.tzinfo is None:
                    expires = expires.replace(tzinfo=timezone.utc)
                seconds = max(0, int((expires.astimezone(timezone.utc) - fetched).total_seconds()))
            except (TypeError, ValueError, OverflowError):
                seconds = None
    raw_age = lowered.get("age", "")
    age_seconds = int(raw_age) if raw_age.isdigit() else 0
    if seconds is not None:
        seconds = max(0, seconds - age_seconds)
    if seconds is None or seconds <= 0:
        return None
    retained_seconds = min(seconds, MAX_CACHE_SECONDS)
    return {
        "cache_control": cache_control,
        "expires_header": lowered.get("expires", ""),
        "provider_freshness_seconds": seconds,
        "response_age_seconds": age_seconds,
        "retained_seconds": retained_seconds,
        "retain_until": format_utc(fetched + timedelta(seconds=retained_seconds)),
        "hard_cap_applied": seconds > MAX_CACHE_SECONDS,
    }


def _safe_url(value: Any, *, image: bool = False) -> str:
    text = str(value or "").strip()
    if not text or len(text) > 8000:
        return ""
    parsed = urlparse(text)
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in {"http", "https"}:
        return ""
    if image:
        if not any(host.endswith(suffix) for suffix in GOOGLE_IMAGE_HOST_SUFFIXES):
            return ""
    elif host not in GOOGLE_BOOK_HOSTS and host != "books.googleusercontent.com":
        return ""
    return text


def _best_image(image_links: Mapping[str, Any]) -> tuple[str, str]:
    for key in ("extraLarge", "large", "medium", "small", "thumbnail", "smallThumbnail"):
        url = _safe_url(image_links.get(key), image=True)
        if url:
            return key, url
    return "", ""


def _thumbnail(image_links: Mapping[str, Any], fallback: str) -> str:
    for key in ("smallThumbnail", "thumbnail", "small"):
        url = _safe_url(image_links.get(key), image=True)
        if url:
            return url
    return fallback


def _compact_dimensions(value: Any) -> dict[str, str]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, str] = {}
    for key in ("height", "width", "thickness"):
        text = str(value.get(key) or "").strip()
        if text and len(text) <= 100:
            result[key] = text
    return result


def _provider_identifiers(value: Any) -> tuple[list[dict[str, str]], set[str]]:
    evidence: list[dict[str, str]] = []
    canonical: set[str] = set()
    if not isinstance(value, list):
        return evidence, canonical
    for item in value[:40]:
        if not isinstance(item, Mapping) or item.get("type") not in ISBN_TYPES:
            continue
        normalized = normalize_isbn(item.get("identifier"))
        comparison = canonical_isbn(normalized)
        if not normalized or not comparison:
            continue
        evidence_item = {"type": str(item["type"]), "value": normalized}
        if evidence_item not in evidence:
            evidence.append(evidence_item)
        canonical.add(comparison)
    return evidence, canonical


def _plain_string(value: Any, limit: int = 4000) -> str:
    text = str(value or "").strip()
    return text if len(text) <= limit else text[:limit]


def candidate_fingerprint(candidate: Mapping[str, Any]) -> str:
    return canonical_checksum({
        "catalog_id": candidate.get("catalog_id"),
        "catalog_isbns": candidate.get("catalog_isbns"),
        "query_isbn": candidate.get("query_isbn"),
        "provider": "google_books",
        "scope": candidate.get("scope"),
        "provider_volume_id": candidate.get("provider_volume_id"),
        "provider_result_position": candidate.get("provider_result_position"),
        "matched_identifiers": candidate.get("matched_identifiers"),
        "provider_identifiers": candidate.get("provider_identifiers"),
        "source_url": candidate.get("source_url"),
        "api_info_url": candidate.get("api_info_url"),
        "image_url": candidate.get("image_url"),
        "thumbnail_url": candidate.get("thumbnail_url"),
        "image_size_label": candidate.get("image_size_label"),
        "image_transport": candidate.get("image_transport"),
        "edition_summary": candidate.get("edition_summary"),
        "provider_physical_evidence": candidate.get("provider_physical_evidence"),
        "access_summary": candidate.get("access_summary"),
        "source_metadata": candidate.get("source_metadata"),
        "attribution": candidate.get("attribution"),
        "rights": candidate.get("rights"),
        "review_required": candidate.get("review_required"),
        "public_eligible": candidate.get("public_eligible"),
        "publication_effect": candidate.get("publication_effect"),
    })


def validate_stored_candidate(candidate: Mapping[str, Any], query: Mapping[str, Any]) -> None:
    """Fail closed if private state was edited or belongs to another query."""

    requested = canonical_isbn(query.get("isbn"))
    catalog_values = sorted(set(query.get("catalog", {}).get("normalized_isbns") or []))
    volume_id = str(candidate.get("provider_volume_id") or "")
    expected_key = f"{query['catalog_id']}:google_books:{requested}:{volume_id}"
    required = {
        "catalog_id": query["catalog_id"],
        "catalog_isbns": catalog_values,
        "provider": "google_books",
        "scope": "external_exact_edition",
        "query_isbn": requested,
        "candidate_key": expected_key,
        "review_required": True,
        "public_eligible": False,
        "publication_effect": "none",
    }
    for field, expected in required.items():
        if candidate.get(field) != expected:
            raise SourceError(f"stored candidate has invalid {field}: {expected_key}")
    if not VOLUME_ID_RE.fullmatch(volume_id):
        raise SourceError(f"stored candidate has an invalid Google Books volume ID: {expected_key}")
    position = candidate.get("provider_result_position")
    if isinstance(position, bool) or not isinstance(position, int) or not 0 <= position < MAX_RESULTS_PER_QUERY:
        raise SourceError(f"stored candidate has an invalid provider result position: {expected_key}")
    matched = candidate.get("matched_identifiers")
    if not isinstance(matched, list) or not matched:
        raise SourceError(f"stored candidate lacks exact ISBN evidence: {expected_key}")
    matched_values = {
        canonical_isbn(item.get("value"))
        for item in matched
        if isinstance(item, Mapping) and item.get("type") == "isbn"
    }
    matched_values.discard("")
    if requested not in matched_values or not matched_values.issubset(set(catalog_values)):
        raise SourceError(f"stored candidate ISBN evidence is not exact: {expected_key}")
    if candidate.get("source_url") != f"https://books.google.com/books?id={quote(volume_id, safe='')}":
        raise SourceError(f"stored candidate source URL does not agree with its volume ID: {expected_key}")
    if not _safe_url(candidate.get("image_url"), image=True):
        raise SourceError(f"stored candidate has an invalid provider image URL: {expected_key}")
    if candidate.get("image_transport") != urlparse(str(candidate.get("image_url"))).scheme:
        raise SourceError(f"stored candidate image transport does not agree with its URL: {expected_key}")
    if not _safe_url(candidate.get("thumbnail_url"), image=True):
        raise SourceError(f"stored candidate has an invalid provider thumbnail URL: {expected_key}")
    source_metadata = candidate.get("source_metadata") if isinstance(candidate.get("source_metadata"), Mapping) else {}
    cache = source_metadata.get("cache") if isinstance(source_metadata.get("cache"), Mapping) else {}
    if source_metadata.get("query_url_without_credentials") != query.get("request_url_without_credentials"):
        raise SourceError(f"stored candidate query URL does not agree with the plan: {expected_key}")
    if "key=" in str(source_metadata.get("query_url_without_credentials") or ""):
        raise SourceError(f"stored candidate unexpectedly contains a credential parameter: {expected_key}")
    if not SHA256_RE.fullmatch(str(source_metadata.get("response_sha256") or "")):
        raise SourceError(f"stored candidate lacks a response checksum: {expected_key}")
    rights = candidate.get("rights") if isinstance(candidate.get("rights"), Mapping) else {}
    if (
        rights.get("underlying_cover_rights") != "not_established"
        or rights.get("remote_reference_only") is not True
        or rights.get("binary_download_or_cache_allowed") is not False
        or rights.get("api_content_retain_until") != cache.get("retain_until")
    ):
        raise SourceError(f"stored candidate has unsafe rights state: {expected_key}")
    physical = candidate.get("provider_physical_evidence") if isinstance(candidate.get("provider_physical_evidence"), Mapping) else {}
    if (
        physical.get("scope") != "raw_google_books_provider_volume_metadata_only"
        or physical.get("clark_copy_measurement") is not False
        or physical.get("pixel_inference_used") is not False
    ):
        raise SourceError(f"stored candidate has unsafe physical-evidence scope: {expected_key}")
    fingerprint = str(candidate.get("candidate_fingerprint") or "")
    if not SHA256_RE.fullmatch(fingerprint) or fingerprint != candidate_fingerprint(candidate):
        raise SourceError(f"stored candidate fingerprint is stale or invalid: {expected_key}")


def extract_exact_candidates(
    query: Mapping[str, Any],
    payload: Mapping[str, Any],
    *,
    fetched_at: str,
    response_sha256: str,
    cache: Mapping[str, Any],
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Select only provider volumes whose own ISBN list contains the query ISBN."""

    requested = canonical_isbn(query.get("isbn"))
    catalog_values = set(query.get("catalog", {}).get("normalized_isbns") or [])
    if not requested or requested not in catalog_values:
        raise SourceError("query ISBN is not an exact identifier from its Clark catalog record")
    raw_items = payload.get("items")
    items = raw_items if isinstance(raw_items, list) else []
    candidates: list[dict[str, Any]] = []
    rejected = Counter()
    for position, raw in enumerate(items[:MAX_RESULTS_PER_QUERY]):
        if not isinstance(raw, Mapping):
            rejected["malformed_volume"] += 1
            continue
        volume_id = str(raw.get("id") or "").strip()
        if raw.get("kind") not in (None, "books#volume") or not VOLUME_ID_RE.fullmatch(volume_id):
            rejected["invalid_volume_id"] += 1
            continue
        info = raw.get("volumeInfo") if isinstance(raw.get("volumeInfo"), Mapping) else {}
        provider_ids, provider_canonical = _provider_identifiers(info.get("industryIdentifiers"))
        if requested not in provider_canonical:
            rejected["no_exact_query_isbn"] += 1
            continue
        matched = sorted(catalog_values.intersection(provider_canonical))
        if not matched:
            rejected["no_exact_catalog_isbn"] += 1
            continue
        image_links = info.get("imageLinks") if isinstance(info.get("imageLinks"), Mapping) else {}
        image_size, image_url = _best_image(image_links)
        if not image_url:
            rejected["no_provider_cover_reference"] += 1
            continue
        source_url = f"https://books.google.com/books?id={quote(volume_id, safe='')}"
        api_info_url = _safe_url(info.get("canonicalVolumeLink") or info.get("infoLink"))
        page_count = info.get("pageCount")
        if isinstance(page_count, bool) or not isinstance(page_count, int) or not (0 < page_count < 100_000):
            page_count = None
        dimensions = _compact_dimensions(info.get("dimensions"))
        candidate = {
            "candidate_key": f"{query['catalog_id']}:google_books:{requested}:{volume_id}",
            "catalog_id": query["catalog_id"],
            "catalog_isbns": sorted(catalog_values),
            "provider": "google_books",
            "scope": "external_exact_edition",
            "query_isbn": requested,
            "provider_volume_id": volume_id,
            "provider_result_position": position,
            "matched_identifiers": [{"type": "isbn", "value": value} for value in matched],
            "provider_identifiers": provider_ids,
            "source_url": source_url,
            "api_info_url": api_info_url,
            "image_url": image_url,
            "thumbnail_url": _thumbnail(image_links, image_url),
            "image_size_label": image_size,
            "image_transport": urlparse(image_url).scheme,
            "edition_summary": {
                "title": _plain_string(info.get("title")),
                "subtitle": _plain_string(info.get("subtitle")),
                "authors": _strings(info.get("authors"), limit=20),
                "publisher": _plain_string(info.get("publisher")),
                "published_date": _plain_string(info.get("publishedDate"), 100),
                "language": _plain_string(info.get("language"), 30),
            },
            "provider_physical_evidence": {
                "page_count": page_count,
                "dimensions": dimensions,
                "print_type": _plain_string(info.get("printType"), 50),
                "scope": "raw_google_books_provider_volume_metadata_only",
                "clark_copy_measurement": False,
                "pixel_inference_used": False,
                "caveat": "These fields describe the exact-ISBN Google Books volume record, not Clark's physical copy, binding, jacket, texture, condition, or side profile.",
            },
            "access_summary": {
                "country": _plain_string((raw.get("accessInfo") or {}).get("country"), 10)
                if isinstance(raw.get("accessInfo"), Mapping) else "",
                "viewability": _plain_string((raw.get("accessInfo") or {}).get("viewability"), 50)
                if isinstance(raw.get("accessInfo"), Mapping) else "",
                "public_domain": (raw.get("accessInfo") or {}).get("publicDomain")
                if isinstance(raw.get("accessInfo"), Mapping)
                and isinstance((raw.get("accessInfo") or {}).get("publicDomain"), bool) else None,
            },
            "source_metadata": {
                "provider_etag": _plain_string(raw.get("etag"), 1000),
                "api_resource_url": f"https://www.googleapis.com/books/v1/volumes/{quote(volume_id, safe='')}",
                "query_url_without_credentials": query["request_url_without_credentials"],
                "fetched_at": fetched_at,
                "response_sha256": response_sha256,
                "cache": dict(cache),
            },
            "attribution": {
                "text": "Powered by Google",
                "required_adjacent_to_displayed_api_results": True,
                "prominent_google_books_link_required": True,
                "branding_guidelines": BRANDING_GUIDELINES,
            },
            "rights": {
                "underlying_cover_rights": "not_established",
                "remote_reference_only": True,
                "binary_download_or_cache_allowed": False,
                "api_content_retain_until": cache["retain_until"],
                "removal_request_process_required_before_public_use": True,
            },
            "review_required": True,
            "public_eligible": False,
            "publication_effect": "none",
        }
        candidate["candidate_fingerprint"] = candidate_fingerprint(candidate)
        candidates.append(candidate)
    return candidates, dict(sorted(rejected.items()))


def empty_state(plan: Mapping[str, Any], *, created_at: Optional[str] = None) -> dict[str, Any]:
    moment = created_at or utc_now()
    return {
        "schema": STATE_SCHEMA,
        "created_at": moment,
        "updated_at": moment,
        "plan_fingerprint": plan["plan_fingerprint"],
        "plan_inputs": plan["inputs"],
        "entries": {},
        "policy": {
            "response_bodies_stored": False,
            "image_binaries_stored": False,
            "expired_api_content_removed": True,
        },
    }


def validate_state(state: Mapping[str, Any], plan: Mapping[str, Any]) -> None:
    if state.get("schema") != STATE_SCHEMA:
        raise SourceError(f"state must use {STATE_SCHEMA}")
    if state.get("plan_fingerprint") != plan.get("plan_fingerprint") or state.get("plan_inputs") != plan.get("inputs"):
        raise SourceError("discovery state is stale for the current plan")
    if not isinstance(state.get("entries"), Mapping):
        raise SourceError("discovery state entries must be an object")
    query_by_key = {query["query_key"]: query for query in plan["queries"]}
    for key, entry in state["entries"].items():
        if key not in query_by_key or not isinstance(entry, Mapping):
            raise SourceError(f"discovery state contains an unknown or malformed query entry: {key}")
        if entry.get("query_fingerprint") != query_by_key[key]["query_fingerprint"]:
            raise SourceError(f"discovery state has stale query evidence: {key}")


def prune_expired(state: MutableMapping[str, Any], *, now: Optional[str] = None) -> int:
    moment = parse_utc(now or utc_now())
    removed = 0
    entries = state.get("entries") if isinstance(state.get("entries"), MutableMapping) else {}
    for entry in entries.values():
        if not isinstance(entry, MutableMapping) or entry.get("status") not in {"exact_candidates", "no_exact_cover"}:
            continue
        cache = entry.get("cache") if isinstance(entry.get("cache"), Mapping) else {}
        retain_until = str(cache.get("retain_until") or "")
        if not retain_until or parse_utc(retain_until) <= moment:
            entry.pop("candidates", None)
            entry.pop("cache", None)
            entry.pop("response_sha256", None)
            entry.pop("rejected_results", None)
            entry["status"] = "expired"
            entry["expired_at"] = format_utc(moment)
            removed += 1
    if removed:
        state["updated_at"] = format_utc(moment)
    return removed


def pending_queries(
    plan: Mapping[str, Any],
    state: Mapping[str, Any],
    *,
    retry_blocked: bool = False,
) -> list[Mapping[str, Any]]:
    terminal = {"exact_candidates", "no_exact_cover", "permanent_error", "retention_blocked"}
    if retry_blocked:
        terminal -= {"permanent_error", "retention_blocked"}
    entries = state.get("entries") if isinstance(state.get("entries"), Mapping) else {}
    return [
        query for query in plan["queries"]
        if not isinstance(entries.get(query["query_key"]), Mapping)
        or entries[query["query_key"]].get("status") not in terminal
    ]


@dataclass(frozen=True)
class ApiResponse:
    payload: Mapping[str, Any]
    headers: Mapping[str, str]
    response_sha256: str
    received_bytes: int


class GoogleBooksClient:
    def __init__(self, api_key: str, *, timeout: float = 20.0) -> None:
        if not api_key.strip():
            raise SourceError("Google Books API key is required")
        self._api_key = api_key.strip()
        self.timeout = timeout

    def search(self, isbn: str) -> ApiResponse:
        url = build_query_url(isbn, self._api_key)
        request = Request(url, headers={
            "Accept": "application/json",
            "Accept-Encoding": "gzip",
            "User-Agent": USER_AGENT,
        })
        try:
            with urlopen(request, timeout=self.timeout) as response:
                raw = response.read(MAX_RESPONSE_BYTES + 1)
                if len(raw) > MAX_RESPONSE_BYTES:
                    raise ApiError("Google Books response exceeded the bounded byte limit", transient=False)
                headers = {key: value for key, value in response.headers.items()}
        except HTTPError as exc:
            status = int(exc.code or 0)
            transient = status == 429 or 500 <= status <= 599
            message = "Google Books request was rate-limited or temporarily unavailable" if transient else "Google Books request was rejected"
            raise ApiError(message, status=status, transient=transient) from exc
        except (URLError, TimeoutError, OSError) as exc:
            raise ApiError("Google Books request failed before a response was received", transient=True) from exc

        encoding = headers.get("Content-Encoding", headers.get("content-encoding", "")).lower()
        if encoding == "gzip":
            try:
                raw = gzip.decompress(raw)
            except OSError as exc:
                raise ApiError("Google Books returned invalid gzip content", transient=False) from exc
            if len(raw) > MAX_RESPONSE_BYTES:
                raise ApiError("decompressed Google Books response exceeded the bounded byte limit", transient=False)
        elif encoding not in {"", "identity"}:
            raise ApiError("Google Books returned an unsupported content encoding", transient=False)
        try:
            payload = json.loads(raw.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise ApiError("Google Books returned malformed JSON", transient=False) from exc
        if not isinstance(payload, Mapping):
            raise ApiError("Google Books response was not a JSON object", transient=False)
        return ApiResponse(payload, headers, bytes_checksum(raw), len(raw))


def run_discovery(
    plan: Mapping[str, Any],
    state: MutableMapping[str, Any],
    state_path: Path,
    client: Any,
    *,
    limit: int,
    min_interval: float,
    retry_blocked: bool = False,
    now_fn: Callable[[], str] = utc_now,
    monotonic_fn: Callable[[], float] = time.monotonic,
    sleep_fn: Callable[[float], None] = time.sleep,
) -> dict[str, Any]:
    if not 1 <= limit <= MAX_QUERIES_PER_RUN:
        raise SourceError(f"limit must be between 1 and {MAX_QUERIES_PER_RUN}")
    if min_interval < MIN_INTERVAL_SECONDS:
        raise SourceError(f"min-interval must be at least {MIN_INTERVAL_SECONDS:.1f} seconds")
    validate_state(state, plan)
    prune_expired(state, now=now_fn())
    selected = pending_queries(plan, state, retry_blocked=retry_blocked)[:limit]
    attempts = 0
    retained = 0
    blocked = 0
    errors = 0
    last_started: Optional[float] = None

    for query in selected:
        if last_started is not None:
            delay = min_interval - (monotonic_fn() - last_started)
            if delay > 0:
                sleep_fn(delay)
        last_started = monotonic_fn()
        attempted_at = now_fn()
        attempts += 1
        base_entry: dict[str, Any] = {
            "query_fingerprint": query["query_fingerprint"],
            "attempted_at": attempted_at,
        }
        stop_batch = False
        try:
            response = client.search(query["isbn"])
        except ApiError as exc:
            base_entry.update({
                "status": "transient_error" if exc.transient else "permanent_error",
                "http_status": exc.status,
                "diagnostic": str(exc),
                "api_content_retained": False,
            })
            errors += 1
            stop_batch = exc.transient or exc.status in {401, 403, 429}
        else:
            freshness = cache_policy(response.headers, attempted_at)
            if freshness is None:
                base_entry.update({
                    "status": "retention_blocked",
                    "diagnostic": "Response headers did not grant positive cache freshness; no API result content or remote reference was retained.",
                    "api_content_retained": False,
                    "received_bytes": response.received_bytes,
                })
                blocked += 1
            else:
                candidates, rejected = extract_exact_candidates(
                    query,
                    response.payload,
                    fetched_at=attempted_at,
                    response_sha256=response.response_sha256,
                    cache=freshness,
                )
                base_entry.update({
                    "status": "exact_candidates" if candidates else "no_exact_cover",
                    "api_content_retained": True,
                    "response_sha256": response.response_sha256,
                    "received_bytes": response.received_bytes,
                    "cache": freshness,
                    "candidates": candidates,
                    "rejected_results": rejected,
                })
                retained += 1
        state["entries"][query["query_key"]] = base_entry
        state["updated_at"] = now_fn()
        write_json(state_path, state)
        if stop_batch:
            break

    remaining = len(pending_queries(plan, state, retry_blocked=retry_blocked))
    return {
        "selected": len(selected),
        "attempted": attempts,
        "retained_with_positive_freshness": retained,
        "retention_blocked": blocked,
        "errors": errors,
        "remaining": remaining,
        "stopped_early": attempts < len(selected),
    }


def review_adapter_contract() -> dict[str, Any]:
    return {
        "current_review_ui_compatibility": "requires_provider_neutral_cover_queue_v2_adapter",
        "reason": "docs/js/review.js validates shelfsignals-cover-review-queue@1 as Open-Library-specific, including edition and Cover IDs, URLs, and fingerprints.",
        "required_changes": [
            "Add this queue schema to validateImportedQueue without weakening the existing Open Library validator.",
            "Add a google_books provider validator that recomputes this candidate_fingerprint and requires exact canonical ISBN intersection.",
            "Keep candidate URLs text-only under the existing img-src 'none' and connect-src 'none' review-page CSP.",
            "Render an adjacent official Powered by Google attribution and a prominent source_url for every displayed provider result; preserve provider_result_position.",
            "Carry provider, queue schema, queue fingerprint, cache retain-until, exact-edition confirmation, visual check, reviewer, review time, and evidence note into a provider-neutral private ledger.",
            "Reject export after the queue or candidate api_content_retain_until time; rediscover/revalidate instead.",
            "Create a separate publisher adapter only after editorial/legal approval; it must revalidate the live provider reference and branding/removal obligations. Do not pass this schema to build_cover_index.py today.",
        ],
        "publication_adapter_available": False,
        "publication_effect": "none",
    }


def build_review_queue(
    plan: Mapping[str, Any],
    state: MutableMapping[str, Any],
    *,
    generated_at: Optional[str] = None,
) -> dict[str, Any]:
    moment = generated_at or utc_now()
    validate_state(state, plan)
    prune_expired(state, now=moment)
    items: dict[str, dict[str, Any]] = {}
    retain_until_values: list[str] = []
    seen_candidate_keys: set[str] = set()
    for query in plan["queries"]:
        entry = state["entries"].get(query["query_key"])
        if not isinstance(entry, Mapping) or entry.get("status") != "exact_candidates":
            continue
        candidates = entry.get("candidates") if isinstance(entry.get("candidates"), list) else []
        entry_cache = entry.get("cache") if isinstance(entry.get("cache"), Mapping) else {}
        if not candidates:
            continue
        item = items.setdefault(query["catalog_id"], {"catalog": query["catalog"], "candidates": []})
        for candidate in candidates:
            if isinstance(candidate, Mapping):
                validate_stored_candidate(candidate, query)
                candidate_cache = candidate.get("source_metadata", {}).get("cache", {})
                if candidate_cache != entry_cache:
                    raise SourceError(f"candidate cache evidence differs from its discovery entry: {candidate['candidate_key']}")
                key = str(candidate["candidate_key"])
                if key in seen_candidate_keys:
                    raise SourceError(f"private state contains duplicate candidate key: {key}")
                seen_candidate_keys.add(key)
                item["candidates"].append(dict(candidate))
                retain_until = str(candidate.get("rights", {}).get("api_content_retain_until") or "")
                if retain_until:
                    retain_until_values.append(retain_until)
    count = sum(len(item["candidates"]) for item in items.values())
    queue = {
        "schema": QUEUE_SCHEMA,
        "generated_at": moment,
        "valid_until": min(retain_until_values) if retain_until_values else None,
        "inputs": {
            **plan["inputs"],
            "plan_fingerprint": plan["plan_fingerprint"],
            "state_updated_at": state["updated_at"],
        },
        "provider": provider_contract(),
        "policy": policy_contract(),
        "attribution": {
            "text": "Powered by Google",
            "branding_guidelines": BRANDING_GUIDELINES,
            "not_rendered_by_this_json_generator": True,
        },
        "review_adapter": review_adapter_contract(),
        "items": items,
        "summary": {
            "catalog_records": len(items),
            "candidate_references": count,
            "all_matches_are_exact_provider_isbn": True,
            "image_binaries_included": False,
            "public_eligible_candidates": 0,
            "publication_effect": "none",
        },
    }
    queue["queue_fingerprint"] = canonical_checksum({
        "inputs": queue["inputs"],
        "candidate_fingerprints": [
            candidate["candidate_fingerprint"]
            for item in items.values()
            for candidate in item["candidates"]
        ],
        "valid_until": queue["valid_until"],
    })
    return queue


def state_status(plan: Mapping[str, Any], state: MutableMapping[str, Any], *, now: Optional[str] = None) -> dict[str, Any]:
    moment = now or utc_now()
    validate_state(state, plan)
    expired = prune_expired(state, now=moment)
    counts = Counter(
        str(entry.get("status") or "unknown")
        for entry in state["entries"].values()
        if isinstance(entry, Mapping)
    )
    candidates = sum(
        len(entry.get("candidates") or [])
        for entry in state["entries"].values()
        if isinstance(entry, Mapping) and entry.get("status") == "exact_candidates"
    )
    return {
        "as_of": moment,
        "plan_queries": len(plan["queries"]),
        "query_states": dict(sorted(counts.items())),
        "current_exact_cover_candidates": candidates,
        "expired_entries_purged": expired,
        "pending_or_retryable": len(pending_queries(plan, state)),
        "policy": policy_contract(),
    }


def _load_plan_and_catalog(args: argparse.Namespace) -> tuple[dict[str, Any], list[Mapping[str, Any]]]:
    catalog_path = Path(args.catalog)
    records = load_catalog(catalog_path)
    plan = read_json(Path(args.plan))
    if not isinstance(plan, Mapping):
        raise SourceError("plan must be a JSON object")
    validate_plan(plan, records, catalog_path)
    return dict(plan), records


def command_audit(args: argparse.Namespace) -> None:
    catalog_path = Path(args.catalog)
    records = load_catalog(catalog_path)
    plan = build_plan(records, catalog_path)
    print(json.dumps({"inputs": plan["inputs"], "summary": plan["summary"], "policy": plan["policy"]}, indent=2))


def command_plan(args: argparse.Namespace) -> None:
    catalog_path = Path(args.catalog)
    records = load_catalog(catalog_path)
    plan = build_plan(records, catalog_path)
    write_json(Path(args.output), plan)
    print(json.dumps({"output": str(args.output), **plan["summary"]}, indent=2))


def command_discover(args: argparse.Namespace) -> None:
    plan, _records = _load_plan_and_catalog(args)
    state_path = Path(args.state)
    if state_path.exists():
        raw_state = read_json(state_path)
        if not isinstance(raw_state, MutableMapping):
            raise SourceError("state must be a JSON object")
        state: MutableMapping[str, Any] = raw_state
    else:
        state = empty_state(plan)
        write_json(state_path, state)
    api_key = os.environ.get(args.api_key_env, "").strip()
    if not api_key:
        raise SourceError(
            f"set {args.api_key_env} in the environment; API keys are never accepted on the command line or written to output"
        )
    client = GoogleBooksClient(api_key, timeout=args.timeout)
    report = run_discovery(
        plan,
        state,
        state_path,
        client,
        limit=args.limit,
        min_interval=args.min_interval,
        retry_blocked=args.retry_blocked,
    )
    queue = build_review_queue(plan, state)
    write_json(Path(args.queue), queue)
    report["private_queue"] = str(args.queue)
    report["queue_candidates"] = queue["summary"]["candidate_references"]
    report["queue_valid_until"] = queue["valid_until"]
    print(json.dumps(report, indent=2))


def command_queue(args: argparse.Namespace) -> None:
    plan, _records = _load_plan_and_catalog(args)
    raw_state = read_json(Path(args.state))
    if not isinstance(raw_state, MutableMapping):
        raise SourceError("state must be a JSON object")
    queue = build_review_queue(plan, raw_state)
    write_json(Path(args.state), raw_state)
    write_json(Path(args.output), queue)
    print(json.dumps({"output": str(args.output), **queue["summary"], "valid_until": queue["valid_until"]}, indent=2))


def command_status(args: argparse.Namespace) -> None:
    plan, _records = _load_plan_and_catalog(args)
    state_path = Path(args.state)
    if state_path.exists():
        raw_state = read_json(state_path)
        if not isinstance(raw_state, MutableMapping):
            raise SourceError("state must be a JSON object")
        state: MutableMapping[str, Any] = raw_state
    else:
        state = empty_state(plan)
    report = state_status(plan, state)
    if state_path.exists() and report["expired_entries_purged"]:
        write_json(state_path, state)
    print(json.dumps(report, indent=2))


def command_purge(args: argparse.Namespace) -> None:
    plan, _records = _load_plan_and_catalog(args)
    state_path = Path(args.state)
    raw_state = read_json(state_path)
    if not isinstance(raw_state, MutableMapping):
        raise SourceError("state must be a JSON object")
    validate_state(raw_state, plan)
    removed = prune_expired(raw_state)
    write_json(state_path, raw_state)
    queue = build_review_queue(plan, raw_state)
    write_json(Path(args.queue), queue)
    print(json.dumps({"expired_entries_purged": removed, "remaining_candidates": queue["summary"]["candidate_references"]}, indent=2))


def command_self_test(_args: argparse.Namespace) -> None:
    assert canonical_isbn("1-84749-006-9") == "9781847490063"
    assert canonical_isbn("9781847490063") == "9781847490063"
    assert canonical_isbn("9781847490064") == ""
    headers = {"Cache-Control": "private, max-age=3600"}
    policy = cache_policy(headers, "2026-07-14T00:00:00Z")
    assert policy and policy["retain_until"] == "2026-07-14T01:00:00Z"
    assert cache_policy({"Cache-Control": "no-store"}, "2026-07-14T00:00:00Z") is None
    assert "key=" not in build_query_url("9781847490063")
    print("google_books_cover_source self-test: ok (no network)")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    audit = subparsers.add_parser("audit", help="report exact-ISBN query scope without writing or using network")
    audit.add_argument("--catalog", default=DEFAULT_CATALOG)
    audit.set_defaults(func=command_audit)

    plan = subparsers.add_parser("plan", help="write a deterministic private exact-ISBN query plan")
    plan.add_argument("--catalog", default=DEFAULT_CATALOG)
    plan.add_argument("--output", default=DEFAULT_PLAN)
    plan.set_defaults(func=command_plan)

    discover = subparsers.add_parser("discover", help="run a bounded, resumable private API discovery batch")
    discover.add_argument("--catalog", default=DEFAULT_CATALOG)
    discover.add_argument("--plan", default=DEFAULT_PLAN)
    discover.add_argument("--state", default=DEFAULT_STATE)
    discover.add_argument("--queue", default=DEFAULT_QUEUE)
    discover.add_argument("--limit", type=int, default=DEFAULT_QUERY_LIMIT)
    discover.add_argument("--min-interval", type=float, default=DEFAULT_INTERVAL_SECONDS)
    discover.add_argument("--timeout", type=float, default=20.0)
    discover.add_argument("--api-key-env", default=DEFAULT_API_KEY_ENV)
    discover.add_argument("--retry-blocked", action="store_true", help="retry retention-blocked and permanent-error entries")
    discover.set_defaults(func=command_discover)

    queue = subparsers.add_parser("queue", help="rebuild the private queue from unexpired discovery state")
    queue.add_argument("--catalog", default=DEFAULT_CATALOG)
    queue.add_argument("--plan", default=DEFAULT_PLAN)
    queue.add_argument("--state", default=DEFAULT_STATE)
    queue.add_argument("--output", default=DEFAULT_QUEUE)
    queue.set_defaults(func=command_queue)

    status = subparsers.add_parser("status", help="report private progress without network or publication")
    status.add_argument("--catalog", default=DEFAULT_CATALOG)
    status.add_argument("--plan", default=DEFAULT_PLAN)
    status.add_argument("--state", default=DEFAULT_STATE)
    status.set_defaults(func=command_status)

    purge = subparsers.add_parser("purge", help="remove expired API content and rebuild the private queue")
    purge.add_argument("--catalog", default=DEFAULT_CATALOG)
    purge.add_argument("--plan", default=DEFAULT_PLAN)
    purge.add_argument("--state", default=DEFAULT_STATE)
    purge.add_argument("--queue", default=DEFAULT_QUEUE)
    purge.set_defaults(func=command_purge)

    self_test = subparsers.add_parser("self-test", help="run deterministic checks without network")
    self_test.set_defaults(func=command_self_test)
    return parser


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except (SourceError, OSError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
