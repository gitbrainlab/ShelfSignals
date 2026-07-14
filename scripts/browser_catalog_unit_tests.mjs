import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import test from "node:test";
import { gzipSync } from "node:zlib";

import {
  detailShardName,
  hydrateCatalogRecord,
  parseBrowserCatalog,
  parseCatalogDetailShard,
  parseCatalogSearchIndex
} from "../docs/js/catalog-data.js";
import { buildBrowserCatalog } from "./build_browser_catalog.mjs";

const RECORD_URL_TEMPLATE = "https://library.clarkart.edu/discovery/fulldisplay?docid={id}&context=L&vid=01CLARKART_INST%3A01CLARKART_INST_FRANCINE&lang=en&tab=LibraryCatalog";

function canonicalRecord(id, overrides = {}) {
  return {
    id,
    alma_mms: id.replace(/^alma/, ""),
    title: `Catalog title ${id}`,
    authors: ["Catalog author"],
    year: "1985",
    call_number: "NE2698 .S4637L 00001",
    material_type: "book",
    formats: ["112 pages : illustrations ; 24 cm"],
    subjects: ["Photography", "Shipping"],
    notes: ["Catalog note"],
    photo_insert_reasoning: "Mock: legacy machine-generated note that is not public evidence.",
    provenance_notes: ["Gift; Sekula Library Identifier: Front Bedroom A"],
    publishers: ["Catalog publisher"],
    isbns: ["9780306406157"],
    holdings: [{
      subLocation: "Rare Compact Storage",
      subLocationCode: "RARECX",
      callNumber: "NE2698 .S4637L 00001",
      availabilityStatus: "available",
      holKey: "intentionally omitted from browser projection"
    }],
    best_location: {
      subLocation: "Rare Compact Storage",
      subLocationCode: "RARECX",
      callNumber: "NE2698 .S4637L 00001",
      availabilityStatus: "available"
    },
    availability: "available",
    record_url: RECORD_URL_TEMPLATE.replace("{id}", id),
    ...overrides
  };
}

function fixture() {
  const records = [canonicalRecord("alma1"), canonicalRecord("alma2", { title: "Ports and capital" })];
  const catalogBytes = Buffer.from(`${JSON.stringify(records, null, 2)}\n`);
  return buildBrowserCatalog({ records, catalogBytes, generatedAt: "2026-07-14T12:00:00Z", shardCount: 4 });
}

test("compact catalog reconstructs canonical Clark links and source-backed browsing fields", () => {
  const built = fixture();
  const parsed = parseBrowserCatalog(built.core);
  assert.equal(parsed.rejected, false);
  assert.equal(parsed.records.length, 2);
  assert.equal(parsed.records[0].record_url, RECORD_URL_TEMPLATE.replace("{id}", "alma1"));
  assert.deepEqual(parsed.records[0].placements.map(item => item.label), ["Front Bedroom A"]);
  assert.equal(parsed.records[0].signals.includes("image"), true);
  assert.equal(parsed.records[0].signals.includes("sea"), true);
  assert.equal(parsed.records[0].detail_hydrated, false);
  assert.deepEqual(parsed.records[0].subjects, []);
});

test("compact catalog rejects source drift, duplicate IDs, and shard tampering", () => {
  const built = fixture();
  const stale = structuredClone(built.core);
  stale.source.dataset_sha256 = `sha256:${"0".repeat(64)}`;
  stale.source.dataset = "different.json";
  assert.equal(parseBrowserCatalog(stale).rejected, true);

  const duplicate = structuredClone(built.core);
  duplicate.items[1][0] = duplicate.items[0][0];
  assert.equal(parseBrowserCatalog(duplicate).rejected, true);

  const wrongShard = structuredClone(built.core);
  wrongShard.items[0][11] = (wrongShard.items[0][11] + 1) % 4;
  assert.equal(parseBrowserCatalog(wrongShard).rejected, true);
});

test("lazy search requires complete same-catalog coverage", () => {
  const built = fixture();
  const core = parseBrowserCatalog(built.core);
  const ids = new Set(core.records.map(record => record.id));
  const parsed = parseCatalogSearchIndex(built.search, { datasetSha256: core.source.dataset_sha256, catalogIds: ids });
  assert.equal(parsed.rejected, false);
  assert.equal(parsed.searchById.get("alma2").includes("ports and capital"), true);

  const incomplete = structuredClone(built.search);
  incomplete.items.pop();
  assert.equal(parseCatalogSearchIndex(incomplete, { datasetSha256: core.source.dataset_sha256, catalogIds: ids }).rejected, true);

  const stale = structuredClone(built.search);
  stale.source.dataset_sha256 = `sha256:${"f".repeat(64)}`;
  assert.equal(parseCatalogSearchIndex(stale, { datasetSha256: core.source.dataset_sha256, catalogIds: ids }).rejected, true);
});

test("detail shards hydrate exact metadata without leaking discarded holding internals", () => {
  const built = fixture();
  const core = parseBrowserCatalog(built.core);
  const ids = new Set(core.records.map(record => record.id));
  const target = core.records[0];
  const rawShard = built.detailShards[target.detail_shard];
  const parsed = parseCatalogDetailShard(rawShard, {
    datasetSha256: core.source.dataset_sha256,
    catalogIds: ids,
    expectedShard: target.detail_shard
  });
  assert.equal(parsed.rejected, false);
  hydrateCatalogRecord(target, parsed.detailsById.get(target.id));
  assert.equal(target.detail_hydrated, true);
  assert.deepEqual(target.subjects, ["Photography", "Shipping"]);
  assert.equal(target.best_location.subLocation, "Rare Compact Storage");
  assert.equal("holKey" in target.holdings[0], false);
  assert.equal("photo_insert_reasoning" in target, false);
  assert.equal(JSON.stringify(rawShard).includes("Mock: legacy machine-generated note"), false);
  assert.deepEqual(target.isbns, ["9780306406157"]);

  const crossShard = structuredClone(rawShard);
  crossShard.shard = (target.detail_shard + 1) % 4;
  assert.equal(parseCatalogDetailShard(crossShard, {
    datasetSha256: core.source.dataset_sha256,
    catalogIds: ids,
    expectedShard: target.detail_shard
  }).rejected, true);
});

test("committed browser core is bound to the canonical catalog bytes", async () => {
  const [catalogBytes, rawCore] = await Promise.all([
    readFile(new URL("../docs/data/sekula_index.json", import.meta.url)),
    readFile(new URL("../docs/data/catalog-core.json", import.meta.url), "utf8")
  ]);
  const expectedSha = `sha256:${createHash("sha256").update(catalogBytes).digest("hex")}`;
  const parsed = parseBrowserCatalog(JSON.parse(rawCore));
  assert.equal(parsed.rejected, false);
  assert.equal(parsed.source.dataset_sha256, expectedSha);
  assert.equal(parsed.records.length, 11176);
  assert.ok(Buffer.byteLength(rawCore) < 5_000_000, "decoded first-load catalog must remain under 5 MB");
  assert.ok(gzipSync(rawCore).byteLength < 1_200_000, "compressed first-load catalog must remain under 1.2 MB");
  const shardName = detailShardName(parsed.records[0].detail_shard);
  assert.match(shardName, /^\d{3}\.json$/);
});
