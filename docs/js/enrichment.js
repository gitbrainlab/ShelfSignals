import { estimateBookThickness, profileFromRecord } from "./physical.js";

export const EDITION_ENRICHMENT_SCHEMA = "shelfsignals-edition-enrichment@1";

const MATCH_METHODS = new Set(["isbn_exact", "oclc_lccn_exact", "oclc_exact", "lccn_exact"]);
const CLAIM_FIELDS = new Set(["physical_format", "physical_dimensions", "weight", "number_of_pages", "pagination"]);
const ARRAY_FIELDS = new Set(["publishers", "lc_classifications", "dewey_decimal_class", "series", "genres", "languages", "cover_ids", "work_ids", "source_records"]);
const EXTERNAL_EDITION_SCOPE = "provider edition, not Clark copy";
const OPEN_LIBRARY_DIMENSION_ORDER = "height_x_width_x_thickness";
const BINDING_TERMS = Object.freeze([
  ["loose-leaf-binder", /\bloose[ -]?leaf\b/i],
  ["spiral-bound", /\b(?:spiral|wire|coil)[ -]?(?:bound|binding)?\b/i],
  ["comb-bound", /\bcomb[ -]?(?:bound|binding)?\b/i],
  ["casebound", /\b(?:casebound|case bound)\b/i],
  ["hardcover", /\b(?:hardcover|hardback|hardbound|library binding)\b/i],
  ["paperback", /\b(?:paperback|softcover|soft cover|mass market|trade paper)\b/i],
  ["cloth", /\bcloth(?:bound)?\b/i],
  ["boards", /\bboards?\b/i],
  ["wrappers", /\b(?:wrapper|pamphlet|booklet)\b/i],
  ["binder", /\b(?:ring binder|binder)\b/i]
]);

function text(value, maximum = 240) {
  return typeof value === "string" ? value.replace(/\s+/g, " ").trim().slice(0, maximum) : "";
}

function textArray(value, maximumItems = 8, maximumLength = 180) {
  if (!Array.isArray(value)) return [];
  return [...new Set(value.map(item => text(item, maximumLength)).filter(Boolean))].slice(0, maximumItems);
}

function positiveInteger(value, maximum = 100000) {
  const number = Number(value);
  return Number.isInteger(number) && number > 0 && number <= maximum ? number : null;
}

function roundedCentimeters(value) {
  return Math.round((value + 1e-10) * 100) / 100;
}

/**
 * Parse a conservative subset of Open Library's free-text
 * `physical_dimensions` field.
 *
 * Open Library's add-book help calls the order `height x depth x width` while
 * its canonical example (`8.5 x 5.4 x 0.5 inches`) operationally places the
 * front width second and thickness last:
 * https://openlibrary.org/addbook/help
 * Imported records are not consistent enough to trust those last two labels,
 * so this parser treats the first axis as height, the larger remaining axis
 * as front width, and the smaller as thickness. It accepts only complete,
 * single-unit, three-axis values whose geometry makes that distinction clear.
 * Height-only statements, ranges, mixed units, unitless values, and outliers
 * are deliberately rejected rather than guessed.
 */
export function parseOpenLibraryDimensions(value = "") {
  const raw = text(value, 160);
  const match = raw.match(/^(\d{1,3}(?:\.\d{1,3})?)\s*[x\u00d7]\s*(\d{1,3}(?:\.\d{1,3})?)\s*[x\u00d7]\s*(\d{1,3}(?:\.\d{1,3})?)\s*(cm|centimet(?:er|re)s?|mm|millimet(?:er|re)s?|in(?:ch(?:es)?)?)\.?$/i);
  if (!match) return null;

  const unit = match[4].toLowerCase();
  const factor = unit.startsWith("mm") || unit.startsWith("millimet") ? 0.1
    : unit === "cm" || unit.startsWith("centimet") ? 1
      : 2.54;
  const [heightCm, secondCm, thirdCm] = match.slice(1, 4).map(number => roundedCentimeters(Number(number) * factor));
  const widthCm = Math.max(secondCm, thirdCm);
  const thicknessCm = Math.min(secondCm, thirdCm);

  // These bounds intentionally describe plausible book-like editions, not
  // the full range of objects in the Clark collection. Rejection leaves the
  // interface on its existing catalog/model fallback.
  if (heightCm < 5 || heightCm > 100
    || widthCm < 3 || widthCm > 100
    || thicknessCm < 0.05 || thicknessCm > 25
    || Math.max(heightCm, widthCm) / Math.min(heightCm, widthCm) > 4
    || widthCm / thicknessCm < 1.25
    || thicknessCm > Math.min(heightCm, widthCm) * 0.8) return null;

  return {
    status: "parsed_external_edition",
    raw,
    order: OPEN_LIBRARY_DIMENSION_ORDER,
    source_order: "height_x_depth_x_width",
    interpretation: "first_height_larger_remaining_width_smaller_remaining_thickness",
    unit: unit.startsWith("mm") || unit.startsWith("millimet") ? "mm"
      : unit === "cm" || unit.startsWith("centimet") ? "cm"
        : "in",
    height_cm: heightCm,
    width_cm: widthCm,
    thickness_cm: thicknessCm
  };
}

function validSourceUrl(value, sourceId = "") {
  try {
    const url = new URL(value);
    return url.protocol === "https:"
      && url.hostname === "openlibrary.org"
      && new RegExp(`^/books/${sourceId}$`).test(url.pathname);
  } catch (_) {
    return false;
  }
}

function isbnChecksumValid(compact) {
  if (/^\d{9}[\dX]$/.test(compact)) {
    return [...compact].reduce((sum, character, index) => sum + (character === "X" ? 10 : Number(character)) * (10 - index), 0) % 11 === 0;
  }
  if (/^\d{13}$/.test(compact)) {
    return [...compact].reduce((sum, character, index) => sum + Number(character) * (index % 2 ? 3 : 1), 0) % 10 === 0;
  }
  return false;
}

export function canonicalEditionIsbn(value = "") {
  const compact = String(value).toUpperCase().replace(/[^0-9X]/g, "");
  if (!isbnChecksumValid(compact)) return "";
  if (compact.length === 13) return compact;
  const body = `978${compact.slice(0, 9)}`;
  const total = [...body].reduce((sum, character, index) => sum + Number(character) * (index % 2 ? 3 : 1), 0);
  return `${body}${(10 - total % 10) % 10}`;
}

export function normalizeEditionOclc(value = "") {
  const string = String(value).trim();
  const match = string.match(/(?:\(\s*(?:oclc|ocolc)\s*\)|\b(?:oclc|ocolc|ocm|ocn|on))\s*0*(\d{1,12})(?!\d)/i)
    || string.match(/^\s*0*(\d{1,12})\s*$/);
  return match ? match[1] || "0" : "";
}

export function normalizeEditionLccn(value = "") {
  const string = String(value).replace(/^\s*lccn\s*[:#]?\s*/i, "").split("/", 1)[0].trim().toLowerCase();
  let match = string.match(/^([a-z]{0,3})\s*(\d{2}|\d{4})\s*-?\s*(\d{1,6})$/);
  let prefix;
  let year;
  let serial;
  if (match) {
    [, prefix, year, serial] = match;
  } else {
    const compact = string.replace(/[^a-z0-9]/g, "");
    match = compact.match(/^([a-z]{0,3})(\d{7,10})$/);
    if (!match) return "";
    [, prefix] = match;
    const digits = match[2];
    const yearLength = digits.length > 8 ? 4 : 2;
    year = digits.slice(0, yearLength);
    serial = digits.slice(yearLength);
  }
  return serial.length <= 6 ? `${prefix}${year}${serial.padStart(6, "0")}` : "";
}

function recordIdentifiers(record = {}) {
  const values = value => Array.isArray(value) ? value : value ? [value] : [];
  return {
    isbn: new Set(values(record.isbns).map(canonicalEditionIsbn).filter(Boolean)),
    oclc: new Set(values(record.oclc_numbers).map(normalizeEditionOclc).filter(Boolean)),
    lccn: new Set(values(record.lccn).map(normalizeEditionLccn).filter(Boolean))
  };
}

function sanitizeMatch(raw = {}) {
  const method = text(raw.method, 40);
  const confidence = Number(raw.confidence);
  if (!MATCH_METHODS.has(method) || !Number.isFinite(confidence) || confidence < 0 || confidence > 1 || !Array.isArray(raw.identifiers)) return null;
  const identifiers = [];
  for (const item of raw.identifiers.slice(0, 12)) {
    const type = text(item?.type, 12);
    const normalizer = { isbn: canonicalEditionIsbn, oclc: normalizeEditionOclc, lccn: normalizeEditionLccn }[type];
    const value = normalizer?.(item?.value);
    if (value && !identifiers.some(existing => existing.type === type && existing.value === value)) identifiers.push({ type, value });
  }
  const required = method === "oclc_lccn_exact" ? ["oclc", "lccn"]
    : method.startsWith("isbn") ? ["isbn"]
      : method.startsWith("oclc") ? ["oclc"]
        : ["lccn"];
  return required.every(type => identifiers.some(item => item.type === type)) ? { method, confidence, identifiers } : null;
}

function sanitizeEdition(raw = {}) {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return {};
  const edition = {};
  for (const [field, maximum] of Object.entries({ physical_format: 120, physical_dimensions: 160, weight: 80, pagination: 220, edition_name: 180, publish_date: 100, internet_archive_id: 120 })) {
    const value = text(raw[field], maximum);
    if (value) edition[field] = value;
  }
  const pages = positiveInteger(raw.number_of_pages, 20000);
  if (pages) edition.number_of_pages = pages;
  for (const field of ARRAY_FIELDS) {
    if (field === "cover_ids") {
      const values = Array.isArray(raw[field]) ? raw[field].map(item => positiveInteger(item, 1000000000)).filter(Boolean) : [];
      if (values.length) edition[field] = [...new Set(values)].slice(0, 8);
    } else {
      const values = textArray(raw[field], 8, 180);
      if (values.length) edition[field] = values;
    }
  }
  return edition;
}

function sanitizeCandidate(raw = {}) {
  const sourceId = text(raw.source_id, 40);
  const sourceUrl = text(raw.source_url, 220);
  const match = sanitizeMatch(raw.match);
  const edition = sanitizeEdition(raw.edition);
  if (!/^OL\d+M$/.test(sourceId) || !validSourceUrl(sourceUrl, sourceId) || !match || !Object.keys(edition).length) return null;
  return {
    source_id: sourceId,
    source_url: sourceUrl,
    record_modified: text(raw.record_modified, 40),
    match,
    edition
  };
}

function candidateMatchesRecord(candidate, record) {
  const available = recordIdentifiers(record);
  const intersects = type => candidate.match.identifiers.some(item => item.type === type && available[type]?.has(item.value));
  if (candidate.match.method === "isbn_exact") return intersects("isbn");
  if (candidate.match.method === "oclc_lccn_exact") return intersects("oclc") && intersects("lccn");
  if (candidate.match.method === "oclc_exact") return intersects("oclc");
  if (candidate.match.method === "lccn_exact") return intersects("lccn");
  return false;
}

function sanitizeResolved(raw = {}, candidates = []) {
  if (!raw || typeof raw !== "object" || Array.isArray(raw)) return {};
  const candidateMap = new Map(candidates.map(candidate => [candidate.source_id, candidate]));
  const resolved = {};
  for (const [field, claim] of Object.entries(raw)) {
    if (!CLAIM_FIELDS.has(field) || !claim || typeof claim !== "object" || Array.isArray(claim)) continue;
    const sourceId = text(claim.source_id, 40);
    const candidate = candidateMap.get(sourceId);
    if (!candidate || candidate.match.method !== "isbn_exact" || claim.match_method !== "isbn_exact" || claim.provider !== "openlibrary") continue;
    const candidateIsbns = new Set(candidate.match.identifiers.filter(item => item.type === "isbn").map(item => item.value));
    const matchedIsbns = [...new Set(textArray(claim.matched_isbns, 12, 20)
      .map(canonicalEditionIsbn)
      .filter(isbn => isbn && candidateIsbns.has(isbn)))];
    if (!matchedIsbns.length) continue;
    const value = field === "number_of_pages" ? positiveInteger(claim.value, 20000) : text(claim.value, field === "pagination" ? 220 : 160);
    if (value == null || value === "") continue;
    if (!Object.prototype.hasOwnProperty.call(candidate.edition, field) || candidate.edition[field] !== value) continue;
    const exactStatements = candidates
      .filter(item => item.match.method === "isbn_exact" && Object.prototype.hasOwnProperty.call(item.edition, field))
      .map(item => item.edition[field]);
    if (new Set(exactStatements.map(statement => JSON.stringify(statement))).size > 1) continue;
    resolved[field] = {
      value,
      status: "external_edition_stated",
      provider: "openlibrary",
      source_id: sourceId,
      source_url: candidate.source_url,
      match_method: "isbn_exact",
      matched_isbns: matchedIsbns
    };
  }
  return resolved;
}

function rejectedManifest() {
  return { schema: EDITION_ENRICHMENT_SCHEMA, generated_at: null, source: null, summary: {}, items: {}, rejected: true };
}

function hasValidManifestEnvelope(raw = {}) {
  const source = raw?.source;
  const validSource = source
    && source.catalog === "Clark Library Catalog"
    && source.provider === "Open Library"
    && Number.isInteger(source.record_count)
    && source.record_count >= 0
    && /^sha256:[a-f0-9]{64}$/i.test(source.dataset_sha256 || "")
    && /^md5:[a-f0-9]{32}$/i.test(source.provider_dump_checksum || "");
  return raw?.schema === EDITION_ENRICHMENT_SCHEMA
    && validSource
    && raw.items
    && typeof raw.items === "object"
    && !Array.isArray(raw.items);
}

function sanitizeManifestItem(recordId, item) {
  if (!/^alma\d+$/.test(recordId) || item?.status !== "resolved" || !Array.isArray(item.candidates)) return null;
  const candidates = item.candidates.slice(0, 6).map(sanitizeCandidate).filter(Boolean);
  if (!candidates.length) return null;
  return {
    status: "resolved",
    preferred_source_id: candidates.some(candidate => candidate.source_id === item.preferred_source_id) ? item.preferred_source_id : candidates[0].source_id,
    resolved: sanitizeResolved(item.resolved, candidates),
    candidates
  };
}

export function parseEditionEnrichmentManifest(raw = {}) {
  if (!hasValidManifestEnvelope(raw)) return rejectedManifest();
  const items = {};
  for (const [recordId, item] of Object.entries(raw.items)) {
    const sanitized = sanitizeManifestItem(recordId, item);
    if (sanitized) items[recordId] = sanitized;
  }
  return { ...raw, items, rejected: false };
}

/**
 * Validate a manifest without monopolizing the browser's main thread.
 *
 * The synchronous parser above remains the canonical contract. This variant
 * applies the same envelope checks and item sanitizer in insertion order, but
 * hands control back after each bounded batch. Callers inject the scheduling
 * primitive so browsers can use requestIdleCallback while tests can observe
 * every yield deterministically.
 */
export async function parseEditionEnrichmentManifestAsync(raw = {}, {
  batchSize = 400,
  yieldControl = () => Promise.resolve()
} = {}) {
  if (!hasValidManifestEnvelope(raw)) return rejectedManifest();
  const boundedBatchSize = Number.isInteger(batchSize) && batchSize > 0 ? batchSize : 400;
  const yieldBatch = typeof yieldControl === "function" ? yieldControl : () => Promise.resolve();
  const entries = Object.entries(raw.items);
  const items = {};

  for (let index = 0; index < entries.length; index += boundedBatchSize) {
    const batch = entries.slice(index, index + boundedBatchSize);
    for (const [recordId, item] of batch) {
      const sanitized = sanitizeManifestItem(recordId, item);
      if (sanitized) items[recordId] = sanitized;
    }
    await yieldBatch({
      batch: Math.floor(index / boundedBatchSize) + 1,
      processed: Math.min(index + batch.length, entries.length),
      total: entries.length
    });
  }

  return { ...raw, items, rejected: false };
}

export function getRecordEditionEnrichment(record = {}, manifest = {}) {
  const item = manifest?.items?.[record.id];
  if (!item) return null;
  const candidates = item.candidates.filter(candidate => candidateMatchesRecord(candidate, record));
  if (!candidates.length) return null;
  const validSources = new Set(candidates.map(candidate => candidate.source_id));
  const validIsbns = recordIdentifiers(record).isbn;
  const resolved = Object.fromEntries(Object.entries(item.resolved || {}).filter(([, claim]) => (
    validSources.has(claim.source_id) && claim.matched_isbns.some(isbn => validIsbns.has(isbn))
  )));
  const preferred = candidates.find(candidate => candidate.source_id === item.preferred_source_id) || candidates[0];
  return { ...item, candidates, preferred, resolved };
}

function externalClaimTags(claim = {}, status = "external_edition_stated") {
  const sourceId = text(claim.source_id, 40);
  const sourceUrl = text(claim.source_url, 220);
  const matchedIsbns = [...new Set((Array.isArray(claim.matched_isbns)
    ? claim.matched_isbns
    : claim.match?.identifiers?.filter(item => item.type === "isbn").map(item => item.value) || [])
    .map(canonicalEditionIsbn)
    .filter(Boolean))];
  return {
    status,
    provider: "openlibrary",
    source: { id: sourceId, url: sourceUrl },
    source_id: sourceId,
    source_url: sourceUrl,
    match: { method: "isbn_exact", matched_isbns: matchedIsbns },
    match_method: "isbn_exact",
    matched_isbns: matchedIsbns,
    scope: EXTERNAL_EDITION_SCOPE
  };
}

export function bindingFromExternalFormat(value = "", claim = {}) {
  const raw = text(value, 120);
  for (const [term, pattern] of BINDING_TERMS) {
    if (pattern.test(raw)) {
      return {
        term,
        raw,
        ...externalClaimTags(claim)
      };
    }
  }
  return null;
}

function mergeExternalDimensions(catalogDimensions, parsed, claim) {
  if (!parsed || !claim) return { dimensions: catalogDimensions, fields: [] };
  const dimensions = { ...(catalogDimensions || {}) };
  const provenance = { ...(catalogDimensions?.provenance || {}) };
  const fields = [];
  const tags = {
    ...externalClaimTags(claim),
    raw: parsed.raw,
    source_order: "height_x_depth_x_width",
    interpretation: "first_height_larger_remaining_width_smaller_remaining_thickness"
  };

  for (const axis of ["height", "width"]) {
    const valueField = `${axis}_cm`;
    if (Number.isFinite(catalogDimensions?.[valueField])) continue;
    for (const field of [valueField, `${axis}_min_cm`, `${axis}_max_cm`]) {
      dimensions[field] = parsed[valueField];
      provenance[field] = { ...tags };
      fields.push(`dimensions.${field}`);
    }
  }

  if (!fields.length) return { dimensions: catalogDimensions, fields };
  dimensions.status = catalogDimensions ? "mixed_catalog_external_edition" : "external_edition_stated";
  dimensions.order = catalogDimensions?.order || "height_x_width";
  dimensions.provenance = provenance;
  return { dimensions, fields };
}

export function mergeEditionPhysicalProfile(record = {}, enrichment = null) {
  const catalog = profileFromRecord(record);
  if (!enrichment) return catalog;
  const formatClaim = enrichment.resolved?.physical_format;
  const pagesClaim = enrichment.resolved?.number_of_pages;
  const dimensionsClaim = enrichment.resolved?.physical_dimensions;
  const parsedDimensions = dimensionsClaim ? parseOpenLibraryDimensions(dimensionsClaim.value) : null;
  const dimensionMerge = mergeExternalDimensions(catalog.dimensions, parsedDimensions, dimensionsClaim);
  const externalBinding = !catalog.binding && formatClaim ? bindingFromExternalFormat(formatClaim.value, formatClaim) : null;
  const externalExtent = !catalog.extent && pagesClaim ? {
    pages: pagesClaim.value,
    ...externalClaimTags(pagesClaim)
  } : null;
  const binding = catalog.binding || externalBinding;
  const extent = catalog.extent || externalExtent;
  let thickness = catalog.thickness;
  const externalFields = [...dimensionMerge.fields];
  const evidenceClaims = [];

  if (dimensionMerge.fields.length) evidenceClaims.push(dimensionsClaim);
  if (externalBinding) {
    externalFields.push("binding");
    evidenceClaims.push(formatClaim);
  }
  if (externalExtent) {
    externalFields.push("extent");
    evidenceClaims.push(pagesClaim);
  }

  const catalogThicknessIsStated = catalog.thickness
    && !String(catalog.thickness.status || "").startsWith("estimated")
    && !String(catalog.thickness.method || "").includes("model");

  // A conflict-free exact-ISBN edition specification is stronger evidence
  // than the interface's generic page-count model. Preserve any future
  // catalog-stated/measured depth, but let stated provider thickness replace
  // an estimate while retaining its provider-edition scope everywhere.
  if (!catalogThicknessIsStated && parsedDimensions && dimensionsClaim) {
    thickness = {
      value_cm: parsedDimensions.thickness_cm,
      min_cm: parsedDimensions.thickness_cm,
      max_cm: parsedDimensions.thickness_cm,
      method: "open-library-three-axis-dimensions-v1",
      evidence: "Exact-ISBN Open Library edition physical dimensions",
      raw: parsedDimensions.raw,
      source_order: "height_x_depth_x_width",
      interpretation: "first_height_larger_remaining_width_smaller_remaining_thickness",
      ...externalClaimTags(dimensionsClaim)
    };
    externalFields.push("thickness");
    evidenceClaims.push(dimensionsClaim);
  } else if (externalBinding && catalog.extent) {
    const refined = estimateBookThickness(catalog.extent, externalBinding, catalog.source_format || "");
    if (refined) thickness = {
      ...refined,
      ...externalClaimTags(formatClaim, "estimated_external"),
      method: "catalog-extent-external-binding-model-v1",
      evidence: "Clark extent + exact-ISBN Open Library physical format"
    };
    if (refined) externalFields.push("thickness");
  } else if (!catalog.extent && externalExtent) {
    const modeled = estimateBookThickness(externalExtent, binding, "");
    if (modeled) thickness = {
      ...modeled,
      ...externalClaimTags(pagesClaim, "estimated_external"),
      method: "external-edition-extent-model-v1",
      evidence: "Exact-ISBN Open Library page count"
    };
    if (modeled) externalFields.push("thickness");
  }

  const enriched = Boolean(externalFields.length);
  const sources = [...new Map(evidenceClaims.filter(Boolean).map(claim => {
    const tags = externalClaimTags(claim);
    return [`${tags.source_id}:${tags.match_method}`, tags];
  })).values()];
  return {
    ...catalog,
    status: catalog.status === "unavailable" && enriched ? "enriched" : catalog.status,
    ...(dimensionMerge.dimensions ? { dimensions: dimensionMerge.dimensions } : {}),
    ...(binding ? { binding } : {}),
    ...(extent ? { extent } : {}),
    ...(thickness ? { thickness } : {}),
    ...(enriched ? {
      external_evidence: {
        ...(sources[0] || {
          status: "external_edition_stated",
          provider: "openlibrary",
          source: { id: "", url: "" },
          source_id: "",
          source_url: "",
          match: { method: "isbn_exact", matched_isbns: [] },
          match_method: "isbn_exact",
          matched_isbns: [],
          scope: EXTERNAL_EDITION_SCOPE
        }),
        fields: [...new Set(externalFields)],
        sources
      }
    } : {})
  };
}

export function externalEditionLabel(enrichment = null) {
  if (!enrichment?.preferred) return "";
  const edition = enrichment.preferred.edition;
  return [edition.physical_format, edition.edition_name, edition.publish_date].filter(Boolean).join(" · ");
}
