#!/usr/bin/env python3
"""Focused tests for the aggregate Jefferson package owner."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess
import tempfile
import unittest

import build_jefferson_browser_package as catalog_builder
import build_jefferson_collection_package as builder


def catalog_manifest() -> dict:
    return catalog_builder._manifest_payload(
        {"record_count": 2748},
        historical_entry_count=4931,
        established_sowerby_links=17,
    )


def historical_validation(count: int = 4928) -> dict:
    return {
        "schema": "shelfsignals-jefferson-historical-validation@1",
        "counts": {
            "source_backed_entries": count,
            "source_backed_titles": 1351,
            "titles_not_established": 3577,
            "page_resolved_identifiers": 4675,
            "aggregate_spine_identifiers": 253,
        },
    }


def hierarchy_fixture() -> tuple[dict, dict]:
    artifact_rows = []
    hierarchy_rows = []
    for number in range(1, 45):
        faculty = "History" if number <= 15 else "Philosophy" if number <= 29 else "Fine Arts"
        artifact_rows.append({
            "chapter_number": number,
            "chapter_roman": str(number),
            "faculty": faculty,
            "label": f"Chapter {number}",
            "printed_page": number,
            "start_identifier": number,
            "end_identifier": number,
        })
        hierarchy_rows.append({
            "chapter_number": number,
            "chapter_roman": str(number),
            "faculty": faculty,
            "heading": f"Chapter {number}",
            "printed_page": number,
        })
    artifact = {
        "schema": "shelfsignals-loc-sowerby-chapter-ranges@1",
        "chapters": artifact_rows,
    }
    hierarchy = {
        "schema": "shelfsignals-jefferson-hierarchy@1",
        "base_integer_identifier_count": 4931,
        "faculties": [
            {"name": "History", "chapter_start": 1, "chapter_end": 15},
            {"name": "Philosophy", "chapter_start": 16, "chapter_end": 29},
            {"name": "Fine Arts", "chapter_start": 30, "chapter_end": 44},
        ],
        "chapters": hierarchy_rows,
    }
    return hierarchy, artifact


class CombinedJeffersonPackageTests(unittest.TestCase):
    def test_manifest_declares_disjoint_catalog_and_historical_corpora(self):
        manifest = builder.build_combined_manifest(catalog_manifest(), historical_validation())
        self.assertEqual(manifest["schema"], "shelfsignals-collection-manifest@2")
        self.assertEqual([row["id"] for row in manifest["corpora"]], ["catalog", "historical"])
        catalog, historical = manifest["corpora"]
        self.assertEqual(catalog["coverage"]["historical_entry_count"], 4928)
        self.assertEqual(catalog["coverage"]["historical_position_count"], 4931)
        self.assertEqual(historical["coverage"]["record_count"], 4928)
        self.assertEqual(historical["default_order"], "sowerby")
        self.assertEqual(historical["facets"], ["evidence_status"])
        self.assertTrue(all(path.startswith("historical/") for path in historical["data"].values()))
        self.assertFalse(set(catalog["data"].values()) & set(historical["data"].values()))
        self.assertIn("4,928-entry historical Sowerby layer", manifest["copy"]["coverage_statement"])
        self.assertIn("must not be added as unique books", manifest["copy"]["coverage_statement"])
        self.assertIn("1,351 entries have conservative scan-OCR display titles", historical["copy"]["coverage_statement"])
        self.assertIn("4,675 entries resolve to exact LOC PDF pages", historical["copy"]["coverage_statement"])

    def test_manifest_passes_the_runtime_parser(self):
        manifest = builder.build_combined_manifest(catalog_manifest(), historical_validation())
        script = """
          import { parseCollectionManifest } from './docs/js/collections.js';
          let body = '';
          for await (const chunk of process.stdin) body += chunk;
          const parsed = parseCollectionManifest(JSON.parse(body), { expectedId: 'jefferson' });
          if (parsed.rejected) { console.error(JSON.stringify(parsed.errors)); process.exit(1); }
        """
        result = subprocess.run(
            ["node", "--input-type=module", "-e", script],
            input=json.dumps(manifest),
            text=True,
            cwd=builder.REPOSITORY_ROOT,
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 0, result.stderr)

    def test_wrong_historical_count_fails_closed(self):
        with self.assertRaisesRegex(builder.BuildError, "4,928"):
            builder.build_combined_manifest(catalog_manifest(), historical_validation(4931))

    def test_shared_hierarchy_must_match_loc_range_artifact(self):
        hierarchy, artifact = hierarchy_fixture()
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "ranges.json"
            path.write_text(json.dumps(artifact), encoding="utf-8")
            builder.validate_shared_hierarchy(json.dumps(hierarchy).encode(), path)
            hierarchy["chapters"][20]["faculty"] = "History"
            with self.assertRaisesRegex(builder.BuildError, "faculty"):
                builder.validate_shared_hierarchy(json.dumps(hierarchy).encode(), path)

    def test_writer_and_checker_own_both_namespaces(self):
        files = {
            "manifest.json": b"{}\n",
            "catalog-core.json": b"{}\n",
            "historical/catalog-core.json": b"{}\n",
        }
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "jefferson"
            builder.write_package(files, output)
            builder.check_package(files, output)
            (output / "historical/stray.json").write_text("{}\n", encoding="utf-8")
            with self.assertRaisesRegex(builder.BuildError, "unexpected: historical/stray.json"):
                builder.check_package(files, output)
            builder.write_package(files, output)
            self.assertFalse((output / "historical/stray.json").exists())


if __name__ == "__main__":
    unittest.main()
