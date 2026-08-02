import assert from "node:assert/strict";
import test from "node:test";

import { parseUrlState, serializeUrlState } from "../docs/js/catalog.js";
import {
  COLLECTION_MANIFEST_SCHEMA,
  collectionDataUrl,
  parseCollectionManifest
} from "../docs/js/collections.js";
import { createReceipt } from "../docs/js/receipt.js";
import {
  JEFFERSON_SHELF_STORAGE_KEY,
  SHELF_STORAGE_KEY,
  loadShelfIds,
  mergeShelfIdsForCorpus,
  restoreShelfFromReceipt,
  saveShelfIds
} from "../docs/js/shelf.js";

class MemoryStorage {
  constructor() {
    this.values = new Map();
  }

  getItem(key) {
    return this.values.has(key) ? this.values.get(key) : null;
  }

  setItem(key, value) {
    this.values.set(key, String(value));
  }
}

function validJeffersonManifest() {
  return {
    schema: COLLECTION_MANIFEST_SCHEMA,
    id: "jefferson",
    copy: {
      name: "Thomas Jefferson Library",
      short_name: "Jefferson",
      institution: "Library of Congress",
      status_label: "Catalog beta",
      introduction: "A current-catalog evidence layer for the Jefferson collection.",
      coverage_statement: "2,748 catalog instances; not the complete historical corpus.",
      source_label: "Library of Congress catalog"
    },
    data: {
      core: "catalog-core.json",
      search: "catalog-search.json",
      detail_template: "catalog-details/{shard}.json",
      detail_index: "catalog-details/index.json",
      hierarchy: "hierarchy.json",
      public_media: "media-public.json",
      review_media: "media-review.json"
    },
    features: {
      journeys: false,
      placement: false,
      photo_likelihood: false,
      provider_editions: false,
      curated_paths: false,
      historical_hierarchy: true,
      coverage_comparison: true,
      reconstruction_status: true,
      digital_surrogates: true,
      evidence_ledger: true,
      life_events: false,
      physical: false
    },
    coverage: {
      status: "beta",
      entity_type: "catalog_instance",
      record_count: 2748,
      historical_entry_count: 4931,
      historical_volume_count: 6487,
      established_sowerby_links: 17
    },
    shelf: {
      storage_key: JEFFERSON_SHELF_STORAGE_KEY,
      receipt_name: "shelfsignals-jefferson-shelf.json"
    },
    facets: ["languages", "subjects", "material_types", "evidence_status"],
    orders: [
      { id: "title", label: "Title" },
      { id: "lc", label: "Library of Congress classification" }
    ],
    defaults: {
      corpus: "catalog",
      order: "title"
    },
    review: {
      enabled: true,
      code_sha256: `sha256:${"a".repeat(64)}`,
      session_key: "shelfsignals_review:jefferson",
      warning: "Review mode is interface friction, not access control."
    }
  };
}

test("collection, corpus, and order round-trip without disturbing unrelated URL state", () => {
  const serialized = serializeUrlState({
    collection: "JEFFERSON",
    corpus: "CATALOG",
    order: "TITLE",
    evidence: "sowerby_510_exact_bounded",
    record: "jefferson-loc-example"
  }, "https://example.test/ShelfSignals/?collection=stale&corpus=stale&order=stale&unrelated=kept#evidence");

  const result = new URL(serialized, "https://example.test");
  assert.equal(result.searchParams.get("collection"), "jefferson");
  assert.equal(result.searchParams.get("corpus"), "catalog");
  assert.equal(result.searchParams.get("order"), "title");
  assert.equal(result.searchParams.get("evidence"), "sowerby_510_exact_bounded");
  assert.equal(result.searchParams.get("record"), "jefferson-loc-example");
  assert.equal(result.searchParams.get("unrelated"), "kept");
  assert.equal(result.hash, "#evidence");

  const restored = parseUrlState(result.href);
  assert.equal(restored.collection, "jefferson");
  assert.equal(restored.corpus, "catalog");
  assert.equal(restored.order, "title");
  assert.equal(restored.evidence, "sowerby_510_exact_bounded");
  assert.equal(restored.record, "jefferson-loc-example");
});

test("life-event URL state is scoped to the Jefferson historical corpus", () => {
  const historical = new URL(serializeUrlState({
    collection: "jefferson",
    corpus: "historical",
    order: "sowerby",
    event: "adams-homespun-1812"
  }, "https://example.test/ShelfSignals/"), "https://example.test");
  assert.equal(historical.searchParams.get("event"), "adams-homespun-1812");
  assert.equal(parseUrlState(historical.href).event, "adams-homespun-1812");

  const catalog = parseUrlState("https://example.test/ShelfSignals/?collection=jefferson&corpus=catalog&event=adams-homespun-1812");
  assert.equal(catalog.event, "");
  const sekula = parseUrlState("https://example.test/ShelfSignals/?event=adams-homespun-1812");
  assert.equal(sekula.event, "");
});

test("URL state normalizes invalid collection dimensions and keeps Sekula canonical", () => {
  const parsed = parseUrlState("https://example.test/ShelfSignals/?collection=unknown&corpus=complete&order=physical");
  assert.equal(parsed.collection, "sekula");
  assert.equal(parsed.corpus, "");
  assert.equal(parsed.order, "");

  const serialized = serializeUrlState({
    collection: "unknown",
    corpus: "complete",
    order: "physical"
  }, "https://example.test/ShelfSignals/?collection=jefferson&corpus=historical&order=sowerby&unrelated=kept");
  const canonical = new URL(serialized, "https://example.test");
  assert.equal(canonical.searchParams.has("collection"), false);
  assert.equal(canonical.searchParams.has("corpus"), false);
  assert.equal(canonical.searchParams.has("order"), false);
  assert.equal(canonical.searchParams.get("unrelated"), "kept");

  const sekula = serializeUrlState({
    collection: "sekula",
    corpus: "historical",
    order: "sowerby"
  }, "https://example.test/ShelfSignals/");
  assert.equal(new URL(sekula, "https://example.test").search, "");
});

test("Jefferson URLs discard disabled Sekula-only state", () => {
  const parsed = parseUrlState("https://example.test/ShelfSignals/?collection=jefferson&signals=labor&signalMode=all&photo=high&placement=east&group=material&path=books&journey=one&cluster=two&view=spines");
  assert.deepEqual(parsed.signals, []);
  assert.equal(parsed.signalMode, "any");
  assert.equal(parsed.photo, "");
  assert.equal(parsed.placement, "");
  assert.equal(parsed.group, "lc");
  assert.equal(parsed.path, "");
  assert.equal(parsed.journey, "");
  assert.equal(parsed.cluster, "");
  assert.equal(parsed.view, "covers");

  const serialized = new URL(serializeUrlState({
    collection: "jefferson",
    corpus: "catalog",
    order: "title",
    signals: ["labor"],
    signalMode: "all",
    photo: "high",
    placement: "east",
    group: "material",
    path: "books",
    journey: "one",
    cluster: "two",
    view: "spines"
  }, "https://example.test/ShelfSignals/"), "https://example.test");
  for (const key of ["signals", "signalMode", "photo", "placement", "group", "path", "journey", "cluster", "view"]) {
    assert.equal(serialized.searchParams.has(key), false, `${key} leaked into Jefferson URL state`);
  }
});

test("Sekula and Jefferson shelves persist under separate storage keys", () => {
  assert.equal(SHELF_STORAGE_KEY, "shelfsignals_shelf");
  assert.equal(JEFFERSON_SHELF_STORAGE_KEY, "shelfsignals_shelf:jefferson");
  assert.notEqual(SHELF_STORAGE_KEY, JEFFERSON_SHELF_STORAGE_KEY);

  const storage = new MemoryStorage();
  assert.equal(saveShelfIds(["alma-sekula"], storage, SHELF_STORAGE_KEY).ok, true);
  assert.equal(saveShelfIds(["jefferson-loc-example"], storage, JEFFERSON_SHELF_STORAGE_KEY).ok, true);

  assert.deepEqual(loadShelfIds(storage), ["alma-sekula"], "the default key remains the migrated Sekula shelf");
  assert.deepEqual(loadShelfIds(storage, SHELF_STORAGE_KEY), ["alma-sekula"]);
  assert.deepEqual(loadShelfIds(storage, JEFFERSON_SHELF_STORAGE_KEY), ["jefferson-loc-example"]);
});

test("receipt@2 carries its dataset ID and rejects cross-collection restore without fetching", async () => {
  const originalFetch = globalThis.fetch;
  let fetchCount = 0;
  globalThis.fetch = async () => {
    fetchCount += 1;
    throw new Error("network access is forbidden in this contract test");
  };

  try {
    const receipt = await createReceipt({
      items: ["jefferson-loc-example"],
      datasetId: "jefferson",
      datasetName: "Thomas Jefferson Library",
      datasetHash: `sha256:${"b".repeat(64)}`
    });

    assert.equal(receipt.schema, "shelfsignals-receipt@2");
    assert.equal(receipt.dataset.id, "jefferson");
    assert.equal(receipt.dataset.indexHash, "b".repeat(64));
    assert.equal(fetchCount, 0);

    const records = [{ id: "jefferson-loc-example" }];
    assert.deepEqual(restoreShelfFromReceipt(receipt, records, { collectionId: "jefferson" }), {
      valid: true,
      ids: ["jefferson-loc-example"],
      missing: []
    });
    assert.deepEqual(restoreShelfFromReceipt(receipt, records, { collectionId: "sekula" }), {
      valid: false,
      ids: [],
      missing: []
    });
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("Jefferson receipts are corpus- and dataset-bound without erasing sibling-corpus shelf IDs", async () => {
  const catalogHash = `sha256:${"b".repeat(64)}`;
  const receipt = await createReceipt({
    items: ["jefferson-loc-one"],
    datasetId: "jefferson",
    datasetName: "Thomas Jefferson Library",
    datasetCorpus: "catalog",
    datasetHash: catalogHash
  });
  assert.equal(receipt.dataset.corpus, "catalog");
  const records = [{ id: "jefferson-loc-one" }, { id: "jefferson-loc-two" }];
  assert.equal(restoreShelfFromReceipt(receipt, records, {
    collectionId: "jefferson",
    corpusId: "historical",
    datasetHash: catalogHash
  }).valid, false);
  assert.equal(restoreShelfFromReceipt(receipt, records, {
    collectionId: "jefferson",
    corpusId: "catalog",
    datasetHash: `sha256:${"c".repeat(64)}`
  }).valid, false);
  const restored = restoreShelfFromReceipt(receipt, records, {
    collectionId: "jefferson",
    corpusId: "catalog",
    datasetHash: catalogHash
  });
  assert.equal(restored.valid, true);
  assert.deepEqual(
    mergeShelfIdsForCorpus(
      ["jefferson-loc-two", "jefferson-sowerby-3259a"],
      restored.ids,
      records,
      { recordIdPrefix: "jefferson-loc-" }
    ),
    ["jefferson-sowerby-3259a", "jefferson-loc-one"]
  );
});

test("legacy Jefferson receipt@2 without corpus remains catalog-only", () => {
  const receipt = {
    schema: "shelfsignals-receipt@2",
    dataset: { id: "jefferson", name: "Thomas Jefferson Library", indexHash: "b".repeat(64) },
    items: ["jefferson-loc-one"]
  };
  const records = [{ id: "jefferson-loc-one" }];
  assert.equal(restoreShelfFromReceipt(receipt, records, {
    collectionId: "jefferson",
    corpusId: "catalog",
    datasetHash: `sha256:${"b".repeat(64)}`
  }).valid, true);
  assert.equal(restoreShelfFromReceipt(receipt, records, {
    collectionId: "jefferson",
    corpusId: "historical",
    datasetHash: `sha256:${"b".repeat(64)}`
  }).valid, false);
});

test("legacy receipt@1 restores only into Sekula", () => {
  const receipt = {
    schema: "shelfsignals-receipt@1",
    items: ["alma-sekula", "missing"]
  };
  const records = [{ id: "alma-sekula" }];

  assert.deepEqual(restoreShelfFromReceipt(receipt, records, { collectionId: "sekula" }), {
    valid: true,
    ids: ["alma-sekula"],
    missing: ["missing"]
  });
  assert.deepEqual(restoreShelfFromReceipt(receipt, records, { collectionId: "jefferson" }), {
    valid: false,
    ids: [],
    missing: []
  });
});

test("collection manifests validate fail-closed and resolve only safe relative assets", () => {
  const raw = validJeffersonManifest();
  const parsed = parseCollectionManifest(raw, { expectedId: "jefferson" });
  assert.equal(parsed.rejected, false);
  assert.deepEqual(parsed.errors, []);
  assert.notEqual(parsed.manifest, raw, "the accepted manifest is returned as a defensive clone");

  const manifestUrl = "https://example.test/ShelfSignals/data/collections/jefferson/manifest.json";
  assert.equal(
    collectionDataUrl(parsed.manifest, "core", manifestUrl).href,
    "https://example.test/ShelfSignals/data/collections/jefferson/catalog-core.json"
  );
  assert.equal(
    collectionDataUrl(parsed.manifest, "detail_template", manifestUrl, { shard: 7 }).href,
    "https://example.test/ShelfSignals/data/collections/jefferson/catalog-details/007.json"
  );

  const wrongCollection = parseCollectionManifest(raw, { expectedId: "sekula" });
  assert.equal(wrongCollection.rejected, true);
  assert.equal(wrongCollection.manifest, null);
  assert.ok(wrongCollection.errors.some(error => error.path === "id" && error.code === "collection"));

  const unsafePath = structuredClone(raw);
  unsafePath.data.core = "../catalog-core.json";
  const unsafeResult = parseCollectionManifest(unsafePath, { expectedId: "jefferson" });
  assert.equal(unsafeResult.rejected, true);
  assert.ok(unsafeResult.errors.some(error => error.path === "data.core" && error.code === "path"));

  const mixedShelf = structuredClone(raw);
  mixedShelf.shelf.storage_key = SHELF_STORAGE_KEY;
  const mixedShelfResult = parseCollectionManifest(mixedShelf, { expectedId: "jefferson" });
  assert.equal(mixedShelfResult.rejected, true);
  assert.ok(mixedShelfResult.errors.some(error => error.path === "shelf.storage_key" && error.code === "storage"));

  const unknownField = structuredClone(raw);
  unknownField.features.unreviewed_experiment = true;
  const unknownFieldResult = parseCollectionManifest(unknownField, { expectedId: "jefferson" });
  assert.equal(unknownFieldResult.rejected, true);
  assert.ok(unknownFieldResult.errors.some(error => error.path === "features.unreviewed_experiment" && error.code === "field"));
});
