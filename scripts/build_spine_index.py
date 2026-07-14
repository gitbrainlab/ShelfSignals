#!/usr/bin/env python3
"""Build the compact, lazy-loadable ShelfSignals spine geometry index.

The input is the generated Clark catalog physical-profile manifest.  The index
contains only geometry and contract data needed to render a shelf:
Clark-stated height/width, separately encoded binding and housing, conservative
object form, record warnings, and an explicitly modeled depth derived from
Clark extent. It never consumes cover images or provider-edition geometry, and
it never represents the depth model as a measurement of Clark's copy.

Full source descriptions remain in ``book_profiles.json`` and are referenced
by record ID instead of being duplicated into the compact index.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import tempfile
from pathlib import Path
from typing import Any, Mapping, Optional


SCHEMA = "shelfsignals-spine-index@1"
VERSION = "1.0.0"
PROFILE_SCHEMA = "shelfsignals-book-profiles@1"
DEPTH_METHOD = "catalog-extent-model-v1"
DEFAULT_INPUT = Path("docs/data/book_profiles.json")
DEFAULT_OUTPUT = Path("docs/data/spine_index.json")
DEFAULT_ID_PREFIX = "alma"
SHA256_RE = re.compile(r"^sha256:[a-f0-9]{64}$", re.IGNORECASE)

# Binding and housing are intentionally different evidence fields. These codes
# are stable so adding a term later cannot silently reinterpret committed data.
BINDING_CODES = {
    "accordion-folded": 1,
    "casebound": 2,
    "hardcover": 3,
    "paperback": 4,
    "cloth": 5,
    "boards": 6,
    "wrappers": 7,
    "stapled": 8,
    "saddle-stitched": 9,
    "spiral-bound": 10,
    "comb-bound": 11,
    "loose-leaf": 12,
    "loose-leaf-binder": 13,
}
HOUSING_CODES = {
    "portfolio": 1,
    "slipcase": 2,
    "folder": 3,
    "envelope": 4,
    "binder": 5,
    "case": 6,
    "box": 7,
    "container": 8,
}

# Object form is conservative: stated terms remain stated; a paged-object form
# is derived only from Clark-stated page/leaf extent; unsupported forms remain
# honest unknowns. Codes are stable and described in the manifest.
OBJECT_FORMS = {
    0: {"term": "unknown", "evidence_status": "unknown", "basis": "no_supported_catalog_term"},
    1: {"term": "paged_object", "evidence_status": "derived", "basis": "clark_catalog_extent_semantics"},
    2: {"term": "volume", "evidence_status": "stated", "basis": "clark_catalog_object_term"},
    3: {"term": "multi_volume_set", "evidence_status": "stated", "basis": "clark_catalog_object_term"},
    4: {"term": "folded_sheet", "evidence_status": "stated", "basis": "clark_catalog_object_term"},
    5: {"term": "sheet", "evidence_status": "stated", "basis": "clark_catalog_object_term"},
    6: {"term": "portfolio", "evidence_status": "stated", "basis": "clark_catalog_object_term"},
    7: {"term": "housed_materials", "evidence_status": "stated", "basis": "clark_catalog_housing_term"},
    8: {"term": "poster_set", "evidence_status": "stated", "basis": "clark_catalog_object_term"},
    9: {"term": "card_set", "evidence_status": "stated", "basis": "clark_catalog_object_term"},
    10: {"term": "slide_set", "evidence_status": "stated", "basis": "clark_catalog_object_term"},
    11: {"term": "media_disc", "evidence_status": "stated", "basis": "clark_catalog_object_term"},
    12: {"term": "parts_set", "evidence_status": "stated", "basis": "clark_catalog_object_term"},
    13: {"term": "serial_parts", "evidence_status": "stated", "basis": "clark_catalog_object_term"},
    14: {"term": "map", "evidence_status": "stated", "basis": "clark_catalog_object_term"},
}

WARNING_BITS = {
    "height_unavailable": 1,
    "width_unavailable": 2,
    "depth_not_measured": 4,
    "depth_unavailable": 8,
    "object_form_unknown": 16,
    "multi_object_no_single_depth": 32,
    "folded_dimensions": 128,
}

AXIS_PRECEDENCE = {
    "height": ["clark_copy_measurement", "clark_catalog_stated", "verified_exact_edition_stated", "neutral_renderer_default"],
    "width": ["clark_copy_measurement", "clark_catalog_stated", "verified_exact_edition_stated", "neutral_renderer_default"],
    "depth": ["clark_copy_measurement", "clark_catalog_stated", "verified_exact_edition_stated", "catalog_extent_model", "neutral_renderer_default"],
}

RIGHTS_CONTRACT = {
    "scope": "metadata_only",
    "public_display": True,
    "basis": "source_catalog_record",
    "reuse_status": "not_assessed",
    "image_rights": "not_applicable_no_image_asset",
    "credit_line": "Physical description: Clark Library Catalog",
}


def _compact_number(value: Any) -> Optional[int | float]:
    """Return a finite compact JSON number, folding whole floats to integers."""

    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number != number or number in (float("inf"), float("-inf")):
        return None
    return int(number) if number.is_integer() else round(number, 2)


def _measure(raw: Mapping[str, Any], axis: str) -> Optional[int | float | list[int | float]]:
    value = _compact_number(raw.get(f"{axis}_cm"))
    minimum = _compact_number(raw.get(f"{axis}_min_cm"))
    maximum = _compact_number(raw.get(f"{axis}_max_cm"))
    if value is None or minimum is None or maximum is None:
        return None
    if not 2 <= minimum <= value <= maximum <= 200:
        return None
    return value if minimum == value == maximum else [value, minimum, maximum]


def _depth(raw: Mapping[str, Any]) -> Optional[list[int | float]]:
    if raw.get("status") != "estimated" or raw.get("method") != DEPTH_METHOD:
        return None
    value = _compact_number(raw.get("value_cm"))
    minimum = _compact_number(raw.get("min_cm"))
    maximum = _compact_number(raw.get("max_cm"))
    basis_pages = _compact_number(raw.get("basis_pages"))
    if None in (value, minimum, maximum, basis_pages):
        return None
    if not 0 < minimum <= value <= maximum <= 25:
        return None
    if not isinstance(basis_pages, int) or not 0 < basis_pages <= 10000:
        return None
    return [value, minimum, maximum, basis_pages]


def _validate_profiles(raw: Mapping[str, Any]) -> tuple[Mapping[str, Any], Mapping[str, Any]]:
    source = raw.get("source") if isinstance(raw.get("source"), Mapping) else {}
    items = raw.get("items") if isinstance(raw.get("items"), Mapping) else {}
    if raw.get("schema") != PROFILE_SCHEMA:
        raise ValueError(f"input schema must be {PROFILE_SCHEMA}")
    if source.get("catalog") != "Clark Library Catalog":
        raise ValueError("input must be sourced from the Clark Library Catalog")
    if not SHA256_RE.fullmatch(str(source.get("dataset_sha256") or "")):
        raise ValueError("input source dataset checksum is missing or invalid")
    record_count = source.get("record_count")
    if not isinstance(record_count, int) or record_count < 0 or len(items) != record_count:
        raise ValueError("input item count does not match its source record count")
    return source, items


def _object_form(profile: Mapping[str, Any]) -> int:
    """Classify only forms supported by the Clark physical description."""

    source_format = str(profile.get("source_format") or "")
    primary = source_format.split("+", 1)[0].split(";", 1)[0].split(":", 1)[0].lower()
    extent = profile.get("extent") if isinstance(profile.get("extent"), Mapping) else {}
    binding = profile.get("binding") if isinstance(profile.get("binding"), Mapping) else {}
    term = str(binding.get("term") or "")
    if re.search(r"\bvolumes\b", primary) or int(extent.get("volumes") or 0) > 1:
        return 3
    if re.search(r"\bvolume\b", primary) or int(extent.get("volumes") or 0) == 1:
        return 2
    if re.search(r"\b(?:accordion[ -]folded|folded)\s+sheets?\b", primary) or term == "accordion-folded":
        return 4
    if re.search(r"\bsheets?\b", primary) or int(extent.get("sheets") or 0) > 0:
        return 5
    if re.search(r"\bportfolios?\b", primary) or term == "portfolio":
        return 6
    if re.search(r"\b(?:folders?|envelopes?|enclosures?|containers?|boxes?)\b", primary) or term in HOUSING_CODES:
        return 7
    if re.search(r"\bposters?\b", primary):
        return 8
    if re.search(r"\b(?:cards?|postcards?)\b", primary):
        return 9
    if re.search(r"\bslides?\b", primary):
        return 10
    if re.search(r"\b(?:audio|computer optical|video)\s+discs?\b", primary):
        return 11
    if re.search(r"\bparts?\b", primary):
        return 12
    if re.search(r"\bnumbers?\b", primary):
        return 13
    if re.search(r"\bmaps?\b", primary):
        return 14
    if int(extent.get("pages") or 0) > 0 or int(extent.get("leaves") or 0) > 0:
        return 1
    return 0


def _warning_bits(item: Mapping[str, Any]) -> int:
    bits = 0
    if "h" not in item:
        bits |= WARNING_BITS["height_unavailable"]
    if "w" not in item:
        bits |= WARNING_BITS["width_unavailable"]
    bits |= WARNING_BITS["depth_not_measured"] if "d" in item else WARNING_BITS["depth_unavailable"]
    if item.get("o") == 0:
        bits |= WARNING_BITS["object_form_unknown"]
    if item.get("o") == 3 and "d" not in item:
        bits |= WARNING_BITS["multi_object_no_single_depth"]
    if item.get("f") == 1:
        bits |= WARNING_BITS["folded_dimensions"]
    return bits


def build_index(raw: Mapping[str, Any], input_path: Path, id_prefix: str = DEFAULT_ID_PREFIX) -> dict[str, Any]:
    source, profiles = _validate_profiles(raw)
    if not id_prefix or not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]*", id_prefix):
        raise ValueError("ID prefix must be a safe non-empty token")
    if any(not str(record_id).startswith(id_prefix) for record_id in profiles):
        raise ValueError(f"all record IDs must begin with {id_prefix!r}")

    compact_items: dict[str, dict[str, Any]] = {}

    for record_id in sorted(profiles):
        profile = profiles[record_id]
        if not isinstance(profile, Mapping):
            raise ValueError(f"profile {record_id!r} is not an object")
        item: dict[str, Any] = {"o": _object_form(profile)}
        dimensions = profile.get("dimensions")
        if isinstance(dimensions, Mapping) and dimensions and dimensions.get("status") != "stated":
            raise ValueError(f"profile {record_id!r} has non-Clark dimension status")
        if isinstance(dimensions, Mapping) and dimensions.get("status") == "stated":
            if dimensions.get("order") != "height_x_width":
                raise ValueError(f"profile {record_id!r} has an unsupported dimension convention")
            height = _measure(dimensions, "height")
            width = _measure(dimensions, "width")
            if height is not None:
                item["h"] = height
            if width is not None:
                item["w"] = width
            if dimensions.get("presentation") == "folded":
                item["f"] = 1

        thickness = profile.get("thickness")
        if isinstance(thickness, Mapping):
            depth = _depth(thickness)
            if depth is not None:
                item["d"] = depth
            elif thickness:
                raise ValueError(
                    f"profile {record_id!r} has non-Clark or non-modeled thickness; "
                    "the spine index accepts only catalog-extent-model-v1 estimates"
                )

        binding = profile.get("binding")
        if isinstance(binding, Mapping) and binding and binding.get("status") != "stated":
            raise ValueError(f"profile {record_id!r} has non-Clark binding status")
        if isinstance(binding, Mapping) and binding.get("status") == "stated":
            term = str(binding.get("term") or "")
            if term in BINDING_CODES:
                item["b"] = BINDING_CODES[term]
            elif term in HOUSING_CODES:
                item["g"] = HOUSING_CODES[term]
            else:
                raise ValueError(f"profile {record_id!r} has an unencodable binding or housing term")

        item["q"] = _warning_bits(item)
        compact_items[str(record_id)[len(id_prefix):]] = item

    generated_at = str(raw.get("generated_at") or "1970-01-01T00:00:00Z")
    summary = {
        "catalog_records": int(source["record_count"]),
        "indexed_records": len(compact_items),
        "defaulted_unavailable": int(source["record_count"]) - len(compact_items),
        "geometry_unavailable": sum("h" not in item and "d" not in item for item in compact_items.values()),
        "height_stated": sum("h" in item for item in compact_items.values()),
        "width_stated": sum("w" in item for item in compact_items.values()),
        "depth_estimated": sum("d" in item for item in compact_items.values()),
        "binding_stated": sum("b" in item for item in compact_items.values()),
        "housing_stated": sum("g" in item for item in compact_items.values()),
        "object_form_unknown": sum(item.get("o") == 0 for item in compact_items.values()),
        "folded_presentation": sum(item.get("f") == 1 for item in compact_items.values()),
    }
    return {
        "schema": SCHEMA,
        "version": VERSION,
        "generated_at": generated_at,
        "source": {
            "catalog": "Clark Library Catalog",
            "dataset": str(source.get("dataset") or "sekula_index.json"),
            "dataset_sha256": source["dataset_sha256"],
            "record_count": int(source["record_count"]),
            "physical_description_field": "formats",
            "profile_dataset": input_path.name,
            "profile_dataset_sha256": f"sha256:{hashlib.sha256(input_path.read_bytes()).hexdigest()}",
            "profile_schema": PROFILE_SCHEMA,
        },
        "policy": {
            "dimensions": "Height and width are transcribed only from Clark catalog physical descriptions.",
            "depth": "Every d value is an interface estimate from Clark-stated extent using catalog-extent-model-v1; it is not a measurement of the Clark copy.",
            "covers": "Cover images and provider-edition geometry are not inputs to this index.",
            "full_provenance": "Load book_profiles.json#{id} only when a full physical-evidence view is opened.",
        },
        "contract": {
            "representation_type": "synthetic_metadata_derived",
            "scope": "clark_catalog_metadata",
            "rights": RIGHTS_CONTRACT,
            "axis_precedence": AXIS_PRECEDENCE,
            "shared_warnings": [
                {
                    "code": "synthetic_metadata_representation",
                    "message": "Shelf geometry is a metadata-derived representation, not a photograph or measurement of Clark's copy.",
                }
            ],
        },
        "encoding": {
            "id_prefix": id_prefix,
            "fields": {
                "h": "Clark-stated height cm: scalar when exact, otherwise [midpoint, minimum, maximum].",
                "w": "Clark-stated front width cm: scalar when exact, otherwise [midpoint, minimum, maximum].",
                "d": "Modeled depth cm: [midpoint, minimum, maximum, Clark-stated page-equivalent basis].",
                "b": "Clark-stated binding code from binding_codes.",
                "g": "Clark-stated housing code from housing_codes.",
                "f": "1 when h/w are the Clark-stated folded presentation dimensions.",
                "o": "Object-form code from object_form_codes; unknown is explicit.",
                "q": "Record warning bitset from warning_bits; decoded warnings are mandatory.",
            },
            "binding_codes": {str(code): term for term, code in BINDING_CODES.items()},
            "housing_codes": {str(code): term for term, code in HOUSING_CODES.items()},
            "object_form_codes": {str(code): descriptor for code, descriptor in OBJECT_FORMS.items()},
            "warning_bits": {str(bit): code for code, bit in WARNING_BITS.items()},
        },
        "summary": summary,
        "items": compact_items,
    }


def write_manifest(path: Path, manifest: Mapping[str, Any]) -> None:
    """Write stable, reviewable JSON with each compact record on one line."""

    header = {key: value for key, value in manifest.items() if key != "items"}
    text = json.dumps(header, ensure_ascii=False, indent=2)
    text = text[:-2] + ",\n  \"items\": {\n"
    rows = list(manifest["items"].items())
    for index, (record_id, item) in enumerate(rows):
        comma = "," if index < len(rows) - 1 else ""
        text += f"    {json.dumps(record_id)}: {json.dumps(item, ensure_ascii=False, separators=(',', ':'))}{comma}\n"
    text += "  }\n}\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def self_test() -> None:
    fixture = {
        "schema": PROFILE_SCHEMA,
        "version": "1.0.0",
        "generated_at": "2026-07-13T04:00:00Z",
        "source": {
            "catalog": "Clark Library Catalog",
            "dataset": "sekula_index.json",
            "dataset_sha256": f"sha256:{'a' * 64}",
            "record_count": 3,
        },
        "items": {
            "alma1": {
                "status": "parsed",
                "source_format": "300 pages ; 24 x 18 cm ; paperback",
                "dimensions": {
                    "status": "stated", "height_cm": 24, "height_min_cm": 24, "height_max_cm": 24,
                    "width_cm": 18, "width_min_cm": 17, "width_max_cm": 19,
                    "order": "height_x_width", "presentation": "as_cataloged",
                },
                "thickness": {
                    "status": "estimated", "value_cm": 2, "min_cm": 1.5, "max_cm": 2.5,
                    "basis_pages": 300, "method": DEPTH_METHOD,
                },
                "binding": {"status": "stated", "term": "paperback"},
                "extent": {"status": "stated", "pages": 300},
            },
            "alma2": {
                "status": "parsed",
                "source_format": "1 folded sheet ; 28 cm",
                "dimensions": {
                    "status": "stated", "height_cm": 28, "height_min_cm": 28, "height_max_cm": 28,
                    "order": "height_x_width", "presentation": "folded",
                },
            },
            "alma3": {"status": "unavailable"},
        },
    }
    # The fixture checksum is deterministic and intentionally independent of a
    # local file; production generation hashes the real input bytes.
    with tempfile.TemporaryDirectory() as temporary_directory:
        fixture_path = Path(temporary_directory) / "book_profiles.json"
        fixture_path.write_bytes(json.dumps(fixture, sort_keys=True).encode())
        first = build_index(fixture, fixture_path, "alma")
        second = build_index(fixture, fixture_path, "alma")
    assert first == second
    assert first["items"] == {
        "1": {"o": 1, "h": 24, "w": [18, 17, 19], "d": [2, 1.5, 2.5, 300], "b": 4, "q": 4},
        "2": {"o": 4, "h": 28, "f": 1, "q": 138},
        "3": {"o": 0, "q": 27},
    }
    assert first["summary"]["defaulted_unavailable"] == 0
    assert first["summary"]["geometry_unavailable"] == 1
    assert first["contract"]["representation_type"] == "synthetic_metadata_derived"
    assert first["contract"]["rights"]["image_rights"] == "not_applicable_no_image_asset"
    assert first["policy"]["covers"].startswith("Cover images")

    unsafe = json.loads(json.dumps(fixture))
    unsafe["items"]["alma1"]["thickness"]["status"] = "external_edition_stated"
    try:
        with tempfile.TemporaryDirectory() as temporary_directory:
            temporary = Path(temporary_directory) / "book_profiles.json"
            temporary.write_text(json.dumps(unsafe), encoding="utf-8")
            build_index(unsafe, temporary, "alma")
    except ValueError as error:
        assert "accepts only" in str(error)
    else:
        raise AssertionError("external edition thickness must be rejected")
    print("spine index self-test passed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--id-prefix", default=DEFAULT_ID_PREFIX)
    parser.add_argument("--self-test", action="store_true")
    arguments = parser.parse_args()
    if arguments.self_test:
        self_test()
        return 0
    try:
        raw = json.loads(arguments.input.read_text(encoding="utf-8"))
        manifest = build_index(raw, arguments.input, arguments.id_prefix)
        write_manifest(arguments.output, manifest)
    except (OSError, json.JSONDecodeError, ValueError) as error:
        parser.error(str(error))
    print(json.dumps(manifest["summary"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
