#!/usr/bin/env python3
"""Analyze the optical character of exact-match cover images.

This is deliberately an *image* analyzer, not a physical-book estimator.  Its
measurements describe pixels in the Open Library cover raster.  They do not
claim to measure paper texture, binding, thickness, spine geometry, scale, or
condition.

The input manifest is produced by ``enrich_book_visuals.py``.  Only its already
resolved, ISBN-exact, allowlisted Open Library URLs are downloaded.  Binaries
are held in an ignored local cache and are never copied into ``docs``.

Examples::

    python scripts/analyze_cover_visuals.py --self-test
    python scripts/analyze_cover_visuals.py --dry-run
    python scripts/analyze_cover_visuals.py
    python scripts/analyze_cover_visuals.py --offline --dry-run

Pillow is the sole runtime dependency.  The implementation avoids NumPy so it
is quick to install and runs efficiently on Apple Silicon and CI alike.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import sys
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, MutableMapping, Optional, Sequence, Tuple
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qs, urlparse
from urllib.request import Request, urlopen

try:
    from PIL import Image, ImageChops, ImageFilter, ImageOps, ImageStat, UnidentifiedImageError
    from PIL import __version__ as PILLOW_VERSION
except ImportError as exc:  # pragma: no cover - exercised before the CLI can run
    raise SystemExit(
        "Pillow is required. Install it into a virtual environment with "
        "`python -m pip install Pillow`."
    ) from exc


ANALYSIS_SCHEMA = "shelfsignals-cover-optical-analysis@1"
ANALYZER_VERSION = "1.0.0"
EXPECTED_MANIFEST_SCHEMA = "shelfsignals-book-visuals@1"
DEFAULT_MANIFEST = Path("docs/data/book_visuals.json")
DEFAULT_OUTPUT = Path("docs/data/book_visuals.json")
DEFAULT_CACHE = Path(".cache/book-cover-analysis")
USER_AGENT = "ShelfSignals-cover-optical-analyzer/1.0 (+https://github.com/gitbrainlab/ShelfSignals)"
APPROVED_HOST = "covers.openlibrary.org"
MAX_DOWNLOAD_BYTES = 25 * 1024 * 1024
MIN_IMAGE_EDGE = 40
WORKING_LONG_EDGE = 384
PALETTE_COLORS = 6
URL_PATH = re.compile(r"^/b/isbn/([0-9Xx]{10,13})-L\.jpg$")
ARCHIVE_DELIVERY_HOST = re.compile(r"^ia\d+\.us\.archive\.org$")
ARCHIVE_DELIVERY_FILE = re.compile(r"^\d+-L\.jpg$")
NON_PHYSICAL_NOTE = (
    "Image-derived optical measurements only; they do not measure or infer physical book "
    "dimensions, thickness, spine geometry, binding, material texture, or condition."
)


class AnalysisError(RuntimeError):
    """A safe, user-facing analysis failure."""


def _round(value: float, digits: int = 6) -> float:
    """Round metrics consistently while avoiding negative zero in JSON."""

    result = round(float(value), digits)
    return 0.0 if result == 0 else result


def _canonical_sha256(value: Any) -> str:
    payload = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _validate_approved_item(record_id: str, item: Mapping[str, Any]) -> str:
    """Return the URL only for an existing ISBN-exact Open Library resolution."""

    if item.get("status") != "resolved":
        raise AnalysisError(f"{record_id}: item is not resolved")
    if item.get("source") != "openlibrary" or item.get("match_method") != "isbn":
        raise AnalysisError(f"{record_id}: analysis requires an exact Open Library ISBN match")
    if float(item.get("match_confidence", 0)) != 1.0:
        raise AnalysisError(f"{record_id}: analysis requires match_confidence 1.0")

    source_id = str(item.get("source_id", "")).upper()
    url = str(item.get("image_url", ""))
    parsed = urlparse(url)
    path_match = URL_PATH.fullmatch(parsed.path)
    query = parse_qs(parsed.query, keep_blank_values=True)
    if (
        parsed.scheme != "https"
        or parsed.hostname != APPROVED_HOST
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 443)
        or path_match is None
        or path_match.group(1).upper() != source_id
        or query != {"default": ["false"]}
        or parsed.fragment
    ):
        raise AnalysisError(f"{record_id}: image_url is outside the exact Open Library allowlist")
    return url


def _cache_path(cache_dir: Path, record_id: str, url: str) -> Path:
    safe_id = re.sub(r"[^A-Za-z0-9_.-]", "_", record_id)
    url_digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:16]
    return cache_dir / f"{safe_id}-{url_digest}.jpg"


def _approved_delivery_url(url: str) -> bool:
    """Accept Open Library itself or its narrowly scoped Internet Archive backend."""

    parsed = urlparse(url)
    if (
        parsed.scheme != "https"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.port not in (None, 443)
        or parsed.fragment
    ):
        return False
    if parsed.hostname == APPROVED_HOST:
        return True
    if not parsed.hostname or not ARCHIVE_DELIVERY_HOST.fullmatch(parsed.hostname):
        return False
    if parsed.path != "/view_archive.php":
        return False
    query = parse_qs(parsed.query, keep_blank_values=True)
    archives = query.get("archive", [])
    files = query.get("file", [])
    return (
        set(query) == {"archive", "file"}
        and len(archives) == 1
        and archives[0].startswith("/")
        and "/items/" in archives[0]
        and archives[0].endswith(".zip")
        and len(files) == 1
        and ARCHIVE_DELIVERY_FILE.fullmatch(files[0]) is not None
    )


@dataclass
class CoverFetcher:
    """Bounded downloader with deterministic cache names and polite retries."""

    cache_dir: Path
    timeout: float = 30.0
    retries: int = 3
    min_interval: float = 0.2
    offline: bool = False
    refresh: bool = False
    _last_request: float = 0.0

    def _pace(self) -> None:
        remaining = self.min_interval - (time.monotonic() - self._last_request)
        if remaining > 0:
            time.sleep(remaining)
        self._last_request = time.monotonic()

    def get(self, record_id: str, url: str) -> Path:
        destination = _cache_path(self.cache_dir, record_id, url)
        if destination.is_file() and not self.refresh:
            _validate_image_file(destination, record_id)
            return destination
        if self.offline:
            raise AnalysisError(f"{record_id}: cover is not cached and --offline was requested")

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        last_error: Optional[BaseException] = None
        for attempt in range(1, self.retries + 1):
            try:
                self._pace()
                request = Request(
                    url,
                    headers={
                        "Accept": "image/jpeg,image/png,image/webp",
                        "User-Agent": USER_AGENT,
                    },
                )
                with urlopen(request, timeout=self.timeout) as response:
                    final_url = response.geturl()
                    if not _approved_delivery_url(final_url):
                        raise AnalysisError(f"{record_id}: cover redirected outside the approved delivery chain")
                    content_type = response.headers.get_content_type().lower()
                    if not content_type.startswith("image/"):
                        raise AnalysisError(f"{record_id}: server returned {content_type!r}, not an image")
                    content_length = response.headers.get("Content-Length")
                    if content_length and int(content_length) > MAX_DOWNLOAD_BYTES:
                        raise AnalysisError(f"{record_id}: cover exceeds the download size limit")
                    data = response.read(MAX_DOWNLOAD_BYTES + 1)
                if len(data) > MAX_DOWNLOAD_BYTES:
                    raise AnalysisError(f"{record_id}: cover exceeds the download size limit")
                if not data:
                    raise AnalysisError(f"{record_id}: server returned an empty cover")

                temporary = destination.with_suffix(destination.suffix + ".part")
                temporary.write_bytes(data)
                try:
                    _validate_image_file(temporary, record_id)
                    os.replace(temporary, destination)
                finally:
                    temporary.unlink(missing_ok=True)
                return destination
            except (HTTPError, URLError, TimeoutError, OSError, AnalysisError, ValueError) as exc:
                last_error = exc
                if isinstance(exc, AnalysisError) or attempt == self.retries:
                    break
                time.sleep(0.35 * attempt)
        raise AnalysisError(f"{record_id}: cover download failed: {last_error}")


def _validate_image_file(path: Path, record_id: str) -> Tuple[int, int]:
    """Fully decode an image to reject truncation, placeholders, and bombs."""

    if path.stat().st_size <= 0 or path.stat().st_size > MAX_DOWNLOAD_BYTES:
        raise AnalysisError(f"{record_id}: cached cover has an invalid file size")
    try:
        with Image.open(path) as probe:
            width, height = probe.size
            if width < MIN_IMAGE_EDGE or height < MIN_IMAGE_EDGE:
                raise AnalysisError(f"{record_id}: cover is too small and may be a placeholder")
            probe.verify()
        with Image.open(path) as decoded:
            decoded.load()
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError) as exc:
        raise AnalysisError(f"{record_id}: cover is not a valid, complete image") from exc
    return width, height


def _working_image(image: Image.Image) -> Image.Image:
    """Normalize orientation/color and resize to a bounded deterministic raster."""

    image = ImageOps.exif_transpose(image).convert("RGB")
    width, height = image.size
    scale = min(1.0, WORKING_LONG_EDGE / max(width, height))
    size = (max(1, round(width * scale)), max(1, round(height * scale)))
    return image if size == image.size else image.resize(size, Image.Resampling.LANCZOS)


def _luminance_metrics(gray: Image.Image) -> Dict[str, float]:
    pixels = list(gray.get_flattened_data() if hasattr(gray, "get_flattened_data") else gray.getdata())
    count = len(pixels)
    mean = sum(pixels) / (255.0 * count)
    variance = sum(((value / 255.0) - mean) ** 2 for value in pixels) / count

    histogram = gray.histogram()
    entropy = -sum(
        (frequency / count) * math.log2(frequency / count)
        for frequency in histogram
        if frequency
    )

    width, height = gray.size
    horizontal_total = sum(
        abs(pixels[row * width + column] - pixels[row * width + column - 1])
        for row in range(height)
        for column in range(1, width)
    )
    vertical_total = sum(
        abs(pixels[row * width + column] - pixels[(row - 1) * width + column])
        for row in range(1, height)
        for column in range(width)
    )
    pair_count = height * max(0, width - 1) + width * max(0, height - 1)
    gradient = horizontal_total / (255.0 * pair_count) if pair_count else 0.0

    blurred = gray.filter(ImageFilter.BoxBlur(1))
    high_frequency = ImageStat.Stat(ImageChops.difference(gray, blurred)).mean[0] / 255.0
    return {
        "mean_luminance": _round(mean),
        "luminance_contrast": _round(math.sqrt(variance)),
        "luminance_entropy_bits": _round(entropy),
        "gradient_energy": _round(gradient),
        "high_frequency_energy": _round(high_frequency),
    }


def _weighted_crop_mean(image: Image.Image, boxes: Sequence[Tuple[int, int, int, int]]) -> Tuple[float, ...]:
    sums = [0.0 for _ in image.getbands()]
    count = 0
    for box in boxes:
        crop = image.crop(box)
        pixels = crop.width * crop.height
        if not pixels:
            continue
        mean = ImageStat.Stat(crop).mean
        for index, value in enumerate(mean):
            sums[index] += value * pixels
        count += pixels
    return tuple(value / count for value in sums) if count else tuple(sums)


def _border_inner_metrics(rgb: Image.Image) -> Dict[str, float]:
    width, height = rgb.size
    band = max(1, min(width, height) // 16)
    border_boxes = (
        (0, 0, width, band),
        (0, height - band, width, height),
        (0, band, band, height - band),
        (width - band, band, width, height - band),
    )
    inner_box = (band, band, width - band, height - band)
    border_rgb = _weighted_crop_mean(rgb, border_boxes)
    inner_rgb = ImageStat.Stat(rgb.crop(inner_box)).mean

    def luminance(channels: Sequence[float]) -> float:
        red, green, blue = (value / 255.0 for value in channels[:3])
        return 0.2126 * red + 0.7152 * green + 0.0722 * blue

    border_luminance = luminance(border_rgb)
    inner_luminance = luminance(inner_rgb)
    color_distance = math.sqrt(sum((left - right) ** 2 for left, right in zip(border_rgb, inner_rgb)))
    color_distance /= 255.0 * math.sqrt(3.0)
    return {
        "border_mean_luminance": _round(border_luminance),
        "inner_mean_luminance": _round(inner_luminance),
        "border_inner_luminance_delta": _round(abs(border_luminance - inner_luminance)),
        "border_inner_color_distance": _round(color_distance),
        "border_band_fraction": _round(band / min(width, height)),
    }


def _palette(rgb: Image.Image) -> List[Dict[str, Any]]:
    quantized = rgb.quantize(
        colors=PALETTE_COLORS,
        method=Image.Quantize.MEDIANCUT,
        dither=Image.Dither.NONE,
    )
    raw_palette = quantized.getpalette() or []
    total = rgb.width * rgb.height
    colors = quantized.getcolors(maxcolors=PALETTE_COLORS) or []
    entries: List[Tuple[int, str]] = []
    for count, index in colors:
        offset = index * 3
        red, green, blue = raw_palette[offset : offset + 3]
        entries.append((count, f"#{red:02x}{green:02x}{blue:02x}"))
    entries.sort(key=lambda entry: (-entry[0], entry[1]))
    # Shares are independently rounded; ``pixel_count`` keeps the exact ratio.
    return [
        {"hex": color, "share": _round(count / total), "pixel_count": count}
        for count, color in entries
    ]


def analyze_file(path: Path, record_id: str, url: str, source_id: str) -> Dict[str, Any]:
    source_bytes = path.read_bytes()
    source_sha256 = "sha256:" + hashlib.sha256(source_bytes).hexdigest()
    raw_width, raw_height = _validate_image_file(path, record_id)
    try:
        with Image.open(path) as source:
            source_format = str(source.format or "unknown").lower()
            oriented = ImageOps.exif_transpose(source)
            orientation_applied = oriented.size != source.size
            display_width, display_height = oriented.size
            working = _working_image(source)
    except (UnidentifiedImageError, Image.DecompressionBombError, OSError) as exc:
        raise AnalysisError(f"{record_id}: cover could not be decoded for analysis") from exc

    gray = working.convert("L")
    optical_metrics = _luminance_metrics(gray)
    optical_metrics.update(_border_inner_metrics(working))
    result = {
        "schema": ANALYSIS_SCHEMA,
        "source_pixels": {"width": display_width, "height": display_height},
        "stored_raster_pixels": {"width": raw_width, "height": raw_height},
        "source_bytes": len(source_bytes),
        "source_sha256": source_sha256,
        "source_format": source_format,
        "aspect_ratio": _round(display_width / display_height),
        "palette": _palette(working),
        "optical_metrics": optical_metrics,
        "provenance": {
            "provider": "openlibrary",
            "source_id": source_id,
            "analyzed_from_url": url,
            "working_pixels": {"width": working.width, "height": working.height},
            "orientation_applied": orientation_applied,
            "algorithm": f"ShelfSignals Pillow analyzer {ANALYZER_VERSION}",
            "interpretation": NON_PHYSICAL_NOTE,
        },
    }
    return result


def _load_manifest(path: Path) -> MutableMapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise AnalysisError(f"could not read manifest {path}: {exc}") from exc
    if not isinstance(value, dict) or value.get("schema") != EXPECTED_MANIFEST_SCHEMA:
        raise AnalysisError(f"{path} is not a {EXPECTED_MANIFEST_SCHEMA} manifest")
    if not isinstance(value.get("items"), dict):
        raise AnalysisError(f"{path} does not contain an item map")
    return value


def _candidates(manifest: Mapping[str, Any]) -> Iterable[Tuple[str, MutableMapping[str, Any], str]]:
    items = manifest["items"]
    for record_id in sorted(items):
        item = items[record_id]
        if not isinstance(item, dict):
            raise AnalysisError(f"{record_id}: manifest item is not an object")
        # Unresolved records are outside the visual sample and remain untouched.
        if item.get("status") != "resolved":
            continue
        yield record_id, item, _validate_approved_item(record_id, item)


def analyze_manifest(
    manifest: MutableMapping[str, Any],
    fetcher: CoverFetcher,
) -> Tuple[MutableMapping[str, Any], Dict[str, Any]]:
    analyzed: Dict[str, Any] = {}
    failures: List[str] = []
    candidates = list(_candidates(manifest))
    if not candidates:
        raise AnalysisError("manifest has no resolved exact-match covers to analyze")

    for index, (record_id, item, url) in enumerate(candidates, start=1):
        try:
            path = fetcher.get(record_id, url)
            analysis = analyze_file(path, record_id, url, str(item["source_id"]))
            item["image_analysis"] = analysis
            # Preserve the long-standing numeric field while replacing its
            # placeholder precision with the measured raster ratio.
            item["aspect_ratio"] = analysis["aspect_ratio"]
            analyzed[record_id] = analysis
            print(f"[{index:02d}/{len(candidates):02d}] {record_id}: {path.name}", file=sys.stderr)
        except AnalysisError as exc:
            failures.append(str(exc))

    if failures:
        raise AnalysisError("analysis was incomplete:\n  - " + "\n  - ".join(failures))

    analysis_checksum = _canonical_sha256(analyzed)
    manifest["analysis"] = {
        "schema": ANALYSIS_SCHEMA,
        "analyzer_version": ANALYZER_VERSION,
        "engine": {"name": "Pillow", "version": PILLOW_VERSION},
        "working_long_edge_pixels": WORKING_LONG_EDGE,
        "palette_color_count": PALETTE_COLORS,
        "items_analyzed": len(analyzed),
        "analysis_sha256": analysis_checksum,
        "source_policy": (
            "Existing manifest entries resolved by exact ISBN to the approved Open Library "
            "Covers HTTPS host; HTTPS delivery may use Open Library's narrowly validated Internet "
            "Archive image backend. No provider discovery or title matching occurs here."
        ),
        "interpretation": NON_PHYSICAL_NOTE,
    }
    summary = manifest.setdefault("summary", {})
    if isinstance(summary, dict):
        summary["analyzed"] = len(analyzed)
    report = {
        "items_analyzed": len(analyzed),
        "analysis_sha256": analysis_checksum,
        "cache": str(fetcher.cache_dir),
    }
    return manifest, report


def _atomic_write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(value, ensure_ascii=False, indent=2) + "\n"
    descriptor, temporary_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_name, path)
    finally:
        try:
            os.unlink(temporary_name)
        except FileNotFoundError:
            pass


def self_test() -> None:
    """Exercise deterministic metric and allowlist behavior without network access."""

    with tempfile.TemporaryDirectory(prefix="shelfsignals-cover-selftest-") as directory:
        root = Path(directory)
        solid_path = root / "solid.png"
        checker_path = root / "checker.png"
        Image.new("RGB", (96, 144), (80, 120, 160)).save(solid_path)
        checker = Image.new("RGB", (96, 144))
        checker.putdata(
            [
                (245, 245, 245) if (x // 4 + y // 4) % 2 else (10, 10, 10)
                for y in range(144)
                for x in range(96)
            ]
        )
        checker.save(checker_path)

        url = "https://covers.openlibrary.org/b/isbn/0374226261-L.jpg?default=false"
        first = analyze_file(solid_path, "solid", url, "0374226261")
        second = analyze_file(solid_path, "solid", url, "0374226261")
        detailed = analyze_file(checker_path, "checker", url, "0374226261")
        assert first == second, "analysis must be deterministic"
        assert first["source_pixels"] == {"width": 96, "height": 144}
        assert first["aspect_ratio"] == 0.666667
        assert first["optical_metrics"]["gradient_energy"] == 0.0
        assert first["optical_metrics"]["high_frequency_energy"] == 0.0
        assert detailed["optical_metrics"]["gradient_energy"] > 0.1
        assert detailed["optical_metrics"]["high_frequency_energy"] > 0.05
        assert sum(entry["pixel_count"] for entry in first["palette"]) == 96 * 144

        approved = {
            "status": "resolved",
            "source": "openlibrary",
            "source_id": "0374226261",
            "match_method": "isbn",
            "match_confidence": 1.0,
            "image_url": url,
        }
        assert _validate_approved_item("approved", approved) == url
        archive_delivery = (
            "https://ia600507.us.archive.org/view_archive.php?"
            "archive=/8/items/l_covers_0009/l_covers_0009_41.zip&file=0009416866-L.jpg"
        )
        assert _approved_delivery_url(archive_delivery)
        assert not _approved_delivery_url("https://archive.org/download/unrelated.zip")
        rejected = dict(approved, image_url="https://example.com/cover.jpg")
        try:
            _validate_approved_item("rejected", rejected)
        except AnalysisError:
            pass
        else:  # pragma: no cover - a failing assertion path
            raise AssertionError("non-allowlisted URL must be rejected")
    print("cover optical analyzer self-test: ok")


def parse_args(argv: Optional[Sequence[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--cache-dir", type=Path, default=DEFAULT_CACHE)
    parser.add_argument("--timeout", type=float, default=30.0)
    parser.add_argument("--retries", type=int, default=3)
    parser.add_argument("--offline", action="store_true", help="use validated cache entries only")
    parser.add_argument("--refresh", action="store_true", help="redownload every cover")
    parser.add_argument("--dry-run", action="store_true", help="analyze and report without writing JSON")
    parser.add_argument("--self-test", action="store_true", help="run local deterministic tests and exit")
    return parser.parse_args(argv)


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = parse_args(argv)
    if args.self_test:
        self_test()
        return 0
    if args.retries < 1 or args.timeout <= 0:
        raise AnalysisError("--retries and --timeout must be positive")
    manifest = _load_manifest(args.manifest)
    fetcher = CoverFetcher(
        cache_dir=args.cache_dir,
        timeout=args.timeout,
        retries=args.retries,
        offline=args.offline,
        refresh=args.refresh,
    )
    updated, report = analyze_manifest(manifest, fetcher)
    report["output"] = str(args.output)
    report["dry_run"] = bool(args.dry_run)
    if not args.dry_run:
        _atomic_write_json(args.output, updated)
    print(json.dumps(report, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except AnalysisError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(1)
