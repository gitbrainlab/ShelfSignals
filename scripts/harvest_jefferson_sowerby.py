#!/usr/bin/env python3
"""Harvest and build the factual core of the Sowerby catalogue transcript.

The Thomas Jefferson Foundation (TJF) HTML transcription is copyrighted and
its published terms limit reuse.  This tool therefore keeps both raw HTML and
normalized outputs under the git-ignored research workspace.  The crawl-time
acknowledgement records only that the operator reviewed those terms; it is not
publication permission.

The builder deliberately excludes annotations, notes, bibliographies, and
other editorial prose.  Its output unit is a historical Sowerby catalogue
entry, not a work, edition, volume, physical copy, current holding, or digital
object.  A separate product step must establish publication permission before
copying these outputs into ``docs/``.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
import hashlib
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import sys
import time
from typing import Any, Iterable, Iterator, Mapping, Sequence
import urllib.error
import urllib.parse
import urllib.request


SCRIPT_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = SCRIPT_DIR.parent
DEFAULT_WORK_ROOT = REPOSITORY_ROOT / "research/jefferson/work"
DEFAULT_CACHE_ROOT = DEFAULT_WORK_ROOT / "cache/sowerby_transcription_v2"
DEFAULT_DATA_DIR = DEFAULT_WORK_ROOT / "data"

TRANSCRIPT_BASE = "https://tjlibraries.monticello.org/transcripts/sowerby/"
TRANSCRIPT_TOC = urllib.parse.urljoin(TRANSCRIPT_BASE, "sowerby.html")
TERMS_URL = "https://tjlibraries.monticello.org/about/terms.html"
ROBOTS_URL = "https://tjlibraries.monticello.org/robots.txt"
LOC_ITEM_URL = "https://www.loc.gov/item/52060000/"
LOC_ITEM_JSON = "https://www.loc.gov/item/52060000/?fo=json"

# Confirmed by the transcript's cross-volume navigation and final page.  The
# builder verifies every page, link boundary, and published entry range.
EXPECTED_PAGE_LIMITS = {"I": 554, "II": 429, "III": 478, "IV": 562, "V": 184}
EXPECTED_ENTRY_RANGES = {
    "I": (1, 1237),
    "II": (1238, 2322),
    "III": (2323, 3662),
    "IV": (3663, 4615),
    "V": (4616, 4931),
}
EXPECTED_ENTRY_COUNT = 4931
VOLUMES = tuple(EXPECTED_PAGE_LIMITS)
PAGE_RE = re.compile(r"^(I|II|III|IV|V)_(\d+)\.html$")
BASE_IDENTIFIER_RE = re.compile(r"^\[\s*(\d{1,4})\s*\]$")
SUFFIX_IDENTIFIER_RE = re.compile(r"^\[\s*(\d{1,4})\s*([A-Za-z][A-Za-z0-9.-]*)\s*\]$")
RANGE_IDENTIFIER_RE = re.compile(r"^\[\s*(\d{1,4})\s*[-–—]\s*(\d{1,4})\s*\]$")
SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
ROMAN_VALUES = {"I": 1, "V": 5, "X": 10, "L": 50, "C": 100, "D": 500, "M": 1000}

# The published sequence jumps from [2322] at the end of volume II to [2324]
# at the beginning of volume III.  The same gap is present in both the TJF
# transcription and the official LOC page scans; no bibliographic record is
# invented for [2323].  A conspicuous spine placeholder lets downstream code
# preserve the 1..4931 identifier space without presenting it as a book.
KNOWN_SOURCE_GAP_PLACEHOLDERS: dict[int, dict[str, Any]] = {
    2323: {
        "volume": "III",
        "chapter_number": 24,
        "chapter_roman": "XXIV",
        "chapter_heading": "Politics",
        "adjacent_transcript_pages": [
            urllib.parse.urljoin(TRANSCRIPT_BASE, "II_429.html"),
            urllib.parse.urljoin(TRANSCRIPT_BASE, "III_1.html"),
            urllib.parse.urljoin(TRANSCRIPT_BASE, "III_2.html"),
        ],
        "loc_scan_pages": [
            "https://tile.loc.gov/image-services/iiif/service:rbc:rbc0001:2007:2007jeffcat2:04432429/full/pct:100/0/default.jpg",
            "https://tile.loc.gov/image-services/iiif/service:rbc:rbc0001:2007:2007jeffcat3:00103002/full/pct:100/0/default.jpg",
        ],
        "evidence": (
            "Volume II ends with printed identifier [2322], while the first bibliographic entry in volume III "
            "ends with printed identifier [2324]. No [2323] entry was located in the complete five-volume "
            "HTML snapshot. This row preserves the unresolved identifier gap and is not a bibliographic entry."
        ),
    },
    4707: {
        "volume": "V",
        "chapter_number": 42,
        "chapter_roman": "XLII",
        "chapter_heading": "Criticism—Bibliography",
        "adjacent_transcript_pages": [
            urllib.parse.urljoin(TRANSCRIPT_BASE, "V_43.html"),
            urllib.parse.urljoin(TRANSCRIPT_BASE, "V_44.html"),
        ],
        "loc_scan_pages": [
            "https://tile.loc.gov/image-services/iiif/service:rbc:rbc0001:2007:2007jeffcat5:00555043/full/pct:100/0/default.jpg",
            "https://tile.loc.gov/image-services/iiif/service:rbc:rbc0001:2007:2007jeffcat5:00565044/full/pct:100/0/default.jpg",
        ],
        "evidence": (
            "Printed volume V and the HTML transcription jump from identifier [4706] on page 43 to [4709] "
            "on page 44. No [4707] entry was located in the complete five-volume snapshot. This row preserves "
            "the unresolved identifier gap and is not a bibliographic entry."
        ),
    },
    4708: {
        "volume": "V",
        "chapter_number": 42,
        "chapter_roman": "XLII",
        "chapter_heading": "Criticism—Bibliography",
        "adjacent_transcript_pages": [
            urllib.parse.urljoin(TRANSCRIPT_BASE, "V_43.html"),
            urllib.parse.urljoin(TRANSCRIPT_BASE, "V_44.html"),
        ],
        "loc_scan_pages": [
            "https://tile.loc.gov/image-services/iiif/service:rbc:rbc0001:2007:2007jeffcat5:00555043/full/pct:100/0/default.jpg",
            "https://tile.loc.gov/image-services/iiif/service:rbc:rbc0001:2007:2007jeffcat5:00565044/full/pct:100/0/default.jpg",
        ],
        "evidence": (
            "Printed volume V and the HTML transcription jump from identifier [4706] on page 43 to [4709] "
            "on page 44. No [4708] entry was located in the complete five-volume snapshot. This row preserves "
            "the unresolved identifier gap and is not a bibliographic entry."
        ),
    },
}

# These four HTML pages contain large aggregate blocks that repeat entries
# from ordinary transcript pages; two blocks also place future identifiers
# ahead of their normal page sequence. They are retained as evidence, but
# repeated groups are reconciled by explicit BIDNo and their source container
# identity. Unique groups from an aggregate page are reinserted by their
# explicit base number and reported in validation.
KNOWN_AGGREGATE_SOURCE_PAGES = {
    "III_307.html",
    "III_308.html",
    "III_356.html",
    "III_357.html",
    "IV_335.html",
}

# The transcription itself prints an editorial ``i.e. 3545`` immediately
# after this erroneous BIDNo. Store only the factual correction, not the
# surrounding editorial prose.
KNOWN_EXPLICIT_BID_CORRECTIONS = {
    ("III_438.html", "[3345]"): 3545,
    ("V_125.html", "[4856]"): 4859,
}

PUBLIC_OUTPUTS = {
    "entries": "sowerby_entries.jsonl",
    "exceptions": "sowerby_entry_exceptions.jsonl",
    "source_pages": "sowerby_source_pages.jsonl",
    "validation": "sowerby_validation.json",
    "manifest": "sowerby_manifest.json",
}

# Content from these classes can be parsed to delimit records, but is never
# emitted in the factual-core output.
EXCLUDED_EDITORIAL_CLASSES = {
    "AltTitleLoc",
    "bibl",
    "listBibl",
    "note",
    "quote",
    "quotePara",
    "attribution",
}
ENTRY_CONTAINER_CLASSES = {"CatalogEntry", "SubCatalogEntry"}


class SowerbyError(RuntimeError):
    """Raised when source or output evidence fails closed."""


def normalized_space(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def stable_unique(values: Iterable[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = normalized_space(value)
        if text and text not in seen:
            result.append(text)
            seen.add(text)
    return result


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def jsonl_bytes(values: Iterable[Mapping[str, Any]]) -> bytes:
    return b"".join(json_bytes(value) for value in values)


def sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return f"sha256:{digest.hexdigest()}"


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def validate_timestamp(value: str) -> str:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as error:
        raise SowerbyError("--generated-at must be an ISO-8601 timestamp") from error
    if parsed.tzinfo is None:
        raise SowerbyError("--generated-at must include a timezone")
    return parsed.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def atomic_write(path: Path, body: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_bytes(body)
    os.replace(temporary, path)


def atomic_write_json(path: Path, value: Any) -> None:
    atomic_write(path, json_bytes(value))


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise SowerbyError(f"Unable to read {path}: {error}") from error


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
        return normalized_space(
            " ".join(child.text() if isinstance(child, HtmlNode) else str(child) for child in self.children)
        )

    def descendants(self) -> Iterator["HtmlNode"]:
        for child in self.children:
            if isinstance(child, HtmlNode):
                yield child
                yield from child.descendants()


class HtmlTreeParser(HTMLParser):
    VOID_TAGS = {
        "area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "param", "source", "track", "wbr"
    }

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
        lowered = tag.lower()
        for index in range(len(self.stack) - 1, 0, -1):
            if self.stack[index].tag == lowered:
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


def _structured_values_in_children(children: Sequence[Any]) -> bool:
    for child in children:
        if not isinstance(child, HtmlNode):
            continue
        if child.classes & ENTRY_CONTAINER_CLASSES:
            continue
        if child.classes:
            return True
        if _structured_values_in_children(child.children):
            return True
    return False


def _entry_segments(
    entry: HtmlNode,
    parent_entry_html_id: str,
) -> Iterator[tuple[str, HtmlNode, str, list[Any], bool]]:
    """Split malformed/nested entry markup into document-ordered fragments.

    Some pages place a BIDNo after a nested ``SubCatalogEntry`` even though it
    terminates that nested record.  Emitting the outer container as one event
    would move the BIDNo ahead of its child.  Segmenting direct children around
    nested entries preserves the source order without guessing relationships.
    """

    direct_children: list[Any] = []
    identity_emitted = False
    own_html_id = normalized_space(entry.attrs.get("id", ""))

    def flush() -> Iterator[tuple[str, HtmlNode, str, list[Any], bool]]:
        nonlocal direct_children, identity_emitted
        if direct_children and _structured_values_in_children(direct_children):
            include_identity = not identity_emitted
            yield ("entry", entry, parent_entry_html_id, direct_children, include_identity)
            identity_emitted = True
        direct_children = []

    for child in entry.children:
        if isinstance(child, HtmlNode) and child.classes & ENTRY_CONTAINER_CLASSES:
            yield from flush()
            nested_parent = own_html_id or parent_entry_html_id
            yield from _entry_segments(child, nested_parent)
        else:
            direct_children.append(child)
    yield from flush()
    if not identity_emitted and own_html_id and not any(
        isinstance(child, HtmlNode) or normalized_space(child) for child in entry.children
    ):
        # A small number of pages use an empty, identified SubCatalogEntry as
        # the start marker for content continued on the following HTML page.
        yield ("entry", entry, parent_entry_html_id, [], True)


def ordered_structural_nodes(
    root: HtmlNode,
    parent_entry_html_id: str = "",
) -> Iterator[tuple[str, HtmlNode, str, list[Any] | None, bool]]:
    """Yield chapter headings and entry fragments in document order."""

    for child in root.children:
        if not isinstance(child, HtmlNode):
            continue
        if child.classes & ENTRY_CONTAINER_CLASSES:
            yield from _entry_segments(child, parent_entry_html_id)
            continue
        if child.classes & {"ChapterTitle", "head2"}:
            yield ("heading", child, parent_entry_html_id, None, False)
        yield from ordered_structural_nodes(child, parent_entry_html_id)


def roman_to_int(value: str) -> int | None:
    value = value.strip().upper()
    if not value or any(character not in ROMAN_VALUES for character in value):
        return None
    total = 0
    previous = 0
    for character in reversed(value):
        current = ROMAN_VALUES[character]
        total += -current if current < previous else current
        previous = max(previous, current)
    return total


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


def class_values(children: Sequence[Any]) -> dict[str, list[str]]:
    values: dict[str, list[str]] = defaultdict(list)

    def eligible_descendants(node: HtmlNode) -> Iterator[HtmlNode]:
        for child in node.children:
            if not isinstance(child, HtmlNode):
                continue
            if child.classes & ENTRY_CONTAINER_CLASSES:
                continue
            yield child
            yield from eligible_descendants(child)

    synthetic_root = HtmlNode("segment", {}, list(children))
    for node in eligible_descendants(synthetic_root):
        text = node.text()
        for class_name in node.classes:
            if text and text not in values[class_name]:
                values[class_name].append(text)
    return dict(values)


def first(values: Mapping[str, Sequence[str]], key: str) -> str:
    return values.get(key, [""])[0] if values.get(key) else ""


def parse_entry_fragment(
    node: HtmlNode,
    *,
    volume: str,
    page: int,
    parent_entry_html_id: str = "",
    children: Sequence[Any] | None = None,
    include_identity: bool = True,
) -> dict[str, Any]:
    segment_children = node.children if children is None else children
    values = class_values(segment_children)
    identifiers = stable_unique(values.get("BIDNo", []))
    sequence = first(values, "SeqNo")
    return {
        "html_id": normalized_space(node.attrs.get("id", "")) if include_identity else "",
        "container_html_id": normalized_space(node.attrs.get("id", "")),
        "parent_entry_html_id": parent_entry_html_id,
        "container_kind": "SubCatalogEntry" if "SubCatalogEntry" in node.classes else "CatalogEntry",
        "identifier_values": identifiers,
        "sequence_number": sequence,
        "short_titles": stable_unique(values.get("ShortTitle", [])),
        "authors": stable_unique(values.get("Author", [])),
        "bibliographic_titles_imprints": stable_unique(values.get("LongTitle", [])),
        "catalog_call_numbers": stable_unique(values.get("CallNo", [])),
        "publication_places": stable_unique(values.get("pubPlace", [])),
        "publishers": stable_unique(values.get("publisher", [])),
        "publication_dates": stable_unique(values.get("pubDate", [])),
        "formats_or_sizes": stable_unique(values.get("size", [])),
        "edition_spans": stable_unique(values.get("edition", [])),
        "language_spans": stable_unique(
            value
            for key in ("language", "Language", "lang", "languageStmt")
            for value in values.get(key, [])
        ),
        "all_class_names": sorted(values),
        "excluded_editorial_classes_present": sorted(EXCLUDED_EDITORIAL_CLASSES.intersection(values)),
        # Used only to prove exact duplicated source groups. The underlying
        # text includes editorial material and is deliberately never emitted.
        "_source_segment_text": HtmlNode("segment", {}, list(segment_children)).text(),
        "volume": volume,
        "page": page,
        "source_url": urllib.parse.urljoin(TRANSCRIPT_BASE, f"{volume}_{page}.html"),
    }


def parse_page(raw: bytes, *, volume: str, page: int) -> dict[str, Any]:
    expected_label = f"Volume {volume} : page {page}"
    text = raw.decode("utf-8", errors="replace")
    if "Sowerby Catalogue" not in text[:1000] or expected_label not in normalized_space(text):
        raise SowerbyError(f"Unexpected transcript body for {volume}_{page}.html")
    tree = parse_html_tree(raw)
    events: list[dict[str, Any]] = []
    pending_chapter: dict[str, Any] | None = None
    for event_kind, node, parent_entry_html_id, segment_children, include_identity in ordered_structural_nodes(tree):
        if event_kind == "heading":
            if "ChapterTitle" in node.classes:
                match = re.search(r"Chapter\s+([IVXLCDM]+)", node.text(), re.IGNORECASE)
                if not match:
                    # Volume IV includes a one-page "Fine Arts" faculty
                    # divider in the same presentation class as true chapter
                    # headings. It establishes no entry-level chapter state.
                    if node.text() == "Fine Arts":
                        pending_chapter = None
                        continue
                    raise SowerbyError(f"Unparseable chapter heading on {volume}_{page}.html")
                roman = match.group(1).upper()
                pending_chapter = {
                    "type": "chapter",
                    "chapter_roman": roman,
                    "chapter_number": roman_to_int(roman),
                    "chapter_heading": "",
                }
                events.append(pending_chapter)
                continue
            if "head2" in node.classes and pending_chapter is not None and not pending_chapter["chapter_heading"]:
                pending_chapter["chapter_heading"] = node.text()
            continue
        pending_chapter = None
        assert segment_children is not None
        events.append({
            "type": "fragment",
            "fragment": parse_entry_fragment(
                node,
                volume=volume,
                page=page,
                parent_entry_html_id=parent_entry_html_id,
                children=segment_children,
                include_identity=include_identity,
            ),
        })

    linked_pages: set[tuple[str, int]] = set()
    for node in tree.descendants():
        if node.tag != "a":
            continue
        match = PAGE_RE.match(Path(urllib.parse.urlparse(node.attrs.get("href", "")).path).name)
        if match:
            linked_pages.add((match.group(1), int(match.group(2))))
    return {"events": events, "linked_pages": sorted(linked_pages)}


def _merge_field(fragments: Sequence[Mapping[str, Any]], field_name: str) -> list[str]:
    return stable_unique(value for fragment in fragments for value in fragment.get(field_name, []))


def _entry_from_fragments(
    fragments: Sequence[Mapping[str, Any]],
    chapter: Mapping[str, Any],
    identifier_raw: str,
    *,
    inferred_base_number: int | None = None,
) -> tuple[dict[str, Any], bool]:
    base_match = BASE_IDENTIFIER_RE.fullmatch(identifier_raw) if identifier_raw else None
    suffix_match = SUFFIX_IDENTIFIER_RE.fullmatch(identifier_raw) if identifier_raw else None
    if inferred_base_number is not None:
        identifier = str(inferred_base_number)
        base_number = inferred_base_number
        suffix = ""
        is_base = True
        identifier_kind = "base_integer_inferred_from_sequence_gap"
        identifier_evidence = "No BIDNo span in source HTML; assigned only because one ordered record exactly fills a bounded gap between explicit base integers."
    elif not base_match and not suffix_match:
        identifier = identifier_raw
        base_number = None
        suffix = ""
        is_base = False
        identifier_kind = "unparsed"
        identifier_evidence = "Unparsed BIDNo span in source HTML."
    else:
        match = base_match or suffix_match
        assert match is not None
        base_number = int(match.group(1))
        suffix = match.group(2).lower() if suffix_match else ""
        identifier = f"{base_number}{suffix}"
        is_base = not suffix
        identifier_kind = "base_integer" if is_base else "suffixed"
        identifier_evidence = "Explicit BIDNo span in source HTML."
    sequences = stable_unique(fragment.get("sequence_number", "") for fragment in fragments)
    source_pages = stable_unique(fragment["source_url"] for fragment in fragments)
    source_page_labels = [f"{fragment['volume']}:{fragment['page']}" for fragment in fragments]
    source_html_ids = stable_unique(fragment.get("html_id", "") for fragment in fragments)
    source_container_html_ids = stable_unique(fragment.get("container_html_id", "") for fragment in fragments)
    parent_source_html_ids = stable_unique(fragment.get("parent_entry_html_id", "") for fragment in fragments)
    container_kinds = stable_unique(fragment.get("container_kind", "") for fragment in fragments)
    record = {
        "schema": "shelfsignals-jefferson-sowerby-entry@1",
        "id": f"jefferson-sowerby-{identifier}",
        "entity_type": "sowerby_entry",
        "sowerby_identifier": identifier,
        "sowerby_number": base_number,
        "identifier_kind": identifier_kind,
        "identifier_evidence": identifier_evidence,
        "source_identifier_raw": identifier_raw,
        "suffix": suffix,
        "historical_order": base_number if is_base else None,
        "catalogue_volume": fragments[0]["volume"],
        "faculty": faculty_for_chapter(chapter.get("chapter_number")),
        "chapter_number": chapter.get("chapter_number"),
        "chapter_roman": chapter.get("chapter_roman", ""),
        "chapter_heading": chapter.get("chapter_heading", ""),
        "chapter_sequence": sequences[0] if len(sequences) == 1 else "",
        "chapter_sequence_values": sequences,
        "sequence_marker": "J" if len(sequences) == 1 and sequences[0].upper().startswith("J.") else "",
        "short_title_spans": _merge_field(fragments, "short_titles"),
        "authors": _merge_field(fragments, "authors"),
        "bibliographic_title_imprint_spans": _merge_field(fragments, "bibliographic_titles_imprints"),
        "imprint": {
            "places": _merge_field(fragments, "publication_places"),
            "publishers": _merge_field(fragments, "publishers"),
            "dates": _merge_field(fragments, "publication_dates"),
        },
        "language_spans": _merge_field(fragments, "language_spans"),
        "edition_spans": _merge_field(fragments, "edition_spans"),
        "formats_or_sizes": _merge_field(fragments, "formats_or_sizes"),
        "sowerby_catalog_call_numbers": _merge_field(fragments, "catalog_call_numbers"),
        "source": {
            "authority": "Thomas Jefferson Foundation",
            "service": "Thomas Jefferson's Libraries Sowerby HTML transcription",
            "pages": source_pages,
            "page_labels": stable_unique(source_page_labels),
            "source_html_ids": source_html_ids,
            "source_container_html_ids": source_container_html_ids,
            "parent_source_html_ids": parent_source_html_ids,
            "container_kinds": container_kinds,
            "terms": TERMS_URL,
            "loc_scan_item": LOC_ITEM_URL,
        },
        "unit_statement": "Historical Sowerby catalogue entry; not a work, edition, volume, physical copy, current holding, or digital object.",
        "call_number_scope": "Call number transcribed from the Sowerby catalogue; not asserted to be a current LOC holding call number.",
    }
    return record, is_base


def _source_gap_placeholder(number: int, evidence: Mapping[str, Any]) -> dict[str, Any]:
    """Create a non-bibliographic spine node for an independently verified gap."""
    chapter_number = int(evidence["chapter_number"])
    adjacent_pages = list(evidence["adjacent_transcript_pages"])
    page_labels = [
        Path(urllib.parse.urlparse(url).path).stem.replace("_", ":", 1)
        for url in adjacent_pages
    ]
    return {
        "schema": "shelfsignals-jefferson-sowerby-gap-placeholder@1",
        "id": f"jefferson-sowerby-{number}",
        "entity_type": "sowerby_entry_gap_placeholder",
        "sowerby_identifier": str(number),
        "sowerby_number": number,
        "identifier_kind": "base_integer_source_gap_placeholder",
        "identifier_evidence": str(evidence["evidence"]),
        "source_identifier_raw": "",
        "suffix": "",
        "historical_order": number,
        "catalogue_volume": str(evidence["volume"]),
        "faculty": faculty_for_chapter(chapter_number),
        "chapter_number": chapter_number,
        "chapter_roman": str(evidence["chapter_roman"]),
        "chapter_heading": str(evidence["chapter_heading"]),
        "chapter_sequence": "",
        "chapter_sequence_values": [],
        "sequence_marker": "",
        "short_title_spans": [],
        "authors": [],
        "bibliographic_title_imprint_spans": [],
        "imprint": {"places": [], "publishers": [], "dates": []},
        "language_spans": [],
        "edition_spans": [],
        "formats_or_sizes": [],
        "sowerby_catalog_call_numbers": [],
        "source_record_status": "not_located_in_complete_transcript_or_adjacent_printed_scans",
        "source": {
            "authority": "Library of Congress and Thomas Jefferson Foundation",
            "service": "Cross-source audit of the Sowerby identifier sequence",
            "pages": adjacent_pages,
            "page_labels": page_labels,
            "source_html_ids": [],
            "source_container_html_ids": [],
            "parent_source_html_ids": [],
            "container_kinds": [],
            "loc_scan_pages": list(evidence["loc_scan_pages"]),
            "terms": TERMS_URL,
            "loc_scan_item": LOC_ITEM_URL,
        },
        "unit_statement": (
            "Unresolved Sowerby base-number placeholder; not a catalogued book, work, edition, volume, "
            "physical copy, current holding, or digital object."
        ),
        "call_number_scope": "No Sowerby catalogue call number is asserted for this unresolved identifier gap.",
    }


def page_paths(page_dir: Path, page_limits: Mapping[str, int] = EXPECTED_PAGE_LIMITS) -> list[Path]:
    return [page_dir / f"{volume}_{page}.html" for volume, limit in page_limits.items() for page in range(1, limit + 1)]


def compile_page_directory(
    page_dir: Path,
    *,
    page_limits: Mapping[str, int] = EXPECTED_PAGE_LIMITS,
    expected_entry_ranges: Mapping[str, tuple[int, int]] = EXPECTED_ENTRY_RANGES,
    expected_entry_count: int = EXPECTED_ENTRY_COUNT,
    expected_chapter_numbers: Sequence[int] = tuple(range(1, 45)),
    known_source_gap_placeholders: Mapping[int, Mapping[str, Any]] = KNOWN_SOURCE_GAP_PLACEHOLDERS,
    require_sidecars: bool = True,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], dict[str, Any], list[dict[str, Any]]]:
    expected_paths = page_paths(page_dir, page_limits)
    expected_first_number = min(start for start, _ in expected_entry_ranges.values())
    expected_last_number = expected_first_number + expected_entry_count - 1
    missing = [path.name for path in expected_paths if not path.is_file()]
    if missing:
        raise SowerbyError(f"Transcript snapshot is missing pages: {missing[:10]}")
    expected_names = {path.name for path in expected_paths}
    unexpected = sorted(
        path.name for path in page_dir.glob("*.html") if PAGE_RE.match(path.name) and path.name not in expected_names
    )
    if unexpected:
        raise SowerbyError(f"Transcript snapshot has unexpected pages: {unexpected[:10]}")

    source_pages: list[dict[str, Any]] = []
    open_fragments: list[dict[str, Any]] = []
    open_chapter: dict[str, Any] | None = None
    assembled_groups: list[dict[str, Any]] = []
    current_chapter: dict[str, dict[str, Any]] = {volume: {} for volume in page_limits}
    page_hash_payload = bytearray()
    fragment_count = 0
    excluded_class_counts: Counter[str] = Counter()
    source_class_counts: Counter[str] = Counter()
    observed_chapters: dict[int, dict[str, Any]] = {}

    def close_open_group() -> None:
        nonlocal open_fragments, open_chapter
        if not open_fragments:
            return
        identifiers = stable_unique(
            value for open_fragment in open_fragments for value in open_fragment["identifier_values"]
        )
        if len(identifiers) > 1:
            last = open_fragments[-1]
            raise SowerbyError(
                f"Entry has multiple Sowerby identifiers near {last['volume']}_{last['page']}.html: {identifiers}"
            )
        assert open_chapter is not None
        assembled_groups.append({
            "fragments": open_fragments,
            "chapter": open_chapter,
            "identifier_raw": identifiers[0] if identifiers else "",
        })
        open_fragments = []
        open_chapter = None

    for path in expected_paths:
        match = PAGE_RE.match(path.name)
        assert match
        volume, page_text = match.groups()
        page = int(page_text)
        body = path.read_bytes()
        body_hash = sha256_bytes(body)
        sidecar_path = path.with_suffix(".meta.json")
        if require_sidecars:
            if not sidecar_path.is_file():
                raise SowerbyError(f"Missing retrieval sidecar for {path.name}")
            sidecar = load_json(sidecar_path)
            if sidecar.get("sha256") != body_hash or sidecar.get("bytes") != len(body):
                raise SowerbyError(f"Retrieval sidecar mismatch for {path.name}")
            expected_url = urllib.parse.urljoin(TRANSCRIPT_BASE, path.name)
            if sidecar.get("request_url") != expected_url:
                raise SowerbyError(f"Retrieval URL mismatch for {path.name}")
        parsed = parse_page(body, volume=volume, page=page)
        forward = sorted(number for linked_volume, number in parsed["linked_pages"] if linked_volume == volume and number > page)
        if page < page_limits[volume] and (not forward or forward[0] != page + 1):
            raise SowerbyError(f"Transcript navigation does not advance from {path.name} to page {page + 1}")
        if page == page_limits[volume] and forward:
            raise SowerbyError(f"Transcript has an unexpected same-volume page after {path.name}")
        source_pages.append({
            "volume": volume,
            "page": page,
            "url": urllib.parse.urljoin(TRANSCRIPT_BASE, path.name),
            "bytes": len(body),
            "sha256": body_hash,
        })
        page_hash_payload.extend(f"{volume}:{page}:{body_hash}\n".encode("ascii"))

        for event in parsed["events"]:
            if event["type"] == "chapter":
                if open_fragments:
                    close_open_group()
                chapter = {
                    "chapter_roman": event["chapter_roman"],
                    "chapter_number": event["chapter_number"],
                    "chapter_heading": event["chapter_heading"],
                }
                if chapter["chapter_number"] is None:
                    raise SowerbyError(f"Invalid chapter number on {path.name}")
                current_chapter[volume] = chapter
                observed_chapters[chapter["chapter_number"]] = chapter | {"volume": volume, "page": page}
                continue

            fragment = event["fragment"]
            fragment_count += 1
            source_class_counts.update(fragment["all_class_names"])
            excluded_class_counts.update(fragment["excluded_editorial_classes_present"])
            open_html_ids = {
                value
                for open_fragment in open_fragments
                for value in (
                    open_fragment.get("html_id", ""),
                    open_fragment.get("container_html_id", ""),
                    open_fragment.get("parent_entry_html_id", ""),
                )
                if value
            }
            nested_continuation = bool(
                fragment.get("parent_entry_html_id")
                and fragment["parent_entry_html_id"] in open_html_ids
            )
            starts_entry = bool(fragment["html_id"] or fragment["sequence_number"]) and not nested_continuation
            if open_fragments and starts_entry:
                close_open_group()
            if not open_fragments:
                if not starts_entry:
                    raise SowerbyError(f"Orphan continuation fragment at {path.name}")
                if not current_chapter[volume]:
                    raise SowerbyError(f"Entry begins before a chapter is established at {path.name}")
                open_chapter = dict(current_chapter[volume])
            open_fragments.append(fragment)
            identifiers = stable_unique(
                value for open_fragment in open_fragments for value in open_fragment["identifier_values"]
            )
            if identifiers:
                close_open_group()

    if open_fragments:
        close_open_group()

    # A small, audited set of malformed pages contains aggregate copies of
    # earlier or later entries. Defer groups from those pages until their
    # ordinary-page occurrence is seen. Reconcile only explicit identifiers;
    # anonymous aggregate fragments cannot create books or fill gaps.
    repeated_source_groups: list[dict[str, Any]] = []
    ignored_aggregate_unlabeled_groups: list[dict[str, Any]] = []
    unique_aggregate_groups: list[dict[str, Any]] = []
    unique_groups: list[dict[str, Any]] = []
    groups_by_source_identity: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    groups_by_identifier: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}
    deferred_aggregate_groups: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}

    def group_audit(group: Mapping[str, Any]) -> dict[str, Any]:
        fragments = group["fragments"]
        content_hash = sha256_bytes(
            normalized_space(" ".join(fragment["_source_segment_text"] for fragment in fragments)).encode("utf-8")
        )
        factual_signature_payload = {
            "identifier_raw": group["identifier_raw"],
            "chapter_number": group["chapter"].get("chapter_number"),
            "container_html_ids": stable_unique(
                fragment.get("container_html_id", "") for fragment in fragments
            ),
            "sequence_numbers": stable_unique(fragment.get("sequence_number", "") for fragment in fragments),
            "short_titles": _merge_field(fragments, "short_titles"),
            "authors": _merge_field(fragments, "authors"),
            "bibliographic_titles_imprints": _merge_field(fragments, "bibliographic_titles_imprints"),
            "catalog_call_numbers": _merge_field(fragments, "catalog_call_numbers"),
            "publication_places": _merge_field(fragments, "publication_places"),
            "publishers": _merge_field(fragments, "publishers"),
            "publication_dates": _merge_field(fragments, "publication_dates"),
            "formats_or_sizes": _merge_field(fragments, "formats_or_sizes"),
            "edition_spans": _merge_field(fragments, "edition_spans"),
            "language_spans": _merge_field(fragments, "language_spans"),
        }
        identifier_owner_ids = stable_unique(
            fragment.get("container_html_id", "")
            for fragment in fragments
            if group["identifier_raw"] in fragment.get("identifier_values", [])
        )
        source_identity = ""
        if group["identifier_raw"] and identifier_owner_ids:
            source_identity = sha256_bytes(json_bytes({
                "identifier_raw": group["identifier_raw"],
                "identifier_owner_html_ids": identifier_owner_ids,
            }))
        page_names = stable_unique(
            f"{fragment['volume']}_{fragment['page']}.html" for fragment in fragments
        )
        return {
            "complete_source_content_sha256": content_hash,
            "factual_core_sha256": sha256_bytes(json_bytes(factual_signature_payload)),
            "identifier_owner_html_ids": identifier_owner_ids,
            "source_identity": source_identity,
            "pages": stable_unique(fragment["source_url"] for fragment in fragments),
            "page_names": page_names,
            "is_known_aggregate": any(page in KNOWN_AGGREGATE_SOURCE_PAGES for page in page_names),
        }

    def merge_repeated_group(
        canonical: dict[str, Any],
        canonical_audit: Mapping[str, Any],
        repeated: dict[str, Any],
        repeated_audit: Mapping[str, Any],
    ) -> None:
        repeated_source_groups.append({
            "identifier_raw": repeated["identifier_raw"],
            "canonical_source_content_sha256": canonical_audit["complete_source_content_sha256"],
            "repeated_source_content_sha256": repeated_audit["complete_source_content_sha256"],
            "complete_source_text_matches": (
                canonical_audit["complete_source_content_sha256"]
                == repeated_audit["complete_source_content_sha256"]
            ),
            "factual_core_matches": canonical_audit["factual_core_sha256"] == repeated_audit["factual_core_sha256"],
            "canonical_pages": canonical_audit["pages"],
            "repeated_pages": repeated_audit["pages"],
            "identifier_owner_html_ids": stable_unique(
                [*canonical_audit["identifier_owner_html_ids"], *repeated_audit["identifier_owner_html_ids"]]
            ),
        })
        canonical["fragments"].extend(repeated["fragments"])

    for group in assembled_groups:
        audit = group_audit(group)
        identifier_raw = group["identifier_raw"]
        if audit["is_known_aggregate"]:
            if not identifier_raw:
                ignored_aggregate_unlabeled_groups.append({
                    "source_content_sha256": audit["complete_source_content_sha256"],
                    "pages": audit["pages"],
                })
                continue
            prior_bundle = groups_by_identifier.get(identifier_raw)
            if prior_bundle is not None:
                prior, prior_audit = prior_bundle
                merge_repeated_group(prior, prior_audit, group, audit)
                continue
            deferred_bundle = deferred_aggregate_groups.get(identifier_raw)
            if deferred_bundle is not None:
                prior, prior_audit = deferred_bundle
                merge_repeated_group(prior, prior_audit, group, audit)
                continue
            deferred_aggregate_groups[identifier_raw] = (group, audit)
            continue

        deferred_bundle = deferred_aggregate_groups.pop(identifier_raw, None) if identifier_raw else None
        if deferred_bundle is not None:
            deferred, deferred_audit = deferred_bundle
            merge_repeated_group(group, audit, deferred, deferred_audit)

        prior_bundle = (
            groups_by_source_identity.get(str(audit["source_identity"]))
            if audit["source_identity"]
            else None
        )
        if prior_bundle is not None:
            prior, prior_audit = prior_bundle
            merge_repeated_group(prior, prior_audit, group, audit)
            continue

        unique_groups.append(group)
        if audit["source_identity"]:
            groups_by_source_identity[str(audit["source_identity"])] = (group, audit)
        if identifier_raw:
            groups_by_identifier[identifier_raw] = (group, audit)

    def explicit_group_start(group: Mapping[str, Any]) -> int | None:
        identifier_raw = str(group["identifier_raw"])
        base_match = BASE_IDENTIFIER_RE.fullmatch(identifier_raw)
        if base_match:
            return int(base_match.group(1))
        range_match = RANGE_IDENTIFIER_RE.fullmatch(identifier_raw)
        if range_match:
            return int(range_match.group(1))
        return None

    # The only unmatched aggregate groups must carry explicit base/range
    # identifiers. Insert them into the explicit numeric spine and report each
    # recovery; never use their position to infer an unlabeled entry.
    deferred_with_numbers: list[tuple[int, dict[str, Any], dict[str, Any]]] = []
    for identifier_raw, (group, audit) in deferred_aggregate_groups.items():
        number = explicit_group_start(group)
        if number is None:
            raise SowerbyError(f"Unresolved aggregate source group has no base position: {identifier_raw}")
        deferred_with_numbers.append((number, group, audit))
    for number, group, audit in sorted(deferred_with_numbers):
        insertion_index = next(
            (
                index
                for index, existing in enumerate(unique_groups)
                if explicit_group_start(existing) is not None
                and int(explicit_group_start(existing)) > number
            ),
            len(unique_groups),
        )
        unique_groups.insert(insertion_index, group)
        unique_aggregate_groups.append({
            "identifier_raw": group["identifier_raw"],
            "source_content_sha256": audit["complete_source_content_sha256"],
            "pages": audit["pages"],
        })
    assembled_groups = unique_groups

    # Resolve source-HTML omissions only when an unlabeled record fills an
    # exact monotonic gap between explicit base identifiers.  These rows remain
    # prominently labeled as inferred and should be checked against LOC scans.
    entries: list[dict[str, Any]] = []
    exceptions: list[dict[str, Any]] = []
    pending_unlabeled: list[dict[str, Any]] = []
    inferred_numbers: list[int] = []
    gap_inferred_with_unnumbered_neighbors: list[int] = []
    range_resolved_numbers: list[int] = []
    range_shared_fragment_numbers: list[int] = []
    corrected_out_of_order_identifiers: list[dict[str, Any]] = []
    source_gap_placeholder_numbers: list[int] = []
    next_expected_number = expected_first_number

    def emit_unnumbered_groups(groups: Sequence[dict[str, Any]]) -> None:
        for group in groups:
            record, is_base = _entry_from_fragments(group["fragments"], group["chapter"], "")
            assert not is_base
            source_key = next(
                (
                    value
                    for value in record["source"]["source_container_html_ids"]
                    if value and value != "0"
                ),
                "anonymous",
            )
            identity_hash = sha256_bytes(json_bytes({
                "ordered_exception_position": len(exceptions) + 1,
                "source_container_html_ids": record["source"]["source_container_html_ids"],
                "source_pages": record["source"]["pages"],
                "chapter_sequence_values": record["chapter_sequence_values"],
                "short_title_spans": record["short_title_spans"],
                "authors": record["authors"],
            })).removeprefix("sha256:")[:12]
            record["id"] = f"jefferson-sowerby-unnumbered-{source_key}-{identity_hash}"
            record["identifier_kind"] = "unnumbered_source_entry"
            record["identifier_evidence"] = (
                "No BIDNo span in source HTML and no assigned position in the adjacent base-integer spine; "
                "retained separately and not assigned a Sowerby number."
            )
            exceptions.append(record)

    def emit_inferred_pending(until_number: int) -> None:
        nonlocal next_expected_number
        interval_numbers = list(range(next_expected_number, until_number))
        source_gap_numbers = [
            number for number in interval_numbers if number in known_source_gap_placeholders
        ]
        assignable_numbers = [number for number in interval_numbers if number not in source_gap_numbers]
        needed = len(assignable_numbers)
        extra_count = 0
        if len(pending_unlabeled) > needed:
            extra_count = len(pending_unlabeled) - needed
            emit_unnumbered_groups(pending_unlabeled[:extra_count])
            del pending_unlabeled[:extra_count]
        if needed != len(pending_unlabeled):
            pending_summary = [
                {
                    "pages": stable_unique(fragment["source_url"] for fragment in group["fragments"]),
                    "html_ids": stable_unique(fragment.get("container_html_id", "") for fragment in group["fragments"]),
                    "sequence_values": stable_unique(fragment.get("sequence_number", "") for fragment in group["fragments"]),
                    "short_titles": _merge_field(group["fragments"], "short_titles")[:2],
                }
                for group in pending_unlabeled
            ]
            raise SowerbyError(
                "Unlabeled source records do not exactly fill the monotonic Sowerby identifier gap "
                f"before {until_number}: needed {needed}, observed {len(pending_unlabeled)}; {pending_summary}"
            )
        had_unumbered_neighbors = bool(needed and extra_count)
        pending_iterator = iter(pending_unlabeled)
        for number in interval_numbers:
            if number in known_source_gap_placeholders:
                entries.append(_source_gap_placeholder(number, known_source_gap_placeholders[number]))
                source_gap_placeholder_numbers.append(number)
            else:
                group = next(pending_iterator)
                record, is_base = _entry_from_fragments(
                    group["fragments"],
                    group["chapter"],
                    "",
                    inferred_base_number=number,
                )
                assert is_base
                if had_unumbered_neighbors:
                    record["identifier_kind"] = "base_integer_inferred_from_gap_with_unnumbered_neighbors"
                    record["identifier_evidence"] = (
                        "Assigned to the trailing unlabeled record that fills the bounded gap; earlier unlabeled neighboring records were retained separately. LOC scan review is required."
                    )
                    gap_inferred_with_unnumbered_neighbors.append(number)
                entries.append(record)
                inferred_numbers.append(number)
            next_expected_number = number + 1
        pending_unlabeled.clear()

    for group in assembled_groups:
        identifier_raw = group["identifier_raw"]
        if not identifier_raw:
            pending_unlabeled.append(group)
            continue
        base_match = BASE_IDENTIFIER_RE.fullmatch(identifier_raw)
        if base_match:
            number = int(base_match.group(1))
            if number < next_expected_number:
                group_page_names = stable_unique(
                    f"{fragment['volume']}_{fragment['page']}.html" for fragment in group["fragments"]
                )
                explicit_correction = next(
                    (
                        corrected
                        for page_name in group_page_names
                        if (corrected := KNOWN_EXPLICIT_BID_CORRECTIONS.get((page_name, identifier_raw)))
                        is not None
                    ),
                    None,
                )
                looks_like_digit_transposition = (
                    len(str(number)) == len(str(next_expected_number))
                    and sorted(str(number)) == sorted(str(next_expected_number))
                    and any(record["sowerby_number"] == number for record in entries)
                )
                correction_is_exact_next = explicit_correction == next_expected_number
                if pending_unlabeled or not (looks_like_digit_transposition or correction_is_exact_next):
                    raise SowerbyError(
                        f"Out-of-order explicit Sowerby identifier {number} occurs with unresolved preceding records"
                    )
                assigned_number = next_expected_number
                record, is_base = _entry_from_fragments(
                    group["fragments"],
                    group["chapter"],
                    identifier_raw,
                    inferred_base_number=assigned_number,
                )
                assert is_base
                record["identifier_kind"] = "base_integer_corrected_from_out_of_order_html_bid"
                record["identifier_evidence"] = (
                    (
                        f"Source HTML BIDNo {identifier_raw} is followed by an explicit editorial correction to "
                        f"{assigned_number}; the corrected base integer is retained."
                    )
                    if correction_is_exact_next
                    else (
                        f"Source HTML BIDNo {identifier_raw} duplicates or reverses the established sequence; "
                        f"assigned the sole next digit-transposition base integer {assigned_number}. LOC scan review is required."
                    )
                )
                record["source_identifier_raw"] = identifier_raw
                entries.append(record)
                corrected_out_of_order_identifiers.append({
                    "source_identifier_raw": identifier_raw,
                    "assigned_sowerby_number": assigned_number,
                    "correction_basis": (
                        "explicit_source_editorial_correction"
                        if correction_is_exact_next
                        else "unique_digit_transposition_in_monotonic_sequence"
                    ),
                    "source_pages": record["source"]["pages"],
                })
                next_expected_number += 1
                continue
            emit_inferred_pending(number)
            record, is_base = _entry_from_fragments(group["fragments"], group["chapter"], identifier_raw)
            assert is_base
            entries.append(record)
            next_expected_number = number + 1
            continue
        range_match = RANGE_IDENTIFIER_RE.fullmatch(identifier_raw)
        if range_match:
            start = int(range_match.group(1))
            end_text = range_match.group(2)
            end = int(end_text)
            if len(end_text) < len(str(start)):
                end = int(str(start)[: len(str(start)) - len(end_text)] + end_text)
            if start != next_expected_number or end < start:
                raise SowerbyError(f"Out-of-order or invalid explicit Sowerby range {identifier_raw}")
            maximum_prior_groups = end - start
            if len(pending_unlabeled) > maximum_prior_groups:
                raise SowerbyError(
                    f"Explicit Sowerby range {identifier_raw} can cover at most {maximum_prior_groups} preceding unlabeled records; "
                    f"observed {len(pending_unlabeled)}"
                )
            for pending_group in pending_unlabeled:
                record, is_base = _entry_from_fragments(
                    pending_group["fragments"],
                    pending_group["chapter"],
                    "",
                    inferred_base_number=next_expected_number,
                )
                assert is_base
                record["identifier_kind"] = "base_integer_resolved_from_explicit_range"
                record["identifier_evidence"] = (
                    f"Resolved by ordered position within explicit source BIDNo range {identifier_raw}."
                )
                record["source_identifier_range"] = identifier_raw
                entries.append(record)
                range_resolved_numbers.append(next_expected_number)
                next_expected_number += 1
            pending_unlabeled.clear()
            remaining_numbers = list(range(next_expected_number, end + 1))
            for position, number in enumerate(remaining_numbers, 1):
                record, is_base = _entry_from_fragments(
                    group["fragments"],
                    group["chapter"],
                    identifier_raw,
                    inferred_base_number=number,
                )
                assert is_base
                record["source_identifier_range"] = identifier_raw
                record["source_identifier_raw"] = identifier_raw
                record["range_member_position"] = position
                record["range_member_count_in_shared_fragment"] = len(remaining_numbers)
                if len(remaining_numbers) == 1:
                    record["identifier_kind"] = "base_integer_resolved_from_explicit_range"
                    record["identifier_evidence"] = (
                        f"Resolved as the final ordered record in explicit source BIDNo range {identifier_raw}."
                    )
                else:
                    record["identifier_kind"] = "base_integer_shared_explicit_range_fragment"
                    record["identifier_evidence"] = (
                        f"Explicit source BIDNo range {identifier_raw} covers multiple titles in one HTML fragment; "
                        "the individual bibliographic segmentation is unresolved."
                    )
                    record["bibliographic_segmentation_status"] = "multiple base identifiers share one source HTML fragment"
                    range_shared_fragment_numbers.append(number)
                entries.append(record)
                range_resolved_numbers.append(number)
            next_expected_number = end + 1
            continue
        record, is_base = _entry_from_fragments(group["fragments"], group["chapter"], identifier_raw)
        assert not is_base
        exceptions.append(record)

    emit_inferred_pending(expected_last_number + 1)
    spanning_entry_count = sum(len(record["source"]["pages"]) > 1 for record in entries)

    numbers = [record["sowerby_number"] for record in entries]
    number_counts = Counter(numbers)
    missing_numbers = [number for number in range(expected_first_number, expected_last_number + 1) if number not in number_counts]
    duplicate_numbers = {str(number): count for number, count in sorted(number_counts.items()) if count != 1}
    expected_numbers = list(range(expected_first_number, expected_last_number + 1))
    volume_range_mismatches: dict[str, Any] = {}
    for volume, expected_range in expected_entry_ranges.items():
        observed = [
            record["sowerby_number"]
            for record in entries
            if record["catalogue_volume"] == volume
        ]
        if not observed or (min(observed), max(observed)) != expected_range:
            volume_range_mismatches[volume] = {
                "expected": list(expected_range),
                "observed": [min(observed), max(observed)] if observed else [],
            }
    chapter_numbers = sorted(observed_chapters)
    expected_chapters = list(expected_chapter_numbers)
    exception_id_counts = Counter(record["id"] for record in exceptions)
    duplicate_exception_ids = {
        identifier: count for identifier, count in sorted(exception_id_counts.items()) if count != 1
    }
    validation = {
        "schema": "shelfsignals-jefferson-sowerby-validation@1",
        "all_invariants_passed": (
            len(entries) == expected_entry_count
            and numbers == expected_numbers
            and not missing_numbers
            and not duplicate_numbers
            and chapter_numbers == expected_chapters
            and not volume_range_mismatches
            and not duplicate_exception_ids
        ),
        "unit_of_count": "base-integer Sowerby spine position; explicit source gaps are placeholders, not books",
        "expected_base_entry_count": expected_entry_count,
        "expected_first_base_number": expected_first_number,
        "expected_last_base_number": expected_last_number,
        "parsed_base_entry_count": len(entries),
        "base_numbers_are_exactly_1_through_4931_in_order": numbers == expected_numbers,
        "missing_base_numbers": missing_numbers,
        "duplicate_or_nonunit_base_numbers": duplicate_numbers,
        "supplemental_or_unparsed_identifier_count": len(exceptions),
        "duplicate_supplemental_or_unparsed_ids": duplicate_exception_ids,
        "supplemental_or_unparsed_ids_are_unique": not duplicate_exception_ids,
        "supplemental_or_unparsed_identifiers": [
            record["sowerby_identifier"] or record["id"] for record in exceptions
        ],
        "unnumbered_source_entry_count": sum(
            record["identifier_kind"] == "unnumbered_source_entry" for record in exceptions
        ),
        "base_identifiers_inferred_from_exact_sequence_gaps": inferred_numbers,
        "base_identifier_inference_count": len(inferred_numbers),
        "base_identifiers_inferred_from_gaps_with_unnumbered_neighbors": gap_inferred_with_unnumbered_neighbors,
        "base_identifiers_resolved_from_explicit_ranges": range_resolved_numbers,
        "base_identifier_range_resolution_count": len(range_resolved_numbers),
        "base_identifiers_sharing_range_fragments": range_shared_fragment_numbers,
        "base_identifier_shared_range_fragment_count": len(range_shared_fragment_numbers),
        "corrected_out_of_order_html_identifiers": corrected_out_of_order_identifiers,
        "corrected_out_of_order_html_identifier_count": len(corrected_out_of_order_identifiers),
        "source_gap_placeholder_numbers": source_gap_placeholder_numbers,
        "source_gap_placeholder_count": len(source_gap_placeholder_numbers),
        "source_backed_base_entry_count": len(entries) - len(source_gap_placeholder_numbers),
        "repeated_source_group_count": len(repeated_source_groups),
        "repeated_source_groups": repeated_source_groups,
        "verbatim_repeated_source_group_count": sum(
            group["complete_source_text_matches"] for group in repeated_source_groups
        ),
        "factual_core_mismatch_repeated_source_group_count": sum(
            not group["factual_core_matches"] for group in repeated_source_groups
        ),
        "known_aggregate_source_pages": sorted(KNOWN_AGGREGATE_SOURCE_PAGES),
        "ignored_aggregate_unlabeled_group_count": len(ignored_aggregate_unlabeled_groups),
        "ignored_aggregate_unlabeled_groups": ignored_aggregate_unlabeled_groups,
        "unique_aggregate_group_count": len(unique_aggregate_groups),
        "unique_aggregate_groups": unique_aggregate_groups,
        "chapter_numbers": chapter_numbers,
        "expected_chapter_numbers": expected_chapters,
        "chapters_are_exactly_expected_sequence": chapter_numbers == expected_chapters,
        "chapters_are_exactly_1_through_44": chapter_numbers == list(range(1, 45)),
        "observed_chapters": [observed_chapters[number] for number in chapter_numbers],
        "volume_range_mismatches": volume_range_mismatches,
        "expected_pages_by_volume": dict(page_limits),
        "source_page_count": len(source_pages),
        "parsed_fragment_count": fragment_count,
        "entries_spanning_multiple_html_pages": spanning_entry_count,
        "j_marked_entry_count": sum(record["sequence_marker"] == "J" for record in entries),
        "source_class_counts": dict(sorted(source_class_counts.items())),
        "excluded_editorial_class_counts": dict(sorted(excluded_class_counts.items())),
        "excluded_editorial_content_was_published": False,
        "source_snapshot_sha256": sha256_bytes(bytes(page_hash_payload)),
    }
    if not validation["all_invariants_passed"]:
        failure_summary = {
            "parsed_base_entry_count": len(entries),
            "numbers_are_exact_sequence": numbers == expected_numbers,
            "missing_base_numbers": missing_numbers,
            "duplicate_or_nonunit_base_numbers": duplicate_numbers,
            "observed_chapter_numbers": chapter_numbers,
            "expected_chapter_numbers": expected_chapters,
            "volume_range_mismatches": volume_range_mismatches,
            "duplicate_supplemental_or_unparsed_ids": duplicate_exception_ids,
        }
        raise SowerbyError(
            "Sowerby snapshot failed closed: expected base identifiers 1..4931 exactly once, expected chapters, "
            f"and published volume ranges; {json.dumps(failure_summary, sort_keys=True)}"
        )
    return entries, exceptions, validation, source_pages


class CachedFetcher:
    def __init__(self, *, min_interval: float, user_agent: str) -> None:
        self.min_interval = max(0.0, min_interval)
        self.user_agent = user_agent
        self.last_request = 0.0

    def fetch(self, url: str) -> tuple[bytes, dict[str, Any]]:
        wait = self.min_interval - (time.monotonic() - self.last_request)
        if wait > 0:
            time.sleep(wait)
        request = urllib.request.Request(url, headers={"User-Agent": self.user_agent, "Accept": "text/html,*/*;q=0.1"})
        for attempt in range(4):
            try:
                self.last_request = time.monotonic()
                with urllib.request.urlopen(request, timeout=45) as response:
                    body = response.read()
                    status = int(getattr(response, "status", 200))
                    content_type = response.headers.get("Content-Type", "")
                    if status != 200:
                        raise SowerbyError(f"Unexpected HTTP {status} for {url}")
                    if len(body) > 4 * 1024 * 1024:
                        raise SowerbyError(f"Unexpectedly large HTML response for {url}")
                    return body, {
                        "schema": "shelfsignals-source-retrieval@1",
                        "request_url": url,
                        "retrieved_at": utc_now(),
                        "status": status,
                        "content_type": content_type,
                        "bytes": len(body),
                        "sha256": sha256_bytes(body),
                    }
            except urllib.error.HTTPError as error:
                if error.code not in {429, 500, 502, 503, 504} or attempt == 3:
                    raise
                retry_after = error.headers.get("Retry-After", "")
                time.sleep(float(retry_after) if retry_after.isdigit() else 2**attempt)
            except (urllib.error.URLError, TimeoutError):
                if attempt == 3:
                    raise
                time.sleep(2**attempt)
        raise AssertionError("unreachable")


def validate_cached_file(path: Path, expected_url: str) -> bool:
    sidecar_path = path.with_suffix(".meta.json")
    if not path.is_file() or not sidecar_path.is_file():
        return False
    try:
        sidecar = load_json(sidecar_path)
    except SowerbyError:
        return False
    return (
        sidecar.get("request_url") == expected_url
        and sidecar.get("bytes") == path.stat().st_size
        and sidecar.get("sha256") == sha256_file(path)
        and SHA256_RE.fullmatch(str(sidecar.get("sha256", ""))) is not None
    )


def _new_generation_name() -> str:
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}-{os.getpid()}"


def active_generation(cache_root: Path) -> tuple[Path, dict[str, Any]]:
    active_path = cache_root / "active.json"
    if not active_path.is_file():
        raise SowerbyError("No complete active Sowerby snapshot; run crawl first")
    active = load_json(active_path)
    if active.get("complete") is not True or not active.get("generation"):
        raise SowerbyError("Active Sowerby snapshot is not marked complete")
    page_dir = cache_root / "generations" / str(active["generation"]) / "pages"
    if not page_dir.is_dir():
        raise SowerbyError("Active Sowerby snapshot page directory is missing")
    return page_dir, active


def crawl(cache_root: Path, *, refresh: bool, delay: float, user_agent: str) -> dict[str, Any]:
    cache_root.mkdir(parents=True, exist_ok=True)
    if not refresh and (cache_root / "active.json").is_file():
        page_dir, active = active_generation(cache_root)
        compile_page_directory(page_dir, require_sidecars=True)
        return active

    pending_path = cache_root / "pending.json"
    if pending_path.is_file() and not refresh:
        pending = load_json(pending_path)
        generation = str(pending.get("generation", ""))
        if not generation:
            raise SowerbyError("Pending Sowerby crawl lacks a generation ID")
    else:
        generation = _new_generation_name()
        atomic_write_json(pending_path, {"generation": generation, "started_at": utc_now(), "complete": False})
    generation_root = cache_root / "generations" / generation
    page_dir = generation_root / "pages"
    page_dir.mkdir(parents=True, exist_ok=True)
    fetcher = CachedFetcher(min_interval=delay, user_agent=user_agent)

    # Evidence about the access boundary is retained with the snapshot.  Terms
    # acknowledgement is intentionally not represented as reuse permission.
    for label, url in (("toc", TRANSCRIPT_TOC), ("terms", TERMS_URL), ("robots", ROBOTS_URL)):
        path = generation_root / f"{label}.html"
        if not validate_cached_file(path, url):
            body, sidecar = fetcher.fetch(url)
            atomic_write(path, body)
            atomic_write_json(path.with_suffix(".meta.json"), sidecar)

    completed = 0
    total = sum(EXPECTED_PAGE_LIMITS.values())
    for volume, limit in EXPECTED_PAGE_LIMITS.items():
        for page in range(1, limit + 1):
            filename = f"{volume}_{page}.html"
            url = urllib.parse.urljoin(TRANSCRIPT_BASE, filename)
            path = page_dir / filename
            if not validate_cached_file(path, url):
                body, sidecar = fetcher.fetch(url)
                parse_page(body, volume=volume, page=page)
                atomic_write(path, body)
                atomic_write_json(path.with_suffix(".meta.json"), sidecar)
            completed += 1
            if completed % 100 == 0 or completed == total:
                print(f"Sowerby crawl {completed}/{total}", flush=True)

    _, _, validation, source_pages = compile_page_directory(page_dir, require_sidecars=True)
    completed_at = utc_now()
    snapshot = {
        "schema": "shelfsignals-jefferson-sowerby-source-snapshot@1",
        "generation": generation,
        "complete": True,
        "completed_at": completed_at,
        "source_snapshot_sha256": validation["source_snapshot_sha256"],
        "source_page_count": len(source_pages),
        "terms_review_acknowledged": True,
        "terms_review_is_publication_permission": False,
        "source_terms": TERMS_URL,
    }
    atomic_write_json(generation_root / "snapshot.json", snapshot)
    atomic_write_json(cache_root / "active.json", snapshot)
    if pending_path.exists():
        pending_path.unlink()
    return snapshot


def adopt_snapshot(
    source_page_dir: Path,
    cache_root: Path,
    *,
    crawl_completed_at: str,
) -> dict[str, Any]:
    """Adopt a completed, manifest-hashed research crawl without refetching."""
    completed_at = validate_timestamp(crawl_completed_at)
    source_manifest_path = source_page_dir / "manifest.json"
    source_manifest = load_json(source_manifest_path)
    if not isinstance(source_manifest, list):
        raise SowerbyError("Adopted crawl manifest must be a JSON array")
    expected_paths = page_paths(source_page_dir)
    if len(source_manifest) != len(expected_paths):
        raise SowerbyError(
            f"Adopted crawl manifest has {len(source_manifest)} rows; expected {len(expected_paths)}"
        )
    rows_by_name: dict[str, Mapping[str, Any]] = {}
    for row in source_manifest:
        if not isinstance(row, Mapping):
            raise SowerbyError("Adopted crawl manifest contains a non-object row")
        volume = str(row.get("volume", ""))
        try:
            page = int(row.get("page", 0))
        except (TypeError, ValueError) as error:
            raise SowerbyError("Adopted crawl manifest contains an invalid page number") from error
        name = f"{volume}_{page}.html"
        if name in rows_by_name:
            raise SowerbyError(f"Adopted crawl manifest duplicates {name}")
        rows_by_name[name] = row

    source_manifest_hash = sha256_file(source_manifest_path)
    generation = (
        "adopted-"
        + completed_at.replace("-", "").replace(":", "").replace("Z", "Z")
        + "-"
        + source_manifest_hash.removeprefix("sha256:")[:12]
    )
    generation_root = cache_root / "generations" / generation
    target_page_dir = generation_root / "pages"
    target_page_dir.mkdir(parents=True, exist_ok=True)

    for source_path in expected_paths:
        row = rows_by_name.get(source_path.name)
        if row is None:
            raise SowerbyError(f"Adopted crawl manifest is missing {source_path.name}")
        if not source_path.is_file():
            raise SowerbyError(f"Adopted crawl is missing {source_path.name}")
        body = source_path.read_bytes()
        expected_url = urllib.parse.urljoin(TRANSCRIPT_BASE, source_path.name)
        expected_hash = str(row.get("sha256", "")).removeprefix("sha256:")
        observed_hash = hashlib.sha256(body).hexdigest()
        if (
            row.get("url") != expected_url
            or row.get("bytes") != len(body)
            or expected_hash != observed_hash
        ):
            raise SowerbyError(f"Adopted crawl manifest mismatch for {source_path.name}")
        match = PAGE_RE.match(source_path.name)
        assert match is not None
        parse_page(body, volume=match.group(1), page=int(match.group(2)))
        target = target_page_dir / source_path.name
        atomic_write(target, body)
        atomic_write_json(target.with_suffix(".meta.json"), {
            "schema": "shelfsignals-source-retrieval@1",
            "request_url": expected_url,
            "retrieved_at": completed_at,
            "retrieval_time_precision": "crawl_completion_only; per-page timestamps unavailable",
            "status": 200,
            "content_type": "text/html",
            "bytes": len(body),
            "sha256": f"sha256:{observed_hash}",
            "provenance": "adopted_from_complete_manifest_hashed_research_crawl",
            "source_manifest_sha256": source_manifest_hash,
        })

    atomic_write(generation_root / "adopted-crawl-manifest.json", source_manifest_path.read_bytes())
    _, _, validation, source_pages = compile_page_directory(target_page_dir, require_sidecars=True)
    snapshot = {
        "schema": "shelfsignals-jefferson-sowerby-source-snapshot@1",
        "generation": generation,
        "complete": True,
        "completed_at": completed_at,
        "source_snapshot_sha256": validation["source_snapshot_sha256"],
        "source_manifest_sha256": source_manifest_hash,
        "source_page_count": len(source_pages),
        "terms_review_acknowledged": True,
        "terms_review_is_publication_permission": False,
        "source_terms": TERMS_URL,
        "adopted_from_manifest_hashed_research_crawl": True,
    }
    atomic_write_json(generation_root / "snapshot.json", snapshot)
    cache_root.mkdir(parents=True, exist_ok=True)
    atomic_write_json(cache_root / "active.json", snapshot)
    return snapshot


def build(cache_root: Path, data_dir: Path, *, generated_at: str | None = None) -> dict[str, Any]:
    page_dir, active = active_generation(cache_root)
    entries, exceptions, validation, source_pages = compile_page_directory(page_dir, require_sidecars=True)
    timestamp = validate_timestamp(generated_at) if generated_at else validate_timestamp(str(active["completed_at"]))
    outputs: dict[str, bytes] = {
        PUBLIC_OUTPUTS["entries"]: jsonl_bytes(entries),
        PUBLIC_OUTPUTS["exceptions"]: jsonl_bytes(exceptions),
        PUBLIC_OUTPUTS["source_pages"]: jsonl_bytes(source_pages),
        PUBLIC_OUTPUTS["validation"]: json_bytes(validation),
    }
    manifest_outputs = {
        name: {"bytes": len(body), "sha256": sha256_bytes(body)} for name, body in sorted(outputs.items())
    }
    manifest = {
        "schema": "shelfsignals-jefferson-sowerby-package@1",
        "generated_at": timestamp,
        "source_snapshot_sha256": validation["source_snapshot_sha256"],
        "source_page_count": validation["source_page_count"],
        "base_entry_count": len(entries),
        "source_backed_base_entry_count": validation["source_backed_base_entry_count"],
        "source_gap_placeholder_count": validation["source_gap_placeholder_count"],
        "source_gap_placeholder_numbers": validation["source_gap_placeholder_numbers"],
        "supplemental_or_unparsed_identifier_count": len(exceptions),
        "unit_of_count": "base-integer Sowerby spine position; explicit source gaps are placeholders, not books",
        "publication_status": "research-only until Thomas Jefferson Foundation reuse permission is recorded",
        "terms_review_is_publication_permission": False,
        "factual_core_only": True,
        "excluded_content": sorted(EXCLUDED_EDITORIAL_CLASSES),
        "outputs": manifest_outputs,
    }
    outputs[PUBLIC_OUTPUTS["manifest"]] = json_bytes(manifest)
    data_dir.mkdir(parents=True, exist_ok=True)
    for name, body in outputs.items():
        atomic_write(data_dir / name, body)
    return manifest


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("crawl", "adopt", "build", "all"))
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--refresh", action="store_true", help="Create a new source generation instead of using the active snapshot")
    parser.add_argument("--delay", type=float, default=0.35, help="Minimum seconds between source requests")
    parser.add_argument("--generated-at", help="Fixed ISO-8601 UTC timestamp for a byte-reproducible build")
    parser.add_argument("--adopt-page-dir", type=Path, help="Completed manifest-hashed crawl directory for adopt")
    parser.add_argument("--crawl-completed-at", help="UTC completion timestamp recorded for an adopted crawl")
    parser.add_argument(
        "--user-agent",
        default="ShelfSignals-research/0.1 (+https://github.com/gitbrainlab/ShelfSignals)",
    )
    parser.add_argument(
        "--acknowledge-monticello-terms",
        action="store_true",
        help="Required for network crawl; records review of terms, not publication permission",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    if args.command in {"crawl", "all", "adopt"}:
        if not args.acknowledge_monticello_terms:
            raise SowerbyError(
                f"Review {TERMS_URL} and pass --acknowledge-monticello-terms; acknowledgement is not reuse permission"
            )
    if args.command in {"crawl", "all"}:
        crawl(args.cache_root, refresh=args.refresh, delay=args.delay, user_agent=args.user_agent)
    if args.command == "adopt":
        if args.adopt_page_dir is None or not args.crawl_completed_at:
            raise SowerbyError("adopt requires --adopt-page-dir and --crawl-completed-at")
        snapshot = adopt_snapshot(
            args.adopt_page_dir,
            args.cache_root,
            crawl_completed_at=args.crawl_completed_at,
        )
        print(json.dumps(snapshot, ensure_ascii=False, sort_keys=True, indent=2))
    if args.command in {"build", "all"}:
        manifest = build(args.cache_root, args.data_dir, generated_at=args.generated_at)
        print(json.dumps(manifest, ensure_ascii=False, sort_keys=True, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SowerbyError as error:
        print(f"error: {error}", file=sys.stderr)
        raise SystemExit(1)
