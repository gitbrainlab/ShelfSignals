/**
 * Runtime contracts for ShelfSignals cover data.
 *
 * The compact index is deliberately sparse: records absent from `items` use
 * `unresolved_default`. Full source, match, and rights evidence lives behind a
 * lazy `provenance_ref`. Unsafe entries are never returned as displayable
 * covers; they become honest unresolved surrogates instead.
 */

// @ts-check

export const COVER_INDEX_SCHEMA = "shelfsignals-cover-index@1";
export const COVER_PROVENANCE_SCHEMA = "shelfsignals-cover-provenance@1";
export const LEGACY_VISUAL_SCHEMA = "shelfsignals-book-visuals@1";
export const UNRESOLVED_COVER_LABEL = "Cover not yet verified for this edition";
export const PROVIDER_REFERENCE_LABEL = "Exact-ISBN provider cover · visual review pending";
export const REVIEWED_COVER_LABEL = "Human-reviewed exact-edition cover";

export const COVER_STATUSES = Object.freeze(["verified", "provider_reference", "needs_review", "unresolved"]);
export const COVER_PROVIDERS = Object.freeze(["clark", "licensed", "openlibrary", "google_books"]);
export const COVER_SCOPES = Object.freeze(["clark_copy", "exact_edition", "work_level", "none"]);
export const COVER_CACHE_POLICIES = Object.freeze(["local_derivatives", "remote_only", "none"]);
export const COVER_RIGHTS_BASES = Object.freeze([
  "institution_permission",
  "open_license",
  "public_domain",
  "provider_display_terms",
  "pending",
  "unknown"
]);

const GOOGLE_COVER_HOSTS = new Set(["books.google.com", "books.googleusercontent.com"]);
const ISO_DATE = /^\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?Z)?$/;
const SHA256 = /^sha256:[a-f0-9]{64}$/i;

/** @typedef {{path: string, code: string, message: string}} ContractIssue */
/** @typedef {{public_display: boolean, basis: string, credit_line: string, derivatives_allowed: boolean, license_url: string}} CoverRights */
/** @typedef {{thumbnail_url: string, image_url: string, width: number, height: number}} CoverImage */

function isObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function cleanString(value) {
  return typeof value === "string" ? value.trim() : "";
}

function issue(path, code, message) {
  return { path, code, message };
}

function enumValue(value, allowed, fallback) {
  const candidate = cleanString(value);
  return allowed.includes(candidate) ? candidate : fallback;
}

function positiveInteger(value) {
  const number = Number(value);
  return Number.isInteger(number) && number > 0 ? number : 0;
}

function isIsoDate(value) {
  const text = cleanString(value);
  return Boolean(text && ISO_DATE.test(text) && Number.isFinite(Date.parse(text)));
}

function isSafeHttpsUrl(value) {
  try {
    return new URL(String(value)).protocol === "https:";
  } catch (_) {
    return false;
  }
}

function isSafeLocalUrl(value) {
  const text = cleanString(value);
  if (!text || text.startsWith("//") || /^[a-z][a-z\d+.-]*:/i.test(text)) return false;
  const path = text.split(/[?#]/, 1)[0];
  return !path.split("/").includes("..");
}

/** Return true only for a same-origin JSON path suitable for lazy loading. */
export function isSafeProvenanceRef(value) {
  const text = cleanString(value);
  if (!isSafeLocalUrl(text)) return false;
  try {
    const url = new URL(text, "https://shelfsignals.invalid/");
    return url.origin === "https://shelfsignals.invalid" && /\.json$/i.test(url.pathname);
  } catch (_) {
    return false;
  }
}

function normalizeProvider(value) {
  const provider = cleanString(value).toLowerCase().replace(/[ -]+/g, "_");
  if (provider === "google" || provider === "googlebooks") return "google_books";
  if (provider === "open_library") return "openlibrary";
  return COVER_PROVIDERS.includes(provider) ? provider : "";
}

function normalizeStatus(value) {
  const status = cleanString(value).toLowerCase();
  // The legacy visual manifest records an exact identifier and successful
  // image check, but no named visual reviewer. Preserve that useful provider
  // reference without silently upgrading it to a reviewed approval.
  if (status === "resolved" || status === "positive") return "provider_reference";
  if (status === "ambiguous" || status === "review") return "needs_review";
  return COVER_STATUSES.includes(status) ? status : "unresolved";
}

function normalizeReview(raw) {
  const review = isObject(raw) ? raw : {};
  return {
    status: cleanString(review.status || review.decision),
    reviewer: cleanString(review.reviewer),
    reviewed_at: isIsoDate(review.reviewed_at) ? cleanString(review.reviewed_at) : "",
    evidence_note: cleanString(review.evidence_note || review.reason)
  };
}

function hasHumanApproval(review) {
  return review?.status === "approved"
    && Boolean(review.reviewer)
    && Boolean(review.reviewed_at)
    && Boolean(review.evidence_note);
}

function isDisplayableStatus(status) {
  return status === "verified" || status === "provider_reference";
}

function inferredScope(raw, provider) {
  const explicit = enumValue(raw?.scope, COVER_SCOPES, "");
  if (explicit) return explicit;
  if (provider === "clark") return "clark_copy";
  if (/^(?:isbn|oclc|lccn)(?:_exact)?$/i.test(cleanString(raw?.match_method))) return "exact_edition";
  return "none";
}

function providerForRecord(raw) {
  return normalizeProvider(isObject(raw?.source) ? raw.source.provider : raw?.provider || raw?.source);
}

function defaultRights() {
  return {
    public_display: false,
    basis: "unknown",
    credit_line: "",
    derivatives_allowed: false,
    license_url: ""
  };
}

/** @returns {CoverRights} */
function normalizeRights(rawRights, provider, { legacyProviderTerms = false } = {}) {
  const raw = isObject(rawRights) ? rawRights : {};
  const basis = enumValue(raw.basis || raw.status, COVER_RIGHTS_BASES, "unknown");
  let publicDisplay = raw.public_display === true || raw.display === "allowed";
  let normalizedBasis = basis;
  if (legacyProviderTerms && !Object.keys(raw).length && ["openlibrary", "google_books"].includes(provider)) {
    publicDisplay = true;
    normalizedBasis = "provider_display_terms";
  }
  return {
    public_display: publicDisplay,
    basis: normalizedBasis,
    credit_line: cleanString(raw.credit_line || raw.attribution),
    derivatives_allowed: raw.derivatives_allowed === true || raw.derivatives === "allowed",
    license_url: isSafeHttpsUrl(raw.license_url) ? cleanString(raw.license_url) : ""
  };
}

function pixelDimensions(raw) {
  const dimensions = isObject(raw?.dimensions) ? raw.dimensions : {};
  const analyzed = raw?.image_analysis?.source_pixels || raw?.image_analysis?.stored_raster_pixels || {};
  return {
    width: positiveInteger(dimensions.width || raw?.width || raw?.image_width || analyzed.width),
    height: positiveInteger(dimensions.height || raw?.height || raw?.image_height || analyzed.height)
  };
}

/** @returns {CoverImage|null} */
function normalizeImage(raw) {
  const image = isObject(raw?.image) ? raw.image : raw || {};
  const source = isObject(raw?.source) ? raw.source : {};
  const imageUrl = cleanString(image.image_url || image.url || raw?.image_url || source.image_url);
  const thumbnailUrl = cleanString(image.thumbnail_url || image.thumbnail || raw?.thumbnail_url || source.thumbnail_url || imageUrl);
  const dimensions = pixelDimensions({ ...raw, ...image });
  if (!imageUrl && !thumbnailUrl) return null;
  return {
    image_url: imageUrl || thumbnailUrl,
    thumbnail_url: thumbnailUrl || imageUrl,
    width: dimensions.width,
    height: dimensions.height
  };
}

/** True when an image URL is compatible with its declared provider. */
export function isAllowedCoverImageUrl(value, provider) {
  const normalizedProvider = normalizeProvider(provider);
  const text = cleanString(value);
  if (!text || !normalizedProvider) return false;
  if (normalizedProvider === "clark") return isSafeLocalUrl(text);
  if (normalizedProvider === "licensed") return isSafeLocalUrl(text) || isSafeHttpsUrl(text);
  try {
    const url = new URL(text);
    if (url.protocol !== "https:") return false;
    if (normalizedProvider === "openlibrary") return url.hostname.toLowerCase() === "covers.openlibrary.org";
    return GOOGLE_COVER_HOSTS.has(url.hostname.toLowerCase());
  } catch (_) {
    return false;
  }
}

function providerPolicyAllows(provider, scope, cachePolicy) {
  if (provider === "clark") return scope === "clark_copy" && cachePolicy === "local_derivatives";
  if (provider === "openlibrary" || provider === "google_books") return scope === "exact_edition" && cachePolicy === "remote_only";
  if (provider === "licensed") return ["clark_copy", "exact_edition"].includes(scope)
    && ["local_derivatives", "remote_only"].includes(cachePolicy);
  return false;
}

function unresolvedDefault(raw) {
  const configured = typeof raw === "string" ? { label: raw } : isObject(raw) ? raw : {};
  return {
    status: "unresolved",
    provider: null,
    scope: "none",
    image: null,
    rights: defaultRights(),
    cache_policy: "none",
    provenance_ref: "",
    label: cleanString(configured.label) || UNRESOLVED_COVER_LABEL
  };
}

function normalizeCompactItem(id, raw, defaultItem) {
  const warnings = [];
  if (!isObject(raw)) {
    return { value: { ...defaultItem }, warnings: [issue(`items.${id}`, "invalid_item", "Cover entry is not an object.")] };
  }
  const status = normalizeStatus(raw.status);
  const provider = providerForRecord(raw);
  const scope = inferredScope(raw, provider);
  const cachePolicy = enumValue(raw.cache_policy, COVER_CACHE_POLICIES, isDisplayableStatus(status) ? "" : "none");
  const rights = normalizeRights(raw.rights, provider);
  const review = normalizeReview(raw.review);
  const image = normalizeImage(raw);
  const provenanceRef = cleanString(raw.provenance_ref);
  const label = cleanString(raw.label) || (status === "verified"
    ? REVIEWED_COVER_LABEL
    : status === "provider_reference" ? PROVIDER_REFERENCE_LABEL : UNRESOLVED_COVER_LABEL);

  let safe = isDisplayableStatus(status);
  if (safe && !provider) warnings.push(issue(`items.${id}.provider`, "invalid_provider", "Displayable cover has no supported provider."));
  if (safe && !providerPolicyAllows(provider, scope, cachePolicy)) warnings.push(issue(`items.${id}`, "provider_policy", "Provider, scope, and cache policy are incompatible."));
  if (safe && !rights.public_display) warnings.push(issue(`items.${id}.rights`, "display_not_allowed", "Cover lacks public-display authority."));
  if (safe && (!image || !image.width || !image.height)) warnings.push(issue(`items.${id}.image`, "missing_dimensions", "Displayable cover needs positive pixel dimensions."));
  if (safe && image && (!isAllowedCoverImageUrl(image.image_url, provider) || !isAllowedCoverImageUrl(image.thumbnail_url, provider))) {
    warnings.push(issue(`items.${id}.image`, "unsafe_url", "Cover URL is incompatible with its provider."));
  }
  if (safe && !isSafeProvenanceRef(provenanceRef)) warnings.push(issue(`items.${id}.provenance_ref`, "unsafe_provenance_ref", "Displayable cover needs a safe lazy provenance reference."));
  if (safe && provider === "google_books" && !rights.credit_line) warnings.push(issue(`items.${id}.rights.credit_line`, "missing_attribution", "Google Books display requires an attribution line."));
  if (safe && status === "provider_reference" && (!["openlibrary", "google_books"].includes(provider) || scope !== "exact_edition" || cachePolicy !== "remote_only")) {
    warnings.push(issue(`items.${id}`, "invalid_provider_reference", "An unreviewed provider reference must be an exact-edition, remote-only Open Library or Google Books image."));
  }
  if (safe && status === "verified" && !hasHumanApproval(review)) warnings.push(issue(`items.${id}.review`, "missing_human_approval", "A verified cover needs a named reviewer, review date, and evidence note."));
  safe = safe && warnings.length === 0;

  if (!safe && isDisplayableStatus(status)) {
    warnings.push(issue(`items.${id}`, "demoted_to_unresolved", "Unsafe displayable cover was replaced by the unresolved surrogate."));
    return { value: { ...defaultItem, provenance_ref: isSafeProvenanceRef(provenanceRef) ? provenanceRef : "" }, warnings };
  }

  if (!isDisplayableStatus(status)) {
    if (image) warnings.push(issue(`items.${id}.image`, "nonpublic_image_removed", "Unverified entries cannot expose an image."));
    return {
      value: {
        ...defaultItem,
        status,
        provider: provider || null,
        scope,
        provenance_ref: isSafeProvenanceRef(provenanceRef) ? provenanceRef : "",
        label: cleanString(raw.label) || UNRESOLVED_COVER_LABEL
      },
      warnings
    };
  }

  return {
    value: {
      status,
      provider,
      scope,
      image,
      rights,
      cache_policy: cachePolicy,
      provenance_ref: provenanceRef,
      review,
      label
    },
    warnings
  };
}

function catalogIdSet(value) {
  if (value instanceof Set) return new Set([...value].map(String));
  return new Set(Array.isArray(value) ? value.filter(Boolean).map(String) : []);
}

function rejectedCoverIndex(errors, defaultItem = unresolvedDefault(null)) {
  return {
    schema: COVER_INDEX_SCHEMA,
    generated_at: null,
    source: null,
    unresolved_default: defaultItem,
    items: {},
    rejected: true,
    errors,
    warnings: []
  };
}

/**
 * Parse the sparse public cover index. Missing item IDs intentionally resolve
 * to `unresolved_default`; unexpected IDs are rejected when catalog context is
 * supplied.
 */
export function parseCoverIndex(raw = {}, { catalogIds = [], datasetSha256 = "" } = {}) {
  const errors = [];
  if (!isObject(raw) || raw.schema !== COVER_INDEX_SCHEMA) {
    return rejectedCoverIndex([issue("schema", "unsupported_schema", `Expected ${COVER_INDEX_SCHEMA}.`)]);
  }
  if (!isObject(raw.items)) errors.push(issue("items", "invalid_items", "Cover index items must be an object."));
  if (!isObject(raw.source)) errors.push(issue("source", "invalid_source", "Cover index needs catalog source metadata."));
  const ids = catalogIdSet(catalogIds);
  const sourceCount = Number(raw.source?.record_count);
  if (!Number.isInteger(sourceCount) || sourceCount < 0) errors.push(issue("source.record_count", "invalid_record_count", "Cover index needs a non-negative catalog record count."));
  if (ids.size && sourceCount !== ids.size) errors.push(issue("source.record_count", "catalog_count_mismatch", "Cover index does not describe the active catalog."));
  if (datasetSha256 && raw.source?.dataset_sha256 !== datasetSha256) errors.push(issue("source.dataset_sha256", "catalog_checksum_mismatch", "Cover index checksum does not match the active catalog."));
  if (!SHA256.test(raw.source?.dataset_sha256 || "")) errors.push(issue("source.dataset_sha256", "invalid_checksum", "Catalog checksum must be SHA-256."));
  if (raw.generated_at && !isIsoDate(raw.generated_at)) errors.push(issue("generated_at", "invalid_date", "Generated date must be ISO-8601."));

  const defaultItem = unresolvedDefault(raw.unresolved_default || { label: raw.unresolved_label });
  defaultItem.label = UNRESOLVED_COVER_LABEL;
  if (errors.length) return rejectedCoverIndex(errors, defaultItem);

  const items = {};
  const warnings = [];
  for (const [id, item] of Object.entries(raw.items)) {
    if (!id || (ids.size && !ids.has(id))) {
      errors.push(issue(`items.${id}`, "unknown_catalog_id", "Cover index contains an ID outside the active catalog."));
      continue;
    }
    const normalized = normalizeCompactItem(id, item, defaultItem);
    items[id] = normalized.value;
    warnings.push(...normalized.warnings);
  }
  if (errors.length) return rejectedCoverIndex(errors, defaultItem);
  return {
    ...raw,
    source: { ...raw.source, record_count: sourceCount },
    unresolved_default: defaultItem,
    unresolved_label: UNRESOLVED_COVER_LABEL,
    items,
    rejected: false,
    errors: [],
    warnings
  };
}

/** Resolve a record to a displayable cover reference or an explicit unresolved surrogate. */
export function getRecordCoverState(record = {}, index = {}) {
  const id = cleanString(record.id);
  const fallback = isObject(index.unresolved_default) ? index.unresolved_default : unresolvedDefault(null);
  return id && isObject(index.items?.[id]) ? index.items[id] : { ...fallback, label: UNRESOLVED_COVER_LABEL };
}

export function canDisplayCover(record = {}) {
  const image = isObject(record.image) ? record.image : null;
  return isDisplayableStatus(record.status)
    && record.rights?.public_display === true
    && Boolean(image?.image_url && image?.thumbnail_url)
    && isAllowedCoverImageUrl(image.image_url, record.provider)
    && isAllowedCoverImageUrl(image.thumbnail_url, record.provider);
}

/** Deterministic shard name for provenance stores that choose 16-way sharding. */
export function coverProvenanceShard(id = "") {
  let hash = 2166136261;
  for (const character of String(id)) {
    hash ^= character.codePointAt(0);
    hash = Math.imul(hash, 16777619);
  }
  return (hash >>> 0 & 15).toString(16);
}

function normalizeMatchedIdentifiers(raw, provider, catalogId) {
  const source = Array.isArray(raw?.matched_identifiers)
    ? raw.matched_identifiers
    : Array.isArray(raw?.provenance?.matched_identifiers) ? raw.provenance.matched_identifiers : [];
  const values = source.map(candidate => ({
    type: cleanString(candidate?.type).toLowerCase(),
    value: cleanString(candidate?.value)
  })).filter(candidate => candidate.type && candidate.value);
  if (values.length) return values;
  const sourceId = cleanString(raw?.source_id);
  const method = cleanString(raw?.match_method).toLowerCase().replace(/_exact$/, "");
  if (sourceId && ["isbn", "oclc", "lccn"].includes(method)) return [{ type: method, value: sourceId }];
  if (provider === "clark" && catalogId) return [{ type: "catalog_id", value: catalogId }];
  return [];
}

function normalizeFullRecord(id, raw, { legacy = false } = {}) {
  const warnings = [];
  if (!isObject(raw)) return { value: null, warnings: [issue(`items.${id}`, "invalid_item", "Provenance entry is not an object.")] };
  const provider = providerForRecord(raw);
  const status = normalizeStatus(raw.status);
  const scope = inferredScope(raw, provider);
  const image = normalizeImage(raw);
  const rights = normalizeRights(raw.rights, provider, { legacyProviderTerms: legacy });
  const review = normalizeReview(raw.review);
  if (!rights.credit_line) rights.credit_line = cleanString(raw.attribution);
  const cachePolicy = enumValue(raw.cache_policy, COVER_CACHE_POLICIES,
    ["openlibrary", "google_books"].includes(provider) ? "remote_only" : isDisplayableStatus(status) ? "" : "none");
  const sourceObject = isObject(raw.source) ? raw.source : {};
  const sourceUrl = cleanString(sourceObject.source_url || sourceObject.url || raw.source_url);
  const sourceId = cleanString(sourceObject.source_id || sourceObject.id || raw.source_id);
  const matchedIdentifiers = normalizeMatchedIdentifiers(raw, provider, id);
  const selectionRationale = cleanString(raw.selection_rationale)
    || (raw.match_method ? `Selected by ${cleanString(raw.match_method).replaceAll("_", " ")} match.` : "");
  const retrievedAt = cleanString(raw.retrieved_at || raw.checked_at);
  const checksum = cleanString(raw.checksum || raw.image?.checksum || raw.image_analysis?.source_sha256 || raw.provenance?.image_validation?.sha256);

  let safe = isDisplayableStatus(status);
  if (safe && !providerPolicyAllows(provider, scope, cachePolicy)) warnings.push(issue(`items.${id}`, "provider_policy", "Provider, scope, and cache policy are incompatible."));
  if (safe && !rights.public_display) warnings.push(issue(`items.${id}.rights`, "display_not_allowed", "Cover lacks public-display authority."));
  if (safe && (!image || !image.width || !image.height)) warnings.push(issue(`items.${id}.image`, "missing_dimensions", "Displayable cover needs positive pixel dimensions."));
  if (safe && image && (!isAllowedCoverImageUrl(image.image_url, provider) || !isAllowedCoverImageUrl(image.thumbnail_url, provider))) warnings.push(issue(`items.${id}.image`, "unsafe_url", "Cover URL is incompatible with its provider."));
  if (safe && !sourceId) warnings.push(issue(`items.${id}.source.source_id`, "missing_source_id", "Displayable cover needs a provider source ID."));
  if (safe && !isSafeHttpsUrl(sourceUrl)) warnings.push(issue(`items.${id}.source.source_url`, "unsafe_source_url", "Displayable cover needs an HTTPS source record."));
  if (safe && !matchedIdentifiers.length) warnings.push(issue(`items.${id}.matched_identifiers`, "missing_match", "Displayable cover needs its matched identifiers."));
  if (safe && !selectionRationale) warnings.push(issue(`items.${id}.selection_rationale`, "missing_rationale", "Displayable cover needs a selection rationale."));
  if (safe && !isIsoDate(retrievedAt)) warnings.push(issue(`items.${id}.retrieved_at`, "invalid_date", "Displayable cover needs an ISO retrieval date."));
  if (safe && cachePolicy === "local_derivatives" && (!SHA256.test(checksum) || !rights.derivatives_allowed)) {
    warnings.push(issue(`items.${id}.checksum`, "uncleared_derivative", "Locally cached cover needs derivative permission and a SHA-256 checksum."));
  }
  if (safe && status === "provider_reference" && (!["openlibrary", "google_books"].includes(provider) || scope !== "exact_edition" || cachePolicy !== "remote_only")) {
    warnings.push(issue(`items.${id}`, "invalid_provider_reference", "An unreviewed provider reference must be an exact-edition, remote-only Open Library or Google Books image."));
  }
  if (safe && status === "verified" && !hasHumanApproval(review)) warnings.push(issue(`items.${id}.review`, "missing_human_approval", "A verified cover needs a named reviewer, review date, and evidence note."));
  safe = safe && warnings.length === 0;

  return {
    value: {
      catalog_id: id,
      status: safe ? status : status === "needs_review" ? "needs_review" : "unresolved",
      provider: provider || null,
      scope,
      image: safe ? image : null,
      matched_identifiers: matchedIdentifiers,
      selection_rationale: selectionRationale,
      source: {
        provider: provider || null,
        source_id: sourceId,
        source_url: isSafeHttpsUrl(sourceUrl) ? sourceUrl : ""
      },
      rights,
      retrieved_at: isIsoDate(retrievedAt) ? retrievedAt : "",
      checksum: SHA256.test(checksum) ? checksum : null,
      cache_policy: safe ? cachePolicy : "none",
      review,
      label: safe ? (status === "verified" ? REVIEWED_COVER_LABEL : PROVIDER_REFERENCE_LABEL) : UNRESOLVED_COVER_LABEL
    },
    warnings
  };
}

function rejectedProvenance(errors) {
  return { schema: COVER_PROVENANCE_SCHEMA, generated_at: null, items: {}, rejected: true, errors, warnings: [] };
}

/**
 * Parse a provenance manifest or one record. Legacy `book_visuals` manifests
 * are normalized, but display rights are inferred only for their documented
 * Open Library/Google provider-display paths; local assets still require
 * explicit rights.
 */
export function parseCoverProvenance(raw = {}, { recordId = "", catalogIds = [], datasetSha256 = "" } = {}) {
  const ids = catalogIdSet(catalogIds);
  const legacy = raw?.schema === LEGACY_VISUAL_SCHEMA;
  const current = raw?.schema === COVER_PROVENANCE_SCHEMA;
  let sourceItems = null;
  if (current && isObject(raw.items)) sourceItems = raw.items;
  else if (legacy && isObject(raw.items)) sourceItems = raw.items;
  else if (recordId && isObject(raw) && !raw.schema) sourceItems = { [recordId]: raw };
  if (!sourceItems) return rejectedProvenance([issue("schema", "unsupported_schema", `Expected ${COVER_PROVENANCE_SCHEMA}.`)]);

  const errors = [];
  const warnings = [];
  const items = {};
  if (current) {
    const sourceCount = Number(raw.source?.record_count);
    if (!isObject(raw.source)) errors.push(issue("source", "invalid_source", "Cover provenance needs catalog source metadata."));
    if (!Number.isInteger(sourceCount) || sourceCount < 0) errors.push(issue("source.record_count", "invalid_record_count", "Cover provenance needs a non-negative catalog record count."));
    if (ids.size && sourceCount !== ids.size) errors.push(issue("source.record_count", "catalog_count_mismatch", "Cover provenance does not describe the active catalog."));
    if (!SHA256.test(raw.source?.dataset_sha256 || "")) errors.push(issue("source.dataset_sha256", "invalid_checksum", "Cover provenance catalog checksum must be SHA-256."));
    if (datasetSha256 && raw.source?.dataset_sha256 !== datasetSha256) errors.push(issue("source.dataset_sha256", "catalog_checksum_mismatch", "Cover provenance checksum does not match the active catalog."));
    if (!isIsoDate(raw.generated_at)) errors.push(issue("generated_at", "invalid_date", "Cover provenance needs an ISO-8601 generation date."));
  }
  if (errors.length) return rejectedProvenance(errors);
  for (const [id, item] of Object.entries(sourceItems)) {
    if (!id || (recordId && id !== recordId) || (ids.size && !ids.has(id))) continue;
    const normalized = normalizeFullRecord(id, item, { legacy });
    if (normalized.value) items[id] = normalized.value;
    warnings.push(...normalized.warnings);
  }
  if (recordId && !items[recordId]) errors.push(issue(`items.${recordId}`, "missing_record", "Requested cover provenance is absent."));
  if (errors.length) return rejectedProvenance(errors);
  return {
    schema: COVER_PROVENANCE_SCHEMA,
    generated_at: isIsoDate(raw.generated_at) ? raw.generated_at : null,
    source: current ? { ...raw.source } : null,
    items,
    rejected: false,
    errors: [],
    warnings
  };
}

export function getRecordCoverProvenance(record = {}, manifest = {}) {
  const id = cleanString(record.id);
  return id && isObject(manifest.items?.[id]) ? manifest.items[id] : null;
}
