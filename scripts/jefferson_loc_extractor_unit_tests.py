#!/usr/bin/env python3
"""No-network contract tests for the Jefferson/LOC research extractor."""

from __future__ import annotations

import json
import http.client
import hashlib
import sqlite3
import tempfile
import unittest
import urllib.error
import urllib.parse
from collections import Counter
from unittest import mock
from pathlib import Path

from jefferson_loc_extractor import (
    CATALOG_EXACT_HEADING,
    CATALOG_SORTED_QUERY,
    CachedFetcher,
    CatalogGuestSession,
    ExtractionError,
    build_crosswalk,
    build_loc_sowerby_spine,
    build_outputs,
    catalog_search_url,
    folio_source_to_marc,
    harvest_digital,
    load_digital_items,
    load_exact_catalog_instances,
    main,
    normalize_exact_instance,
    normalize_marc_record,
    parse_loc_sowerby_index,
    parse_loc_sowerby_toc,
    parse_sowerby_page,
    parse_sru_page,
    public_catalog_instance_projection,
    public_marc_projection,
    strip_staff_only,
    verify_cache_sidecars,
    write_sqlite,
)


MARC_PAGE = b'''<?xml version="1.0"?>
<zs:searchRetrieveResponse xmlns:zs="http://www.loc.gov/zing/srw/">
  <zs:version>1.1</zs:version>
  <zs:numberOfRecords>1</zs:numberOfRecords>
  <zs:records>
    <zs:record>
      <zs:recordSchema>marcxml</zs:recordSchema>
      <zs:recordPacking>xml</zs:recordPacking>
      <zs:recordData>
        <record xmlns="http://www.loc.gov/MARC21/slim">
          <leader>01953cam a2200409 a 4500</leader>
          <controlfield tag="001">7311922</controlfield>
          <controlfield tag="005">20250608010920.6</controlfield>
          <controlfield tag="008">830505s1801    pau           000 0 eng  </controlfield>
          <datafield tag="010" ind1=" " ind2=" "><subfield code="a">   18020059 </subfield></datafield>
          <datafield tag="050" ind1="0" ind2="0"><subfield code="a">JA36</subfield><subfield code="b">.P8b vol. 101</subfield></datafield>
          <datafield tag="100" ind1="1" ind2=" "><subfield code="a">Jefferson, Thomas,</subfield><subfield code="d">1743-1826.</subfield></datafield>
          <datafield tag="245" ind1="1" ind2="0"><subfield code="a">Speech of Thomas Jefferson :</subfield><subfield code="b">delivered at his instalment.</subfield></datafield>
          <datafield tag="260" ind1=" " ind2=" "><subfield code="a">Philadelphia :</subfield><subfield code="b">Cochran &amp; M'Laughlin,</subfield><subfield code="c">1801.</subfield></datafield>
          <datafield tag="500" ind1=" " ind2=" "><subfield code="a">LC copy forms part of the Jefferson Exhibit Collection.</subfield><subfield code="5">DLC</subfield></datafield>
          <datafield tag="510" ind1="4" ind2=" "><subfield code="a">Sowerby, E.M. Catalogue of the Library of Thomas Jefferson,</subfield><subfield code="c">3259</subfield></datafield>
          <datafield tag="561" ind1=" " ind2=" "><subfield code="a">LC copy is Thomas Jefferson's.</subfield><subfield code="5">DLC</subfield></datafield>
          <datafield tag="650" ind1=" " ind2="0"><subfield code="a">Politics.</subfield></datafield>
          <datafield tag="700" ind1="1" ind2=" "><subfield code="a">Jefferson, Thomas,</subfield><subfield code="d">1743-1826,</subfield><subfield code="e">former owner.</subfield><subfield code="5">DLC</subfield></datafield>
          <datafield tag="710" ind1="2" ind2=" "><subfield code="a">Thomas Jefferson Library Collection (Library of Congress)</subfield></datafield>
          <datafield tag="952" ind1=" " ind2=" "><subfield code="a">Rare Book and Special Collections Division</subfield><subfield code="b">DLC</subfield></datafield>
        </record>
      </zs:recordData>
      <zs:recordPosition>1</zs:recordPosition>
    </zs:record>
  </zs:records>
</zs:searchRetrieveResponse>'''


SOWERBY_PAGE = b'''<!doctype html><html><body>
<div class="portal_body">
  <div class="ChapterTitle"><h2>Chapter XXIV</h2></div>
  <div class="head2"><strong>Politics</strong></div>
  <div class="CatalogEntry" id="jlp-test">
    <div class="SeqNo">J.7</div>
    <div class="ShortTitle"><em>A political speech</em>, <span class="size">8vo.</span> <span class="pubPlace">Philadelphia</span> <span class="pubDate">1801</span>.</div>
    <div class="Author">JEFFERSON, Thomas.</div>
    <div class="LongTitle">Speech of Thomas Jefferson.</div>
    <div class="CallNo">JA36 .P8b</div>
    <div class="editionStmt"><span class="edition">First</span> edition.</div>
    <div class="listBibl"><div class="bibl">Example bibliography.</div></div>
    <div class="note">Initialled by Jefferson.</div>
    <div class="BIDNo">[3259]</div>
  </div>
</div>
<div class="transcript_pagenav"><a href="III_2.html">next</a></div>
</body></html>'''


FOLIO_INSTANCE = {
    "id": "9f051b11-82b3-55bb-bcc2-caa75c10ac2b",
    "hrid": "7311922",
    "title": "Speech of Thomas Jefferson",
    "indexTitle": "Speech of Thomas Jefferson",
    "contributors": [{"name": CATALOG_EXACT_HEADING, "primary": False}],
    "identifiers": [{"value": "18020059", "identifierTypeId": "lccn-type"}],
    "languages": ["eng"],
    "subjects": ["Politics"],
    "notes": [
        {"note": "Sowerby, Catalogue of the Library of Thomas Jefferson, 3259", "staffOnly": False},
        {"note": "internal workflow note", "staffOnly": True},
    ],
    "administrativeNotes": ["internal migration note"],
    "unexpectedInternalField": "must not publish",
    "items": [{
        "id": "item-1",
        "hrid": "it-1",
        "effectiveLocationId": "location-1",
        "status": {"name": "Available"},
        "materialType": {"name": "Book"},
        "effectiveCallNumberComponents": {"callNumber": "JA36 .P8b", "suffix": "Jefferson Coll"},
        "effectiveShelvingOrder": "JA36 .P8b Jefferson Coll",
        "notes": [{"note": "hidden item note", "staffOnly": True}],
        "administrativeNotes": ["internal item workflow"],
        "barcode": "PRIVATE-BARCODE",
        "circulationNotes": [{"note": "internal circulation note"}],
        "tags": {"tagList": ["internal-tag"]},
        "unexpectedItemField": "must not publish",
    }],
    "holdings": [{
        "id": "holding-1",
        "hrid": "ho-1",
        "permanentLocationId": "location-1",
        "notes": [{"note": "hidden holdings MARC", "staffOnly": True}],
        "administrativeNotes": ["internal holdings workflow"],
        "unexpectedHoldingField": "must not publish",
    }],
    "staffSuppress": False,
    "discoverySuppress": False,
    "metadata": {"createdByUserId": "internal-user", "createdDate": "2025-06-06T00:00:00Z"},
}


def write_cache_sidecar(path: Path, request_url: str = "https://example.test/source") -> None:
    raw = path.read_bytes()
    path.with_name(path.name + ".meta.json").write_text(json.dumps({
        "request_url": request_url,
        "final_url": request_url,
        "fetched_at": "2026-08-01T12:00:00Z",
        "content_type": "application/octet-stream",
        "bytes": len(raw),
        "sha256": "sha256:" + hashlib.sha256(raw).hexdigest(),
    }), encoding="utf-8")


class JeffersonLocExtractorTests(unittest.TestCase):
    def test_catalog_query_has_explicit_stable_sort_for_offset_pagination(self) -> None:
        query = urllib.parse.parse_qs(urllib.parse.urlparse(catalog_search_url(25)).query)
        self.assertEqual(query["query"], [CATALOG_SORTED_QUERY])
        self.assertIn("sortby title/sort.ascending", query["query"][0])
        self.assertEqual(query["offset"], ["25"])

    def test_truncated_response_retries_without_committing_partial_cache(self) -> None:
        class Response:
            status = 200
            headers = {"Content-Type": "application/json"}

            def __init__(self, value=None, error=None):
                self.value = value
                self.error = error

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def geturl(self):
                return "https://example.test/source"

            def read(self):
                if self.error:
                    raise self.error
                return self.value

        with tempfile.TemporaryDirectory() as temporary:
            cache_path = Path(temporary) / "source.json"

            class Opener:
                calls = 0

                def open(self, _request, timeout=None):
                    self.calls += 1
                    if self.calls == 1:
                        return Response(error=http.client.IncompleteRead(b"partial", 10))
                    self_test.assertFalse(cache_path.exists(), "partial response must never reach the cache")
                    return Response(value=b'{"complete":true}')

            self_test = self
            opener = Opener()
            fetcher = CachedFetcher(min_interval=0, retries=2, sleep_fn=lambda _seconds: None)
            raw = fetcher.fetch("https://example.test/source", cache_path, opener=opener)
            self.assertEqual(raw, b'{"complete":true}')
            self.assertEqual(cache_path.read_bytes(), raw)
            self.assertEqual(opener.calls, 2)

    def test_http_520_is_retried_as_transient_server_failure(self) -> None:
        class Response:
            status = 200
            headers = {"Content-Type": "application/json"}

            def __enter__(self):
                return self

            def __exit__(self, *_args):
                return False

            def geturl(self):
                return "https://example.test/source"

            def read(self):
                return b"{}"

        class Opener:
            calls = 0

            def open(self, request, timeout=None):
                self.calls += 1
                if self.calls == 1:
                    raise urllib.error.HTTPError(request.full_url, 520, "Origin Error", {}, None)
                return Response()

        with tempfile.TemporaryDirectory() as temporary:
            opener = Opener()
            fetcher = CachedFetcher(min_interval=0, retries=2, sleep_fn=lambda _seconds: None)
            raw = fetcher.fetch("https://example.test/source", Path(temporary) / "source.json", opener=opener)
            self.assertEqual(raw, b"{}")
            self.assertEqual(opener.calls, 2)

    def test_cache_hit_rejects_body_that_no_longer_matches_retrieval_sidecar(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            cache_path = Path(temporary) / "source.json"
            cache_path.write_text('{"version":1}', encoding="utf-8")
            write_cache_sidecar(cache_path)
            cache_path.write_text('{"version":2}', encoding="utf-8")
            fetcher = CachedFetcher(min_interval=0)
            with self.assertRaisesRegex(ExtractionError, "does not match its sidecar"):
                fetcher.fetch("https://example.test/source", cache_path)

    def test_build_rejects_valid_json_tampered_after_retrieval(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / "cache" / "loc_sowerby" / "item.json"
            source.parent.mkdir(parents=True)
            source.write_text('{"item":{"id":"original"}}', encoding="utf-8")
            write_cache_sidecar(source)
            source.write_text('{"item":{"id":"tampered"}}', encoding="utf-8")
            provenance = verify_cache_sidecars(root)
            self.assertTrue(provenance["mismatched_or_invalid_sidecars"])
            with self.assertRaisesRegex(ExtractionError, "do not match retrieval sidecars"):
                build_outputs(root, generated_at="2026-08-01T12:00:00Z")
            self.assertFalse((root / "data" / "manifest.json").exists())

    def test_guest_authentication_closes_http_error_response(self) -> None:
        error = urllib.error.HTTPError(
            "https://search.catalog.loc.gov/api/opac-auth/guest-token",
            503,
            "Unavailable",
            {},
            None,
        )

        class Opener:
            def open(self, _request, timeout=None):
                raise error

        session = CatalogGuestSession(CachedFetcher(min_interval=0))
        session.opener = Opener()
        with self.assertRaisesRegex(ExtractionError, "guest authentication failed"):
            session.authenticate()
        self.assertTrue(error.closed)

    def test_monticello_transcript_requires_explicit_terms_acknowledgement_before_network(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(ExtractionError, "copyrighted|permission"):
                main(["sowerby", "--root", temporary])
            self.assertFalse((Path(temporary) / "cache" / "sowerby_transcription").exists())

    def test_marc_parser_preserves_ordered_fields_and_local_metadata(self) -> None:
        page = parse_sru_page(MARC_PAGE)
        self.assertEqual(page["number_of_records"], 1)
        self.assertEqual(page["records"][0]["record_position"], 1)
        marc = page["records"][0]["marc"]
        self.assertEqual([field["tag"] for field in marc["control_fields"]], ["001", "005", "008"])
        self.assertEqual([field["tag"] for field in marc["data_fields"]][-2:], ["710", "952"])
        self.assertEqual(marc["data_fields"][1]["subfields"], [
            {"code": "a", "value": "JA36"},
            {"code": "b", "value": ".P8b vol. 101"},
        ])

    def test_normalization_is_evidence_preserving_and_does_not_invent_copy_status(self) -> None:
        marc = public_marc_projection(parse_sru_page(MARC_PAGE)["records"][0]["marc"])
        normalized = normalize_marc_record(marc)
        self.assertEqual(normalized["title"], "Speech of Thomas Jefferson : delivered at his instalment.")
        self.assertEqual(normalized["lccn"], "18020059")
        self.assertEqual(normalized["languages"], ["eng"])
        self.assertEqual(normalized["year"], "1801")
        self.assertEqual(normalized["publication_statements"], ["Philadelphia : Cochran & M'Laughlin, 1801."])
        self.assertEqual(normalized["sowerby_numbers"], [3259])
        self.assertEqual(
            normalized["relationship_to_jefferson"],
            "catalog_asserts_jefferson_former_owner_access_point",
        )
        self.assertNotIn("local_fields", normalized)
        self.assertNotIn("replacement", json.dumps(normalized).lower())

    def test_public_marc_projection_removes_local_and_private_fields(self) -> None:
        marc = parse_sru_page(MARC_PAGE)["records"][0]["marc"]
        marc["data_fields"].extend([
            {"tag": "561", "ind1": "0", "ind2": " ", "subfields": [
                {"code": "a", "value": "private provenance"},
            ]},
            {"tag": "245", "ind1": "1", "ind2": "0", "subfields": [
                {"code": "a", "value": "Public title"},
                {"code": "9", "value": "private local workflow value"},
            ]},
            {"tag": "999", "ind1": " ", "ind2": " ", "subfields": [
                {"code": "i", "value": "internal-instance-uuid"},
            ]},
        ])
        stats = Counter()
        projection = public_marc_projection(marc, stats)
        self.assertNotIn("005", [field["tag"] for field in projection["control_fields"]])
        self.assertNotIn("952", [field["tag"] for field in projection["data_fields"]])
        self.assertNotIn("999", [field["tag"] for field in projection["data_fields"]])
        self.assertNotIn("private provenance", json.dumps(projection))
        self.assertNotIn("private local workflow value", json.dumps(projection))
        self.assertEqual(stats["marc_local_9xx_fields_removed"], 2)
        self.assertEqual(stats["marc_private_note_fields_removed"], 1)
        self.assertEqual(stats["marc_local_subfield_9_values_removed"], 1)

    def test_sowerby_suffixes_and_ranges_are_not_collapsed_to_base_entry_links(self) -> None:
        marc = {
            "leader": "",
            "control_fields": [],
            "data_fields": [
                {"tag": "510", "ind1": "4", "ind2": " ", "subfields": [
                    {"code": "a", "value": "Sowerby"}, {"code": "c", "value": "3168a"},
                ]},
                {"tag": "510", "ind1": "4", "ind2": " ", "subfields": [
                    {"code": "a", "value": "Sowerby"}, {"code": "c", "value": "3370-3383"},
                ]},
            ],
        }
        normalized = normalize_marc_record(marc)
        self.assertEqual(normalized["sowerby_numbers"], [])
        self.assertEqual(normalized["sowerby_references"][0]["identifiers"], ["3168a"])
        self.assertEqual(normalized["sowerby_references"][1]["identifiers"], ["3370", "3383"])

    def test_sowerby_parser_keeps_source_layer_and_nested_transcription_fields(self) -> None:
        page = parse_sowerby_page(
            SOWERBY_PAGE,
            volume="III",
            page=1,
            source_url="https://tjlibraries.monticello.org/transcripts/sowerby/III_1.html",
        )
        self.assertEqual(page["chapter_number"], 24)
        self.assertEqual(page["chapter_heading"], "Politics")
        self.assertEqual(page["linked_pages"], [("III", 2)])
        entry = page["entries"][0]
        self.assertEqual(entry["sowerby_number"], 3259)
        self.assertEqual(entry["sequence_marker"], "J")
        self.assertEqual(entry["publication_places"], ["Philadelphia"])
        self.assertEqual(entry["source"]["authority"], "Thomas Jefferson Foundation")

    def test_crosswalk_uses_explicit_marc_510_and_lccn_only(self) -> None:
        marc = parse_sru_page(MARC_PAGE)["records"][0]["marc"]
        projection = public_marc_projection(marc)
        record = {
            "id": "loc:catalog:7311922",
            "source_marc_projection": projection,
            "normalized": normalize_marc_record(projection),
        }
        entry = parse_sowerby_page(SOWERBY_PAGE, volume="III", page=1, source_url="https://example.test/III_1.html")["entries"][0]
        digital = {
            "id": "loc:digital:18020059",
            "search_result": {"number_lccn": ["18020059"]},
        }
        links, stats = build_crosswalk([record], [entry], [digital])
        self.assertEqual(links[0]["catalog_entity_ids"], ["loc:catalog:7311922"])
        self.assertEqual(links[0]["digital_item_ids"], ["loc:digital:18020059"])
        self.assertEqual(links[0]["catalog_digital_links"], [{
            "catalog_entity_id": "loc:catalog:7311922",
            "digital_item_id": "loc:digital:18020059",
            "match_basis": "normalized LCCN exact",
            "normalized_lccns": ["18020059"],
        }])
        self.assertEqual(links[0]["evidence"], ["explicit MARC 510 Sowerby citation"])
        self.assertEqual(stats["sowerby_references_with_one_catalog_candidate_in_bounded_sample"], 1)
        self.assertEqual(stats["catalog_entities_assessed_in_bounded_marc_sample"], 1)

    def test_crosswalk_negative_status_discloses_bounded_assessment_scope(self) -> None:
        records = [
            {"id": "loc:instance:assessed", "source_marc_projection": {}, "normalized": {"sowerby_numbers": [], "lccns": []}},
            {"id": "loc:instance:unassessed", "normalized": {"sowerby_numbers": [], "lccns": []}},
        ]
        links, stats = build_crosswalk(
            records,
            [{"id": "sowerby:1", "sowerby_number": 1}],
            [],
        )
        self.assertEqual(links[0]["catalog_assessment_status"], "not_established_in_bounded_marc_sample")
        self.assertEqual(links[0]["assessment_scope"]["evidence_eligible_catalog_entity_count"], 1)
        self.assertEqual(links[0]["assessment_scope"]["catalog_entities_not_assessed"], 1)
        self.assertIn("bounded evidence-eligible sample", links[0]["evidence"][0])
        self.assertEqual(stats["catalog_entities_not_assessed"], 1)

    def test_sqlite_crosswalk_does_not_invent_catalog_digital_pairs(self) -> None:
        crosswalk = [{
            "sowerby_reference_id": "sowerby:3259",
            "sowerby_base_integer": 3259,
            "catalog_entity_ids": ["loc:catalog:a", "loc:catalog:b"],
            "digital_item_ids": ["loc:digital:a"],
            "catalog_digital_links": [{
                "catalog_entity_id": "loc:catalog:a",
                "digital_item_id": "loc:digital:a",
                "match_basis": "normalized LCCN exact",
                "normalized_lccns": ["18020059"],
            }],
            "catalog_assessment_status": "multiple_candidates_in_bounded_marc_sample",
            "assessment_scope": {
                "method": "one plain base-integer identifier in source MARC 510 subfield c",
                "selected_catalog_entity_count": 2,
                "evidence_eligible_catalog_entity_count": 2,
                "catalog_entities_not_assessed": 0,
            },
            "evidence": ["explicit MARC 510 Sowerby citation"],
        }, {
            "sowerby_reference_id": "sowerby:3260",
            "sowerby_base_integer": 3260,
            "catalog_entity_ids": [],
            "digital_item_ids": [],
            "catalog_digital_links": [],
            "catalog_assessment_status": "not_established_in_bounded_marc_sample",
            "assessment_scope": {
                "method": "one plain base-integer identifier in source MARC 510 subfield c",
                "selected_catalog_entity_count": 2,
                "evidence_eligible_catalog_entity_count": 2,
                "catalog_entities_not_assessed": 0,
            },
            "evidence": ["not established by the bounded source-MARC sample"],
        }]
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "crosswalk.sqlite"
            write_sqlite(path, "2026-08-01T12:00:00Z", [], [], [], [], [], [], crosswalk)
            connection = sqlite3.connect(path)
            try:
                rows = connection.execute(
                    "SELECT catalog_entity_id, digital_item_id, catalog_assessment_status, assessment_scope_json "
                    "FROM crosswalk ORDER BY sowerby_base_integer, catalog_entity_id"
                ).fetchall()
                metadata = dict(connection.execute("SELECT key, value FROM metadata"))
            finally:
                connection.close()
        self.assertEqual([(row[0], row[1]) for row in rows], [
            ("loc:catalog:a", "loc:digital:a"),
            ("loc:catalog:b", None),
            (None, None),
        ])
        self.assertEqual(rows[0][2], "multiple_candidates_in_bounded_marc_sample")
        self.assertEqual(rows[1][2], "multiple_candidates_in_bounded_marc_sample")
        self.assertEqual(rows[2][2], "not_established_in_bounded_marc_sample")
        self.assertTrue(all(json.loads(row[3])["evidence_eligible_catalog_entity_count"] == 2 for row in rows))
        self.assertNotIn("sowerby_unit", metadata)
        self.assertIn("base-integer identifier", metadata["loc_sowerby_spine_unit"])
        self.assertEqual(json.loads(metadata["crosswalk_assessment_scope_json"])["selected_catalog_entity_count"], 2)

    def test_staff_only_catalog_nodes_and_internal_user_ids_are_not_republished(self) -> None:
        from collections import Counter
        stats = Counter()
        cleaned = strip_staff_only(FOLIO_INSTANCE, stats)
        serialized = json.dumps(cleaned)
        self.assertNotIn("internal workflow note", serialized)
        self.assertNotIn("hidden item note", serialized)
        self.assertNotIn("hidden holdings MARC", serialized)
        self.assertNotIn("internal-user", serialized)
        self.assertNotIn("PRIVATE-BARCODE", serialized)
        self.assertNotIn("internal migration note", serialized)
        self.assertNotIn("internal item workflow", serialized)
        self.assertNotIn("internal holdings workflow", serialized)
        self.assertNotIn("internal circulation note", serialized)
        self.assertNotIn("internal-tag", serialized)
        self.assertEqual(stats["staff_only_nodes_removed"], 3)
        self.assertEqual(stats["internal_user_identifiers_removed"], 1)
        self.assertEqual(stats["administrative_note_fields_removed"], 3)
        self.assertEqual(stats["item_barcode_fields_removed"], 1)
        self.assertEqual(stats["circulation_note_fields_removed"], 1)
        self.assertEqual(stats["internal_tag_fields_removed"], 1)
        projected = public_catalog_instance_projection(cleaned, stats)
        projected_text = json.dumps(projected)
        self.assertNotIn("unexpectedInternalField", projected_text)
        self.assertNotIn("unexpectedItemField", projected_text)
        self.assertNotIn("unexpectedHoldingField", projected_text)
        self.assertEqual(stats["unallowlisted_instance_fields_removed"], 2)
        self.assertEqual(stats["unallowlisted_holding_fields_removed"], 1)
        self.assertEqual(stats["unallowlisted_item_fields_removed"], 1)

    def test_exact_collection_or_exhibit_note_does_not_assert_jefferson_ownership(self) -> None:
        instance = {
            "id": "instance-a",
            "hrid": "a",
            "title": "Example",
            "contributors": [{"name": CATALOG_EXACT_HEADING}],
            "notes": [{
                "note": "LC copy forms part of the Jefferson Exhibit Collection.",
                "staffOnly": False,
            }],
            "identifiers": [],
            "items": [],
            "holdings": [],
        }
        normalized = normalize_exact_instance(instance, identifier_types={}, locations={})
        self.assertEqual(normalized["relationship_to_jefferson"], "exact_collection_heading_membership")
        self.assertEqual(normalized["ownership_or_reconstruction_status"], "unresolved")
        self.assertEqual(normalized["ownership_or_reconstruction_evidence"], [])

    def test_folio_source_record_conversion_preserves_marc_order_and_subfields(self) -> None:
        source = {
            "parsedRecord": {"content": {"leader": "00000nam a2200000 i 4500", "fields": [
                {"001": "7311922"},
                {"245": {"ind1": "1", "ind2": "0", "subfields": [{"a": "Title :"}, {"b": "subtitle."}]}},
                {"510": {"ind1": "4", "ind2": " ", "subfields": [{"a": "Sowerby"}, {"c": "3259"}]}},
            ]}}
        }
        marc = folio_source_to_marc(source)
        self.assertEqual(marc["leader"], "00000nam a2200000 i 4500")
        self.assertEqual(marc["control_fields"], [{"tag": "001", "value": "7311922"}])
        self.assertEqual([field["tag"] for field in marc["data_fields"]], ["245", "510"])
        self.assertEqual(marc["data_fields"][0]["subfields"][1], {"code": "b", "value": "subtitle."})

    def test_loc_sowerby_toc_and_index_remain_reference_layers(self) -> None:
        toc = b'''<pre>
<h3>Volume I</h3>
[Note: Volume I contains entries 1 - 1237].
HISTORY - CIVIL
 I   Ancient History  1
 II  Modern History - Foreign 62
<h3>Volume II</h3>
[Note: Volume II contains entries 1238 - 2322].
 XVI Ethics
 XXX Architecture
</pre>'''
        parsed = parse_loc_sowerby_toc(toc)
        self.assertEqual(parsed["volume_ranges"][0]["entry_count"], 1237)
        self.assertEqual(parsed["volume_ranges"][1]["first_sowerby_number"], 1238)
        self.assertEqual([chapter["chapter_number"] for chapter in parsed["chapters"]], [1, 2, 16, 30])
        self.assertEqual(parsed["chapters"][0]["faculty"], "History")
        self.assertEqual(parsed["chapters"][-1]["faculty"], "Fine Arts")
        spine = build_loc_sowerby_spine({"volume_ranges": parsed["volume_ranges"]})
        self.assertEqual(spine[0]["id"], "sowerby:1")
        self.assertEqual(spine[1237]["sowerby_number"], 1238)
        self.assertIn("identifier spine only", spine[0]["metadata_status"])

        index = b'''<pre>
<a name="A"><b>A</b></a>
Account of Louisiana, V, 3166a
Acts passed at a Congress (1791), 1873; see also V, 1873
Adams, Abigail: Correspondence, 1352, II p. 411,
  3184, 3518
Caslon, William, Specimen of
</pre>'''
        entries = parse_loc_sowerby_index(index)
        self.assertEqual(len(entries), 4)
        self.assertEqual(entries[0]["references"], [])
        self.assertTrue(any(
            ref["type"] == "volume_reference" and ref["reference"] == "3166a"
            for ref in entries[0]["reference_candidates_unvalidated"]
        ))
        self.assertTrue(any(ref["type"] == "see_also" for ref in entries[1]["reference_candidates_unvalidated"]))
        self.assertTrue(any(
            ref["type"] == "volume_page" and ref["page"] == 411
            for ref in entries[2]["reference_candidates_unvalidated"]
        ))
        self.assertIn("not used for crosswalks", entries[0]["reference_parsing_status"])
        self.assertEqual(entries[3]["reference_candidates_unvalidated"], [])

    def test_end_to_end_build_writes_full_jsonl_index_and_searchable_sqlite(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            sru = root / "cache" / "loc_sru" / "000001.xml"
            sru.parent.mkdir(parents=True)
            sru.write_bytes(MARC_PAGE)
            write_cache_sidecar(sru)
            search = root / "cache" / "loc_digital" / "search" / "0001.json"
            search.parent.mkdir(parents=True)
            search.write_text(json.dumps({
                "pagination": {"of": 1, "total": 1},
                "results": [{"id": "http://www.loc.gov/item/18020059/", "url": "https://www.loc.gov/item/18020059/", "number_lccn": ["18020059"], "title": "Speech"}],
            }), encoding="utf-8")
            write_cache_sidecar(search, "https://example.test/digital")
            transcript = root / "cache" / "sowerby_transcription" / "III_1.html"
            transcript.parent.mkdir(parents=True)
            transcript.write_bytes(SOWERBY_PAGE)
            write_cache_sidecar(transcript)

            exact_root = root / "cache" / "loc_catalog_exact"
            search_dir = exact_root / "search-p025"
            search_dir.mkdir(parents=True)
            (exact_root / "active.json").write_text(json.dumps({
                "page_size": 25,
                "cache_directory": "cache/loc_catalog_exact/search-p025",
            }), encoding="utf-8")
            catalog_page = search_dir / "offset-000000.json"
            catalog_page.write_text(json.dumps({
                "totalRecords": 1,
                "instances": [FOLIO_INSTANCE],
            }), encoding="utf-8")
            write_cache_sidecar(catalog_page, "https://example.test/catalog")
            reference = exact_root / "reference"
            reference.mkdir()
            identifier_types = reference / "identifier-types.json"
            identifier_types.write_text(json.dumps({
                "identifierTypes": [{"id": "lccn-type", "name": "LCCN"}],
            }), encoding="utf-8")
            write_cache_sidecar(identifier_types)
            locations = reference / "locations.json"
            locations.write_text(json.dumps({
                "locations": [{"id": "location-1", "name": "RBSCD Onsite", "discoveryDisplayName": "Rare Book Reading Room"}],
            }), encoding="utf-8")
            write_cache_sidecar(locations)

            manifest = build_outputs(root, generated_at="2026-08-01T12:00:00Z")
            self.assertEqual(manifest["counts"], {
                "loc_exact_catalog_instances": 1,
                "loc_exact_catalog_holdings": 1,
                "loc_exact_catalog_items": 1,
                "loc_broad_sru_marc_records": 1,
                "loc_digital_items": 1,
                "loc_sowerby_base_integer_identifiers": 0,
                "loc_sowerby_entry_spine": 0,
                "loc_sowerby_index_terms": 0,
                "monticello_sowerby_transcription_fragments": 1,
            })
            full_record = json.loads((root / "data" / "loc_sru_marc_records.jsonl").read_text().splitlines()[0])
            self.assertNotIn(
                "952",
                [field["tag"] for field in full_record["marc_projection"]["data_fields"]],
            )
            exact_record = json.loads((root / "data" / "loc_catalog_instances.jsonl").read_text().splitlines()[0])
            self.assertNotIn("internal workflow note", json.dumps(exact_record))
            self.assertNotIn("source_marc", exact_record)
            self.assertEqual(
                full_record["source"]["marc_projection_policy"],
                "loc-public-bibliographic-marc-allowlist@1",
            )
            self.assertEqual(exact_record["normalized"]["sowerby_numbers"], [])
            self.assertTrue(exact_record["normalized"]["sowerby_note_candidates_unparsed"])
            self.assertEqual(exact_record["normalized"]["items"][0]["effective_location"], "Rare Book Reading Room")
            index = json.loads((root / "data" / "loc_catalog_index.json").read_text())
            self.assertIn("not a Sowerby-entry", index["unit_of_count"])
            validation = json.loads((root / "data" / "validation.json").read_text())
            self.assertTrue(validation["catalog_exact"]["instance_count_matches"])
            self.assertEqual(validation["catalog_exact"]["staff_only_nodes_removed"], 3)
            connection = sqlite3.connect(root / "data" / "jefferson_catalog.sqlite")
            try:
                self.assertEqual(connection.execute("SELECT count(*) FROM catalog_records").fetchone()[0], 1)
                self.assertEqual(connection.execute("SELECT count(*) FROM catalog_instances").fetchone()[0], 1)
                self.assertEqual(connection.execute("SELECT count(*) FROM holdings").fetchone()[0], 1)
                self.assertEqual(connection.execute("SELECT count(*) FROM items").fetchone()[0], 1)
                self.assertEqual(connection.execute("SELECT count(*) FROM sowerby_entry_spine").fetchone()[0], 0)
                self.assertEqual(connection.execute("SELECT title FROM catalog_records").fetchone()[0], "Speech of Thomas Jefferson : delivered at his instalment.")
                self.assertEqual(connection.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            finally:
                connection.close()

    def test_active_snapshot_loaders_reject_stale_extra_pages(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            exact = root / "cache" / "loc_catalog_exact"
            search = exact / "generation" / "search"
            search.mkdir(parents=True)
            (exact / "active.json").write_text(json.dumps({
                "complete": True,
                "page_size": 25,
                "cache_directory": str(search.relative_to(root)),
                "source_marc_instance_ids": [],
            }), encoding="utf-8")
            payload = {"totalRecords": 1, "instances": [FOLIO_INSTANCE]}
            (search / "offset-000000.json").write_text(json.dumps(payload), encoding="utf-8")
            (search / "offset-000025.json").write_text(json.dumps(payload), encoding="utf-8")
            with self.assertRaisesRegex(ExtractionError, "unexpected pages"):
                load_exact_catalog_instances(root)

            digital = root / "cache" / "loc_digital"
            digital_search = digital / "generation" / "search"
            digital_search.mkdir(parents=True)
            (digital / "active.json").write_text(json.dumps({
                "complete": True,
                "search_directory": str(digital_search.relative_to(root)),
            }), encoding="utf-8")
            digital_payload = {
                "pagination": {"of": 1, "total": 1},
                "results": [{"id": "https://www.loc.gov/item/one/", "url": "https://www.loc.gov/item/one/"}],
            }
            (digital_search / "0001.json").write_text(json.dumps(digital_payload), encoding="utf-8")
            (digital_search / "0002.json").write_text(json.dumps(digital_payload), encoding="utf-8")
            with self.assertRaisesRegex(ExtractionError, "unexpected pages"):
                load_digital_items(root)

    def test_build_fails_closed_before_manifest_on_invalid_exact_snapshot(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            exact = root / "cache" / "loc_catalog_exact"
            search = exact / "search"
            search.mkdir(parents=True)
            (exact / "active.json").write_text(json.dumps({
                "complete": True,
                "page_size": 25,
                "cache_directory": str(search.relative_to(root)),
                "source_marc_instance_ids": [],
            }), encoding="utf-8")
            (search / "offset-000000.json").write_text(json.dumps({
                "totalRecords": 2,
                "instances": [FOLIO_INSTANCE],
            }), encoding="utf-8")
            with self.assertRaisesRegex(ExtractionError, "invalid source snapshot"):
                build_outputs(root, generated_at="2026-08-01T12:00:00Z")
            self.assertFalse((root / "data" / "manifest.json").exists())

    def test_build_rejects_an_empty_all_not_applicable_package(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with self.assertRaisesRegex(ExtractionError, "minimum_source_package"):
                build_outputs(root, generated_at="2026-08-01T12:00:00Z")
            self.assertFalse((root / "data" / "manifest.json").exists())

    def test_digital_detail_failure_does_not_activate_incomplete_snapshot(self) -> None:
        payload = json.dumps({
            "pagination": {"of": 1, "total": 1},
            "results": [{"id": "https://www.loc.gov/item/one/", "url": "https://www.loc.gov/item/one/"}],
        }).encode()

        def fake_fetch(_fetcher, url, _cache_path, **_kwargs):
            if "www.loc.gov/books/" in url:
                return payload
            raise ExtractionError("simulated persistent detail failure")

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            with mock.patch.object(CachedFetcher, "fetch", fake_fetch):
                with self.assertRaisesRegex(ExtractionError, "missing requested item details"):
                    harvest_digital(root, refresh=False, delay=0, item_details=True, item_delay=0)
            self.assertFalse((root / "cache" / "loc_digital" / "active.json").exists())

    def test_search_only_refresh_does_not_inherit_old_detail_requirement(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            cache = root / "cache" / "loc_digital"
            old_search = cache / "old" / "search"
            old_details = cache / "old" / "items"
            new_search = cache / "new" / "search"
            new_search.mkdir(parents=True)
            old_search.mkdir(parents=True)
            old_details.mkdir(parents=True)
            payload = {
                "pagination": {"of": 1, "total": 1},
                "results": [{"id": "https://www.loc.gov/item/one/", "url": "https://www.loc.gov/item/one/"}],
            }
            (new_search / "0001.json").write_text(json.dumps(payload), encoding="utf-8")
            (cache / "active.json").write_text(json.dumps({
                "complete": True,
                "search_facet": "contributor:thomas jefferson library collection (library of congress)",
                "search_directory": str(old_search.relative_to(root)),
                "detail_directory": str(old_details.relative_to(root)),
                "item_details_requested": True,
            }), encoding="utf-8")
            (cache / "pending.json").write_text(json.dumps({
                "search_facet": "contributor:thomas jefferson library collection (library of congress)",
                "search_directory": str(new_search.relative_to(root)),
                "detail_directory": str((cache / "new" / "items").relative_to(root)),
                "failure_directory": str((cache / "new" / "failures").relative_to(root)),
            }), encoding="utf-8")
            harvest_digital(root, refresh=True, delay=0, item_details=False, item_delay=0)
            active = json.loads((cache / "active.json").read_text())
            self.assertEqual(active["search_directory"], str(new_search.relative_to(root)))
            self.assertFalse(active["item_details_requested"])

    def test_sru_diagnostic_is_a_hard_failure(self) -> None:
        raw = b'''<zs:searchRetrieveResponse xmlns:zs="http://www.loc.gov/zing/srw/"><zs:numberOfRecords>0</zs:numberOfRecords><zs:diagnostics><zs:diagnostic><zs:message>Unsupported index</zs:message></zs:diagnostic></zs:diagnostics></zs:searchRetrieveResponse>'''
        with self.assertRaisesRegex(ExtractionError, "Unsupported index"):
            parse_sru_page(raw)


if __name__ == "__main__":
    unittest.main()
