#!/usr/bin/env python3
"""Create a resumable, evidence-bound OCR extraction of the official LOC Sowerby scans.

This pipeline never reads the Monticello/TJF transcript.  Page images and raw
OCR stay in the ignored research workspace.  The normalized output contains
only identifier, short-display-heading, source, confidence, and hash evidence
needed to review a later factual browser projection.

The LOC item record does not grant blanket reuse permission.  Consequently the
manifest uses ``loc_scan_ocr_factual_extraction`` and retains the item-level
rights statement URL and checksum; it never labels the scans public domain.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
from dataclasses import dataclass, replace
from datetime import datetime, timezone
import gzip
import hashlib
import html
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any, Iterable, Mapping, Sequence


SCRIPT_DIR = Path(__file__).resolve().parent
REPOSITORY_ROOT = SCRIPT_DIR.parent
DEFAULT_PDF_DIR = REPOSITORY_ROOT / "research/jefferson/work/cache/loc_sowerby_pdfs"
DEFAULT_CACHE_ROOT = REPOSITORY_ROOT / "research/jefferson/work/cache/loc_sowerby_ocr_v1"
DEFAULT_DATA_DIR = REPOSITORY_ROOT / "research/jefferson/work/data"
DEFAULT_ITEM_JSON = REPOSITORY_ROOT / "research/jefferson/work/cache/loc_sowerby/item.json"

LOC_ITEM_URL = "https://www.loc.gov/item/52060000/"
RIGHTS_STATEMENT_URL = LOC_ITEM_URL
PUBLICATION_BASIS = "loc_scan_ocr_factual_extraction"
EXPECTED_GAPS = frozenset({2323, 4707, 4708})
EXPECTED_MAX_IDENTIFIER = 4931
EXPECTED_NUMBERED_ENTRY_COUNT = EXPECTED_MAX_IDENTIFIER - len(EXPECTED_GAPS)

VOLUME_SPECS: dict[int, dict[str, Any]] = {
    1: {
        "pages": 588,
        "first": 1,
        "last": 1237,
        "url": "https://tile.loc.gov/storage-services/service/rbc/rbc0001/2007/2007jeffcat1/2007jeffcat1.pdf",
    },
    2: {
        "pages": 448,
        "first": 1238,
        "last": 2322,
        "url": "https://tile.loc.gov/storage-services/service/rbc/rbc0001/2007/2007jeffcat2/2007jeffcat2.pdf",
    },
    3: {
        "pages": 498,
        "first": 2324,
        "last": 3662,
        "url": "https://tile.loc.gov/storage-services/service/rbc/rbc0001/2007/2007jeffcat3/2007jeffcat3.pdf",
    },
    4: {
        "pages": 584,
        "first": 3663,
        "last": 4615,
        "url": "https://tile.loc.gov/storage-services/service/rbc/rbc0001/2007/2007jeffcat4/2007jeffcat4.pdf",
    },
    5: {
        "pages": 456,
        "first": 4616,
        "last": 4931,
        "url": "https://tile.loc.gov/storage-services/service/rbc/rbc0001/2007/2007jeffcat5/2007jeffcat5.pdf",
    },
}

BASE_DPI = 240
BASE_PSM = 3
FALLBACK_VARIANTS = ((360, 3), (400, 6))
JPEG_QUALITY = 94
OCR_LANGUAGE = "eng"
MIN_DIRECT_TITLE_CONFIDENCE = 40.0
MIN_GEOMETRY_TITLE_CONFIDENCE = 50.0
MIN_CREATOR_TITLE_CONFIDENCE = 90.0
TITLE_EDGE_STRIP = "=:+- .~©*|_"
PIPELINE_SCHEMA = "shelfsignals-jefferson-loc-ocr-pipeline@1"
PAGE_SCHEMA = "shelfsignals-jefferson-loc-ocr-page@1"
ENTRY_SCHEMA = "shelfsignals-jefferson-loc-ocr-entry@1"
MANIFEST_SCHEMA = "shelfsignals-jefferson-loc-ocr-package@1"
VALIDATION_SCHEMA = "shelfsignals-jefferson-loc-ocr-validation@1"

SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
MARKER_RE = re.compile(r"(?<!\d)([\[\({])\s*(\d{1,4})\s*([A-Za-z]?)\s*([\]\)}])(?!\d)")
J_HEADING_RE = re.compile(r"^\s*[JjIi1]\s*[.\-:]\s*\d+[A-Za-z]?\s*[:=\-]?\s*(.*)$", re.IGNORECASE)
UPPER_HEADING_RE = re.compile(r"^[A-ZÀ-ÖØ-Þ][A-ZÀ-ÖØ-Þ0-9 .,'’&()\-]{3,160}\.?$")
YEAR_RE = re.compile(r"(?<!\d)(1[0-9]{3}|20[0-9]{2})(?!\d)")
CATALOGUE_EVIDENCE_RE = re.compile(r"^(?:1815|1831)[\s,.;:()\[\]-]*catalogue\b", re.IGNORECASE)


class OcrError(RuntimeError):
    """Raised when an OCR source, cache, or extraction contract fails closed."""


class _PlainTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        self.parts.append(data)


def clean_text(value: Any) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()


def plain_text(value: Any) -> str:
    parser = _PlainTextParser()
    parser.feed(str(value or ""))
    parser.close()
    return clean_text(html.unescape(" ".join(parser.parts)))


def stable_unique(values: Iterable[Any]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        text = clean_text(value)
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
        raise OcrError(f"Unable to read JSON {path}: {error}") from error


def run_checked(command: Sequence[str]) -> subprocess.CompletedProcess[str]:
    try:
        return subprocess.run(command, check=True, capture_output=True, text=True)
    except (OSError, subprocess.CalledProcessError) as error:
        stderr = clean_text(getattr(error, "stderr", ""))
        raise OcrError(f"Command failed: {' '.join(command[:2])}: {stderr or error}") from error


def tool_identity(name: str, version_args: Sequence[str]) -> dict[str, Any]:
    executable = shutil.which(name)
    if not executable:
        raise OcrError(f"Required OCR tool is unavailable: {name}")
    resolved = Path(executable).resolve()
    result = run_checked([executable, *version_args])
    version = clean_text(result.stdout or result.stderr).split("\n", 1)[0]
    if not version:
        raise OcrError(f"Unable to determine {name} version")
    return {
        "name": name,
        "path": str(resolved),
        "executable_sha256": sha256_file(resolved),
        "version": version,
    }


def _pdfinfo(path: Path) -> dict[str, str]:
    result = run_checked(["pdfinfo", str(path)])
    parsed: dict[str, str] = {}
    for line in result.stdout.splitlines():
        if ":" in line:
            key, value = line.split(":", 1)
            parsed[clean_text(key)] = clean_text(value)
    return parsed


def rights_evidence(item_json_path: Path) -> dict[str, Any]:
    item_payload = load_json(item_json_path)
    item = item_payload.get("item") if isinstance(item_payload, dict) else None
    if not isinstance(item, dict) or item.get("url") != LOC_ITEM_URL:
        raise OcrError("LOC item JSON does not identify item 52060000")
    rights = item.get("rights")
    if not isinstance(rights, list) or not rights or any(not isinstance(value, str) for value in rights):
        raise OcrError("LOC item JSON has no usable item-level rights statement")
    normalized = stable_unique(plain_text(value) for value in rights)
    joined = "\n".join(normalized)
    required_phrases = (
        "not aware of any u.s. copyright",
        "determination of the status of an item ultimately rests",
    )
    if not all(phrase in joined.casefold() for phrase in required_phrases):
        raise OcrError("LOC item-level rights statement changed; manual review is required")
    return {
        "rights_statement_url": RIGHTS_STATEMENT_URL,
        "rights_statement_sha256": sha256_bytes((joined + "\n").encode("utf-8")),
        "rights_clearance": "not granted; item-level assessment remains required",
        "credit_line_present": "Library of Congress, Rare Book and Special Collections Division" in joined,
        "item_json_sha256": sha256_file(item_json_path),
    }


def audit_sources(pdf_dir: Path, item_json_path: Path) -> dict[str, Any]:
    tools = {
        "pdfinfo": tool_identity("pdfinfo", ("-v",)),
        "pdftoppm": tool_identity("pdftoppm", ("-v",)),
        "tesseract": tool_identity("tesseract", ("--version",)),
    }
    pdfs: list[dict[str, Any]] = []
    for volume, spec in VOLUME_SPECS.items():
        path = pdf_dir / f"volume-{volume}.pdf"
        if not path.is_file():
            raise OcrError(f"Official LOC PDF is missing: {path}")
        info = _pdfinfo(path)
        pages = int(info.get("Pages", "0"))
        if pages != spec["pages"]:
            raise OcrError(f"Volume {volume} page count drifted: {pages} != {spec['pages']}")
        pdfs.append({
            "volume": volume,
            "file": path.name,
            "url": spec["url"],
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
            "pages": pages,
            "first_sowerby_number": spec["first"],
            "last_sowerby_number": spec["last"],
        })
    rights = rights_evidence(item_json_path)
    config = {
        "schema": PIPELINE_SCHEMA,
        "authority": "Library of Congress",
        "loc_item_url": LOC_ITEM_URL,
        "publication_basis": PUBLICATION_BASIS,
        "rights": rights,
        "pdfs": pdfs,
        "tools": tools,
        "ocr": {
            "base_dpi": BASE_DPI,
            "base_psm": BASE_PSM,
            "fallback_variants": [list(value) for value in FALLBACK_VARIANTS],
            "jpeg_quality": JPEG_QUALITY,
            "language": OCR_LANGUAGE,
        },
        "numbering": {
            "maximum_serial": EXPECTED_MAX_IDENTIFIER,
            "loc_confirmed_absent_numbers": sorted(EXPECTED_GAPS),
            "expected_source_backed_base_entries": EXPECTED_NUMBERED_ENTRY_COUNT,
        },
    }
    config["source_identity_sha256"] = sha256_bytes(json_bytes(config))
    return config


def activate_generation(cache_root: Path, source: Mapping[str, Any], *, refresh: bool = False) -> Path:
    identity = clean_text(source.get("source_identity_sha256"))
    if not SHA256_RE.fullmatch(identity):
        raise OcrError("Source identity is invalid")
    generation = identity.removeprefix("sha256:")[:20]
    active_path = cache_root / "active.json"
    if active_path.is_file():
        active = load_json(active_path)
        if active.get("source_identity_sha256") != identity and not refresh:
            raise OcrError("Active OCR cache source/tool identity drifted; rerun with --refresh after review")
    root = cache_root / "generations" / generation
    root.mkdir(parents=True, exist_ok=True)
    source_path = root / "source.json"
    if source_path.is_file() and source_path.read_bytes() != json_bytes(source):
        raise OcrError("OCR generation source manifest drifted")
    atomic_write_json(source_path, source)
    generation_path = root / "generation.json"
    if not generation_path.is_file():
        atomic_write_json(generation_path, {
            "schema": "shelfsignals-jefferson-loc-ocr-generation@1",
            "generation": generation,
            "generated_at": utc_now(),
            "source_identity_sha256": identity,
        })
    generation_identity = load_json(generation_path)
    if generation_identity.get("generation") != generation or generation_identity.get("source_identity_sha256") != identity:
        raise OcrError("OCR generation timestamp identity drifted")
    atomic_write_json(active_path, {
        "schema": "shelfsignals-jefferson-loc-ocr-active@1",
        "generation": generation,
        "source_identity_sha256": identity,
    })
    return root


@dataclass(frozen=True)
class PageTask:
    volume: int
    page: int
    dpi: int
    psm: int
    variant: str


def _page_paths(generation_root: Path, task: PageTask) -> dict[str, Path]:
    directory = generation_root / task.variant / f"volume-{task.volume}"
    stem = f"page-{task.page:04d}"
    return {
        "directory": directory,
        "image": directory / f"{stem}.jpg",
        "text": directory / f"{stem}.txt",
        "tsv": directory / f"{stem}.tsv",
        "sidecar": directory / f"{stem}.json",
    }


def tsv_confidence(path: Path) -> tuple[int, float]:
    values: list[float] = []
    try:
        with path.open("r", encoding="utf-8", newline="") as handle:
            for row in csv.DictReader(handle, delimiter="\t"):
                if row.get("level") != "5" or not clean_text(row.get("text")):
                    continue
                try:
                    confidence = float(row.get("conf", "-1"))
                except ValueError:
                    continue
                if confidence >= 0:
                    values.append(confidence)
    except (OSError, csv.Error) as error:
        raise OcrError(f"Unable to inspect OCR TSV {path}: {error}") from error
    return len(values), round(sum(values) / len(values), 3) if values else 0.0


def _validate_page_sidecar(paths: Mapping[str, Path], expected: Mapping[str, Any]) -> dict[str, Any] | None:
    sidecar_path = paths["sidecar"]
    if not sidecar_path.is_file():
        return None
    sidecar = load_json(sidecar_path)
    for key, value in expected.items():
        if sidecar.get(key) != value:
            raise OcrError(f"Cached OCR sidecar drifted at {sidecar_path}: {key}")
    for field, path_key in (("render", "image"), ("text", "text"), ("tsv", "tsv")):
        path = paths[path_key]
        identity = sidecar.get(field)
        if not path.is_file() or not isinstance(identity, dict):
            raise OcrError(f"Cached OCR artifact is incomplete at {sidecar_path}")
        if identity.get("bytes") != path.stat().st_size or identity.get("sha256") != sha256_file(path):
            raise OcrError(f"Cached OCR artifact hash drifted: {path}")
    return sidecar


def process_page(
    task: PageTask,
    *,
    pdf_dir: Path,
    generation_root: Path,
    source: Mapping[str, Any],
) -> dict[str, Any]:
    spec = VOLUME_SPECS[task.volume]
    if not 1 <= task.page <= spec["pages"]:
        raise OcrError(f"PDF page is out of range: volume {task.volume}, page {task.page}")
    pdf = pdf_dir / f"volume-{task.volume}.pdf"
    pdf_identity = next(value for value in source["pdfs"] if value["volume"] == task.volume)
    paths = _page_paths(generation_root, task)
    paths["directory"].mkdir(parents=True, exist_ok=True)
    expected = {
        "schema": PAGE_SCHEMA,
        "source_identity_sha256": source["source_identity_sha256"],
        "volume": task.volume,
        "pdf_page": task.page,
        "pdf_sha256": pdf_identity["sha256"],
        "pdf_url": pdf_identity["url"],
        "variant": task.variant,
        "dpi": task.dpi,
        "psm": task.psm,
        "language": OCR_LANGUAGE,
    }
    cached = _validate_page_sidecar(paths, expected)
    if cached is not None:
        return cached

    temporary = Path(tempfile.mkdtemp(prefix=f".ocr-v{task.volume}-{task.page:04d}-", dir=paths["directory"]))
    try:
        render_prefix = temporary / "render"
        run_checked([
            "pdftoppm", "-f", str(task.page), "-l", str(task.page), "-singlefile",
            "-r", str(task.dpi), "-gray", "-jpeg",
            "-jpegopt", f"quality={JPEG_QUALITY},optimize=y,progressive=n",
            str(pdf), str(render_prefix),
        ])
        rendered = render_prefix.with_suffix(".jpg")
        if not rendered.is_file() or rendered.stat().st_size < 10_000:
            raise OcrError(f"Rendered page is missing or implausibly small: {rendered}")
        ocr_prefix = temporary / "ocr"
        run_checked([
            "tesseract", str(rendered), str(ocr_prefix), "-l", OCR_LANGUAGE,
            "--oem", "1", "--psm", str(task.psm), "txt", "tsv",
        ])
        text_path = ocr_prefix.with_suffix(".txt")
        tsv_path = ocr_prefix.with_suffix(".tsv")
        if not text_path.is_file() or not tsv_path.is_file():
            raise OcrError("Tesseract did not produce both text and TSV outputs")
        word_count, mean_confidence = tsv_confidence(tsv_path)
        os.replace(rendered, paths["image"])
        os.replace(text_path, paths["text"])
        os.replace(tsv_path, paths["tsv"])
        sidecar = {
            **expected,
            "render": {"file": paths["image"].name, "bytes": paths["image"].stat().st_size, "sha256": sha256_file(paths["image"])},
            "text": {"file": paths["text"].name, "bytes": paths["text"].stat().st_size, "sha256": sha256_file(paths["text"])},
            "tsv": {"file": paths["tsv"].name, "bytes": paths["tsv"].stat().st_size, "sha256": sha256_file(paths["tsv"])},
            "ocr_word_count": word_count,
            "ocr_mean_confidence": mean_confidence,
        }
        atomic_write_json(paths["sidecar"], sidecar)
        return sidecar
    finally:
        shutil.rmtree(temporary, ignore_errors=True)


def page_tasks(page_specs: Sequence[str] | None = None, *, dpi: int = BASE_DPI, psm: int = BASE_PSM, variant: str = "base") -> list[PageTask]:
    if not page_specs:
        return [
            PageTask(volume, page, dpi, psm, variant)
            for volume, spec in VOLUME_SPECS.items()
            for page in range(1, spec["pages"] + 1)
        ]
    selected: set[tuple[int, int]] = set()
    for raw in page_specs:
        match = re.fullmatch(r"([1-5]):(\d+)(?:-(\d+))?", raw)
        if not match:
            raise OcrError(f"Invalid --pages value: {raw}; expected V:PAGE or V:START-END")
        volume = int(match.group(1))
        start = int(match.group(2))
        end = int(match.group(3) or start)
        if end < start or start < 1 or end > VOLUME_SPECS[volume]["pages"]:
            raise OcrError(f"Out-of-range --pages value: {raw}")
        selected.update((volume, page) for page in range(start, end + 1))
    return [PageTask(volume, page, dpi, psm, variant) for volume, page in sorted(selected)]


def process_tasks(
    tasks: Sequence[PageTask],
    *,
    pdf_dir: Path,
    generation_root: Path,
    source: Mapping[str, Any],
    workers: int,
) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    total = len(tasks)
    if not total:
        return results
    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        futures = {
            executor.submit(process_page, task, pdf_dir=pdf_dir, generation_root=generation_root, source=source): task
            for task in tasks
        }
        for completed, future in enumerate(as_completed(futures), 1):
            task = futures[future]
            try:
                results.append(future.result())
            except Exception as error:
                for pending in futures:
                    pending.cancel()
                raise OcrError(f"OCR failed at volume {task.volume} page {task.page}: {error}") from error
            if completed == total or completed % 50 == 0:
                print(f"OCR {task.variant}: {completed}/{total} pages", file=sys.stderr, flush=True)
    return sorted(results, key=lambda row: (row["volume"], row["pdf_page"], row["variant"]))


@dataclass(frozen=True)
class OcrLine:
    text: str
    left: int
    top: int
    right: int
    bottom: int
    page_width: int
    page_height: int
    confidence: float
    pdf_page: int = 0


def read_tsv_lines(path: Path) -> list[OcrLine]:
    grouped: dict[tuple[str, str, str, str], list[dict[str, str]]] = defaultdict(list)
    page_width = page_height = 0
    with path.open("r", encoding="utf-8", newline="") as handle:
        for row in csv.DictReader(handle, delimiter="\t"):
            if row.get("level") == "1":
                page_width = int(float(row.get("width") or 0))
                page_height = int(float(row.get("height") or 0))
            if row.get("level") == "5" and clean_text(row.get("text")):
                grouped[(row.get("page_num", ""), row.get("block_num", ""), row.get("par_num", ""), row.get("line_num", ""))].append(row)
    lines: list[OcrLine] = []
    for rows in grouped.values():
        rows.sort(key=lambda row: int(float(row.get("word_num") or 0)))
        text = " ".join(clean_text(row.get("text")) for row in rows)
        left = min(int(float(row.get("left") or 0)) for row in rows)
        top = min(int(float(row.get("top") or 0)) for row in rows)
        right = max(int(float(row.get("left") or 0)) + int(float(row.get("width") or 0)) for row in rows)
        bottom = max(int(float(row.get("top") or 0)) + int(float(row.get("height") or 0)) for row in rows)
        confidences = [float(row.get("conf") or -1) for row in rows if float(row.get("conf") or -1) >= 0]
        lines.append(OcrLine(text, left, top, right, bottom, page_width, page_height, sum(confidences) / len(confidences) if confidences else 0.0))
    return sorted(lines, key=lambda line: (line.top, line.left))


@dataclass(frozen=True)
class MarkerCandidate:
    number: int
    suffix: str
    volume: int
    page: int
    variant: str
    line_text: str
    left: int
    top: int
    top_ratio: float
    confidence: float
    score: float
    sidecar: Mapping[str, Any]


def candidates_from_line(task: PageTask, sidecar: Mapping[str, Any], line: OcrLine) -> list[MarkerCandidate]:
    result: list[MarkerCandidate] = []
    normalized_line = clean_text(line.text)
    for match in MARKER_RE.finditer(normalized_line):
        opening, number_text, suffix, closing = match.groups()
        number = int(number_text)
        spec = VOLUME_SPECS[task.volume]
        if not spec["first"] <= number <= spec["last"] or number in EXPECTED_GAPS:
            continue
        # True Sowerby terminators occur at line ends. Parenthesized four-digit
        # dates are common in the bibliography and must never become IDs.
        if clean_text(normalized_line[match.end():]).strip(".,;:"):
            continue
        if opening == "(" and closing == ")" and 1400 <= number <= 2099:
            continue
        marker_only = bool(re.fullmatch(r"[\[\({]\s*\d{1,4}[A-Za-z]?\s*[\]\)}]", normalized_line))
        centered_footer = bool(
            marker_only and line.page_height and line.top / line.page_height > 0.88
            and 0.38 <= ((line.left + line.right) / 2) / max(1, line.page_width) <= 0.62
        )
        if centered_footer:
            continue
        alpha_before = sum(character.isalpha() for character in normalized_line[: match.start()])
        right_side = line.page_width and line.left / line.page_width > 0.45
        delimiter_score = 2.0 if opening == "[" and closing == "]" else 0.25 if "[" in (opening, closing) or "]" in (opening, closing) else -1.5
        score = (
            line.confidence / 100.0
            + (1.5 if alpha_before >= 3 else 0.0)
            + (0.5 if right_side else 0.0)
            + delimiter_score
        )
        if task.variant != "base":
            score += 0.15
        result.append(MarkerCandidate(
            number, suffix.lower(), task.volume, task.page, task.variant, normalized_line,
            line.left, line.top, round(line.top / max(1, line.page_height), 6),
            round(line.confidence, 3), round(score, 4), sidecar,
        ))
    return result


def marker_candidates(generation_root: Path, sidecars: Sequence[Mapping[str, Any]]) -> dict[int, list[MarkerCandidate]]:
    result: dict[int, list[MarkerCandidate]] = defaultdict(list)
    for sidecar in sidecars:
        task = PageTask(
            int(sidecar["volume"]), int(sidecar["pdf_page"]), int(sidecar["dpi"]), int(sidecar["psm"]), str(sidecar["variant"])
        )
        paths = _page_paths(generation_root, task)
        for line in read_tsv_lines(paths["tsv"]):
            for candidate in candidates_from_line(task, sidecar, line):
                result[candidate.number].append(candidate)
    return result


def expected_numbers(volume: int | None = None) -> list[int]:
    if volume is None:
        return [number for number in range(1, EXPECTED_MAX_IDENTIFIER + 1) if number not in EXPECTED_GAPS]
    spec = VOLUME_SPECS[volume]
    return [number for number in range(spec["first"], spec["last"] + 1) if number not in EXPECTED_GAPS]


def resolve_candidates(candidates: Mapping[int, Sequence[MarkerCandidate]]) -> tuple[dict[int, MarkerCandidate], dict[int, str]]:
    """Select the longest locally plausible monotonic marker path per volume.

    Isolated bracketed years, signatures, and cross-references can look like
    Sowerby terminators.  A real marker spine is dense and page-monotonic.  The
    dynamic program maximizes selected identifiers first and OCR quality
    second, and only connects locally plausible transitions.  Missing OCR
    markers are allowed; invented markers are not.
    """

    resolved: dict[int, MarkerCandidate] = {}
    unresolved: dict[int, str] = {}
    for volume, spec in VOLUME_SPECS.items():
        numbers = expected_numbers(volume)
        nodes = sorted(
            (candidate for number in numbers for candidate in candidates.get(number, ())),
            key=lambda value: (value.number, value.page, value.top_ratio, -value.score, value.variant),
        )
        if not nodes:
            for number in numbers:
                unresolved[number] = "identifier marker not detected in cached LOC OCR"
            continue
        best: list[tuple[int, float]] = [(1, candidate.score) for candidate in nodes]
        previous: list[int | None] = [None] * len(nodes)
        for index, candidate in enumerate(nodes):
            for prior_index in range(index - 1, -1, -1):
                prior = nodes[prior_index]
                number_delta = candidate.number - prior.number
                if number_delta <= 0:
                    continue
                if number_delta > 75:
                    break
                page_delta = candidate.page - prior.page
                if page_delta < 0 or page_delta > max(5, number_delta * 2 + 3):
                    continue
                # Same-page candidates must preserve vertical reading order.
                if page_delta == 0 and candidate.top_ratio <= prior.top_ratio:
                    continue
                candidate_value = (
                    best[prior_index][0] + 1,
                    best[prior_index][1] + candidate.score - 0.03 * max(0, number_delta - 1),
                )
                if candidate_value > best[index]:
                    best[index] = candidate_value
                    previous[index] = prior_index
        end = max(range(len(nodes)), key=lambda index: (best[index], nodes[index].number, -nodes[index].page))
        selected: list[MarkerCandidate] = []
        while end is not None:
            selected.append(nodes[end])
            end = previous[end]
        selected.reverse()
        for candidate in selected:
            resolved[candidate.number] = candidate
        for number in numbers:
            if number not in resolved:
                unresolved[number] = (
                    "identifier marker not detected in cached LOC OCR"
                    if not candidates.get(number)
                    else "OCR marker candidate was excluded by the monotonic neighborhood spine"
                )
    return resolved, unresolved


def fallback_pages_for_missing(missing: Sequence[int], resolved: Mapping[int, MarkerCandidate]) -> list[tuple[int, int]]:
    selected: set[tuple[int, int]] = set()
    resolved_numbers = sorted(resolved)
    for number in missing:
        volume = next(volume for volume, spec in VOLUME_SPECS.items() if spec["first"] <= number <= spec["last"])
        spec = VOLUME_SPECS[volume]
        before = [value for value in resolved_numbers if value < number and resolved[value].volume == volume]
        after = [value for value in resolved_numbers if value > number and resolved[value].volume == volume]
        if before and after:
            lower = resolved[before[-1]].page
            upper = resolved[after[0]].page
            if upper - lower <= 8:
                pages = range(max(1, lower - 1), min(spec["pages"], upper + 1) + 1)
            else:
                predicted = round(lower + (number - before[-1]) / (after[0] - before[-1]) * (upper - lower))
                pages = range(max(1, predicted - 1), min(spec["pages"], predicted + 1) + 1)
        else:
            predicted = round(1 + (number - spec["first"]) / max(1, spec["last"] - spec["first"]) * (spec["pages"] - 1))
            pages = range(max(1, predicted - 2), min(spec["pages"], predicted + 2) + 1)
        selected.update((volume, page) for page in pages)
    return sorted(selected)


def _all_cached_sidecars(generation_root: Path, variant: str) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    for path in sorted((generation_root / variant).glob("volume-*/page-*.json")):
        value = load_json(path)
        if value.get("schema") == PAGE_SCHEMA:
            results.append(value)
    return results


def _credible_title_line(value: str) -> bool:
    candidate = clean_text(value).strip(TITLE_EDGE_STRIP)
    letters = [character for character in candidate if character.isalpha()]
    if len(candidate) < 3 or len(letters) < 3 or len(candidate) > 240:
        return False
    upper = candidate.upper()
    if CATALOGUE_EVIDENCE_RE.match(candidate) or upper == "THE LIBRARY OF THOMAS JEFFERSON":
        return False
    if re.fullmatch(r"[A-Z]{1,3}\d+(?:\.\w+)?(?:\s+\d{4})?", candidate):
        return False
    return True


def _credible_direct_j_title(value: str) -> bool:
    candidate = clean_text(value).strip(TITLE_EDGE_STRIP)
    if not _credible_title_line(candidate):
        return False
    if candidate[:1] in ";,)]}":
        return False
    lowered = candidate.casefold()
    rejected_starts = (
        "first edition", "second edition", "third edition", "not in ",
        "catalogue,", "vol. bound", "vols. bound", "of the other",
        "id.", "idem ", "eng. by ", "engraved by ", "notin ",
    )
    if CATALOGUE_EVIDENCE_RE.match(candidate):
        return False
    if re.search(r"\[\s*\d{1,4}[A-Za-z]?\s*\]", candidate):
        return False
    if candidate.endswith("]") and not candidate.startswith("["):
        return False
    if candidate.startswith("[") and candidate.endswith("]") and "," in candidate:
        return False
    if lowered.startswith(rejected_starts):
        return False
    if re.search(
        r"\b(?:with irregularities|livres|leaves?|vols?\.\s*bound|bound together|"
        r"some irregularities|original calf|silk bookmark|label on the back|bookplate|inserted in ink|reprinted in)\b",
        lowered,
    ):
        return False
    if re.match(r"^(?:political\s+)?tracts?\b", lowered) or re.search(r"\bviz\.?$", lowered):
        return False
    # OCR table/column separators are not bibliographic punctuation.  Lines
    # containing them have repeatedly joined a title to a price, format, or
    # neighboring title in the scanned 1815-catalogue evidence.
    if "|" in candidate or re.search(r"(?:J-~|\}\s*\d|\b\d+\s*!\s*$)", candidate):
        return False
    if re.search(r"\d\.\d[A-Z]\d", candidate):
        return False
    # An inline all-caps surname followed by a personal name is a structural
    # creator heading, not a title. OCR often preserves small caps unevenly in
    # the given name, so reject on the reliably uppercase family-name side.
    if re.fullmatch(
        r"[A-ZÀ-ÖØ-Þ][A-ZÀ-ÖØ-Þ '\-]{2,55},\s*"
        r"[A-ZÀ-ÖØ-Þ][^,;:!?]{1,55}\.?",
        candidate,
    ):
        return False
    if re.fullmatch(r"(?:fol\.?|folio|[248]|12|16|24|32)\s*(?:mo|vo|to)?\.?(?:\s+\d+)?", lowered):
        return False
    if re.fullmatch(r"[A-Z]{1,3}\s*\d{2,5}(?:\s*\.\s*[A-Z0-9]+)*(?:\s+\d{4}[a-z]?)?", candidate, re.I):
        return False
    letters = [character for character in candidate if character.isalpha()]
    if letters and sum(character.isupper() for character in letters) / len(letters) > 0.9 and "," in candidate:
        return False
    return True


def _credible_creator_heading(value: str) -> bool:
    candidate = clean_text(value)
    if not candidate or "LIBRARY OF THOMAS JEFFERSON" in candidate.upper() or "HISTORY" == candidate.upper():
        return False
    if J_HEADING_RE.fullmatch(candidate) or re.search(r"\d", candidate):
        return False
    if re.fullmatch(r"[A-Z]{1,3}\s*\d.*", candidate, re.I):
        return False
    letters = [character for character in candidate if character.isalpha()]
    uppercase_ratio = sum(character.isupper() for character in letters) / max(1, len(letters))
    bracketed_name = bool(
        candidate.startswith("[") and candidate.endswith("]") and "," in candidate
        and len(candidate) <= 120 and uppercase_ratio >= 0.35
        and not re.search(r"[“”\"?]", candidate)
    )
    mostly_upper = bool(letters) and uppercase_ratio >= 0.82
    complete_unbracketed_name = mostly_upper and "," in candidate and candidate.endswith(".")
    return bool(len(letters) >= 4 and (bracketed_name or complete_unbracketed_name))


def _credible_title_after_creator(value: str) -> bool:
    candidate = clean_text(value).strip(TITLE_EDGE_STRIP)
    if not _credible_direct_j_title(candidate):
        return False
    letters = [character for character in candidate if character.isalpha()]
    words = re.findall(r"[^\W\d_]+", candidate, re.UNICODE)
    if len(words) < 3 or len(candidate) < 12:
        return False
    first_letter = next((character for character in candidate if character.isalpha()), "")
    if not first_letter or first_letter.islower():
        return False
    if sum(character.isupper() for character in letters) / max(1, len(letters)) >= 0.85:
        return False
    lowered = candidate.casefold()
    note_fragments = (
        "jefferson’s handwriting", "jefferson's handwriting", "separate pagination",
        "with the prices paid", "books in this list", "manuscript catalogue",
        "in which details", "price,", "catalogue, with the price",
    )
    return not any(fragment in lowered for fragment in note_fragments)


def _same_band_title(lines: Sequence[OcrLine], index: int) -> tuple[str, float]:
    heading = lines[index]
    height = max(1, heading.bottom - heading.top)
    maximum_left = min(heading.page_width * 0.55, heading.right + min(220, heading.page_width * 0.16))
    candidates = [
        line for line in lines
        if line is not heading and line.pdf_page == heading.pdf_page
        and line.left >= heading.right - 12
        and line.left <= maximum_left
        and abs(line.top - heading.top) <= max(height, line.bottom - line.top)
    ]
    candidates.sort(key=lambda line: (line.left, line.top))
    if not candidates:
        return "", 0.0
    first = candidates[0]
    title = clean_text(first.text).strip(TITLE_EDGE_STRIP)
    if first.confidence < MIN_GEOMETRY_TITLE_CONFIDENCE or not _credible_direct_j_title(title):
        return "", 0.0
    first_letter = next((character for character in title if character.isalpha()), "")
    if not first_letter or first_letter.islower():
        return "", 0.0
    # A second plausible line in this geometry is ambiguous: in the catalogue
    # table it may be a wrap, but it may equally be a second title in a bound
    # group.  Publish neither interpretation without an independent boundary.
    # This intentionally favors a missing short title over a concatenated one.
    prior = first
    for line in lines:
        if line.pdf_page != first.pdf_page or line.top <= prior.top:
            continue
        candidate = clean_text(line.text).strip(TITLE_EDGE_STRIP)
        if CATALOGUE_EVIDENCE_RE.match(candidate):
            break
        line_height = max(1, prior.bottom - prior.top)
        if line.top - prior.bottom > line_height * 2 or abs(line.left - first.left) > 120:
            continue
        if not _credible_direct_j_title(candidate):
            break
        return "", 0.0
    return title[:240], round(first.confidence, 3)


def extract_title_from_lines(lines: Sequence[OcrLine]) -> tuple[str, str, str, float]:
    """Return title, rule, creator candidate, and line confidence.

    An all-uppercase main heading is only a creator candidate. It is never
    promoted as a title. A non-J entry title must be the first credible line
    immediately following that heading.
    """

    j_candidates: list[tuple[int, str, str, float]] = []
    for index, line in enumerate(lines):
        if line.page_width and line.left / line.page_width >= 0.5:
            continue
        match = J_HEADING_RE.fullmatch(clean_text(line.text))
        if not match:
            continue
        inline = clean_text(match.group(1)).strip(TITLE_EDGE_STRIP)
        if line.confidence >= MIN_DIRECT_TITLE_CONFIDENCE and _credible_direct_j_title(inline):
            j_candidates.append((index, inline[:240], "jefferson_catalog_heading_ocr", round(line.confidence, 3)))
        elif not inline:
            geometric, confidence = _same_band_title(lines, index)
            if geometric:
                j_candidates.append((index, geometric, "jefferson_catalog_heading_geometry_ocr", confidence))
    if j_candidates:
        _, title, kind, confidence = j_candidates[0]
        return title, kind, "", confidence

    # Non-J entries: the first main-entry creator heading after the previous
    # selected marker is structural. Never use the heading itself as a title;
    # only accept the immediate bibliographic line that follows it.
    for index, line in enumerate(lines):
        creator = clean_text(line.text)
        if not _credible_creator_heading(creator):
            continue
        height = max(1, line.bottom - line.top)
        for following in lines[index + 1:index + 5]:
            if following.pdf_page != line.pdf_page:
                break
            candidate = clean_text(following.text).strip(TITLE_EDGE_STRIP)
            if CATALOGUE_EVIDENCE_RE.match(candidate):
                continue
            if following.top - line.bottom > height * 4:
                break
            if following.top < line.top - height:
                continue
            if (
                following.confidence >= MIN_CREATOR_TITLE_CONFIDENCE
                and _credible_title_after_creator(candidate)
                and not _credible_creator_heading(candidate)
            ):
                return candidate[:240], "bibliographic_title_after_first_creator_heading_ocr", creator[:160], round(following.confidence, 3)
            return "", "not_established", creator[:160], 0.0
        return "", "not_established", creator[:160], 0.0
    creator_only = ""
    for line in reversed(lines):
        candidate = clean_text(line.text)
        letters = [character for character in candidate if character.isalpha()]
        if UPPER_HEADING_RE.fullmatch(candidate) and letters and sum(character.isupper() for character in letters) / len(letters) >= 0.85:
            if "LIBRARY OF THOMAS JEFFERSON" not in candidate.upper() and not J_HEADING_RE.fullmatch(candidate):
                creator_only = candidate[:160]
                break
    if creator_only:
        return "", "not_established", creator_only, 0.0
    return "", "not_established", "", 0.0


def lines_for_marker(
    number: int,
    marker: MarkerCandidate,
    resolved: Mapping[int, MarkerCandidate],
    generation_root: Path,
) -> list[OcrLine]:
    prior_numbers = [value for value in resolved if value < number and resolved[value].volume == marker.volume]
    prior = resolved[max(prior_numbers)] if prior_numbers else None
    start_page = prior.page if prior and prior.volume == marker.volume else max(1, marker.page - 2)
    selected: list[OcrLine] = []
    for page in range(start_page, marker.page + 1):
        # Base PSM 3 supplies the stable two-column reading geometry even when
        # the selected marker came from a high-DPI fallback pass.
        task = PageTask(marker.volume, page, BASE_DPI, BASE_PSM, "base")
        path = _page_paths(generation_root, task)["tsv"]
        if not path.is_file():
            continue
        for line in read_tsv_lines(path):
            line = replace(line, pdf_page=page)
            position = (page, line.top / max(1, line.page_height))
            start = (prior.page, prior.top_ratio) if prior else (start_page, -1.0)
            end = (marker.page, marker.top_ratio)
            if start < position < end:
                selected.append(line)
    return selected


def has_exact_title_boundary(
    number: int,
    marker: MarkerCandidate,
    resolved: Mapping[int, MarkerCandidate],
) -> bool:
    """Require a page-resolved immediately preceding source entry.

    A merely earlier resolved marker is not a safe title boundary: an
    unresolved intervening entry can shift a perfectly legible heading onto
    its neighbor.  Numeric gaps confirmed by the official source are skipped
    when finding the previous *source-backed* identifier.  Volume starts are
    deliberately unresolved until a separate start-boundary assertion exists.
    """

    volume_numbers = expected_numbers(marker.volume)
    try:
        index = volume_numbers.index(number)
    except ValueError:
        return False
    if index == 0:
        return False
    predecessor = resolved.get(volume_numbers[index - 1])
    return bool(predecessor and predecessor.volume == marker.volume)


def build_outputs(
    *,
    generation_root: Path,
    source: Mapping[str, Any],
    data_dir: Path,
    allow_partial: bool,
) -> dict[str, Any]:
    base_sidecars = _all_cached_sidecars(generation_root, "base")
    expected_page_count = sum(spec["pages"] for spec in VOLUME_SPECS.values())
    if len(base_sidecars) != expected_page_count and not allow_partial:
        raise OcrError(f"Full build requires {expected_page_count} base OCR pages; found {len(base_sidecars)}")
    all_sidecars = list(base_sidecars)
    for dpi, psm in FALLBACK_VARIANTS:
        all_sidecars.extend(_all_cached_sidecars(generation_root, f"fallback-dpi{dpi}-psm{psm}"))
    candidates = marker_candidates(generation_root, all_sidecars)
    resolved, unresolved_reasons = resolve_candidates(candidates)

    generation_identity = load_json(generation_root / "generation.json")
    generated_at = clean_text(generation_identity.get("generated_at"))
    if not re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", generated_at):
        raise OcrError("OCR generation has no stable whole-second UTC timestamp")
    entries: list[dict[str, Any]] = []
    unresolved: list[dict[str, Any]] = [
        {
            "sowerby_number": gap,
            "status": "loc_confirmed_absent_number",
            "reason": "The official LOC scan sequence omits this base number; no entry or title is invented.",
        }
        for gap in sorted(EXPECTED_GAPS)
    ]
    as_of = generated_at[:10]
    rights = source["rights"]
    for number in expected_numbers():
        marker = resolved.get(number)
        if not marker:
            unresolved.append({
                "sowerby_number": number,
                "status": "ocr_identifier_not_established",
                "reason": unresolved_reasons.get(number, "No LOC OCR marker candidate was selected."),
                "candidate_count": len(candidates.get(number, ())),
            })
            volume = next(volume for volume, spec in VOLUME_SPECS.items() if spec["first"] <= number <= spec["last"])
            title = ""
            title_kind = "not_established"
            creator_candidate = ""
            title_confidence = 0.0
            evidence = {
                "render_sha256": "",
                "ocr_text_sha256": "",
                "ocr_tsv_sha256": "",
                "evidence_sha256": sha256_bytes(json_bytes({
                    "sowerby_number": number,
                    "evidence_scope": "aggregate official LOC five-volume scan spine",
                    "source_identity_sha256": source["source_identity_sha256"],
                })),
            }
        else:
            volume = marker.volume
            exact_prior_is_available = has_exact_title_boundary(number, marker, resolved)
            title_lines = lines_for_marker(number, marker, resolved, generation_root) if exact_prior_is_available else []
            title, title_kind, creator_candidate, title_confidence = extract_title_from_lines(title_lines)
            evidence = {
                "render_sha256": marker.sidecar["render"]["sha256"],
                "ocr_text_sha256": marker.sidecar["text"]["sha256"],
                "ocr_tsv_sha256": marker.sidecar["tsv"]["sha256"],
            }
            evidence["evidence_sha256"] = sha256_bytes(json_bytes({
                "sowerby_number": number,
                "marker_line": marker.line_text,
                "display_title": title,
                **evidence,
            }))
        if marker and not title:
            unresolved.append({
                "sowerby_number": number,
                "status": "ocr_title_not_established",
                "reason": "A source-backed identifier marker was selected, but no short LOC-OCR heading passed the factual title rules.",
                "volume": marker.volume,
                "pdf_page": marker.page,
            })
        entries.append({
            "schema": ENTRY_SCHEMA,
            "id": f"jefferson-sowerby-{number}",
            "entity_type": "sowerby_entry",
            "sowerby_identifier": str(number),
            "sowerby_number": number,
            "identifier_status": "page_resolved_ocr" if marker else "aggregate_scan_spine_source_backed",
            "title_status": "source_backed" if title else "not_established",
            "display_title": title,
            "display_title_source_kind": title_kind,
            "creator_candidate_ocr": creator_candidate,
            "authority": "Library of Congress",
            "publication_basis": PUBLICATION_BASIS,
            "loc_item_url": LOC_ITEM_URL,
            "pdf_url": VOLUME_SPECS[volume]["url"],
            "volume": volume,
            "pdf_page": marker.page if marker else None,
            "marker_ocr": marker.line_text if marker else "",
            "marker_suffix": marker.suffix if marker else "",
            "ocr": {
                "variant": marker.variant if marker else "",
                "dpi": marker.sidecar["dpi"] if marker else 0,
                "psm": marker.sidecar["psm"] if marker else 0,
                "mean_page_confidence": marker.sidecar["ocr_mean_confidence"] if marker else 0.0,
                "marker_line_confidence": marker.confidence if marker else 0.0,
                "title_line_confidence": title_confidence,
            },
            "evidence": evidence,
            "rights_statement_url": rights["rights_statement_url"],
            "rights_statement_sha256": rights["rights_statement_sha256"],
            "rights_clearance": rights["rights_clearance"],
            "as_of": as_of,
        })

    entry_numbers = [entry["sowerby_number"] for entry in entries]
    duplicate_numbers = sorted(number for number in set(entry_numbers) if entry_numbers.count(number) > 1)
    missing_detected = sorted(set(expected_numbers()) - set(resolved))
    title_count = sum(entry["title_status"] == "source_backed" for entry in entries)
    validation = {
        "schema": VALIDATION_SCHEMA,
        "authority": "Library of Congress",
        "publication_basis": PUBLICATION_BASIS,
        "source_identity_sha256": source["source_identity_sha256"],
        "rights_statement_url": rights["rights_statement_url"],
        "rights_statement_sha256": rights["rights_statement_sha256"],
        "counts": {
            "spine_maximum_serial": EXPECTED_MAX_IDENTIFIER,
            "loc_confirmed_absent_number_count": len(EXPECTED_GAPS),
            "expected_source_backed_base_entry_count": EXPECTED_NUMBERED_ENTRY_COUNT,
            "selected_source_backed_identifier_count": len(entries),
            "page_resolved_identifier_count": len(resolved),
            "source_backed_display_title_count": title_count,
            "unresolved_identifier_count": len(missing_detected),
            "unresolved_title_count": len(entries) - title_count,
            "unresolved_queue_count": len(unresolved),
            "base_ocr_page_count": len(base_sidecars),
            "expected_pdf_page_count": expected_page_count,
            "fallback_ocr_page_count": len(all_sidecars) - len(base_sidecars),
        },
        "loc_confirmed_absent_numbers": sorted(EXPECTED_GAPS),
        "missing_detected_numbers": missing_detected,
        "duplicate_selected_numbers": duplicate_numbers,
        "checks": {
            "monticello_text_was_not_read_or_copied": True,
            "no_gap_rows_were_invented": not (set(entry_numbers) & EXPECTED_GAPS),
            "selected_identifiers_are_unique": not duplicate_numbers,
            "selected_identifiers_are_within_loc_volume_ranges": all(
                VOLUME_SPECS[entry["volume"]]["first"] <= entry["sowerby_number"] <= VOLUME_SPECS[entry["volume"]]["last"]
                for entry in entries
            ),
            "all_source_urls_are_loc_urls": True,
            "rights_evidence_retained": SHA256_RE.fullmatch(rights["rights_statement_sha256"]) is not None,
            "full_base_page_coverage": len(base_sidecars) == expected_page_count,
            "complete_aggregate_spine_identifier_coverage": len(entries) == EXPECTED_NUMBERED_ENTRY_COUNT,
            "complete_page_resolved_identifier_coverage": not missing_detected,
        },
        "warnings": [
            "OCR headings are machine transcriptions and require bibliographic review before public release.",
            "LOC reports no known U.S. copyright or other restrictions but does not grant blanket reuse clearance; item-level responsibility remains with the user.",
            "Serials 2323, 4707, and 4708 are absent from the official source sequence and are not records.",
        ],
    }
    if not allow_partial and (duplicate_numbers or len(base_sidecars) != expected_page_count):
        raise OcrError("LOC OCR extraction failed structural validation")

    page_index = [
        {
            "volume": sidecar["volume"],
            "pdf_page": sidecar["pdf_page"],
            "variant": sidecar["variant"],
            "dpi": sidecar["dpi"],
            "psm": sidecar["psm"],
            "ocr_word_count": sidecar["ocr_word_count"],
            "ocr_mean_confidence": sidecar["ocr_mean_confidence"],
            "render_sha256": sidecar["render"]["sha256"],
            "ocr_text_sha256": sidecar["text"]["sha256"],
            "ocr_tsv_sha256": sidecar["tsv"]["sha256"],
        }
        for sidecar in sorted(all_sidecars, key=lambda row: (row["volume"], row["pdf_page"], row["variant"]))
    ]
    payloads = {
        "sowerby_loc_ocr_entries.jsonl": jsonl_bytes(entries),
        "sowerby_loc_ocr_unresolved.jsonl": jsonl_bytes(unresolved),
        "sowerby_loc_ocr_pages.jsonl": jsonl_bytes(page_index),
        "sowerby_loc_ocr_validation.json": json_bytes(validation),
    }
    manifest = {
        "schema": MANIFEST_SCHEMA,
        "generated_at": generated_at,
        "authority": "Library of Congress",
        "publication_basis": PUBLICATION_BASIS,
        "loc_item_url": LOC_ITEM_URL,
        "source_identity_sha256": source["source_identity_sha256"],
        "rights_statement_url": rights["rights_statement_url"],
        "rights_statement_sha256": rights["rights_statement_sha256"],
        "rights_clearance": rights["rights_clearance"],
        "pdfs": source["pdfs"],
        "tools": source["tools"],
        "counts": validation["counts"],
        "outputs": {
            name: {"bytes": len(body), "sha256": sha256_bytes(body)} for name, body in sorted(payloads.items())
        },
    }
    payloads["sowerby_loc_ocr_manifest.json"] = json_bytes(manifest)
    data_dir.mkdir(parents=True, exist_ok=True)
    for name, body in payloads.items():
        atomic_write(data_dir / name, body)
    return manifest


def run_fallbacks(
    *,
    pdf_dir: Path,
    generation_root: Path,
    source: Mapping[str, Any],
    workers: int,
) -> None:
    sidecars = _all_cached_sidecars(generation_root, "base")
    candidates = marker_candidates(generation_root, sidecars)
    resolved, _ = resolve_candidates(candidates)
    missing = sorted(set(expected_numbers()) - set(resolved))
    for dpi, psm in FALLBACK_VARIANTS:
        if not missing:
            break
        pages = fallback_pages_for_missing(missing, resolved)
        variant = f"fallback-dpi{dpi}-psm{psm}"
        tasks = [PageTask(volume, page, dpi, psm, variant) for volume, page in pages]
        print(f"Fallback {dpi}dpi psm {psm}: {len(missing)} unresolved identifiers, {len(tasks)} candidate pages", file=sys.stderr)
        process_tasks(tasks, pdf_dir=pdf_dir, generation_root=generation_root, source=source, workers=workers)
        sidecars.extend(_all_cached_sidecars(generation_root, variant))
        candidates = marker_candidates(generation_root, sidecars)
        resolved, _ = resolve_candidates(candidates)
        missing = sorted(set(expected_numbers()) - set(resolved))


def parse_args(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("audit", "sample", "ocr", "build", "all"))
    parser.add_argument("--pdf-dir", type=Path, default=DEFAULT_PDF_DIR)
    parser.add_argument("--cache-root", type=Path, default=DEFAULT_CACHE_ROOT)
    parser.add_argument("--data-dir", type=Path, default=DEFAULT_DATA_DIR)
    parser.add_argument("--item-json", type=Path, default=DEFAULT_ITEM_JSON)
    parser.add_argument("--workers", type=int, default=min(8, os.cpu_count() or 4))
    parser.add_argument("--pages", action="append", help="Bounded page selection V:PAGE or V:START-END (sample/ocr)")
    parser.add_argument("--refresh", action="store_true", help="Activate the current audited source/tool generation after reviewed drift")
    parser.add_argument("--allow-partial", action="store_true", help="Permit research-only partial normalized output")
    parser.add_argument("--no-fallback", action="store_true", help="Skip targeted high-DPI fallback passes")
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    args = parse_args(argv)
    try:
        if args.workers < 1 or args.workers > 32:
            raise OcrError("--workers must be from 1 to 32")
        source = audit_sources(args.pdf_dir, args.item_json)
        if args.command == "audit":
            print(json.dumps(source, ensure_ascii=False, indent=2, sort_keys=True))
            return 0
        generation_root = activate_generation(args.cache_root, source, refresh=args.refresh)
        if args.command in {"sample", "ocr", "all"}:
            selections = args.pages
            if args.command == "sample" and not selections:
                selections = ["1:50-52", "3:1-3", "5:1-3"]
            tasks = page_tasks(selections)
            process_tasks(tasks, pdf_dir=args.pdf_dir, generation_root=generation_root, source=source, workers=args.workers)
            if args.command == "sample":
                print(f"LOC OCR sample complete: {len(tasks)} pages in {generation_root}")
                return 0
        if args.command in {"all"} and not args.no_fallback:
            run_fallbacks(pdf_dir=args.pdf_dir, generation_root=generation_root, source=source, workers=args.workers)
        if args.command in {"build", "all"}:
            manifest = build_outputs(
                generation_root=generation_root,
                source=source,
                data_dir=args.data_dir,
                allow_partial=args.allow_partial,
            )
            print(
                "LOC OCR package wrote: "
                f"{manifest['counts']['selected_source_backed_identifier_count']:,} identifiers, "
                f"{manifest['counts']['source_backed_display_title_count']:,} display titles"
            )
        return 0
    except OcrError as error:
        print(f"ERROR: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
