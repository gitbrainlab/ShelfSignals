#!/usr/bin/env python3
"""Deterministic, no-network tests for cover batch operations."""

from __future__ import annotations

import json
import tempfile
import unittest
from copy import deepcopy
from pathlib import Path

from cover_source_pipeline import (
    PROBE_SCHEMA,
    PipelineError,
    build_batch_plan,
    build_batch_review_queue,
    build_public_manifest,
    build_review_queue,
    empty_probe_cache,
    find_batch,
    load_probe_cache,
    pipeline_status,
    probe_candidates,
    review_template,
    validate_batch_plan,
    write_batch_review_queues,
    write_json,
)


class FakeProbeClient:
    def __init__(self) -> None:
        self.calls: list[str] = []

    def probe(self, candidate, checked_at):
        self.calls.append(candidate["candidate_key"])
        return {
            "candidate_fingerprint": candidate["candidate_fingerprint"],
            "status": "positive",
            "checked_at": checked_at,
            "bounded_probe": True,
            "width": 300,
            "height": 400,
            "aspect_ratio": 0.75,
        }


class CoverBatchOperationsTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.root = Path(self.temporary.name)
        self.catalog_path = self.root / "catalog.json"
        self.editions_path = self.root / "editions.json"
        records = [
            {"id": "alma-a", "title": "Alpha", "isbns": ["9780374226268"]},
            {"id": "alma-b", "title": "Beta", "isbns": ["9780520270947"]},
            {"id": "alma-c", "title": "Gamma", "isbns": ["9781847490063"]},
        ]
        editions = {
            "schema": "shelfsignals-edition-enrichment@1",
            "source": {
                "provider_snapshot": "2026-06-30",
                "provider_dump_checksum": "md5:" + "d" * 32,
            },
            "items": {
                "alma-a": {"candidates": [{
                    "source_id": "OL100M",
                    "match": {"method": "isbn_exact", "identifiers": [{"type": "isbn", "value": "9780374226268"}]},
                    "edition": {"cover_ids": [100, 101]},
                }]},
                "alma-b": {"candidates": [{
                    "source_id": "OL200M",
                    "match": {"method": "isbn_exact", "identifiers": [{"type": "isbn", "value": "9780520270947"}]},
                    "edition": {"cover_ids": [200]},
                }]},
                "alma-c": {"candidates": [{
                    "source_id": "OL300M",
                    "match": {"method": "isbn_exact", "identifiers": [{"type": "isbn", "value": "9781847490063"}]},
                    "edition": {"cover_ids": [300, 301, 302]},
                }]},
            },
        }
        self.catalog_path.write_text(json.dumps(records), encoding="utf-8")
        self.editions_path.write_text(json.dumps(editions), encoding="utf-8")
        self.queue = build_review_queue(
            records,
            editions,
            self.catalog_path,
            self.editions_path,
            generated_at="2026-07-14T00:00:00Z",
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_plan_is_deterministic_complete_and_record_atomic(self) -> None:
        first = build_batch_plan(self.queue, 2, generated_at="2026-07-14T00:00:00Z")
        second = build_batch_plan(self.queue, 2, generated_at="2026-07-14T00:00:00Z")
        self.assertEqual(first, second)
        self.assertEqual(first["summary"]["candidate_count"], 6)
        self.assertEqual(first["summary"]["batch_count"], 3)
        self.assertEqual(first["summary"]["batches_over_target"], 1)
        self.assertEqual([batch["record_count"] for batch in first["batches"]], [1, 1, 1])
        validate_batch_plan(first, self.queue)

    def test_plan_rejects_tampering_and_stale_queue(self) -> None:
        plan = build_batch_plan(self.queue, 2, generated_at="2026-07-14T00:00:00Z")
        tampered = deepcopy(plan)
        tampered["batches"][0]["candidates"][0]["candidate_fingerprint"] = "sha256:" + "f" * 64
        with self.assertRaisesRegex(PipelineError, "stale fingerprint"):
            validate_batch_plan(tampered, self.queue)

        changed_queue = deepcopy(self.queue)
        changed_queue["items"]["alma-a"]["candidates"] = changed_queue["items"]["alma-a"]["candidates"][:1]
        with self.assertRaisesRegex(PipelineError, "stale for the current candidate set"):
            validate_batch_plan(plan, changed_queue)

    def test_browser_queue_shards_keep_evidence_and_never_publish(self) -> None:
        plan = build_batch_plan(self.queue, 2, generated_at="2026-07-14T00:00:00Z")
        batch = find_batch(plan, "cover-0001")
        shard = build_batch_review_queue(self.queue, plan, batch)
        self.assertEqual(shard["inputs"], self.queue["inputs"])
        self.assertEqual(shard["summary"]["catalog_records"], 1)
        self.assertEqual(shard["summary"]["candidate_references"], 2)
        self.assertEqual(shard["batch"]["publication_effect"], "none")
        self.assertEqual(set(shard["items"]), {"alma-a"})

        output_dir = self.root / "batches"
        paths = write_batch_review_queues(self.queue, plan, output_dir)
        self.assertEqual(len(paths), 3)
        self.assertTrue(all(path.exists() for path in paths))
        with self.assertRaisesRegex(PipelineError, "already exists"):
            write_batch_review_queues(self.queue, plan, output_dir)

    def test_probe_batch_resumes_and_never_touches_other_batches(self) -> None:
        plan = build_batch_plan(self.queue, 2, generated_at="2026-07-14T00:00:00Z")
        batch = find_batch(plan, "cover-0001")
        keys = {entry["candidate_key"] for entry in batch["candidates"]}
        cache = empty_probe_cache(self.queue)
        cache_path = self.root / "probes.json"
        client = FakeProbeClient()

        first = probe_candidates(self.queue, cache, cache_path, client, 1, include_keys=keys)
        self.assertEqual(first["attempted"], 1)
        self.assertEqual(first["remaining"], 1)
        second = probe_candidates(self.queue, cache, cache_path, client, 1, include_keys=keys)
        self.assertEqual(second["attempted"], 1)
        self.assertEqual(second["remaining"], 0)
        self.assertEqual(set(client.calls), keys)
        self.assertEqual(set(cache["entries"]), keys)

    def test_probe_cache_is_bound_to_queue_inputs(self) -> None:
        payload = empty_probe_cache(self.queue)
        payload["queue_inputs"] = {"catalog_sha256": "sha256:" + "f" * 64}
        cache_path = self.root / "probes.json"
        write_json(cache_path, payload)
        with self.assertRaisesRegex(PipelineError, "different queue_inputs"):
            load_probe_cache(cache_path, self.queue)

    def test_status_reports_progress_and_gate_readiness_without_writes(self) -> None:
        candidate = self.queue["items"]["alma-a"]["candidates"][0]
        key = candidate["candidate_key"]
        probes = {
            "schema": PROBE_SCHEMA,
            "queue_inputs": self.queue["inputs"],
            "entries": {key: {
                "candidate_fingerprint": candidate["candidate_fingerprint"],
                "status": "positive",
                "checked_at": "2026-07-14T00:00:00Z",
                "bounded_probe": True,
                "width": 300,
                "height": 400,
                "aspect_ratio": 0.75,
            }},
        }
        reviews = review_template(self.queue)
        reviews["decisions"][key] = {
            "candidate_fingerprint": candidate["candidate_fingerprint"],
            "decision": "approve",
            "reviewer": "Test reviewer",
            "reviewed_at": "2026-07-14T00:00:00Z",
            "exact_edition_confirmed": True,
            "visual_check": True,
            "rights_scope": "remote_reference_only",
            "evidence_note": "Exact ISBN and visible edition evidence were compared.",
        }
        report = pipeline_status(self.queue, probes, reviews, {key})
        self.assertEqual(report["summary"]["publication_eligible_records"], 1)
        self.assertEqual(report["summary"]["probe_completion_percent"], 100.0)
        self.assertEqual(report["summary"]["review_completion_percent"], 100.0)
        self.assertTrue(report["policy"]["report_publishes_nothing"])
        self.assertTrue(report["policy"]["image_binaries_read_or_written"] is False)

    def test_publisher_rejects_state_from_another_queue(self) -> None:
        probes = empty_probe_cache(self.queue)
        reviews = review_template(self.queue)
        reviews["queue_inputs"] = {"catalog_sha256": "sha256:" + "f" * 64}
        with self.assertRaisesRegex(PipelineError, "review ledger queue_inputs"):
            build_public_manifest(self.queue, probes, reviews)


if __name__ == "__main__":
    unittest.main(verbosity=2)
