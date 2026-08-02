/**
 * Fail-closed collection manifest contracts.
 *
 * Manifests contain presentation configuration and relative public-data paths;
 * they are not a source of bibliographic evidence. Every collection payload
 * still validates its own source identity in `catalog-data.js`.
 */

// @ts-check

export const COLLECTION_MANIFEST_SCHEMA = "shelfsignals-collection-manifest@1";
export const COLLECTION_MANIFEST_SCHEMA_V2 = "shelfsignals-collection-manifest@2";

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
export const COLLECTION_COVERAGE_FIELDS_V2 = Object.freeze([
  "status",
  "entity_type",
  "record_count",
  "historical_entry_count",
  "historical_position_count",
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
export const COLLECTION_CORPUS_IDS = Object.freeze(["catalog", "historical"]);
export const COLLECTION_ENTITY_TYPES = Object.freeze(["bibliographic_record", "catalog_instance", "sowerby_entry"]);

// Hierarchy is collection-level: the same Sowerby hierarchy can contextualize
// both the catalog evidence layer and the historical corpus. Every other path
// can contain record IDs or source identity and must therefore be routed by
// corpus once a manifest declares more than one corpus.
export const COLLECTION_CORPUS_DATA_FIELDS = Object.freeze(
  COLLECTION_DATA_FIELDS.filter(field => field !== "hierarchy")
);

const MANIFEST_FIELDS_V1 = Object.freeze([
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
const MANIFEST_FIELDS_V2 = Object.freeze([...MANIFEST_FIELDS_V1.slice(0, -1), "corpora", "review"]);
const SHELF_FIELDS = Object.freeze(["storage_key", "receipt_name"]);
const ORDER_FIELDS = Object.freeze(["id", "label"]);
const DEFAULT_FIELDS = Object.freeze(["corpus", "order"]);
const REVIEW_FIELDS = Object.freeze(["enabled", "code_sha256", "session_key", "warning"]);
const REQUIRED_DATA_FIELDS = Object.freeze(["core", "search", "detail_template", "detail_index"]);
const REQUIRED_CORPUS_DATA_FIELDS = Object.freeze([...REQUIRED_DATA_FIELDS, "validation"]);
const CORPUS_COPY_FIELDS = Object.freeze(["status_label", "introduction", "coverage_statement", "source_label"]);
const CORPUS_FIELDS = Object.freeze([
  "id",
  "label",
  "record_id_prefix",
  "copy",
  "coverage",
  "data",
  "features",
  "facets",
  "orders",
  "default_order"
]);
const SAFE_COLLECTION_ID = /^[a-z][a-z0-9-]{0,63}$/;
const SAFE_STORAGE_KEY = /^[A-Za-z0-9_.:-]+$/;
const SAFE_RECEIPT_NAME = /^[A-Za-z0-9][A-Za-z0-9._ -]{0,127}\.json$/i;
const SHA256 = /^sha256:[a-f0-9]{64}$/i;
const SAFE_RECORD_PREFIX = /^[a-z][a-z0-9-]{2,63}-$/;

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
  const isV2 = raw?.schema === COLLECTION_MANIFEST_SCHEMA_V2;
  const manifestFields = isV2 ? MANIFEST_FIELDS_V2 : MANIFEST_FIELDS_V1;
  if (!requireExactKeys(raw, manifestFields, "", errors, { optional: ["review"] })) {
    return { rejected: true, errors, manifest: null };
  }
  if (![COLLECTION_MANIFEST_SCHEMA, COLLECTION_MANIFEST_SCHEMA_V2].includes(raw.schema)) errors.push(issue("schema", "schema", "Unsupported collection manifest schema"));

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

  const coverageFields = isV2 ? COLLECTION_COVERAGE_FIELDS_V2 : COLLECTION_COVERAGE_FIELDS;
  if (requireExactKeys(raw.coverage, coverageFields, "coverage", errors)) {
    if (!["canonical", "beta", "complete"].includes(raw.coverage.status)) {
      errors.push(issue("coverage.status", "status", "Coverage status is invalid"));
    }
    if (!cleanString(raw.coverage.entity_type)) errors.push(issue("coverage.entity_type", "string", "Coverage entity type is required"));
    if (!Number.isInteger(raw.coverage.record_count) || raw.coverage.record_count <= 0) {
      errors.push(issue("coverage.record_count", "count", "Coverage record count must be positive"));
    }
    for (const field of ["historical_entry_count", ...(isV2 ? ["historical_position_count"] : []), "historical_volume_count", "established_sowerby_links"]) {
      if (!nonNegativeIntegerOrNull(raw.coverage[field])) errors.push(issue(`coverage.${field}`, "count", "Coverage count must be a non-negative integer or null"));
    }
    if (isV2 && Number.isInteger(raw.coverage.historical_entry_count) && Number.isInteger(raw.coverage.historical_position_count)
      && raw.coverage.historical_position_count < raw.coverage.historical_entry_count) {
      errors.push(issue("coverage.historical_position_count", "count", "Historical position count cannot be smaller than the source-backed entry count"));
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

  const corpora = Array.isArray(raw.corpora) ? raw.corpora : [];
  const review = raw.review;
  if (review !== undefined) {
    if (requireExactKeys(review, REVIEW_FIELDS, "review", errors)) {
      if (review.enabled !== true) errors.push(issue("review.enabled", "boolean", "An included review configuration must be enabled"));
      if (!SHA256.test(cleanString(review.code_sha256))) errors.push(issue("review.code_sha256", "sha256", "Review code digest is invalid"));
      if (cleanString(review.session_key) !== `shelfsignals_review:${id}`) errors.push(issue("review.session_key", "storage", "Review session key is unsafe or belongs to another collection"));
      if (!cleanString(review.warning)) errors.push(issue("review.warning", "string", "Review warning is required"));
      const hasReviewMedia = raw.data?.review_media || (isV2 && corpora.some(corpus => corpus?.data?.review_media));
      if (!hasReviewMedia) errors.push(issue("data.review_media", "path", "At least one review-media path is required when review mode is enabled"));
    }
  } else if (raw.data?.review_media || (isV2 && corpora.some(corpus => corpus?.data?.review_media))) {
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
    const enabled = dataField === "hierarchy" && isV2
      ? corpora.some(corpus => corpus?.features?.[feature] === true)
      : raw.features?.[feature] === true;
    if (enabled && !raw.data?.[dataField]) {
      errors.push(issue(`data.${dataField}`, "feature", `Data path is required when features.${feature} is enabled`));
    }
  }

  if (isV2) {
    if (!Array.isArray(raw.corpora) || raw.corpora.length === 0) {
      errors.push(issue("corpora", "array", "Version-2 manifests require a non-empty corpora array"));
    } else {
      const seenCorpusIds = new Set();
      const corpusById = new Map();
      const routedPaths = new Map();
      const topLevelCorpusFields = COLLECTION_CORPUS_DATA_FIELDS.filter(field => Object.hasOwn(raw.data || {}, field));
      const seenPrefixes = [];

      raw.corpora.forEach((corpus, index) => {
        const path = `corpora[${index}]`;
        if (!requireExactKeys(corpus, CORPUS_FIELDS, path, errors)) return;
        const corpusId = cleanString(corpus.id);
        if (!COLLECTION_CORPUS_IDS.includes(corpusId) || seenCorpusIds.has(corpusId)) {
          errors.push(issue(`${path}.id`, "corpus", "Corpus ID is unknown or duplicated"));
        }
        seenCorpusIds.add(corpusId);
        corpusById.set(corpusId, corpus);

        if (!cleanString(corpus.label)) errors.push(issue(`${path}.label`, "string", "Corpus label is required"));
        const prefix = cleanString(corpus.record_id_prefix).toLocaleLowerCase();
        if (!SAFE_RECORD_PREFIX.test(prefix)) errors.push(issue(`${path}.record_id_prefix`, "id", "Corpus record prefix is unsafe"));
        if (seenPrefixes.some(previous => prefix.startsWith(previous) || previous.startsWith(prefix))) {
          errors.push(issue(`${path}.record_id_prefix`, "duplicate", "Corpus record prefixes must be unique and non-overlapping"));
        }
        seenPrefixes.push(prefix);

        if (requireExactKeys(corpus.copy, CORPUS_COPY_FIELDS, `${path}.copy`, errors)) {
          for (const field of CORPUS_COPY_FIELDS) {
            if (!cleanString(corpus.copy[field])) errors.push(issue(`${path}.copy.${field}`, "string", "Corpus copy must be a non-empty string"));
          }
        }

        if (requireExactKeys(corpus.coverage, COLLECTION_COVERAGE_FIELDS_V2, `${path}.coverage`, errors)) {
          if (!["canonical", "beta", "complete"].includes(corpus.coverage.status)) errors.push(issue(`${path}.coverage.status`, "status", "Corpus coverage status is invalid"));
          if (!COLLECTION_ENTITY_TYPES.includes(corpus.coverage.entity_type)) errors.push(issue(`${path}.coverage.entity_type`, "entity", "Corpus entity type is invalid"));
          if (id === "jefferson" && corpusId === "catalog" && corpus.coverage.entity_type !== "catalog_instance") errors.push(issue(`${path}.coverage.entity_type`, "entity", "The Jefferson catalog corpus must contain catalog instances"));
          if (corpusId === "historical" && corpus.coverage.entity_type !== "sowerby_entry") errors.push(issue(`${path}.coverage.entity_type`, "entity", "The historical corpus must contain Sowerby entries"));
          if (!Number.isInteger(corpus.coverage.record_count) || corpus.coverage.record_count <= 0) errors.push(issue(`${path}.coverage.record_count`, "count", "Corpus record count must be positive"));
          for (const field of ["historical_entry_count", "historical_position_count", "historical_volume_count", "established_sowerby_links"]) {
            if (!nonNegativeIntegerOrNull(corpus.coverage[field])) errors.push(issue(`${path}.coverage.${field}`, "count", "Corpus coverage count must be a non-negative integer or null"));
          }
          if (Number.isInteger(corpus.coverage.historical_entry_count) && Number.isInteger(corpus.coverage.historical_position_count)
            && corpus.coverage.historical_position_count < corpus.coverage.historical_entry_count) {
            errors.push(issue(`${path}.coverage.historical_position_count`, "count", "Historical position count cannot be smaller than the source-backed entry count"));
          }
        }

        if (requireExactKeys(corpus.features, COLLECTION_FEATURE_FIELDS, `${path}.features`, errors)) {
          for (const field of COLLECTION_FEATURE_FIELDS) {
            if (typeof corpus.features[field] !== "boolean") errors.push(issue(`${path}.features.${field}`, "boolean", "Corpus feature flags must be booleans"));
          }
        }

        if (requireExactKeys(corpus.data, COLLECTION_CORPUS_DATA_FIELDS, `${path}.data`, errors, {
          optional: COLLECTION_CORPUS_DATA_FIELDS.filter(field => !REQUIRED_CORPUS_DATA_FIELDS.includes(field))
        })) {
          const localPaths = new Map();
          for (const [field, value] of Object.entries(corpus.data)) {
            const dataPath = safeRelativeDataPath(value, { template: field === "detail_template" });
            if (!dataPath) {
              errors.push(issue(`${path}.data.${field}`, "path", "Corpus data path must be safe and collection-relative"));
              continue;
            }
            const normalized = field === "detail_template" ? dataPath.replace("{shard}", "000") : dataPath;
            if (localPaths.has(normalized)) errors.push(issue(`${path}.data.${field}`, "duplicate", `Corpus data path duplicates ${localPaths.get(normalized)}`));
            else localPaths.set(normalized, field);
            if (routedPaths.has(normalized)) errors.push(issue(`${path}.data.${field}`, "duplicate", `Corpus data path duplicates ${routedPaths.get(normalized)}`));
            else routedPaths.set(normalized, `${path}.data.${field}`);
          }
          for (const [feature, dataField] of requiredFeaturePaths) {
            if (dataField !== "hierarchy" && corpus.features?.[feature] === true && !corpus.data?.[dataField]) {
              errors.push(issue(`${path}.data.${dataField}`, "feature", `Corpus data path is required when features.${feature} is enabled`));
            }
          }
        }

        if (!Array.isArray(corpus.facets) || corpus.facets.length === 0) {
          errors.push(issue(`${path}.facets`, "array", "At least one corpus facet is required"));
        } else {
          const seen = new Set();
          corpus.facets.forEach((facet, facetIndex) => {
            if (!COLLECTION_FACET_IDS.includes(facet) || seen.has(facet)) errors.push(issue(`${path}.facets[${facetIndex}]`, "facet", "Corpus facet is unknown or duplicated"));
            seen.add(facet);
          });
        }

        if (!Array.isArray(corpus.orders) || corpus.orders.length === 0) {
          errors.push(issue(`${path}.orders`, "array", "At least one corpus order is required"));
        } else {
          const seen = new Set();
          corpus.orders.forEach((order, orderIndex) => {
            const orderPath = `${path}.orders[${orderIndex}]`;
            if (!requireExactKeys(order, ORDER_FIELDS, orderPath, errors)) return;
            if (!COLLECTION_ORDER_IDS.includes(order.id) || seen.has(order.id)) errors.push(issue(`${orderPath}.id`, "order", "Corpus order is unknown or duplicated"));
            if (!cleanString(order.label)) errors.push(issue(`${orderPath}.label`, "string", "Corpus order label is required"));
            seen.add(order.id);
          });
          if (!seen.has(corpus.default_order)) errors.push(issue(`${path}.default_order`, "order", "Corpus default order must be declared"));
          if (corpusId === "historical" && (!seen.has("sowerby") || corpus.default_order !== "sowerby")) {
            errors.push(issue(`${path}.default_order`, "order", "The historical corpus must declare and default to Sowerby order"));
          }
        }
      });

      const defaultCorpus = corpusById.get(raw.defaults?.corpus);
      if (!defaultCorpus) {
        errors.push(issue("defaults.corpus", "corpus", "Default corpus must have a declared corpus package"));
      } else {
        if (raw.defaults.order !== defaultCorpus.default_order) errors.push(issue("defaults.order", "order", "Default order must match the default corpus"));
        if (JSON.stringify(raw.coverage) !== JSON.stringify(defaultCorpus.coverage)) errors.push(issue("coverage", "corpus", "Top-level coverage must describe the default corpus"));
        for (const field of CORPUS_COPY_FIELDS) {
          if (raw.copy?.[field] !== defaultCorpus.copy?.[field]) errors.push(issue(`copy.${field}`, "corpus", "Top-level corpus copy must match the default corpus"));
        }
        if (JSON.stringify(raw.facets) !== JSON.stringify(defaultCorpus.facets)
          || JSON.stringify(raw.orders) !== JSON.stringify(defaultCorpus.orders)
          || JSON.stringify(raw.features) !== JSON.stringify(defaultCorpus.features)) {
          errors.push(issue("defaults", "corpus", "Top-level features, facets, and orders must match the default corpus"));
        }
        for (const field of topLevelCorpusFields) {
          if (raw.data?.[field] !== defaultCorpus.data?.[field]) {
            errors.push(issue(`data.${field}`, "corpus", "Top-level routed data must match the default corpus"));
          }
        }
      }
    }
  }

  if (errors.length) return { rejected: true, errors, manifest: null };
  return { rejected: false, errors: [], manifest: structuredClone(raw) };
}

/** Return declared corpora, or a normalized single-corpus view of a legacy manifest. */
export function collectionCorpusOptions(manifest) {
  if (!isObject(manifest) || ![COLLECTION_MANIFEST_SCHEMA, COLLECTION_MANIFEST_SCHEMA_V2].includes(manifest.schema)) return [];
  if (manifest.schema === COLLECTION_MANIFEST_SCHEMA_V2 && Array.isArray(manifest.corpora) && manifest.corpora.length) {
    return manifest.corpora.map(corpus => structuredClone(corpus));
  }
  const corpusId = COLLECTION_CORPUS_IDS.includes(manifest.defaults?.corpus) ? manifest.defaults.corpus : "catalog";
  return [{
    id: corpusId,
    label: corpusId === "historical" ? "Historical Sowerby corpus" : (manifest.id === "jefferson" ? "Current LOC catalog" : "Catalog"),
    record_id_prefix: manifest.id === "jefferson" ? "jefferson-loc-" : "",
    copy: {
      status_label: manifest.copy?.status_label || "Collection",
      introduction: manifest.copy?.introduction || "",
      coverage_statement: manifest.copy?.coverage_statement || "",
      source_label: manifest.copy?.source_label || "source catalog"
    },
    coverage: structuredClone(manifest.coverage || {}),
    data: structuredClone(manifest.data || {}),
    features: structuredClone(manifest.features || {}),
    facets: [...(manifest.facets || [])],
    orders: structuredClone(manifest.orders || []),
    default_order: manifest.defaults?.order || manifest.orders?.[0]?.id || "catalog"
  }];
}

/** Select a declared corpus, falling back only to the manifest's validated default. */
export function resolveCollectionCorpus(manifest, requestedCorpus = "") {
  const corpora = collectionCorpusOptions(manifest);
  if (!corpora.length) return null;
  const requested = cleanString(requestedCorpus).toLocaleLowerCase();
  return corpora.find(corpus => corpus.id === requested)
    || corpora.find(corpus => corpus.id === manifest.defaults?.corpus)
    || corpora[0];
}

/**
 * Resolve URL state without breaking pre-corpus record deep links. Prefix
 * inference applies only when the URL omitted `corpus`; an explicit corpus is
 * never silently changed to accommodate a foreign record ID.
 */
export function resolveCollectionCorpusForState(manifest, { requestedCorpus = "", recordId = "" } = {}) {
  const requested = cleanString(requestedCorpus).toLocaleLowerCase();
  if (requested) return resolveCollectionCorpus(manifest, requested);
  const record = cleanString(recordId);
  if (record) {
    const matches = collectionCorpusOptions(manifest).filter(corpus => {
      const prefix = cleanString(corpus.record_id_prefix).toLocaleLowerCase();
      return prefix && record.startsWith(prefix);
    });
    if (matches.length === 1) return matches[0];
  }
  return resolveCollectionCorpus(manifest, "");
}

/** Resolve a validated manifest path relative to the manifest itself. */
export function collectionDataUrl(manifest, field, manifestUrl, { shard, corpus = "" } = {}) {
  if (!isObject(manifest) || ![COLLECTION_MANIFEST_SCHEMA, COLLECTION_MANIFEST_SCHEMA_V2].includes(manifest.schema) || !COLLECTION_DATA_FIELDS.includes(field)) {
    throw new TypeError("A validated collection manifest and known data field are required");
  }
  const selectedCorpus = resolveCollectionCorpus(manifest, corpus);
  if (corpus && (!selectedCorpus || selectedCorpus.id !== corpus)) throw new TypeError(`Collection corpus is unavailable: ${corpus}`);
  const corpusRouted = manifest.schema === COLLECTION_MANIFEST_SCHEMA_V2 && COLLECTION_CORPUS_DATA_FIELDS.includes(field);
  const data = corpusRouted ? selectedCorpus?.data : manifest.data;
  let path = safeRelativeDataPath(data?.[field], { template: field === "detail_template" });
  if (!path) throw new TypeError(`Collection data path is unavailable: ${field}`);
  if (field === "detail_template") {
    if (!Number.isInteger(shard) || shard < 0 || shard > 999) throw new TypeError("Detail shard must be an integer from 0 to 999");
    path = path.replace("{shard}", String(shard).padStart(3, "0"));
  }
  return new URL(path, manifestUrl);
}
