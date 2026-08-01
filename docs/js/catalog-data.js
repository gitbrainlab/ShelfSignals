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

// Version 1 remains the Clark/Sekula contract above. Version 2 is the
// collection-neutral contract used by Jefferson catalog-instance packages.
export const BROWSER_CATALOG_SCHEMA_V2 = "shelfsignals-browser-catalog@2";
export const CATALOG_SEARCH_SCHEMA_V2 = "shelfsignals-catalog-search@2";
export const CATALOG_DETAIL_SCHEMA_V2 = "shelfsignals-catalog-detail-shard@2";
export const CATALOG_DETAIL_INDEX_SCHEMA_V2 = "shelfsignals-catalog-detail-index@2";

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

export const CORE_FIELDS_V2 = Object.freeze([
  "id",
  "entity_type",
  "title",
  "authors",
  "year",
  "call_number",
  "material_type",
  "formats",
  "record_url",
  "facets",
  "orders",
  "evidence_status",
  "detail_shard"
]);
export const SEARCH_FIELDS_V2 = Object.freeze(["id", "search_text"]);
export const DETAIL_FIELDS_V2 = Object.freeze([
  "id",
  "entity_type",
  "full_title",
  "alternative_titles",
  "contributors",
  "publication",
  "languages",
  "subjects",
  "classifications",
  "modern_call_numbers",
  "holdings",
  "items",
  "identifiers",
  "lccns",
  "record_url",
  "relationship_to_jefferson",
  "ownership_or_reconstruction_status",
  "sowerby_numbers",
  "sowerby_evidence",
  "field_evidence",
  "source"
]);

const SOURCE_FIELDS_V2 = Object.freeze([
  "collection_id", "catalog", "dataset", "dataset_sha256", "record_count", "id_set_sha256"
]);
const CORE_CONTRACT_FIELDS_V2 = Object.freeze([
  "core_fields", "detail_fields", "detail_shard_count", "detail_path_template", "search_path"
]);
const FACET_FIELDS_V2 = Object.freeze(["lc", "material", "decade"]);
const ORDER_FIELDS_V2 = Object.freeze(["title", "lc", "sowerby"]);
const PUBLICATION_FIELDS_V2 = Object.freeze(["date", "place", "publisher"]);
const CONTRIBUTOR_FIELDS_V2 = Object.freeze(["name", "primary"]);
const CLASSIFICATION_FIELDS_V2 = Object.freeze(["source", "type_id", "value"]);
const HOLDING_FIELDS_V2 = Object.freeze(["id", "hrid", "permanent_location", "discovery_suppress"]);
const ITEM_FIELDS_V2 = Object.freeze([
  "id", "hrid", "call_number", "effective_location", "material_type", "status", "discovery_suppress"
]);
const IDENTIFIER_FIELDS_V2 = Object.freeze(["type", "value"]);
const SOWERBY_EVIDENCE_FIELDS_V2 = Object.freeze(["sowerby_number", "status", "method", "evidence", "assessment_scope"]);
const ASSESSMENT_SCOPE_FIELDS_V2 = Object.freeze([
  "selected_catalog_entity_count", "evidence_eligible_catalog_entity_count", "catalog_entities_not_assessed"
]);
const FIELD_EVIDENCE_FIELDS_V2 = Object.freeze([
  "collection_membership", "ownership_or_reconstruction_status", "sowerby_link"
]);
const ASSERTION_FIELDS_V2 = Object.freeze(["status", "assertion", "source"]);
const DETAIL_SOURCE_FIELDS_V2 = Object.freeze(["authority", "catalog_entity_id", "record_sha256", "source_position"]);

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

function exactObjectFields(value, expected) {
  if (!isObject(value)) return false;
  const keys = Object.keys(value).sort();
  return keys.length === expected.length
    && keys.every((entry, index) => entry === [...expected].sort()[index]);
}

function addUnknownFieldIssues(value, expected, path, errors) {
  if (!isObject(value)) {
    errors.push(issue(path, "object", "An object is required"));
    return false;
  }
  const expectedSet = new Set(expected);
  for (const key of Object.keys(value)) {
    if (!expectedSet.has(key)) errors.push(issue(`${path}.${key}`, "field", "Unknown field"));
  }
  for (const key of expected) {
    if (!Object.hasOwn(value, key)) errors.push(issue(`${path}.${key}`, "field", "Required field is missing"));
  }
  return exactObjectFields(value, expected);
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

function validCollectionId(value) {
  return /^[a-z][a-z0-9-]{0,63}$/.test(cleanString(value));
}

function validGenericSource(source, {
  expectedSource = null,
  collectionId = "",
  datasetSha256 = "",
  recordCount = 0,
  requireExpectedCollection = false
} = {}) {
  if (!exactObjectFields(source, SOURCE_FIELDS_V2)) return false;
  if (!validCollectionId(source.collection_id)) return false;
  if (!cleanString(source.catalog) || !cleanString(source.dataset) || /[\0-\x1f\x7f]/.test(source.dataset)) return false;
  if (!SHA256.test(cleanString(source.dataset_sha256)) || !SHA256.test(cleanString(source.id_set_sha256))) return false;
  if (!Number.isInteger(source.record_count) || source.record_count <= 0) return false;
  const expectedCollection = cleanString(expectedSource?.collection_id || collectionId);
  if (requireExpectedCollection && !expectedCollection) return false;
  if (expectedCollection && source.collection_id !== expectedCollection) return false;
  const expectedDatasetSha = cleanString(expectedSource?.dataset_sha256 || datasetSha256);
  if (expectedDatasetSha && source.dataset_sha256 !== expectedDatasetSha) return false;
  if (recordCount && source.record_count !== recordCount) return false;
  if (isObject(expectedSource)) {
    for (const field of SOURCE_FIELDS_V2) {
      if (source[field] !== expectedSource[field]) return false;
    }
  }
  return true;
}

function safeRelativeProjectionPath(value, { template = false } = {}) {
  const path = cleanString(value);
  if (!path || path.startsWith("/") || path.includes("\\") || /[?#\0-\x1f\x7f]/.test(path)) return "";
  if (template) {
    if ((path.match(/\{shard\}/g) || []).length !== 1) return "";
  } else if (/[{}]/.test(path)) return "";
  const sample = template ? path.replace("{shard}", "000") : path;
  if (!/^[A-Za-z0-9._~/-]+$/.test(sample)) return "";
  const segments = sample.split("/");
  if (segments.some(segment => !segment || segment === "." || segment === "..")) return "";
  return path;
}

function safeHttpsUrl(value, { optional = false } = {}) {
  const raw = cleanString(value);
  if (!raw && optional) return "";
  try {
    const url = new URL(raw);
    if (url.protocol !== "https:" || !url.hostname || url.username || url.password) return null;
    return url.href;
  } catch (_) {
    return null;
  }
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

function emptyDetailsV2() {
  return {
    full_title: "",
    alternative_titles: [],
    contributors: [],
    publication: [],
    languages: [],
    subjects: [],
    classifications: [],
    modern_call_numbers: [],
    holdings: [],
    items: [],
    identifiers: [],
    lccns: [],
    relationship_to_jefferson: "",
    ownership_or_reconstruction_status: "",
    sowerby_numbers: [],
    sowerby_evidence: [],
    field_evidence: null,
    source: null
  };
}

function decodeStringArrayV2(value, path, errors, { allowEmpty = true } = {}) {
  if (!Array.isArray(value) || value.some(entry => typeof entry !== "string" || (!allowEmpty && !cleanString(entry)))) {
    errors.push(issue(path, "array", "A string array is required"));
    return [];
  }
  return value.map(String);
}

function decodeIntegerArrayV2(value, path, errors, { positive = false } = {}) {
  const valid = Array.isArray(value) && value.every(entry => Number.isInteger(entry) && (positive ? entry > 0 : entry >= 0));
  if (!valid) {
    errors.push(issue(path, "array", "An integer array is required"));
    return [];
  }
  return [...value];
}

function decodeExactObjectArrayV2(value, fields, path, errors, decode) {
  if (!Array.isArray(value)) {
    errors.push(issue(path, "array", "An array is required"));
    return [];
  }
  return value.map((entry, index) => {
    const entryPath = `${path}[${index}]`;
    addUnknownFieldIssues(entry, fields, entryPath, errors);
    return decode(entry || {}, entryPath);
  });
}

function decodeAssertionV2(value, path, errors) {
  addUnknownFieldIssues(value, ASSERTION_FIELDS_V2, path, errors);
  const decoded = {};
  for (const field of ASSERTION_FIELDS_V2) {
    if (!cleanString(value?.[field])) errors.push(issue(`${path}.${field}`, "string", "Evidence assertion fields must be non-empty strings"));
    decoded[field] = String(value?.[field] || "");
  }
  return decoded;
}

function decodeDetailRowV2(row, path, errors) {
  if (!Array.isArray(row) || row.length !== DETAIL_FIELDS_V2.length) {
    errors.push(issue(path, "row", "Detail row length is invalid"));
    return null;
  }
  const raw = Object.fromEntries(DETAIL_FIELDS_V2.map((field, index) => [field, row[index]]));
  const id = cleanString(raw.id);
  if (!id || !SAFE_ID.test(id)) errors.push(issue(`${path}.id`, "id", "Detail record ID is missing or unsafe"));
  if (raw.entity_type !== "catalog_instance") errors.push(issue(`${path}.entity_type`, "entity", "Detail entity type is invalid"));

  const detail = {
    id,
    entity_type: "catalog_instance",
    full_title: String(raw.full_title || ""),
    alternative_titles: decodeStringArrayV2(raw.alternative_titles, `${path}.alternative_titles`, errors),
    contributors: decodeExactObjectArrayV2(raw.contributors, CONTRIBUTOR_FIELDS_V2, `${path}.contributors`, errors, (entry, entryPath) => {
      if (!cleanString(entry.name)) errors.push(issue(`${entryPath}.name`, "string", "Contributor name is required"));
      if (typeof entry.primary !== "boolean") errors.push(issue(`${entryPath}.primary`, "boolean", "Contributor primary flag must be boolean"));
      return { name: String(entry.name || ""), primary: entry.primary === true };
    }),
    publication: decodeExactObjectArrayV2(raw.publication, PUBLICATION_FIELDS_V2, `${path}.publication`, errors, (entry, entryPath) => {
      const value = Object.fromEntries(PUBLICATION_FIELDS_V2.map(field => [field, String(entry[field] || "")]));
      if (PUBLICATION_FIELDS_V2.some(field => typeof entry[field] !== "string") || !Object.values(value).some(cleanString)) {
        errors.push(issue(entryPath, "publication", "Publication fields must be strings and at least one must be non-empty"));
      }
      return value;
    }),
    languages: decodeStringArrayV2(raw.languages, `${path}.languages`, errors),
    subjects: decodeStringArrayV2(raw.subjects, `${path}.subjects`, errors),
    classifications: decodeExactObjectArrayV2(raw.classifications, CLASSIFICATION_FIELDS_V2, `${path}.classifications`, errors, (entry, entryPath) => {
      const value = Object.fromEntries(CLASSIFICATION_FIELDS_V2.map(field => [field, String(entry[field] || "")]));
      if (CLASSIFICATION_FIELDS_V2.some(field => typeof entry[field] !== "string") || !cleanString(value.value)) {
        errors.push(issue(entryPath, "classification", "Classification fields must be strings with a non-empty value"));
      }
      return value;
    }),
    modern_call_numbers: decodeExactObjectArrayV2(raw.modern_call_numbers, CLASSIFICATION_FIELDS_V2, `${path}.modern_call_numbers`, errors, (entry, entryPath) => {
      const value = Object.fromEntries(CLASSIFICATION_FIELDS_V2.map(field => [field, String(entry[field] || "")]));
      if (CLASSIFICATION_FIELDS_V2.some(field => typeof entry[field] !== "string") || !cleanString(value.value)) {
        errors.push(issue(entryPath, "call_number", "Call-number fields must be strings with a non-empty value"));
      }
      return value;
    }),
    holdings: decodeExactObjectArrayV2(raw.holdings, HOLDING_FIELDS_V2, `${path}.holdings`, errors, (entry, entryPath) => {
      if (!cleanString(entry.id) || !cleanString(entry.hrid) || typeof entry.permanent_location !== "string" || typeof entry.discovery_suppress !== "boolean") {
        errors.push(issue(entryPath, "holding", "Holding projection is invalid"));
      }
      return {
        id: String(entry.id || ""), hrid: String(entry.hrid || ""),
        permanent_location: String(entry.permanent_location || ""), discovery_suppress: entry.discovery_suppress === true
      };
    }),
    items: decodeExactObjectArrayV2(raw.items, ITEM_FIELDS_V2, `${path}.items`, errors, (entry, entryPath) => {
      const stringFields = ITEM_FIELDS_V2.filter(field => field !== "discovery_suppress");
      if (!cleanString(entry.id) || !cleanString(entry.hrid) || stringFields.some(field => typeof entry[field] !== "string") || typeof entry.discovery_suppress !== "boolean") {
        errors.push(issue(entryPath, "item", "Item projection is invalid"));
      }
      return {
        ...Object.fromEntries(stringFields.map(field => [field, String(entry[field] || "")])),
        discovery_suppress: entry.discovery_suppress === true
      };
    }),
    identifiers: decodeExactObjectArrayV2(raw.identifiers, IDENTIFIER_FIELDS_V2, `${path}.identifiers`, errors, (entry, entryPath) => {
      if (!cleanString(entry.type) || !cleanString(entry.value)) errors.push(issue(entryPath, "identifier", "Identifier type and value are required"));
      return { type: String(entry.type || ""), value: String(entry.value || "") };
    }),
    lccns: decodeStringArrayV2(raw.lccns, `${path}.lccns`, errors),
    record_url: "",
    relationship_to_jefferson: String(raw.relationship_to_jefferson || ""),
    ownership_or_reconstruction_status: String(raw.ownership_or_reconstruction_status || ""),
    sowerby_numbers: decodeIntegerArrayV2(raw.sowerby_numbers, `${path}.sowerby_numbers`, errors, { positive: true }),
    sowerby_evidence: decodeExactObjectArrayV2(raw.sowerby_evidence, SOWERBY_EVIDENCE_FIELDS_V2, `${path}.sowerby_evidence`, errors, (entry, entryPath) => {
      if (!Number.isInteger(entry.sowerby_number) || entry.sowerby_number <= 0) errors.push(issue(`${entryPath}.sowerby_number`, "number", "Sowerby number must be a positive integer"));
      for (const field of ["status", "method", "evidence"]) {
        if (!cleanString(entry[field])) errors.push(issue(`${entryPath}.${field}`, "string", "Sowerby evidence fields must be non-empty strings"));
      }
      addUnknownFieldIssues(entry.assessment_scope, ASSESSMENT_SCOPE_FIELDS_V2, `${entryPath}.assessment_scope`, errors);
      const assessmentScope = {};
      for (const field of ASSESSMENT_SCOPE_FIELDS_V2) {
        if (!Number.isInteger(entry.assessment_scope?.[field]) || entry.assessment_scope[field] < 0) errors.push(issue(`${entryPath}.assessment_scope.${field}`, "count", "Assessment scope must be a non-negative integer"));
        assessmentScope[field] = Number(entry.assessment_scope?.[field] || 0);
      }
      return {
        sowerby_number: Number(entry.sowerby_number), status: String(entry.status || ""),
        method: String(entry.method || ""), evidence: String(entry.evidence || ""), assessment_scope: assessmentScope
      };
    }),
    field_evidence: {},
    source: {}
  };

  if (!cleanString(raw.full_title)) errors.push(issue(`${path}.full_title`, "title", "Full catalog title is required"));

  const recordUrl = safeHttpsUrl(raw.record_url, { optional: true });
  if (recordUrl === null) errors.push(issue(`${path}.record_url`, "url", "Record URL must be empty or HTTPS"));
  detail.record_url = recordUrl || "";
  if (typeof raw.relationship_to_jefferson !== "string" || typeof raw.ownership_or_reconstruction_status !== "string") {
    errors.push(issue(path, "status", "Relationship and reconstruction status must be strings"));
  }

  addUnknownFieldIssues(raw.field_evidence, FIELD_EVIDENCE_FIELDS_V2, `${path}.field_evidence`, errors);
  for (const field of FIELD_EVIDENCE_FIELDS_V2) {
    detail.field_evidence[field] = decodeAssertionV2(raw.field_evidence?.[field], `${path}.field_evidence.${field}`, errors);
  }

  addUnknownFieldIssues(raw.source, DETAIL_SOURCE_FIELDS_V2, `${path}.source`, errors);
  if (!cleanString(raw.source?.authority) || !cleanString(raw.source?.catalog_entity_id)) errors.push(issue(`${path}.source`, "source", "Detail source identity is incomplete"));
  if (!SHA256.test(cleanString(raw.source?.record_sha256))) errors.push(issue(`${path}.source.record_sha256`, "sha256", "Detail record checksum is invalid"));
  if (!Number.isInteger(raw.source?.source_position) || raw.source.source_position <= 0) errors.push(issue(`${path}.source.source_position`, "position", "Source position must be positive"));
  detail.source = {
    authority: String(raw.source?.authority || ""),
    catalog_entity_id: String(raw.source?.catalog_entity_id || ""),
    record_sha256: String(raw.source?.record_sha256 || ""),
    source_position: Number(raw.source?.source_position || 0)
  };
  return detail;
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

/** Parse the compact first-load version-1 projection and reconstruct exact Clark URLs. */
function parseBrowserCatalogV1(raw) {
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

function parseBrowserCatalogV2(raw, { collectionId = "" } = {}) {
  const errors = [];
  addUnknownFieldIssues(raw, ["schema", "generated_at", "source", "contract", "items"], "catalog", errors);
  if (raw?.schema !== BROWSER_CATALOG_SCHEMA_V2) errors.push(issue("schema", "schema", "Unsupported browser catalog schema"));
  if (!ISO_DATE.test(cleanString(raw?.generated_at))) errors.push(issue("generated_at", "date", "A UTC generation time is required"));
  if (!validGenericSource(raw?.source, { collectionId })) errors.push(issue("source", "source", "Collection source identity is invalid"));
  addUnknownFieldIssues(raw?.contract, CORE_CONTRACT_FIELDS_V2, "contract", errors);
  if (!exactFields(raw?.contract?.core_fields, CORE_FIELDS_V2)) errors.push(issue("contract.core_fields", "fields", "Core field order changed"));
  if (!exactFields(raw?.contract?.detail_fields, DETAIL_FIELDS_V2)) errors.push(issue("contract.detail_fields", "fields", "Detail field order changed"));
  const shardCount = Number(raw?.contract?.detail_shard_count);
  if (!Number.isInteger(shardCount) || shardCount < 1 || shardCount > 1000) errors.push(issue("contract.detail_shard_count", "range", "Detail shard count is invalid"));
  const detailPath = safeRelativeProjectionPath(raw?.contract?.detail_path_template, { template: true });
  if (!detailPath) errors.push(issue("contract.detail_path_template", "path", "Detail path template is invalid"));
  const searchPath = safeRelativeProjectionPath(raw?.contract?.search_path);
  if (!searchPath) errors.push(issue("contract.search_path", "path", "Search path is invalid"));
  if (detailPath && searchPath && detailPath.replace("{shard}", "000") === searchPath) errors.push(issue("contract.search_path", "duplicate", "Search and detail paths must be distinct"));
  if (!Array.isArray(raw?.items)) errors.push(issue("items", "array", "Catalog items must be an array"));
  if (errors.length) return { rejected: true, errors, source: null, records: [] };

  const records = [];
  const ids = new Set();
  raw.items.forEach((row, index) => {
    const path = `items[${index}]`;
    if (!Array.isArray(row) || row.length !== CORE_FIELDS_V2.length) {
      errors.push(issue(path, "row", "Core row length is invalid"));
      return;
    }
    const [
      rawId, rawEntityType, rawTitle, rawAuthors, rawYear, rawCallNumber, rawMaterial,
      rawFormats, rawRecordUrl, rawFacets, rawOrders, rawEvidenceStatus, rawShard
    ] = row;
    const id = cleanString(rawId);
    const title = cleanString(rawTitle);
    if (!id || !SAFE_ID.test(id) || ids.has(id)) errors.push(issue(`${path}.id`, "id", "Record ID is missing, unsafe, or duplicated"));
    if (rawEntityType !== "catalog_instance") errors.push(issue(`${path}.entity_type`, "entity", "Core entity type is invalid"));
    if (!title) errors.push(issue(`${path}.title`, "title", "Canonical title is required"));
    const authors = decodeStringArrayV2(rawAuthors, `${path}.authors`, errors);
    const formats = decodeStringArrayV2(rawFormats, `${path}.formats`, errors);
    for (const [field, value] of [["year", rawYear], ["call_number", rawCallNumber], ["material_type", rawMaterial]]) {
      if (typeof value !== "string") errors.push(issue(`${path}.${field}`, "string", "Core scalar fields must be strings"));
    }
    const recordUrl = safeHttpsUrl(rawRecordUrl, { optional: true });
    if (recordUrl === null) errors.push(issue(`${path}.record_url`, "url", "Record URL must be empty or HTTPS"));

    addUnknownFieldIssues(rawFacets, FACET_FIELDS_V2, `${path}.facets`, errors);
    const facets = {
      lc: decodeStringArrayV2(rawFacets?.lc, `${path}.facets.lc`, errors),
      material: decodeStringArrayV2(rawFacets?.material, `${path}.facets.material`, errors),
      decade: decodeIntegerArrayV2(rawFacets?.decade, `${path}.facets.decade`, errors)
    };

    addUnknownFieldIssues(rawOrders, ORDER_FIELDS_V2, `${path}.orders`, errors);
    const titleOrder = rawOrders?.title;
    const lcOrder = rawOrders?.lc;
    const sowerbyOrder = rawOrders?.sowerby;
    if (!Number.isInteger(titleOrder) || titleOrder < 0) errors.push(issue(`${path}.orders.title`, "order", "Title order must be a non-negative integer"));
    if (lcOrder !== null && (!Number.isInteger(lcOrder) || lcOrder < 0)) errors.push(issue(`${path}.orders.lc`, "order", "LC order must be a non-negative integer or null"));
    if (sowerbyOrder !== null && (!Number.isInteger(sowerbyOrder) || sowerbyOrder <= 0)) errors.push(issue(`${path}.orders.sowerby`, "order", "Sowerby order must be a positive integer or null"));
    const orders = { title: Number(titleOrder), lc: lcOrder, sowerby: sowerbyOrder };

    if (!["collection_heading_only", "sowerby_510_exact_bounded"].includes(rawEvidenceStatus)) {
      errors.push(issue(`${path}.evidence_status`, "evidence", "Core evidence status is invalid"));
    }
    const detailShard = Number(rawShard);
    if (!Number.isInteger(detailShard) || detailShard < 0 || detailShard >= shardCount || stableCatalogShard(id, shardCount) !== detailShard) {
      errors.push(issue(`${path}.detail_shard`, "shard", "Record is assigned to the wrong detail shard"));
    }
    ids.add(id);
    records.push({
      ...emptyDetailsV2(),
      id,
      entity_type: "catalog_instance",
      title,
      authors,
      year: String(rawYear || ""),
      call_number: String(rawCallNumber || ""),
      material_type: String(rawMaterial || ""),
      formats,
      record_url: recordUrl || "",
      catalogLink: recordUrl || "",
      facets,
      orders,
      evidence_status: String(rawEvidenceStatus || ""),
      detail_shard: detailShard,
      placements: [],
      signals: [],
      photo_insert_bucket: "",
      photo_insert_score: null,
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
    detailFields: [...DETAIL_FIELDS_V2],
    records
  };
}

/** Parse a compact first-load projection. Version 1 behavior is unchanged. */
export function parseBrowserCatalog(raw, options = {}) {
  return raw?.schema === BROWSER_CATALOG_SCHEMA_V2
    ? parseBrowserCatalogV2(raw, options)
    : parseBrowserCatalogV1(raw);
}

/** Parse the full-field search projection. It is loaded only after a query. */
function parseCatalogSearchIndexV1(raw, { datasetSha256 = "", catalogIds = [] } = {}) {
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

function parseCatalogSearchIndexV2(raw, {
  datasetSha256 = "",
  catalogIds = [],
  collectionId = "",
  catalogSource = null
} = {}) {
  const errors = [];
  const ids = asCatalogIdSet(catalogIds);
  if (!ids.size) errors.push(issue("catalogIds", "catalog", "Validated catalog IDs are required for version-2 search"));
  addUnknownFieldIssues(raw, ["schema", "generated_at", "source", "fields", "items"], "search", errors);
  if (raw?.schema !== CATALOG_SEARCH_SCHEMA_V2) errors.push(issue("schema", "schema", "Unsupported search schema"));
  if (!ISO_DATE.test(cleanString(raw?.generated_at))) errors.push(issue("generated_at", "date", "A UTC generation time is required"));
  if (!validGenericSource(raw?.source, {
    expectedSource: catalogSource,
    collectionId,
    datasetSha256,
    recordCount: ids.size,
    requireExpectedCollection: true
  })) errors.push(issue("source", "source", "Search source identity does not match the catalog"));
  if (!exactFields(raw?.fields, SEARCH_FIELDS_V2)) errors.push(issue("fields", "fields", "Search field order changed"));
  if (!Array.isArray(raw?.items)) errors.push(issue("items", "array", "Search items must be an array"));
  if (errors.length) return { rejected: true, errors, searchById: new Map() };

  const searchById = new Map();
  raw.items.forEach((row, index) => {
    if (!Array.isArray(row) || row.length !== SEARCH_FIELDS_V2.length) {
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

/** Parse a full-field search projection and enforce same-collection identity. */
export function parseCatalogSearchIndex(raw, options = {}) {
  return raw?.schema === CATALOG_SEARCH_SCHEMA_V2
    ? parseCatalogSearchIndexV2(raw, options)
    : parseCatalogSearchIndexV1(raw, options);
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
function parseCatalogDetailShardV1(raw, { datasetSha256 = "", catalogIds = [], expectedShard } = {}) {
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

function parseCatalogDetailShardV2(raw, {
  datasetSha256 = "",
  catalogIds = [],
  collectionId = "",
  catalogSource = null,
  expectedShard
} = {}) {
  const errors = [];
  const ids = asCatalogIdSet(catalogIds);
  if (!ids.size) errors.push(issue("catalogIds", "catalog", "Validated catalog IDs are required for version-2 details"));
  addUnknownFieldIssues(raw, ["schema", "generated_at", "source", "shard", "shard_count", "item_count", "fields", "items"], "detail", errors);
  if (raw?.schema !== CATALOG_DETAIL_SCHEMA_V2) errors.push(issue("schema", "schema", "Unsupported detail-shard schema"));
  if (!ISO_DATE.test(cleanString(raw?.generated_at))) errors.push(issue("generated_at", "date", "A UTC generation time is required"));
  if (!validGenericSource(raw?.source, {
    expectedSource: catalogSource,
    collectionId,
    datasetSha256,
    recordCount: ids.size,
    requireExpectedCollection: true
  })) errors.push(issue("source", "source", "Detail source identity does not match the catalog"));
  if (!exactFields(raw?.fields, DETAIL_FIELDS_V2)) errors.push(issue("fields", "fields", "Detail field order changed"));
  const shard = Number(raw?.shard);
  const shardCount = Number(raw?.shard_count);
  if (!Number.isInteger(shard) || !Number.isInteger(shardCount) || shard < 0 || shard >= shardCount || (Number.isInteger(expectedShard) && shard !== expectedShard)) {
    errors.push(issue("shard", "shard", "Detail shard identity is invalid"));
  }
  if (!Number.isInteger(raw?.item_count) || raw.item_count < 0) errors.push(issue("item_count", "count", "Detail item count is invalid"));
  if (!Array.isArray(raw?.items)) errors.push(issue("items", "array", "Detail items must be an array"));
  if (errors.length) return { rejected: true, errors, detailsById: new Map() };

  const detailsById = new Map();
  raw.items.forEach((row, index) => {
    const detail = decodeDetailRowV2(row, `items[${index}]`, errors);
    if (!detail) return;
    const id = cleanString(detail.id);
    if (!ids.has(id) || detailsById.has(id) || stableCatalogShard(id, shardCount) !== shard) {
      errors.push(issue(`items[${index}].id`, "record", "Detail record is unknown, duplicated, or assigned to the wrong shard"));
      return;
    }
    detailsById.set(id, detail);
  });
  if (raw.item_count !== detailsById.size) errors.push(issue("item_count", "count", "Detail item count does not match the shard"));
  return errors.length
    ? { rejected: true, errors, detailsById: new Map() }
    : { rejected: false, errors: [], source: { ...raw.source }, shard, shardCount, detailsById };
}

/** Parse one deterministic detail shard and reject cross-collection content. */
export function parseCatalogDetailShard(raw, options = {}) {
  return raw?.schema === CATALOG_DETAIL_SCHEMA_V2
    ? parseCatalogDetailShardV2(raw, options)
    : parseCatalogDetailShardV1(raw, options);
}

/** Parse the version-2 detail index and reject duplicate or missing shards. */
export function parseCatalogDetailIndex(raw, {
  datasetSha256 = "",
  catalogIds = [],
  collectionId = "",
  catalogSource = null,
  expectedShardCount
} = {}) {
  const errors = [];
  const ids = asCatalogIdSet(catalogIds);
  if (!ids.size) errors.push(issue("catalogIds", "catalog", "Validated catalog IDs are required for the detail index"));
  addUnknownFieldIssues(raw, ["schema", "generated_at", "source", "shard_count", "fields", "shards"], "detail_index", errors);
  if (raw?.schema !== CATALOG_DETAIL_INDEX_SCHEMA_V2) errors.push(issue("schema", "schema", "Unsupported detail-index schema"));
  if (!ISO_DATE.test(cleanString(raw?.generated_at))) errors.push(issue("generated_at", "date", "A UTC generation time is required"));
  if (!validGenericSource(raw?.source, {
    expectedSource: catalogSource,
    collectionId,
    datasetSha256,
    recordCount: ids.size,
    requireExpectedCollection: true
  })) errors.push(issue("source", "source", "Detail-index source identity does not match the catalog"));
  if (!exactFields(raw?.fields, DETAIL_FIELDS_V2)) errors.push(issue("fields", "fields", "Detail field order changed"));
  const shardCount = Number(raw?.shard_count);
  if (!Number.isInteger(shardCount) || shardCount < 1 || shardCount > 1000 || (Number.isInteger(expectedShardCount) && shardCount !== expectedShardCount)) {
    errors.push(issue("shard_count", "shard", "Detail shard count is invalid"));
  }
  if (!Array.isArray(raw?.shards)) errors.push(issue("shards", "array", "Detail shards must be an array"));
  if (errors.length) return { rejected: true, errors, shards: [] };

  const seen = new Set();
  let itemCount = 0;
  const shards = [];
  raw.shards.forEach((entry, index) => {
    const path = `shards[${index}]`;
    addUnknownFieldIssues(entry, ["shard", "file", "item_count", "bytes", "sha256"], path, errors);
    const shard = Number(entry?.shard);
    if (!Number.isInteger(shard) || shard < 0 || shard >= shardCount || seen.has(shard)) {
      errors.push(issue(`${path}.shard`, "shard", "Shard is invalid or duplicated"));
    }
    if (Number.isInteger(shard) && entry?.file !== detailShardName(shard)) errors.push(issue(`${path}.file`, "path", "Shard filename does not match its identity"));
    if (!Number.isInteger(entry?.item_count) || entry.item_count < 0) errors.push(issue(`${path}.item_count`, "count", "Shard item count is invalid"));
    if (!Number.isInteger(entry?.bytes) || entry.bytes <= 0) errors.push(issue(`${path}.bytes`, "count", "Shard byte count is invalid"));
    if (!SHA256.test(cleanString(entry?.sha256))) errors.push(issue(`${path}.sha256`, "sha256", "Shard checksum is invalid"));
    seen.add(shard);
    itemCount += Number.isInteger(entry?.item_count) ? entry.item_count : 0;
    shards.push({ ...entry });
  });
  if (seen.size !== shardCount || shards.length !== shardCount) errors.push(issue("shards", "count", "Detail index does not declare every shard exactly once"));
  if (itemCount !== raw.source.record_count) errors.push(issue("shards", "count", "Detail shard counts do not cover the complete catalog"));
  return errors.length
    ? { rejected: true, errors, shards: [] }
    : { rejected: false, errors: [], source: { ...raw.source }, shardCount, shards };
}

/** Merge a validated detail projection into an existing in-memory record. */
export function hydrateCatalogRecord(record, details) {
  if (!isObject(record) || !cleanString(record.id) || !isObject(details) || details.id !== record.id) return record;
  if (details.entity_type === "catalog_instance") {
    for (const field of DETAIL_FIELDS_V2) {
      if (field === "id" || field === "entity_type") continue;
      record[field] = structuredClone(details[field]);
    }
    record.title = details.full_title;
    record.entity_type = details.entity_type;
    record.catalogLink = details.record_url || record.catalogLink || "";
    record.detail_hydrated = true;
    return record;
  }
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
