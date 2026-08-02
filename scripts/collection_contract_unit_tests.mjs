import assert from "node:assert/strict";
import test from "node:test";

import {
  BROWSER_CATALOG_SCHEMA_V2,
  CATALOG_DETAIL_INDEX_SCHEMA_V2,
  CATALOG_DETAIL_SCHEMA_V2,
  CATALOG_SEARCH_SCHEMA_V2,
  CORE_FIELDS_V2,
  DETAIL_FIELDS_V2,
  HISTORICAL_CATALOG_SCHEMA,
  HISTORICAL_CORE_FIELDS,
  HISTORICAL_DETAIL_FIELDS,
  HISTORICAL_DETAIL_INDEX_SCHEMA,
  HISTORICAL_DETAIL_SCHEMA,
  HISTORICAL_SEARCH_FIELDS,
  HISTORICAL_SEARCH_SCHEMA,
  SEARCH_FIELDS_V2,
  hydrateCatalogRecord,
  parseBrowserCatalog,
  parseCatalogDetailIndex,
  parseCatalogDetailShard,
  parseCatalogSearchIndex
} from "../docs/js/catalog-data.js";
import {
  COLLECTION_MANIFEST_SCHEMA,
  COLLECTION_MANIFEST_SCHEMA_V2,
  collectionCorpusOptions,
  collectionConfigUnknownFields,
  collectionDataUrl,
  parseCollectionManifest,
  resolveCollectionCorpusForState
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

function dualCorpusManifestFixture({ defaultCorpus = "catalog" } = {}) {
  const legacy = manifestFixture();
  const catalog = {
    id: "catalog",
    label: "Current LOC catalog",
    record_id_prefix: "jefferson-loc-",
    copy: {
      status_label: legacy.copy.status_label,
      introduction: legacy.copy.introduction,
      coverage_statement: legacy.copy.coverage_statement,
      source_label: legacy.copy.source_label
    },
    coverage: {
      ...structuredClone(legacy.coverage),
      historical_entry_count: 4928,
      historical_position_count: 4931
    },
    data: Object.fromEntries(Object.entries(legacy.data).filter(([field]) => field !== "hierarchy")),
    features: structuredClone(legacy.features),
    facets: [...legacy.facets],
    orders: structuredClone(legacy.orders),
    default_order: "title"
  };
  const historical = {
    id: "historical",
    label: "Historical Sowerby corpus",
    record_id_prefix: "jefferson-sowerby-",
    copy: {
      status_label: "Historical corpus",
      introduction: "Explore source-backed Sowerby entries in historical catalog order.",
      coverage_statement: "Source-backed entries remain distinct from modern catalog and custodial entities.",
      source_label: "Library of Congress Sowerby scans"
    },
    coverage: {
      status: "beta",
      entity_type: "sowerby_entry",
      record_count: 3,
      historical_entry_count: 4928,
      historical_position_count: 4931,
      historical_volume_count: 6487,
      established_sowerby_links: 0
    },
    data: {
      core: "historical/catalog-core.json",
      search: "historical/catalog-search.json",
      detail_template: "historical/catalog-details/{shard}.json",
      detail_index: "historical/catalog-details/index.json",
      validation: "historical/validation.json"
    },
    features: {
      ...structuredClone(legacy.features),
      digital_surrogates: false
    },
    facets: ["materials", "decades", "evidence_status"],
    orders: [
      { id: "sowerby", label: "Sowerby order" },
      { id: "title", label: "Title" }
    ],
    default_order: "sowerby"
  };
  const selected = defaultCorpus === "historical" ? historical : catalog;
  return {
    ...legacy,
    schema: COLLECTION_MANIFEST_SCHEMA_V2,
    copy: {
      ...legacy.copy,
      ...selected.copy
    },
    coverage: structuredClone(selected.coverage),
    data: {
      ...structuredClone(selected.data),
      hierarchy: legacy.data.hierarchy
    },
    features: structuredClone(selected.features),
    facets: [...selected.facets],
    orders: structuredClone(selected.orders),
    defaults: { corpus: defaultCorpus, order: selected.default_order },
    corpora: [catalog, historical]
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

function historicalSourceFixture(overrides = {}) {
  return {
    collection_id: "jefferson",
    corpus_id: "historical",
    authority: "Library of Congress",
    publication_basis: "loc_scan_ocr_factual_extraction",
    rights_statement_url: "https://www.loc.gov/item/52060000/",
    rights_statement_sha256: HASH_C,
    dataset: "loc_sowerby_scan_ocr.jsonl",
    dataset_sha256: HASH_A,
    record_count: 3,
    id_set_sha256: HASH_B,
    ...overrides
  };
}

function historicalCoreRow(identifier, sowerbyOrder, titleOrder) {
  const values = {
    id: `jefferson-sowerby-${identifier}`,
    entity_type: "sowerby_entry",
    sowerby_identifier: identifier,
    title: `Historical title ${identifier}`,
    title_status: "source_backed",
    creators: ["Source-backed creator"],
    date: "1815",
    material_type: "Book",
    formats: ["text"],
    source_url: "https://www.loc.gov/item/52060000/",
    faculty: "Philosophy",
    chapter_number: 24,
    chapter_label: "Politics",
    orders: { sowerby: sowerbyOrder, title: titleOrder },
    evidence_status: identifier === "3259a" ? "sowerby_entry_aggregate_spine" : "sowerby_entry_page_resolved",
    detail_shard: 0
  };
  return HISTORICAL_CORE_FIELDS.map(field => values[field]);
}

function historicalCatalogFixture() {
  return {
    schema: HISTORICAL_CATALOG_SCHEMA,
    generated_at: GENERATED_AT,
    source: historicalSourceFixture(),
    numbering: {
      max_source_serial: 4931,
      source_backed_entry_count: 3,
      gaps: ["2323", "4707", "4708"].map(identifier => ({
        identifier,
        status: "source_number_absent",
        evidence: `LOC-confirmed non-book source-number gap ${identifier}.`,
        source_url: "https://www.loc.gov/item/52060000/"
      }))
    },
    contract: {
      core_fields: [...HISTORICAL_CORE_FIELDS],
      detail_fields: [...HISTORICAL_DETAIL_FIELDS],
      detail_shard_count: 1,
      detail_path_template: "historical/catalog-details/{shard}.json",
      search_path: "historical/catalog-search.json",
      record_id_prefix: "jefferson-sowerby-"
    },
    items: [
      historicalCoreRow("3259", 0, 1),
      historicalCoreRow("3259a", 1, 0),
      historicalCoreRow("3260", 2, 2)
    ]
  };
}

function historicalDetailValues(identifier, position) {
  const sourceUrl = identifier === "3259"
    ? "https://tile.loc.gov/storage-services/service/rbc/fixture.pdf#page=42"
    : "https://www.loc.gov/item/52060000/";
  const assertion = (field, value) => ({
    field,
    status: "source_backed",
    value,
    source: "Library of Congress Sowerby scan",
    source_url: sourceUrl,
    evidence_sha256: HASH_C,
    as_of: "2026-08-01"
  });
  return {
    id: `jefferson-sowerby-${identifier}`,
    entity_type: "sowerby_entry",
    sowerby_identifier: identifier,
    full_title: `Complete historical title ${identifier}`,
    title_status: "source_backed",
    alternative_titles: [],
    creators: ["Source-backed creator"],
    contributors: [{ name: "Source-backed creator", role: "author", primary: true }],
    publication: { date: "1815", places: ["Washington"], publishers: ["Congress"] },
    languages: ["eng"],
    subjects: ["Politics"],
    formats: ["text"],
    material_type: "Book",
    faculty: "Philosophy",
    chapter_number: 24,
    chapter_label: "Politics",
    source_url: sourceUrl,
    relationship_to_jefferson: "historical_catalog_membership",
    ownership_or_reconstruction_status: "not_established",
    links: {
      catalog_instances: [], editions: [], volumes: [], physical_copies: [], holdings: [], digital_objects: []
    },
    assertions: [
      assertion("title", `Complete historical title ${identifier}`),
      assertion("historical_catalog_membership", identifier),
      assertion("historical_chapter", "24"),
      assertion("historical_sequence", identifier)
    ],
    source: {
      authority: "Library of Congress",
      publication_basis: "loc_scan_ocr_factual_extraction",
      rights_statement_url: "https://www.loc.gov/item/52060000/",
      rights_statement_sha256: HASH_C,
      sowerby_identifier: identifier,
      source_url: sourceUrl,
      record_sha256: HASH_C,
      source_position: position
    }
  };
}

function historicalDetailRow(identifier, position) {
  const values = historicalDetailValues(identifier, position);
  return HISTORICAL_DETAIL_FIELDS.map(field => values[field]);
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

test("version-2 collection manifest routes disjoint catalog and historical packages", () => {
  const raw = dualCorpusManifestFixture();
  const parsed = parseCollectionManifest(raw, { expectedId: "jefferson" });
  assert.equal(parsed.rejected, false, JSON.stringify(parsed.errors));
  assert.deepEqual(collectionCorpusOptions(parsed.manifest).map(corpus => corpus.id), ["catalog", "historical"]);
  const manifestUrl = "https://example.org/data/collections/jefferson/manifest.json";
  assert.equal(
    collectionDataUrl(parsed.manifest, "core", manifestUrl, { corpus: "historical" }).href,
    "https://example.org/data/collections/jefferson/historical/catalog-core.json"
  );
  assert.equal(
    collectionDataUrl(parsed.manifest, "detail_template", manifestUrl, { corpus: "historical", shard: 7 }).href,
    "https://example.org/data/collections/jefferson/historical/catalog-details/007.json"
  );
  assert.equal(
    collectionDataUrl(parsed.manifest, "validation", manifestUrl, { corpus: "catalog" }).href,
    "https://example.org/data/collections/jefferson/validation.json"
  );
  assert.equal(
    collectionDataUrl(parsed.manifest, "hierarchy", manifestUrl, { corpus: "historical" }).href,
    "https://example.org/data/collections/jefferson/hierarchy.json",
    "the historical hierarchy remains a shared collection-level source"
  );
});

test("version-2 manifest permits a historical default only when its complete package is declared", () => {
  const historicalDefault = dualCorpusManifestFixture({ defaultCorpus: "historical" });
  const parsed = parseCollectionManifest(historicalDefault, { expectedId: "jefferson" });
  assert.equal(parsed.rejected, false, JSON.stringify(parsed.errors));
  assert.equal(parsed.manifest.defaults.order, "sowerby");
  assert.equal(parsed.manifest.coverage.entity_type, "sowerby_entry");

  const missingValidation = dualCorpusManifestFixture({ defaultCorpus: "historical" });
  delete missingValidation.corpora[1].data.validation;
  assert.equal(parseCollectionManifest(missingValidation).rejected, true);

  const undeclaredDefault = dualCorpusManifestFixture();
  undeclaredDefault.defaults.corpus = "historical";
  assert.equal(parseCollectionManifest(undeclaredDefault).rejected, true, "top-level defaults cannot flip without mirroring a real package");
});

test("version-2 manifest rejects corpus path collisions, prefix overlap, and copy or coverage drift", () => {
  for (const malformedCorpora of [{}, "catalog", null]) {
    const malformed = dualCorpusManifestFixture();
    malformed.corpora = malformedCorpora;
    assert.doesNotThrow(() => parseCollectionManifest(malformed));
    assert.equal(parseCollectionManifest(malformed).rejected, true);
  }

  const duplicatePath = dualCorpusManifestFixture();
  duplicatePath.corpora[1].data.validation = duplicatePath.corpora[0].data.validation;
  assert.equal(parseCollectionManifest(duplicatePath).rejected, true);

  const overlappingPrefix = dualCorpusManifestFixture();
  overlappingPrefix.corpora[1].record_id_prefix = "jefferson-loc-history-";
  assert.equal(parseCollectionManifest(overlappingPrefix).rejected, true);

  const driftedCoverage = dualCorpusManifestFixture();
  driftedCoverage.corpora[0].coverage.record_count = 2747;
  assert.equal(parseCollectionManifest(driftedCoverage).rejected, true);

  const legacyWithCorpora = manifestFixture();
  legacyWithCorpora.corpora = dualCorpusManifestFixture().corpora;
  assert.equal(parseCollectionManifest(legacyWithCorpora).rejected, true, "@1 remains unchanged and cannot opt into partial corpus semantics");
});

test("legacy record prefixes infer a corpus only when the URL did not declare one", () => {
  const parsed = parseCollectionManifest(dualCorpusManifestFixture({ defaultCorpus: "historical" }));
  assert.equal(parsed.rejected, false);
  assert.equal(resolveCollectionCorpusForState(parsed.manifest, { recordId: "jefferson-loc-one" }).id, "catalog");
  assert.equal(resolveCollectionCorpusForState(parsed.manifest, { recordId: "jefferson-sowerby-3259a" }).id, "historical");
  assert.equal(resolveCollectionCorpusForState(parsed.manifest, {
    requestedCorpus: "historical",
    recordId: "jefferson-loc-one"
  }).id, "historical", "an explicit corpus is never silently changed to fit a foreign record ID");
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

test("historical core is corpus-bound, suffix-safe, and explicit about source-numbering gaps", () => {
  const raw = historicalCatalogFixture();
  const options = {
    collectionId: "jefferson",
    corpusId: "historical",
    entityType: "sowerby_entry",
    recordIdPrefix: "jefferson-sowerby-",
    detailPathTemplate: "historical/catalog-details/{shard}.json",
    searchPath: "historical/catalog-search.json"
  };
  const parsed = parseBrowserCatalog(raw, options);
  assert.equal(parsed.rejected, false, JSON.stringify(parsed.errors));
  assert.deepEqual(parsed.records.map(record => record.sowerby_identifier), ["3259", "3259a", "3260"]);
  assert.deepEqual(parsed.records.map(record => record.orders.sowerby), [0, 1, 2]);
  assert.deepEqual(parsed.records.map(record => record.evidence_status), [
    "sowerby_entry_page_resolved",
    "sowerby_entry_aggregate_spine",
    "sowerby_entry_page_resolved"
  ]);
  assert.equal(parsed.numbering.gaps[0].identifier, "2323");

  const unresolvedTitle = structuredClone(raw);
  unresolvedTitle.items[0][HISTORICAL_CORE_FIELDS.indexOf("title")] = "";
  unresolvedTitle.items[0][HISTORICAL_CORE_FIELDS.indexOf("title_status")] = "not_established";
  const unresolvedParsed = parseBrowserCatalog(unresolvedTitle, options);
  assert.equal(unresolvedParsed.rejected, false, JSON.stringify(unresolvedParsed.errors));
  assert.equal(unresolvedParsed.records[0].title, "Sowerby entry 3259 — title not established");

  assert.equal(parseBrowserCatalog(raw, { ...options, corpusId: "catalog" }).rejected, true);
  assert.equal(parseBrowserCatalog(raw, { ...options, recordIdPrefix: "jefferson-loc-" }).rejected, true);

  const inventedGap = structuredClone(raw);
  inventedGap.items[0][HISTORICAL_CORE_FIELDS.indexOf("id")] = "jefferson-sowerby-2323";
  inventedGap.items[0][HISTORICAL_CORE_FIELDS.indexOf("sowerby_identifier")] = "2323";
  assert.equal(parseBrowserCatalog(inventedGap, options).rejected, true, "an editorial numbering gap cannot masquerade as a source-backed entry");

  const officialTile = structuredClone(raw);
  officialTile.items[0][HISTORICAL_CORE_FIELDS.indexOf("source_url")] = "https://tile.loc.gov/storage-services/service/rbc/fixture.pdf#page=42";
  assert.equal(parseBrowserCatalog(officialTile, options).rejected, false, "official tile.loc.gov scan URLs must remain inspectable");

  const lookalikeHost = structuredClone(raw);
  lookalikeHost.items[0][HISTORICAL_CORE_FIELDS.indexOf("source_url")] = "https://tile.loc.gov.example/fixture.pdf";
  assert.equal(parseBrowserCatalog(lookalikeHost, options).rejected, true, "lookalike LOC hostnames must fail closed");

  const restrictedBasis = structuredClone(raw);
  restrictedBasis.source.authority = "Thomas Jefferson Foundation";
  restrictedBasis.source.publication_basis = "monticello_transcript";
  restrictedBasis.source.dataset = "monticello_transcript.json";
  assert.equal(parseBrowserCatalog(restrictedBasis, options).rejected, true, "restricted research transcripts cannot become the public publication source");

  const collapsedEvidence = structuredClone(raw);
  collapsedEvidence.items[0][HISTORICAL_CORE_FIELDS.indexOf("evidence_status")] = "sowerby_entry_source_backed";
  assert.equal(parseBrowserCatalog(collapsedEvidence, options).rejected, true, "historical evidence levels cannot collapse to one generic source-backed state");
});

test("historical search, details, and index reject cross-corpus source identity", () => {
  const options = {
    collectionId: "jefferson",
    corpusId: "historical",
    entityType: "sowerby_entry",
    recordIdPrefix: "jefferson-sowerby-",
    detailPathTemplate: "historical/catalog-details/{shard}.json",
    searchPath: "historical/catalog-search.json"
  };
  const core = parseBrowserCatalog(historicalCatalogFixture(), options);
  assert.equal(core.rejected, false, JSON.stringify(core.errors));
  const catalogIds = new Set(core.records.map(record => record.id));
  const sharedOptions = { ...options, catalogIds, catalogSource: core.source, datasetSha256: core.source.dataset_sha256 };
  const search = {
    schema: HISTORICAL_SEARCH_SCHEMA,
    generated_at: GENERATED_AT,
    source: historicalSourceFixture(),
    fields: [...HISTORICAL_SEARCH_FIELDS],
    items: [
      ["jefferson-sowerby-3259", "historical searchable text 3259"],
      ["jefferson-sowerby-3259a", "historical searchable text 3259a"],
      ["jefferson-sowerby-3260", "historical searchable text 3260"]
    ]
  };
  assert.equal(parseCatalogSearchIndex(search, sharedOptions).rejected, false);
  const wrongSearchSource = structuredClone(search);
  wrongSearchSource.source.corpus_id = "catalog";
  assert.equal(parseCatalogSearchIndex(wrongSearchSource, sharedOptions).rejected, true);

  const detail = {
    schema: HISTORICAL_DETAIL_SCHEMA,
    generated_at: GENERATED_AT,
    source: historicalSourceFixture(),
    shard: 0,
    shard_count: 1,
    item_count: 3,
    fields: [...HISTORICAL_DETAIL_FIELDS],
    items: [historicalDetailRow("3259", 1), historicalDetailRow("3259a", 2), historicalDetailRow("3260", 3)]
  };
  const parsedDetail = parseCatalogDetailShard(detail, { ...sharedOptions, expectedShard: 0 });
  assert.equal(parsedDetail.rejected, false, JSON.stringify(parsedDetail.errors));
  const target = core.records[1];
  hydrateCatalogRecord(target, parsedDetail.detailsById.get(target.id));
  assert.equal(target.entity_type, "sowerby_entry");
  assert.equal(target.sowerby_identifier, "3259a");
  assert.equal(target.title, "Complete historical title 3259a");
  assert.equal(target.ownership_or_reconstruction_status, "not_established");
  assert.equal(target.historical_assertions.length, 4);

  const unresolvedDetail = structuredClone(detail);
  unresolvedDetail.items[0][HISTORICAL_DETAIL_FIELDS.indexOf("full_title")] = "";
  unresolvedDetail.items[0][HISTORICAL_DETAIL_FIELDS.indexOf("title_status")] = "not_established";
  const unresolvedAssertions = unresolvedDetail.items[0][HISTORICAL_DETAIL_FIELDS.indexOf("assertions")];
  const titleAssertion = unresolvedAssertions.find(assertion => assertion.field === "title");
  titleAssertion.status = "not_established";
  titleAssertion.value = "";
  assert.equal(parseCatalogDetailShard(unresolvedDetail, { ...sharedOptions, expectedShard: 0 }).rejected, false);

  const missingAssertionEvidence = structuredClone(detail);
  delete missingAssertionEvidence.items[0][HISTORICAL_DETAIL_FIELDS.indexOf("assertions")][0].evidence_sha256;
  assert.equal(parseCatalogDetailShard(missingAssertionEvidence, { ...sharedOptions, expectedShard: 0 }).rejected, true);
  const foreignAssertionSource = structuredClone(detail);
  foreignAssertionSource.items[0][HISTORICAL_DETAIL_FIELDS.indexOf("assertions")][0].source_url = "https://example.org/not-loc";
  assert.equal(parseCatalogDetailShard(foreignAssertionSource, { ...sharedOptions, expectedShard: 0 }).rejected, true);

  const conflatedLink = structuredClone(detail);
  conflatedLink.items[0][HISTORICAL_DETAIL_FIELDS.indexOf("links")].physical_copies = ["jefferson-loc-one"];
  assert.equal(parseCatalogDetailShard(conflatedLink, { ...sharedOptions, expectedShard: 0 }).rejected, true);

  const index = {
    schema: HISTORICAL_DETAIL_INDEX_SCHEMA,
    generated_at: GENERATED_AT,
    source: historicalSourceFixture(),
    shard_count: 1,
    fields: [...HISTORICAL_DETAIL_FIELDS],
    shards: [{ shard: 0, file: "000.json", item_count: 3, bytes: 1234, sha256: HASH_C }]
  };
  assert.equal(parseCatalogDetailIndex(index, { ...sharedOptions, expectedShardCount: 1 }).rejected, false);
  const wrongIndex = structuredClone(index);
  wrongIndex.source.dataset_sha256 = HASH_C;
  assert.equal(parseCatalogDetailIndex(wrongIndex, { ...sharedOptions, expectedShardCount: 1 }).rejected, true);
});
