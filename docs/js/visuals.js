/**
 * Deterministic visual helpers for real ShelfSignals catalog records.
 * Generated colors and book forms are interface representations, never scans.
 */

import { profileFromRecord } from "./physical.js";

export const VISUAL_MANIFEST_SCHEMA = "shelfsignals-book-visuals@1";
export const FEATURED_SCHEMA = "shelfsignals-featured-items@1";

const SAFE_COVER_HOSTS = new Set([
  "covers.openlibrary.org",
  "books.google.com",
  "books.googleusercontent.com",
  "books.googleusercontent.com"
]);

export function normalizeIsbn(value = "") {
  const compact = String(value).toUpperCase().replace(/[^0-9X]/g, "");
  if (/^\d{9}[\dX]$/.test(compact)) {
    const total = [...compact].reduce((sum, digit, index) => sum + (digit === "X" ? 10 : Number(digit)) * (10 - index), 0);
    return total % 11 === 0 ? compact : "";
  }
  if (/^\d{13}$/.test(compact)) {
    const total = [...compact].reduce((sum, digit, index) => sum + Number(digit) * (index % 2 ? 3 : 1), 0);
    return total % 10 === 0 ? compact : "";
  }
  return "";
}

export function normalizeOclc(value = "") {
  const text = String(value).trim();
  const tagged = text.match(/(?:OCoLC|ocolc|ocm|ocn|on)?\s*0*(\d{4,})/i);
  return tagged ? tagged[1] : "";
}

export function normalizeLccn(value = "") {
  return String(value).toLowerCase().replace(/^lccn\s*/i, "").replace(/[^a-z0-9]/g, "");
}

export function stableHash(value = "") {
  let hash = 2166136261;
  for (const char of String(value)) {
    hash ^= char.codePointAt(0);
    hash = Math.imul(hash, 16777619);
  }
  return hash >>> 0;
}

function hslToHex(hue, saturation, lightness) {
  const s = saturation / 100;
  const l = lightness / 100;
  const chroma = (1 - Math.abs(2 * l - 1)) * s;
  const segment = hue / 60;
  const second = chroma * (1 - Math.abs((segment % 2) - 1));
  let rgb = [0, 0, 0];
  if (segment < 1) rgb = [chroma, second, 0];
  else if (segment < 2) rgb = [second, chroma, 0];
  else if (segment < 3) rgb = [0, chroma, second];
  else if (segment < 4) rgb = [0, second, chroma];
  else if (segment < 5) rgb = [second, 0, chroma];
  else rgb = [chroma, 0, second];
  const offset = l - chroma / 2;
  return `#${rgb.map(channel => Math.round((channel + offset) * 255).toString(16).padStart(2, "0")).join("")}`;
}

export function deterministicBookColors(record = {}) {
  const seed = stableHash(record.id || record.title || record.call_number || "shelfsignals");
  const hueFamilies = [18, 27, 36, 47, 82, 136, 164, 193, 211, 226, 246, 278, 328, 354];
  const hue = (hueFamilies[seed % hueFamilies.length] + ((seed >>> 8) % 13) - 6 + 360) % 360;
  const saturation = 18 + ((seed >>> 12) % 27);
  const baseLightness = 19 + ((seed >>> 18) % 17);
  const color = hslToHex(hue, saturation, baseLightness);
  const darkInk = "#000000";
  const lightInk = "#ffffff";
  return {
    color,
    light: hslToHex(hue, Math.max(12, saturation - 3), Math.min(52, baseLightness + 14)),
    dark: hslToHex(hue, Math.min(55, saturation + 7), Math.max(7, baseLightness - 10)),
    ink: contrastRatio(color, darkInk) >= contrastRatio(color, lightInk) ? darkInk : lightInk
  };
}

export function parsePhysicalHeight(formats = []) {
  const profile = profileFromRecord({ formats });
  const height = Number(profile.dimensions?.height_cm);
  return Number.isFinite(height) && height >= 5 && height <= 100 ? height : null;
}

export function physicalBookHeight(record = {}, min = 18, max = 34) {
  const cm = parsePhysicalHeight(record.formats);
  const clamped = Math.max(min, Math.min(max, cm || 23));
  return { cm, ratio: (clamped - min) / (max - min) };
}

export function shortDisplayTitle(title = "", max = 92) {
  const clean = String(title || "Untitled").replace(/\s+/g, " ").trim();
  const responsibility = clean.indexOf(" / ");
  const candidate = responsibility > 10 ? clean.slice(0, responsibility) : clean;
  if (candidate.length <= max) return candidate;
  const clipped = candidate.slice(0, max - 1).replace(/\s+\S*$/, "").trim();
  return `${clipped || candidate.slice(0, max - 1)}…`;
}

export function isAllowedCoverUrl(value) {
  if (!value) return false;
  try {
    const url = new URL(value);
    return url.protocol === "https:" && SAFE_COVER_HOSTS.has(url.hostname.toLowerCase());
  } catch (_) {
    return false;
  }
}

export function parseVisualManifest(raw = {}) {
  if (!raw || raw.schema !== VISUAL_MANIFEST_SCHEMA || typeof raw.items !== "object" || Array.isArray(raw.items)) {
    return { schema: VISUAL_MANIFEST_SCHEMA, generated_at: null, items: {}, rejected: true };
  }
  const items = {};
  for (const [id, visual] of Object.entries(raw.items)) {
    if (!visual || visual.status !== "resolved" || !isAllowedCoverUrl(visual.image_url || visual.thumbnail_url)) continue;
    const imageUrl = isAllowedCoverUrl(visual.image_url) ? visual.image_url : visual.thumbnail_url;
    items[id] = {
      ...visual,
      image_url: imageUrl,
      thumbnail_url: isAllowedCoverUrl(visual.thumbnail_url) ? visual.thumbnail_url : imageUrl
    };
  }
  return { ...raw, items, rejected: false };
}

export function getRecordVisual(record = {}, manifest = {}) {
  const visual = manifest.items?.[record.id];
  return visual && isAllowedCoverUrl(visual.image_url) ? visual : null;
}

function hexLuminance(value = "") {
  const match = String(value).match(/^#([a-f\d]{2})([a-f\d]{2})([a-f\d]{2})$/i);
  if (!match) return 0;
  const channels = match.slice(1).map(channel => Number.parseInt(channel, 16) / 255);
  const linear = channels.map(channel => channel <= .04045 ? channel / 12.92 : ((channel + .055) / 1.055) ** 2.4);
  return .2126 * linear[0] + .7152 * linear[1] + .0722 * linear[2];
}

function contrastRatio(left, right) {
  const first = hexLuminance(left);
  const second = hexLuminance(right);
  return (Math.max(first, second) + .05) / (Math.min(first, second) + .05);
}

function visualBookColors(record, visual) {
  const fallback = deterministicBookColors(record);
  const palette = visual?.image_analysis?.palette?.map(item => item?.hex).filter(value => /^#[a-f\d]{6}$/i.test(value || "")) || [];
  if (!palette.length) return fallback;
  const ranked = [...palette].sort((left, right) => hexLuminance(left) - hexLuminance(right));
  const dominant = palette[0] || fallback.color;
  const darkInk = "#000000";
  const lightInk = "#ffffff";
  return {
    color: dominant,
    light: ranked[ranked.length - 1] || fallback.light,
    dark: ranked[0] || fallback.dark,
    ink: contrastRatio(dominant, darkInk) >= contrastRatio(dominant, lightInk) ? darkInk : lightInk
  };
}

export function resolveFeaturedItems(records = [], config = {}, manifest = {}, desired = 11) {
  const byId = new Map(records.map(record => [record.id, record]));
  const requested = Array.isArray(config.hero) ? config.hero : [];
  const selected = [];
  const seen = new Set();
  for (const id of requested) {
    const record = byId.get(id);
    if (record && !seen.has(id)) {
      selected.push(record);
      seen.add(id);
    }
  }
  if (selected.length < desired) {
    const coverFirst = records.filter(record => getRecordVisual(record, manifest));
    const fallback = coverFirst.length ? coverFirst : records;
    for (const record of fallback) {
      if (selected.length >= desired) break;
      if (!record?.id || seen.has(record.id)) continue;
      selected.push(record);
      seen.add(record.id);
    }
  }
  return selected.slice(0, desired);
}

export function bookStyleProperties(record = {}, visual = null) {
  const colors = visualBookColors(record, visual);
  const profile = record.physicalProfile || profileFromRecord(record);
  const heightCm = Number(profile.dimensions?.height_cm);
  const widthCm = Number(profile.dimensions?.width_cm);
  const depthCm = Number(profile.thickness?.value_cm);
  const clampedHeight = Math.max(18, Math.min(34, heightCm || 23));
  const ratio = (clampedHeight - 18) / 16;
  const measuredAspect = Number.isFinite(heightCm) && Number.isFinite(widthCm) && heightCm > 0 ? widthCm / heightCm : NaN;
  const analyzedAspect = Number(visual?.image_analysis?.aspect_ratio || visual?.aspect_ratio);
  const aspect = Number.isFinite(measuredAspect) && measuredAspect > .25 && measuredAspect < 1.8
    ? measuredAspect
    : analyzedAspect;
  const safeAspect = Number.isFinite(aspect) && aspect > .25 && aspect < 1.8 ? aspect : .68;
  const safeDepth = Number.isFinite(depthCm) && depthCm > 0 ? Math.max(.35, Math.min(7.5, depthCm)) : null;
  const optical = visual?.image_analysis?.optical_metrics || {};
  const frequency = Number(optical.high_frequency_energy);
  const textureOpacity = Number.isFinite(frequency) ? Math.max(.018, Math.min(.09, frequency * 2.4)) : .025;
  return {
    "--book-color": colors.color,
    "--book-light": colors.light,
    "--book-dark": colors.dark,
    "--book-ink": colors.ink,
    "--book-height": `${330 + ratio * 160}px`,
    "--mobile-height": `${250 + ratio * 70}px`,
    "--spine-height": `${112 + ratio * 80}px`,
    "--hero-width": `${safeDepth ? Math.round(17 + safeDepth * 12) : 28}px`,
    "--spine-width": `${safeDepth ? Math.round(8 + safeDepth * 9) : 22}px`,
    "--book-ratio": String(safeAspect),
    "--profile-front-height": "158px",
    "--profile-front-width": `${Math.max(64, Math.min(188, Math.round(158 * safeAspect)))}px`,
    "--profile-depth": `${safeDepth ? Math.round(7 + safeDepth * 7) : 14}px`,
    "--cover-texture": String(textureOpacity.toFixed(3)),
    ...(visual ? { "--cover-image": `url("${visual.thumbnail_url || visual.image_url}")` } : {})
  };
}

export function applyBookStyle(element, record, visual = null) {
  for (const [property, value] of Object.entries(bookStyleProperties(record, visual))) {
    element.style.setProperty(property, value);
  }
  if (visual) element.classList.add("has-cover");
}
