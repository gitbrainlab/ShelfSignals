import { deriveSignals } from "./signals.js";
import { parseLcCallNumber } from "./lc.js";
import { normalizeYear } from "./year.js";
import { shortDisplayTitle } from "./visuals.js";

function arrayValue(value) {
  return Array.isArray(value) ? value.filter(Boolean).map(String) : (value ? [String(value)] : []);
}

export function enrichRecord(record = {}) {
  const authors = arrayValue(record.authors);
  const contributors = arrayValue(record.contributors);
  const subjects = [...new Set(arrayValue(record.subjects))];
  const notes = arrayValue(record.notes);
  const provenance = arrayValue(record.provenance_notes);
  const sekulaNotes = arrayValue(record.sekula_notes);
  const identifiers = [
    ...arrayValue(record.isbns),
    ...arrayValue(record.issns),
    ...arrayValue(record.oclc_numbers),
    ...arrayValue(record.lccn),
    record.alma_mms,
    record.id
  ].filter(Boolean);
  const { lcClass, lcNumber, lcKey } = parseLcCallNumber(record.call_number);
  const yearPrimary = normalizeYear(record.year);
  const signals = deriveSignals(subjects, [...notes, ...provenance, ...sekulaNotes, record.title, record.description]);
  const searchText = [
    record.title,
    record.uniform_title,
    ...arrayValue(record.alternative_titles),
    ...authors,
    ...contributors,
    ...subjects,
    record.call_number,
    ...notes,
    ...provenance,
    ...sekulaNotes,
    record.description,
    ...arrayValue(record.publishers),
    ...arrayValue(record.formats),
    ...arrayValue(record.table_of_contents),
    ...identifiers
  ].filter(Boolean).join(" \u241f ").toLocaleLowerCase();

  return {
    ...record,
    id: String(record.id || ""),
    title: String(record.title || "Untitled"),
    displayTitle: shortDisplayTitle(record.title),
    authors,
    contributors,
    subjects,
    notes,
    provenance_notes: provenance,
    sekula_notes: sekulaNotes,
    publishers: arrayValue(record.publishers),
    formats: arrayValue(record.formats),
    isbns: arrayValue(record.isbns),
    oclc_numbers: arrayValue(record.oclc_numbers),
    lccn: arrayValue(record.lccn),
    signals,
    lcClass,
    lcNumber,
    lcKey,
    yearPrimary,
    decade: yearPrimary ? Math.floor(yearPrimary / 10) * 10 : null,
    materialKey: String(record.material_type || "other").toLocaleLowerCase(),
    catalogLink: String(record.record_url || ""),
    searchText
  };
}

export function enrichRecords(records = []) {
  return records.filter(record => record && record.id && record.title).map(enrichRecord);
}

export function normalizeFilterState(state = {}) {
  return {
    query: String(state.query || "").trim(),
    signals: [...new Set(Array.isArray(state.signals) ? state.signals.filter(Boolean) : [])],
    signalMode: state.signalMode === "all" ? "all" : "any",
    lc: String(state.lc || ""),
    material: String(state.material || ""),
    decade: state.decade === "" || state.decade == null ? "" : String(state.decade),
    photo: String(state.photo || ""),
    group: ["lc", "decade", "material"].includes(state.group) ? state.group : "lc",
    path: String(state.path || "")
  };
}

export function recordMatchesSignals(record, selected = [], mode = "any") {
  if (!selected.length) return true;
  const available = new Set(record.signals || []);
  return mode === "all" ? selected.every(id => available.has(id)) : selected.some(id => available.has(id));
}

export function filterRecords(records = [], rawState = {}) {
  const state = normalizeFilterState(rawState);
  const terms = state.query.toLocaleLowerCase().split(/\s+/).filter(Boolean);
  return records.filter(record => {
    if (terms.length && !terms.every(term => record.searchText.includes(term))) return false;
    if (!recordMatchesSignals(record, state.signals, state.signalMode)) return false;
    if (state.lc && record.lcClass !== state.lc) return false;
    if (state.material && record.materialKey !== state.material) return false;
    if (state.decade && String(record.decade || "") !== state.decade) return false;
    if (state.photo && record.photo_insert_bucket !== state.photo) return false;
    return true;
  });
}

export function recordsForPath(records = [], path = {}) {
  const explicit = Array.isArray(path.item_ids) ? new Set(path.item_ids) : null;
  if (explicit?.size) return records.filter(record => explicit.has(record.id));
  return records.filter(record => recordMatchesSignals(record, path.signals || [], path.matchMode || "any"));
}

export function groupLabel(record, group = "lc") {
  if (group === "decade") return record.decade ? `${record.decade}s` : "Date unknown";
  if (group === "material") return titleCase(record.materialKey || "other");
  return record.lcClass ? `LC ${record.lcClass}` : "Other call numbers";
}

export function groupRecords(records = [], group = "lc") {
  const grouped = new Map();
  for (const record of records) {
    const label = groupLabel(record, group);
    if (!grouped.has(label)) grouped.set(label, []);
    grouped.get(label).push(record);
  }
  return [...grouped.entries()]
    .sort(([a], [b]) => {
      if (/unknown|other/i.test(a)) return 1;
      if (/unknown|other/i.test(b)) return -1;
      return a.localeCompare(b, undefined, { numeric: true });
    })
    .map(([label, items]) => ({ label, items }));
}

export function collectionFacets(records = []) {
  const classes = [...new Set(records.map(record => record.lcClass).filter(Boolean))].sort();
  const materials = [...new Set(records.map(record => record.materialKey).filter(Boolean))].sort();
  const decades = [...new Set(records.map(record => record.decade).filter(Boolean))].sort((a, b) => b - a);
  const years = records.map(record => record.yearPrimary).filter(Boolean);
  return {
    classes,
    materials,
    decades,
    minYear: years.length ? Math.min(...years) : null,
    maxYear: years.length ? Math.max(...years) : null
  };
}

export function parseUrlState(url = globalThis.location?.href || "https://example.invalid/") {
  const parsed = new URL(url, "https://example.invalid/");
  const params = parsed.searchParams;
  return {
    record: params.get("record") || "",
    query: params.get("q") || "",
    signals: (params.get("signals") || "").split(",").filter(Boolean),
    signalMode: params.get("signalMode") || "any",
    lc: params.get("lc") || "",
    material: params.get("material") || "",
    decade: params.get("decade") || "",
    photo: params.get("photo") || "",
    group: params.get("group") || "lc",
    path: params.get("path") || "",
    view: params.get("view") || "covers"
  };
}

export function serializeUrlState(rawState = {}, base = globalThis.location?.href || "https://example.invalid/") {
  const state = normalizeFilterState(rawState);
  const url = new URL(base, "https://example.invalid/");
  for (const key of ["record", "q", "signals", "signalMode", "lc", "material", "decade", "photo", "group", "path", "view"]) {
    url.searchParams.delete(key);
  }
  const values = {
    record: rawState.record,
    q: state.query,
    signals: state.signals.join(","),
    signalMode: state.signalMode !== "any" ? state.signalMode : "",
    lc: state.lc,
    material: state.material,
    decade: state.decade,
    photo: state.photo,
    group: state.group !== "lc" ? state.group : "",
    path: state.path,
    view: rawState.view && rawState.view !== "covers" ? rawState.view : ""
  };
  for (const [key, value] of Object.entries(values)) {
    if (value) url.searchParams.set(key, String(value));
  }
  return `${url.pathname}${url.search}${url.hash}`;
}

export function titleCase(value = "") {
  return String(value).replace(/[_-]+/g, " ").replace(/\b\w/g, letter => letter.toUpperCase());
}
