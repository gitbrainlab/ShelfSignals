/**
 * Physical profiles derived from Clark catalog descriptions.
 *
 * Dimensions, extents, and bindings marked `stated` are catalog facts.
 * Thickness is always marked `estimated`: ShelfSignals has not measured these
 * objects and must not present the estimate as collection metadata.
 */

export const PHYSICAL_MANIFEST_SCHEMA = "shelfsignals-book-profiles@1";

const FRACTIONS = Object.freeze({
  "¼": 1 / 4,
  "½": 1 / 2,
  "¾": 3 / 4,
  "⅓": 1 / 3,
  "⅔": 2 / 3,
  "⅛": 1 / 8,
  "⅜": 3 / 8,
  "⅝": 5 / 8,
  "⅞": 7 / 8
});
const FRACTION_GLYPHS = "¼½¾⅓⅔⅛⅜⅝⅞";
const NUMBER_PATTERN = String.raw`(?:\d+(?:\.\d+)?(?:\s+\d+\s*\/\s*\d+)?|\d+\s*[${FRACTION_GLYPHS}]|\d+\s*\/\s*\d+)`;
const RANGE_PATTERN = `${NUMBER_PATTERN}(?:\\s*[-–]\\s*${NUMBER_PATTERN})?`;
const SIZE_PATTERN = String.raw`(?:^|(?<boundary>[^\d/]))(?<height>${RANGE_PATTERN})(?:\s*[x×X]\s*(?<width>${RANGE_PATTERN}))?\s*cm\b`;
const EXTENT_TOKEN_PATTERN = String.raw`(?:[ivxlcdm]+|\d{1,3}(?:,\d{3})+|\d+)`;
const EXTENT_PATTERN = String.raw`(?:^|[^\w-])(?<values>(?:\[?${EXTENT_TOKEN_PATTERN}(?:\s*[-–]\s*${EXTENT_TOKEN_PATTERN})?\]?\s*,?\s*)+)(?:(?:approximately|about)\s+)?(?:unnumbered\s+)?(?<unit>pages?|leaves|leafs|sheets?|volumes?)\b`;

const BINDING_PATTERNS = Object.freeze([
  ["accordion-folded", /\baccordion[ -]folded\b/i],
  ["loose-leaf-binder", /\bloose[ -]leaf\s+binder\b/i],
  ["loose-leaf", /\bloose[ -]leaf\b/i],
  ["saddle-stitched", /\bsaddle[ -]stitched\b/i],
  ["spiral-bound", /\bspiral[ -](?:bound|binding)\b/i],
  ["comb-bound", /\bcomb[ -](?:bound|binding)\b/i],
  ["casebound", /\bcase[ -]?bound\b/i],
  ["hardcover", /\b(?:hardcover|hardback)\b/i],
  ["paperback", /\bpaperback\b/i],
  ["cloth", /\bcloth(?:bound)?\b/i],
  ["boards", /\bboards?\b/i],
  ["wrappers", /\bwrappers?\b/i],
  ["stapled", /\bstapled\b/i],
  ["portfolio", /\bportfolio\b/i],
  ["slipcase", /\bslipcase\b/i],
  ["folder", /^\s*\d+\s+folders?\b/i],
  ["envelope", /^\s*\d+\s+envelopes?\b/i],
  ["binder", /\bbinder\b/i],
  ["case", /\bin (?:a )?case\b/i],
  ["box", /\bin (?:a )?box\b/i],
  ["container", /\bin (?:a )?container\b/i]
]);

function rounded(value) {
  return Math.round((value + 1e-10) * 100) / 100;
}

export function parseCatalogNumber(value = "") {
  const text = String(value).trim();
  const glyph = [...text].find(character => Object.prototype.hasOwnProperty.call(FRACTIONS, character));
  if (glyph) {
    const whole = Number(text.replace(glyph, "").trim() || 0);
    return Number.isFinite(whole) ? whole + FRACTIONS[glyph] : null;
  }
  const fraction = text.match(/^(?:(\d+(?:\.\d+)?)\s+)?(\d+)\s*\/\s*(\d+)$/);
  if (fraction) {
    const denominator = Number(fraction[3]);
    return denominator ? Number(fraction[1] || 0) + Number(fraction[2]) / denominator : null;
  }
  const number = Number(text);
  return Number.isFinite(number) ? number : null;
}

function parseMeasure(value = "") {
  const parts = String(value).trim().split(/\s*[-–]\s*/, 2);
  const numbers = parts.map(parseCatalogNumber);
  if (numbers.some(number => !Number.isFinite(number))) return null;
  const lower = Math.min(...numbers);
  const upper = Math.max(...numbers);
  if (lower < 2 || upper > 200) return null;
  return { value: rounded((lower + upper) / 2), min: rounded(lower), max: rounded(upper) };
}

function dimensionPayload(match) {
  const height = parseMeasure(match?.groups?.height);
  const width = match?.groups?.width ? parseMeasure(match.groups.width) : null;
  if (!height) return null;
  return {
    height_cm: height.value,
    height_min_cm: height.min,
    height_max_cm: height.max,
    ...(width ? {
      width_cm: width.value,
      width_min_cm: width.min,
      width_max_cm: width.max
    } : {})
  };
}

function combineDimensionPayloads(first, second) {
  const combined = {};
  for (const axis of ["height", "width"]) {
    const minimums = [first?.[`${axis}_min_cm`], second?.[`${axis}_min_cm`]];
    const maximums = [first?.[`${axis}_max_cm`], second?.[`${axis}_max_cm`]];
    if ([...minimums, ...maximums].some(value => !Number.isFinite(value))) continue;
    const lower = Math.min(...minimums);
    const upper = Math.max(...maximums);
    combined[`${axis}_cm`] = rounded((lower + upper) / 2);
    combined[`${axis}_min_cm`] = rounded(lower);
    combined[`${axis}_max_cm`] = rounded(upper);
  }
  return combined;
}

function primaryDimensionDescription(description = "") {
  const text = String(description);
  const firstPlus = text.indexOf("+");
  if (firstPlus < 0) return text;
  const firstSegment = text.slice(0, firstPlus);
  if (/\bcm\b/i.test(firstSegment)) return firstSegment;
  const secondPlus = text.indexOf("+", firstPlus + 1);
  const extended = text.slice(0, secondPlus < 0 ? text.length : secondPlus);
  return /\bcm\b/i.test(extended) ? extended : firstSegment;
}

export function parseCatalogDimensions(description = "") {
  const primary = primaryDimensionDescription(description);
  const matches = [...primary.matchAll(new RegExp(SIZE_PATTERN, "gi"))];
  if (!matches.length) return null;
  const matchStart = match => match.index + (match.groups?.boundary?.length || 0);
  const folded = /\bfolded\s+to\b/i.exec(primary);
  let selected = matches[matches.length - 1];
  if (folded) selected = matches.find(match => matchStart(match) >= folded.index + folded[0].length) || selected;
  let dimensions = dimensionPayload(selected);
  if (!folded && matches.length > 1) {
    for (let index = 0; index < matches.length - 1; index += 1) {
      const first = matches[index];
      const second = matches[index + 1];
      const between = primary.slice(first.index + first[0].length, matchStart(second));
      if (/^\s*[-–]\s*$/.test(between)) {
        dimensions = combineDimensionPayloads(dimensionPayload(first), dimensionPayload(second));
        break;
      }
    }
  }
  if (!dimensions) return null;
  Object.assign(dimensions, {
    status: "stated",
    order: "height_x_width",
    presentation: folded ? "folded" : "as_cataloged"
  });

  if (folded) {
    const before = matches.filter(match => match.index + match[0].length <= folded.index);
    let unfolded = before.length ? dimensionPayload(before[before.length - 1]) : null;
    if (!unfolded) {
      const prefix = primary.slice(0, folded.index);
      const unitless = new RegExp(`(?<height>${RANGE_PATTERN})\\s*[x×X]\\s*(?<width>${RANGE_PATTERN})\\s*[,(]?\\s*$`, "i").exec(prefix);
      unfolded = dimensionPayload(unitless);
    }
    if (unfolded) dimensions.unfolded = unfolded;
  }
  return dimensions;
}

function romanToInteger(value = "") {
  const text = String(value).toLowerCase();
  if (!/^[ivxlcdm]+$/.test(text)) return null;
  const values = { i: 1, v: 5, x: 10, l: 50, c: 100, d: 500, m: 1000 };
  let total = 0;
  let previous = 0;
  for (const character of [...text].reverse()) {
    const current = values[character];
    total += current < previous ? -current : current;
    previous = Math.max(previous, current);
  }
  return total > 0 && total < 5000 ? total : null;
}

function extentTokenCount(value = "") {
  const parts = String(value).trim().replace(/^\[|\]$/g, "").split(/\s*[-–]\s*/, 2);
  const number = part => /^(?:\d+|\d{1,3}(?:,\d{3})+)$/.test(part) ? Number(part.replaceAll(",", "")) : romanToInteger(part);
  const start = number(parts[0]);
  if (!Number.isFinite(start)) return null;
  if (parts.length === 1) return start;
  const end = number(parts[1]);
  return Number.isFinite(end) ? Math.abs(end - start) + 1 : null;
}

export function parseCatalogExtent(description = "") {
  const primary = String(description).split("+", 1)[0];
  const totals = { pages: 0, leaves: 0, sheets: 0, volumes: 0 };
  const found = new Set();
  for (const match of primary.matchAll(new RegExp(EXTENT_PATTERN, "gi"))) {
    const unit = match.groups.unit.toLowerCase();
    const key = ["leaf", "leafs", "leaves"].includes(unit) ? "leaves" : `${unit.replace(/s$/, "")}s`;
    const tokens = match.groups.values.match(new RegExp(`\\[?${EXTENT_TOKEN_PATTERN}(?:\\s*[-–]\\s*${EXTENT_TOKEN_PATTERN})?\\]?`, "gi")) || [];
    const counts = tokens.map(extentTokenCount).filter(Number.isFinite);
    if (counts.length) {
      totals[key] += counts.reduce((sum, count) => sum + count, 0);
      found.add(key);
    }
  }
  if (!found.size) return null;
  return {
    status: "stated",
    ...Object.fromEntries(["pages", "leaves", "sheets", "volumes"].filter(key => found.has(key)).map(key => [key, totals[key]]))
  };
}

export function parseCatalogBinding(description = "") {
  const primary = String(description).split("+", 1)[0];
  for (const [term, pattern] of BINDING_PATTERNS) {
    if (pattern.test(primary)) return { status: "stated", term };
  }
  return null;
}

export function estimateBookThickness(extent = null, binding = null, description = "") {
  if (!extent) return null;
  const volumes = Number(extent.volumes || 1);
  if (!Number.isFinite(volumes) || volumes > 1) return null;
  if (Number(extent.sheets || 0) > 0) return null;
  const term = String(binding?.term || "");
  if (["accordion-folded", "portfolio", "binder", "loose-leaf-binder", "loose-leaf", "case", "box", "folder", "envelope", "slipcase", "container"].includes(term)) return null;
  if (/^\s*\d+\s+(?:(?:accordion\s+)?folded\s+)?(?:sheets?|posters?|cards?|postcards?|folders?|envelopes?|slides?|photographs?|portfolios?|maps?|prints?|broadsides?|objects?)\b/i.test(description)) return null;
  const pageEquivalent = Number(extent.pages || 0) + 2 * Number(extent.leaves || 0);
  if (!Number.isFinite(pageEquivalent) || pageEquivalent <= 0) return null;
  const allowances = {
    paperback: [0.12, 0.25],
    hardcover: [0.35, 0.65],
    casebound: [0.35, 0.65],
    cloth: [0.30, 0.60],
    boards: [0.30, 0.60],
    wrappers: [0.10, 0.24],
    stapled: [0.06, 0.16],
    "saddle-stitched": [0.06, 0.16]
  };
  const [coverMin, coverMax] = allowances[term] || [0.18, 0.45];
  const minimum = pageEquivalent * 0.004 + coverMin;
  const maximum = pageEquivalent * 0.007 + coverMax;
  return {
    status: "estimated",
    value_cm: rounded((minimum + maximum) / 2),
    min_cm: rounded(minimum),
    max_cm: rounded(maximum),
    basis_pages: pageEquivalent,
    method: "catalog-extent-model-v1"
  };
}

export function parsePhysicalDescription(description = "") {
  const sourceFormat = String(description).replace(/\s+/g, " ").trim();
  if (!sourceFormat) return { status: "unavailable" };
  const dimensions = parseCatalogDimensions(sourceFormat);
  const extent = parseCatalogExtent(sourceFormat);
  const binding = parseCatalogBinding(sourceFormat);
  const thickness = estimateBookThickness(extent, binding, sourceFormat);
  return {
    status: dimensions || extent || binding ? "parsed" : "unavailable",
    source_format: sourceFormat,
    ...(dimensions ? { dimensions } : {}),
    ...(extent ? { extent } : {}),
    ...(binding ? { binding } : {}),
    ...(thickness ? { thickness } : {})
  };
}

function profileScore(profile) {
  return ["dimensions", "extent", "binding"].reduce((score, key) => score * 2 + Number(Boolean(profile[key])), 0) * 10000
    + String(profile.source_format || "").length;
}

export function profileFromRecord(record = {}) {
  const values = Array.isArray(record.formats) ? record.formats : record.formats == null || record.formats === "" ? [] : [record.formats];
  const profiles = values.map(parsePhysicalDescription);
  if (!profiles.length) return { status: "unavailable" };
  return profiles.reduce((best, profile) => profileScore(profile) > profileScore(best) ? profile : best);
}

export function parsePhysicalManifest(raw = {}) {
  const source = raw?.source;
  const provenanceIsValid = source
    && source.catalog === "Clark Library Catalog"
    && typeof source.dataset === "string"
    && /^sha256:[a-f0-9]{64}$/i.test(source.dataset_sha256 || "")
    && Number.isInteger(source.record_count)
    && source.record_count >= 0;
  if (raw?.schema !== PHYSICAL_MANIFEST_SCHEMA || !provenanceIsValid || !raw.items || typeof raw.items !== "object" || Array.isArray(raw.items)) {
    return { schema: PHYSICAL_MANIFEST_SCHEMA, generated_at: null, source: null, summary: {}, items: {}, rejected: true };
  }
  const items = {};
  for (const [id, profile] of Object.entries(raw.items)) {
    if (!id || !profile || typeof profile !== "object" || Array.isArray(profile)) continue;
    if (profile.status === "unavailable" && !profile.source_format) {
      items[id] = { status: "unavailable" };
      continue;
    }
    if (typeof profile.source_format !== "string") continue;
    const reparsed = parsePhysicalDescription(profile.source_format);
    if (profile.status !== reparsed.status) continue;
    items[id] = reparsed;
  }
  if (Object.keys(items).length !== source.record_count) {
    return { schema: PHYSICAL_MANIFEST_SCHEMA, generated_at: null, source: null, summary: {}, items: {}, rejected: true };
  }
  return { ...raw, items, rejected: false };
}

export function getRecordPhysicalProfile(record = {}, manifest = {}) {
  const id = String(record.id || "");
  return id && manifest?.items?.[id] ? manifest.items[id] : profileFromRecord(record);
}
