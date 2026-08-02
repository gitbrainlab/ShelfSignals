#!/usr/bin/env python3
"""Build the deterministic Jefferson life-event and chapter insight graph.

The graph never infers reading from collection membership, chapter placement,
or title similarity.  Chapter-to-event edges are contextual navigation aids;
record-level use assessments require an explicit named source in the reviewed
configuration.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
import sys
from typing import Any, Mapping, Sequence
from urllib.parse import urlparse


REPOSITORY_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_CORE = REPOSITORY_ROOT / "docs/data/collections/jefferson/historical/catalog-core.json"
DEFAULT_CONFIG = REPOSITORY_ROOT / "research/jefferson/jefferson-life-events.json"
DEFAULT_OUTPUT = REPOSITORY_ROOT / "docs/data/collections/jefferson/historical/insights.json"

CONFIG_SCHEMA = "shelfsignals-jefferson-life-event-config@1"
OUTPUT_SCHEMA = "shelfsignals-jefferson-insight-graph@1"
CORE_SCHEMA = "shelfsignals-browser-historical@1"
EXPECTED_RECORD_COUNT = 4928
EXPECTED_CHAPTER_COUNT = 44
SAFE_ID = re.compile(r"^[a-z][a-z0-9-]{1,63}$")
RECORD_ID = re.compile(r"^jefferson-sowerby-[1-9][0-9]{0,3}$")
ALLOWED_EVENT_KINDS = {"event", "life_period"}
ALLOWED_USE_STATUS = {
    "not_established",
    "documented_interaction",
    "documented_excerpting",
    "documented_correspondence_context",
}


class BuildError(RuntimeError):
    """Raised when graph evidence or identity fails closed."""


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def sha256_bytes(value: bytes) -> str:
    return f"sha256:{hashlib.sha256(value).hexdigest()}"


def load_object(path: Path, label: str) -> dict[str, Any]:
    try:
        value = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise BuildError(f"Unable to read {label}: {error}") from error
    if not isinstance(value, dict):
        raise BuildError(f"{label} must be a JSON object")
    return value


def exact_keys(value: Mapping[str, Any], expected: set[str], label: str) -> None:
    actual = set(value)
    if actual != expected:
        raise BuildError(f"{label} fields differ: missing={sorted(expected - actual)}, unknown={sorted(actual - expected)}")


def string_list(value: Any, label: str) -> list[str]:
    if not isinstance(value, list) or not value or any(not clean_text(item) for item in value):
        raise BuildError(f"{label} must be a non-empty-string array")
    return [clean_text(item) for item in value]


def validate_loc_url(value: Any, label: str) -> str:
    url = clean_text(value)
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or (host != "loc.gov" and not host.endswith(".loc.gov")) or parsed.username or parsed.password:
        raise BuildError(f"{label} must be an approved loc.gov HTTPS URL")
    return url


def decode_core(core: Mapping[str, Any]) -> tuple[list[dict[str, Any]], dict[str, Any], str]:
    if core.get("schema") != CORE_SCHEMA:
        raise BuildError("Historical core schema is invalid")
    source = core.get("source")
    if not isinstance(source, dict) or source.get("collection_id") != "jefferson" or source.get("corpus_id") != "historical":
        raise BuildError("Historical core source identity is invalid")
    fields = (core.get("contract") or {}).get("core_fields")
    items = core.get("items")
    if not isinstance(fields, list) or len(fields) != len(set(fields)) or not isinstance(items, list):
        raise BuildError("Historical core compact contract is invalid")
    if len(items) != EXPECTED_RECORD_COUNT or source.get("record_count") != EXPECTED_RECORD_COUNT:
        raise BuildError("Historical core must contain exactly 4,928 source-backed entries")
    records: list[dict[str, Any]] = []
    seen: set[str] = set()
    for index, row in enumerate(items):
        if not isinstance(row, list) or len(row) != len(fields):
            raise BuildError(f"Historical core row {index} violates its compact field contract")
        record = dict(zip(fields, row, strict=True))
        record_id = clean_text(record.get("id"))
        chapter = record.get("chapter_number")
        if not RECORD_ID.fullmatch(record_id) or record_id in seen or not isinstance(chapter, int) or not 1 <= chapter <= 44:
            raise BuildError(f"Historical core identity/chapter is invalid at row {index}")
        seen.add(record_id)
        records.append(record)
    generated_at = clean_text(core.get("generated_at"))
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", generated_at):
        raise BuildError("Historical core generated_at is invalid")
    return records, dict(source), generated_at


def build_graph(core: Mapping[str, Any], config: Mapping[str, Any]) -> dict[str, Any]:
    records, catalog_source, generated_at = decode_core(core)
    exact_keys(config, {"schema", "collection_id", "corpus_id", "as_of", "sources", "questions", "events", "record_relations"}, "Event config")
    if config.get("schema") != CONFIG_SCHEMA or config.get("collection_id") != "jefferson" or config.get("corpus_id") != "historical":
        raise BuildError("Event config identity is invalid")
    as_of = clean_text(config.get("as_of"))
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}", as_of):
        raise BuildError("Event config as_of date is invalid")

    source_rows = config.get("sources")
    if not isinstance(source_rows, list) or not source_rows:
        raise BuildError("Event config requires named sources")
    sources: list[dict[str, str]] = []
    source_ids: set[str] = set()
    for index, raw in enumerate(source_rows):
        if not isinstance(raw, dict):
            raise BuildError(f"Source {index} must be an object")
        exact_keys(raw, {"id", "label", "url"}, f"Source {index}")
        source_id = clean_text(raw.get("id"))
        if not SAFE_ID.fullmatch(source_id) or source_id in source_ids:
            raise BuildError(f"Source {index} ID is unsafe or duplicated")
        source_ids.add(source_id)
        label = clean_text(raw.get("label"))
        if not label:
            raise BuildError(f"Source {source_id} label is required")
        sources.append({"id": source_id, "label": label, "url": validate_loc_url(raw.get("url"), f"Source {source_id}")})

    question_rows = config.get("questions")
    if not isinstance(question_rows, list) or [row.get("id") for row in question_rows if isinstance(row, dict)] != [
        "why-present", "life-context", "documented-use", "connections"
    ]:
        raise BuildError("The four question prompts must be present in canonical order")
    questions: list[dict[str, str]] = []
    for index, raw in enumerate(question_rows):
        exact_keys(raw, {"id", "label", "prompt"}, f"Question {index}")
        question = {field: clean_text(raw.get(field)) for field in ("id", "label", "prompt")}
        if not all(question.values()):
            raise BuildError(f"Question {index} text is required")
        questions.append(question)

    by_id = {record["id"]: record for record in records}
    chapter_records: dict[int, list[dict[str, Any]]] = {number: [] for number in range(1, EXPECTED_CHAPTER_COUNT + 1)}
    for record in records:
        chapter_records[record["chapter_number"]].append(record)

    event_rows = config.get("events")
    if not isinstance(event_rows, list) or not event_rows:
        raise BuildError("Event config requires events")
    events: list[dict[str, Any]] = []
    event_ids: set[str] = set()
    chapter_event_ids: dict[int, list[str]] = {number: [] for number in chapter_records}
    event_record_ids: dict[str, set[str]] = {}
    event_fields = {
        "id", "kind", "title", "short_title", "date_label", "start_year", "end_year", "phase",
        "summary", "critical_context", "people", "places", "themes", "source_ids", "chapter_groups",
    }
    group_fields = {"chapters", "relationship", "rationale", "context_score"}
    for index, raw in enumerate(event_rows):
        if not isinstance(raw, dict):
            raise BuildError(f"Event {index} must be an object")
        exact_keys(raw, event_fields, f"Event {index}")
        event_id = clean_text(raw.get("id"))
        if not SAFE_ID.fullmatch(event_id) or event_id in event_ids:
            raise BuildError(f"Event {index} ID is unsafe or duplicated")
        event_ids.add(event_id)
        if raw.get("kind") not in ALLOWED_EVENT_KINDS:
            raise BuildError(f"Event {event_id} kind is invalid")
        text_fields = ("title", "short_title", "date_label", "phase", "summary", "critical_context")
        if any(not clean_text(raw.get(field)) for field in text_fields):
            raise BuildError(f"Event {event_id} text is incomplete")
        start = raw.get("start_year")
        end = raw.get("end_year")
        if not isinstance(start, int) or not isinstance(end, int) or not 1743 <= start <= end <= 1826:
            raise BuildError(f"Event {event_id} dates are invalid")
        references = string_list(raw.get("source_ids"), f"Event {event_id} source_ids")
        if any(reference not in source_ids for reference in references):
            raise BuildError(f"Event {event_id} cites an unknown source")
        groups = raw.get("chapter_groups")
        if not isinstance(groups, list) or not groups:
            raise BuildError(f"Event {event_id} requires chapter groups")
        normalized_groups: list[dict[str, Any]] = []
        related_ids: set[str] = set()
        used_chapters: set[int] = set()
        for group_index, group in enumerate(groups):
            if not isinstance(group, dict):
                raise BuildError(f"Event {event_id} chapter group {group_index} must be an object")
            exact_keys(group, group_fields, f"Event {event_id} chapter group {group_index}")
            chapters = group.get("chapters")
            score = group.get("context_score")
            if not isinstance(chapters, list) or not chapters or chapters != sorted(set(chapters)) or any(not isinstance(chapter, int) or chapter not in chapter_records for chapter in chapters):
                raise BuildError(f"Event {event_id} chapter group {group_index} chapters are invalid")
            if used_chapters.intersection(chapters):
                raise BuildError(f"Event {event_id} chapter groups overlap")
            if not isinstance(score, int) or not 0 <= score <= 100:
                raise BuildError(f"Event {event_id} context score is invalid")
            if not clean_text(group.get("relationship")) or not clean_text(group.get("rationale")):
                raise BuildError(f"Event {event_id} chapter group {group_index} text is incomplete")
            used_chapters.update(chapters)
            group_records = [record for chapter in chapters for record in chapter_records[chapter]]
            group_ids = {record["id"] for record in group_records}
            related_ids.update(group_ids)
            for chapter in chapters:
                chapter_event_ids[chapter].append(event_id)
            normalized_groups.append({
                "chapters": chapters,
                "relationship": clean_text(group.get("relationship")),
                "rationale": clean_text(group.get("rationale")),
                "context_score": score,
                "related_record_count": len(group_ids),
                "source_backed_title_count": sum(1 for record in group_records if record.get("title_status") == "source_backed"),
            })
        event_record_ids[event_id] = related_ids
        events.append({
            "id": event_id,
            "kind": raw["kind"],
            "title": clean_text(raw.get("title")),
            "short_title": clean_text(raw.get("short_title")),
            "date_label": clean_text(raw.get("date_label")),
            "start_year": start,
            "end_year": end,
            "phase": clean_text(raw.get("phase")),
            "summary": clean_text(raw.get("summary")),
            "critical_context": clean_text(raw.get("critical_context")),
            "people": string_list(raw.get("people"), f"Event {event_id} people"),
            "places": string_list(raw.get("places"), f"Event {event_id} places"),
            "themes": string_list(raw.get("themes"), f"Event {event_id} themes"),
            "source_ids": references,
            "chapter_groups": normalized_groups,
            "chapter_count": len(used_chapters),
            "related_record_count": len(related_ids),
            "source_backed_title_count": sum(1 for record_id in related_ids if by_id[record_id].get("title_status") == "source_backed"),
            "direct_relation_count": 0,
        })

    relation_rows = config.get("record_relations")
    if not isinstance(relation_rows, list):
        raise BuildError("Event config record_relations must be an array")
    relation_fields = {
        "event_id", "record_id", "display_label", "relationship", "claim", "event_use_status",
        "use_confidence_score", "connection_score", "source_ids", "limits",
    }
    relations: list[dict[str, Any]] = []
    relation_keys: set[tuple[str, str]] = set()
    for index, raw in enumerate(relation_rows):
        if not isinstance(raw, dict):
            raise BuildError(f"Record relation {index} must be an object")
        exact_keys(raw, relation_fields, f"Record relation {index}")
        event_id = clean_text(raw.get("event_id"))
        record_id = clean_text(raw.get("record_id"))
        key = (event_id, record_id)
        if event_id not in event_ids or record_id not in by_id or key in relation_keys:
            raise BuildError(f"Record relation {index} has an unknown or duplicated identity")
        if record_id not in event_record_ids[event_id]:
            raise BuildError(f"Record relation {index} falls outside its event chapter clusters")
        relation_keys.add(key)
        status = clean_text(raw.get("event_use_status"))
        score = raw.get("use_confidence_score")
        connection_score = raw.get("connection_score")
        if status not in ALLOWED_USE_STATUS:
            raise BuildError(f"Record relation {index} use status is invalid")
        if status == "not_established" and score is not None:
            raise BuildError(f"Record relation {index} cannot score unestablished use")
        if status != "not_established" and (not isinstance(score, int) or not 0 <= score <= 100):
            raise BuildError(f"Record relation {index} requires a bounded use-confidence score")
        if not isinstance(connection_score, int) or not 0 <= connection_score <= 100:
            raise BuildError(f"Record relation {index} connection score is invalid")
        if any(not clean_text(raw.get(field)) for field in ("display_label", "relationship", "claim", "limits")):
            raise BuildError(f"Record relation {index} text is incomplete")
        references = string_list(raw.get("source_ids"), f"Record relation {index} source_ids")
        if any(reference not in source_ids for reference in references):
            raise BuildError(f"Record relation {index} cites an unknown source")
        relations.append({
            "event_id": event_id,
            "record_id": record_id,
            "display_label": clean_text(raw.get("display_label")),
            "relationship": clean_text(raw.get("relationship")),
            "claim": clean_text(raw.get("claim")),
            "event_use_status": status,
            "use_confidence_score": score,
            "connection_score": connection_score,
            "source_ids": references,
            "limits": clean_text(raw.get("limits")),
        })
    direct_counts: dict[str, int] = {event_id: 0 for event_id in event_ids}
    for relation in relations:
        direct_counts[relation["event_id"]] += 1
    for event in events:
        event["direct_relation_count"] = direct_counts[event["id"]]

    chapter_clusters: list[dict[str, Any]] = []
    for number, rows in chapter_records.items():
        example = rows[0]
        chapter_clusters.append({
            "chapter_number": number,
            "faculty": clean_text(example.get("faculty")),
            "label": clean_text(example.get("chapter_label")),
            "record_count": len(rows),
            "source_backed_title_count": sum(1 for record in rows if record.get("title_status") == "source_backed"),
            "event_ids": chapter_event_ids[number],
        })
    if len(chapter_clusters) != EXPECTED_CHAPTER_COUNT or sum(row["record_count"] for row in chapter_clusters) != EXPECTED_RECORD_COUNT:
        raise BuildError("Insight chapter clusters do not reconcile to the historical corpus")

    graph = {
        "schema": OUTPUT_SCHEMA,
        "generated_at": generated_at,
        "as_of": as_of,
        "collection_id": "jefferson",
        "corpus_id": "historical",
        "catalog_source": catalog_source,
        "config_sha256": sha256_bytes(json_bytes(config)),
        "methodology": {
            "context_score": "An ordinal evidence-strength score for navigation: 100 is corpus-defining or directly documented; 70–99 is tight documentary or thematic alignment; 40–69 is broad contextual alignment. It is not a probability of reading or influence.",
            "use_confidence_score": "Shown only when a named source documents a specific interaction such as receipt, correspondence, commentary, or excerpting. It measures confidence in that bounded assessment, not frequency, influence, or complete reading.",
            "default_use_assessment": "not_established",
            "limitations": [
                "Sowerby membership and chapter placement do not prove reading, consultation, endorsement, acquisition date, or influence.",
                "Chapter-to-event edges are curated contextual lenses and never documentary record-level use claims.",
                "Only source-backed record relations may override the default 'not established' use assessment.",
                "A Sowerby entry is not silently treated as a work, edition, volume, physical copy, holding, or digital object.",
            ],
        },
        "questions": questions,
        "sources": sources,
        "events": events,
        "chapter_clusters": chapter_clusters,
        "record_relations": relations,
        "coverage": {
            "historical_entries": EXPECTED_RECORD_COUNT,
            "historical_chapters": EXPECTED_CHAPTER_COUNT,
            "source_backed_titles": sum(1 for record in records if record.get("title_status") == "source_backed"),
            "titles_not_established": sum(1 for record in records if record.get("title_status") != "source_backed"),
            "events": len(events),
            "chapter_event_edges": sum(event["chapter_count"] for event in events),
            "direct_record_relations": len(relations),
            "records_with_direct_relations": len({relation["record_id"] for relation in relations}),
        },
    }
    if graph["coverage"]["source_backed_titles"] + graph["coverage"]["titles_not_established"] != EXPECTED_RECORD_COUNT:
        raise BuildError("Insight title coverage does not reconcile")
    return graph


def build_bytes(core_path: Path = DEFAULT_CORE, config_path: Path = DEFAULT_CONFIG) -> bytes:
    return json_bytes(build_graph(load_object(core_path, "historical core"), load_object(config_path, "event config")))


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--core", type=Path, default=DEFAULT_CORE)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--check", action="store_true")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        body = build_bytes(args.core, args.config)
        if args.check:
            if not args.output.is_file() or args.output.read_bytes() != body:
                raise BuildError("Committed insight graph is missing or stale")
            action = "checked"
        else:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_bytes(body)
            action = "wrote"
        graph = json.loads(body)
        print(
            f"Jefferson insight graph {action}: {graph['coverage']['events']} events, "
            f"{graph['coverage']['historical_chapters']} chapters, "
            f"{graph['coverage']['direct_record_relations']} direct record relations"
        )
        return 0
    except BuildError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
