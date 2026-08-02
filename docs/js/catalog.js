import { deriveSignals } from "./signals.js";
import { parseLcCallNumber } from "./lc.js";
import { normalizePlacementKey, parsePhysicalIdentifiers, recordMatchesPlacement } from "./placement.js";
import { normalizeYear } from "./year.js";
import { shortDisplayTitle } from "./visuals.js";

function arrayValue(value) {
  return Array.isArray(value) ? value.filter(Boolean).map(String) : (value ? [String(value)] : []);
}

function namedArrayValue(value) {
  return Array.isArray(value)
    ? value.map(item => typeof item === "string" ? item : item?.name).filter(Boolean).map(String)
    : [];
}

export function enrichRecord(record = {}) {
  const authors = arrayValue(record.authors);
  const contributors = namedArrayValue(record.contributors).length
    ? namedArrayValue(record.contributors)
    : arrayValue(record.contributors);
  const subjects = [...new Set(arrayValue(record.subjects))];
  const notes = arrayValue(record.notes);
  const provenance = arrayValue(record.provenance_notes);
  const sekulaNotes = arrayValue(record.sekula_notes);
  const placements = Array.isArray(record.placements)
    ? record.placements.filter(placement => placement?.key && placement?.label).map(placement => ({ ...placement }))
    : parsePhysicalIdentifiers({ provenance_notes: provenance, sekula_notes: sekulaNotes });
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
  const signals = Array.isArray(record.signals)
    ? [...new Set(record.signals.filter(Boolean).map(String))]
    : deriveSignals(subjects, [...notes, ...provenance, ...sekulaNotes, record.title, record.description]);
  const derivedSearchText = [
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
    ...placements.map(placement => placement.label),
    record.description,
    ...arrayValue(record.publishers),
    ...arrayValue(record.formats),
    ...arrayValue(record.table_of_contents),
    ...identifiers
  ].filter(Boolean).join(" \u241f ").toLocaleLowerCase();
  const searchText = typeof record.searchText === "string" ? record.searchText : derivedSearchText;
  const publications = Array.isArray(record.publication) ? record.publication.filter(item => item && typeof item === "object") : [];
  const publishers = arrayValue(record.publishers).length
    ? arrayValue(record.publishers)
    : publications.map(item => item.publisher).filter(Boolean).map(String);
  const places = arrayValue(record.places).length
    ? arrayValue(record.places)
    : publications.map(item => item.place).filter(Boolean).map(String);

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
    placements,
    publishers,
    places,
    publication_places: places,
    languages: arrayValue(record.languages),
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
    evidence: String(state.evidence || ""),
    photo: String(state.photo || ""),
    placement: normalizePlacementKey(state.placement),
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
    if (state.evidence && record.evidence_status !== state.evidence) return false;
    if (state.photo && record.photo_insert_bucket !== state.photo) return false;
    if (state.placement && !recordMatchesPlacement(record, state.placement)) return false;
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
  const collectionValue = (params.get("collection") || "sekula").toLocaleLowerCase();
  const corpusValue = (params.get("corpus") || "").toLocaleLowerCase();
  const orderValue = (params.get("order") || "").toLocaleLowerCase();
  const collection = ["sekula", "jefferson"].includes(collectionValue) ? collectionValue : "sekula";
  const allowedOrders = collection === "jefferson" ? ["sowerby", "title", "lc"] : ["catalog", "title", "lc"];
  const sekulaState = collection === "sekula";
  const viewValue = params.get("view") || "covers";
  return {
    collection,
    corpus: collection === "jefferson" && ["catalog", "historical"].includes(corpusValue) ? corpusValue : "",
    order: allowedOrders.includes(orderValue) ? orderValue : "",
    record: params.get("record") || "",
    query: params.get("q") || "",
    signals: sekulaState ? (params.get("signals") || "").split(",").filter(Boolean) : [],
    signalMode: sekulaState && params.get("signalMode") === "all" ? "all" : "any",
    lc: params.get("lc") || "",
    material: params.get("material") || "",
    decade: params.get("decade") || "",
    evidence: collection === "jefferson" ? (params.get("evidence") || "") : "",
    photo: sekulaState ? (params.get("photo") || "") : "",
    placement: sekulaState ? (params.get("placement") || "") : "",
    group: sekulaState ? (params.get("group") || "lc") : "lc",
    path: sekulaState ? (params.get("path") || "") : "",
    journey: sekulaState ? (params.get("journey") || "") : "",
    cluster: sekulaState ? (params.get("cluster") || "") : "",
    event: collection === "jefferson" && corpusValue === "historical" ? (params.get("event") || "") : "",
    view: collection === "jefferson" && viewValue === "spines" ? "covers" : viewValue
  };
}

export function serializeUrlState(rawState = {}, base = globalThis.location?.href || "https://example.invalid/") {
  const state = normalizeFilterState(rawState);
  const url = new URL(base, "https://example.invalid/");
  for (const key of ["collection", "corpus", "order", "record", "q", "signals", "signalMode", "lc", "material", "decade", "evidence", "photo", "placement", "group", "path", "journey", "cluster", "event", "view"]) {
    url.searchParams.delete(key);
  }
  const collection = String(rawState.collection || "sekula").toLocaleLowerCase() === "jefferson" ? "jefferson" : "sekula";
  const corpus = ["catalog", "historical"].includes(String(rawState.corpus || "").toLocaleLowerCase())
    ? String(rawState.corpus).toLocaleLowerCase()
    : "";
  const allowedOrders = collection === "jefferson" ? ["sowerby", "title", "lc"] : ["catalog", "title", "lc"];
  const order = allowedOrders.includes(String(rawState.order || "").toLocaleLowerCase())
    ? String(rawState.order).toLocaleLowerCase()
    : "";
  const sekulaState = collection === "sekula";
  const values = {
    collection: collection === "jefferson" ? collection : "",
    corpus: collection === "jefferson" ? corpus : "",
    order: collection === "jefferson" ? order : (order && order !== "catalog" ? order : ""),
    record: rawState.record,
    q: state.query,
    signals: sekulaState ? state.signals.join(",") : "",
    signalMode: sekulaState && state.signalMode !== "any" ? state.signalMode : "",
    lc: state.lc,
    material: state.material,
    decade: state.decade,
    evidence: collection === "jefferson" ? state.evidence : "",
    photo: sekulaState ? state.photo : "",
    placement: sekulaState ? state.placement : "",
    group: sekulaState && state.group !== "lc" ? state.group : "",
    path: sekulaState ? state.path : "",
    journey: sekulaState ? rawState.journey : "",
    cluster: sekulaState && rawState.journey ? rawState.cluster : "",
    event: collection === "jefferson" && corpus === "historical" ? rawState.event : "",
    view: rawState.view && rawState.view !== "covers" && !(collection === "jefferson" && rawState.view === "spines") ? rawState.view : ""
  };
  for (const [key, value] of Object.entries(values)) {
    if (value) url.searchParams.set(key, String(value));
  }
  return `${url.pathname}${url.search}${url.hash}`;
}

export function titleCase(value = "") {
  return String(value).replace(/[_-]+/g, " ").replace(/\b\w/g, letter => letter.toUpperCase());
}
