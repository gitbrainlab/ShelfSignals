#!/usr/bin/env python3

from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import unittest


SCRIPT_DIR = Path(__file__).resolve().parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

import build_jefferson_insight_graph as builder


class JeffersonInsightGraphTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.core = builder.load_object(builder.DEFAULT_CORE, "historical core")
        cls.config = builder.load_object(builder.DEFAULT_CONFIG, "event config")

    def test_real_graph_is_deterministic_and_reconciles(self) -> None:
        first = builder.build_graph(self.core, self.config)
        second = builder.build_graph(self.core, self.config)
        self.assertEqual(builder.json_bytes(first), builder.json_bytes(second))
        self.assertEqual(first["coverage"]["historical_entries"], 4928)
        self.assertEqual(first["coverage"]["historical_chapters"], 44)
        self.assertEqual(first["coverage"]["events"], 9)
        self.assertEqual(first["coverage"]["direct_record_relations"], 5)
        self.assertEqual(first["coverage"]["chapter_event_edges"], sum(event["chapter_count"] for event in first["events"]))
        self.assertEqual(sum(row["record_count"] for row in first["chapter_clusters"]), 4928)
        self.assertTrue(all(
            relation["use_confidence_score"] is None
            for relation in first["record_relations"]
            if relation["event_use_status"] == "not_established"
        ))
        serialized = builder.json_bytes(first).decode("utf-8").lower()
        self.assertNotIn("monticello.org", serialized)
        self.assertNotIn("thomas jefferson foundation", serialized)

    def test_unestablished_use_cannot_receive_a_score(self) -> None:
        config = copy.deepcopy(self.config)
        relation = next(row for row in config["record_relations"] if row["event_use_status"] == "not_established")
        relation["use_confidence_score"] = 50
        with self.assertRaisesRegex(builder.BuildError, "cannot score unestablished use"):
            builder.build_graph(self.core, config)

    def test_sources_and_record_ids_fail_closed(self) -> None:
        unsafe = copy.deepcopy(self.config)
        unsafe["sources"][0]["url"] = "https://example.org/not-loc"
        with self.assertRaisesRegex(builder.BuildError, "loc.gov"):
            builder.build_graph(self.core, unsafe)

        unknown = copy.deepcopy(self.config)
        unknown["record_relations"][0]["record_id"] = "jefferson-sowerby-9999"
        with self.assertRaisesRegex(builder.BuildError, "unknown or duplicated identity"):
            builder.build_graph(self.core, unknown)

        cross_cluster = copy.deepcopy(self.config)
        cross_cluster["record_relations"][0]["record_id"] = "jefferson-sowerby-1"
        with self.assertRaisesRegex(builder.BuildError, "outside its event chapter clusters"):
            builder.build_graph(self.core, cross_cluster)


if __name__ == "__main__":
    unittest.main()
