import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { parseBrowserCatalog } from "../docs/js/catalog-data.js";
import { eventContextForRecord, parseJeffersonInsightGraph } from "../docs/js/jefferson-insights.js";


const root = new URL("../docs/data/collections/jefferson/historical/", import.meta.url);


async function fixtures() {
  const coreRaw = JSON.parse(await readFile(new URL("catalog-core.json", root), "utf8"));
  const core = parseBrowserCatalog(coreRaw, {
    collectionId: "jefferson",
    corpusId: "historical",
    entityType: "sowerby_entry",
    recordIdPrefix: "jefferson-sowerby-",
    detailPathTemplate: "historical/catalog-details/{shard}.json",
    searchPath: "historical/catalog-search.json"
  });
  assert.equal(core.rejected, false, JSON.stringify(core.errors));
  const graph = JSON.parse(await readFile(new URL("insights.json", root), "utf8"));
  return {
    core,
    graph,
    recordIds: new Set(core.records.map(record => record.id)),
    recordChapters: new Map(core.records.map(record => [record.id, record.chapter_number]))
  };
}


test("Jefferson insight graph binds events, chapters, records, and explicit use evidence", async () => {
  const { core, graph, recordIds, recordChapters } = await fixtures();
  const parsed = parseJeffersonInsightGraph(graph, { catalogSource: core.source, recordIds, recordChapters });
  assert.equal(parsed.rejected, false, JSON.stringify(parsed.errors));
  assert.equal(parsed.events.length, 9);
  assert.equal(parsed.chapter_clusters.reduce((sum, chapter) => sum + chapter.record_count, 0), 4928);
  assert.equal(parsed.record_relations.filter(relation => relation.use_confidence_score !== null).length, 3);
  assert.equal(parsed.record_relations.filter(relation => relation.event_use_status === "not_established").every(relation => relation.use_confidence_score === null), true);

  const adams = core.records.find(record => record.id === "jefferson-sowerby-4659");
  const contexts = eventContextForRecord(parsed, adams);
  assert.ok(contexts.some(context => context.event.id === "adams-homespun-1812" && context.direct?.connection_score === 100));
  assert.ok(contexts.some(context => context.event.id === "library-to-congress-1815" && context.direct === null));
});


test("Jefferson insight graph fails closed on unsafe sources, unbounded claims, and catalog drift", async () => {
  const { core, graph, recordIds, recordChapters } = await fixtures();
  const unsafe = structuredClone(graph);
  unsafe.sources[0].url = "https://example.com/not-reviewed";
  assert.equal(parseJeffersonInsightGraph(unsafe, { catalogSource: core.source, recordIds, recordChapters }).rejected, true);

  const inventedScore = structuredClone(graph);
  const relation = inventedScore.record_relations.find(row => row.event_use_status === "not_established");
  relation.use_confidence_score = 50;
  assert.equal(parseJeffersonInsightGraph(inventedScore, { catalogSource: core.source, recordIds, recordChapters }).rejected, true);

  const driftedSource = { ...core.source, dataset_sha256: `sha256:${"f".repeat(64)}` };
  assert.equal(parseJeffersonInsightGraph(graph, { catalogSource: driftedSource, recordIds, recordChapters }).rejected, true);

  const unknownRecord = structuredClone(graph);
  unknownRecord.record_relations[0].record_id = "jefferson-sowerby-9999";
  assert.equal(parseJeffersonInsightGraph(unknownRecord, { catalogSource: core.source, recordIds, recordChapters }).rejected, true);

  const crossCluster = structuredClone(graph);
  crossCluster.record_relations[0].record_id = "jefferson-sowerby-1";
  assert.equal(parseJeffersonInsightGraph(crossCluster, { catalogSource: core.source, recordIds, recordChapters }).rejected, true);
});
