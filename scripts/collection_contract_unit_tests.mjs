import assert from "node:assert/strict";
import test from "node:test";

import {
  BROWSER_CATALOG_SCHEMA_V2,
  CATALOG_DETAIL_INDEX_SCHEMA_V2,
  CATALOG_DETAIL_SCHEMA_V2,
  CATALOG_SEARCH_SCHEMA_V2,
  CORE_FIELDS_V2,
  DETAIL_FIELDS_V2,
  SEARCH_FIELDS_V2,
  hydrateCatalogRecord,
  parseBrowserCatalog,
  parseCatalogDetailIndex,
  parseCatalogDetailShard,
  parseCatalogSearchIndex
} from "../docs/js/catalog-data.js";
import {
  COLLECTION_MANIFEST_SCHEMA,
  collectionConfigUnknownFields,
  collectionDataUrl,
  parseCollectionManifest
} from "../docs/js/collections.js";

const GENERATED_AT = "2026-08-01T17:30:00Z";
const HASH_A = `sha256:${"a".repeat(64)}`;
const HASH_B = `sha256:${"b".repeat(64)}`;
const HASH_C = `sha256:${"c".repeat(64)}`;

function manifestFixture() {
  return {
    schema: COLLECTION_MANIFEST_SCHEMA,
    id: "jefferson",
    copy: {
      name: "Thomas Jefferson's Library",
      short_name: "Jefferson",
      institution: "Library of Congress",
      status_label: "Catalog beta",
      introduction: "Explore the current catalog evidence.",
      coverage_statement: "2,748 catalog instances are not 4,931 Sowerby entries.",
      source_label: "Library of Congress catalog"
    },
    data: {
      core: "catalog-core.json",
      search: "catalog-search.json",
      detail_template: "catalog-details/{shard}.json",
      detail_index: "catalog-details/index.json",
      hierarchy: "hierarchy.json",
      featured: "featured_items.json",
      public_media: "media-public.json",
      validation: "validation.json",
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
      storage_key: "shelfsignals_shelf:jefferson",
      receipt_name: "ShelfSignals Jefferson Receipt.json"
    },
    facets: ["classes", "materials", "decades", "evidence_status"],
    orders: [
      { id: "title", label: "Title" },
      { id: "lc", label: "Modern LC classification" }
    ],
    defaults: { corpus: "catalog", order: "title" },
    review: {
      enabled: true,
      code_sha256: HASH_C,
      session_key: "shelfsignals_review:jefferson",
      warning: "Review mode—not access controlled"
    }
  };
}

function sourceFixture(overrides = {}) {
  return {
    collection_id: "jefferson",
    catalog: "Library of Congress catalog",
    dataset: "loc_catalog_instances.jsonl",
    dataset_sha256: HASH_A,
    record_count: 2,
    id_set_sha256: HASH_B,
    ...overrides
  };
}

function coreRow(id, titleOrder, overrides = {}) {
  const values = {
    id,
    entity_type: "catalog_instance",
    title: `Catalog title ${titleOrder}`,
    authors: ["Primary creator"],
    year: "1815",
    call_number: "E332 .A1",
    material_type: "Book",
    formats: ["text"],
    record_url: titleOrder === 0 ? "https://catalog.loc.gov/record/one" : "",
    facets: { lc: ["E"], material: ["Book"], decade: [1810] },
    orders: { title: titleOrder, lc: titleOrder, sowerby: titleOrder === 0 ? 123 : null },
    evidence_status: titleOrder === 0 ? "sowerby_510_exact_bounded" : "collection_heading_only",
    detail_shard: 0,
    ...overrides
  };
  return CORE_FIELDS_V2.map(field => values[field]);
}

function catalogFixture() {
  return {
    schema: BROWSER_CATALOG_SCHEMA_V2,
    generated_at: GENERATED_AT,
    source: sourceFixture(),
    contract: {
      core_fields: [...CORE_FIELDS_V2],
      detail_fields: [...DETAIL_FIELDS_V2],
      detail_shard_count: 1,
      detail_path_template: "catalog-details/{shard}.json",
      search_path: "catalog-search.json"
    },
    items: [coreRow("jefferson-loc-one", 0), coreRow("jefferson-loc-two", 1)]
  };
}

function detailValues(id, position, { linked = false } = {}) {
  const evidence = status => ({ status, assertion: status, source: "Library of Congress catalog" });
  return {
    id,
    entity_type: "catalog_instance",
    full_title: `The complete catalog title for record ${position}`,
    alternative_titles: ["Alternate title"],
    contributors: [{ name: "Primary creator", primary: true }],
    publication: [{ date: "1815", place: "Washington", publisher: "Congress" }],
    languages: ["eng"],
    subjects: ["Libraries"],
    classifications: [{ source: "instance_classification", type_id: "lc", value: "E332" }],
    modern_call_numbers: [{ source: "item_effective_call_number", type_id: "lc", value: "E332 .A1" }],
    holdings: [{ id: `holding-${position}`, hrid: `ho${position}`, permanent_location: "Rare Book Reading Room", discovery_suppress: false }],
    items: [{
      id: `item-${position}`, hrid: `it${position}`, call_number: "E332 .A1", effective_location: "Rare Book Reading Room",
      material_type: "Book", status: "Available", discovery_suppress: false
    }],
    identifiers: [{ type: "lccn", value: `lccn-${position}` }],
    lccns: [`lccn-${position}`],
    record_url: `https://catalog.loc.gov/record/${position}`,
    relationship_to_jefferson: "collection_membership_only",
    ownership_or_reconstruction_status: "unresolved",
    sowerby_numbers: linked ? [123] : [],
    sowerby_evidence: linked ? [{
      sowerby_number: 123,
      status: "one_candidate_in_bounded_marc_sample",
      method: "marc_510_exact",
      evidence: "MARC 510",
      assessment_scope: {
        selected_catalog_entity_count: 2748,
        evidence_eligible_catalog_entity_count: 25,
        catalog_entities_not_assessed: 2723
      }
    }] : [],
    field_evidence: {
      collection_membership: evidence("exact_collection_heading_membership"),
      ownership_or_reconstruction_status: evidence("unresolved"),
      sowerby_link: evidence(linked ? "established_in_bounded_marc_sample" : "not_established_in_bounded_marc_sample")
    },
    source: {
      authority: "Library of Congress",
      catalog_entity_id: `loc:instance:${position}`,
      record_sha256: HASH_C,
      source_position: position
    }
  };
}

function detailRow(id, position, options) {
  const values = detailValues(id, position, options);
  return DETAIL_FIELDS_V2.map(field => values[field]);
}

function detailFixture() {
  return {
    schema: CATALOG_DETAIL_SCHEMA_V2,
    generated_at: GENERATED_AT,
    source: sourceFixture(),
    shard: 0,
    shard_count: 1,
    item_count: 2,
    fields: [...DETAIL_FIELDS_V2],
    items: [detailRow("jefferson-loc-one", 1, { linked: true }), detailRow("jefferson-loc-two", 2)]
  };
}

test("collection manifest validates copy, capabilities, coverage, storage, review, and relative data paths", () => {
  const raw = manifestFixture();
  const parsed = parseCollectionManifest(raw, { expectedId: "jefferson" });
  assert.equal(parsed.rejected, false);
  assert.notEqual(parsed.manifest, raw);
  assert.equal(parsed.manifest.copy.status_label, "Catalog beta");
  assert.equal(
    collectionDataUrl(parsed.manifest, "detail_template", "https://example.org/data/collections/jefferson/manifest.json", { shard: 7 }).href,
    "https://example.org/data/collections/jefferson/catalog-details/007.json"
  );
  assert.deepEqual(collectionConfigUnknownFields({ data: { core: "ok", surprise: "x" }, features: { placement: false, magic: true } }), {
    data: ["surprise"],
    features: ["magic"]
  });

  const canonicalOrder = manifestFixture();
  canonicalOrder.orders = [{ id: "catalog", label: "Catalog order" }];
  canonicalOrder.defaults.order = "catalog";
  assert.equal(parseCollectionManifest(canonicalOrder).rejected, false);
});

test("collection manifest fails closed on unknown fields, unsafe paths, cross-collection state, and undeclared defaults", () => {
  const unknown = manifestFixture();
  unknown.features.magic = true;
  unknown.data.extra = "extra.json";
  assert.equal(parseCollectionManifest(unknown).rejected, true);

  const unsafe = manifestFixture();
  unsafe.data.core = "../private.json";
  unsafe.data.search = "https://evil.example/catalog.json";
  assert.equal(parseCollectionManifest(unsafe).rejected, true);

  const stateLeak = manifestFixture();
  stateLeak.shelf.storage_key = "shelfsignals_shelf";
  stateLeak.review.session_key = "shelfsignals_review:sekula";
  stateLeak.defaults.order = "sowerby";
  assert.equal(parseCollectionManifest(stateLeak, { expectedId: "jefferson" }).rejected, true);

  const missingAsset = manifestFixture();
  delete missingAsset.data.hierarchy;
  assert.equal(parseCollectionManifest(missingAsset).rejected, true);
});

test("version-2 core parses collection-neutral fields without changing version-1 behavior", () => {
  const parsed = parseBrowserCatalog(catalogFixture(), { collectionId: "jefferson" });
  assert.equal(parsed.rejected, false);
  assert.equal(parsed.records.length, 2);
  assert.equal(parsed.records[0].entity_type, "catalog_instance");
  assert.deepEqual(parsed.records[0].facets, { lc: ["E"], material: ["Book"], decade: [1810] });
  assert.equal(parsed.records[0].orders.sowerby, 123);
  assert.equal(parsed.records[1].record_url, "");
  assert.equal(parsed.records[0].detail_hydrated, false);
});

test("version-2 core rejects unknown contracts, wrong collections, duplicate IDs, unsafe URLs, and wrong shards", () => {
  const wrongCollection = catalogFixture();
  assert.equal(parseBrowserCatalog(wrongCollection, { collectionId: "sekula" }).rejected, true);

  const unknown = catalogFixture();
  unknown.contract.extra = true;
  unknown.source.extra = true;
  assert.equal(parseBrowserCatalog(unknown, { collectionId: "jefferson" }).rejected, true);

  const duplicate = catalogFixture();
  duplicate.items[1][0] = duplicate.items[0][0];
  assert.equal(parseBrowserCatalog(duplicate, { collectionId: "jefferson" }).rejected, true);

  const unsafeUrl = catalogFixture();
  unsafeUrl.items[0][CORE_FIELDS_V2.indexOf("record_url")] = "javascript:alert(1)";
  assert.equal(parseBrowserCatalog(unsafeUrl, { collectionId: "jefferson" }).rejected, true);

  const wrongShard = catalogFixture();
  wrongShard.contract.detail_shard_count = 2;
  wrongShard.items[0][CORE_FIELDS_V2.indexOf("detail_shard")] = 1;
  assert.equal(parseBrowserCatalog(wrongShard, { collectionId: "jefferson" }).rejected, true);
});

test("version-2 lazy search requires complete coverage and exact core source identity", () => {
  const core = parseBrowserCatalog(catalogFixture(), { collectionId: "jefferson" });
  const catalogIds = new Set(core.records.map(record => record.id));
  const search = {
    schema: CATALOG_SEARCH_SCHEMA_V2,
    generated_at: GENERATED_AT,
    source: sourceFixture(),
    fields: [...SEARCH_FIELDS_V2],
    items: [["jefferson-loc-one", "first searchable text"], ["jefferson-loc-two", "second searchable text"]]
  };
  const parsed = parseCatalogSearchIndex(search, { catalogIds, catalogSource: core.source });
  assert.equal(parsed.rejected, false);
  assert.equal(parsed.searchById.get("jefferson-loc-two"), "second searchable text");

  const duplicate = structuredClone(search);
  duplicate.items[1][0] = duplicate.items[0][0];
  assert.equal(parseCatalogSearchIndex(duplicate, { catalogIds, catalogSource: core.source }).rejected, true);

  const wrongSource = structuredClone(search);
  wrongSource.source.catalog = "Different catalog";
  assert.equal(parseCatalogSearchIndex(wrongSource, { catalogIds, catalogSource: core.source }).rejected, true);
  assert.equal(parseCatalogSearchIndex(search, { catalogIds }).rejected, true, "collection expectation is mandatory for @2");
});

test("version-2 details are contract-declared, source-bound, shard-bound, and hydrate the catalog record", () => {
  const core = parseBrowserCatalog(catalogFixture(), { collectionId: "jefferson" });
  const catalogIds = new Set(core.records.map(record => record.id));
  const detail = detailFixture();
  const parsed = parseCatalogDetailShard(detail, {
    catalogIds,
    catalogSource: core.source,
    expectedShard: 0
  });
  assert.equal(parsed.rejected, false, JSON.stringify(parsed.errors));
  const target = core.records[0];
  hydrateCatalogRecord(target, parsed.detailsById.get(target.id));
  assert.equal(target.detail_hydrated, true);
  assert.equal(target.title, "The complete catalog title for record 1");
  assert.equal(target.full_title, "The complete catalog title for record 1");
  assert.equal(target.sowerby_numbers[0], 123);
  assert.equal(target.holdings[0].permanent_location, "Rare Book Reading Room");
  assert.equal(target.field_evidence.sowerby_link.status, "established_in_bounded_marc_sample");

  const changedContract = structuredClone(detail);
  changedContract.fields[2] = "unknown_detail";
  assert.equal(parseCatalogDetailShard(changedContract, { catalogIds, catalogSource: core.source, expectedShard: 0 }).rejected, true);

  const missingFullTitle = structuredClone(detail);
  missingFullTitle.items[0][DETAIL_FIELDS_V2.indexOf("full_title")] = "";
  assert.equal(parseCatalogDetailShard(missingFullTitle, { catalogIds, catalogSource: core.source, expectedShard: 0 }).rejected, true);

  const unknownNested = structuredClone(detail);
  unknownNested.items[0][DETAIL_FIELDS_V2.indexOf("holdings")][0].barcode = "private";
  assert.equal(parseCatalogDetailShard(unknownNested, { catalogIds, catalogSource: core.source, expectedShard: 0 }).rejected, true);

  const duplicate = structuredClone(detail);
  duplicate.items[1] = structuredClone(duplicate.items[0]);
  assert.equal(parseCatalogDetailShard(duplicate, { catalogIds, catalogSource: core.source, expectedShard: 0 }).rejected, true);
});

test("version-2 detail index rejects duplicate, missing, and wrong-source shard declarations", () => {
  const core = parseBrowserCatalog(catalogFixture(), { collectionId: "jefferson" });
  const catalogIds = new Set(core.records.map(record => record.id));
  const index = {
    schema: CATALOG_DETAIL_INDEX_SCHEMA_V2,
    generated_at: GENERATED_AT,
    source: sourceFixture(),
    shard_count: 1,
    fields: [...DETAIL_FIELDS_V2],
    shards: [{ shard: 0, file: "000.json", item_count: 2, bytes: 1234, sha256: HASH_C }]
  };
  assert.equal(parseCatalogDetailIndex(index, { catalogIds, catalogSource: core.source, expectedShardCount: 1 }).rejected, false);

  const duplicate = structuredClone(index);
  duplicate.shards.push(structuredClone(duplicate.shards[0]));
  assert.equal(parseCatalogDetailIndex(duplicate, { catalogIds, catalogSource: core.source, expectedShardCount: 1 }).rejected, true);

  const wrongSource = structuredClone(index);
  wrongSource.source.dataset = "different.jsonl";
  assert.equal(parseCatalogDetailIndex(wrongSource, { catalogIds, catalogSource: core.source, expectedShardCount: 1 }).rejected, true);
});
