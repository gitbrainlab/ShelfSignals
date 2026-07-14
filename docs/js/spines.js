/**
 * Compact spine-geometry runtime.
 *
 * This module is intentionally independent of the cover pipeline. It decodes
 * Clark-stated height/width, separate binding/housing evidence, conservative
 * object form, per-axis precedence, rights, and warnings plus a clearly
 * labeled depth model. Full catalog wording remains in book_profiles.json and
 * can be loaded only when a physical-evidence drawer is opened.
 */

// @ts-check

export const SPINE_INDEX_SCHEMA = "shelfsignals-spine-index@1";
export const SPINE_DEPTH_METHOD = "catalog-extent-model-v1";
export const SPINE_REPRESENTATION_TYPE = "synthetic_metadata_derived";

export const SPINE_RIGHTS = Object.freeze({
  scope: "metadata_only",
  public_display: true,
  basis: "source_catalog_record",
  reuse_status: "not_assessed",
  image_rights: "not_applicable_no_image_asset",
  credit_line: "Physical description: Clark Library Catalog"
});

export const SPINE_AXIS_PRECEDENCE = Object.freeze({
  height: Object.freeze(["clark_copy_measurement", "clark_catalog_stated", "verified_exact_edition_stated", "neutral_renderer_default"]),
  width: Object.freeze(["clark_copy_measurement", "clark_catalog_stated", "verified_exact_edition_stated", "neutral_renderer_default"]),
  depth: Object.freeze(["clark_copy_measurement", "clark_catalog_stated", "verified_exact_edition_stated", "catalog_extent_model", "neutral_renderer_default"])
});

export const SPINE_WARNING_BITS = Object.freeze({
  height_unavailable: 1,
  width_unavailable: 2,
  depth_not_measured: 4,
  depth_unavailable: 8,
  object_form_unknown: 16,
  multi_object_no_single_depth: 32,
  folded_dimensions: 128
});

export const SPINE_BINDING_CODES = Object.freeze({
  "1": "accordion-folded", "2": "casebound", "3": "hardcover", "4": "paperback", "5": "cloth",
  "6": "boards", "7": "wrappers", "8": "stapled", "9": "saddle-stitched", "10": "spiral-bound",
  "11": "comb-bound", "12": "loose-leaf", "13": "loose-leaf-binder"
});
export const SPINE_HOUSING_CODES = Object.freeze({
  "1": "portfolio", "2": "slipcase", "3": "folder", "4": "envelope",
  "5": "binder", "6": "case", "7": "box", "8": "container"
});
export const SPINE_OBJECT_FORM_CODES = Object.freeze({
  "0": { term: "unknown", evidence_status: "unknown", basis: "no_supported_catalog_term" },
  "1": { term: "paged_object", evidence_status: "derived", basis: "clark_catalog_extent_semantics" },
  "2": { term: "volume", evidence_status: "stated", basis: "clark_catalog_object_term" },
  "3": { term: "multi_volume_set", evidence_status: "stated", basis: "clark_catalog_object_term" },
  "4": { term: "folded_sheet", evidence_status: "stated", basis: "clark_catalog_object_term" },
  "5": { term: "sheet", evidence_status: "stated", basis: "clark_catalog_object_term" },
  "6": { term: "portfolio", evidence_status: "stated", basis: "clark_catalog_object_term" },
  "7": { term: "housed_materials", evidence_status: "stated", basis: "clark_catalog_housing_term" },
  "8": { term: "poster_set", evidence_status: "stated", basis: "clark_catalog_object_term" },
  "9": { term: "card_set", evidence_status: "stated", basis: "clark_catalog_object_term" },
  "10": { term: "slide_set", evidence_status: "stated", basis: "clark_catalog_object_term" },
  "11": { term: "media_disc", evidence_status: "stated", basis: "clark_catalog_object_term" },
  "12": { term: "parts_set", evidence_status: "stated", basis: "clark_catalog_object_term" },
  "13": { term: "serial_parts", evidence_status: "stated", basis: "clark_catalog_object_term" },
  "14": { term: "map", evidence_status: "stated", basis: "clark_catalog_object_term" }
});

const SPINE_WARNING_MESSAGES = Object.freeze({
  synthetic_metadata_representation: "Shelf geometry is a metadata-derived representation, not a photograph or measurement of Clark's copy.",
  height_unavailable: "Clark's physical description does not provide a renderable height; the renderer may use a neutral default.",
  width_unavailable: "Clark's physical description does not provide a front width; the renderer may use a neutral default.",
  depth_not_measured: "Depth is modeled from Clark-stated extent and is not a measurement of Clark's copy.",
  depth_unavailable: "No defensible depth model is available; the renderer may use a neutral default.",
  object_form_unknown: "The catalog wording does not support a controlled object-form classification.",
  multi_object_no_single_depth: "A multi-object set cannot be represented by one factual spine depth.",
  folded_dimensions: "Displayed dimensions describe the Clark-stated folded presentation."
});

const SHA256 = /^sha256:[a-f0-9]{64}$/i;
const SAFE_SUFFIX = /^[A-Za-z0-9._~-]+$/;
const SAFE_DATASET = /^[A-Za-z0-9._-]+\.json$/;
const ALLOWED_ITEM_KEYS = new Set(["h", "w", "d", "b", "g", "f", "o", "q"]);

function isObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function cleanString(value) {
  return typeof value === "string" ? value.trim() : "";
}

function finiteNumber(value) {
  return typeof value === "number" && Number.isFinite(value);
}

function equalStringArray(value, expected) {
  return Array.isArray(value) && value.length === expected.length && value.every((entry, index) => entry === expected[index]);
}

function validRights(value) {
  return isObject(value) && Object.entries(SPINE_RIGHTS).every(([key, expected]) => value[key] === expected)
    && Object.keys(value).length === Object.keys(SPINE_RIGHTS).length;
}

function validContract(value) {
  if (!isObject(value) || value.representation_type !== SPINE_REPRESENTATION_TYPE || value.scope !== "clark_catalog_metadata") return false;
  if (!validRights(value.rights) || !isObject(value.axis_precedence)) return false;
  if (!Object.entries(SPINE_AXIS_PRECEDENCE).every(([axis, expected]) => equalStringArray(value.axis_precedence[axis], expected))) return false;
  return Array.isArray(value.shared_warnings)
    && value.shared_warnings.length === 1
    && value.shared_warnings[0]?.code === "synthetic_metadata_representation"
    && value.shared_warnings[0]?.message === SPINE_WARNING_MESSAGES.synthetic_metadata_representation;
}

function validObjectFormDescriptor(value) {
  return isObject(value)
    && Object.keys(value).length === 3
    && cleanString(value.term)
    && ["stated", "derived", "unknown"].includes(value.evidence_status)
    && ["clark_catalog_object_term", "clark_catalog_housing_term", "clark_catalog_extent_semantics", "no_supported_catalog_term"].includes(value.basis);
}

function validStringCodeTable(value, expected) {
  return isObject(value)
    && Object.keys(value).length === Object.keys(expected).length
    && Object.entries(expected).every(([code, term]) => value[code] === term);
}

function validObjectFormCodeTable(value) {
  return isObject(value)
    && Object.keys(value).length === Object.keys(SPINE_OBJECT_FORM_CODES).length
    && Object.entries(SPINE_OBJECT_FORM_CODES).every(([code, expected]) => {
      const actual = value[code];
      return validObjectFormDescriptor(actual)
        && Object.entries(expected).every(([key, expectedValue]) => actual[key] === expectedValue);
    });
}

function expectedWarningBits(item, objectFormCodes) {
  let bits = 0;
  if (!Object.prototype.hasOwnProperty.call(item, "h")) bits |= SPINE_WARNING_BITS.height_unavailable;
  if (!Object.prototype.hasOwnProperty.call(item, "w")) bits |= SPINE_WARNING_BITS.width_unavailable;
  bits |= Object.prototype.hasOwnProperty.call(item, "d") ? SPINE_WARNING_BITS.depth_not_measured : SPINE_WARNING_BITS.depth_unavailable;
  const form = objectFormCodes[String(item.o)];
  if (form?.term === "unknown") bits |= SPINE_WARNING_BITS.object_form_unknown;
  if (form?.term === "multi_volume_set" && !Object.prototype.hasOwnProperty.call(item, "d")) bits |= SPINE_WARNING_BITS.multi_object_no_single_depth;
  if (item.f === 1) bits |= SPINE_WARNING_BITS.folded_dimensions;
  return bits;
}

function normalizedMeasure(value) {
  if (finiteNumber(value) && value >= 2 && value <= 200) return value;
  if (!Array.isArray(value) || value.length !== 3 || !value.every(finiteNumber)) return null;
  const [midpoint, minimum, maximum] = value;
  return minimum >= 2 && minimum <= midpoint && midpoint <= maximum && maximum <= 200
    ? [midpoint, minimum, maximum]
    : null;
}

function normalizedDepth(value) {
  if (!Array.isArray(value) || value.length !== 4 || !value.every(finiteNumber)) return null;
  const [midpoint, minimum, maximum, basisPages] = value;
  if (!(minimum > 0 && minimum <= midpoint && midpoint <= maximum && maximum <= 25)) return null;
  if (!Number.isInteger(basisPages) || basisPages <= 0 || basisPages > 10000) return null;
  return [midpoint, minimum, maximum, basisPages];
}

function rejected(errors = []) {
  return {
    schema: SPINE_INDEX_SCHEMA,
    generated_at: null,
    source: null,
    policy: {},
    encoding: {},
    summary: {},
    items: {},
    rejected: true,
    errors
  };
}

function catalogIdSet(value) {
  if (value instanceof Set) return new Set([...value].map(String));
  return new Set(Array.isArray(value) ? value.filter(Boolean).map(String) : []);
}

/**
 * Validate an encoded spine index without expanding all profiles into memory.
 *
 * @param {unknown} raw
 * @param {{catalogIds?: string[]|Set<string>, datasetSha256?: string}} options
 */
export function parseSpineIndex(raw = {}, options = {}) {
  const errors = [];
  if (!isObject(raw) || raw.schema !== SPINE_INDEX_SCHEMA) errors.push("unsupported_schema");
  const source = isObject(raw?.source) ? raw.source : {};
  if (source.catalog !== "Clark Library Catalog") errors.push("invalid_catalog_source");
  if (!SAFE_DATASET.test(cleanString(source.dataset))) errors.push("invalid_catalog_dataset");
  if (!SHA256.test(cleanString(source.dataset_sha256))) errors.push("invalid_catalog_checksum");
  if (!Number.isInteger(source.record_count) || source.record_count < 0) errors.push("invalid_record_count");
  if (source.physical_description_field !== "formats") errors.push("invalid_physical_source_field");
  if (source.profile_schema !== "shelfsignals-book-profiles@1") errors.push("invalid_profile_schema");
  if (!SAFE_DATASET.test(cleanString(source.profile_dataset))) errors.push("invalid_profile_dataset");
  if (!SHA256.test(cleanString(source.profile_dataset_sha256))) errors.push("invalid_profile_checksum");
  if (options.datasetSha256 && cleanString(options.datasetSha256).toLowerCase() !== cleanString(source.dataset_sha256).toLowerCase()) {
    errors.push("stale_catalog_checksum");
  }
  const contract = isObject(raw?.contract) ? raw.contract : {};
  if (!validContract(contract)) errors.push("invalid_spine_contract");

  const encoding = isObject(raw?.encoding) ? raw.encoding : {};
  const idPrefix = cleanString(encoding.id_prefix);
  if (!/^[A-Za-z][A-Za-z0-9_-]*$/.test(idPrefix)) errors.push("invalid_id_prefix");
  const bindingCodes = isObject(encoding.binding_codes) ? encoding.binding_codes : {};
  if (!validStringCodeTable(bindingCodes, SPINE_BINDING_CODES)) {
    errors.push("invalid_binding_codes");
  }
  const housingCodes = isObject(encoding.housing_codes) ? encoding.housing_codes : {};
  if (!validStringCodeTable(housingCodes, SPINE_HOUSING_CODES)) {
    errors.push("invalid_housing_codes");
  }
  const objectFormCodes = isObject(encoding.object_form_codes) ? encoding.object_form_codes : {};
  if (!validObjectFormCodeTable(objectFormCodes)) {
    errors.push("invalid_object_form_codes");
  }
  if (objectFormCodes["0"]?.term !== "unknown" || objectFormCodes["0"]?.evidence_status !== "unknown") {
    errors.push("missing_unknown_object_form");
  }
  const warningBits = isObject(encoding.warning_bits) ? encoding.warning_bits : {};
  const expectedWarningTable = Object.fromEntries(Object.entries(SPINE_WARNING_BITS).map(([code, bit]) => [String(bit), code]));
  if (Object.keys(warningBits).length !== Object.keys(expectedWarningTable).length
    || Object.entries(expectedWarningTable).some(([bit, code]) => warningBits[bit] !== code)) {
    errors.push("invalid_warning_bits");
  }

  if (!isObject(raw?.items)) errors.push("invalid_items");
  if (errors.length) return rejected(errors);

  const catalogIds = catalogIdSet(options.catalogIds);
  if (catalogIds.size && catalogIds.size !== source.record_count) errors.push("catalog_count_mismatch");
  const items = Object.create(null);
  for (const [suffix, rawItem] of Object.entries(raw.items)) {
    const path = `${idPrefix}${suffix}`;
    if (!suffix || !SAFE_SUFFIX.test(suffix) || !isObject(rawItem)) {
      errors.push(`invalid_item:${path}`);
      continue;
    }
    if (catalogIds.size && !catalogIds.has(path)) errors.push(`unknown_catalog_id:${path}`);
    if (Object.keys(rawItem).some(key => !ALLOWED_ITEM_KEYS.has(key))) {
      errors.push(`unsupported_item_field:${path}`);
      continue;
    }
    const item = {};
    if (Object.prototype.hasOwnProperty.call(rawItem, "h")) {
      item.h = normalizedMeasure(rawItem.h);
      if (item.h === null) errors.push(`invalid_height:${path}`);
    }
    if (Object.prototype.hasOwnProperty.call(rawItem, "w")) {
      item.w = normalizedMeasure(rawItem.w);
      if (item.w === null) errors.push(`invalid_width:${path}`);
    }
    if (Object.prototype.hasOwnProperty.call(rawItem, "d")) {
      item.d = normalizedDepth(rawItem.d);
      if (item.d === null) errors.push(`invalid_depth:${path}`);
    }
    if (Object.prototype.hasOwnProperty.call(rawItem, "b")) {
      const code = String(rawItem.b);
      if (!Number.isInteger(rawItem.b) || !cleanString(bindingCodes[code])) errors.push(`invalid_binding:${path}`);
      else item.b = rawItem.b;
    }
    if (Object.prototype.hasOwnProperty.call(rawItem, "g")) {
      const code = String(rawItem.g);
      if (!Number.isInteger(rawItem.g) || !cleanString(housingCodes[code])) errors.push(`invalid_housing:${path}`);
      else item.g = rawItem.g;
    }
    if (Object.prototype.hasOwnProperty.call(rawItem, "b") && Object.prototype.hasOwnProperty.call(rawItem, "g")) {
      errors.push(`binding_housing_conflict:${path}`);
    }
    if (Object.prototype.hasOwnProperty.call(rawItem, "f")) {
      if (rawItem.f !== 1) errors.push(`invalid_folded_flag:${path}`);
      else item.f = 1;
    }
    if (!Number.isInteger(rawItem.o) || !validObjectFormDescriptor(objectFormCodes[String(rawItem.o)])) {
      errors.push(`invalid_object_form:${path}`);
    } else item.o = rawItem.o;
    if (!Number.isInteger(rawItem.q) || rawItem.q < 0 || rawItem.q > 255) {
      errors.push(`invalid_warning_bitset:${path}`);
    } else item.q = rawItem.q;
    if (Number.isInteger(item.q) && item.q !== expectedWarningBits(item, objectFormCodes)) {
      errors.push(`warning_bitset_mismatch:${path}`);
    }
    items[suffix] = item;
  }

  const summary = isObject(raw?.summary) ? raw.summary : {};
  if (summary.catalog_records !== source.record_count) errors.push("summary_catalog_count_mismatch");
  if (summary.indexed_records !== Object.keys(items).length) errors.push("summary_index_count_mismatch");
  if (summary.defaulted_unavailable !== source.record_count - Object.keys(items).length) errors.push("summary_default_count_mismatch");
  const summaryFields = {
    height_stated: "h",
    width_stated: "w",
    depth_estimated: "d",
    binding_stated: "b",
    housing_stated: "g"
  };
  for (const [summaryKey, itemKey] of Object.entries(summaryFields)) {
    const actual = Object.values(items).filter(item => Object.prototype.hasOwnProperty.call(item, itemKey)).length;
    if (summary[summaryKey] !== actual) errors.push(`summary_${summaryKey}_mismatch`);
  }
  const foldedCount = Object.values(items).filter(item => item.f === 1).length;
  if (summary.folded_presentation !== foldedCount) errors.push("summary_folded_presentation_mismatch");
  const unknownFormCount = Object.values(items).filter(item => objectFormCodes[String(item.o)]?.term === "unknown").length;
  if (summary.object_form_unknown !== unknownFormCount) errors.push("summary_object_form_unknown_mismatch");
  const geometryUnavailable = Object.values(items).filter(item => !Object.prototype.hasOwnProperty.call(item, "h") && !Object.prototype.hasOwnProperty.call(item, "d")).length;
  if (summary.geometry_unavailable !== geometryUnavailable) errors.push("summary_geometry_unavailable_mismatch");
  if (errors.length) return rejected(errors);

  return {
    ...raw,
    source: { ...source },
    contract: {
      ...contract,
      rights: { ...contract.rights },
      axis_precedence: Object.fromEntries(Object.entries(contract.axis_precedence).map(([axis, order]) => [axis, [...order]])),
      shared_warnings: contract.shared_warnings.map(warning => ({ ...warning }))
    },
    encoding: {
      ...encoding,
      binding_codes: { ...bindingCodes },
      housing_codes: { ...housingCodes },
      object_form_codes: Object.fromEntries(Object.entries(objectFormCodes).map(([code, descriptor]) => [code, { ...descriptor }])),
      warning_bits: { ...warningBits }
    },
    items,
    rejected: false,
    errors: []
  };
}

function expandedMeasure(value, axis) {
  const [midpoint, minimum, maximum] = Array.isArray(value) ? value : [value, value, value];
  return {
    [`${axis}_cm`]: midpoint,
    [`${axis}_min_cm`]: minimum,
    [`${axis}_max_cm`]: maximum
  };
}

function rightsFor(index) {
  return index?.rejected === false && validRights(index?.contract?.rights)
    ? { ...index.contract.rights }
    : { ...SPINE_RIGHTS };
}

function precedenceFor(index, axis) {
  const configured = index?.rejected === false ? index?.contract?.axis_precedence?.[axis] : null;
  return equalStringArray(configured, SPINE_AXIS_PRECEDENCE[axis]) ? [...configured] : [...SPINE_AXIS_PRECEDENCE[axis]];
}

function axisEvidence(index, axis, state) {
  const precedence = precedenceFor(index, axis);
  const selectedSource = state === "stated"
    ? "clark_catalog_stated"
    : state === "estimated"
      ? "catalog_extent_model"
      : "neutral_renderer_default";
  return {
    status: state,
    selected_source: selectedSource,
    precedence_rank: precedence.indexOf(selectedSource) + 1,
    precedence,
    scope: state === "stated" ? "clark_catalog_record" : state === "estimated" ? "interface_model" : "synthetic_fallback",
    factual_metadata: state === "stated",
    copy_specific: false,
    cover_image_inference: false
  };
}

function decodedWarnings(compact, index) {
  const warnings = (index?.contract?.shared_warnings || []).map(warning => ({ ...warning }));
  for (const [code, bit] of Object.entries(SPINE_WARNING_BITS)) {
    if ((compact.q & bit) !== bit) continue;
    warnings.push({ code, message: SPINE_WARNING_MESSAGES[code] });
  }
  return warnings;
}

function unavailableProfile(id, profileDataset, index) {
  return {
    status: "unavailable",
    representation_type: "neutral_placeholder",
    source_scope: "none",
    copy_specific_depth: false,
    provenance_ref: id && SAFE_DATASET.test(profileDataset) ? `${profileDataset}#${id}` : "",
    rights: rightsFor(index),
    object_form: { term: "unknown", evidence_status: "unknown", basis: "no_supported_catalog_term", copy_specific: false },
    binding: null,
    housing: null,
    axis_evidence: {
      height: axisEvidence(index, "height", "unavailable"),
      width: axisEvidence(index, "width", "unavailable"),
      depth: axisEvidence(index, "depth", "unavailable")
    },
    warnings: [
      { code: "spine_record_unavailable", message: "No validated spine record is available; only a neutral placeholder may be shown." }
    ]
  };
}

/** Decode one record on demand into the existing physical-profile shape. */
export function getRecordSpineProfile(record = {}, index = {}) {
  const id = cleanString(record.id);
  const idPrefix = cleanString(index?.encoding?.id_prefix);
  const profileDataset = cleanString(index?.source?.profile_dataset);
  const provenanceRef = id && SAFE_DATASET.test(profileDataset) ? `${profileDataset}#${id}` : "";
  if (!id || index?.rejected !== false || !idPrefix || !id.startsWith(idPrefix)) {
    return unavailableProfile(id, profileDataset, index);
  }
  const compact = index.items?.[id.slice(idPrefix.length)];
  if (!compact) return unavailableProfile(id, profileDataset, index);

  const dimensions = {};
  if (compact.h != null) Object.assign(dimensions, expandedMeasure(compact.h, "height"));
  if (compact.w != null) Object.assign(dimensions, expandedMeasure(compact.w, "width"));
  if (Object.keys(dimensions).length) Object.assign(dimensions, {
    status: "stated",
    order: "height_x_width",
    presentation: compact.f === 1 ? "folded" : "as_cataloged"
  });

  const bindingTerm = cleanString(index.encoding?.binding_codes?.[String(compact.b)]);
  const housingTerm = cleanString(index.encoding?.housing_codes?.[String(compact.g)]);
  const objectForm = index.encoding?.object_form_codes?.[String(compact.o)] || {
    term: "unknown", evidence_status: "unknown", basis: "no_supported_catalog_term"
  };
  const depth = compact.d;
  return {
    status: "indexed",
    representation_type: SPINE_REPRESENTATION_TYPE,
    source_scope: "clark_catalog_record",
    copy_specific_depth: false,
    provenance_ref: provenanceRef,
    rights: rightsFor(index),
    object_form: { ...objectForm, copy_specific: false },
    binding: bindingTerm ? { status: "stated", term: bindingTerm, source_scope: "clark_catalog_record" } : null,
    housing: housingTerm ? { status: "stated", term: housingTerm, source_scope: "clark_catalog_record" } : null,
    axis_evidence: {
      height: axisEvidence(index, "height", compact.h != null ? "stated" : "unavailable"),
      width: axisEvidence(index, "width", compact.w != null ? "stated" : "unavailable"),
      depth: axisEvidence(index, "depth", depth ? "estimated" : "unavailable")
    },
    warnings: decodedWarnings(compact, index),
    ...(Object.keys(dimensions).length ? { dimensions } : {}),
    ...(depth ? {
      thickness: {
        status: "estimated",
        value_cm: depth[0],
        min_cm: depth[1],
        max_cm: depth[2],
        basis_pages: depth[3],
        method: SPINE_DEPTH_METHOD,
        evidence: "Clark-stated extent; interface model, not measured"
      }
    } : {})
  };
}

/** Rights gate for using a validated metadata-derived spine representation. */
export function canDisplaySpine(profile = {}) {
  return profile?.status === "indexed"
    && profile?.representation_type === SPINE_REPRESENTATION_TYPE
    && profile?.rights?.public_display === true
    && profile?.rights?.scope === "metadata_only";
}

/** Fetch and validate the index only when a shelf/spine view needs it. */
export async function loadSpineIndex(url = "data/spine_index.json", options = {}) {
  const response = await fetch(url, { credentials: "same-origin" });
  if (!response.ok) throw new Error(`Spine index request failed: ${response.status}`);
  return parseSpineIndex(await response.json(), options);
}
