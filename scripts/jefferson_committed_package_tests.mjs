import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readdir, readFile } from "node:fs/promises";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";

import {
  hydrateCatalogRecord,
  parseBrowserCatalog,
  parseCatalogDetailIndex,
  parseCatalogDetailShard,
  parseCatalogSearchIndex
} from "../docs/js/catalog-data.js";
import { parseCollectionManifest } from "../docs/js/collections.js";
import { eventContextForRecord, parseJeffersonInsightGraph } from "../docs/js/jefferson-insights.js";


const REPOSITORY_ROOT = fileURLToPath(new URL("../", import.meta.url));
const COLLECTION_ROOT = path.join(REPOSITORY_ROOT, "docs/data/collections/jefferson");
const HISTORICAL_ROOT = path.join(COLLECTION_ROOT, "historical");
const CHAPTER_RANGES_PATH = path.join(REPOSITORY_ROOT, "research/jefferson/loc-sowerby-chapter-ranges.json");
const EXPECTED_GAPS = [2323, 4707, 4708];


async function jsonAt(root, relative) {
  return JSON.parse(await readFile(path.join(root, relative), "utf8"));
}


function sha256(body) {
  return `sha256:${createHash("sha256").update(body).digest("hex")}`;
}


async function filesUnder(root, prefix = "") {
  const result = [];
  for (const entry of await readdir(path.join(root, prefix), { withFileTypes: true })) {
    const relative = path.posix.join(prefix, entry.name);
    if (entry.isDirectory()) result.push(...await filesUnder(root, relative));
    else if (entry.isFile()) result.push(relative);
    else throw new Error(`Unexpected non-file in committed package: ${relative}`);
  }
  return result.sort();
}


async function parsedManifest() {
  const raw = await jsonAt(COLLECTION_ROOT, "manifest.json");
  const parsed = parseCollectionManifest(raw, { expectedId: "jefferson" });
  assert.equal(parsed.rejected, false, JSON.stringify(parsed.errors));
  return parsed.manifest;
}


function corpusOptions(corpus) {
  return {
    collectionId: "jefferson",
    corpusId: corpus.id,
    entityType: corpus.coverage.entity_type,
    recordIdPrefix: corpus.record_id_prefix,
    detailPathTemplate: corpus.data.detail_template,
    searchPath: corpus.data.search
  };
}


test("committed Jefferson manifest exposes disjoint catalog and historical corpora", async () => {
  const manifest = await parsedManifest();
  assert.equal(manifest.schema, "shelfsignals-collection-manifest@2");
  assert.deepEqual(manifest.defaults, { corpus: "catalog", order: "title" });
  assert.deepEqual(manifest.corpora.map(corpus => corpus.id), ["catalog", "historical"]);

  const [catalog, historical] = manifest.corpora;
  assert.equal(catalog.coverage.record_count, 2748);
  assert.equal(catalog.coverage.entity_type, "catalog_instance");
  assert.equal(historical.coverage.record_count, 4928);
  assert.equal(historical.coverage.historical_position_count, 4931);
  assert.equal(historical.coverage.historical_volume_count, 6487);
  assert.equal(historical.default_order, "sowerby");
  assert.ok(Object.values(historical.data).every(value => value.startsWith("historical/")));
  assert.equal(new Set(Object.values(catalog.data).filter(Boolean).filter(value => Object.values(historical.data).includes(value))).size, 0);

  const catalogCore = parseBrowserCatalog(await jsonAt(COLLECTION_ROOT, catalog.data.core), corpusOptions(catalog));
  assert.equal(catalogCore.rejected, false, JSON.stringify(catalogCore.errors));
  assert.equal(catalogCore.records.length, 2748);
  assert.ok(catalogCore.records.every(record => record.id.startsWith("jefferson-loc-")));

  const historicalCore = parseBrowserCatalog(await jsonAt(COLLECTION_ROOT, historical.data.core), corpusOptions(historical));
  assert.equal(historicalCore.rejected, false, JSON.stringify(historicalCore.errors));
  assert.equal(historicalCore.records.length, 4928);
  assert.ok(historicalCore.records.every(record => record.id.startsWith("jefferson-sowerby-")));
});


test("committed historical projections are complete, hash-bound, private-source-free, and browser-decodable", async () => {
  const manifest = await parsedManifest();
  const corpus = manifest.corpora.find(candidate => candidate.id === "historical");
  assert.ok(corpus);
  const options = corpusOptions(corpus);
  const core = parseBrowserCatalog(await jsonAt(COLLECTION_ROOT, corpus.data.core), options);
  assert.equal(core.rejected, false, JSON.stringify(core.errors));
  const ids = new Set(core.records.map(record => record.id));
  assert.equal(ids.size, 4928);
  assert.deepEqual(core.numbering.gaps.map(gap => Number(gap.identifier)), EXPECTED_GAPS);
  for (const gap of EXPECTED_GAPS) assert.equal(ids.has(`jefferson-sowerby-${gap}`), false);

  const shared = {
    ...options,
    catalogIds: ids,
    catalogSource: core.source,
    datasetSha256: core.source.dataset_sha256
  };
  const search = parseCatalogSearchIndex(await jsonAt(COLLECTION_ROOT, corpus.data.search), shared);
  assert.equal(search.rejected, false, JSON.stringify(search.errors));
  assert.equal(search.searchById.size, 4928);

  const rawIndex = await jsonAt(COLLECTION_ROOT, corpus.data.detail_index);
  const index = parseCatalogDetailIndex(rawIndex, { ...shared, expectedShardCount: 64 });
  assert.equal(index.rejected, false, JSON.stringify(index.errors));
  assert.equal(index.shards.length, 64);

  const details = new Map();
  for (const declaration of index.shards) {
    const relative = `catalog-details/${declaration.file}`;
    const body = await readFile(path.join(HISTORICAL_ROOT, relative));
    assert.equal(body.length, declaration.bytes, `${relative} byte count drifted`);
    assert.equal(sha256(body), declaration.sha256, `${relative} hash drifted`);
    const parsed = parseCatalogDetailShard(JSON.parse(body), { ...shared, expectedShard: declaration.shard });
    assert.equal(parsed.rejected, false, `${relative}: ${JSON.stringify(parsed.errors)}`);
    for (const [id, detail] of parsed.detailsById) {
      assert.equal(details.has(id), false, `duplicate historical detail ${id}`);
      details.set(id, detail);
    }
  }
  assert.equal(details.size, 4928);
  assert.deepEqual([...details.keys()].sort(), [...ids].sort());

  const validation = await jsonAt(COLLECTION_ROOT, corpus.data.validation);
  assert.equal(validation.schema, "shelfsignals-jefferson-historical-validation@1");
  assert.deepEqual(validation.source, core.source);
  assert.equal(validation.counts.source_backed_entries, 4928);
  assert.equal(validation.counts.max_source_serial, 4931);
  assert.equal(validation.counts.source_number_gaps, 3);
  assert.equal(validation.counts.chapters, 44);
  assert.equal(validation.counts.source_backed_titles + validation.counts.titles_not_established, 4928);
  assert.equal(validation.counts.page_resolved_identifiers + validation.counts.aggregate_spine_identifiers, 4928);
  assert.equal(core.records.filter(record => record.evidence_status === "sowerby_entry_page_resolved").length, validation.counts.page_resolved_identifiers);
  assert.equal(core.records.filter(record => record.evidence_status === "sowerby_entry_aggregate_spine").length, validation.counts.aggregate_spine_identifiers);
  assert.ok(core.records.every(record => !record.material_type && record.formats.length === 0));
  assert.ok(validation.counts.source_backed_titles > 0);
  assert.ok(Object.values(validation.checks).every(value => value === true));

  const insights = parseJeffersonInsightGraph(await jsonAt(COLLECTION_ROOT, corpus.data.insights), {
    catalogSource: core.source,
    recordIds: ids,
    recordChapters: new Map(core.records.map(record => [record.id, record.chapter_number]))
  });
  assert.equal(insights.rejected, false, JSON.stringify(insights.errors));
  assert.equal(insights.events.length, 9);
  assert.equal(insights.chapter_clusters.length, 44);
  assert.equal(insights.record_relations.length, 5);
  assert.equal(insights.coverage.source_backed_titles, validation.counts.source_backed_titles);
  assert.equal(insights.coverage.titles_not_established, validation.counts.titles_not_established);
  const adamsContext = eventContextForRecord(insights, core.records.find(record => record.id === "jefferson-sowerby-4659"));
  const adamsRelation = adamsContext.find(context => context.event.id === "adams-homespun-1812")?.direct;
  assert.equal(adamsRelation?.event_use_status, "documented_interaction");
  assert.equal(adamsRelation?.use_confidence_score, 98);
  assert.equal(insights.record_relations.filter(relation => relation.event_use_status === "not_established").every(relation => relation.use_confidence_score === null), true);

  const chapterRangesBody = await readFile(CHAPTER_RANGES_PATH);
  assert.equal(
    sha256(chapterRangesBody),
    validation.source_package.loc_chapter_ranges_sha256,
    "tracked LOC chapter-range evidence drifted from the published historical package"
  );
  const chapterRanges = JSON.parse(chapterRangesBody);
  assert.equal(chapterRanges.authority, "Library of Congress");
  assert.equal(chapterRanges.chapters.length, 44);
  assert.deepEqual(chapterRanges.numbering.confirmed_absent_numbers, EXPECTED_GAPS);
  const covered = new Set();
  for (const chapter of chapterRanges.chapters) {
    for (let identifier = chapter.start_identifier; identifier <= chapter.end_identifier; identifier += 1) {
      if (!EXPECTED_GAPS.includes(identifier)) covered.add(identifier);
    }
  }
  assert.equal(covered.size, 4928);
  assert.ok([...ids].every(id => covered.has(Number(id.replace("jefferson-sowerby-", "")))));

  const expectedFiles = new Set([...Object.keys(validation.outputs), "validation.json", "insights.json"]);
  assert.deepEqual(new Set(await filesUnder(HISTORICAL_ROOT)), expectedFiles);
  const forbidden = /(?:https?:\/\/)?(?:www\.|tjlibraries\.)?monticello\.org|thomas jefferson foundation|\/research\/jefferson\/|\/Volumes\/|\.sqlite(?:3)?(?:["'\s?#]|$)/iu;
  for (const [relative, identity] of Object.entries(validation.outputs)) {
    const body = await readFile(path.join(HISTORICAL_ROOT, relative));
    assert.equal(body.length, identity.bytes, `${relative} validation byte count drifted`);
    assert.equal(sha256(body), identity.sha256, `${relative} validation hash drifted`);
    assert.equal(forbidden.test(body.toString("utf8")), false, `${relative} leaked private/local source identity`);
  }
  const insightBody = await readFile(path.join(HISTORICAL_ROOT, "insights.json"));
  assert.equal(forbidden.test(insightBody.toString("utf8")), false, "insights.json leaked private/local source identity");

  const sourceBacked = core.records.find(record => record.title_status === "source_backed");
  const unresolved = core.records.find(record => record.title_status === "not_established");
  assert.ok(sourceBacked);
  assert.ok(unresolved);
  hydrateCatalogRecord(sourceBacked, details.get(sourceBacked.id));
  hydrateCatalogRecord(unresolved, details.get(unresolved.id));
  assert.equal(sourceBacked.detail_hydrated, true);
  assert.equal(unresolved.detail_hydrated, true);
  assert.match(unresolved.title, /^Sowerby entry \d+ — title not established$/);
  assert.equal(unresolved.ownership_or_reconstruction_status, "not_established");
});
