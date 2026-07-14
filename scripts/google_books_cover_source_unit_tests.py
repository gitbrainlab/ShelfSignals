#!/usr/bin/env python3
"""No-network tests for the private Google Books cover lead workflow."""

from __future__ import annotations

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from google_books_cover_source import (
    ApiError,
    ApiResponse,
    SourceError,
    build_plan,
    build_query_url,
    build_review_queue,
    cache_policy,
    canonical_isbn,
    empty_state,
    extract_exact_candidates,
    pending_queries,
    prune_expired,
    run_discovery,
    validate_plan,
    validate_state,
)


NOW = "2026-07-14T00:00:00Z"
RETAIN_UNTIL = "2026-07-14T01:00:00Z"


def volume(
    volume_id: str,
    isbn: str,
    *,
    image: str = "https://books.google.com/books/content?id=VOL1&printsec=frontcover&img=1&zoom=2",
) -> dict:
    return {
        "kind": "books#volume",
        "id": volume_id,
        "etag": "etag-value",
        "selfLink": f"https://www.googleapis.com/books/v1/volumes/{volume_id}",
        "volumeInfo": {
            "title": "Provider edition title",
            "authors": ["Provider Author"],
            "publisher": "Provider Press",
            "publishedDate": "2007",
            "industryIdentifiers": [{"type": "ISBN_13", "identifier": isbn}],
            "pageCount": 211,
            "dimensions": {"height": "20.0 cm", "width": "13.0 cm", "thickness": "1.8 cm"},
            "printType": "BOOK",
            "imageLinks": {"thumbnail": image},
            "canonicalVolumeLink": f"https://books.google.com/books?id={volume_id}",
            "language": "en",
        },
        "accessInfo": {"country": "US", "viewability": "PARTIAL", "publicDomain": False},
    }


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def search(self, isbn):
        self.calls.append(isbn)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class GoogleBooksCoverSourceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.state_path = self.root / ".cache" / "state.json"
        self.catalog_path = self.root / "catalog.json"
        self.records = [
            {
                "id": "alma-a",
                "title": "Boy",
                "authors": ["Hanley, James"],
                "year": "2010, 2007, ©1931",
                "call_number": "NE2698 .S4637L 07858",
                "isbns": ["9781847490063", "1847490069"],
                "record_url": "https://library.clarkart.edu/record/a",
            },
            {
                "id": "alma-b",
                "title": "Ways of seeing",
                "authors": ["Berger, John"],
                "year": "1972",
                "call_number": "N7430.5 .B47",
                "isbns": ["9780140135152"],
                "record_url": "https://library.clarkart.edu/record/b",
            },
            {"id": "alma-no-isbn", "title": "No identifier", "isbns": []},
        ]
        self.catalog_path.write_text(json.dumps(self.records), encoding="utf-8")
        self.plan = build_plan(self.records, self.catalog_path, generated_at=NOW)

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def response(self, isbn="9781847490063", volume_id="VOL1") -> ApiResponse:
        payload = {"totalItems": 1, "items": [volume(volume_id, isbn)]}
        raw = json.dumps(payload, sort_keys=True).encode()
        return ApiResponse(
            payload=payload,
            headers={"Cache-Control": "private, max-age=3600"},
            response_sha256="sha256:" + "a" * 64,
            received_bytes=len(raw),
        )

    def test_plan_uses_real_catalog_identifiers_and_deduplicates_isbn_forms(self) -> None:
        self.assertEqual(self.plan["summary"]["catalog_records"], 3)
        self.assertEqual(self.plan["summary"]["records_with_valid_isbn"], 2)
        self.assertEqual(self.plan["summary"]["exact_isbn_queries"], 2)
        first = self.plan["queries"][0]
        self.assertEqual(first["query_key"], "alma-a:9781847490063")
        self.assertEqual(first["catalog"]["title"], "Boy")
        self.assertNotIn("key=", first["request_url_without_credentials"])
        self.assertIn("isbn%3A9781847490063", first["request_url_without_credentials"])
        validate_plan(self.plan, self.records, self.catalog_path)

    def test_plan_rejects_stale_or_reordered_query_evidence(self) -> None:
        changed = deepcopy(self.plan)
        changed["queries"].reverse()
        with self.assertRaisesRegex(SourceError, "fingerprint|changed|reordered"):
            validate_plan(changed, self.records, self.catalog_path)

        changed = deepcopy(self.plan)
        changed["inputs"]["catalog_sha256"] = "sha256:" + "f" * 64
        with self.assertRaisesRegex(SourceError, "stale"):
            validate_plan(changed, self.records, self.catalog_path)

    def test_isbn_normalization_is_checksum_validated(self) -> None:
        self.assertEqual(canonical_isbn("1-84749-006-9"), "9781847490063")
        self.assertEqual(canonical_isbn("9781847490063"), "9781847490063")
        self.assertEqual(canonical_isbn("9781847490064"), "")
        self.assertNotIn("key=", build_query_url("9781847490063"))

    def test_cache_policy_requires_positive_freshness_and_hard_caps_retention(self) -> None:
        accepted = cache_policy({"Cache-Control": "private, max-age=3600"}, NOW)
        self.assertEqual(accepted["retain_until"], RETAIN_UNTIL)
        self.assertFalse(accepted["hard_cap_applied"])
        capped = cache_policy({"Cache-Control": "max-age=999999"}, NOW)
        self.assertEqual(capped["retain_until"], "2026-07-15T00:00:00Z")
        self.assertTrue(capped["hard_cap_applied"])
        aged = cache_policy({"Cache-Control": "max-age=3600", "Age": "600"}, NOW)
        self.assertEqual(aged["retain_until"], "2026-07-14T00:50:00Z")
        self.assertEqual(aged["response_age_seconds"], 600)
        self.assertIsNone(cache_policy({"Cache-Control": "no-store, max-age=3600"}, NOW))
        self.assertIsNone(cache_policy({"Cache-Control": "no-cache, max-age=3600"}, NOW))
        self.assertIsNone(cache_policy({"Cache-Control": "private, max-age=0"}, NOW))
        self.assertIsNone(cache_policy({}, NOW))

    def test_exact_isbn_filter_rejects_title_matches_and_requires_cover_reference(self) -> None:
        query = self.plan["queries"][0]
        payload = {
            "items": [
                volume("WRONG", "9780140135152"),
                volume("NOIMAGE", "9781847490063", image="https://example.com/not-google.jpg"),
                volume("RIGHT", "9781847490063"),
            ]
        }
        cache = cache_policy({"Cache-Control": "max-age=3600"}, NOW)
        candidates, rejected = extract_exact_candidates(
            query,
            payload,
            fetched_at=NOW,
            response_sha256="sha256:" + "a" * 64,
            cache=cache,
        )
        self.assertEqual(len(candidates), 1)
        self.assertEqual(candidates[0]["provider_volume_id"], "RIGHT")
        self.assertEqual(candidates[0]["provider_result_position"], 2)
        self.assertEqual(rejected, {"no_exact_query_isbn": 1, "no_provider_cover_reference": 1})

    def test_raw_physical_fields_are_provider_only_and_never_pixel_inference(self) -> None:
        query = self.plan["queries"][0]
        cache = cache_policy({"Cache-Control": "max-age=3600"}, NOW)
        candidates, _ = extract_exact_candidates(
            query,
            self.response().payload,
            fetched_at=NOW,
            response_sha256="sha256:" + "a" * 64,
            cache=cache,
        )
        evidence = candidates[0]["provider_physical_evidence"]
        self.assertEqual(evidence["page_count"], 211)
        self.assertEqual(evidence["dimensions"]["thickness"], "1.8 cm")
        self.assertEqual(evidence["print_type"], "BOOK")
        self.assertEqual(evidence["scope"], "raw_google_books_provider_volume_metadata_only")
        self.assertFalse(evidence["clark_copy_measurement"])
        self.assertFalse(evidence["pixel_inference_used"])
        self.assertIn("not Clark's physical copy", evidence["caveat"])

    def test_discovery_is_bounded_resumable_and_writes_no_response_body(self) -> None:
        state = empty_state(self.plan, created_at=NOW)
        state_path = self.state_path
        first_client = FakeClient([self.response()])
        report = run_discovery(
            self.plan,
            state,
            state_path,
            first_client,
            limit=1,
            min_interval=1.0,
            now_fn=lambda: NOW,
            monotonic_fn=lambda: 0.0,
            sleep_fn=lambda _seconds: None,
        )
        self.assertEqual(report["attempted"], 1)
        self.assertEqual(report["remaining"], 1)
        self.assertEqual(first_client.calls, ["9781847490063"])
        persisted = json.loads(state_path.read_text())
        self.assertNotIn("response_body", json.dumps(persisted))

        second_client = FakeClient([self.response("9780140135152", "VOL2")])
        report = run_discovery(
            self.plan,
            persisted,
            state_path,
            second_client,
            limit=1,
            min_interval=1.0,
            now_fn=lambda: NOW,
            monotonic_fn=lambda: 0.0,
            sleep_fn=lambda _seconds: None,
        )
        self.assertEqual(report["remaining"], 0)
        self.assertEqual(second_client.calls, ["9780140135152"])

    def test_missing_freshness_retains_no_api_content_and_does_not_hammer(self) -> None:
        state = empty_state(self.plan, created_at=NOW)
        state_path = self.state_path
        blocked_response = ApiResponse(
            payload=self.response().payload,
            headers={"Cache-Control": "private, max-age=0, must-revalidate"},
            response_sha256="sha256:" + "a" * 64,
            received_bytes=100,
        )
        client = FakeClient([blocked_response])
        report = run_discovery(
            self.plan,
            state,
            state_path,
            client,
            limit=1,
            min_interval=1.0,
            now_fn=lambda: NOW,
            monotonic_fn=lambda: 0.0,
            sleep_fn=lambda _seconds: None,
        )
        self.assertEqual(report["retention_blocked"], 1)
        entry = next(iter(state["entries"].values()))
        self.assertFalse(entry["api_content_retained"])
        self.assertNotIn("candidates", entry)
        self.assertNotIn("response_sha256", entry)
        self.assertEqual(len(pending_queries(self.plan, state)), 1)
        self.assertEqual(len(pending_queries(self.plan, state, retry_blocked=True)), 2)

    def test_transient_api_error_stops_batch_and_remains_retryable(self) -> None:
        state = empty_state(self.plan, created_at=NOW)
        state_path = self.state_path
        client = FakeClient([ApiError("rate limited", status=429, transient=True)])
        report = run_discovery(
            self.plan,
            state,
            state_path,
            client,
            limit=2,
            min_interval=1.0,
            now_fn=lambda: NOW,
            monotonic_fn=lambda: 0.0,
            sleep_fn=lambda _seconds: None,
        )
        self.assertEqual(report["attempted"], 1)
        self.assertTrue(report["stopped_early"])
        self.assertEqual(len(pending_queries(self.plan, state)), 2)
        entry = next(iter(state["entries"].values()))
        self.assertFalse(entry["api_content_retained"])

    def test_queue_is_private_remote_only_attributed_and_never_public_eligible(self) -> None:
        state = empty_state(self.plan, created_at=NOW)
        state_path = self.state_path
        run_discovery(
            self.plan,
            state,
            state_path,
            FakeClient([self.response()]),
            limit=1,
            min_interval=1.0,
            now_fn=lambda: NOW,
            monotonic_fn=lambda: 0.0,
            sleep_fn=lambda _seconds: None,
        )
        queue = build_review_queue(self.plan, state, generated_at=NOW)
        self.assertEqual(queue["summary"]["candidate_references"], 1)
        self.assertEqual(queue["summary"]["public_eligible_candidates"], 0)
        self.assertFalse(queue["summary"]["image_binaries_included"])
        self.assertEqual(queue["valid_until"], RETAIN_UNTIL)
        self.assertEqual(queue["attribution"]["text"], "Powered by Google")
        self.assertFalse(queue["review_adapter"]["publication_adapter_available"])
        candidate = queue["items"]["alma-a"]["candidates"][0]
        self.assertTrue(candidate["rights"]["remote_reference_only"])
        self.assertFalse(candidate["rights"]["binary_download_or_cache_allowed"])
        self.assertFalse(candidate["public_eligible"])

    def test_queue_fails_closed_on_candidate_tampering(self) -> None:
        state = empty_state(self.plan, created_at=NOW)
        state_path = self.state_path
        run_discovery(
            self.plan,
            state,
            state_path,
            FakeClient([self.response()]),
            limit=1,
            min_interval=1.0,
            now_fn=lambda: NOW,
            monotonic_fn=lambda: 0.0,
            sleep_fn=lambda _seconds: None,
        )
        candidate = next(iter(state["entries"].values()))["candidates"][0]
        candidate["rights"]["binary_download_or_cache_allowed"] = True
        with self.assertRaisesRegex(SourceError, "unsafe rights"):
            build_review_queue(self.plan, state, generated_at=NOW)

    def test_expired_candidates_are_removed_and_become_retryable(self) -> None:
        state = empty_state(self.plan, created_at=NOW)
        state_path = self.state_path
        run_discovery(
            self.plan,
            state,
            state_path,
            FakeClient([self.response()]),
            limit=1,
            min_interval=1.0,
            now_fn=lambda: NOW,
            monotonic_fn=lambda: 0.0,
            sleep_fn=lambda _seconds: None,
        )
        self.assertEqual(prune_expired(state, now=RETAIN_UNTIL), 1)
        entry = next(iter(state["entries"].values()))
        self.assertEqual(entry["status"], "expired")
        self.assertNotIn("candidates", entry)
        self.assertEqual(len(pending_queries(self.plan, state)), 2)

    def test_state_from_another_plan_is_rejected(self) -> None:
        state = empty_state(self.plan, created_at=NOW)
        state["plan_fingerprint"] = "sha256:" + "f" * 64
        with self.assertRaisesRegex(SourceError, "stale"):
            validate_state(state, self.plan)


if __name__ == "__main__":
    unittest.main(verbosity=2)
