/**
 * Compact, fail-closed browser catalog contracts.
 *
 * `sekula_index.json` remains the canonical research dataset. The files read
 * here are deterministic projections: a small first-load catalog, a lazy
 * full-field search index, and record-detail shards. No displayed metadata is
 * invented by this module.
 */

// @ts-check

export const BROWSER_CATALOG_SCHEMA = "shelfsignals-browser-catalog@1";
export const CATALOG_SEARCH_SCHEMA = "shelfsignals-catalog-search@1";
export const CATALOG_DETAIL_SCHEMA = "shelfsignals-catalog-detail-shard@1";
export const CATALOG_DETAIL_INDEX_SCHEMA = "shelfsignals-catalog-detail-index@1";

export const CORE_FIELDS = Object.freeze([
  "id",
  "title",
  "authors",
  "year",
  "call_number",
  "material_type",
  "formats",
  "photo_insert_bucket",
  "photo_insert_score",
  "placements",
  "signals",
  "detail_shard"
]);

export const PLACEMENT_FIELDS = Object.freeze(["label", "key", "room_label", "room_key"]);
export const SEARCH_FIELDS = Object.freeze(["id", "search_text"]);
export const HOLDING_FIELDS = Object.freeze(["sub_location", "sub_location_code", "call_number", "availability_status"]);
export const DETAIL_FIELDS = Object.freeze([
  "id",
  "alma_mms",
  "source_record_id",
  "original_source_id",
  "source_system",
  "frbr_group_id",
  "uniform_title",
  "alternative_titles",
  "contributors",
  "languages",
  "identifiers",
  "publishers",
  "places",
  "series",
  "table_of_contents",
  "description",
  "notes",
  "provenance_notes",
  "sekula_notes",
  "subjects",
  "collection",
  "collection_tags",
  "call_number_notes",
  "availability",
  "best_location",
  "holdings",
  "isbns",
  "issns",
  "oclc_numbers",
  "lccn",
  "source"
]);

const ARRAY_DETAIL_FIELDS = new Set([
  "alternative_titles", "contributors", "languages", "identifiers", "publishers", "places", "series",
  "table_of_contents", "notes", "provenance_notes", "sekula_notes", "subjects", "collection_tags",
  "call_number_notes", "holdings", "isbns", "issns", "oclc_numbers", "lccn"
]);
const STRING_DETAIL_FIELDS = new Set(DETAIL_FIELDS.filter(field => field !== "id" && field !== "best_location" && !ARRAY_DETAIL_FIELDS.has(field)));
const SHA256 = /^sha256:[a-f0-9]{64}$/i;
const ISO_DATE = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?Z$/;
const SAFE_ID = /^[A-Za-z0-9._~-]+$/;

/** @typedef {{path: string, code: string, message: string}} CatalogIssue */

function isObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function cleanString(value) {
  return typeof value === "string" ? value.trim() : "";
}

function issue(path, code, message) {
  return { path, code, message };
}

function exactFields(value, expected) {
  return Array.isArray(value)
    && value.length === expected.length
    && value.every((entry, index) => entry === expected[index]);
}

function asCatalogIdSet(catalogIds) {
  return catalogIds instanceof Set
    ? catalogIds
    : new Set(Array.isArray(catalogIds) ? catalogIds.map(String) : []);
}

function validSource(source, { datasetSha256 = "", recordCount = 0 } = {}) {
  if (!isObject(source)) return false;
  if (source.catalog !== "Clark Library Catalog" || source.dataset !== "sekula_index.json") return false;
  if (!SHA256.test(cleanString(source.dataset_sha256)) || !SHA256.test(cleanString(source.id_set_sha256))) return false;
  if (!Number.isInteger(source.record_count) || source.record_count <= 0) return false;
  if (datasetSha256 && source.dataset_sha256 !== datasetSha256) return false;
  if (recordCount && source.record_count !== recordCount) return false;
  return true;
}

function safeCatalogTemplate(value) {
  const template = cleanString(value);
  if (!template || (template.match(/\{id\}/g) || []).length !== 1) return "";
  try {
    const url = new URL(template.replace("{id}", "alma1"));
    if (url.protocol !== "https:" || url.hostname !== "library.clarkart.edu") return "";
    if (!url.pathname.endsWith("/discovery/fulldisplay") || url.searchParams.get("docid") !== "alma1") return "";
    if (url.searchParams.get("context") !== "L" || url.searchParams.get("vid") !== "01CLARKART_INST:01CLARKART_INST_FRANCINE") return "";
    if (url.searchParams.get("lang") !== "en" || url.searchParams.get("tab") !== "LibraryCatalog") return "";
    return template;
  } catch (_) {
    return "";
  }
}

function catalogUrl(template, id) {
  return template.replace("{id}", encodeURIComponent(id));
}

function stringArray(value) {
  return Array.isArray(value) ? value.filter(entry => entry != null && entry !== "").map(String) : [];
}

function decodePlacement(value) {
  if (!Array.isArray(value) || value.length !== PLACEMENT_FIELDS.length) return null;
  const [label, key, roomLabel, roomKey] = value.map(cleanString);
  if (!label || !key) return null;
  return { label, key, roomLabel, roomKey };
}

function decodeHolding(value) {
  if (!Array.isArray(value) || value.length !== HOLDING_FIELDS.length) return null;
  const [subLocation, subLocationCode, callNumber, availabilityStatus] = value.map(entry => String(entry || ""));
  if (![subLocation, subLocationCode, callNumber, availabilityStatus].some(Boolean)) return null;
  return { subLocation, subLocationCode, callNumber, availabilityStatus };
}

function emptyDetails() {
  const details = {};
  for (const field of ARRAY_DETAIL_FIELDS) details[field] = [];
  for (const field of STRING_DETAIL_FIELDS) details[field] = "";
  details.best_location = null;
  return details;
}

/** FNV-1a, matching `stableHash` in visuals.js without importing UI code. */
export function stableCatalogShard(value = "", shardCount = 128) {
  let hash = 2166136261;
  for (const char of String(value)) {
    hash ^= char.codePointAt(0);
    hash = Math.imul(hash, 16777619);
  }
  const count = Number.isInteger(shardCount) && shardCount > 0 ? shardCount : 128;
  return (hash >>> 0) % count;
}

export function detailShardName(shard) {
  if (!Number.isInteger(shard) || shard < 0 || shard > 999) throw new TypeError("Detail shard must be an integer from 0 to 999");
  return `${String(shard).padStart(3, "0")}.json`;
}

/** Parse the compact first-load projection and reconstruct exact Clark URLs. */
export function parseBrowserCatalog(raw) {
  const errors = [];
  if (!isObject(raw) || raw.schema !== BROWSER_CATALOG_SCHEMA) errors.push(issue("schema", "schema", "Unsupported browser catalog schema"));
  if (!ISO_DATE.test(cleanString(raw?.generated_at))) errors.push(issue("generated_at", "date", "A UTC generation time is required"));
  if (!validSource(raw?.source)) errors.push(issue("source", "source", "Canonical source identity is invalid"));
  const template = safeCatalogTemplate(raw?.source?.record_url_template);
  if (!template) errors.push(issue("source.record_url_template", "url", "Clark record URL template is invalid"));
  if (!isObject(raw?.contract)) errors.push(issue("contract", "object", "Catalog contract is required"));
  if (!exactFields(raw?.contract?.core_fields, CORE_FIELDS)) errors.push(issue("contract.core_fields", "fields", "Core field order changed"));
  if (!exactFields(raw?.contract?.placement_fields, PLACEMENT_FIELDS)) errors.push(issue("contract.placement_fields", "fields", "Placement field order changed"));
  const shardCount = Number(raw?.contract?.detail_shard_count);
  if (!Number.isInteger(shardCount) || shardCount < 1 || shardCount > 1000) errors.push(issue("contract.detail_shard_count", "range", "Detail shard count is invalid"));
  if (!Array.isArray(raw?.items)) errors.push(issue("items", "array", "Catalog items must be an array"));
  if (errors.length) return { rejected: true, errors, source: null, records: [] };

  const records = [];
  const ids = new Set();
  raw.items.forEach((row, index) => {
    const path = `items[${index}]`;
    if (!Array.isArray(row) || row.length !== CORE_FIELDS.length) {
      errors.push(issue(path, "row", "Core row length is invalid"));
      return;
    }
    const [rawId, rawTitle, rawAuthors, rawYear, rawCallNumber, rawMaterial, rawFormats, rawPhotoBucket, rawPhotoScore, rawPlacements, rawSignals, rawShard] = row;
    const id = cleanString(rawId);
    const title = cleanString(rawTitle);
    if (!id || !SAFE_ID.test(id) || ids.has(id)) errors.push(issue(`${path}.id`, "id", "Record ID is missing, unsafe, or duplicated"));
    if (!title) errors.push(issue(`${path}.title`, "title", "Canonical title is required"));
    if (!Array.isArray(rawAuthors) || !Array.isArray(rawFormats)) errors.push(issue(path, "arrays", "Authors and formats must be arrays"));
    if (rawPhotoScore != null && !Number.isFinite(Number(rawPhotoScore))) errors.push(issue(`${path}.photo_insert_score`, "number", "Photo score must be numeric or null"));
    const placements = Array.isArray(rawPlacements) ? rawPlacements.map(decodePlacement) : [];
    if (!Array.isArray(rawPlacements) || placements.some(value => !value)) errors.push(issue(`${path}.placements`, "placement", "Placement projection is invalid"));
    const signals = stringArray(rawSignals);
    if (!Array.isArray(rawSignals) || signals.length !== rawSignals.length) errors.push(issue(`${path}.signals`, "signals", "Signal projection is invalid"));
    const detailShard = Number(rawShard);
    if (!Number.isInteger(detailShard) || detailShard < 0 || detailShard >= shardCount || stableCatalogShard(id, shardCount) !== detailShard) {
      errors.push(issue(`${path}.detail_shard`, "shard", "Record is assigned to the wrong detail shard"));
    }
    ids.add(id);
    records.push({
      ...emptyDetails(),
      id,
      title,
      authors: stringArray(rawAuthors),
      year: String(rawYear || ""),
      call_number: String(rawCallNumber || ""),
      material_type: String(rawMaterial || ""),
      formats: stringArray(rawFormats),
      photo_insert_bucket: String(rawPhotoBucket || ""),
      photo_insert_score: Number.isFinite(Number(rawPhotoScore)) ? Number(rawPhotoScore) : null,
      placements: placements.filter(Boolean),
      signals,
      detail_shard: detailShard,
      record_url: catalogUrl(template, id),
      catalogLink: catalogUrl(template, id),
      searchText: "",
      detail_hydrated: false
    });
  });

  if (records.length !== raw.source.record_count) errors.push(issue("items", "count", "Core record count does not match the canonical source"));
  if (errors.length) return { rejected: true, errors, source: null, records: [] };
  return {
    rejected: false,
    errors: [],
    source: { ...raw.source },
    generated_at: raw.generated_at,
    detailShardCount: shardCount,
    records
  };
}

/** Parse the full-field search projection. It is loaded only after a query. */
export function parseCatalogSearchIndex(raw, { datasetSha256 = "", catalogIds = [] } = {}) {
  const errors = [];
  const ids = asCatalogIdSet(catalogIds);
  if (!isObject(raw) || raw.schema !== CATALOG_SEARCH_SCHEMA) errors.push(issue("schema", "schema", "Unsupported search schema"));
  if (!ISO_DATE.test(cleanString(raw?.generated_at))) errors.push(issue("generated_at", "date", "A UTC generation time is required"));
  if (!validSource(raw?.source, { datasetSha256, recordCount: ids.size })) errors.push(issue("source", "source", "Search source identity does not match the catalog"));
  if (!exactFields(raw?.fields, SEARCH_FIELDS)) errors.push(issue("fields", "fields", "Search field order changed"));
  if (!Array.isArray(raw?.items)) errors.push(issue("items", "array", "Search items must be an array"));
  if (errors.length) return { rejected: true, errors, searchById: new Map() };

  const searchById = new Map();
  raw.items.forEach((row, index) => {
    if (!Array.isArray(row) || row.length !== SEARCH_FIELDS.length) {
      errors.push(issue(`items[${index}]`, "row", "Search row length is invalid"));
      return;
    }
    const id = cleanString(row[0]);
    const searchText = typeof row[1] === "string" ? row[1] : "";
    if (!ids.has(id) || searchById.has(id) || !searchText) errors.push(issue(`items[${index}]`, "record", "Search record is unknown, duplicated, or empty"));
    else searchById.set(id, searchText);
  });
  if (searchById.size !== ids.size) errors.push(issue("items", "count", "Search index does not cover the complete catalog"));
  return errors.length
    ? { rejected: true, errors, searchById: new Map() }
    : { rejected: false, errors: [], source: { ...raw.source }, searchById };
}

function decodeDetailRow(row, path, errors) {
  if (!Array.isArray(row) || row.length !== DETAIL_FIELDS.length) {
    errors.push(issue(path, "row", "Detail row length is invalid"));
    return null;
  }
  const detail = {};
  DETAIL_FIELDS.forEach((field, index) => {
    const value = row[index];
    if (field === "best_location") {
      detail[field] = value == null ? null : decodeHolding(value);
      if (value != null && !detail[field]) errors.push(issue(`${path}.${field}`, "holding", "Best location is invalid"));
    } else if (field === "holdings") {
      const decoded = Array.isArray(value) ? value.map(decodeHolding) : [];
      if (!Array.isArray(value) || decoded.some(entry => !entry)) errors.push(issue(`${path}.${field}`, "holdings", "Holdings are invalid"));
      detail[field] = decoded.filter(Boolean);
    } else if (ARRAY_DETAIL_FIELDS.has(field)) {
      if (!Array.isArray(value)) errors.push(issue(`${path}.${field}`, "array", "Detail field must be an array"));
      detail[field] = stringArray(value);
    } else {
      if (typeof value !== "string") errors.push(issue(`${path}.${field}`, "string", "Detail field must be a string"));
      detail[field] = String(value || "");
    }
  });
  return detail;
}

/** Parse one deterministic detail shard and reject cross-catalog content. */
export function parseCatalogDetailShard(raw, { datasetSha256 = "", catalogIds = [], expectedShard } = {}) {
  const errors = [];
  const ids = asCatalogIdSet(catalogIds);
  if (!isObject(raw) || raw.schema !== CATALOG_DETAIL_SCHEMA) errors.push(issue("schema", "schema", "Unsupported detail-shard schema"));
  if (!ISO_DATE.test(cleanString(raw?.generated_at))) errors.push(issue("generated_at", "date", "A UTC generation time is required"));
  if (!validSource(raw?.source, { datasetSha256, recordCount: ids.size })) errors.push(issue("source", "source", "Detail source identity does not match the catalog"));
  if (!exactFields(raw?.fields, DETAIL_FIELDS)) errors.push(issue("fields", "fields", "Detail field order changed"));
  if (!exactFields(raw?.holding_fields, HOLDING_FIELDS)) errors.push(issue("holding_fields", "fields", "Holding field order changed"));
  const shard = Number(raw?.shard);
  const shardCount = Number(raw?.shard_count);
  if (!Number.isInteger(shard) || !Number.isInteger(shardCount) || shard < 0 || shard >= shardCount || (Number.isInteger(expectedShard) && shard !== expectedShard)) {
    errors.push(issue("shard", "shard", "Detail shard identity is invalid"));
  }
  if (!Array.isArray(raw?.items)) errors.push(issue("items", "array", "Detail items must be an array"));
  if (errors.length) return { rejected: true, errors, detailsById: new Map() };

  const detailsById = new Map();
  raw.items.forEach((row, index) => {
    const detail = decodeDetailRow(row, `items[${index}]`, errors);
    if (!detail) return;
    const id = cleanString(detail.id);
    if (!ids.has(id) || detailsById.has(id) || stableCatalogShard(id, shardCount) !== shard) {
      errors.push(issue(`items[${index}].id`, "record", "Detail record is unknown, duplicated, or assigned to the wrong shard"));
      return;
    }
    detailsById.set(id, detail);
  });
  if (Number(raw.item_count) !== detailsById.size) errors.push(issue("item_count", "count", "Detail item count does not match the shard"));
  return errors.length
    ? { rejected: true, errors, detailsById: new Map() }
    : { rejected: false, errors: [], source: { ...raw.source }, shard, shardCount, detailsById };
}

/** Merge a validated detail projection into an existing in-memory record. */
export function hydrateCatalogRecord(record, details) {
  if (!isObject(record) || !cleanString(record.id) || !isObject(details) || details.id !== record.id) return record;
  for (const field of DETAIL_FIELDS) {
    if (field === "id") continue;
    if (field === "best_location") record[field] = details[field] ? { ...details[field] } : null;
    else if (field === "holdings") record[field] = Array.isArray(details[field]) ? details[field].map(item => ({ ...item })) : [];
    else if (ARRAY_DETAIL_FIELDS.has(field)) record[field] = stringArray(details[field]);
    else record[field] = String(details[field] || "");
  }
  record.detail_hydrated = true;
  return record;
}
