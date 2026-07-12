import { SIGNALS, SIGNAL_LABELS } from "./signals.js";
import {
  collectionFacets,
  enrichRecord,
  filterRecords,
  groupRecords,
  normalizeFilterState,
  parseUrlState,
  recordsForPath,
  serializeUrlState,
  titleCase
} from "./catalog.js";
import {
  applyBookStyle,
  getRecordVisual,
  parseVisualManifest,
  resolveFeaturedItems,
  shortDisplayTitle,
  stableHash
} from "./visuals.js";
import {
  loadShelfIds,
  resolveShelfRecords,
  restoreShelfFromReceipt,
  saveShelfIds,
  toggleShelfId
} from "./shelf.js";
import { createReceipt, downloadReceipt, verifyReceipt } from "./receipt.js";

const DATA_URL = new URL("../data/sekula_index.json", import.meta.url);
const VISUALS_URL = new URL("../data/book_visuals.json", import.meta.url);
const FEATURED_URL = new URL("../data/featured_items.json", import.meta.url);
const PATHS_URL = new URL("../preview/exhibit/curated-paths.json", import.meta.url);
const PAGE_SIZE = 72;
const SEARCH_SUGGESTION_LIMIT = 8;
const APP_VERSION = "2.0.0";

const $ = selector => document.querySelector(selector);
const $$ = selector => [...document.querySelectorAll(selector)];

const dom = {
  loading: $("#loadingScreen"),
  heroStage: $("#heroStage"),
  heroFocusIndex: $("#heroFocusIndex"),
  heroFocusTitle: $("#heroFocusTitle"),
  heroFocusMeta: $("#heroFocusMeta"),
  heroSignals: $("#heroSignals"),
  heroSearchForm: $("#heroSearchForm"),
  heroSearchInput: $("#heroSearchInput"),
  pathGrid: $("#pathGrid"),
  collectionCount: $("#collectionCount"),
  classCount: $("#classCount"),
  yearSpan: $("#yearSpan"),
  resultSummary: $("#resultSummary"),
  collectionGrid: $("#collectionGrid"),
  emptyState: $("#emptyState"),
  loadMoreWrap: $("#loadMoreWrap"),
  loadMore: $("#loadMore"),
  renderedCount: $("#renderedCount"),
  activeFilters: $("#activeFilters"),
  signalFilters: $("#signalFilters"),
  lcFilter: $("#lcFilter"),
  materialFilter: $("#materialFilter"),
  decadeFilter: $("#decadeFilter"),
  photoFilter: $("#photoFilter"),
  groupFilter: $("#groupFilter"),
  collectionSearch: $("#collectionSearch"),
  resetFilters: $("#resetFilters"),
  emptyReset: $("#emptyReset"),
  openSearch: $("#openSearch"),
  searchDialog: $("#searchDialog"),
  globalSearchInput: $("#globalSearchInput"),
  searchSuggestions: $("#searchSuggestions"),
  detailDrawer: $("#detailDrawer"),
  detailPosition: $("#detailPosition"),
  detailVisual: $("#detailVisual"),
  detailKicker: $("#detailKicker"),
  detailTitle: $("#detailTitle"),
  detailByline: $("#detailByline"),
  detailShelfButton: $("#detailShelfButton"),
  catalogLink: $("#catalogLink"),
  detailMetadata: $("#detailMetadata"),
  subjectList: $("#subjectList"),
  detailSubjects: $("#detailSubjects"),
  notesList: $("#notesList"),
  detailNotes: $("#detailNotes"),
  previousBook: $("#previousBook"),
  nextBook: $("#nextBook"),
  closeDetail: $("#closeDetail"),
  drawerBackdrop: $("#drawerBackdrop"),
  openShelf: $("#openShelf"),
  shelfDrawer: $("#shelfDrawer"),
  closeShelf: $("#closeShelf"),
  shelfCount: $("#shelfCount"),
  shelfList: $("#shelfList"),
  exportShelf: $("#exportShelf"),
  exportReceipt: $("#exportReceipt"),
  clearShelf: $("#clearShelf"),
  toast: $("#toast")
};

const initialUrl = parseUrlState();
const state = {
  records: [],
  recordMap: new Map(),
  filtered: [],
  paths: [],
  pathMap: new Map(),
  visuals: parseVisualManifest({}),
  featuredConfig: {},
  filters: normalizeFilterState(initialUrl),
  view: ["covers", "spines", "list"].includes(initialUrl.view) ? initialUrl.view : "covers",
  renderLimit: PAGE_SIZE,
  selectedId: initialUrl.record,
  shelfIds: loadShelfIds(),
  activeDrawer: null,
  lastFocus: null,
  syncingHistory: false
};

function textElement(tag, className, text) {
  const element = document.createElement(tag);
  if (className) element.className = className;
  element.textContent = text ?? "";
  return element;
}

function clear(element) {
  if (element) element.replaceChildren();
}

function formatNumber(value) {
  return new Intl.NumberFormat().format(value || 0);
}

function authorLabel(record) {
  return record.authors.length ? record.authors.join(", ") : "Creator not recorded";
}

function compactMeta(record) {
  return [record.authors[0], record.yearPrimary, record.call_number].filter(Boolean).join(" · ");
}

function yieldToBrowser() {
  return new Promise(resolve => {
    if ("requestIdleCallback" in window) window.requestIdleCallback(resolve, { timeout: 60 });
    else setTimeout(resolve, 0);
  });
}

async function enrichInBatches(rawRecords) {
  const enriched = [];
  const progress = dom.loading?.querySelector("p");
  for (let index = 0; index < rawRecords.length; index += 300) {
    const slice = rawRecords.slice(index, index + 300);
    for (const record of slice) enriched.push(enrichRecord(record));
    if (progress && index % 1200 === 0) progress.textContent = `Reading catalog metadata · ${formatNumber(Math.min(index + slice.length, rawRecords.length))}`;
    await yieldToBrowser();
  }
  return enriched;
}

async function fetchJson(url, fallback) {
  try {
    const response = await fetch(url);
    if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
    return await response.json();
  } catch (error) {
    console.warn(`ShelfSignals could not load ${url}:`, error);
    return fallback;
  }
}

function setStyles(element, properties) {
  for (const [property, value] of Object.entries(properties)) element.style.setProperty(property, value);
}

function appendCoverImage(container, record, visual, eager = false) {
  if (!visual) return;
  const image = document.createElement("img");
  image.className = "cover-image";
  image.src = visual.thumbnail_url || visual.image_url;
  image.alt = "";
  image.loading = eager ? "eager" : "lazy";
  image.decoding = "async";
  image.addEventListener("error", () => {
    image.remove();
    container.classList.remove("has-cover");
    container.style.removeProperty("--cover-image");
  }, { once: true });
  container.prepend(image);
}

function makeBookObject(record, { detail = false, eager = false } = {}) {
  const visual = getRecordVisual(record, state.visuals);
  const object = document.createElement("div");
  object.className = "book-object";
  applyBookStyle(object, record, visual);
  appendCoverImage(object, record, visual, eager);

  object.append(
    textElement("span", "book-cover-class", [record.material_type, record.call_number].filter(Boolean).join(" · ")),
    textElement("strong", "book-cover-title", record.displayTitle),
    (() => {
      const meta = document.createElement("span");
      meta.className = "book-cover-meta";
      meta.append(textElement("span", "", record.authors[0] || "Allan Sekula Library"));
      meta.append(textElement("span", "", record.yearPrimary || record.year || "Date unknown"));
      return meta;
    })()
  );
  object.setAttribute("aria-hidden", detail ? "false" : "true");
  return object;
}

function renderHero() {
  clear(dom.heroStage);
  const featured = resolveFeaturedItems(state.records, state.featuredConfig, state.visuals, 11);
  featured.forEach((record, index) => {
    const visual = getRecordVisual(record, state.visuals);
    const button = document.createElement("button");
    button.type = "button";
    button.className = "hero-book";
    button.setAttribute("role", "listitem");
    button.setAttribute("aria-label", `Open ${record.title}${record.authors[0] ? ` by ${record.authors[0]}` : ""}`);
    applyBookStyle(button, record, visual);
    appendCoverImage(button, record, visual, index < 5);
    const spine = document.createElement("span");
    spine.className = "hero-book-spine";
    spine.append(textElement("strong", "", record.displayTitle));
    spine.append(textElement("small", "", record.authors[0] || record.call_number));
    button.append(spine);
    const focus = () => {
      $$(".hero-book.is-focused").forEach(item => item.classList.remove("is-focused"));
      button.classList.add("is-focused");
      dom.heroFocusIndex.textContent = String(index + 1).padStart(2, "0");
      dom.heroFocusTitle.textContent = record.displayTitle;
      dom.heroFocusMeta.textContent = compactMeta(record);
    };
    button.addEventListener("mouseenter", focus);
    button.addEventListener("focus", focus);
    button.addEventListener("click", () => openDetail(record.id, true));
    dom.heroStage.append(button);
    if (index === 0) focus();
  });
}

function signalShortLabel(signal) {
  return signal.label.split(" /")[0];
}

function renderHeroSignals() {
  clear(dom.heroSignals);
  SIGNALS.slice(0, 8).forEach(signal => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "signal-chip";
    button.textContent = signalShortLabel(signal);
    button.style.setProperty("--signal-color", signal.color);
    button.setAttribute("aria-pressed", state.filters.signals.includes(signal.id) ? "true" : "false");
    button.addEventListener("click", () => {
      state.filters = normalizeFilterState({ ...state.filters, signals: [signal.id], signalMode: "any", path: "" });
      syncFilterControls();
      applyFilters({ scroll: true });
    });
    dom.heroSignals.append(button);
  });
}

function renderStats() {
  const facets = collectionFacets(state.records);
  dom.collectionCount.textContent = formatNumber(state.records.length);
  dom.classCount.textContent = formatNumber(facets.classes.length);
  dom.yearSpan.textContent = facets.minYear && facets.maxYear ? `${facets.minYear}–${facets.maxYear}` : "Cataloged dates";
}

function pathColor(path, index) {
  const signal = SIGNALS.find(item => path.signals?.includes(item.id));
  return signal?.color || ["#785842", "#3e5d63", "#5a4d68", "#5f6045"][index % 4];
}

function renderPaths() {
  clear(dom.pathGrid);
  state.paths.slice(0, 8).forEach((path, index) => {
    const results = recordsForPath(state.records, path);
    const button = document.createElement("button");
    button.type = "button";
    button.className = "path-card";
    button.style.setProperty("--path-color", pathColor(path, index));
    button.style.setProperty("--path-x", `${42 + (stableHash(path.id) % 48)}%`);
    button.setAttribute("aria-label", `Open path ${path.title}, ${formatNumber(results.length)} matching records`);
    button.append(textElement("span", "path-number", `PATH ${String(index + 1).padStart(2, "0")}`));
    button.append(textElement("span", "path-signals", (path.signals || []).map(id => SIGNAL_LABELS[id]?.split(" /")[0] || id).join(" · ")));
    button.append(textElement("h3", "", path.title));
    button.append(textElement("p", "", path.subtitle || path.narrative || "A dynamic route through catalog metadata."));
    button.append(textElement("span", "path-count", `${formatNumber(results.length)} matching records →`));
    button.addEventListener("click", () => applyPath(path));
    dom.pathGrid.append(button);
  });
}

function applyPath(path) {
  state.filters = normalizeFilterState({
    ...state.filters,
    query: "",
    signals: path.signals || [],
    signalMode: path.matchMode || "any",
    lc: "",
    material: "",
    decade: "",
    photo: "",
    path: path.id
  });
  dom.heroSearchInput.value = "";
  syncFilterControls();
  applyFilters({ scroll: true });
}

function addOption(select, value, label) {
  const option = document.createElement("option");
  option.value = value;
  option.textContent = label;
  select.append(option);
}

function initFacetControls() {
  const facets = collectionFacets(state.records);
  facets.classes.forEach(value => addOption(dom.lcFilter, value, value));
  facets.materials.forEach(value => addOption(dom.materialFilter, value, titleCase(value)));
  facets.decades.forEach(value => addOption(dom.decadeFilter, String(value), `${value}s`));
  ["Strongly Likely", "Likely", "Plausible", "Unlikely"].forEach(value => addOption(dom.photoFilter, value, value));

  clear(dom.signalFilters);
  SIGNALS.forEach(signal => {
    const label = document.createElement("label");
    label.style.setProperty("--signal-color", signal.color);
    const input = document.createElement("input");
    input.type = "checkbox";
    input.value = signal.id;
    input.addEventListener("change", () => {
      const selected = $$("#signalFilters input:checked").map(item => item.value);
      state.filters = normalizeFilterState({ ...state.filters, signals: selected, path: "" });
      applyFilters();
    });
    label.append(input, document.createTextNode(signalShortLabel(signal)));
    dom.signalFilters.append(label);
  });
}

function syncFilterControls() {
  dom.collectionSearch.value = state.filters.query;
  dom.lcFilter.value = state.filters.lc;
  dom.materialFilter.value = state.filters.material;
  dom.decadeFilter.value = state.filters.decade;
  dom.photoFilter.value = state.filters.photo;
  dom.groupFilter.value = state.filters.group;
  $$("#signalFilters input").forEach(input => { input.checked = state.filters.signals.includes(input.value); });
  renderHeroSignals();
}

function debounce(callback, delay = 220) {
  let timer = 0;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => callback(...args), delay);
  };
}

function resetFilters({ scroll = false } = {}) {
  state.filters = normalizeFilterState({ group: state.filters.group });
  state.renderLimit = PAGE_SIZE;
  dom.heroSearchInput.value = "";
  syncFilterControls();
  applyFilters({ scroll });
}

function updateUrl({ selectedId = state.selectedId, replace = true } = {}) {
  if (state.syncingHistory) return;
  const url = serializeUrlState({ ...state.filters, record: selectedId, view: state.view });
  history[replace ? "replaceState" : "pushState"]({ shelfsignals: true }, "", url);
}

function applyFilters({ scroll = false } = {}) {
  state.renderLimit = PAGE_SIZE;
  state.filtered = filterRecords(state.records, state.filters);
  renderCollection();
  renderActiveFilters();
  updateUrl();
  if (scroll) $("#collection").scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
}

function activeFilterEntries() {
  const entries = [];
  if (state.filters.path) entries.push({ key: "path", label: `Path: ${state.pathMap.get(state.filters.path)?.title || state.filters.path}` });
  if (state.filters.query) entries.push({ key: "query", label: `Search: ${state.filters.query}` });
  state.filters.signals.forEach(signal => entries.push({ key: `signal:${signal}`, label: SIGNAL_LABELS[signal]?.split(" /")[0] || signal }));
  if (state.filters.lc) entries.push({ key: "lc", label: `LC ${state.filters.lc}` });
  if (state.filters.material) entries.push({ key: "material", label: titleCase(state.filters.material) });
  if (state.filters.decade) entries.push({ key: "decade", label: `${state.filters.decade}s` });
  if (state.filters.photo) entries.push({ key: "photo", label: state.filters.photo });
  return entries;
}

function removeActiveFilter(key) {
  const next = { ...state.filters, path: "" };
  if (key.startsWith("signal:")) next.signals = next.signals.filter(id => id !== key.slice(7));
  else if (key === "query") next.query = "";
  else next[key] = "";
  state.filters = normalizeFilterState(next);
  syncFilterControls();
  applyFilters();
}

function renderActiveFilters() {
  clear(dom.activeFilters);
  activeFilterEntries().forEach(entry => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "active-filter";
    button.textContent = `${entry.label} ×`;
    button.setAttribute("aria-label", `Remove ${entry.label} filter`);
    button.addEventListener("click", () => removeActiveFilter(entry.key));
    dom.activeFilters.append(button);
  });
}

function createCoverCard(record, index) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "book-card";
  button.setAttribute("role", "listitem");
  button.setAttribute("aria-label", `Open ${record.title}${record.authors[0] ? ` by ${record.authors[0]}` : ""}`);
  button.append(makeBookObject(record));
  button.append(textElement("strong", "book-card-title", record.displayTitle));
  button.append(textElement("span", "book-card-meta", compactMeta(record) || record.material_type));
  button.addEventListener("click", () => openDetail(record.id, true));
  button.dataset.recordId = record.id;
  button.dataset.index = String(index);
  return button;
}

function createListBook(record, index) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "list-book";
  button.setAttribute("role", "listitem");
  button.append(textElement("span", "list-book-index", String(index + 1).padStart(3, "0")));
  button.append(textElement("span", "list-book-title", record.title));
  button.append(textElement("span", "list-book-author", authorLabel(record)));
  button.append(textElement("span", "list-book-year", record.yearPrimary || record.year || "—"));
  button.append(textElement("span", "list-book-call", record.call_number || "—"));
  button.append(textElement("span", "", "→"));
  button.addEventListener("click", () => openDetail(record.id, true));
  return button;
}

function createSpine(record) {
  const button = document.createElement("button");
  button.type = "button";
  button.className = "spine-book";
  button.textContent = record.displayTitle;
  button.title = `${record.title}${compactMeta(record) ? ` — ${compactMeta(record)}` : ""}`;
  button.setAttribute("aria-label", `Open ${record.title}`);
  applyBookStyle(button, record, null);
  button.addEventListener("click", () => openDetail(record.id, true));
  return button;
}

function renderCollection() {
  clear(dom.collectionGrid);
  const total = state.records.length;
  const count = state.filtered.length;
  const rendered = Math.min(state.renderLimit, count);
  dom.resultSummary.textContent = `${formatNumber(count)} of ${formatNumber(total)} records${state.filters.path ? ` · dynamic path “${state.pathMap.get(state.filters.path)?.title || state.filters.path}”` : ""}`;
  dom.collectionGrid.className = `collection-grid ${state.view}-view`;
  dom.emptyState.hidden = count !== 0;
  dom.collectionGrid.hidden = count === 0;

  if (count) {
    const visible = state.filtered.slice(0, state.renderLimit);
    if (state.view === "covers") {
      visible.forEach((record, index) => dom.collectionGrid.append(createCoverCard(record, index)));
    } else if (state.view === "list") {
      visible.forEach((record, index) => dom.collectionGrid.append(createListBook(record, index)));
    } else {
      groupRecords(visible, state.filters.group).forEach(group => {
        const section = document.createElement("section");
        section.className = "spine-group";
        const header = document.createElement("header");
        header.className = "spine-group-header";
        header.append(textElement("span", "", group.label), textElement("span", "", `${formatNumber(group.items.length)} shown`));
        const shelf = document.createElement("div");
        shelf.className = "spine-shelf";
        shelf.setAttribute("role", "list");
        group.items.forEach(record => shelf.append(createSpine(record)));
        section.append(header, shelf);
        dom.collectionGrid.append(section);
      });
    }
  }

  dom.loadMoreWrap.hidden = count === 0;
  dom.loadMore.hidden = rendered >= count;
  dom.renderedCount.textContent = count ? `${formatNumber(rendered)} rendered · bounded page size ${PAGE_SIZE}` : "";
}

function metadataRow(label, value) {
  if (!value && value !== 0) return null;
  const wrapper = document.createElement("div");
  wrapper.append(textElement("dt", "", label), textElement("dd", "", String(value)));
  return wrapper;
}

function setDrawer(drawer, open) {
  if (open) {
    if (state.activeDrawer && state.activeDrawer !== drawer) setDrawer(state.activeDrawer, false);
    state.activeDrawer = drawer;
    state.lastFocus = document.activeElement;
    drawer.classList.add("open");
    drawer.setAttribute("aria-hidden", "false");
    dom.drawerBackdrop.hidden = false;
    document.body.classList.add("drawer-open");
    requestAnimationFrame(() => drawer.querySelector("button, a")?.focus());
  } else {
    drawer.classList.remove("open");
    drawer.setAttribute("aria-hidden", "true");
    if (state.activeDrawer === drawer) state.activeDrawer = null;
    if (!state.activeDrawer) {
      dom.drawerBackdrop.hidden = true;
      document.body.classList.remove("drawer-open");
      if (state.lastFocus?.isConnected) state.lastFocus.focus();
    }
  }
}

function renderDetail(record) {
  const position = state.filtered.findIndex(item => item.id === record.id);
  dom.detailPosition.textContent = position >= 0 ? `Record ${formatNumber(position + 1)} of ${formatNumber(state.filtered.length)}` : "Collection record";
  clear(dom.detailVisual);
  dom.detailVisual.append(makeBookObject(record, { detail: true, eager: true }));
  dom.detailKicker.textContent = [record.material_type, record.call_number].filter(Boolean).join(" · ");
  dom.detailTitle.textContent = record.title;
  dom.detailByline.textContent = [record.authors.length ? `By ${record.authors.join(", ")}` : "", record.year].filter(Boolean).join(" · ");
  dom.catalogLink.href = record.catalogLink;
  dom.catalogLink.hidden = !record.catalogLink;
  updateDetailShelfButton(record.id);
  dom.detailShelfButton.onclick = () => toggleShelf(record.id);
  dom.previousBook.disabled = position <= 0;
  dom.nextBook.disabled = position < 0 || position >= state.filtered.length - 1;

  clear(dom.detailMetadata);
  const publisher = record.publishers.join(" · ");
  const format = record.formats.join(" · ");
  const photoValue = record.photo_insert_bucket
    ? `${record.photo_insert_bucket}${record.photo_insert_score != null ? ` · ${record.photo_insert_score}/100` : ""} (experimental metadata estimate)`
    : "";
  [
    metadataRow("Contributors", record.contributors.join(" · ")),
    metadataRow("Publication", record.year),
    metadataRow("Publisher", publisher),
    metadataRow("Material", record.material_type),
    metadataRow("Physical format", format),
    metadataRow("Call number", record.call_number),
    metadataRow("Availability", titleCase(record.availability)),
    metadataRow("ISBN", record.isbns.join(" · ")),
    metadataRow("OCLC", record.oclc_numbers.join(" · ")),
    metadataRow("Photo likelihood", photoValue),
    record.photo_insert_reasoning ? metadataRow("Estimate note", record.photo_insert_reasoning) : null
  ].filter(Boolean).forEach(row => dom.detailMetadata.append(row));

  clear(dom.subjectList);
  record.subjects.slice(0, 24).forEach(subject => dom.subjectList.append(textElement("span", "", subject)));
  dom.detailSubjects.hidden = !record.subjects.length;
  clear(dom.notesList);
  [...record.notes, ...record.sekula_notes, ...record.provenance_notes].slice(0, 16).forEach(note => dom.notesList.append(textElement("p", "", note)));
  dom.detailNotes.hidden = !dom.notesList.childElementCount;
}

function openDetail(id, updateHistory = false) {
  const record = state.recordMap.get(id);
  if (!record) return;
  state.selectedId = id;
  renderDetail(record);
  setDrawer(dom.detailDrawer, true);
  updateUrl({ selectedId: id, replace: !updateHistory });
}

function closeDetail({ updateHistory = true } = {}) {
  setDrawer(dom.detailDrawer, false);
  state.selectedId = "";
  if (updateHistory) updateUrl({ selectedId: "" });
}

function navigateDetail(direction) {
  const index = state.filtered.findIndex(record => record.id === state.selectedId);
  const next = state.filtered[index + direction];
  if (next) openDetail(next.id);
}

function updateDetailShelfButton(id) {
  const saved = state.shelfIds.includes(id);
  dom.detailShelfButton.textContent = saved ? "Remove from My Shelf" : "Add to My Shelf";
  dom.detailShelfButton.setAttribute("aria-pressed", saved ? "true" : "false");
}

function toggleShelf(id) {
  const wasSaved = state.shelfIds.includes(id);
  const next = toggleShelfId(state.shelfIds, id);
  const saved = saveShelfIds(next);
  state.shelfIds = saved.ids;
  renderShelf();
  if (state.selectedId === id) updateDetailShelfButton(id);
  showToast(wasSaved ? "Removed from My Shelf" : "Added to My Shelf");
}

function renderShelf() {
  const records = resolveShelfRecords(state.shelfIds, state.records);
  dom.shelfCount.textContent = String(records.length);
  clear(dom.shelfList);
  if (!records.length) {
    dom.shelfList.append(textElement("div", "shelf-empty", "Your shelf is empty. Open a record to begin a reading list."));
  } else {
    records.forEach((record, index) => {
      const item = document.createElement("article");
      item.className = "shelf-item";
      item.append(textElement("span", "shelf-item-index", String(index + 1).padStart(2, "0")));
      const copy = document.createElement("div");
      copy.append(textElement("strong", "", record.displayTitle));
      copy.append(textElement("small", "", compactMeta(record)));
      const remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = "✕";
      remove.setAttribute("aria-label", `Remove ${record.title} from My Shelf`);
      remove.addEventListener("click", () => toggleShelf(record.id));
      item.append(copy, remove);
      item.addEventListener("dblclick", () => openDetail(record.id, true));
      dom.shelfList.append(item);
    });
  }
  dom.exportShelf.disabled = !records.length;
  dom.exportReceipt.disabled = !records.length;
  dom.clearShelf.disabled = !records.length;
}

function exportShelfText() {
  const records = resolveShelfRecords(state.shelfIds, state.records);
  if (!records.length) return showToast("Your shelf is empty");
  const body = records.map((record, index) => [
    `${index + 1}. ${record.title}`,
    record.authors.length ? `   ${record.authors.join(", ")}` : "",
    `   ${[record.year, record.call_number].filter(Boolean).join(" · ")}`,
    record.catalogLink ? `   ${record.catalogLink}` : ""
  ].filter(Boolean).join("\n")).join("\n\n");
  downloadBlob(body, `shelfsignals-shelf-${new Date().toISOString().slice(0, 10)}.txt`, "text/plain");
  showToast("Shelf list exported");
}

async function exportShelfReceipt() {
  const records = resolveShelfRecords(state.shelfIds, state.records);
  if (!records.length) return showToast("Your shelf is empty");
  const receipt = await createReceipt({
    mode: "shelf",
    items: records,
    filters: state.filters,
    datasetName: "Allan Sekula Library",
    datasetUrl: DATA_URL.href,
    appVersion: APP_VERSION
  });
  downloadReceipt(receipt);
  showToast("Digital Receipt exported");
}

function downloadBlob(content, filename, type) {
  const url = URL.createObjectURL(new Blob([content], { type }));
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = filename;
  anchor.click();
  setTimeout(() => URL.revokeObjectURL(url), 0);
}

function restoreReceiptFile(file) {
  if (!file) return;
  file.text().then(async text => {
    try {
      const receipt = JSON.parse(text);
      const verification = await verifyReceipt(receipt);
      if (!verification.valid) throw new Error(verification.reason);
      const restored = restoreShelfFromReceipt(receipt, state.records);
      if (!restored.valid) throw new Error("Unsupported receipt schema");
      state.shelfIds = restored.ids;
      saveShelfIds(restored.ids);
      renderShelf();
      showToast(`Restored ${restored.ids.length} records${restored.missing.length ? ` · ${restored.missing.length} unavailable` : ""}`);
    } catch (error) {
      showToast(`Receipt could not be restored: ${error.message}`);
    }
  });
}

function addRestoreReceiptControl() {
  const button = document.createElement("button");
  button.type = "button";
  button.textContent = "Restore receipt";
  const input = document.createElement("input");
  input.type = "file";
  input.accept = "application/json,.json";
  input.className = "sr-only";
  input.addEventListener("change", () => restoreReceiptFile(input.files?.[0]));
  button.addEventListener("click", () => input.click());
  dom.exportReceipt.after(button, input);
}

let toastTimer = 0;
function showToast(message) {
  clearTimeout(toastTimer);
  dom.toast.textContent = message;
  dom.toast.classList.add("show");
  toastTimer = setTimeout(() => dom.toast.classList.remove("show"), 2800);
}

function openSearchDialog() {
  if (!dom.searchDialog.open) dom.searchDialog.showModal();
  dom.globalSearchInput.value = state.filters.query;
  renderSearchSuggestions(dom.globalSearchInput.value);
  requestAnimationFrame(() => dom.globalSearchInput.focus());
}

function renderSearchSuggestions(query) {
  clear(dom.searchSuggestions);
  const trimmed = String(query || "").trim();
  const matches = trimmed ? filterRecords(state.records, { query: trimmed }).slice(0, SEARCH_SUGGESTION_LIMIT) : resolveFeaturedItems(state.records, state.featuredConfig, state.visuals, SEARCH_SUGGESTION_LIMIT);
  if (!matches.length) {
    dom.searchSuggestions.append(textElement("p", "shelf-empty", "No catalog records match this search."));
    return;
  }
  matches.forEach((record, index) => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "search-suggestion";
    button.append(textElement("span", "search-suggestion-index", String(index + 1).padStart(2, "0")));
    const copy = document.createElement("span");
    copy.append(textElement("strong", "", record.displayTitle), textElement("small", "", compactMeta(record)));
    button.append(copy, textElement("span", "", "→"));
    button.addEventListener("click", () => {
      dom.searchDialog.close();
      openDetail(record.id, true);
    });
    dom.searchSuggestions.append(button);
  });
}

function bindEvents() {
  const updateSearch = debounce(value => {
    state.filters = normalizeFilterState({ ...state.filters, query: value, path: "" });
    applyFilters();
  });
  dom.collectionSearch.addEventListener("input", event => updateSearch(event.target.value));
  dom.heroSearchForm.addEventListener("submit", event => {
    event.preventDefault();
    state.filters = normalizeFilterState({ ...state.filters, query: dom.heroSearchInput.value, path: "" });
    syncFilterControls();
    applyFilters({ scroll: true });
  });
  [[dom.lcFilter, "lc"], [dom.materialFilter, "material"], [dom.decadeFilter, "decade"], [dom.photoFilter, "photo"], [dom.groupFilter, "group"]].forEach(([select, key]) => {
    select.addEventListener("change", () => {
      state.filters = normalizeFilterState({ ...state.filters, [key]: select.value, path: key === "group" ? state.filters.path : "" });
      applyFilters();
    });
  });
  dom.resetFilters.addEventListener("click", () => resetFilters());
  dom.emptyReset.addEventListener("click", () => resetFilters());
  dom.loadMore.addEventListener("click", () => { state.renderLimit += PAGE_SIZE; renderCollection(); });
  $$(".view-button").forEach(button => button.addEventListener("click", () => {
    state.view = button.dataset.view;
    $$(".view-button").forEach(candidate => {
      const active = candidate === button;
      candidate.classList.toggle("active", active);
      candidate.setAttribute("aria-pressed", active ? "true" : "false");
    });
    state.renderLimit = PAGE_SIZE;
    renderCollection();
    updateUrl();
  }));
  dom.openSearch.addEventListener("click", openSearchDialog);
  dom.globalSearchInput.addEventListener("input", debounce(event => renderSearchSuggestions(event.target.value), 120));
  dom.globalSearchInput.addEventListener("keydown", event => {
    if (event.key === "Enter") {
      event.preventDefault();
      dom.searchDialog.close();
      state.filters = normalizeFilterState({ ...state.filters, query: event.currentTarget.value, path: "" });
      syncFilterControls();
      applyFilters({ scroll: true });
    }
  });
  dom.closeDetail.addEventListener("click", () => closeDetail());
  dom.previousBook.addEventListener("click", () => navigateDetail(-1));
  dom.nextBook.addEventListener("click", () => navigateDetail(1));
  dom.drawerBackdrop.addEventListener("click", () => state.activeDrawer === dom.detailDrawer ? closeDetail() : setDrawer(dom.shelfDrawer, false));
  dom.openShelf.addEventListener("click", () => setDrawer(dom.shelfDrawer, true));
  dom.closeShelf.addEventListener("click", () => setDrawer(dom.shelfDrawer, false));
  dom.exportShelf.addEventListener("click", exportShelfText);
  dom.exportReceipt.addEventListener("click", exportShelfReceipt);
  dom.clearShelf.addEventListener("click", () => {
    if (!state.shelfIds.length || !confirm("Clear every record from My Shelf?")) return;
    state.shelfIds = [];
    saveShelfIds([]);
    renderShelf();
    showToast("My Shelf cleared");
  });
  document.addEventListener("keydown", event => {
    if ((event.metaKey || event.ctrlKey) && event.key.toLocaleLowerCase() === "k") {
      event.preventDefault();
      openSearchDialog();
    }
    if (event.key === "Escape" && state.activeDrawer) {
      if (state.activeDrawer === dom.detailDrawer) closeDetail();
      else setDrawer(state.activeDrawer, false);
    }
    if (event.key === "Tab" && state.activeDrawer) {
      const focusable = [...state.activeDrawer.querySelectorAll("button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), [tabindex]:not([tabindex='-1'])")]
        .filter(element => !element.hidden && element.getClientRects().length);
      if (focusable.length) {
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) {
          event.preventDefault();
          last.focus();
        } else if (!event.shiftKey && document.activeElement === last) {
          event.preventDefault();
          first.focus();
        }
      }
    }
    if (state.activeDrawer === dom.detailDrawer && event.key === "ArrowLeft") navigateDetail(-1);
    if (state.activeDrawer === dom.detailDrawer && event.key === "ArrowRight") navigateDetail(1);
  });
  window.addEventListener("popstate", () => {
    const restored = parseUrlState();
    state.syncingHistory = true;
    state.filters = normalizeFilterState(restored);
    state.view = ["covers", "spines", "list"].includes(restored.view) ? restored.view : "covers";
    state.selectedId = restored.record;
    syncFilterControls();
    state.filtered = filterRecords(state.records, state.filters);
    renderCollection();
    renderActiveFilters();
    $$(".view-button").forEach(button => {
      const active = button.dataset.view === state.view;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", active ? "true" : "false");
    });
    if (state.selectedId && state.recordMap.has(state.selectedId)) openDetail(state.selectedId);
    else if (state.activeDrawer === dom.detailDrawer) closeDetail({ updateHistory: false });
    state.syncingHistory = false;
  });
}

async function init() {
  try {
    const [rawData, rawVisuals, featuredConfig, pathConfig] = await Promise.all([
      fetchJson(DATA_URL, []),
      fetchJson(VISUALS_URL, {}),
      fetchJson(FEATURED_URL, {}),
      fetchJson(PATHS_URL, { paths: [] })
    ]);
    const rawRecords = Array.isArray(rawData) ? rawData : (rawData.items || []);
    if (!rawRecords.length) throw new Error("The collection dataset is empty or unavailable.");
    state.visuals = parseVisualManifest(rawVisuals);
    state.featuredConfig = featuredConfig || {};
    state.paths = Array.isArray(pathConfig.paths) ? pathConfig.paths : [];
    state.pathMap = new Map(state.paths.map(path => [path.id, path]));
    state.records = await enrichInBatches(rawRecords);
    state.recordMap = new Map(state.records.map(record => [record.id, record]));
    state.filtered = filterRecords(state.records, state.filters);

    renderHero();
    renderHeroSignals();
    renderStats();
    renderPaths();
    initFacetControls();
    syncFilterControls();
    bindEvents();
    addRestoreReceiptControl();
    renderShelf();
    renderActiveFilters();
    renderCollection();
    $$(".view-button").forEach(button => {
      const active = button.dataset.view === state.view;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", active ? "true" : "false");
    });

    if (state.filters.path && state.pathMap.has(state.filters.path) && !state.filters.signals.length) {
      const path = state.pathMap.get(state.filters.path);
      state.filters = normalizeFilterState({ ...state.filters, signals: path.signals || [], signalMode: path.matchMode || "any" });
      syncFilterControls();
      applyFilters();
    }
    if (state.selectedId && state.recordMap.has(state.selectedId)) openDetail(state.selectedId);
    else if (state.selectedId) {
      state.selectedId = "";
      updateUrl({ selectedId: "" });
    }
    dom.loading.classList.add("ready");
    setTimeout(() => dom.loading.remove(), 700);
  } catch (error) {
    console.error("ShelfSignals initialization failed:", error);
    const progress = dom.loading?.querySelector("p");
    if (progress) progress.textContent = `The library could not be opened: ${error.message}`;
    dom.loading?.classList.add("error");
  }
}

init();
