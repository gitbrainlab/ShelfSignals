#!/usr/bin/env python3
"""Prepare, probe, review, and publish exact-edition cover references safely.

This pipeline starts with the already-downloaded Open Library editions dump
enrichment.  It does not search by title and it does not crawl provider pages.
All discovery and network state stays in ``.cache`` by default.  A cover can
reach a public manifest only after an exact ISBN match, a successful bounded
availability probe, and an explicit human approval tied to a stable candidate
fingerprint.

Typical workflow::

    python3 scripts/cover_source_pipeline.py audit
    python3 scripts/cover_source_pipeline.py plan-batches \
        --queue-dir .cache/cover-review/batches
    python3 scripts/cover_source_pipeline.py probe \
        --plan .cache/cover-review/batch-plan.json --batch-id cover-0001 --limit 10
    # Open docs/review.html and review one private batch queue.
    python3 scripts/cover_source_pipeline.py merge-reviews \
        --input ~/Downloads/candidates.reviews.json --force
    python3 scripts/cover_source_pipeline.py status
    python3 scripts/cover_source_pipeline.py publish

No network request is made by ``audit``, ``plan-batches``, ``init-review``,
``merge-reviews``, ``status``, ``publish``, or ``self-test``.  ``probe`` is
deliberately bounded and resumable.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import struct
import sys
import tempfile
import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, MutableMapping, Optional, Sequence
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


VERSION = "1.0.0"
QUEUE_SCHEMA = "shelfsignals-cover-review-queue@1"
PROBE_SCHEMA = "shelfsignals-cover-probe-cache@1"
REVIEWS_SCHEMA = "shelfsignals-cover-reviews@1"
PUBLIC_SCHEMA = "shelfsignals-reviewed-cover-references@1"
BATCH_PLAN_SCHEMA = "shelfsignals-cover-batch-plan@1"
EDITION_SCHEMA = "shelfsignals-edition-enrichment@1"
VISUAL_SCHEMA = "shelfsignals-book-visuals@1"

DEFAULT_CATALOG = Path("docs/data/sekula_index.json")
DEFAULT_EDITIONS = Path("docs/data/book_editions.json")
DEFAULT_VISUALS = Path("docs/data/book_visuals.json")
DEFAULT_QUEUE = Path(".cache/cover-review/candidates.json")
DEFAULT_PROBES = Path(".cache/cover-review/probes.json")
DEFAULT_REVIEWS = Path(".cache/cover-review/reviews.json")
DEFAULT_PUBLIC_OUTPUT = Path(".cache/cover-review/reviewed-cover-references.json")
DEFAULT_BATCH_PLAN = Path(".cache/cover-review/batch-plan.json")
DEFAULT_BATCH_DIR = Path(".cache/cover-review/batches")

OPEN_LIBRARY_COVERS = "https://covers.openlibrary.org/b/id"
OPEN_LIBRARY_LICENSE = "https://openlibrary.org/developers/licensing"
OPEN_LIBRARY_COVER_DOCS = "https://openlibrary.org/dev/docs/api/covers"
OPEN_LIBRARY_DUMP_DOCS = "https://openlibrary.org/developers/dumps"
USER_AGENT = "ShelfSignals-cover-review/1.0 (+https://github.com/gitbrainlab/ShelfSignals)"

MAX_PROBES_PER_RUN = 100
DEFAULT_BATCH_TARGET = 100
MAX_BATCH_TARGET = 1_000
MIN_INTERVAL_SECONDS = 3.0
DEFAULT_INTERVAL_SECONDS = 3.1
MAX_PROBE_BYTES = 192 * 1024
MIN_IMAGE_EDGE = 40
OL_EDITION_RE = re.compile(r"^OL\d+M$")
REVIEWED_AT_RE = re.compile(r"^20\d{2}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class PipelineError(RuntimeError):
    """A concise, user-facing pipeline failure."""


def utc_now() -> str:
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    moment = datetime.fromtimestamp(int(epoch), timezone.utc) if epoch else datetime.now(timezone.utc)
    return moment.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical_checksum(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


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
        raise PipelineError(f"could not read {path}: {exc}") from exc


def write_json(path: Path, payload: Any, *, compact: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    kwargs = {"ensure_ascii": False, "sort_keys": True}
    if compact:
        kwargs["separators"] = (",", ":")
    else:
        kwargs["indent"] = 2
    rendered = json.dumps(payload, **kwargs) + "\n"
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", delete=False
    ) as handle:
        handle.write(rendered)
        temporary = Path(handle.name)
    temporary.replace(path)


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
    """Return ISBN-13 so ISBN-10 and ISBN-13 exact matches compare correctly."""

    normalized = normalize_isbn(value)
    if len(normalized) == 13:
        return normalized
    if len(normalized) != 10:
        return ""
    body = "978" + normalized[:9]
    total = sum(int(character) * (1 if index % 2 == 0 else 3) for index, character in enumerate(body))
    return body + str((-total) % 10)


def _values(value: Any) -> list[Any]:
    return value if isinstance(value, list) else ([] if value in (None, "") else [value])


def catalog_isbns(record: Mapping[str, Any]) -> list[str]:
    return sorted({item for raw in _values(record.get("isbns")) if (item := canonical_isbn(raw))})


def load_catalog(path: Path) -> list[Mapping[str, Any]]:
    payload = read_json(path)
    if not isinstance(payload, list):
        raise PipelineError("catalog must be a JSON array")
    records: list[Mapping[str, Any]] = []
    seen: set[str] = set()
    for index, record in enumerate(payload):
        if not isinstance(record, Mapping):
            raise PipelineError(f"catalog record {index} is not an object")
        record_id = str(record.get("id") or "").strip()
        if not record_id or record_id in seen:
            raise PipelineError(f"catalog record {index} has a missing or duplicate id")
        seen.add(record_id)
        records.append(record)
    return records


def load_editions(path: Path) -> Mapping[str, Any]:
    payload = read_json(path)
    if not isinstance(payload, Mapping) or payload.get("schema") != EDITION_SCHEMA:
        raise PipelineError(f"{path} is not a {EDITION_SCHEMA} manifest")
    if not isinstance(payload.get("items"), Mapping):
        raise PipelineError(f"{path} has no edition items object")
    return payload


def _catalog_summary(record: Mapping[str, Any], normalized_isbns: Sequence[str]) -> dict[str, Any]:
    authors = [str(value).strip() for value in _values(record.get("authors")) if str(value).strip()]
    return {
        "title": str(record.get("title") or "Untitled").strip(),
        "authors": authors[:8],
        "year": str(record.get("year") or "").strip(),
        "call_number": str(record.get("call_number") or "").strip(),
        "normalized_isbns": list(normalized_isbns),
        "catalog_url": str(record.get("record_url") or "").strip(),
    }


def _candidate_from_dump(
    record_id: str,
    normalized_catalog_isbns: Sequence[str],
    raw: Mapping[str, Any],
    cover_id: int,
    dump_checksum: str,
) -> Optional[dict[str, Any]]:
    source_id = str(raw.get("source_id") or "").strip()
    if not OL_EDITION_RE.fullmatch(source_id):
        return None
    match = raw.get("match") if isinstance(raw.get("match"), Mapping) else {}
    if match.get("method") != "isbn_exact":
        return None
    provider_isbns = {
        item
        for identifier in _values(match.get("identifiers"))
        if isinstance(identifier, Mapping) and identifier.get("type") == "isbn"
        if (item := canonical_isbn(identifier.get("value")))
    }
    matched = sorted(set(normalized_catalog_isbns).intersection(provider_isbns))
    if not matched or not isinstance(cover_id, int) or not 0 < cover_id < 1_000_000_000:
        return None
    edition = raw.get("edition") if isinstance(raw.get("edition"), Mapping) else {}
    fingerprint_payload = {
        "catalog_id": record_id,
        "catalog_isbns": sorted(normalized_catalog_isbns),
        "matched_isbns": matched,
        "provider": "openlibrary",
        "provider_edition_id": source_id,
        "cover_id": cover_id,
        "provider_dump_checksum": dump_checksum,
    }
    fingerprint = canonical_checksum(fingerprint_payload)
    return {
        "candidate_key": f"{record_id}:{source_id}:{cover_id}",
        "candidate_fingerprint": fingerprint,
        "provider": "openlibrary",
        "scope": "external_exact_edition",
        "provider_edition_id": source_id,
        "cover_id": cover_id,
        "matched_identifiers": [{"type": "isbn", "value": value} for value in matched],
        "source_url": f"https://openlibrary.org/books/{source_id}",
        "image_url": f"{OPEN_LIBRARY_COVERS}/{cover_id}-L.jpg?default=false",
        "thumbnail_url": f"{OPEN_LIBRARY_COVERS}/{cover_id}-M.jpg?default=false",
        "edition_summary": {
            key: edition[key]
            for key in ("edition_name", "publish_date", "publishers", "physical_format")
            if edition.get(key) not in (None, "", [])
        },
        "review_required": True,
        "public_eligible": False,
    }


def existing_visual_summary(path: Optional[Path], catalog_by_id: Mapping[str, Mapping[str, Any]]) -> dict[str, int]:
    summary = {
        "existing_public_references": 0,
        "existing_exact_identifier_references": 0,
        "existing_references_with_human_review_metadata": 0,
    }
    if path is None or not path.exists():
        return summary
    payload = read_json(path)
    if not isinstance(payload, Mapping) or payload.get("schema") != VISUAL_SCHEMA:
        raise PipelineError(f"{path} is not a {VISUAL_SCHEMA} manifest")
    items = payload.get("items")
    if not isinstance(items, Mapping):
        return summary
    for record_id, item in items.items():
        if not isinstance(item, Mapping) or item.get("status") != "resolved":
            continue
        summary["existing_public_references"] += 1
        record = catalog_by_id.get(str(record_id), {})
        source_isbn = canonical_isbn(item.get("source_id"))
        if source_isbn and source_isbn in set(catalog_isbns(record)):
            summary["existing_exact_identifier_references"] += 1
        review = item.get("review")
        if isinstance(review, Mapping) and review.get("reviewer") and review.get("reviewed_at"):
            summary["existing_references_with_human_review_metadata"] += 1
    return summary


def build_review_queue(
    records: Sequence[Mapping[str, Any]],
    editions: Mapping[str, Any],
    catalog_path: Path,
    editions_path: Path,
    visuals_path: Optional[Path] = None,
    generated_at: Optional[str] = None,
) -> dict[str, Any]:
    generated_at = generated_at or utc_now()
    edition_items = editions["items"]
    source = editions.get("source") if isinstance(editions.get("source"), Mapping) else {}
    dump_checksum = str(source.get("provider_dump_checksum") or "")
    catalog_by_id = {str(record["id"]): record for record in records}
    items: dict[str, Any] = {}
    reason_counts: Counter[str] = Counter()
    candidate_count = 0
    unsafe_exact_candidates = 0

    for record in records:
        record_id = str(record["id"])
        normalized = catalog_isbns(record)
        edition_item = edition_items.get(record_id)
        raw_candidates = (
            edition_item.get("candidates", [])
            if isinstance(edition_item, Mapping) and isinstance(edition_item.get("candidates"), list)
            else []
        )
        exact_candidates = [
            raw for raw in raw_candidates
            if isinstance(raw, Mapping)
            and isinstance(raw.get("match"), Mapping)
            and raw["match"].get("method") == "isbn_exact"
        ]
        candidates: list[dict[str, Any]] = []
        for raw in exact_candidates:
            edition = raw.get("edition") if isinstance(raw.get("edition"), Mapping) else {}
            for cover_id in _values(edition.get("cover_ids")):
                candidate = _candidate_from_dump(record_id, normalized, raw, cover_id, dump_checksum)
                if candidate:
                    candidates.append(candidate)
                else:
                    unsafe_exact_candidates += 1
        deduplicated = {
            candidate["candidate_key"]: candidate
            for candidate in sorted(candidates, key=lambda value: value["candidate_key"])
        }
        candidates = list(deduplicated.values())

        if candidates:
            status = "review_required"
        elif not normalized:
            status = "unresolved_no_valid_isbn"
        elif exact_candidates:
            status = "unresolved_exact_edition_has_no_safe_cover"
        else:
            status = "unresolved_no_exact_edition_match"
        reason_counts[status] += 1
        candidate_count += len(candidates)
        items[record_id] = {
            "status": status,
            "unresolved_label": "Cover not yet verified for this edition",
            "catalog": _catalog_summary(record, normalized),
            "candidates": candidates,
        }

    visual_counts = existing_visual_summary(visuals_path, catalog_by_id)
    record_count = len(records)
    records_with_candidates = reason_counts["review_required"]
    summary = {
        "catalog_records": record_count,
        "records_with_valid_isbn": sum(bool(catalog_isbns(record)) for record in records),
        "records_with_review_candidates": records_with_candidates,
        "candidate_references": candidate_count,
        "records_without_review_candidates": record_count - records_with_candidates,
        "potential_catalog_coverage_percent": round(records_with_candidates * 100 / record_count, 2) if record_count else 0,
        "unsafe_exact_candidates_rejected": unsafe_exact_candidates,
        "records_by_status": dict(sorted(reason_counts.items())),
        **visual_counts,
    }
    return {
        "schema": QUEUE_SCHEMA,
        "version": VERSION,
        "generated_at": generated_at,
        "inputs": {
            "catalog": str(catalog_path),
            "catalog_sha256": file_checksum(catalog_path),
            "editions": str(editions_path),
            "editions_sha256": file_checksum(editions_path),
            "provider_snapshot": source.get("provider_snapshot"),
            "provider_dump_checksum": dump_checksum,
        },
        "provider": {
            "name": "Open Library",
            "discovery_method": "monthly_editions_dump_exact_isbn_join",
            "dump_documentation": OPEN_LIBRARY_DUMP_DOCS,
            "cover_documentation": OPEN_LIBRARY_COVER_DOCS,
            "licensing": OPEN_LIBRARY_LICENSE,
        },
        "policy": {
            "network_discovery": False,
            "title_matching": False,
            "public_until_reviewed": False,
            "copy_scope": "Provider-edition cover only; never evidence of the Clark copy's condition, texture, binding, or jacket.",
            "unresolved_label": "Cover not yet verified for this edition",
        },
        "summary": summary,
        "items": items,
    }


def _image_dimensions(data: bytes) -> Optional[tuple[int, int]]:
    if len(data) >= 24 and data.startswith(b"\x89PNG\r\n\x1a\n"):
        return struct.unpack(">II", data[16:24])
    if len(data) >= 10 and data[:6] in (b"GIF87a", b"GIF89a"):
        return struct.unpack("<HH", data[6:10])
    if len(data) >= 30 and data.startswith(b"RIFF") and data[8:12] == b"WEBP" and data[12:16] == b"VP8X":
        return 1 + int.from_bytes(data[24:27], "little"), 1 + int.from_bytes(data[27:30], "little")
    if len(data) >= 4 and data.startswith(b"\xff\xd8"):
        offset = 2
        frame_markers = {0xC0, 0xC1, 0xC2, 0xC3, 0xC5, 0xC6, 0xC7, 0xC9, 0xCA, 0xCB, 0xCD, 0xCE, 0xCF}
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
            length = int.from_bytes(data[offset:offset + 2], "big")
            if length < 2 or offset + length > len(data):
                break
            if marker in frame_markers and length >= 7:
                height = int.from_bytes(data[offset + 3:offset + 5], "big")
                width = int.from_bytes(data[offset + 5:offset + 7], "big")
                return width, height
            offset += length
    return None


@dataclass
class CoverProbeClient:
    min_interval: float = DEFAULT_INTERVAL_SECONDS
    timeout: float = 15.0
    _last_request: float = 0.0

    def probe(self, candidate: Mapping[str, Any], checked_at: str) -> dict[str, Any]:
        url = str(candidate.get("image_url") or "")
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.hostname != "covers.openlibrary.org":
            raise PipelineError("candidate image URL is outside the approved HTTPS cover host")
        remaining = self.min_interval - (time.monotonic() - self._last_request)
        if remaining > 0:
            time.sleep(remaining)
        self._last_request = time.monotonic()
        request = Request(
            url,
            headers={
                "Accept": "image/avif,image/webp,image/png,image/jpeg,image/gif",
                "Range": f"bytes=0-{MAX_PROBE_BYTES - 1}",
                "User-Agent": USER_AGENT,
            },
        )
        try:
            with urlopen(request, timeout=self.timeout) as response:
                final_url = response.geturl()
                content_type = response.headers.get_content_type().lower()
                data = response.read(MAX_PROBE_BYTES + 1)
                status_code = int(getattr(response, "status", 200))
                headers = response.headers
            final = urlparse(final_url)
            if final.scheme != "https" or not (
                final.hostname == "covers.openlibrary.org" or str(final.hostname or "").endswith(".archive.org")
            ):
                return {"status": "error", "reason": "unsafe_redirect", "checked_at": checked_at}
            if not content_type.startswith("image/"):
                return {"status": "negative", "reason": "non_image_response", "checked_at": checked_at}
            dimensions = _image_dimensions(data[:MAX_PROBE_BYTES])
            if not dimensions:
                return {"status": "negative", "reason": "dimensions_unreadable", "checked_at": checked_at}
            width, height = dimensions
            if width < MIN_IMAGE_EDGE or height < MIN_IMAGE_EDGE:
                return {"status": "negative", "reason": "placeholder_sized", "checked_at": checked_at}
            return {
                "status": "positive",
                "checked_at": checked_at,
                "http_status": status_code,
                "content_type": content_type,
                "width": width,
                "height": height,
                "aspect_ratio": round(width / height, 6),
                "bytes_examined": min(len(data), MAX_PROBE_BYTES),
                "bounded_probe": True,
                "etag": str(headers.get("ETag") or "")[:200],
                "last_modified": str(headers.get("Last-Modified") or "")[:200],
            }
        except HTTPError as exc:
            retry_after = str(exc.headers.get("Retry-After") or "")[:40] if exc.headers else ""
            if exc.code in (403, 429):
                return {
                    "status": "rate_limited",
                    "reason": f"http_{exc.code}",
                    "retry_after": retry_after,
                    "checked_at": checked_at,
                }
            if exc.code == 404:
                return {"status": "negative", "reason": "not_found", "checked_at": checked_at}
            return {"status": "error", "reason": f"http_{exc.code}", "checked_at": checked_at}
        except (URLError, TimeoutError, OSError) as exc:
            return {"status": "error", "reason": type(exc).__name__, "checked_at": checked_at}


def load_queue(path: Path) -> Mapping[str, Any]:
    payload = read_json(path)
    if not isinstance(payload, Mapping) or payload.get("schema") != QUEUE_SCHEMA:
        raise PipelineError(f"{path} is not a {QUEUE_SCHEMA} file")
    if not isinstance(payload.get("items"), Mapping):
        raise PipelineError(f"{path} has no queue items")
    return payload


def empty_probe_cache(queue: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": PROBE_SCHEMA,
        "version": VERSION,
        "provider": "openlibrary",
        "queue_inputs": queue.get("inputs", {}),
        "updated_at": None,
        "entries": {},
    }


def load_probe_cache(path: Path, queue: Mapping[str, Any]) -> MutableMapping[str, Any]:
    if not path.exists():
        return empty_probe_cache(queue)
    payload = read_json(path)
    if not isinstance(payload, MutableMapping) or payload.get("schema") != PROBE_SCHEMA:
        raise PipelineError(f"{path} is not a {PROBE_SCHEMA} cache")
    if not isinstance(payload.get("entries"), MutableMapping):
        raise PipelineError(f"{path} has no probe entries")
    if payload.get("queue_inputs") != queue.get("inputs", {}):
        raise PipelineError(f"{path} belongs to different queue_inputs; start a new probe cache")
    return payload


def queue_candidates(queue: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    candidates: list[Mapping[str, Any]] = []
    for record_id in sorted(queue["items"]):
        item = queue["items"][record_id]
        if not isinstance(item, Mapping):
            continue
        for candidate in item.get("candidates", []):
            if isinstance(candidate, Mapping):
                candidates.append(candidate)
    return candidates


def queue_candidate_index(
    queue: Mapping[str, Any],
) -> tuple[dict[str, Mapping[str, Any]], dict[str, str]]:
    """Return validated candidate and record indexes for operational tooling."""

    candidates: dict[str, Mapping[str, Any]] = {}
    records: dict[str, str] = {}
    for record_id in sorted(queue["items"]):
        item = queue["items"][record_id]
        if not isinstance(item, Mapping):
            continue
        for candidate in item.get("candidates", []):
            if not isinstance(candidate, Mapping):
                continue
            key = str(candidate.get("candidate_key") or "")
            fingerprint = str(candidate.get("candidate_fingerprint") or "")
            if not key:
                raise PipelineError(f"candidate for {record_id} has no candidate_key")
            if key in candidates:
                raise PipelineError(f"duplicate candidate_key in queue: {key}")
            if not re.fullmatch(r"sha256:[a-f0-9]{64}", fingerprint):
                raise PipelineError(f"candidate {key} has an invalid candidate_fingerprint")
            candidates[key] = candidate
            records[key] = str(record_id)
    return candidates, records


def queue_identity(queue: Mapping[str, Any]) -> str:
    """Fingerprint the exact operational candidate set, independent of JSON layout."""

    candidates, records = queue_candidate_index(queue)
    return canonical_checksum({
        "schema": queue.get("schema"),
        "inputs": queue.get("inputs", {}),
        "candidates": [
            {
                "candidate_key": key,
                "candidate_fingerprint": candidates[key]["candidate_fingerprint"],
                "record_id": records[key],
            }
            for key in sorted(candidates)
        ],
    })


def _batch_fingerprint(queue_fingerprint: str, batch: Mapping[str, Any]) -> str:
    return canonical_checksum({
        "queue_fingerprint": queue_fingerprint,
        "batch_id": batch.get("batch_id"),
        "sequence": batch.get("sequence"),
        "record_ids": batch.get("record_ids", []),
        "candidates": batch.get("candidates", []),
    })


def build_batch_plan(
    queue: Mapping[str, Any],
    target_candidates: int = DEFAULT_BATCH_TARGET,
    generated_at: Optional[str] = None,
) -> dict[str, Any]:
    """Partition candidates deterministically without splitting a catalog record."""

    if not 1 <= target_candidates <= MAX_BATCH_TARGET:
        raise PipelineError(f"batch target must be between 1 and {MAX_BATCH_TARGET}")
    candidates, records_by_key = queue_candidate_index(queue)
    keys_by_record: dict[str, list[str]] = defaultdict(list)
    for key, record_id in records_by_key.items():
        keys_by_record[record_id].append(key)
    for keys in keys_by_record.values():
        keys.sort()

    record_groups: list[tuple[str, list[str]]] = sorted(keys_by_record.items())
    packed: list[list[tuple[str, list[str]]]] = []
    current: list[tuple[str, list[str]]] = []
    current_count = 0
    for record_id, keys in record_groups:
        if current and current_count + len(keys) > target_candidates:
            packed.append(current)
            current = []
            current_count = 0
        current.append((record_id, keys))
        current_count += len(keys)
    if current:
        packed.append(current)

    queue_fingerprint = queue_identity(queue)
    batches: list[dict[str, Any]] = []
    for index, groups in enumerate(packed, start=1):
        entries = [
            {
                "candidate_key": key,
                "candidate_fingerprint": str(candidates[key]["candidate_fingerprint"]),
            }
            for _record_id, keys in groups
            for key in keys
        ]
        batch: dict[str, Any] = {
            "batch_id": f"cover-{index:04d}",
            "sequence": index,
            "record_ids": [record_id for record_id, _keys in groups],
            "record_count": len(groups),
            "candidate_count": len(entries),
            "candidates": entries,
        }
        batch["batch_fingerprint"] = _batch_fingerprint(queue_fingerprint, batch)
        batches.append(batch)

    candidate_counts = [batch["candidate_count"] for batch in batches]
    return {
        "schema": BATCH_PLAN_SCHEMA,
        "version": VERSION,
        "generated_at": generated_at or utc_now(),
        "queue_inputs": queue.get("inputs", {}),
        "queue_fingerprint": queue_fingerprint,
        "policy": {
            "record_atomic": True,
            "public_effect": "none",
            "network_effect": "none",
            "image_binaries_included": False,
        },
        "target_candidates": target_candidates,
        "summary": {
            "batch_count": len(batches),
            "record_count": len(record_groups),
            "candidate_count": len(candidates),
            "largest_batch_candidates": max(candidate_counts, default=0),
            "batches_over_target": sum(count > target_candidates for count in candidate_counts),
        },
        "batches": batches,
    }


def validate_batch_plan(plan: Mapping[str, Any], queue: Mapping[str, Any]) -> Mapping[str, Any]:
    """Fail closed if a plan is stale, incomplete, duplicated, or hand-edited."""

    if plan.get("schema") != BATCH_PLAN_SCHEMA:
        raise PipelineError(f"batch plan is not a {BATCH_PLAN_SCHEMA} file")
    expected_identity = queue_identity(queue)
    if plan.get("queue_inputs") != queue.get("inputs", {}):
        raise PipelineError("batch plan queue_inputs do not match the current queue")
    if plan.get("queue_fingerprint") != expected_identity:
        raise PipelineError("batch plan is stale for the current candidate set")
    batches = plan.get("batches")
    if not isinstance(batches, list):
        raise PipelineError("batch plan has no batches array")

    queue_index, records_by_key = queue_candidate_index(queue)
    seen_keys: set[str] = set()
    seen_records: set[str] = set()
    seen_ids: set[str] = set()
    for position, batch in enumerate(batches, start=1):
        if not isinstance(batch, Mapping):
            raise PipelineError(f"batch {position} is not an object")
        batch_id = str(batch.get("batch_id") or "")
        if not re.fullmatch(r"cover-\d{4,}", batch_id) or batch_id in seen_ids:
            raise PipelineError(f"batch {position} has an invalid or duplicate batch_id")
        seen_ids.add(batch_id)
        if batch.get("sequence") != position:
            raise PipelineError(f"batch {batch_id} has a non-contiguous sequence")
        record_ids = batch.get("record_ids")
        entries = batch.get("candidates")
        if not isinstance(record_ids, list) or not all(isinstance(value, str) for value in record_ids):
            raise PipelineError(f"batch {batch_id} has invalid record_ids")
        if not isinstance(entries, list):
            raise PipelineError(f"batch {batch_id} has no candidates array")
        if len(record_ids) != len(set(record_ids)) or seen_records.intersection(record_ids):
            raise PipelineError(f"batch {batch_id} splits or duplicates a catalog record")
        seen_records.update(record_ids)
        batch_keys: list[str] = []
        for entry in entries:
            if not isinstance(entry, Mapping):
                raise PipelineError(f"batch {batch_id} has an invalid candidate entry")
            key = str(entry.get("candidate_key") or "")
            candidate = queue_index.get(key)
            if candidate is None or key in seen_keys:
                raise PipelineError(f"batch {batch_id} has an unknown or duplicate candidate_key {key!r}")
            if records_by_key[key] not in record_ids:
                raise PipelineError(f"batch {batch_id} candidate {key} is assigned to the wrong record")
            if entry.get("candidate_fingerprint") != candidate.get("candidate_fingerprint"):
                raise PipelineError(f"batch {batch_id} candidate {key} has a stale fingerprint")
            seen_keys.add(key)
            batch_keys.append(key)
        expected_keys = sorted(key for key, record_id in records_by_key.items() if record_id in record_ids)
        if sorted(batch_keys) != expected_keys:
            raise PipelineError(f"batch {batch_id} does not contain every candidate for its records")
        if batch.get("record_count") != len(record_ids) or batch.get("candidate_count") != len(entries):
            raise PipelineError(f"batch {batch_id} summary counts are stale")
        if batch.get("batch_fingerprint") != _batch_fingerprint(expected_identity, batch):
            raise PipelineError(f"batch {batch_id} fingerprint is stale")

    if seen_keys != set(queue_index):
        raise PipelineError("batch plan does not cover the current candidate set exactly once")
    return plan


def load_batch_plan(path: Path, queue: Mapping[str, Any]) -> Mapping[str, Any]:
    payload = read_json(path)
    if not isinstance(payload, Mapping):
        raise PipelineError(f"{path} is not a batch plan object")
    return validate_batch_plan(payload, queue)


def find_batch(plan: Mapping[str, Any], batch_id: str) -> Mapping[str, Any]:
    for batch in plan.get("batches", []):
        if isinstance(batch, Mapping) and batch.get("batch_id") == batch_id:
            return batch
    raise PipelineError(f"unknown batch_id {batch_id!r}")


def build_batch_review_queue(
    queue: Mapping[str, Any],
    plan: Mapping[str, Any],
    batch: Mapping[str, Any],
    *,
    _plan_validated: bool = False,
) -> dict[str, Any]:
    """Create a browser-reviewable private queue shard with unchanged evidence."""

    if not _plan_validated:
        validate_batch_plan(plan, queue)
    batch_id = str(batch.get("batch_id") or "")
    current = find_batch(plan, batch_id)
    if current != batch:
        raise PipelineError(f"batch {batch_id} does not match the validated plan")
    items = {record_id: queue["items"][record_id] for record_id in batch["record_ids"]}
    status_counts = Counter(str(item.get("status") or "unknown") for item in items.values())
    candidate_count = sum(len(item.get("candidates", [])) for item in items.values())
    output = dict(queue)
    output["generated_at"] = plan.get("generated_at")
    output["batch"] = {
        "batch_id": batch_id,
        "sequence": batch.get("sequence"),
        "plan_queue_fingerprint": plan.get("queue_fingerprint"),
        "batch_fingerprint": batch.get("batch_fingerprint"),
        "publication_effect": "none",
    }
    output["summary"] = {
        "catalog_records": len(items),
        "records_with_valid_isbn": sum(bool(item.get("catalog", {}).get("normalized_isbns")) for item in items.values()),
        "records_with_review_candidates": sum(bool(item.get("candidates")) for item in items.values()),
        "candidate_references": candidate_count,
        "records_without_review_candidates": sum(not bool(item.get("candidates")) for item in items.values()),
        "records_by_status": dict(sorted(status_counts.items())),
        "source_catalog_records": queue.get("summary", {}).get("catalog_records"),
        "source_candidate_references": queue.get("summary", {}).get("candidate_references"),
    }
    output["items"] = items
    return output


def write_batch_review_queues(
    queue: Mapping[str, Any],
    plan: Mapping[str, Any],
    output_dir: Path,
    *,
    force: bool = False,
) -> list[Path]:
    validate_batch_plan(plan, queue)
    paths = [output_dir / f"{batch['batch_id']}.candidates.json" for batch in plan["batches"]]
    existing = [path for path in paths if path.exists()]
    if existing and not force:
        raise PipelineError(f"batch review queue already exists: {existing[0]} (use --force to replace planned files)")
    for batch, path in zip(plan["batches"], paths):
        write_json(path, build_batch_review_queue(queue, plan, batch, _plan_validated=True), compact=True)
    return paths


def probe_candidates(
    queue: Mapping[str, Any],
    cache: MutableMapping[str, Any],
    cache_path: Path,
    client: CoverProbeClient,
    limit: int,
    force: bool = False,
    include_keys: Optional[set[str]] = None,
) -> dict[str, int]:
    entries = cache["entries"]
    attempted = 0
    skipped = 0
    counts: Counter[str] = Counter()
    candidates = queue_candidates(queue)
    selected = [
        candidate for candidate in candidates
        if include_keys is None or str(candidate.get("candidate_key") or "") in include_keys
    ]
    if include_keys is not None:
        found = {str(candidate.get("candidate_key") or "") for candidate in selected}
        missing = include_keys - found
        if missing:
            raise PipelineError(f"probe selection contains unknown candidate_key {sorted(missing)[0]!r}")
    for candidate in selected:
        key = str(candidate.get("candidate_key") or "")
        fingerprint = str(candidate.get("candidate_fingerprint") or "")
        previous = entries.get(key)
        reusable = (
            not force
            and isinstance(previous, Mapping)
            and previous.get("candidate_fingerprint") == fingerprint
            and previous.get("status") in {"positive", "negative"}
        )
        if reusable:
            skipped += 1
            continue
        if attempted >= limit:
            break
        checked_at = utc_now()
        outcome = client.probe(candidate, checked_at)
        entries[key] = {"candidate_fingerprint": fingerprint, **outcome}
        cache["updated_at"] = checked_at
        write_json(cache_path, cache, compact=True)
        attempted += 1
        counts[str(outcome.get("status") or "error")] += 1
        if outcome.get("status") == "rate_limited":
            break
    terminal = 0
    positive = 0
    negative = 0
    for candidate in selected:
        key = str(candidate.get("candidate_key") or "")
        previous = entries.get(key)
        if not isinstance(previous, Mapping) or previous.get("candidate_fingerprint") != candidate.get("candidate_fingerprint"):
            continue
        status = previous.get("status")
        if status in {"positive", "negative"}:
            terminal += 1
            positive += status == "positive"
            negative += status == "negative"
    return {
        "selected": len(selected),
        "attempted": attempted,
        "skipped_cached": skipped,
        "terminal_cached": terminal,
        "positive_cached": positive,
        "negative_cached": negative,
        "remaining": len(selected) - terminal,
        **dict(sorted(counts.items())),
    }


def review_template(queue: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "schema": REVIEWS_SCHEMA,
        "version": VERSION,
        "queue_inputs": queue.get("inputs", {}),
        "instructions": {
            "decision": "Use approve, reject, or defer.",
            "approval_gate": (
                "Approval requires candidate_fingerprint, reviewer, reviewed_at, exact_edition_confirmed=true, "
                "visual_check=true, rights_scope=remote_reference_only, and an evidence_note."
            ),
            "selection": "Approve at most one front-cover candidate per catalog record.",
        },
        "decisions": {},
    }


def load_reviews(path: Path) -> Mapping[str, Any]:
    payload = read_json(path)
    if not isinstance(payload, Mapping) or payload.get("schema") != REVIEWS_SCHEMA:
        raise PipelineError(f"{path} is not a {REVIEWS_SCHEMA} file")
    if not isinstance(payload.get("decisions"), Mapping):
        raise PipelineError(f"{path} has no decisions object")
    return payload


def require_matching_queue_inputs(
    queue: Mapping[str, Any],
    state: Mapping[str, Any],
    label: str,
) -> None:
    if state.get("queue_inputs") != queue.get("inputs", {}):
        raise PipelineError(f"{label} queue_inputs do not match the current review queue")


def merge_review_ledgers(
    queue: Mapping[str, Any],
    ledgers: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    """Merge complete review decisions deterministically or reject conflicts."""

    candidates = {
        str(candidate.get("candidate_key") or ""): (str(record_id), candidate)
        for record_id, item in queue["items"].items()
        if isinstance(item, Mapping)
        for candidate in item.get("candidates", [])
        if isinstance(candidate, Mapping)
    }
    merged: dict[str, Any] = {}
    for ledger_index, ledger in enumerate(ledgers, start=1):
        if not isinstance(ledger, Mapping) or ledger.get("schema") != REVIEWS_SCHEMA:
            raise PipelineError(f"review ledger {ledger_index} is not a {REVIEWS_SCHEMA} file")
        if ledger.get("queue_inputs") != queue.get("inputs", {}):
            raise PipelineError(f"review ledger {ledger_index} does not match the current queue_inputs")
        decisions = ledger.get("decisions")
        if not isinstance(decisions, Mapping):
            raise PipelineError(f"review ledger {ledger_index} has no decisions object")
        for key in sorted(decisions):
            review = decisions[key]
            current = candidates.get(str(key))
            if current is None:
                raise PipelineError(f"review ledger {ledger_index} contains unknown candidate_key {key!r}")
            if not isinstance(review, Mapping):
                raise PipelineError(f"review ledger {ledger_index} decision {key!r} is not an object")
            candidate = current[1]
            if review.get("candidate_fingerprint") != candidate.get("candidate_fingerprint"):
                raise PipelineError(f"review ledger {ledger_index} decision {key!r} has a stale candidate_fingerprint")
            if review.get("decision") not in {"approve", "reject", "defer"}:
                raise PipelineError(f"review ledger {ledger_index} decision {key!r} is not approve, reject, or defer")
            normalized = dict(review)
            previous = merged.get(str(key))
            if previous is not None and previous != normalized:
                raise PipelineError(f"conflicting review decisions exist for candidate_key {key!r}")
            merged[str(key)] = normalized

    approvals_by_record: dict[str, list[str]] = defaultdict(list)
    for key, review in merged.items():
        if review.get("decision") == "approve":
            approvals_by_record[candidates[key][0]].append(key)
    conflicts = {
        record_id: keys
        for record_id, keys in approvals_by_record.items()
        if len(keys) > 1
    }
    if conflicts:
        record_id = sorted(conflicts)[0]
        raise PipelineError(
            f"merged ledgers approve multiple front covers for {record_id}: "
            + ", ".join(sorted(conflicts[record_id]))
        )

    output = review_template(queue)
    output["decisions"] = {key: merged[key] for key in sorted(merged)}
    return output


def _valid_approval(
    candidate: Mapping[str, Any],
    review: Any,
    probe: Any,
) -> tuple[bool, str]:
    if not isinstance(review, Mapping) or review.get("decision") != "approve":
        return False, "not_approved"
    fingerprint = candidate.get("candidate_fingerprint")
    if review.get("candidate_fingerprint") != fingerprint:
        return False, "stale_review_fingerprint"
    if not str(review.get("reviewer") or "").strip():
        return False, "missing_reviewer"
    if not REVIEWED_AT_RE.fullmatch(str(review.get("reviewed_at") or "")):
        return False, "invalid_reviewed_at"
    if review.get("exact_edition_confirmed") is not True:
        return False, "exact_edition_not_confirmed"
    if review.get("visual_check") is not True:
        return False, "visual_check_not_confirmed"
    if review.get("rights_scope") != "remote_reference_only":
        return False, "unsafe_rights_scope"
    if len(str(review.get("evidence_note") or "").strip()) < 12:
        return False, "missing_evidence_note"
    if not isinstance(probe, Mapping) or probe.get("status") != "positive":
        return False, "missing_positive_probe"
    if probe.get("candidate_fingerprint") != fingerprint:
        return False, "stale_probe_fingerprint"
    if probe.get("bounded_probe") is not True:
        return False, "unbounded_probe"
    if not REVIEWED_AT_RE.fullmatch(str(probe.get("checked_at") or "")):
        return False, "invalid_probe_timestamp"
    if any(
        isinstance(probe.get(field), bool)
        or not isinstance(probe.get(field), int)
        or probe.get(field) <= 0
        for field in ("width", "height")
    ):
        return False, "invalid_probe_dimensions"
    aspect_ratio = probe.get("aspect_ratio")
    if isinstance(aspect_ratio, bool) or not isinstance(aspect_ratio, (int, float)) or aspect_ratio <= 0:
        return False, "invalid_probe_aspect_ratio"
    if candidate.get("scope") != "external_exact_edition" or not candidate.get("matched_identifiers"):
        return False, "candidate_not_exact_edition"
    return True, "approved"


def pipeline_status(
    queue: Mapping[str, Any],
    probes: Mapping[str, Any],
    reviews: Mapping[str, Any],
    include_keys: Optional[set[str]] = None,
) -> dict[str, Any]:
    """Build an offline progress and publication-gate report."""

    require_matching_queue_inputs(queue, probes, "probe cache")
    require_matching_queue_inputs(queue, reviews, "review ledger")
    candidates, records_by_key = queue_candidate_index(queue)
    selected_keys = set(candidates) if include_keys is None else set(include_keys)
    unknown = selected_keys - set(candidates)
    if unknown:
        raise PipelineError(f"status selection contains unknown candidate_key {sorted(unknown)[0]!r}")
    probe_entries = probes.get("entries") if isinstance(probes.get("entries"), Mapping) else {}
    decisions = reviews.get("decisions") if isinstance(reviews.get("decisions"), Mapping) else {}

    probe_counts: Counter[str] = Counter()
    review_counts: Counter[str] = Counter()
    gate_counts: Counter[str] = Counter()
    current_decisions: set[str] = set()
    valid_approvals_by_record: dict[str, list[str]] = defaultdict(list)
    keys_by_record: dict[str, set[str]] = defaultdict(set)

    for key in sorted(selected_keys):
        candidate = candidates[key]
        record_id = records_by_key[key]
        keys_by_record[record_id].add(key)
        probe = probe_entries.get(key)
        if not isinstance(probe, Mapping):
            probe_counts["missing"] += 1
        elif probe.get("candidate_fingerprint") != candidate.get("candidate_fingerprint"):
            probe_counts["stale"] += 1
        else:
            probe_counts[str(probe.get("status") or "error")] += 1

        review = decisions.get(key)
        if not isinstance(review, Mapping):
            review_counts["unreviewed"] += 1
            continue
        if review.get("candidate_fingerprint") != candidate.get("candidate_fingerprint"):
            review_counts["stale"] += 1
            continue
        decision = str(review.get("decision") or "invalid")
        review_counts[decision] += 1
        current_decisions.add(key)
        if decision == "approve":
            valid, reason = _valid_approval(candidate, review, probe)
            gate_counts[reason] += 1
            if valid:
                valid_approvals_by_record[record_id].append(key)

    complete_records = sum(keys.issubset(current_decisions) for keys in keys_by_record.values())
    eligible_records = sum(len(keys) == 1 for keys in valid_approvals_by_record.values())
    conflicting_records = sum(len(keys) > 1 for keys in valid_approvals_by_record.values())
    total = len(selected_keys)
    terminal_probes = probe_counts["positive"] + probe_counts["negative"]
    return {
        "schema": "shelfsignals-cover-pipeline-status@1",
        "generated_at": utc_now(),
        "scope": "all_candidates" if include_keys is None else "selected_batch",
        "queue_fingerprint": queue_identity(queue),
        "summary": {
            "catalog_records_in_scope": len(keys_by_record),
            "candidate_references_in_scope": total,
            "terminal_probe_results": terminal_probes,
            "probe_completion_percent": round(terminal_probes * 100 / total, 2) if total else 100.0,
            "reviewed_candidates": len(current_decisions),
            "review_completion_percent": round(len(current_decisions) * 100 / total, 2) if total else 100.0,
            "fully_reviewed_records": complete_records,
            "publication_eligible_records": eligible_records,
            "records_with_multiple_gate-valid_approvals": conflicting_records,
        },
        "probe_status": dict(sorted(probe_counts.items())),
        "review_status": dict(sorted(review_counts.items())),
        "approval_gate_status": dict(sorted(gate_counts.items())),
        "policy": {
            "report_is_offline": True,
            "report_publishes_nothing": True,
            "image_binaries_read_or_written": False,
        },
    }


def build_public_manifest(
    queue: Mapping[str, Any],
    probes: Mapping[str, Any],
    reviews: Mapping[str, Any],
    generated_at: Optional[str] = None,
) -> dict[str, Any]:
    generated_at = generated_at or utc_now()
    require_matching_queue_inputs(queue, probes, "probe cache")
    require_matching_queue_inputs(queue, reviews, "review ledger")
    probe_entries = probes.get("entries") if isinstance(probes.get("entries"), Mapping) else {}
    decisions = reviews.get("decisions") if isinstance(reviews.get("decisions"), Mapping) else {}
    accepted_by_record: dict[str, list[tuple[Mapping[str, Any], Mapping[str, Any], Mapping[str, Any]]]] = defaultdict(list)
    rejection_counts: Counter[str] = Counter()

    for record_id, item in queue["items"].items():
        if not isinstance(item, Mapping):
            continue
        for candidate in item.get("candidates", []):
            if not isinstance(candidate, Mapping):
                continue
            key = str(candidate.get("candidate_key") or "")
            review = decisions.get(key)
            probe = probe_entries.get(key)
            valid, reason = _valid_approval(candidate, review, probe)
            if valid:
                accepted_by_record[str(record_id)].append((candidate, review, probe))
            elif isinstance(review, Mapping) and review.get("decision") == "approve":
                rejection_counts[reason] += 1

    items: dict[str, Any] = {}
    for record_id, accepted in sorted(accepted_by_record.items()):
        if len(accepted) != 1:
            rejection_counts["multiple_approved_front_covers"] += len(accepted)
            continue
        candidate, review, probe = accepted[0]
        catalog = queue["items"][record_id].get("catalog", {})
        items[record_id] = {
            "status": "resolved",
            "lookup_status": "positive",
            "scope": "external_exact_edition",
            "image_url": candidate["image_url"],
            "thumbnail_url": candidate["thumbnail_url"],
            "source": "openlibrary",
            "source_id": candidate["provider_edition_id"],
            "source_url": candidate["source_url"],
            "cover_id": candidate["cover_id"],
            "match_method": "isbn_exact_human_reviewed",
            "match_confidence": 1.0,
            "matched_identifiers": candidate["matched_identifiers"],
            "image": {
                "width": probe["width"],
                "height": probe["height"],
                "aspect_ratio": probe["aspect_ratio"],
            },
            "review": {
                "reviewer": str(review["reviewer"]).strip(),
                "reviewed_at": review["reviewed_at"],
                "evidence_note": str(review["evidence_note"]).strip(),
                "candidate_fingerprint": candidate["candidate_fingerprint"],
            },
            "gate_receipt": {
                "exact_edition_confirmed": review["exact_edition_confirmed"],
                "visual_check": review["visual_check"],
                "rights_scope": review["rights_scope"],
                "probe": {
                    "status": probe.get("status"),
                    "bounded_probe": probe.get("bounded_probe"),
                    "candidate_fingerprint": probe.get("candidate_fingerprint"),
                    "checked_at": probe.get("checked_at"),
                    "width": probe.get("width"),
                    "height": probe.get("height"),
                },
            },
            "rights": {
                "status": "underlying_cover_rights_not_established",
                "display_scope": "provider_hosted_reference_only",
                "binary_cache_allowed": False,
                "license_url": OPEN_LIBRARY_LICENSE,
                "note": (
                    "Open Library's database licensing statement does not establish an open license for the "
                    "underlying cover artwork. ShelfSignals stores the reference, not the image binary."
                ),
            },
            "provenance": {
                "catalog_url": catalog.get("catalog_url"),
                "provider_edition_url": candidate["source_url"],
                "provider_snapshot": queue.get("inputs", {}).get("provider_snapshot"),
                "provider_dump_checksum": queue.get("inputs", {}).get("provider_dump_checksum"),
                "probe_checked_at": probe.get("checked_at"),
                "copy_scope": (
                    "This is an external exact-edition cover reference, not a photograph of the Clark copy "
                    "and not evidence of its physical condition."
                ),
            },
        }

    return {
        "schema": PUBLIC_SCHEMA,
        "version": VERSION,
        "generated_at": generated_at,
        "policy": {
            "public_items": "Human-reviewed exact-ISBN edition references with positive bounded probes only.",
            "unreviewed_candidates_included": False,
            "binary_images_included": False,
            "provider": "Open Library",
            "provider_documentation": OPEN_LIBRARY_COVER_DOCS,
            "provider_licensing": OPEN_LIBRARY_LICENSE,
        },
        "summary": {
            "published": len(items),
            "approved_but_rejected_by_gate": sum(rejection_counts.values()),
            "gate_rejections": dict(sorted(rejection_counts.items())),
        },
        "items": items,
    }


def run_self_test() -> None:
    assert canonical_isbn("0-374-22626-1") == "9780374226268"
    assert canonical_isbn("978-0-374-22626-8") == "9780374226268"
    assert canonical_isbn("978-0-374-22626-2") == ""
    with tempfile.TemporaryDirectory() as directory:
        root = Path(directory)
        catalog_path = root / "catalog.json"
        editions_path = root / "editions.json"
        records = [
            {"id": "alma1", "title": "Exact", "isbns": ["0-374-22626-1"], "record_url": "https://example.test/1"},
            {"id": "alma2", "title": "No ISBN", "isbns": []},
            {"id": "alma3", "title": "No cover", "isbns": ["9780520270947"]},
            {"id": "alma4", "title": "Unsafe", "isbns": ["9781847490063"]},
        ]
        editions = {
            "schema": EDITION_SCHEMA,
            "source": {"provider_snapshot": "2026-06-30", "provider_dump_checksum": "md5:test"},
            "items": {
                "alma1": {"candidates": [{
                    "source_id": "OL1M",
                    "match": {"method": "isbn_exact", "identifiers": [{"type": "isbn", "value": "9780374226268"}]},
                    "edition": {"cover_ids": [123], "publish_date": "2000"},
                }]},
                "alma3": {"candidates": [{
                    "source_id": "OL2M",
                    "match": {"method": "isbn_exact", "identifiers": [{"type": "isbn", "value": "9780520270947"}]},
                    "edition": {},
                }]},
                "alma4": {"candidates": [{
                    "source_id": "OL3M",
                    "match": {"method": "isbn_exact", "identifiers": [{"type": "isbn", "value": "9783869302560"}]},
                    "edition": {"cover_ids": [999]},
                }]},
            },
        }
        catalog_path.write_text(json.dumps(records), encoding="utf-8")
        editions_path.write_text(json.dumps(editions), encoding="utf-8")
        queue = build_review_queue(records, editions, catalog_path, editions_path, generated_at="2026-07-13T00:00:00Z")
        assert queue["summary"]["records_with_review_candidates"] == 1
        assert queue["summary"]["candidate_references"] == 1
        assert queue["items"]["alma2"]["status"] == "unresolved_no_valid_isbn"
        assert queue["items"]["alma3"]["status"] == "unresolved_exact_edition_has_no_safe_cover"
        assert queue["items"]["alma4"]["status"] == "unresolved_exact_edition_has_no_safe_cover"
        candidate = queue["items"]["alma1"]["candidates"][0]
        key = candidate["candidate_key"]
        probe = {
            "schema": PROBE_SCHEMA,
            "queue_inputs": queue["inputs"],
            "entries": {key: {
                "candidate_fingerprint": candidate["candidate_fingerprint"],
                "status": "positive", "checked_at": "2026-07-13T00:00:00Z",
                "bounded_probe": True,
                "width": 300, "height": 400, "aspect_ratio": 0.75,
            }},
        }
        reviews = {
            "schema": REVIEWS_SCHEMA,
            "queue_inputs": queue["inputs"],
            "decisions": {key: {
                "candidate_fingerprint": candidate["candidate_fingerprint"],
                "decision": "approve", "reviewer": "Test reviewer",
                "reviewed_at": "2026-07-13T00:00:00Z",
                "exact_edition_confirmed": True, "visual_check": True,
                "rights_scope": "remote_reference_only",
                "evidence_note": "ISBN, publisher, and date compared to the catalog record.",
            }},
        }
        public = build_public_manifest(queue, probe, reviews, generated_at="2026-07-13T00:00:00Z")
        assert list(public["items"]) == ["alma1"]
        assert public["items"]["alma1"]["rights"]["binary_cache_allowed"] is False
        receipt = public["items"]["alma1"]["gate_receipt"]
        assert receipt["exact_edition_confirmed"] is True
        assert receipt["visual_check"] is True
        assert receipt["rights_scope"] == "remote_reference_only"
        assert receipt["probe"]["bounded_probe"] is True
        assert receipt["probe"]["candidate_fingerprint"] == candidate["candidate_fingerprint"]
        assert receipt["probe"]["width"] == 300
        assert receipt["probe"]["height"] == 400
        unbounded_probe = json.loads(json.dumps(probe))
        unbounded_probe["entries"][key]["bounded_probe"] = False
        blocked = build_public_manifest(queue, unbounded_probe, reviews, generated_at="2026-07-13T00:00:00Z")
        assert blocked["items"] == {}
        assert blocked["summary"]["gate_rejections"]["unbounded_probe"] == 1
        plan = build_batch_plan(queue, target_candidates=1, generated_at="2026-07-13T00:00:00Z")
        assert plan["summary"]["candidate_count"] == 1
        assert plan["summary"]["batch_count"] == 1
        validate_batch_plan(plan, queue)
        shard = build_batch_review_queue(queue, plan, plan["batches"][0])
        assert shard["batch"]["publication_effect"] == "none"
        assert shard["summary"]["candidate_references"] == 1
        status = pipeline_status(queue, probe, reviews)
        assert status["summary"]["publication_eligible_records"] == 1
        assert status["summary"]["probe_completion_percent"] == 100.0
        merged = merge_review_ledgers(queue, [reviews, json.loads(json.dumps(reviews))])
        assert list(merged["decisions"]) == [key]
        conflicting = json.loads(json.dumps(reviews))
        conflicting["decisions"][key]["evidence_note"] = "A conflicting review note that is still long enough."
        try:
            merge_review_ledgers(queue, [reviews, conflicting])
            raise AssertionError("conflicting reviews should fail")
        except PipelineError as exc:
            assert "conflicting review decisions" in str(exc)
        reviews["decisions"][key]["candidate_fingerprint"] = "sha256:stale"
        stale = build_public_manifest(queue, probe, reviews, generated_at="2026-07-13T00:00:00Z")
        assert stale["items"] == {}
        assert stale["summary"]["gate_rejections"]["stale_review_fingerprint"] == 1
    print("cover source pipeline self-test passed")


def add_common_inputs(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    parser.add_argument("--editions", type=Path, default=DEFAULT_EDITIONS)
    parser.add_argument("--visuals", type=Path, default=DEFAULT_VISUALS)


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    audit = subparsers.add_parser("audit", help="build the all-record private review queue without network access")
    add_common_inputs(audit)
    audit.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)

    batches = subparsers.add_parser(
        "plan-batches",
        help="write a deterministic private batch plan and optional browser-review queue shards",
    )
    batches.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    batches.add_argument("--plan", type=Path, default=DEFAULT_BATCH_PLAN)
    batches.add_argument("--queue-dir", type=Path, help="also write one private review queue per batch")
    batches.add_argument("--target-candidates", type=int, default=DEFAULT_BATCH_TARGET)
    batches.add_argument("--force", action="store_true", help="replace the plan and its planned queue shard files")

    initialize = subparsers.add_parser("init-review", help="create an empty private review ledger")
    initialize.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    initialize.add_argument("--reviews", type=Path, default=DEFAULT_REVIEWS)
    initialize.add_argument("--force", action="store_true", help="replace an existing empty/review ledger")

    merge = subparsers.add_parser("merge-reviews", help="merge compatible partial review ledgers and reject conflicts")
    merge.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    merge.add_argument("--input", dest="inputs", type=Path, action="append", required=True, help="partial review ledger; repeat for each input")
    merge.add_argument("--output", type=Path, default=DEFAULT_REVIEWS)
    merge.add_argument("--force", action="store_true", help="replace an existing merged ledger")

    probe = subparsers.add_parser("probe", help="run a bounded, rate-limited, resumable availability probe")
    probe.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    probe.add_argument("--probes", type=Path, default=DEFAULT_PROBES)
    probe.add_argument("--limit", type=int, default=10, help=f"network requests this run (maximum {MAX_PROBES_PER_RUN})")
    probe.add_argument("--min-interval", type=float, default=DEFAULT_INTERVAL_SECONDS)
    probe.add_argument("--timeout", type=float, default=15.0)
    probe.add_argument("--force", action="store_true", help="reprobe cached positive/negative results")
    probe.add_argument("--plan", type=Path, help="validated batch plan used to limit this run")
    probe.add_argument("--batch-id", help="batch ID from --plan; repeated runs resume from the shared probe cache")

    status = subparsers.add_parser("status", help="report offline probe, review, and publication-gate progress")
    status.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    status.add_argument("--probes", type=Path, default=DEFAULT_PROBES)
    status.add_argument("--reviews", type=Path, default=DEFAULT_REVIEWS)
    status.add_argument("--plan", type=Path, help="validated batch plan used to scope the report")
    status.add_argument("--batch-id", help="batch ID from --plan")
    status.add_argument("--output", type=Path, help="optional private JSON report path")

    publish = subparsers.add_parser("publish", help="emit only reviewed, positively probed exact-edition references")
    publish.add_argument("--queue", type=Path, default=DEFAULT_QUEUE)
    publish.add_argument("--probes", type=Path, default=DEFAULT_PROBES)
    publish.add_argument("--reviews", type=Path, default=DEFAULT_REVIEWS)
    publish.add_argument("--output", type=Path, default=DEFAULT_PUBLIC_OUTPUT)
    publish.add_argument(
        "--allow-docs-output",
        action="store_true",
        help="explicitly permit writing under docs/ after review",
    )

    subparsers.add_parser("self-test", help="run deterministic checks without network access")
    args = parser.parse_args(argv)
    if args.command == "probe":
        if not 1 <= args.limit <= MAX_PROBES_PER_RUN:
            parser.error(f"--limit must be between 1 and {MAX_PROBES_PER_RUN}")
        if args.min_interval < MIN_INTERVAL_SECONDS:
            parser.error(f"--min-interval must be at least {MIN_INTERVAL_SECONDS} seconds")
        if not 2 <= args.timeout <= 60:
            parser.error("--timeout must be between 2 and 60 seconds")
        if bool(args.plan) != bool(args.batch_id):
            parser.error("--plan and --batch-id must be supplied together")
    if args.command == "plan-batches" and not 1 <= args.target_candidates <= MAX_BATCH_TARGET:
        parser.error(f"--target-candidates must be between 1 and {MAX_BATCH_TARGET}")
    if args.command == "status" and bool(args.plan) != bool(args.batch_id):
        parser.error("--plan and --batch-id must be supplied together")
    return args


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    try:
        if args.command == "self-test":
            run_self_test()
            return 0
        if args.command == "audit":
            records = load_catalog(args.catalog)
            editions = load_editions(args.editions)
            visuals = args.visuals if args.visuals.exists() else None
            queue = build_review_queue(records, editions, args.catalog, args.editions, visuals)
            write_json(args.queue, queue, compact=True)
            print(json.dumps(queue["summary"], indent=2, sort_keys=True))
            print(f"wrote private review queue {args.queue}; no network requests were made")
            return 0
        queue = load_queue(args.queue)
        if args.command == "plan-batches":
            if args.plan.exists() and not args.force:
                raise PipelineError(f"batch plan already exists: {args.plan} (use --force to replace it)")
            plan = build_batch_plan(queue, target_candidates=args.target_candidates)
            if args.queue_dir:
                paths = write_batch_review_queues(queue, plan, args.queue_dir, force=args.force)
            else:
                paths = []
            write_json(args.plan, plan, compact=True)
            print(json.dumps(plan["summary"], indent=2, sort_keys=True))
            print(f"wrote private batch plan {args.plan}; no network requests were made")
            if paths:
                print(f"wrote {len(paths)} private browser-review queues under {args.queue_dir}")
            return 0
        if args.command == "init-review":
            if args.reviews.exists() and not args.force:
                raise PipelineError(f"review ledger already exists: {args.reviews} (use --force to replace it)")
            write_json(args.reviews, review_template(queue))
            print(f"wrote private review ledger {args.reviews}")
            return 0
        if args.command == "merge-reviews":
            ledgers = [load_reviews(path) for path in args.inputs]
            merged = merge_review_ledgers(queue, ledgers)
            merged["merged_at"] = utc_now()
            merged["merge_sources"] = [str(path) for path in args.inputs]
            if args.output.exists() and not args.force:
                raise PipelineError(f"merged review ledger already exists: {args.output} (use --force to replace it)")
            write_json(args.output, merged)
            print(f"wrote {len(merged['decisions'])} merged decisions to {args.output}")
            return 0
        if args.command == "probe":
            cache = load_probe_cache(args.probes, queue)
            include_keys = None
            if args.plan:
                plan = load_batch_plan(args.plan, queue)
                batch = find_batch(plan, args.batch_id)
                include_keys = {str(entry["candidate_key"]) for entry in batch["candidates"]}
            result = probe_candidates(
                queue,
                cache,
                args.probes,
                CoverProbeClient(min_interval=args.min_interval, timeout=args.timeout),
                limit=args.limit,
                force=args.force,
                include_keys=include_keys,
            )
            print(json.dumps(result, indent=2, sort_keys=True))
            print(f"probe cache is resumable at {args.probes}; no image binaries were retained")
            return 0
        if args.command == "status":
            probes = load_probe_cache(args.probes, queue)
            reviews = load_reviews(args.reviews) if args.reviews.exists() else review_template(queue)
            include_keys = None
            if args.plan:
                plan = load_batch_plan(args.plan, queue)
                batch = find_batch(plan, args.batch_id)
                include_keys = {str(entry["candidate_key"]) for entry in batch["candidates"]}
            report = pipeline_status(queue, probes, reviews, include_keys=include_keys)
            if args.plan:
                report["batch"] = {
                    "batch_id": args.batch_id,
                    "batch_fingerprint": batch.get("batch_fingerprint"),
                    "plan": str(args.plan),
                }
            print(json.dumps(report, indent=2, sort_keys=True))
            if args.output:
                write_json(args.output, report)
                print(f"wrote private offline status report {args.output}")
            return 0
        if args.command == "publish":
            try:
                output_relative = args.output.resolve().relative_to(Path("docs").resolve())
            except ValueError:
                output_relative = None
            if output_relative is not None and not args.allow_docs_output:
                raise PipelineError("refusing to write under docs/ without --allow-docs-output")
            probes = load_probe_cache(args.probes, queue)
            reviews = load_reviews(args.reviews)
            public = build_public_manifest(queue, probes, reviews)
            write_json(args.output, public, compact=True)
            print(json.dumps(public["summary"], indent=2, sort_keys=True))
            print(f"wrote reviewed-only manifest {args.output}")
            return 0
    except (PipelineError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
