#!/usr/bin/env python3
"""Ingest reviewed Clark-copy or rights-cleared exact-edition cover images.

The command is intentionally local-only: it never discovers or downloads an
image.  Original files remain outside ``docs``.  After strict catalog,
identity, human-review, and rights checks, Pillow produces two bounded,
metadata-stripped WebP derivatives at immutable content-bound paths.  The
resulting reviewed-reference manifest still has no publication effect until it
passes ``build_cover_index.py --cleared-references``.
"""

from __future__ import annotations

import argparse
import io
import json
import os
import tempfile
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    from cleared_cover_contract import (
        CLEARED_REFERENCES_SCHEMA,
        CONTRACT_VERSION,
        DERIVATIVE_PROFILES,
        INTAKE_SCHEMA,
        MAX_SOURCE_PIXELS,
        PUBLIC_COVER_PREFIX,
        ClearedCoverError,
        candidate_fingerprint,
        derivative_asset_set_fingerprint,
        load_catalog,
        minimal_webp_vp8x,
        public_catalog_identity,
        resolve_source_file,
        sha256_bytes,
        sha256_file,
        validate_cleared_references,
        validate_intake_manifest,
        webp_dimensions,
    )
except ModuleNotFoundError:  # Supports ``python -m scripts.ingest_cleared_covers``.
    from scripts.cleared_cover_contract import (  # type: ignore
        CLEARED_REFERENCES_SCHEMA,
        CONTRACT_VERSION,
        DERIVATIVE_PROFILES,
        INTAKE_SCHEMA,
        MAX_SOURCE_PIXELS,
        PUBLIC_COVER_PREFIX,
        ClearedCoverError,
        candidate_fingerprint,
        derivative_asset_set_fingerprint,
        load_catalog,
        minimal_webp_vp8x,
        public_catalog_identity,
        resolve_source_file,
        sha256_bytes,
        sha256_file,
        validate_cleared_references,
        validate_intake_manifest,
        webp_dimensions,
    )


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CATALOG = ROOT / "docs/data/sekula_index.json"
DEFAULT_DOCS_ROOT = ROOT / "docs"
DEFAULT_OUTPUT_DIR = DEFAULT_DOCS_ROOT / PUBLIC_COVER_PREFIX
DEFAULT_REFERENCES = ROOT / ".cache/cover-review/cleared-cover-references.json"
PIPELINE_NAME = "ingest_cleared_covers.py"
PILLOW_HELP = (
    "Pillow with WebP support is required for source inspection and local derivatives. "
    "Install it in an isolated environment with `python -m pip install Pillow` and rerun the command."
)


def load_pillow() -> tuple[Any, Any, Any, str]:
    try:
        from PIL import Image, ImageOps, features
        from PIL import __version__ as pillow_version
    except ImportError as exc:
        raise ClearedCoverError(PILLOW_HELP) from exc
    if not features.check("webp"):
        raise ClearedCoverError(f"{PILLOW_HELP} This Pillow build does not include WebP encoding.")
    Image.MAX_IMAGE_PIXELS = MAX_SOURCE_PIXELS
    return Image, ImageOps, features, str(pillow_version)


def probe_source_image(path: Path) -> dict[str, Any]:
    Image, ImageOps, _, _ = load_pillow()
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(path) as opened:
                if int(getattr(opened, "n_frames", 1)) != 1:
                    raise ClearedCoverError(f"source image must be single-frame: {path.name}")
                image_format = str(opened.format or "").lower()
                if image_format == "jpg":
                    image_format = "jpeg"
                opened.load()
                oriented = ImageOps.exif_transpose(opened)
                width, height = oriented.size
    except ClearedCoverError:
        raise
    except Exception as exc:
        raise ClearedCoverError(f"source image could not be decoded safely: {path.name}: {exc}") from exc
    return {
        "sha256": sha256_file(path),
        "width": int(width),
        "height": int(height),
        "format": image_format,
        "bytes": path.stat().st_size,
        "animated": False,
    }


def _rgb_without_metadata(image: Any, Image: Any) -> Any:
    if image.mode in {"RGBA", "LA"} or (image.mode == "P" and "transparency" in image.info):
        rgba = image.convert("RGBA")
        background = Image.new("RGBA", rgba.size, (255, 255, 255, 255))
        background.alpha_composite(rgba)
        return background.convert("RGB")
    return image.convert("RGB")


def render_derivatives(
    *,
    source_path: Path,
    catalog_id: str,
    source_image: Mapping[str, Any],
    output_dir: Path,
    pillow_version: str,
) -> tuple[str, list[dict[str, Any]]]:
    """Create immutable bounded derivatives, never copying the source original."""

    Image, ImageOps, _, _ = load_pillow()
    asset_fingerprint = derivative_asset_set_fingerprint(source_image, pillow_version)
    asset_key = asset_fingerprint.removeprefix("sha256:")[:20]
    target_dir = output_dir / catalog_id / asset_key
    target_dir.mkdir(parents=True, exist_ok=True)
    derivatives: list[dict[str, Any]] = []
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(source_path) as opened:
                if int(getattr(opened, "n_frames", 1)) != 1:
                    raise ClearedCoverError(f"source image must be single-frame: {source_path.name}")
                opened.load()
                oriented = ImageOps.exif_transpose(opened)
                prepared = _rgb_without_metadata(oriented, Image)
                for profile in DERIVATIVE_PROFILES:
                    rendered = prepared.copy()
                    rendered.thumbnail(
                        (int(profile["max_width"]), int(profile["max_height"])),
                        resample=Image.Resampling.LANCZOS,
                    )
                    buffer = io.BytesIO()
                    rendered.save(
                        buffer,
                        format="WEBP",
                        quality=int(profile["quality"]),
                        method=6,
                        exact=True,
                    )
                    payload = buffer.getvalue()
                    width, height = webp_dimensions(payload, f"{catalog_id} {profile['profile']} derivative")
                    filename = f"cover-{profile['profile']}.webp"
                    destination = target_dir / filename
                    if destination.exists():
                        if not destination.is_file() or destination.is_symlink() or destination.read_bytes() != payload:
                            raise ClearedCoverError(
                                f"immutable derivative path already contains different bytes: {destination}"
                            )
                    else:
                        with tempfile.NamedTemporaryFile(
                            mode="wb", dir=target_dir, prefix=f".{filename}.", suffix=".tmp", delete=False
                        ) as temporary:
                            temporary.write(payload)
                            temporary.flush()
                            os.fsync(temporary.fileno())
                            temporary_path = Path(temporary.name)
                        try:
                            os.replace(temporary_path, destination)
                        finally:
                            if temporary_path.exists():
                                temporary_path.unlink()
                    public_url = f"{PUBLIC_COVER_PREFIX}/{catalog_id}/{asset_key}/{filename}"
                    derivatives.append({
                        "profile": profile["profile"],
                        "url": public_url,
                        "width": width,
                        "height": height,
                        "format": "webp",
                        "sha256": sha256_bytes(payload),
                        "bytes": len(payload),
                        "max_width": profile["max_width"],
                        "max_height": profile["max_height"],
                    })
    except ClearedCoverError:
        raise
    except Exception as exc:
        raise ClearedCoverError(f"failed to render {catalog_id} safely: {exc}") from exc
    return asset_fingerprint, derivatives


def build_cleared_reference_manifest(
    validated_items: Sequence[Mapping[str, Any]],
    *,
    catalog: Sequence[Mapping[str, Any]],
    catalog_sha256: str,
    intake_sha256: str,
    generated_at: str,
    output_dir: Path,
    pillow_version: str,
) -> dict[str, Any]:
    public_items: dict[str, Any] = {}
    scope_counts = {"clark_copy": 0, "exact_edition": 0}
    for item in sorted(validated_items, key=lambda candidate: str(candidate["catalog_id"])):
        catalog_id = str(item["catalog_id"])
        source_path = item.get("_source_path")
        if not isinstance(source_path, Path):
            raise ClearedCoverError(f"{catalog_id} was not validated against a local source file")
        asset_fingerprint, derivatives = render_derivatives(
            source_path=source_path,
            catalog_id=catalog_id,
            source_image=item["image"],
            output_dir=output_dir,
            pillow_version=pillow_version,
        )
        derivative_by_profile = {entry["profile"]: entry for entry in derivatives}
        display = derivative_by_profile["display"]
        thumbnail = derivative_by_profile["thumbnail"]
        review_fingerprint = candidate_fingerprint(
            catalog_id=catalog_id,
            catalog_record_fingerprint_value=item["catalog_identity"]["record_fingerprint"],
            provider=str(item["provider"]),
            scope=str(item["scope"]),
            matched_identifiers=item["identity"]["matched_identifiers"],
            source=item["source"],
            source_image=item["image"],
            rights=item["rights"],
            identity_attestation=item["identity"]["attestation"],
            review=item["review"],
        )
        public_items[catalog_id] = {
            "status": "resolved",
            "provider": item["provider"],
            "scope": item["scope"],
            "catalog_identity": item["catalog_identity"],
            "matched_identifiers": item["identity"]["matched_identifiers"],
            "source": item["source"],
            "image": {
                "image_url": display["url"],
                "thumbnail_url": thumbnail["url"],
                "width": display["width"],
                "height": display["height"],
                "source": item["image"],
                "derivatives": derivatives,
            },
            "rights": item["rights"],
            "review": {
                "status": "approved",
                "reviewer": item["review"]["reviewer"],
                "reviewed_at": item["review"]["reviewed_at"],
                "evidence_note": item["review"]["evidence_note"],
                "candidate_fingerprint": review_fingerprint,
            },
            "gate_receipt": {
                "front_cover_confirmed": True,
                "copy_or_edition_confirmed": True,
                "visual_check": True,
                "rights_scope": "local_derivatives",
                "identity_attestation": item["identity"]["attestation"],
                "candidate_fingerprint": review_fingerprint,
            },
            "provenance": {
                "catalog_url": item["catalog_identity"]["record_url"],
                "catalog_dataset_sha256": catalog_sha256,
                "catalog_record_fingerprint": item["catalog_identity"]["record_fingerprint"],
                "source_file_name": Path(str(item["source_file"])).name,
                "source_id": item["source"]["source_id"],
                "source_reference_url": item["source"]["source_reference_url"],
                "asset_set_fingerprint": asset_fingerprint,
                "ingested_at": generated_at,
            },
        }
        scope_counts[str(item["scope"])] += 1
    return {
        "schema": CLEARED_REFERENCES_SCHEMA,
        "version": CONTRACT_VERSION,
        "generated_at": generated_at,
        "source": {
            "pipeline": PIPELINE_NAME,
            "pipeline_version": CONTRACT_VERSION,
            "catalog_dataset_sha256": catalog_sha256,
            "catalog_record_count": len(catalog),
            "intake_sha256": intake_sha256,
            "pillow_version": pillow_version,
        },
        "policy": {
            "unreviewed_items_included": False,
            "original_binaries_included": False,
            "local_derivatives_only": True,
        },
        "summary": {
            "published": len(public_items),
            "clark_copy": scope_counts["clark_copy"],
            "exact_edition": scope_counts["exact_edition"],
        },
        "items": public_items,
    }


def atomic_write_json(path: Path, payload: Mapping[str, Any], *, replace: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists() and not replace:
        raise ClearedCoverError(f"output already exists; inspect it or pass --replace: {path}")
    serialized = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False
    ) as temporary:
        temporary.write(serialized)
        temporary.flush()
        os.fsync(temporary.fileno())
        temporary_path = Path(temporary.name)
    try:
        os.replace(temporary_path, path)
    finally:
        if temporary_path.exists():
            temporary_path.unlink()


def generated_timestamp(value: str) -> str:
    if value:
        if len(value) != 20 or not value.endswith("Z"):
            raise ClearedCoverError("--generated-at must be a second-precision UTC timestamp")
        try:
            datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
        except ValueError as exc:
            raise ClearedCoverError("--generated-at must be a real second-precision UTC timestamp") from exc
        return value
    epoch = os.environ.get("SOURCE_DATE_EPOCH")
    if epoch:
        try:
            return datetime.fromtimestamp(int(epoch), timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
        except (ValueError, OverflowError) as exc:
            raise ClearedCoverError("SOURCE_DATE_EPOCH must be an integer Unix timestamp") from exc
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _load_intake(path: Path) -> tuple[Any, bytes]:
    raw = path.read_bytes()
    try:
        return json.loads(raw), raw
    except json.JSONDecodeError as exc:
        raise ClearedCoverError(f"intake is not valid JSON: {exc}") from exc


def run_validate(args: argparse.Namespace) -> int:
    catalog, _, catalog_sha256 = load_catalog(args.catalog)
    intake, _ = _load_intake(args.intake)
    source_root = (args.source_root or args.intake.parent).resolve()
    items = validate_intake_manifest(
        intake,
        catalog=catalog,
        catalog_sha256=catalog_sha256,
        source_root=source_root,
        source_probe=probe_source_image,
    )
    print(f"validated {len(items)} cleared cover intake item(s); no files written")
    return 0


def run_ingest(args: argparse.Namespace) -> int:
    catalog, _, catalog_sha256 = load_catalog(args.catalog)
    intake, intake_bytes = _load_intake(args.intake)
    source_root = (args.source_root or args.intake.parent).resolve()
    docs_root = args.docs_root.resolve()
    output_dir = args.output_dir.resolve()
    references_output = args.references_output.resolve()
    expected_output = (docs_root / PUBLIC_COVER_PREFIX).resolve()
    try:
        expected_output.relative_to(docs_root)
    except ValueError as exc:
        raise ClearedCoverError("the public cover output path escapes --docs-root through a symlink") from exc
    if output_dir != expected_output:
        raise ClearedCoverError(
            f"--output-dir must map exactly to {PUBLIC_COVER_PREFIX} beneath --docs-root ({expected_output})"
        )
    try:
        references_output.relative_to(docs_root)
    except ValueError:
        pass
    else:
        if not args.allow_docs_output:
            raise ClearedCoverError(
                "--references-output is beneath docs; pass --allow-docs-output only after reviewing its public provenance fields"
            )
    _, _, _, pillow_version = load_pillow()
    items = validate_intake_manifest(
        intake,
        catalog=catalog,
        catalog_sha256=catalog_sha256,
        source_root=source_root,
        source_probe=probe_source_image,
    )
    for item in items:
        source_path = item.get("_source_path")
        if isinstance(source_path, Path):
            try:
                source_path.resolve().relative_to(docs_root)
            except ValueError:
                pass
            else:
                raise ClearedCoverError(
                    f"{item['catalog_id']} original source is inside docs; move it to private storage before ingest"
                )
    generated_at = generated_timestamp(args.generated_at)
    manifest = build_cleared_reference_manifest(
        items,
        catalog=catalog,
        catalog_sha256=catalog_sha256,
        intake_sha256=sha256_bytes(intake_bytes),
        generated_at=generated_at,
        output_dir=output_dir,
        pillow_version=pillow_version,
    )
    # Reopen and checksum every derivative through the same contract used by
    # the index builder before exposing a reviewed-reference manifest.
    validate_cleared_references(
        manifest,
        catalog=catalog,
        catalog_sha256=catalog_sha256,
        docs_root=docs_root,
    )
    atomic_write_json(references_output, manifest, replace=args.replace)
    print(
        f"wrote {references_output} ({manifest['summary']['published']} reviewed references; "
        "original binaries excluded)"
    )
    print(f"wrote immutable WebP derivatives beneath {output_dir}")
    print("publication effect: none; run build_cover_index.py --cleared-references only after reviewing this manifest")
    return 0


def run_scaffold(args: argparse.Namespace) -> int:
    catalog, _, catalog_sha256 = load_catalog(args.catalog)
    record_by_id = {str(record.get("id") or ""): record for record in catalog}
    record = record_by_id.get(args.catalog_id)
    if record is None:
        raise ClearedCoverError("--catalog-id is outside the canonical catalog")
    source_root = (args.source_root or Path.cwd()).resolve()
    if args.provider == "clark" and args.scope != "clark_copy":
        raise ClearedCoverError("a Clark scaffold must use --scope clark_copy")
    relative_path = args.source_file
    if relative_path.is_absolute() or ".." in relative_path.parts:
        raise ClearedCoverError("--source-file must be relative to --source-root and may not traverse")
    relative = relative_path.as_posix()
    source_path = resolve_source_file(source_root, relative)
    probe = probe_source_image(source_path)
    matched = [{"type": "catalog_id", "value": args.catalog_id}] if args.scope == "clark_copy" else []
    source_reference = str(record.get("record_url") or "") if args.provider == "clark" else "https://REPLACE-WITH-SOURCE-RECORD.example/"
    scaffold = {
        "schema": INTAKE_SCHEMA,
        "catalog": {"dataset_sha256": catalog_sha256, "record_count": len(catalog)},
        "items": [{
            "catalog_id": args.catalog_id,
            "catalog_identity": public_catalog_identity(record, catalog_sha256),
            "provider": args.provider,
            "scope": args.scope,
            "source_file": relative,
            "source": {
                "source_id": "REPLACE-WITH-CAPTURE-OR-ASSET-ID",
                "source_reference_url": source_reference,
                "creator": "REPLACE-WITH-PHOTOGRAPHER-OR-ASSET-CREATOR",
                "source_date": "REPLACE-WITH-YYYY-MM-DD",
            },
            "identity": {
                "front_cover_confirmed": False,
                "copy_or_edition_confirmed": False,
                "attestation": "REPLACE-WITH-THE-OBJECT-IDENTITY-AND-FRONT-COVER-EVIDENCE",
                "matched_identifiers": matched,
            },
            "image": {key: probe[key] for key in ("sha256", "width", "height", "format", "bytes")},
            "rights": {
                "basis": "institution_permission",
                "public_display": False,
                "derivatives_allowed": False,
                "license_or_permission_reference": "REPLACE-WITH-PERMISSION-OR-LICENSE-ID",
                "evidence_url": "https://REPLACE-WITH-RIGHTS-EVIDENCE.example/",
                "rights_holder": "REPLACE-WITH-RIGHTS-HOLDER",
                "credit_line": "REPLACE-WITH-REQUIRED-CREDIT-LINE",
                "evidence_note": "REPLACE-WITH-THE-PUBLIC-DISPLAY-AND-DERIVATIVE-RIGHTS-EVIDENCE",
            },
            "review": {
                "reviewer": "REPLACE-WITH-NAMED-REVIEWER",
                "reviewed_at": "REPLACE-WITH-YYYY-MM-DDTHH:MM:SSZ",
                "evidence_note": "REPLACE-WITH-THE-REVIEWER-EVIDENCE-NOTE",
            },
        }],
    }
    atomic_write_json(args.output, scaffold, replace=args.replace)
    print(f"wrote non-publishable intake scaffold {args.output}")
    print("The false gates and REPLACE fields are intentional; validate/ingest will reject them until reviewed.")
    return 0


def run_self_test() -> int:
    # This test intentionally stays Pillow-free so contract checks run in a
    # minimal CI environment.  Image encoding is exercised only when the
    # documented Pillow dependency is present.
    payload = minimal_webp_vp8x(320, 480)
    assert webp_dimensions(payload) == (320, 480)
    record = {
        "id": "alma991000000000000001",
        "title": "Fixture title",
        "authors": ["Fixture author"],
        "year": "2001",
        "call_number": "N1 .F59",
        "isbns": ["9780374226268"],
        "oclc_numbers": [],
        "lccn": [],
        "record_url": "https://library.clarkart.edu/fixture",
    }
    catalog_sha = "sha256:" + "a" * 64
    with tempfile.TemporaryDirectory() as temporary:
        source_root = Path(temporary)
        source_path = source_root / "fixture.jpg"
        source_path.write_bytes(b"private-fixture-bytes")
        image = {
            "sha256": sha256_file(source_path),
            "width": 600,
            "height": 900,
            "format": "jpeg",
            "bytes": source_path.stat().st_size,
        }
        intake = {
            "schema": INTAKE_SCHEMA,
            "catalog": {"dataset_sha256": catalog_sha, "record_count": 1},
            "items": [{
                "catalog_id": record["id"],
                "catalog_identity": public_catalog_identity(record, catalog_sha),
                "provider": "clark",
                "scope": "clark_copy",
                "source_file": source_path.name,
                "source": {
                    "source_id": "CLARK-CAPTURE-1",
                    "source_reference_url": record["record_url"],
                    "creator": "Fixture Photographer",
                    "source_date": "2026-07-14",
                },
                "identity": {
                    "front_cover_confirmed": True,
                    "copy_or_edition_confirmed": True,
                    "attestation": "The reviewer compared the catalog ID and photographed object label.",
                    "matched_identifiers": [{"type": "catalog_id", "value": record["id"]}],
                },
                "image": image,
                "rights": {
                    "basis": "institution_permission",
                    "public_display": True,
                    "derivatives_allowed": True,
                    "license_or_permission_reference": "CLARK-COVER-PERMISSION-1",
                    "evidence_url": "https://www.clarkart.edu/fixture-rights",
                    "rights_holder": "Fixture Rights Holder",
                    "credit_line": "Fixture credit line",
                    "evidence_note": "Written permission authorizes public display and local derivatives.",
                },
                "review": {
                    "reviewer": "Fixture Reviewer",
                    "reviewed_at": "2026-07-14T00:00:00Z",
                    "evidence_note": "Front-cover role, Clark-copy identity, and rights evidence were reviewed.",
                },
            }],
        }

        def fake_probe(_: Path) -> Mapping[str, Any]:
            return {**image, "animated": False}

        validated = validate_intake_manifest(
            intake,
            catalog=[record],
            catalog_sha256=catalog_sha,
            source_root=source_root,
            source_probe=fake_probe,
        )
        assert len(validated) == 1
        unsafe = json.loads(json.dumps(intake))
        unsafe["items"][0]["rights"]["derivatives_allowed"] = False
        try:
            validate_intake_manifest(unsafe, catalog=[record], catalog_sha256=catalog_sha)
            raise AssertionError("missing derivative permission should fail closed")
        except ClearedCoverError as exc:
            assert "derivatives_allowed" in str(exc)
    print("cleared-cover ingest self-test passed (pure contract; Pillow not required)")
    return 0


def run_encoder_self_test() -> int:
    """Exercise the real Pillow/WebP path without creating a public asset."""

    Image, _, _, pillow_version = load_pillow()
    with tempfile.TemporaryDirectory() as temporary:
        root = Path(temporary)
        source_path = root / "private-encoder-fixture.png"
        fixture = Image.new("RGBA", (900, 1200), (36, 58, 71, 180))
        fixture.save(source_path, format="PNG", dpi=(144, 144), author="metadata must not survive")
        source_image = probe_source_image(source_path)
        _, derivatives = render_derivatives(
            source_path=source_path,
            catalog_id="alma991000000000000001",
            source_image=source_image,
            output_dir=root / "not-public",
            pillow_version=pillow_version,
        )
        assert {entry["profile"] for entry in derivatives} == {"thumbnail", "display"}
        for entry in derivatives:
            assert entry["width"] <= entry["max_width"]
            assert entry["height"] <= entry["max_height"]
            derivative_path = root / "not-public" / "alma991000000000000001" / entry["url"].split("/")[-2] / Path(entry["url"]).name
            with Image.open(derivative_path) as rendered:
                rendered.load()
                assert rendered.format == "WEBP"
                assert rendered.mode == "RGB"
                assert int(getattr(rendered, "n_frames", 1)) == 1
                assert len(rendered.getexif()) == 0
                assert rendered.size == (entry["width"], entry["height"])
    print(f"cleared-cover encoder self-test passed (Pillow {pillow_version}; WebP; no public files written)")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)

    validate_parser = subparsers.add_parser("validate", help="decode sources and validate every evidence gate; write nothing")
    validate_parser.add_argument("--intake", type=Path, required=True)
    validate_parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    validate_parser.add_argument("--source-root", type=Path)
    validate_parser.set_defaults(handler=run_validate)

    ingest_parser = subparsers.add_parser("ingest", help="write bounded derivatives and reviewed references")
    ingest_parser.add_argument("--intake", type=Path, required=True)
    ingest_parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    ingest_parser.add_argument("--source-root", type=Path)
    ingest_parser.add_argument("--docs-root", type=Path, default=DEFAULT_DOCS_ROOT)
    ingest_parser.add_argument("--output-dir", type=Path, default=DEFAULT_OUTPUT_DIR)
    ingest_parser.add_argument("--references-output", type=Path, default=DEFAULT_REFERENCES)
    ingest_parser.add_argument("--generated-at", default="")
    ingest_parser.add_argument("--replace", action="store_true")
    ingest_parser.add_argument(
        "--allow-docs-output",
        action="store_true",
        help="allow the reviewed-reference JSON itself beneath docs after a separate public-provenance review",
    )
    ingest_parser.set_defaults(handler=run_ingest)

    scaffold_parser = subparsers.add_parser("scaffold", help="inspect one source and make a deliberately non-publishable intake scaffold")
    scaffold_parser.add_argument("--catalog", type=Path, default=DEFAULT_CATALOG)
    scaffold_parser.add_argument("--catalog-id", required=True)
    scaffold_parser.add_argument("--source-root", type=Path)
    scaffold_parser.add_argument("--source-file", type=Path, required=True)
    scaffold_parser.add_argument("--provider", choices=("clark", "licensed"), default="clark")
    scaffold_parser.add_argument("--scope", choices=("clark_copy", "exact_edition"), default="clark_copy")
    scaffold_parser.add_argument("--output", type=Path, required=True)
    scaffold_parser.add_argument("--replace", action="store_true")
    scaffold_parser.set_defaults(handler=run_scaffold)

    self_test_parser = subparsers.add_parser("self-test", help="run Pillow-free contract checks")
    self_test_parser.set_defaults(handler=lambda _: run_self_test())
    encoder_test_parser = subparsers.add_parser("encoder-self-test", help="exercise the real Pillow/WebP encoder in a temporary directory")
    encoder_test_parser.set_defaults(handler=lambda _: run_encoder_self_test())
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    try:
        return int(args.handler(args))
    except (ClearedCoverError, OSError, json.JSONDecodeError) as exc:
        raise SystemExit(f"cleared-cover ingest refused: {exc}") from exc


if __name__ == "__main__":
    raise SystemExit(main())
