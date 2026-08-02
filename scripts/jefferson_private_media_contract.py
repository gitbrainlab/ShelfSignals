#!/usr/bin/env python3
"""Strict metadata contract for authenticated Jefferson photo bundles."""

from __future__ import annotations

import datetime as dt
import re
from typing import Any, Mapping


SCHEMA = "shelfsignals-private-media-bundle@1"
SECURITY_NOTICE = (
    "This manifest requires gateway authentication. Possession of this bundle "
    "is not access control or public-reuse permission."
)
ROOT_FIELDS = {
    "schema", "collection_id", "audience", "generated_at", "unit_of_count",
    "security_notice", "items",
}
ITEM_FIELDS = {
    "id", "entity_type", "context_scope", "asset_path", "thumbnail_path",
    "mime_type", "bytes", "sha256", "width", "height", "alt", "caption",
    "captured_on", "creator", "rights", "evidence",
}
RIGHTS_FIELDS = {"status", "public_reuse", "credit_line"}
EVIDENCE_FIELDS = {"source", "book_level_matches", "chapter_labels"}
EXPECTED_IDS = {f"jefferson-exhibition-{number:02d}" for number in range(1, 5)}
ASSET_PATH_RE = re.compile(r"^private/jefferson/display/([0-9a-f]{64})\.jpg$")
SHA256_RE = re.compile(r"^sha256:[0-9a-f]{64}$")
UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


class PrivateMediaContractError(ValueError):
    """Raised when a private photo manifest violates its declared shape."""


def _object(value: Any, fields: set[str], label: str) -> Mapping[str, Any]:
    if not isinstance(value, dict) or set(value) != fields:
        raise PrivateMediaContractError(f"{label} must contain exactly the declared fields")
    return value


def _text(value: Any, label: str, maximum: int) -> str:
    if not isinstance(value, str) or not value.strip() or len(value) > maximum or CONTROL_RE.search(value):
        raise PrivateMediaContractError(f"{label} is not safe bounded text")
    return value


def _integer(value: Any, minimum: int, maximum: int, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or not minimum <= value <= maximum:
        raise PrivateMediaContractError(f"{label} is outside its integer bounds")
    return value


def validate_manifest(raw: Any) -> Mapping[str, Any]:
    manifest = _object(raw, ROOT_FIELDS, "Private media manifest")
    if (
        manifest["schema"] != SCHEMA
        or manifest["collection_id"] != "jefferson"
        or manifest["audience"] != "authenticated_review"
        or manifest["unit_of_count"] != "exhibition context photograph"
        or manifest["security_notice"] != SECURITY_NOTICE
    ):
        raise PrivateMediaContractError("Private media manifest has the wrong identity or security notice")
    generated_at = _text(manifest["generated_at"], "generated_at", 20)
    if not UTC_RE.fullmatch(generated_at):
        raise PrivateMediaContractError("generated_at must be a whole-second UTC timestamp")
    try:
        dt.datetime.strptime(generated_at, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as error:
        raise PrivateMediaContractError("generated_at is not a valid UTC timestamp") from error

    items = manifest["items"]
    if not isinstance(items, list) or len(items) != 4:
        raise PrivateMediaContractError("Private media manifest must contain exactly four photographs")
    identifiers: set[str] = set()
    paths: set[str] = set()
    digests: set[str] = set()
    for index, value in enumerate(items):
        label = f"items[{index}]"
        item = _object(value, ITEM_FIELDS, label)
        identifier = _text(item["id"], f"{label}.id", 64)
        identifiers.add(identifier)
        if item["entity_type"] != "exhibition_context_photograph" or item["context_scope"] != "exhibition_context_only":
            raise PrivateMediaContractError(f"{label} has an unsafe evidence scope")
        asset_path = _text(item["asset_path"], f"{label}.asset_path", 160)
        match = ASSET_PATH_RE.fullmatch(asset_path)
        digest = item["sha256"]
        if not match or not isinstance(digest, str) or not SHA256_RE.fullmatch(digest) or match.group(1) != digest.removeprefix("sha256:"):
            raise PrivateMediaContractError(f"{label} has an inconsistent content-hash asset path")
        if item["thumbnail_path"] != asset_path or item["mime_type"] != "image/jpeg":
            raise PrivateMediaContractError(f"{label} has an unsupported derivative or MIME type")
        _integer(item["bytes"], 1, 50 * 1024 * 1024, f"{label}.bytes")
        _integer(item["width"], 1, 16_384, f"{label}.width")
        _integer(item["height"], 1, 16_384, f"{label}.height")
        for field in ("alt", "caption"):
            _text(item[field], f"{label}.{field}", 1_000)
        captured_on = _text(item["captured_on"], f"{label}.captured_on", 10)
        if not DATE_RE.fullmatch(captured_on):
            raise PrivateMediaContractError(f"{label}.captured_on must use YYYY-MM-DD")
        try:
            dt.date.fromisoformat(captured_on)
        except ValueError as error:
            raise PrivateMediaContractError(f"{label}.captured_on is not a valid date") from error
        creator = _text(item["creator"], f"{label}.creator", 300)
        rights = _object(item["rights"], RIGHTS_FIELDS, f"{label}.rights")
        if (
            rights["status"] != "contributor_authorized_private_review"
            or rights["public_reuse"] != "not_granted"
            or rights["credit_line"] != creator
        ):
            raise PrivateMediaContractError(f"{label} weakens the declared private-review rights")
        evidence = _object(item["evidence"], EVIDENCE_FIELDS, f"{label}.evidence")
        if evidence != {
            "source": "project_contributor_upload",
            "book_level_matches": "not_established",
            "chapter_labels": "visible_in_photograph_only",
        }:
            raise PrivateMediaContractError(f"{label} has an unsupported evidence assertion")
        paths.add(asset_path)
        digests.add(digest)
    if identifiers != EXPECTED_IDS or len(paths) != 4 or len(digests) != 4:
        raise PrivateMediaContractError("Private media items must retain four unique declared identities and binaries")
    return manifest
