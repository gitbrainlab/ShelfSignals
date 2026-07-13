#!/usr/bin/env python3
"""Extract exact-edition metadata from an Open Library monthly dump.

The Open Library API is intentionally not used for collection-scale work.  This
script streams the official monthly editions dump, joins only on normalized
ISBN/OCLC/LCCN values already present in the Clark catalog, and writes a sparse
manifest.  External claims never overwrite Clark metadata and are always kept
with provider, snapshot, identifier, and match-method provenance.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
import tempfile
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, BinaryIO, Iterable, Mapping, Optional, Sequence


SCHEMA = "shelfsignals-edition-enrichment@1"
VERSION = "1.0.0"
GENERATOR = "scripts/enrich_book_editions.py"
METHOD_VERSION = "openlibrary-dump-exact-identifiers-v1"
DEFAULT_INPUT = Path("docs/data/sekula_index.json")
DEFAULT_OUTPUT = Path("docs/data/book_editions.json")
DEFAULT_DUMP = Path(".cache/openlibrary/ol_dump_editions_latest.txt.gz")
OPEN_LIBRARY_DUMP_URL = "https://openlibrary.org/data/ol_dump_editions_latest.txt.gz"

ISBN_FIELDS = ("isbn_10", "isbn_13")
IDENTIFIER_FIELDS = (*ISBN_FIELDS, "oclc_numbers", "lccn")
FIELD_ARRAY_PATTERNS = {
    field: re.compile(rb'"' + field.encode("ascii") + rb'"\s*:\s*\[([^\]]{0,8192})\]')
    for field in IDENTIFIER_FIELDS
}
QUOTED_VALUE_RE = re.compile(rb'"([^"\\]{1,256})"')
SNAPSHOT_RE = re.compile(r"(20\d{2}-\d{2}-\d{2})")
OL_EDITION_RE = re.compile(r"^/books/OL\d+M$")

MATCH_PRIORITY = {
    "isbn_exact": 4,
    "oclc_lccn_exact": 3,
    "oclc_exact": 2,
    "lccn_exact": 1,
}
RESOLVABLE_FIELDS = (
    "physical_format",
    "physical_dimensions",
    "weight",
    "number_of_pages",
    "pagination",
)


class EnrichmentError(RuntimeError):
    """A safe, user-facing enrichment failure."""


def utc_now() -> str:
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    moment = datetime.fromtimestamp(int(epoch), timezone.utc) if epoch else datetime.now(timezone.utc)
    return moment.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def canonical_json_checksum(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def file_checksum(path: Path, algorithm: str = "sha256") -> str:
    digest = hashlib.new(algorithm)
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(8 * 1024 * 1024), b""):
            digest.update(chunk)
    return f"{algorithm}:{digest.hexdigest()}"


def _isbn_checksum_valid(compact: str) -> bool:
    if len(compact) == 10 and re.fullmatch(r"\d{9}[\dX]", compact):
        return sum((10 - index) * (10 if character == "X" else int(character)) for index, character in enumerate(compact)) % 11 == 0
    if len(compact) == 13 and compact.isdigit():
        return sum(int(character) * (1 if index % 2 == 0 else 3) for index, character in enumerate(compact)) % 10 == 0
    return False


def normalize_isbn(value: Any) -> str:
    compact = re.sub(r"[^0-9X]", "", str(value or "").upper())
    return compact if _isbn_checksum_valid(compact) else ""


def canonical_isbn(value: Any) -> str:
    """Return a valid ISBN-13, converting ISBN-10 when required."""

    normalized = normalize_isbn(value)
    if len(normalized) == 13:
        return normalized
    if len(normalized) != 10:
        return ""
    body = "978" + normalized[:9]
    total = sum(int(character) * (1 if index % 2 == 0 else 3) for index, character in enumerate(body))
    return body + str((-total) % 10)


def normalize_oclc(value: Any) -> str:
    text = str(value or "").strip()
    match = re.search(r"(?i)(?:\(\s*(?:oclc|ocolc)\s*\)|\b(?:oclc|ocolc|ocm|ocn|on))\s*0*(\d{1,12})(?!\d)", text)
    if not match:
        match = re.fullmatch(r"\s*0*(\d{1,12})\s*", text)
    return (match.group(1) or "0") if match else ""


def normalize_lccn(value: Any) -> str:
    text = re.sub(r"(?i)^\s*lccn\s*[:#]?\s*", "", str(value or "")).split("/", 1)[0].strip().lower()
    match = re.fullmatch(r"([a-z]{0,3})\s*(\d{2}|\d{4})\s*-?\s*(\d{1,6})", text)
    if match:
        prefix, year, serial = match.groups()
    else:
        compact = re.sub(r"[^a-z0-9]", "", text)
        compact_match = re.fullmatch(r"([a-z]{0,3})(\d{7,10})", compact)
        if not compact_match:
            return ""
        prefix, digits = compact_match.groups()
        year_length = 4 if len(digits) > 8 else 2
        year, serial = digits[:year_length], digits[year_length:]
    return f"{prefix}{year}{serial.zfill(6)}" if len(serial) <= 6 else ""


def _values(value: Any) -> list[Any]:
    return value if isinstance(value, list) else ([] if value in (None, "") else [value])


def normalized_record_identifiers(record: Mapping[str, Any]) -> dict[str, list[str]]:
    return {
        "isbn": sorted({item for raw in _values(record.get("isbns")) if (item := canonical_isbn(raw))}),
        "oclc": sorted({item for raw in _values(record.get("oclc_numbers")) if (item := normalize_oclc(raw))}),
        "lccn": sorted({item for raw in _values(record.get("lccn")) if (item := normalize_lccn(raw))}),
    }


def raw_line_identifiers(line: bytes) -> dict[str, set[str]]:
    """Extract identifiers cheaply before parsing a matching dump JSON record."""

    raw: dict[str, list[str]] = {field: [] for field in IDENTIFIER_FIELDS}
    for field, pattern in FIELD_ARRAY_PATTERNS.items():
        match = pattern.search(line)
        if match:
            raw[field] = [value.decode("ascii", "ignore") for value in QUOTED_VALUE_RE.findall(match.group(1))]
    return {
        "isbn": {item for field in ISBN_FIELDS for value in raw[field] if (item := canonical_isbn(value))},
        "oclc": {item for value in raw["oclc_numbers"] if (item := normalize_oclc(value))},
        "lccn": {item for value in raw["lccn"] if (item := normalize_lccn(value))},
    }


def _text(value: Any, maximum: int = 240) -> str:
    if isinstance(value, Mapping):
        value = value.get("value")
    clean = re.sub(r"\s+", " ", str(value or "")).strip()
    return clean[:maximum]


def _text_list(value: Any, maximum_items: int = 8, maximum_length: int = 180) -> list[str]:
    result: list[str] = []
    for raw in _values(value):
        clean = _text(raw, maximum_length)
        if clean and clean not in result:
            result.append(clean)
        if len(result) >= maximum_items:
            break
    return result


def _first_text(value: Any, maximum: int = 240) -> str:
    for raw in _values(value):
        clean = _text(raw, maximum)
        if clean:
            return clean
    return ""


def _language_codes(value: Any) -> list[str]:
    result: list[str] = []
    for item in _values(value):
        key = _text(item.get("key") if isinstance(item, Mapping) else item, 80)
        code = key.rsplit("/", 1)[-1].lower()
        if re.fullmatch(r"[a-z]{2,8}", code) and code not in result:
            result.append(code)
    return result[:8]


def _positive_int(value: Any, maximum: int = 100_000) -> Optional[int]:
    try:
        number = int(value)
    except (TypeError, ValueError):
        return None
    return number if 0 < number <= maximum else None


def edition_payload(record: Mapping[str, Any]) -> dict[str, Any]:
    payload: dict[str, Any] = {}
    scalar_fields = {
        "physical_format": 120,
        "physical_dimensions": 160,
        "weight": 80,
        "pagination": 220,
        "edition_name": 180,
        "publish_date": 100,
    }
    for field, maximum in scalar_fields.items():
        value = _first_text(record.get(field), maximum)
        if value:
            payload[field] = value
    pages = _positive_int(record.get("number_of_pages"), 20_000)
    if pages:
        payload["number_of_pages"] = pages
    for field, limit in (
        ("publishers", 6),
        ("lc_classifications", 6),
        ("dewey_decimal_class", 6),
        ("series", 6),
        ("genres", 8),
        ("source_records", 8),
    ):
        values = _text_list(record.get(field), limit)
        if values:
            payload[field] = values
    languages = _language_codes(record.get("languages"))
    if languages:
        payload["languages"] = languages
    covers = sorted({number for raw in _values(record.get("covers")) if (number := _positive_int(raw, 1_000_000_000))})
    if covers:
        payload["cover_ids"] = covers[:8]
    archive_id = _text(record.get("ocaid"), 120)
    if archive_id and re.fullmatch(r"[A-Za-z0-9_.-]+", archive_id):
        payload["internet_archive_id"] = archive_id
    work_ids = []
    for work in _values(record.get("works")):
        key = _text(work.get("key") if isinstance(work, Mapping) else work, 80)
        if re.fullmatch(r"/works/OL\d+W", key) and key not in work_ids:
            work_ids.append(key)
    if work_ids:
        payload["work_ids"] = work_ids[:4]
    return payload


def candidate_record_ids(
    provider_ids: Mapping[str, set[str]],
    reverse: Mapping[str, Mapping[str, set[str]]],
) -> set[str]:
    result: set[str] = set()
    for kind in ("isbn", "oclc", "lccn"):
        for value in provider_ids[kind]:
            result.update(reverse[kind].get(value, set()))
    return result


def classify_match(
    catalog_ids: Mapping[str, Sequence[str]], provider_ids: Mapping[str, set[str]]
) -> Optional[dict[str, Any]]:
    intersections = {
        kind: sorted(set(catalog_ids[kind]).intersection(provider_ids[kind]))
        for kind in ("isbn", "oclc", "lccn")
    }
    # A conflicting ISBN on an OCLC/LCCN-only candidate is not safe edition evidence.
    if catalog_ids["isbn"] and provider_ids["isbn"] and not intersections["isbn"]:
        return None
    if intersections["isbn"]:
        method, confidence = "isbn_exact", 1.0
    elif intersections["oclc"] and intersections["lccn"]:
        method, confidence = "oclc_lccn_exact", 0.98
    elif intersections["oclc"]:
        method, confidence = "oclc_exact", 0.95
    elif intersections["lccn"]:
        method, confidence = "lccn_exact", 0.9
    else:
        return None
    matched = [
        {"type": kind, "value": value}
        for kind in ("isbn", "oclc", "lccn")
        for value in intersections[kind]
    ]
    return {"method": method, "confidence": confidence, "identifiers": matched}


def usefulness(candidate: Mapping[str, Any]) -> int:
    edition = candidate.get("edition") or {}
    score = sum(1 for field in RESOLVABLE_FIELDS if edition.get(field) not in (None, "", [])) * 20
    score += sum(1 for field in ("edition_name", "publishers", "publish_date", "languages", "lc_classifications", "cover_ids", "internet_archive_id") if edition.get(field) not in (None, "", []))
    return score


def candidate_sort_key(candidate: Mapping[str, Any]) -> tuple[Any, ...]:
    match = candidate.get("match") or {}
    return (
        -MATCH_PRIORITY.get(str(match.get("method")), 0),
        -usefulness(candidate),
        str(candidate.get("source_id") or ""),
    )


def deduplicate_candidates(
    candidates: Sequence[Mapping[str, Any]], maximum: Optional[int] = None
) -> tuple[list[dict[str, Any]], int]:
    unique: dict[str, dict[str, Any]] = {}
    for candidate in sorted(candidates, key=candidate_sort_key):
        signature = canonical_json_checksum({"match": candidate.get("match"), "edition": candidate.get("edition")})
        unique.setdefault(signature, dict(candidate))
    ordered = sorted(unique.values(), key=candidate_sort_key)
    selected = ordered if maximum is None else ordered[:maximum]
    return selected, max(0, len(candidates) - len(selected))


def consensus_claim(candidates: Sequence[Mapping[str, Any]], field: str) -> tuple[Optional[dict[str, Any]], bool]:
    exact = [candidate for candidate in candidates if candidate.get("match", {}).get("method") == "isbn_exact"]
    claims = [(candidate, candidate.get("edition", {}).get(field)) for candidate in exact]
    claims = [(candidate, value) for candidate, value in claims if value not in (None, "", [])]
    if not claims:
        return None, False
    canonical = {json.dumps(value, ensure_ascii=False, sort_keys=True) for _, value in claims}
    if len(canonical) != 1:
        return None, True
    candidate, value = claims[0]
    matched_isbns = [item["value"] for item in candidate["match"]["identifiers"] if item["type"] == "isbn"]
    return {
        "value": value,
        "status": "external_edition_stated",
        "provider": "openlibrary",
        "source_id": candidate["source_id"],
        "source_url": candidate["source_url"],
        "match_method": "isbn_exact",
        "matched_isbns": matched_isbns,
    }, False


def iter_dump_lines(handle: BinaryIO) -> Iterable[bytes]:
    for line in handle:
        if line:
            yield line


def extract_candidates(
    records: Sequence[Mapping[str, Any]],
    dump_lines: Iterable[bytes],
    progress_every: int = 2_000_000,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, int]]:
    catalog_ids: dict[str, dict[str, list[str]]] = {}
    reverse: dict[str, dict[str, set[str]]] = {kind: defaultdict(set) for kind in ("isbn", "oclc", "lccn")}
    for record in records:
        record_id = str(record.get("id") or "")
        if not record_id:
            continue
        identifiers = normalized_record_identifiers(record)
        catalog_ids[record_id] = identifiers
        for kind, values in identifiers.items():
            for value in values:
                reverse[kind][value].add(record_id)

    candidates: dict[str, list[dict[str, Any]]] = defaultdict(list)
    stats = {"dump_records_scanned": 0, "dump_records_json_parsed": 0, "unsafe_identifier_conflicts": 0}
    for line in dump_lines:
        stats["dump_records_scanned"] += 1
        if progress_every and stats["dump_records_scanned"] % progress_every == 0:
            print(json.dumps({"progress": stats, "matched_records": len(candidates)}, sort_keys=True), flush=True)
        if not any(token in line for token in (b'"isbn_10"', b'"isbn_13"', b'"oclc_numbers"', b'"lccn"')):
            continue
        provider_ids = raw_line_identifiers(line)
        record_ids = candidate_record_ids(provider_ids, reverse)
        if not record_ids:
            continue
        parts = line.rstrip(b"\n").split(b"\t", 4)
        if len(parts) != 5:
            continue
        try:
            source_id = parts[1].decode("utf-8")
            raw_record = json.loads(parts[4])
        except (UnicodeDecodeError, json.JSONDecodeError):
            continue
        if not OL_EDITION_RE.fullmatch(source_id) or not isinstance(raw_record, Mapping):
            continue
        stats["dump_records_json_parsed"] += 1
        edition = edition_payload(raw_record)
        if not edition:
            continue
        for record_id in record_ids:
            match = classify_match(catalog_ids[record_id], provider_ids)
            if not match:
                if catalog_ids[record_id]["isbn"] and provider_ids["isbn"]:
                    stats["unsafe_identifier_conflicts"] += 1
                continue
            candidates[record_id].append({
                "source_id": source_id.rsplit("/", 1)[-1],
                "source_url": "https://openlibrary.org" + source_id,
                "record_modified": parts[3].decode("utf-8", "replace")[:40],
                "match": match,
                "edition": edition,
            })
    return dict(candidates), stats


def build_manifest(
    records: Sequence[Mapping[str, Any]],
    dump_lines: Iterable[bytes],
    input_path: Path,
    dump_path: Path,
    dump_checksum: str,
    snapshot: str,
) -> dict[str, Any]:
    raw_candidates, stats = extract_candidates(records, dump_lines)
    items: dict[str, Any] = {}
    method_counts: dict[str, int] = defaultdict(int)
    field_counts: dict[str, int] = defaultdict(int)
    field_conflicts: dict[str, int] = defaultdict(int)
    candidates_kept = 0
    candidates_dropped = 0
    for record_id in sorted(raw_candidates):
        all_candidates, _ = deduplicate_candidates(raw_candidates[record_id])
        if not all_candidates:
            continue
        resolved: dict[str, Any] = {}
        for field in RESOLVABLE_FIELDS:
            # Resolve over every unique candidate before applying the browser-payload
            # cap. A conflicting fifth candidate must not be hidden by truncation.
            claim, conflict = consensus_claim(all_candidates, field)
            if claim:
                resolved[field] = claim
                field_counts[field] += 1
            if conflict:
                field_conflicts[field] += 1
        required_source_ids = {claim["source_id"] for claim in resolved.values()}
        required = [candidate for candidate in all_candidates if candidate["source_id"] in required_source_ids]
        candidates = []
        for candidate in [all_candidates[0], *required, *all_candidates]:
            if candidate["source_id"] not in {item["source_id"] for item in candidates}:
                candidates.append(candidate)
            if len(candidates) >= 6:
                break
        dropped = max(0, len(raw_candidates[record_id]) - len(candidates))
        for method in {candidate["match"]["method"] for candidate in candidates}:
            method_counts[method] += 1
        items[record_id] = {
            "status": "resolved",
            "preferred_source_id": candidates[0]["source_id"],
            "resolved": resolved,
            "candidates": candidates,
        }
        candidates_kept += len(candidates)
        candidates_dropped += dropped

    dataset_checksum = "sha256:" + hashlib.sha256(input_path.read_bytes()).hexdigest()
    summary = {
        "catalog_records": len(records),
        "matched_records": len(items),
        "unmatched_records": len(records) - len(items),
        "candidates_kept": candidates_kept,
        "candidates_dropped": candidates_dropped,
        **stats,
        "records_by_match_method": dict(sorted(method_counts.items())),
        "resolved_fields": dict(sorted(field_counts.items())),
        "field_conflicts": dict(sorted(field_conflicts.items())),
    }
    return {
        "schema": SCHEMA,
        "version": VERSION,
        "generated_at": utc_now(),
        "source": {
            "catalog": "Clark Library Catalog",
            "dataset": input_path.name,
            "dataset_sha256": dataset_checksum,
            "record_count": len(records),
            "provider": "Open Library",
            "provider_snapshot": snapshot,
            "provider_dump": dump_path.name,
            "provider_dump_url": (
                f"https://archive.org/download/ol_dump_{snapshot}/ol_dump_editions_{snapshot}.txt.gz"
                if re.fullmatch(r"20\d{2}-\d{2}-\d{2}", snapshot)
                else OPEN_LIBRARY_DUMP_URL
            ),
            "provider_latest_url": OPEN_LIBRARY_DUMP_URL,
            "provider_dump_checksum": dump_checksum,
            "license_url": "https://openlibrary.org/developers/licensing",
            "policy": "Exact normalized identifiers only. External claims describe a provider edition, never the condition or measurements of Clark's individual copy.",
        },
        "methodology": {
            "generator": GENERATOR,
            "method": METHOD_VERSION,
            "precedence": "Clark catalog facts remain authoritative; only conflict-free exact-ISBN claims are exposed as resolved physical-edition fields.",
            "common_crawl": "Not used as an authority. Future crawled claims must retain original URL and WARC provenance and match an exact ISBN in the payload.",
        },
        "summary": summary,
        "items": items,
    }


def infer_snapshot(path: Path) -> str:
    match = SNAPSHOT_RE.search(path.name)
    return match.group(1) if match else "unknown"


def self_test() -> None:
    assert canonical_isbn("0-374-22626-1") == "9780374226268"
    assert canonical_isbn("978-0-374-22626-8") == "9780374226268"
    assert canonical_isbn("978-0-374-22626-2") == ""
    records = [
        {"id": "alma1", "isbns": ["0-374-22626-1"], "oclc_numbers": ["(OCoLC)3223849"], "lccn": ["77011916"]},
        {"id": "alma2", "isbns": [], "oclc_numbers": ["(OCoLC)6103237"], "lccn": ["35024291"]},
        {"id": "alma3", "isbns": ["9780520270947"], "oclc_numbers": ["(OCoLC)999"], "lccn": []},
        {"id": "alma4", "isbns": ["9781847490063"], "oclc_numbers": [], "lccn": []},
    ]
    editions = [
        {
            "key": "/books/OL1M", "isbn_10": ["0374226261"], "oclc_numbers": ["3223849"], "lccn": ["77011916"],
            "physical_format": "Hardcover", "number_of_pages": 207, "publishers": ["Farrar, Straus and Giroux"],
            "source_records": ["marc:oclc:3223849"],
        },
        {
            "key": "/books/OL2M", "oclc_numbers": ["6103237"], "lccn": ["35024291"], "physical_format": "Annual", "pagination": "15 volumes",
        },
        {
            # OCLC collides but the disjoint ISBN must reject this as edition evidence for alma3.
            "key": "/books/OL3M", "isbn_13": ["9783869302560"], "oclc_numbers": ["999"], "physical_format": "Paperback",
        },
        *[
            {
                "key": f"/books/OL{index}M", "isbn_13": ["9781847490063"],
                "physical_format": "Paperback" if index == 8 else "Hardcover", "edition_name": f"Variant {index}",
            }
            for index in range(4, 9)
        ],
    ]
    lines = [
        b"/type/edition\t" + item["key"].encode() + b"\t1\t2026-06-30T00:00:00\t" + json.dumps(item).encode() + b"\n"
        for item in editions
    ]
    with tempfile.TemporaryDirectory() as directory:
        input_path = Path(directory) / "catalog.json"
        dump_path = Path(directory) / "ol_dump_editions_2026-06-30.txt.gz"
        input_path.write_text(json.dumps(records), encoding="utf-8")
        manifest = build_manifest(records, lines, input_path, dump_path, "md5:test", "2026-06-30")
    assert set(manifest["items"]) == {"alma1", "alma2", "alma4"}
    assert manifest["items"]["alma1"]["resolved"]["physical_format"]["value"] == "Hardcover"
    assert manifest["items"]["alma1"]["resolved"]["number_of_pages"]["value"] == 207
    assert manifest["items"]["alma1"]["candidates"][0]["edition"]["source_records"] == ["marc:oclc:3223849"]
    assert manifest["items"]["alma2"]["resolved"] == {}, "OCLC-only data remains evidence but cannot drive geometry"
    assert "physical_format" not in manifest["items"]["alma4"]["resolved"], "a conflict beyond four candidates must remain visible"
    assert manifest["summary"]["field_conflicts"]["physical_format"] == 1
    assert manifest["summary"]["unsafe_identifier_conflicts"] == 1
    print("edition enrichment self-test passed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--dump", type=Path, default=DEFAULT_DUMP)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--snapshot", default="")
    parser.add_argument("--expected-md5", default="", help="Fail unless the compressed dump matches this official MD5.")
    parser.add_argument("--self-test", action="store_true")
    arguments = parser.parse_args()
    if arguments.self_test:
        self_test()
        return 0
    try:
        records = json.loads(arguments.input.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        parser.error(f"could not read catalog input: {error}")
    if not isinstance(records, list):
        parser.error("catalog input must be a JSON array")
    if not arguments.dump.is_file():
        parser.error(f"Open Library dump not found: {arguments.dump}")
    checksum = file_checksum(arguments.dump, "md5")
    if arguments.expected_md5 and checksum != f"md5:{arguments.expected_md5.lower()}":
        parser.error(f"dump checksum mismatch: expected md5:{arguments.expected_md5.lower()}, received {checksum}")
    snapshot = arguments.snapshot or infer_snapshot(arguments.dump)
    try:
        with gzip.open(arguments.dump, "rb") as handle:
            manifest = build_manifest(records, iter_dump_lines(handle), arguments.input, arguments.dump, checksum, snapshot)
    except (OSError, EOFError, gzip.BadGzipFile) as error:
        parser.error(f"could not stream Open Library dump: {error}")
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(manifest, ensure_ascii=False, separators=(",", ":")) + "\n"
    with tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", dir=arguments.output.parent, prefix=f".{arguments.output.name}.", delete=False
    ) as handle:
        handle.write(payload)
        temporary_path = Path(handle.name)
    temporary_path.replace(arguments.output)
    print(json.dumps(manifest["summary"], indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
