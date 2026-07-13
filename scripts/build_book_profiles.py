#!/usr/bin/env python3
"""Build physical book profiles from Clark catalog descriptions.

Only the catalog ``formats`` field is treated as factual.  Thickness is an
explicit estimate derived from the stated page/leaf extent; the generator does
not claim to have measured any object.  The committed manifest is intentionally
network-free and reproducible from ``sekula_index.json``.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Optional


SCHEMA = "shelfsignals-book-profiles@1"
VERSION = "1.0.0"
DEFAULT_INPUT = Path("docs/data/sekula_index.json")
DEFAULT_OUTPUT = Path("docs/data/book_profiles.json")

UNICODE_FRACTIONS = {
    "¼": 1 / 4,
    "½": 1 / 2,
    "¾": 3 / 4,
    "⅓": 1 / 3,
    "⅔": 2 / 3,
    "⅛": 1 / 8,
    "⅜": 3 / 8,
    "⅝": 5 / 8,
    "⅞": 7 / 8,
}
FRACTION_GLYPHS = "".join(UNICODE_FRACTIONS)
NUMBER_PATTERN = rf"(?:\d+(?:\.\d+)?(?:\s+\d+\s*/\s*\d+)?|\d+\s*[{FRACTION_GLYPHS}]|\d+\s*/\s*\d+)"
RANGE_PATTERN = rf"{NUMBER_PATTERN}(?:\s*[-–]\s*{NUMBER_PATTERN})?"
SIZE_RE = re.compile(
    rf"(?<![\d/])(?P<height>{RANGE_PATTERN})(?:\s*[x×X]\s*(?P<width>{RANGE_PATTERN}))?\s*cm\b",
    re.IGNORECASE,
)
FOLDED_RE = re.compile(r"\bfolded\s+to\b", re.IGNORECASE)
EXTENT_TOKEN_PATTERN = r"(?:[ivxlcdm]+|\d{1,3}(?:,\d{3})+|\d+)"
EXTENT_GROUP_RE = re.compile(
    rf"(?<![\w-])(?P<values>(?:\[?{EXTENT_TOKEN_PATTERN}(?:\s*[-–]\s*{EXTENT_TOKEN_PATTERN})?\]?\s*,?\s*)+)"
    r"(?:(?:approximately|about)\s+)?(?:unnumbered\s+)?(?P<unit>pages?|leaves|leafs|sheets?|volumes?)\b",
    re.IGNORECASE,
)

BINDING_PATTERNS = (
    ("accordion-folded", re.compile(r"\baccordion[ -]folded\b", re.IGNORECASE)),
    ("loose-leaf-binder", re.compile(r"\bloose[ -]leaf\s+binder\b", re.IGNORECASE)),
    ("loose-leaf", re.compile(r"\bloose[ -]leaf\b", re.IGNORECASE)),
    ("saddle-stitched", re.compile(r"\bsaddle[ -]stitched\b", re.IGNORECASE)),
    ("spiral-bound", re.compile(r"\bspiral[ -](?:bound|binding)\b", re.IGNORECASE)),
    ("comb-bound", re.compile(r"\bcomb[ -](?:bound|binding)\b", re.IGNORECASE)),
    ("casebound", re.compile(r"\bcase[ -]?bound\b", re.IGNORECASE)),
    ("hardcover", re.compile(r"\b(?:hardcover|hardback)\b", re.IGNORECASE)),
    ("paperback", re.compile(r"\bpaperback\b", re.IGNORECASE)),
    ("cloth", re.compile(r"\bcloth(?:bound)?\b", re.IGNORECASE)),
    ("boards", re.compile(r"\bboards?\b", re.IGNORECASE)),
    ("wrappers", re.compile(r"\bwrappers?\b", re.IGNORECASE)),
    ("stapled", re.compile(r"\bstapled\b", re.IGNORECASE)),
    ("portfolio", re.compile(r"\bportfolio\b", re.IGNORECASE)),
    ("slipcase", re.compile(r"\bslipcase\b", re.IGNORECASE)),
    ("folder", re.compile(r"^\s*\d+\s+folders?\b", re.IGNORECASE)),
    ("envelope", re.compile(r"^\s*\d+\s+envelopes?\b", re.IGNORECASE)),
    ("binder", re.compile(r"\bbinder\b", re.IGNORECASE)),
    ("case", re.compile(r"\bin (?:a )?case\b", re.IGNORECASE)),
    ("box", re.compile(r"\bin (?:a )?box\b", re.IGNORECASE)),
    ("container", re.compile(r"\bin (?:a )?container\b", re.IGNORECASE)),
)


def utc_now() -> str:
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    moment = datetime.fromtimestamp(int(epoch), timezone.utc) if epoch else datetime.now(timezone.utc)
    return moment.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _round(value: float) -> float:
    return round(value + 1e-10, 2)


def parse_number(value: str) -> Optional[float]:
    """Parse decimals, ASCII fractions, and common Unicode fractions."""

    text = str(value or "").strip()
    glyph = next((character for character in text if character in UNICODE_FRACTIONS), None)
    if glyph:
        whole = re.sub(rf"[{FRACTION_GLYPHS}]", "", text).strip()
        try:
            return float(whole or 0) + UNICODE_FRACTIONS[glyph]
        except ValueError:
            return None
    mixed = re.fullmatch(r"(?:(\d+(?:\.\d+)?)\s+)?(\d+)\s*/\s*(\d+)", text)
    if mixed:
        whole, numerator, denominator = mixed.groups()
        if int(denominator) == 0:
            return None
        return float(whole or 0) + int(numerator) / int(denominator)
    try:
        return float(text)
    except ValueError:
        return None


def parse_measure(value: str) -> Optional[dict[str, float]]:
    parts = re.split(r"\s*[-–]\s*", str(value or "").strip(), maxsplit=1)
    numbers = [parse_number(part) for part in parts]
    if any(number is None for number in numbers):
        return None
    ordered = sorted(float(number) for number in numbers if number is not None)
    lower, upper = ordered[0], ordered[-1]
    if lower < 2 or upper > 200:
        return None
    return {"value": _round((lower + upper) / 2), "min": _round(lower), "max": _round(upper)}


def _dimension_payload(match: re.Match[str]) -> Optional[dict[str, Any]]:
    height = parse_measure(match.group("height"))
    width = parse_measure(match.group("width")) if match.group("width") else None
    if not height:
        return None
    payload: dict[str, Any] = {
        "height_cm": height["value"],
        "height_min_cm": height["min"],
        "height_max_cm": height["max"],
    }
    if width:
        payload.update(
            width_cm=width["value"],
            width_min_cm=width["min"],
            width_max_cm=width["max"],
        )
    return payload


def _combine_dimension_payloads(first: Mapping[str, Any], second: Mapping[str, Any]) -> dict[str, Any]:
    combined: dict[str, Any] = {}
    for axis in ("height", "width"):
        minimums = [payload.get(f"{axis}_min_cm") for payload in (first, second)]
        maximums = [payload.get(f"{axis}_max_cm") for payload in (first, second)]
        if any(value is None for value in minimums + maximums):
            continue
        lower, upper = min(minimums), max(maximums)
        combined[f"{axis}_cm"] = _round((lower + upper) / 2)
        combined[f"{axis}_min_cm"] = _round(lower)
        combined[f"{axis}_max_cm"] = _round(upper)
    return combined


def primary_dimension_description(description: str) -> str:
    text = str(description or "")
    if "+" not in text:
        return text
    first, remainder = text.split("+", 1)
    if re.search(r"\bcm\b", first, re.IGNORECASE):
        return first
    second = remainder.split("+", 1)[0]
    extended = first + "+" + second
    return extended if re.search(r"\bcm\b", extended, re.IGNORECASE) else first


def parse_dimensions(description: str) -> Optional[dict[str, Any]]:
    """Parse the primary object's H×W dimensions, ignoring material after ``+``."""

    primary = primary_dimension_description(description)
    matches = list(SIZE_RE.finditer(primary))
    if not matches:
        return None

    folded = FOLDED_RE.search(primary)
    selected = None
    if folded:
        after_fold = [match for match in matches if match.start() >= folded.end()]
        selected = after_fold[0] if after_fold else matches[-1]
    else:
        selected = matches[-1]
    dimensions = _dimension_payload(selected)
    if not folded and len(matches) > 1:
        for first, second in zip(matches, matches[1:]):
            if re.fullmatch(r"\s*[-–]\s*", primary[first.end(): second.start()]):
                first_payload = _dimension_payload(first)
                second_payload = _dimension_payload(second)
                if first_payload and second_payload:
                    dimensions = _combine_dimension_payloads(first_payload, second_payload)
                break
    if not dimensions:
        return None
    dimensions.update(status="stated", order="height_x_width", presentation="folded" if folded else "as_cataloged")

    if folded:
        before = [match for match in matches if match.end() <= folded.start()]
        if before:
            unfolded = _dimension_payload(before[-1])
            if unfolded and unfolded != {key: dimensions[key] for key in unfolded}:
                dimensions["unfolded"] = unfolded
        else:
            # Some records omit the first ``cm``: ``56 x 43 (folded to 28 x 22 cm)``.
            unitless = re.search(
                rf"(?P<height>{RANGE_PATTERN})\s*[x×X]\s*(?P<width>{RANGE_PATTERN})\s*[,(]?\s*$",
                primary[: folded.start()],
                re.IGNORECASE,
            )
            if unitless:
                unfolded = _dimension_payload(unitless)
                if unfolded:
                    dimensions["unfolded"] = unfolded
    return dimensions


def roman_to_int(value: str) -> Optional[int]:
    text = value.lower()
    if not text or not re.fullmatch(r"[ivxlcdm]+", text):
        return None
    values = {"i": 1, "v": 5, "x": 10, "l": 50, "c": 100, "d": 500, "m": 1000}
    total = 0
    previous = 0
    for character in reversed(text):
        current = values[character]
        total += -current if current < previous else current
        previous = max(previous, current)
    return total if 0 < total < 5000 else None


def extent_token_count(token: str) -> Optional[int]:
    clean = str(token or "").strip().strip("[]")
    parts = re.split(r"\s*[-–]\s*", clean, maxsplit=1)

    def number(part: str) -> Optional[int]:
        return int(part.replace(",", "")) if re.fullmatch(r"(?:\d+|\d{1,3}(?:,\d{3})+)", part) else roman_to_int(part)

    start = number(parts[0])
    if start is None:
        return None
    if len(parts) == 1:
        return start
    end = number(parts[1])
    if end is None:
        return None
    return abs(end - start) + 1


def parse_extent(description: str) -> Optional[dict[str, Any]]:
    """Extract page/leaf/sheet/volume extent from the primary object."""

    primary = str(description or "").split("+", 1)[0]
    totals = {"pages": 0, "leaves": 0, "sheets": 0, "volumes": 0}
    found: set[str] = set()
    for match in EXTENT_GROUP_RE.finditer(primary):
        unit = match.group("unit").lower()
        key = "leaves" if unit in ("leaf", "leafs", "leaves") else unit.rstrip("s") + "s"
        tokens = re.findall(rf"\[?{EXTENT_TOKEN_PATTERN}(?:\s*[-–]\s*{EXTENT_TOKEN_PATTERN})?\]?", match.group("values"), re.IGNORECASE)
        counts = [extent_token_count(token) for token in tokens]
        valid = [count for count in counts if count is not None]
        if valid:
            totals[key] += sum(valid)
            found.add(key)
    if not found:
        return None
    return {"status": "stated", **{key: totals[key] for key in ("pages", "leaves", "sheets", "volumes") if key in found}}


def parse_binding(description: str) -> Optional[dict[str, str]]:
    primary = str(description or "").split("+", 1)[0]
    for term, pattern in BINDING_PATTERNS:
        if pattern.search(primary):
            return {"status": "stated", "term": term}
    return None


def estimate_thickness(
    extent: Optional[Mapping[str, Any]],
    binding: Optional[Mapping[str, Any]],
    description: str = "",
) -> Optional[dict[str, Any]]:
    """Estimate a closed book's spine thickness; never return it as measured fact."""

    if not extent:
        return None
    volumes = int(extent.get("volumes") or 1)
    if volumes > 1:
        return None
    if int(extent.get("sheets") or 0) > 0:
        return None
    term = str((binding or {}).get("term") or "")
    if term in {
        "accordion-folded", "portfolio", "binder", "loose-leaf-binder", "loose-leaf",
        "case", "box", "folder", "envelope", "slipcase", "container",
    }:
        return None
    if re.match(
        r"^\s*\d+\s+(?:(?:accordion\s+)?folded\s+)?(?:sheets?|posters?|cards?|postcards?|folders?|envelopes?|slides?|photographs?|portfolios?|maps?|prints?|broadsides?|objects?)\b",
        str(description or ""),
        re.IGNORECASE,
    ):
        return None
    page_equivalent = int(extent.get("pages") or 0) + 2 * int(extent.get("leaves") or 0)
    if page_equivalent <= 0:
        return None
    cover_allowances = {
        "paperback": (0.12, 0.25),
        "hardcover": (0.35, 0.65),
        "casebound": (0.35, 0.65),
        "cloth": (0.30, 0.60),
        "boards": (0.30, 0.60),
        "wrappers": (0.10, 0.24),
        "stapled": (0.06, 0.16),
        "saddle-stitched": (0.06, 0.16),
    }
    cover_min, cover_max = cover_allowances.get(term, (0.18, 0.45))
    # Typical book paper is roughly 0.08–0.14 mm per leaf, represented here
    # as 0.004–0.007 cm per printed page plus the cover allowance.
    minimum = page_equivalent * 0.004 + cover_min
    maximum = page_equivalent * 0.007 + cover_max
    return {
        "status": "estimated",
        "value_cm": _round((minimum + maximum) / 2),
        "min_cm": _round(minimum),
        "max_cm": _round(maximum),
        "basis_pages": page_equivalent,
        "method": "catalog-extent-model-v1",
    }


def parse_physical_description(description: str) -> dict[str, Any]:
    source_format = re.sub(r"\s+", " ", str(description or "")).strip()
    if not source_format:
        return {"status": "unavailable"}
    dimensions = parse_dimensions(source_format)
    extent = parse_extent(source_format)
    binding = parse_binding(source_format)
    thickness = estimate_thickness(extent, binding, source_format)
    profile: dict[str, Any] = {"status": "parsed" if any((dimensions, extent, binding)) else "unavailable", "source_format": source_format}
    if dimensions:
        profile["dimensions"] = dimensions
    if extent:
        profile["extent"] = extent
    if binding:
        profile["binding"] = binding
    if thickness:
        profile["thickness"] = thickness
    return profile


def _profile_score(profile: Mapping[str, Any]) -> tuple[int, int, int, int]:
    return (
        int("dimensions" in profile),
        int("extent" in profile),
        int("binding" in profile),
        len(str(profile.get("source_format") or "")),
    )


def profile_record(record: Mapping[str, Any]) -> dict[str, Any]:
    formats = record.get("formats")
    values: Iterable[Any] = formats if isinstance(formats, list) else ([] if formats in (None, "") else [formats])
    candidates = [parse_physical_description(str(value or "")) for value in values]
    if not candidates:
        return {"status": "unavailable"}
    return max(candidates, key=_profile_score)


def build_manifest(records: list[Mapping[str, Any]], input_path: Path) -> dict[str, Any]:
    items = {str(record.get("id") or ""): profile_record(record) for record in records if str(record.get("id") or "")}
    summary = {
        "records": len(items),
        "dimensions_stated": sum("dimensions" in profile for profile in items.values()),
        "extent_stated": sum("extent" in profile for profile in items.values()),
        "binding_or_housing_stated": sum("binding" in profile for profile in items.values()),
        "thickness_estimated": sum("thickness" in profile for profile in items.values()),
        "unavailable": sum(profile["status"] == "unavailable" for profile in items.values()),
    }
    digest = hashlib.sha256(input_path.read_bytes()).hexdigest()
    return {
        "schema": SCHEMA,
        "version": VERSION,
        "generated_at": utc_now(),
        "source": {
            "catalog": "Clark Library Catalog",
            "dataset": input_path.name,
            "dataset_sha256": f"sha256:{digest}",
            "record_count": len(records),
            "record_url_field": "record_url",
            "physical_description_field": "formats",
            "policy": "Stated values come only from the catalog formats field; accompanying material after '+' is excluded.",
        },
        "methodology": {
            "dimensions": "Centimeters are parsed as H x W (height first); ranges retain bounds and use their midpoint; folded-to size is the display size.",
            "thickness": "Modeled only for book-like, single-volume records from stated page/leaf extent using 0.004-0.007 cm per page plus a cover allowance; folded sheets, housings, loose-leaf objects, and non-book carriers are excluded; never a measured value.",
        },
        "summary": summary,
        "items": items,
    }


def self_test() -> None:
    assert parse_dimensions("116 pages ; 24 x 28 cm") == {
        "height_cm": 24.0, "height_min_cm": 24.0, "height_max_cm": 24.0,
        "width_cm": 28.0, "width_min_cm": 28.0, "width_max_cm": 28.0,
        "status": "stated", "order": "height_x_width", "presentation": "as_cataloged",
    }
    ranged = parse_dimensions("volumes ; 31-33 cm")
    assert ranged and ranged["height_cm"] == 32 and ranged["height_min_cm"] == 31 and ranged["height_max_cm"] == 33
    varied = parse_dimensions("4 cards ; 11 x 23 cm - 13 x 18 cm")
    assert varied and varied["height_cm"] == 12 and varied["width_cm"] == 20.5
    fraction = parse_dimensions("277 pages ; 25 x 31 1/2 cm")
    assert fraction and fraction["width_cm"] == 31.5
    folded = parse_dimensions("1 sheet ; 56 x 43 (folded to 28 x 22 cm) + disc (12 cm)")
    assert folded and folded["height_cm"] == 28 and folded["width_cm"] == 22 and folded["unfolded"]["height_cm"] == 56
    assert parse_dimensions("191 pages ; 29 cm + pamphlet ; 28 x 11 cm")["height_cm"] == 29
    assert parse_dimensions("263 pages : color illustrations + suppl. ; 30 cm +")["height_cm"] == 30
    extent = parse_extent("xv, 619 pages, 14 unnumbered leaves of plates ; 21 cm")
    assert extent == {"status": "stated", "pages": 634, "leaves": 14}
    assert parse_extent("xvi, 1,323 pages") == {"status": "stated", "pages": 1339}
    assert parse_binding("1 accordion folded sheet ; 14 cm")["term"] == "accordion-folded"
    assert parse_binding("1 sheet, in a slipcase ; 26 cm")["term"] == "slipcase"
    estimated = estimate_thickness(extent, None)
    assert estimated and estimated["status"] == "estimated" and estimated["basis_pages"] == 662
    assert estimated["method"] == "catalog-extent-model-v1"
    assert estimate_thickness({"status": "stated", "pages": 8}, {"status": "stated", "term": "accordion-folded"}, "1 accordion folded sheet") is None
    assert estimate_thickness({"status": "stated", "pages": 8, "sheets": 1}, None, "1 folded sheet") is None
    print("book profile parser self-test passed")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--self-test", action="store_true")
    arguments = parser.parse_args()
    if arguments.self_test:
        self_test()
        return 0
    try:
        records = json.loads(arguments.input.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        parser.error(f"could not read input: {error}")
    if not isinstance(records, list):
        parser.error("input must be a JSON array")
    manifest = build_manifest(records, arguments.input)
    arguments.output.parent.mkdir(parents=True, exist_ok=True)
    arguments.output.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(manifest["summary"], sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
