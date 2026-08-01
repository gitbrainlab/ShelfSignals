/**
 * Fail-closed collection manifest contracts.
 *
 * Manifests contain presentation configuration and relative public-data paths;
 * they are not a source of bibliographic evidence. Every collection payload
 * still validates its own source identity in `catalog-data.js`.
 */

// @ts-check

export const COLLECTION_MANIFEST_SCHEMA = "shelfsignals-collection-manifest@1";

export const COLLECTION_COPY_FIELDS = Object.freeze([
  "name",
  "short_name",
  "institution",
  "status_label",
  "introduction",
  "coverage_statement",
  "source_label"
]);

export const COLLECTION_DATA_FIELDS = Object.freeze([
  "core",
  "search",
  "detail_template",
  "detail_index",
  "hierarchy",
  "featured",
  "public_media",
  "validation",
  "review_media",
  "covers",
  "cover_provenance",
  "paths",
  "journeys",
  "spines",
  "editions"
]);

export const COLLECTION_FEATURE_FIELDS = Object.freeze([
  "journeys",
  "placement",
  "photo_likelihood",
  "provider_editions",
  "curated_paths",
  "historical_hierarchy",
  "coverage_comparison",
  "reconstruction_status",
  "digital_surrogates",
  "evidence_ledger",
  "physical"
]);

export const COLLECTION_COVERAGE_FIELDS = Object.freeze([
  "status",
  "entity_type",
  "record_count",
  "historical_entry_count",
  "historical_volume_count",
  "established_sowerby_links"
]);

export const COLLECTION_FACET_IDS = Object.freeze([
  "classes",
  "materials",
  "decades",
  "photo_likelihood",
  "signals",
  "placements",
  "languages",
  "subjects",
  "material_types",
  "formats",
  "publication_places",
  "reconstruction_status",
  "digital_availability",
  "evidence_status"
]);

export const COLLECTION_ORDER_IDS = Object.freeze(["catalog", "title", "lc", "sowerby"]);

const MANIFEST_FIELDS = Object.freeze([
  "schema",
  "id",
  "copy",
  "data",
  "features",
  "coverage",
  "shelf",
  "facets",
  "orders",
  "defaults",
  "review"
]);
const SHELF_FIELDS = Object.freeze(["storage_key", "receipt_name"]);
const ORDER_FIELDS = Object.freeze(["id", "label"]);
const DEFAULT_FIELDS = Object.freeze(["corpus", "order"]);
const REVIEW_FIELDS = Object.freeze(["enabled", "code_sha256", "session_key", "warning"]);
const REQUIRED_DATA_FIELDS = Object.freeze(["core", "search", "detail_template", "detail_index"]);
const SAFE_COLLECTION_ID = /^[a-z][a-z0-9-]{0,63}$/;
const SAFE_STORAGE_KEY = /^[A-Za-z0-9_.:-]+$/;
const SAFE_RECEIPT_NAME = /^[A-Za-z0-9][A-Za-z0-9._ -]{0,127}\.json$/i;
const SHA256 = /^sha256:[a-f0-9]{64}$/i;

/** @typedef {{path: string, code: string, message: string}} CollectionIssue */

function isObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function cleanString(value) {
  return typeof value === "string" ? value.trim() : "";
}

function issue(path, code, message) {
  return { path, code, message };
}

function unknownKeys(value, allowed) {
  if (!isObject(value)) return [];
  const accepted = new Set(allowed);
  return Object.keys(value).filter(key => !accepted.has(key)).sort();
}

function requireExactKeys(value, allowed, path, errors, { optional = [] } = {}) {
  if (!isObject(value)) {
    errors.push(issue(path, "object", `${path || "Value"} must be an object`));
    return false;
  }
  for (const key of unknownKeys(value, allowed)) {
    errors.push(issue(path ? `${path}.${key}` : key, "field", "Unknown field"));
  }
  const optionalSet = new Set(optional);
  for (const key of allowed) {
    if (!optionalSet.has(key) && !Object.hasOwn(value, key)) {
      errors.push(issue(path ? `${path}.${key}` : key, "field", "Required field is missing"));
    }
  }
  return true;
}

function safeRelativeDataPath(value, { template = false } = {}) {
  const path = cleanString(value);
  if (!path || path.startsWith("/") || path.includes("\\") || /[?#\0-\x1f\x7f]/.test(path)) return "";
  if (template) {
    if ((path.match(/\{shard\}/g) || []).length !== 1) return "";
  } else if (/[{}]/.test(path)) return "";
  const sample = template ? path.replace("{shard}", "000") : path;
  if (!/^[A-Za-z0-9._~/-]+$/.test(sample)) return "";
  const segments = sample.split("/");
  if (segments.some(segment => !segment || segment === "." || segment === "..")) return "";
  try {
    const base = new URL("https://manifest.invalid/collection/");
    const resolved = new URL(sample, base);
    if (resolved.origin !== base.origin || !resolved.pathname.startsWith(base.pathname)) return "";
  } catch (_) {
    return "";
  }
  return path;
}

function nonNegativeIntegerOrNull(value) {
  return value == null || (Number.isInteger(value) && value >= 0);
}

/**
 * Return unknown data/feature keys without accepting them. This is useful to
 * surface manifest-authoring errors before calling the full parser.
 */
export function collectionConfigUnknownFields(raw) {
  return {
    data: unknownKeys(raw?.data, COLLECTION_DATA_FIELDS),
    features: unknownKeys(raw?.features, COLLECTION_FEATURE_FIELDS)
  };
}

/** Parse one collection manifest. No partial manifest is returned on error. */
export function parseCollectionManifest(raw, { expectedId = "" } = {}) {
  /** @type {CollectionIssue[]} */
  const errors = [];
  if (!requireExactKeys(raw, MANIFEST_FIELDS, "", errors, { optional: ["review"] })) {
    return { rejected: true, errors, manifest: null };
  }
  if (raw.schema !== COLLECTION_MANIFEST_SCHEMA) errors.push(issue("schema", "schema", "Unsupported collection manifest schema"));

  const id = cleanString(raw.id);
  if (!SAFE_COLLECTION_ID.test(id)) errors.push(issue("id", "id", "Collection ID is missing or unsafe"));
  if (expectedId && id !== expectedId) errors.push(issue("id", "collection", "Manifest collection does not match the requested collection"));

  if (requireExactKeys(raw.copy, COLLECTION_COPY_FIELDS, "copy", errors)) {
    for (const field of COLLECTION_COPY_FIELDS) {
      if (!cleanString(raw.copy[field])) errors.push(issue(`copy.${field}`, "string", "Collection copy must be a non-empty string"));
    }
  }

  if (requireExactKeys(raw.features, COLLECTION_FEATURE_FIELDS, "features", errors)) {
    for (const field of COLLECTION_FEATURE_FIELDS) {
      if (typeof raw.features[field] !== "boolean") errors.push(issue(`features.${field}`, "boolean", "Feature flags must be booleans"));
    }
  }

  if (requireExactKeys(raw.data, COLLECTION_DATA_FIELDS, "data", errors, {
    optional: COLLECTION_DATA_FIELDS.filter(field => !REQUIRED_DATA_FIELDS.includes(field))
  })) {
    const paths = new Map();
    for (const [field, value] of Object.entries(raw.data)) {
      const path = safeRelativeDataPath(value, { template: field === "detail_template" });
      if (!path) {
        errors.push(issue(`data.${field}`, "path", "Data path must be a safe collection-relative path"));
        continue;
      }
      const normalized = field === "detail_template" ? path.replace("{shard}", "000") : path;
      if (paths.has(normalized)) errors.push(issue(`data.${field}`, "duplicate", `Data path duplicates data.${paths.get(normalized)}`));
      else paths.set(normalized, field);
    }
  }

  if (requireExactKeys(raw.coverage, COLLECTION_COVERAGE_FIELDS, "coverage", errors)) {
    if (!["canonical", "beta", "complete"].includes(raw.coverage.status)) {
      errors.push(issue("coverage.status", "status", "Coverage status is invalid"));
    }
    if (!cleanString(raw.coverage.entity_type)) errors.push(issue("coverage.entity_type", "string", "Coverage entity type is required"));
    if (!Number.isInteger(raw.coverage.record_count) || raw.coverage.record_count <= 0) {
      errors.push(issue("coverage.record_count", "count", "Coverage record count must be positive"));
    }
    for (const field of ["historical_entry_count", "historical_volume_count", "established_sowerby_links"]) {
      if (!nonNegativeIntegerOrNull(raw.coverage[field])) errors.push(issue(`coverage.${field}`, "count", "Coverage count must be a non-negative integer or null"));
    }
  }

  if (requireExactKeys(raw.shelf, SHELF_FIELDS, "shelf", errors)) {
    const expectedShelfKey = id === "sekula" ? "shelfsignals_shelf" : `shelfsignals_shelf:${id}`;
    if (!SAFE_STORAGE_KEY.test(cleanString(raw.shelf.storage_key)) || raw.shelf.storage_key !== expectedShelfKey) {
      errors.push(issue("shelf.storage_key", "storage", "Shelf storage key is unsafe or belongs to another collection"));
    }
    if (!SAFE_RECEIPT_NAME.test(cleanString(raw.shelf.receipt_name))) {
      errors.push(issue("shelf.receipt_name", "filename", "Receipt name must be a safe JSON filename"));
    }
  }

  if (!Array.isArray(raw.facets) || raw.facets.length === 0) {
    errors.push(issue("facets", "array", "At least one facet ID is required"));
  } else {
    const seen = new Set();
    raw.facets.forEach((facet, index) => {
      if (!COLLECTION_FACET_IDS.includes(facet) || seen.has(facet)) errors.push(issue(`facets[${index}]`, "facet", "Facet ID is unknown or duplicated"));
      seen.add(facet);
    });
  }

  if (!Array.isArray(raw.orders) || raw.orders.length === 0) {
    errors.push(issue("orders", "array", "At least one ordering option is required"));
  } else {
    const seen = new Set();
    raw.orders.forEach((order, index) => {
      const path = `orders[${index}]`;
      if (!requireExactKeys(order, ORDER_FIELDS, path, errors)) return;
      if (!COLLECTION_ORDER_IDS.includes(order.id) || seen.has(order.id)) errors.push(issue(`${path}.id`, "order", "Order ID is unknown or duplicated"));
      if (!cleanString(order.label)) errors.push(issue(`${path}.label`, "string", "Order label is required"));
      seen.add(order.id);
    });
  }

  if (requireExactKeys(raw.defaults, DEFAULT_FIELDS, "defaults", errors)) {
    if (!["catalog", "historical"].includes(raw.defaults.corpus)) errors.push(issue("defaults.corpus", "corpus", "Default corpus is invalid"));
    const declaredOrders = new Set(Array.isArray(raw.orders) ? raw.orders.map(order => order?.id) : []);
    if (!declaredOrders.has(raw.defaults.order)) errors.push(issue("defaults.order", "order", "Default order must be declared by the manifest"));
  }

  const review = raw.review;
  if (review !== undefined) {
    if (requireExactKeys(review, REVIEW_FIELDS, "review", errors)) {
      if (review.enabled !== true) errors.push(issue("review.enabled", "boolean", "An included review configuration must be enabled"));
      if (!SHA256.test(cleanString(review.code_sha256))) errors.push(issue("review.code_sha256", "sha256", "Review code digest is invalid"));
      if (cleanString(review.session_key) !== `shelfsignals_review:${id}`) errors.push(issue("review.session_key", "storage", "Review session key is unsafe or belongs to another collection"));
      if (!cleanString(review.warning)) errors.push(issue("review.warning", "string", "Review warning is required"));
      if (!raw.data?.review_media) errors.push(issue("data.review_media", "path", "Review media path is required when review mode is enabled"));
    }
  } else if (raw.data?.review_media) {
    errors.push(issue("data.review_media", "review", "Review media cannot be configured without review mode"));
  }

  const requiredFeaturePaths = [
    ["journeys", "journeys"],
    ["provider_editions", "editions"],
    ["curated_paths", "paths"],
    ["historical_hierarchy", "hierarchy"],
    ["digital_surrogates", "public_media"]
  ];
  for (const [feature, dataField] of requiredFeaturePaths) {
    if (raw.features?.[feature] === true && !raw.data?.[dataField]) {
      errors.push(issue(`data.${dataField}`, "feature", `Data path is required when features.${feature} is enabled`));
    }
  }

  if (errors.length) return { rejected: true, errors, manifest: null };
  return { rejected: false, errors: [], manifest: structuredClone(raw) };
}

/** Resolve a validated manifest path relative to the manifest itself. */
export function collectionDataUrl(manifest, field, manifestUrl, { shard } = {}) {
  if (!isObject(manifest) || manifest.schema !== COLLECTION_MANIFEST_SCHEMA || !COLLECTION_DATA_FIELDS.includes(field)) {
    throw new TypeError("A validated collection manifest and known data field are required");
  }
  let path = safeRelativeDataPath(manifest.data?.[field], { template: field === "detail_template" });
  if (!path) throw new TypeError(`Collection data path is unavailable: ${field}`);
  if (field === "detail_template") {
    if (!Number.isInteger(shard) || shard < 0 || shard > 999) throw new TypeError("Detail shard must be an integer from 0 to 999");
    path = path.replace("{shard}", String(shard).padStart(3, "0"));
  }
  return new URL(path, manifestUrl);
}
