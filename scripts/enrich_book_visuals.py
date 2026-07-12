#!/usr/bin/env python3
"""Build a metadata-only book-cover manifest from exact catalog identifiers.

The script intentionally uses provider APIs rather than scraping pages.  It never
writes image binaries: validated HTTPS image URLs and their provenance are the
only visual data placed in the manifest.

Examples::

    python scripts/enrich_book_visuals.py --dry-run --limit 10
    python scripts/enrich_book_visuals.py --provider none --dry-run --limit 1
    python scripts/enrich_book_visuals.py --self-test
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import struct
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen


MANIFEST_SCHEMA = "shelfsignals-book-visuals@1"
MANIFEST_VERSION = "1.1.0"
CACHE_SCHEMA = "shelfsignals-book-visual-cache@1"
OPEN_LIBRARY_API = "https://openlibrary.org/api/books"
OPEN_LIBRARY_COVERS = "https://covers.openlibrary.org/b"
USER_AGENT = "ShelfSignals-book-visual-enricher/1.1 (+https://github.com/gitbrainlab/ShelfSignals)"
DEFAULT_INPUT = Path("docs/data/sekula_index.json")
DEFAULT_OUTPUT = Path("docs/data/book_visuals.json")
DEFAULT_CACHE = Path(".cache/book_visuals-openlibrary.json")
MAX_JSON_BYTES = 2 * 1024 * 1024
MAX_IMAGE_PROBE_BYTES = 128 * 1024
MIN_IMAGE_EDGE = 40
PLACEHOLDER_TOKENS = ("placeholder", "no-cover", "nocover", "missing-cover", "default-image")


class EnrichmentError(RuntimeError):
    """A safe, user-facing enrichment failure."""


def utc_now() -> str:
    """Return a UTC timestamp; SOURCE_DATE_EPOCH makes generated files reproducible."""

    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    moment = datetime.fromtimestamp(int(epoch), timezone.utc) if epoch else datetime.now(timezone.utc)
    return moment.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical_checksum(value: Any) -> str:
    """Return a stable SHA-256 checksum for a JSON-compatible value."""

    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _isbn_checksum_valid(compact: str) -> bool:
    if len(compact) == 10 and re.fullmatch(r"\d{9}[\dX]", compact):
        total = sum((10 - index) * (10 if char == "X" else int(char)) for index, char in enumerate(compact))
        return total % 11 == 0
    if len(compact) == 13 and compact.isdigit():
        total = sum(int(char) * (1 if index % 2 == 0 else 3) for index, char in enumerate(compact))
        return total % 10 == 0
    return False


def normalize_isbn(value: Any) -> str:
    """Normalize an ISBN only when its ISBN-10/13 checksum is valid."""

    compact = re.sub(r"[^0-9X]", "", str(value or "").upper())
    return compact if _isbn_checksum_valid(compact) else ""


def normalize_oclc(value: Any) -> str:
    """Normalize an OCLC control number, removing common MARC prefixes/zeros."""

    text = str(value or "").strip()
    match = re.search(
        r"(?i)(?:\(\s*(?:oclc|ocolc)\s*\)|\b(?:oclc|ocolc|ocm|ocn|on))\s*0*(\d{1,12})(?!\d)",
        text,
    )
    if not match:
        match = re.fullmatch(r"\s*0*(\d{1,12})\s*", text)
    if not match:
        return ""
    # OCLC numbers are control numbers, not check-digit identifiers.  The
    # identifier-set checksum below protects their normalized representation.
    return match.group(1) or "0"


def normalize_lccn(value: Any) -> str:
    """Normalize an LCCN using the Library of Congress zero-padding convention."""

    text = re.sub(r"(?i)^\s*lccn\s*[:#]?\s*", "", str(value or ""))
    text = text.split("/", 1)[0].strip().lower()
    match = re.fullmatch(r"([a-z]{0,3})\s*(\d{2}|\d{4})\s*-?\s*(\d{1,6})", text)
    if not match:
        # Already-normalized values have no separator, so split eight-digit
        # pre-2001 numbers after two digits and ten-digit numbers after four.
        compact = re.sub(r"[^a-z0-9]", "", text)
        compact_match = re.fullmatch(r"([a-z]{0,3})(\d{7,10})", compact)
        if not compact_match:
            return ""
        prefix, digits = compact_match.groups()
        year_length = 4 if len(digits) > 8 else 2
        year, serial = digits[:year_length], digits[year_length:]
    else:
        prefix, year, serial = match.groups()
    if len(serial) > 6:
        return ""
    return f"{prefix}{year}{serial.zfill(6)}"


def _normalized_values(values: Any, normalizer: Any) -> List[str]:
    source = values if isinstance(values, list) else ([] if values in (None, "") else [values])
    return sorted({normalized for value in source if (normalized := normalizer(value))})


def normalized_identifiers(record: Mapping[str, Any]) -> Dict[str, List[str]]:
    """Extract sorted, validated exact identifiers from a canonical record."""

    return {
        "isbn": _normalized_values(record.get("isbns"), normalize_isbn),
        "oclc": _normalized_values(record.get("oclc_numbers"), normalize_oclc),
        "lccn": _normalized_values(record.get("lccn"), normalize_lccn),
    }


def identifier_checksum(identifiers: Mapping[str, Sequence[str]]) -> str:
    """Checksum the normalized ISBN/OCLC/LCCN set used for resolution."""

    canonical = {kind: sorted(set(identifiers.get(kind, []))) for kind in ("isbn", "oclc", "lccn")}
    return canonical_checksum(canonical)


def iter_identifier_queries(identifiers: Mapping[str, Sequence[str]]) -> Iterable[Tuple[str, str]]:
    """Yield exact identifiers in deterministic, most-specific-first order."""

    for kind in ("isbn", "oclc", "lccn"):
        for value in sorted(set(identifiers.get(kind, []))):
            yield kind, value


def _image_dimensions(data: bytes) -> Optional[Tuple[int, int]]:
    """Read common image dimensions from a bounded in-memory response prefix."""

    if len(data) >= 24 and data.startswith(b"\x89PNG\r\n\x1a\n"):
        return struct.unpack(">II", data[16:24])
    if len(data) >= 10 and data[:6] in (b"GIF87a", b"GIF89a"):
        return struct.unpack("<HH", data[6:10])
    if len(data) >= 30 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        if data[12:16] == b"VP8X":
            return (1 + int.from_bytes(data[24:27], "little"), 1 + int.from_bytes(data[27:30], "little"))
    if len(data) >= 4 and data.startswith(b"\xff\xd8"):
        offset = 2
        start_of_frame = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
        while offset + 4 <= len(data):
            while offset < len(data) and data[offset] != 0xFF:
                offset += 1
            while offset < len(data) and data[offset] == 0xFF:
                offset += 1
            if offset >= len(data):
                break
            marker = data[offset]
            offset += 1
            if marker in (0xD8, 0xD9) or 0xD0 <= marker <= 0xD7:
                continue
            if offset + 2 > len(data):
                break
            segment_length = int.from_bytes(data[offset:offset + 2], "big")
            if segment_length < 2 or offset + segment_length > len(data):
                break
            if marker in start_of_frame and segment_length >= 7:
                height = int.from_bytes(data[offset + 3:offset + 5], "big")
                width = int.from_bytes(data[offset + 5:offset + 7], "big")
                return width, height
            offset += segment_length
    return None


@dataclass
class RateLimitedHttpClient:
    """Small stdlib HTTP client with deterministic pacing and bounded reads."""

    min_interval: float = 0.35
    timeout: float = 15.0
    _last_request: float = 0.0

    def _pace(self) -> None:
        remaining = self.min_interval - (time.monotonic() - self._last_request)
        if remaining > 0:
            time.sleep(remaining)
        self._last_request = time.monotonic()

    def _open(self, request: Request) -> Any:
        self._pace()
        return urlopen(request, timeout=self.timeout)

    def get_json(self, url: str) -> Mapping[str, Any]:
        if urlparse(url).scheme != "https":
            raise EnrichmentError("provider URL is not HTTPS")
        request = Request(url, headers={"Accept": "application/json", "User-Agent": USER_AGENT})
        with self._open(request) as response:
            if urlparse(response.geturl()).scheme != "https":
                raise EnrichmentError("provider redirected to a non-HTTPS URL")
            content_type = response.headers.get_content_type().lower()
            if content_type not in ("application/json", "text/json"):
                raise EnrichmentError(f"provider returned non-JSON content type {content_type!r}")
            data = response.read(MAX_JSON_BYTES + 1)
        if len(data) > MAX_JSON_BYTES:
            raise EnrichmentError("provider JSON response exceeded size limit")
        try:
            payload = json.loads(data.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise EnrichmentError("provider returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise EnrichmentError("provider JSON response was not an object")
        return payload

    def validate_image(self, url: str) -> Mapping[str, Any]:
        parsed = urlparse(url)
        lowered_url = url.lower()
        if parsed.scheme != "https" or parsed.hostname != "covers.openlibrary.org":
            raise EnrichmentError("cover URL is not an approved Open Library HTTPS URL")
        if any(token in lowered_url for token in PLACEHOLDER_TOKENS):
            raise EnrichmentError("cover URL resembles a placeholder")
        request = Request(
            url,
            headers={
                "Accept": "image/avif,image/webp,image/png,image/jpeg,image/gif",
                "Range": f"bytes=0-{MAX_IMAGE_PROBE_BYTES - 1}",
                "User-Agent": USER_AGENT,
            },
        )
        with self._open(request) as response:
            final_url = response.geturl()
            content_type = response.headers.get_content_type().lower()
            data = response.read(MAX_IMAGE_PROBE_BYTES)
        if urlparse(final_url).scheme != "https":
            raise EnrichmentError("cover redirected to a non-HTTPS URL")
        if not content_type.startswith("image/"):
            raise EnrichmentError(f"cover returned non-image content type {content_type!r}")
        dimensions = _image_dimensions(data)
        if not dimensions:
            raise EnrichmentError("cover image dimensions could not be validated")
        width, height = dimensions
        if width < MIN_IMAGE_EDGE or height < MIN_IMAGE_EDGE:
            raise EnrichmentError("cover image is too small and may be a placeholder")
        ratio = width / height
        if not 0.2 <= ratio <= 2.5:
            raise EnrichmentError("cover image has an implausible aspect ratio")
        return {
            "method": "bounded_get",
            "content_type": content_type,
            "width": width,
            "height": height,
            "aspect_ratio": round(ratio, 4),
        }


def _open_library_bibkey(kind: str, value: str) -> str:
    return f"{kind.upper()}:{value}"


def _cover_urls(kind: str, value: str) -> Tuple[str, str]:
    safe_kind = {"isbn": "isbn", "oclc": "oclc", "lccn": "lccn"}[kind]
    base = f"{OPEN_LIBRARY_COVERS}/{safe_kind}/{value}"
    return f"{base}-L.jpg?default=false", f"{base}-M.jpg?default=false"


def _candidate_key(candidate: Mapping[str, Any]) -> str:
    key = str(candidate.get("key") or "").strip()
    if re.fullmatch(r"/books/OL\d+M", key):
        return key
    source_url = str(candidate.get("url") or "").strip()
    parsed = urlparse(source_url)
    match = re.match(r"^(/books/OL\d+M)(?:/|$)", parsed.path) if parsed.hostname == "openlibrary.org" else None
    return match.group(1) if match else ""


def resolve_open_library_identifier(
    kind: str,
    value: str,
    client: RateLimitedHttpClient,
    checked_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Resolve one exact identifier with the Open Library Books and Covers APIs."""

    checked_at = checked_at or utc_now()
    bibkey = _open_library_bibkey(kind, value)
    query_url = OPEN_LIBRARY_API + "?" + urlencode({"bibkeys": bibkey, "format": "json", "jscmd": "data"})
    try:
        payload = client.get_json(query_url)
        candidates = [(key, candidate) for key, candidate in payload.items() if key == bibkey and isinstance(candidate, dict)]
        if not candidates:
            return {"status": "negative", "reason": "identifier_not_found", "checked_at": checked_at}
        if len(candidates) != 1:
            return {"status": "ambiguous", "reason": "multiple_exact_candidates", "checked_at": checked_at}
        _, candidate = candidates[0]
        candidate_key = _candidate_key(candidate)
        if not candidate_key:
            return {"status": "error", "reason": "candidate_missing_stable_edition_key", "checked_at": checked_at}
        # Requiring cover metadata prevents the Covers API from being treated as
        # an existence probe and keeps negative/default images out of the manifest.
        if not isinstance(candidate.get("cover"), dict):
            return {"status": "negative", "reason": "candidate_has_no_cover", "checked_at": checked_at}
        image_url, thumbnail_url = _cover_urls(kind, value)
        image_validation = dict(client.validate_image(image_url))
        return {
            "status": "positive",
            "checked_at": checked_at,
            "candidate_key": candidate_key,
            "source_url": "https://openlibrary.org" + candidate_key,
            "image_url": image_url,
            "thumbnail_url": thumbnail_url,
            "image_validation": image_validation,
        }
    except HTTPError as exc:
        if exc.code == 404:
            return {"status": "negative", "reason": "cover_or_identifier_not_found", "checked_at": checked_at}
        return {"status": "error", "reason": f"http_{exc.code}", "checked_at": checked_at}
    except (URLError, TimeoutError, EnrichmentError, OSError) as exc:
        return {"status": "error", "reason": type(exc).__name__, "checked_at": checked_at}


def empty_cache(provider: str) -> Dict[str, Any]:
    return {"schema": CACHE_SCHEMA, "provider": provider, "entries": {}}


def load_cache(path: Path, provider: str) -> Dict[str, Any]:
    if not path.exists():
        return empty_cache(provider)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EnrichmentError(f"could not read cache {path}: {exc}") from exc
    if payload.get("schema") != CACHE_SCHEMA or payload.get("provider") != provider:
        raise EnrichmentError(f"cache {path} has an incompatible schema or provider")
    if not isinstance(payload.get("entries"), dict):
        raise EnrichmentError(f"cache {path} has invalid entries")
    return payload


def _query_cache_key(kind: str, value: str) -> str:
    return f"{kind.upper()}:{value}"


def resolve_record(
    record: Mapping[str, Any],
    provider: str,
    cache: MutableMapping[str, Any],
    client: RateLimitedHttpClient,
    force: bool = False,
    checked_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Resolve a record conservatively, rejecting conflicting exact matches."""

    checked_at = checked_at or utc_now()
    identifiers = normalized_identifiers(record)
    checksum = identifier_checksum(identifiers)
    provenance: Dict[str, Any] = {
        "provider": provider,
        "match_policy": "exact_normalized_identifier_only",
        "normalized_identifiers": identifiers,
        "identifier_checksum": checksum,
    }
    queries = list(iter_identifier_queries(identifiers))
    if not queries:
        return {
            "status": "negative",
            "reason": "no_valid_exact_identifier",
            "checked_at": checked_at,
            "provenance": provenance,
        }
    if provider == "none":
        return {
            "status": "negative",
            "reason": "provider_disabled",
            "checked_at": checked_at,
            "provenance": provenance,
        }

    entries = cache.setdefault("entries", {})
    outcomes: List[Tuple[str, str, Mapping[str, Any]]] = []
    for kind, value in queries:
        cache_key = _query_cache_key(kind, value)
        outcome = None if force else entries.get(cache_key)
        if not isinstance(outcome, dict):
            outcome = resolve_open_library_identifier(kind, value, client, checked_at=checked_at)
            entries[cache_key] = outcome
        outcomes.append((kind, value, outcome))

    positives = [(kind, value, outcome) for kind, value, outcome in outcomes if outcome.get("status") == "positive"]
    errors = [(kind, value, outcome) for kind, value, outcome in outcomes if outcome.get("status") == "error"]
    ambiguities = [(kind, value, outcome) for kind, value, outcome in outcomes if outcome.get("status") == "ambiguous"]
    candidates: Dict[str, List[Tuple[str, str, Mapping[str, Any]]]] = {}
    for positive in positives:
        candidates.setdefault(str(positive[2].get("candidate_key")), []).append(positive)

    provenance["queries"] = [
        {"type": kind, "value": value, "status": str(outcome.get("status", "error"))}
        for kind, value, outcome in outcomes
    ]
    if ambiguities or len(candidates) > 1:
        provenance["candidate_keys"] = sorted(key for key in candidates if key)
        return {
            "status": "ambiguous",
            "reason": "conflicting_exact_identifier_matches",
            "checked_at": checked_at,
            "provenance": provenance,
        }
    if errors:
        return {
            "status": "error",
            "reason": "one_or_more_provider_queries_failed",
            "checked_at": checked_at,
            "provenance": provenance,
        }
    if not positives:
        return {
            "status": "negative",
            "reason": "no_exact_identifier_with_valid_cover",
            "checked_at": checked_at,
            "provenance": provenance,
        }

    kind, value, outcome = positives[0]
    matching = [{"type": item_kind, "value": item_value} for item_kind, item_value, _ in positives]
    provenance.update(
        {
            "matched_identifiers": matching,
            "candidate_key": outcome["candidate_key"],
            "image_validation": outcome["image_validation"],
        }
    )
    return {
        # `resolved` is retained for the current JS manifest parser.  The
        # provider-neutral outcome vocabulary is explicit in `lookup_status`.
        "status": "resolved",
        "lookup_status": "positive",
        "image_url": outcome["image_url"],
        "thumbnail_url": outcome["thumbnail_url"],
        "source": "openlibrary",
        "source_id": value,
        "source_url": outcome["source_url"],
        "match_method": f"{kind}_exact",
        "match_confidence": 1.0,
        "attribution": "Cover reference served by Open Library Covers API",
        "checked_at": outcome["checked_at"],
        "aspect_ratio": outcome["image_validation"]["aspect_ratio"],
        "provenance": provenance,
    }


def _manifest_status(item: Mapping[str, Any]) -> str:
    if item.get("status") == "resolved":
        return "positive"
    status = str(item.get("lookup_status") or item.get("status") or "error")
    return status if status in {"positive", "negative", "ambiguous", "error"} else "error"


def manifest_summary(items: Mapping[str, Mapping[str, Any]]) -> Dict[str, int]:
    counts = {status: 0 for status in ("positive", "negative", "ambiguous", "error")}
    for item in items.values():
        counts[_manifest_status(item)] += 1
    return {
        "checked": len(items),
        "resolved": counts["positive"],
        "rejected": counts["negative"] + counts["ambiguous"] + counts["error"],
        "ambiguous": counts["ambiguous"],
        **counts,
    }


def load_records(path: Path) -> List[Mapping[str, Any]]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EnrichmentError(f"could not read canonical input {path}: {exc}") from exc
    if not isinstance(payload, list):
        raise EnrichmentError("canonical input must be a JSON array")
    records: List[Mapping[str, Any]] = []
    seen = set()
    for index, record in enumerate(payload):
        if not isinstance(record, dict):
            raise EnrichmentError(f"canonical record {index} is not an object")
        record_id = str(record.get("id") or "").strip()
        if not record_id:
            raise EnrichmentError(f"canonical record {index} has no id")
        if record_id in seen:
            raise EnrichmentError(f"canonical input contains duplicate id {record_id!r}")
        seen.add(record_id)
        records.append(record)
    return records


def load_existing_items(path: Path) -> Dict[str, Mapping[str, Any]]:
    if not path.exists():
        return {}
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EnrichmentError(f"could not read existing output {path}: {exc}") from exc
    if payload.get("schema") != MANIFEST_SCHEMA or not isinstance(payload.get("items"), dict):
        raise EnrichmentError(f"existing output {path} is not a {MANIFEST_SCHEMA} manifest")
    return dict(payload["items"])


def write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    temporary.replace(path)


def build_manifest(
    records: Sequence[Mapping[str, Any]],
    input_path: Path,
    existing_items: Mapping[str, Mapping[str, Any]],
    provider: str,
    cache: MutableMapping[str, Any],
    client: RateLimitedHttpClient,
    limit: Optional[int] = None,
    force: bool = False,
    generated_at: Optional[str] = None,
) -> Dict[str, Any]:
    generated_at = generated_at or utc_now()
    canonical_ids = {str(record["id"]) for record in records}
    items: Dict[str, Mapping[str, Any]] = {
        record_id: item for record_id, item in existing_items.items() if record_id in canonical_ids
    }
    selected = list(records[:limit] if limit is not None else records)
    for record in selected:
        record_id = str(record["id"])
        identifiers = normalized_identifiers(record)
        checksum = identifier_checksum(identifiers)
        previous = items.get(record_id, {})
        previous_provenance = previous.get("provenance", {}) if isinstance(previous, dict) else {}
        can_reuse = (
            not force
            and isinstance(previous_provenance, dict)
            and previous_provenance.get("identifier_checksum") == checksum
            and previous_provenance.get("provider") == provider
        )
        if not can_reuse:
            item = resolve_record(record, provider, cache, client, force=force, checked_at=generated_at)
            if item.get("status") != "resolved":
                item["lookup_status"] = item["status"]
                item["source"] = provider
                item["match_method"] = "none"
                item["match_confidence"] = 0.0
            items[record_id] = item

    sorted_items = {key: items[key] for key in sorted(items)}
    input_bytes = input_path.read_bytes()
    return {
        "schema": MANIFEST_SCHEMA,
        "version": MANIFEST_VERSION,
        "generated_at": generated_at,
        "input": input_path.name,
        "provider_policy": (
            "Exact normalized ISBN, OCLC, or LCCN API resolution only; conflicts and placeholders are rejected, "
            "and no image binaries are redistributed."
        ),
        "provenance": {
            "generator": "scripts/enrich_book_visuals.py",
            "provider": provider,
            "provider_endpoint": OPEN_LIBRARY_API if provider == "openlibrary" else None,
            "input_sha256": "sha256:" + hashlib.sha256(input_bytes).hexdigest(),
            "cache_schema": CACHE_SCHEMA,
        },
        "summary": manifest_summary(sorted_items),
        "items": sorted_items,
    }


def run_self_test() -> None:
    assert normalize_isbn("0-374-22626-1") == "0374226261"
    assert normalize_isbn("978-0-374-22626-8") == "9780374226268"
    assert normalize_isbn("978-0-374-22626-2") == ""
    assert normalize_oclc("(OCoLC)006103237") == "6103237"
    assert normalize_oclc("(cstrlin)maca(ocolc)6686356") == "6686356"
    assert normalize_oclc("not-an-oclc") == ""
    assert normalize_lccn("ca 07004418") == "ca07004418"
    assert normalize_lccn("sc77292") == "sc77000292"
    assert normalize_lccn("78005062 /sn") == "78005062"
    identifiers = {"isbn": ["0374226261"], "oclc": ["6103237"], "lccn": []}
    assert identifier_checksum(identifiers) == identifier_checksum(dict(reversed(list(identifiers.items()))))
    assert _image_dimensions(b"GIF89a" + struct.pack("<HH", 320, 480)) == (320, 480)
    summary = manifest_summary({"a": {"status": "resolved"}, "b": {"status": "negative"}})
    assert summary["positive"] == 1 and summary["negative"] == 1 and summary["rejected"] == 1


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT, help="canonical ShelfSignals JSON array")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT, help="versioned visual manifest JSON")
    parser.add_argument("--cache", type=Path, default=DEFAULT_CACHE, help="persistent metadata-only provider cache")
    parser.add_argument("--provider", choices=("openlibrary", "none"), default="openlibrary")
    parser.add_argument("--limit", type=int, help="process only the first N canonical records")
    parser.add_argument("--force", action="store_true", help="bypass prior output and cached provider responses")
    parser.add_argument("--dry-run", action="store_true", help="resolve and report without writing output or cache")
    parser.add_argument("--self-test", action="store_true", help="run pure normalization/schema checks and exit")
    args = parser.parse_args(argv)
    if args.limit is not None and args.limit < 1:
        parser.error("--limit must be at least 1")
    return args


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    if args.self_test:
        run_self_test()
        print("self-test: ok")
        return 0
    try:
        records = load_records(args.input)
        existing_items = load_existing_items(args.output)
        cache = load_cache(args.cache, args.provider)
        manifest = build_manifest(
            records=records,
            input_path=args.input,
            existing_items=existing_items,
            provider=args.provider,
            cache=cache,
            client=RateLimitedHttpClient(),
            limit=args.limit,
            force=args.force,
        )
        summary = manifest["summary"]
        mode = "dry-run" if args.dry_run else "write"
        print(
            f"{mode}: checked={summary['checked']} positive={summary['positive']} "
            f"negative={summary['negative']} ambiguous={summary['ambiguous']} error={summary['error']}"
        )
        if args.dry_run:
            return 0
        write_json(args.output, manifest)
        write_json(args.cache, cache)
        print(f"wrote {args.output} and metadata cache {args.cache}; no image binaries were written")
        return 0
    except (EnrichmentError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
