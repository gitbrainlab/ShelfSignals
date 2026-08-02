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
  hydrateCatalogRecord,
  parseBrowserCatalog,
  parseCatalogDetailShard,
  parseCatalogSearchIndex
} from "./catalog-data.js";
import {
  applyBookStyle,
  parseVisualManifest,
  resolveFeaturedItems,
  shortDisplayTitle,
  stableHash
} from "./visuals.js";
import {
  PROVIDER_REFERENCE_LABEL,
  REVIEWED_COVER_LABEL,
  UNRESOLVED_COVER_LABEL,
  canDisplayCover,
  getRecordCoverProvenance,
  getRecordCoverState,
  parseCoverIndex,
  parseCoverProvenance
} from "./covers.js";
import {
  JOURNEY_PHASES,
  associationClaimLabel,
  getPublicAssociations,
  journeyById,
  parseJourneyIndex,
  parseJourneyManifest
} from "./journeys.js";
import {
  canDisplaySpine,
  getRecordSpineProfile,
  loadSpineIndex
} from "./spines.js";
import {
  externalEditionLabel,
  getRecordEditionEnrichment,
  mergeEditionPhysicalProfile,
  parseEditionEnrichmentManifest,
  parseEditionEnrichmentManifestAsync
} from "./enrichment.js";
import { profileFromRecord } from "./physical.js";
import {
  loadShelfIds,
  mergeShelfIdsForCorpus,
  resolveShelfRecords,
  restoreShelfFromReceipt,
  saveShelfIds,
  toggleShelfId
} from "./shelf.js";
import { createReceipt, downloadReceipt, verifyReceipt } from "./receipt.js";
import {
  collectionCorpusOptions,
  collectionDataUrl,
  parseCollectionManifest,
  resolveCollectionCorpus,
  resolveCollectionCorpusForState
} from "./collections.js";

// Each collection owns its data paths and feature switches. Only these small,
// versioned manifests are selected by application code.
const COLLECTION_MANIFEST_URLS = Object.freeze({
  sekula: new URL("../sekula-collection.json", import.meta.url),
  jefferson: new URL("../data/collections/jefferson/manifest.json", import.meta.url)
});
const DEFAULT_COLLECTION_ID = "sekula";
const PAGE_SIZE = 72;
const SEARCH_SUGGESTION_LIMIT = 8;
const APP_VERSION = "2.0.0";
const JEFFERSON_HISTORICAL_POSITION_COUNT = 4931;
const JEFFERSON_SOURCE_BACKED_ENTRY_COUNT = 4928;
const JEFFERSON_SOURCE_NUMBERING_GAPS = Object.freeze(["2323", "4707", "4708"]);

const $ = selector => document.querySelector(selector);
const $$ = selector => [...document.querySelectorAll(selector)];

const dom = {
  loading: $("#loadingScreen"),
  retryApp: $("#retryApp"),
  pageRegions: $$(".site-header, main, .site-footer"),
  collectionSwitcher: $("#collectionSwitcher"),
  corpusSwitcher: $("#corpusSwitcher"),
  modeBanners: $("#modeBanners"),
  collectionStatusBanner: $("#collectionStatusBanner"),
  collectionStatusLabel: $("#collectionStatusLabel"),
  collectionStatusText: $("#collectionStatusText"),
  jeffersonOverview: $("#jeffersonOverview"),
  jeffersonCoverageCount: $("#jeffersonCoverageCount"),
  jeffersonHistoricalCount: $("#jeffersonHistoricalCount"),
  jeffersonPositionCount: $("#jeffersonPositionCount"),
  jeffersonVolumeCount: $("#jeffersonVolumeCount"),
  jeffersonHierarchySummary: $("#jeffersonHierarchySummary"),
  jeffersonHierarchyContent: $("#jeffersonHierarchyContent"),
  jeffersonEvidenceSummary: $("#jeffersonEvidenceSummary"),
  openReviewerMode: $("#openReviewerMode"),
  reviewerDialog: $("#reviewerDialog"),
  reviewerCode: $("#reviewerCode"),
  reviewerCodeError: $("#reviewerCodeError"),
  unlockReviewerMode: $("#unlockReviewerMode"),
  closeReviewerDialog: $("#closeReviewerDialog"),
  reviewerModeBanner: $("#reviewerModeBanner"),
  reviewerModeStatus: $("#reviewerModeStatus"),
  exitReviewerMode: $("#exitReviewerMode"),
  heroStage: $("#heroStage"),
  heroFocusIndex: $("#heroFocusIndex"),
  heroFocusTitle: $("#heroFocusTitle"),
  heroFocusMeta: $("#heroFocusMeta"),
  heroSignals: $("#heroSignals"),
  heroSearchForm: $("#heroSearchForm"),
  heroSearchInput: $("#heroSearchInput"),
  journeyFeature: $("#journeyFeature"),
  journeyReader: $("#journeyReader"),
  closeJourney: $("#closeJourney"),
  journeyProgress: $("#journeyProgress"),
  journeyEvidenceLink: $("#journeyEvidenceLink"),
  journeyTimeline: $("#journeyTimeline"),
  journeyKicker: $("#journeyKicker"),
  journeyReaderTitle: $("#journeyReaderTitle"),
  journeyDeck: $("#journeyDeck"),
  journeyFacts: $("#journeyFacts"),
  journeyHeroImage: $("#journeyHeroImage"),
  journeyMosaic: $("#journeyMosaic"),
  journeyClusters: $("#journeyClusters"),
  journeyPhaseShelves: $("#journeyPhaseShelves"),
  journeyEvidenceBody: $("#journeyEvidenceBody"),
  pathGrid: $("#pathGrid"),
  collectionCount: $("#collectionCount"),
  classCount: $("#classCount"),
  yearSpan: $("#yearSpan"),
  resultSummary: $("#resultSummary"),
  profileMethod: $("#profileMethod"),
  collectionGrid: $("#collectionGrid"),
  emptyState: $("#emptyState"),
  loadMoreWrap: $("#loadMoreWrap"),
  loadMore: $("#loadMore"),
  renderedCount: $("#renderedCount"),
  filtersPanel: $(".filters-panel"),
  toggleFilters: $("#toggleFilters"),
  activeFilters: $("#activeFilters"),
  signalFilters: $("#signalFilters"),
  lcFilter: $("#lcFilter"),
  materialFilter: $("#materialFilter"),
  decadeFilter: $("#decadeFilter"),
  evidenceFilter: $("#evidenceFilter"),
  photoFilter: $("#photoFilter"),
  groupFilter: $("#groupFilter"),
  orderFilter: $("#orderFilter"),
  collectionSearch: $("#collectionSearch"),
  resetFilters: $("#resetFilters"),
  emptyReset: $("#emptyReset"),
  openSearch: $("#openSearch"),
  searchDialog: $("#searchDialog"),
  globalSearchInput: $("#globalSearchInput"),
  searchSuggestions: $("#searchSuggestions"),
  detailDrawer: $("#detailDrawer"),
  detailContent: $("#detailDrawer .detail-content"),
  detailLoading: $("#detailLoading"),
  detailPosition: $("#detailPosition"),
  detailVisual: $("#detailVisual"),
  detailKicker: $("#detailKicker"),
  detailTitle: $("#detailTitle"),
  detailByline: $("#detailByline"),
  detailShelfButton: $("#detailShelfButton"),
  catalogLink: $("#catalogLink"),
  detailMetadata: $("#detailMetadata"),
  detailPlacement: $("#detailPlacement"),
  detailPlacementList: $("#detailPlacementList"),
  detailCoverEvidence: $("#detailCoverEvidence"),
  detailCoverEvidenceBody: $("#detailCoverEvidenceBody"),
  detailPhysical: $("#detailPhysical"),
  physicalBook: $("#physicalBook"),
  physicalMetrics: $("#physicalMetrics"),
  physicalEvidence: $("#physicalEvidence"),
  detailEdition: $("#detailEdition"),
  detailEditionLoader: $("#detailEditionLoader"),
  loadEditionEvidence: $("#loadEditionEvidence"),
  editionLoaderStatus: $("#editionLoaderStatus"),
  editionMetadata: $("#editionMetadata"),
  editionEvidenceLink: $("#editionEvidenceLink"),
  editionEvidenceNote: $("#editionEvidenceNote"),
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

function syncModeBannerHeight() {
  const height = dom.modeBanners ? Math.ceil(dom.modeBanners.getBoundingClientRect().height) : 0;
  document.documentElement.style.setProperty("--mode-banners-h", `${height}px`);
}

if (dom.modeBanners) {
  if (typeof ResizeObserver === "function") new ResizeObserver(syncModeBannerHeight).observe(dom.modeBanners);
  window.addEventListener("resize", syncModeBannerHeight, { passive: true });
  syncModeBannerHeight();
}

const initialUrl = parseUrlState();
const requestedCollectionId = Object.hasOwn(COLLECTION_MANIFEST_URLS, initialUrl.collection)
  ? initialUrl.collection
  : DEFAULT_COLLECTION_ID;
const state = {
  collectionId: requestedCollectionId,
  collectionManifest: null,
  activeCorpus: null,
  collectionManifestUrl: COLLECTION_MANIFEST_URLS[requestedCollectionId],
  assetUrls: {},
  corpus: requestedCollectionId === "jefferson" ? (initialUrl.corpus || "catalog") : "",
  order: requestedCollectionId === "jefferson" ? (initialUrl.order || "title") : "",
  hierarchy: null,
  historicalNumbering: null,
  validation: null,
  publicMedia: null,
  reviewMedia: null,
  reviewUnlocked: false,
  records: [],
  recordMap: new Map(),
  recordIds: new Set(),
  catalogSearchById: new Map(),
  catalogSearchPromise: null,
  catalogSearchAbortController: null,
  catalogSearchStatus: "idle",
  searchRequestToken: 0,
  suggestionRequestToken: 0,
  detailShardPromises: new Map(),
  detailShardsReady: new Set(),
  detailRequestToken: 0,
  filtered: [],
  paths: [],
  pathMap: new Map(),
  visuals: parseVisualManifest({}),
  covers: null,
  failedCoverIds: new Set(),
  coverProvenance: null,
  coverProvenancePromise: null,
  coverEvidenceRequestToken: 0,
  spineIndex: null,
  spineIndexPromise: null,
  spineIndexStatus: "idle",
  catalogSha256: "",
  catalogSource: null,
  editions: parseEditionEnrichmentManifest({}),
  editionLoadPromise: null,
  editionStatus: "idle",
  journeyIndex: parseJourneyIndex({}),
  journeyManifests: new Map(),
  journeyId: initialUrl.journey,
  clusterId: initialUrl.cluster,
  journeyReturnScroll: 0,
  journeyLastFocus: null,
  journeyObserver: null,
  journeyNavigationToken: 0,
  journeyNavigationLock: "",
  deferredObservers: [],
  featuredConfig: {},
  facets: null,
  filters: normalizeFilterState(initialUrl),
  view: ["covers", "spines", "list"].includes(initialUrl.view) ? initialUrl.view : "covers",
  renderLimit: PAGE_SIZE,
  selectedId: initialUrl.record,
  shelfIds: [],
  activeDrawer: null,
  lastFocus: null,
  syncingHistory: false,
  historySyncToken: 0
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

function naturalList(values) {
  if (values.length < 2) return values[0] || "";
  if (values.length === 2) return `${values[0]} and ${values[1]}`;
  return `${values.slice(0, -1).join(", ")}, and ${values[values.length - 1]}`;
}

function featureEnabled(name) {
  return (state.activeCorpus?.features || state.collectionManifest?.features)?.[name] === true;
}

function activeFacetIds() {
  return state.activeCorpus?.facets || state.collectionManifest?.facets || [];
}

function normalizeFiltersForActiveCorpus(rawState = {}) {
  const facets = activeFacetIds();
  return normalizeFilterState({
    ...rawState,
    signals: facets.includes("signals") ? rawState.signals : [],
    signalMode: facets.includes("signals") ? rawState.signalMode : "any",
    lc: facets.includes("classes") ? rawState.lc : "",
    material: facets.includes("materials") ? rawState.material : "",
    decade: facets.includes("decades") ? rawState.decade : "",
    evidence: facets.includes("evidence_status") ? rawState.evidence : "",
    photo: featureEnabled("photo_likelihood") ? rawState.photo : "",
    placement: featureEnabled("placement") ? rawState.placement : "",
    path: featureEnabled("curated_paths") ? rawState.path : "",
    group: featureEnabled("physical") ? rawState.group : "lc"
  });
}

function activeEntityType() {
  return state.activeCorpus?.coverage?.entity_type || state.collectionManifest?.coverage?.entity_type || "bibliographic_record";
}

function activeCoverage() {
  return state.activeCorpus?.coverage || state.collectionManifest?.coverage || {};
}

function historicalCoverageCounts() {
  const coverage = activeCoverage();
  const explicitPositions = Number(coverage.historical_position_count);
  const legacyPositions = Number(coverage.historical_entry_count) === JEFFERSON_HISTORICAL_POSITION_COUNT;
  return {
    entries: explicitPositions > 0
      ? Number(coverage.historical_entry_count)
      : (legacyPositions ? JEFFERSON_SOURCE_BACKED_ENTRY_COUNT : Number(coverage.historical_entry_count || 0)),
    positions: explicitPositions > 0
      ? explicitPositions
      : (legacyPositions ? JEFFERSON_HISTORICAL_POSITION_COUNT : Number(coverage.historical_entry_count || 0)),
    gaps: state.historicalNumbering?.gaps?.map(gap => gap.identifier) || [...JEFFERSON_SOURCE_NUMBERING_GAPS]
  };
}

function activeCorpusCopy() {
  const copy = state.activeCorpus?.copy || state.collectionManifest?.copy || {};
  const coverage = state.activeCorpus?.coverage || state.collectionManifest?.coverage || {};
  if (state.collectionId === "jefferson" && !coverage.historical_position_count
    && Number(coverage.historical_entry_count) === JEFFERSON_HISTORICAL_POSITION_COUNT) {
    return {
      ...copy,
      coverage_statement: String(copy.coverage_statement || "")
        .replace("the complete 4,931-entry Sowerby corpus", "the 4,931-position Sowerby spine (4,928 source-backed entries plus 3 non-book gaps)")
    };
  }
  return copy;
}

function activeUnitLabel({ singular = false } = {}) {
  const entityType = activeEntityType();
  if (entityType === "sowerby_entry") return singular ? "Sowerby entry" : "Sowerby entries";
  if (entityType === "catalog_instance") return singular ? "catalog instance" : "catalog instances";
  return singular ? "catalog record" : "catalog records";
}

function collectionShelfKey() {
  return state.collectionManifest?.shelf?.storage_key || "shelfsignals_shelf";
}

function manifestAssetUrl(name) {
  const corpusData = state.activeCorpus?.data || state.collectionManifest?.data || {};
  const multiCorpus = Array.isArray(state.collectionManifest?.corpora);
  const path = multiCorpus && name !== "hierarchy" ? corpusData[name] : state.collectionManifest?.data?.[name];
  if (!path || !state.collectionManifestUrl) return null;
  const cacheKey = `${state.corpus || "catalog"}:${name}`;
  if (state.assetUrls[cacheKey]) return state.assetUrls[cacheKey];
  const url = collectionDataUrl(state.collectionManifest, name, state.collectionManifestUrl, { corpus: state.corpus });
  state.assetUrls[cacheKey] = url;
  return url;
}

function catalogDetailUrl(shard) {
  if (!state.activeCorpus?.data?.detail_template && !state.collectionManifest?.data?.detail_template) return null;
  return collectionDataUrl(state.collectionManifest, "detail_template", state.collectionManifestUrl, { shard, corpus: state.corpus });
}

function orderedRecords(records = []) {
  const order = state.order;
  if (!order || order === "catalog") return [...records];
  return [...records].sort((left, right) => {
    const leftOrder = left.orders?.[order];
    const rightOrder = right.orders?.[order];
    if (leftOrder != null || rightOrder != null) {
      if (leftOrder == null) return 1;
      if (rightOrder == null) return -1;
      const comparison = String(leftOrder).localeCompare(String(rightOrder), undefined, { numeric: true, sensitivity: "base" });
      if (comparison) return comparison;
    }
    if (order === "lc") {
      const comparison = String(left.call_number || "").localeCompare(String(right.call_number || ""), undefined, { numeric: true, sensitivity: "base" });
      if (comparison) return comparison;
    }
    return String(left.title || "").localeCompare(String(right.title || ""), undefined, { numeric: true, sensitivity: "base" })
      || String(left.id || "").localeCompare(String(right.id || ""));
  });
}

function decodeMediaManifest(raw, expectedAudience) {
  const expectedFields = [
    "record_id", "digital_item_id", "url", "thumbnail_url", "rights_access",
    "review_status", "match_basis", "normalized_lccns", "sowerby_numbers"
  ];
  const expectedKeys = ["schema", "generated_at", "collection_id", "audience", "security_notice", "source", "fields", "items"];
  const exactKeys = value => value && typeof value === "object" && !Array.isArray(value)
    && Object.keys(value).sort().join("\u241f") === [...expectedKeys].sort().join("\u241f");
  const exactFields = Array.isArray(raw?.fields)
    && raw.fields.length === expectedFields.length
    && raw.fields.every((field, index) => field === expectedFields[index]);
  const sameSource = state.catalogSource && raw?.source && Object.keys(state.catalogSource).every(key => raw.source[key] === state.catalogSource[key])
    && Object.keys(raw.source).length === Object.keys(state.catalogSource).length;
  if (!exactKeys(raw) || raw.schema !== "shelfsignals-media-manifest@1" || raw.collection_id !== state.collectionId
    || raw.audience !== expectedAudience || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/.test(raw.generated_at)
    || !String(raw.security_notice || "").trim() || !sameSource || !exactFields || !Array.isArray(raw.items)) {
    return { rejected: true, items: [] };
  }
  const allowedStatus = expectedAudience === "public" ? "public_rights_reviewed" : "rights_review_required";
  const seen = new Set();
  const items = [];
  for (const row of raw.items) {
    if (!Array.isArray(row) || row.length !== expectedFields.length) return { rejected: true, items: [] };
    const item = Object.fromEntries(expectedFields.map((field, index) => [field, row[index]]));
    const validUrl = (value, hosts, optional = false) => {
      if (!value && optional) return true;
      try {
        const url = new URL(value);
        return url.protocol === "https:" && !url.username && !url.password && hosts.has(url.hostname);
      } catch (_) { return false; }
    };
    if (!state.recordIds.has(item.record_id) || seen.has(item.record_id) || !/^loc:digital:[A-Za-z0-9._:-]+$/.test(item.digital_item_id)
      || !validUrl(item.url, new Set(["www.loc.gov", "loc.gov"]))
      || !validUrl(item.thumbnail_url, new Set(["tile.loc.gov"]), true)
      || !Array.isArray(item.rights_access) || item.rights_access.some(value => !String(value).trim())
      || item.review_status !== allowedStatus || item.match_basis !== "normalized LCCN exact"
      || !Array.isArray(item.normalized_lccns) || !item.normalized_lccns.length || item.normalized_lccns.some(value => !String(value).trim())
      || !Array.isArray(item.sowerby_numbers) || item.sowerby_numbers.some(value => !Number.isInteger(value) || value <= 0)) {
      return { rejected: true, items: [] };
    }
    seen.add(item.record_id);
    items.push(item);
  }
  return { ...raw, rejected: false, items };
}

function setCollectionSpecificCopy() {
  const manifest = state.collectionManifest;
  const isJefferson = state.collectionId === "jefferson";
  const corpus = state.activeCorpus;
  const corpusCopy = activeCorpusCopy();
  const facets = activeFacetIds();
  const name = manifest.copy.name;
  document.title = `ShelfSignals — ${name}`;
  const description = document.querySelector('meta[name="description"]');
  if (description) description.content = `${corpusCopy.introduction} ${corpusCopy.coverage_statement}`;
  const loadingCopy = dom.loading?.querySelector("p");
  if (loadingCopy) loadingCopy.textContent = `Opening ${name}`;
  dom.collectionSwitcher.value = state.collectionId;

  const eyebrow = $(".hero .eyebrow");
  if (eyebrow) {
    eyebrow.replaceChildren(textElement("span", "", `ShelfSignals ${APP_VERSION}`), document.createTextNode(` · ${manifest.copy.institution}`));
  }
  const heroTitle = $("#heroTitle");
  if (heroTitle) {
    const emphasis = document.createElement("em");
    emphasis.textContent = name;
    heroTitle.replaceChildren(document.createTextNode("Explore the"), document.createElement("br"), emphasis);
  }
  const heroIntro = $(".hero-intro");
  if (heroIntro) heroIntro.textContent = corpusCopy.introduction;
  const heroSearchLabel = document.querySelector('label[for="heroSearchInput"]');
  if (heroSearchLabel) heroSearchLabel.textContent = `Search ${name}`;
  if (dom.heroSearchInput) dom.heroSearchInput.placeholder = `Search ${manifest.copy.short_name}…`;
  const introductionCopy = $(".introduction-copy > p");
  if (introductionCopy) introductionCopy.textContent = corpusCopy.coverage_statement;
  const collectionUnit = dom.collectionCount?.nextElementSibling;
  if (collectionUnit) collectionUnit.textContent = activeUnitLabel();
  const collectionHeading = $("#collectionTitle");
  if (collectionHeading) collectionHeading.textContent = activeEntityType() === "sowerby_entry" ? "Browse historical entries" : (isJefferson ? "Browse catalog instances" : "Browse the shelves");
  const collectionKicker = $(".collection-header .section-index");
  if (collectionKicker && isJefferson) collectionKicker.textContent = activeEntityType() === "sowerby_entry" ? "04 / Historical corpus beta" : "04 / Catalog corpus beta";
  const overviewKicker = $(".collection-overview-header .section-index");
  if (overviewKicker && isJefferson) overviewKicker.textContent = activeEntityType() === "sowerby_entry" ? "Jefferson historical beta" : "Jefferson catalog beta";
  const catalogAction = dom.catalogLink;
  if (catalogAction) catalogAction.textContent = `View in ${corpusCopy.source_label} ↗`;
  const aboutCopy = $(".about-section > div:last-child > p:first-child");
  if (aboutCopy) aboutCopy.textContent = `ShelfSignals presents ${name} through ${corpusCopy.source_label}. ${corpusCopy.coverage_statement}`;
  const footerScope = $(".site-footer span:nth-child(2)");
  if (footerScope) footerScope.textContent = isJefferson
    ? "Catalog instances, historical entries, physical copies, holdings, and digital objects remain distinct."
    : "Clark catalog facts and external provider-edition evidence are kept visibly distinct.";

  dom.collectionStatusBanner.hidden = !isJefferson;
  dom.collectionStatusLabel.textContent = corpusCopy.status_label;
  dom.collectionStatusText.textContent = corpusCopy.coverage_statement;
  syncModeBannerHeight();
  dom.jeffersonOverview.hidden = !isJefferson;
  if (isJefferson) {
    const historical = activeEntityType() === "sowerby_entry";
    const overviewTitle = $("#jeffersonOverviewTitle");
    const overviewSummary = $("#jeffersonOverviewSummary");
    const coverageSummary = $("#jeffersonCoverageSummary");
    if (overviewTitle) {
      const emphasis = document.createElement("em");
      emphasis.textContent = historical ? "linked with care." : "with historical limits.";
      overviewTitle.replaceChildren(
        document.createTextNode(historical ? "Historical entries," : "A catalog view"),
        document.createElement("br"),
        emphasis
      );
    }
    if (overviewSummary) overviewSummary.textContent = historical
      ? "Historical Sowerby entries remain distinct from modern catalog instances, editions, physical copies, holdings, and digital objects."
      : "This beta keeps modern Library of Congress catalog records, Sowerby’s reconstructed historical order, physical copies, holdings, and digital objects distinct.";
    if (coverageSummary) coverageSummary.textContent = historical
      ? "This corpus represents source-backed Sowerby entries; linked modern records and custodial objects remain separate evidence entities."
      : "The current view is a modern catalog extraction, not a complete reconstruction of Jefferson’s 1815 library.";
  }
  dom.openReviewerMode.hidden = !manifest.review?.enabled || !corpus?.data?.review_media;
  $("#journeys").hidden = !featureEnabled("journeys");
  $("#paths").hidden = !featureEnabled("curated_paths");
  $("#signals").hidden = !facets.includes("signals");
  dom.heroSignals.hidden = !facets.includes("signals");
  dom.lcFilter.closest("fieldset").hidden = !facets.includes("classes");
  dom.materialFilter.closest("fieldset").hidden = !facets.includes("materials");
  dom.decadeFilter.closest("fieldset").hidden = !facets.includes("decades");
  dom.photoFilter.closest("fieldset").hidden = !featureEnabled("photo_likelihood");
  dom.evidenceFilter.closest("fieldset").hidden = !facets.includes("evidence_status");
  dom.groupFilter.closest("fieldset").hidden = !featureEnabled("physical");
  const spineButton = $('.view-button[data-view="spines"]');
  if (spineButton) spineButton.hidden = !featureEnabled("physical");
  dom.detailPlacement.hidden = !featureEnabled("placement");
  dom.detailPhysical.hidden = !featureEnabled("physical");
  dom.detailEditionLoader.hidden = !featureEnabled("provider_editions");
  dom.detailEdition.hidden = !featureEnabled("provider_editions");
  const coverHeading = dom.detailCoverEvidence?.querySelector("h3");
  if (coverHeading && isJefferson) coverHeading.textContent = "Digital-surrogate evidence";
  const notesHeading = dom.detailNotes?.querySelector("h3");
  if (notesHeading && isJefferson) notesHeading.textContent = "Evidence ledger";
  dom.detailCoverEvidence.hidden = isJefferson ? !featureEnabled("digital_surrogates") : false;
  $$('.primary-nav a[href="#journeys"]').forEach(link => { link.hidden = !featureEnabled("journeys"); });
  $$('.primary-nav a[href="#signals"]').forEach(link => { link.hidden = !facets.includes("signals"); });
  $$('.primary-nav a[href="#paths"]').forEach(link => { link.hidden = !featureEnabled("curated_paths"); });
  if (isJefferson) {
    const resources = $(".about-section > div:last-child > p:last-child");
    if (resources) {
      const project = document.createElement("a");
      project.href = "https://github.com/gitbrainlab/ShelfSignals";
      project.rel = "noopener noreferrer";
      project.textContent = "Project source";
      const guide = document.createElement("a");
      guide.href = "./interfaces.md";
      guide.textContent = "Interface guide";
      resources.replaceChildren(project, document.createTextNode(" · "), guide);
    }
  }

  if (dom.corpusSwitcher) {
    clear(dom.corpusSwitcher);
    const corpusOptions = collectionCorpusOptions(manifest);
    corpusOptions.forEach(option => addOption(dom.corpusSwitcher, option.id, option.label));
    dom.corpusSwitcher.value = state.corpus;
    dom.corpusSwitcher.closest("label").hidden = !isJefferson;
    dom.corpusSwitcher.disabled = corpusOptions.length < 2;
    dom.corpusSwitcher.setAttribute("aria-description", corpusOptions.length < 2 ? "Only one corpus is currently available" : "Changing corpus reloads the collection");
  }
  if (dom.orderFilter) {
    clear(dom.orderFilter);
    (corpus?.orders || manifest.orders).forEach(option => addOption(dom.orderFilter, option.id, option.label));
    dom.orderFilter.value = state.order;
    dom.orderFilter.closest("label").hidden = (corpus?.orders || manifest.orders).length < 2;
  }
}

function updateJeffersonOverview() {
  if (state.collectionId !== "jefferson") return;
  const coverage = activeCoverage();
  const historicalCounts = historicalCoverageCounts();
  dom.jeffersonCoverageCount.textContent = formatNumber(coverage.record_count);
  const coverageUnit = dom.jeffersonCoverageCount?.nextElementSibling;
  if (coverageUnit) coverageUnit.textContent = activeUnitLabel();
  dom.jeffersonHistoricalCount.textContent = formatNumber(historicalCounts.entries);
  dom.jeffersonPositionCount.textContent = formatNumber(historicalCounts.positions);
  dom.jeffersonVolumeCount.textContent = formatNumber(coverage.historical_volume_count);
  const chapters = state.hierarchy?.chapters?.length || 44;
  const faculties = state.hierarchy?.faculties?.map(item => item.name).filter(Boolean) || ["History", "Philosophy", "Fine Arts"];
  dom.jeffersonHierarchySummary.textContent = activeEntityType() === "sowerby_entry"
    ? `${chapters} Sowerby chapters across ${naturalList(faculties)} organize this historical intellectual-order view. It does not reconstruct physical shelving or adjacency.`
    : `${chapters} Sowerby chapters across ${naturalList(faculties)} are available only as a coverage preview. This view does not reconstruct physical shelving or adjacency.`;
  clear(dom.jeffersonHierarchyContent);
  if (state.hierarchy?.chapters?.length) {
    faculties.forEach((faculty, index) => {
      const facultyChapters = state.hierarchy.chapters.filter(chapter => chapter.faculty === faculty);
      const details = document.createElement("details");
      if (index === 0) details.open = true;
      details.append(textElement("summary", "", `${faculty} · ${facultyChapters.length} chapters`));
      const list = document.createElement("ol");
      facultyChapters.forEach(chapter => {
        const item = document.createElement("li");
        item.append(textElement("span", "", chapter.chapter_roman), document.createTextNode(chapter.heading));
        list.append(item);
      });
      details.append(list);
      dom.jeffersonHierarchyContent.append(details);
    });
  } else {
    faculties.forEach(faculty => dom.jeffersonHierarchyContent.append(textElement("span", "", faculty)));
  }
  const validationCounts = state.validation?.counts || {};
  const mediaSummary = Number.isInteger(validationCounts.public_media_items) && Number.isInteger(validationCounts.review_media_items)
    ? ` Public mode includes ${formatNumber(validationCounts.public_media_items)} approved media; ${formatNumber(validationCounts.review_media_items)} exact-linked preview remains rights-pending in reviewer mode.`
    : "";
  const titleSummary = Number.isInteger(validationCounts.source_backed_titles) && Number.isInteger(validationCounts.titles_not_established)
    ? ` ${formatNumber(validationCounts.source_backed_titles)} short titles passed the conservative LOC scan-OCR publication rules; ${formatNumber(validationCounts.titles_not_established)} remain explicitly not established pending bibliographic review.`
    : "";
  const identifierSummary = Number.isInteger(validationCounts.page_resolved_identifiers) && Number.isInteger(validationCounts.aggregate_spine_identifiers)
    ? ` ${formatNumber(validationCounts.page_resolved_identifiers)} identifiers are tied to an exact LOC PDF page; ${formatNumber(validationCounts.aggregate_spine_identifiers)} retain aggregate scan-spine support without an exact page assignment.`
    : "";
  dom.jeffersonEvidenceSummary.textContent = activeEntityType() === "sowerby_entry"
    ? `The ${historicalCounts.positions.toLocaleString()} ordered positions contain ${historicalCounts.entries.toLocaleString()} source-backed entries and ${historicalCounts.gaps.length} explicit non-book numbering gaps (${historicalCounts.gaps.join(", ")}). Every published assertion retains source and as-of evidence; linked entities remain typed and unresolved links stay explicit.${identifierSummary}${titleSummary}${mediaSummary}`
    : `The historical spine has ${historicalCounts.positions.toLocaleString()} positions: ${historicalCounts.entries.toLocaleString()} source-backed entries plus explicit non-book gaps ${historicalCounts.gaps.join(", ")}. Only ${formatNumber(coverage.established_sowerby_links)} catalog–Sowerby links are established by the bounded MARC assessment. Ownership and reconstruction status are not established unless directly sourced.${mediaSummary}`;
}

function changeCollection(nextCollectionId) {
  const next = Object.hasOwn(COLLECTION_MANIFEST_URLS, nextCollectionId) ? nextCollectionId : DEFAULT_COLLECTION_ID;
  const url = new URL(location.href);
  ["record", "q", "signals", "signalMode", "lc", "material", "decade", "evidence", "photo", "placement", "group", "path", "journey", "cluster", "view", "corpus", "order"].forEach(key => url.searchParams.delete(key));
  if (next === DEFAULT_COLLECTION_ID) url.searchParams.delete("collection");
  else url.searchParams.set("collection", next);
  url.hash = "";
  location.assign(`${url.pathname}${url.search}`);
}

function changeCorpus(nextCorpusId) {
  const next = resolveCollectionCorpus(state.collectionManifest, nextCorpusId);
  if (!next || next.id === state.corpus) return;
  const url = new URL(location.href);
  ["record", "q", "signals", "signalMode", "lc", "material", "decade", "evidence", "photo", "placement", "group", "path", "journey", "cluster", "view", "order"].forEach(key => url.searchParams.delete(key));
  url.searchParams.set("corpus", next.id);
  url.searchParams.set("order", next.default_order);
  url.hash = "";
  location.assign(`${url.pathname}${url.search}`);
}

async function sha256Text(value) {
  const bytes = new TextEncoder().encode(String(value));
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)].map(byte => byte.toString(16).padStart(2, "0")).join("");
}

async function loadReviewMedia() {
  if (!state.reviewUnlocked || state.reviewMedia) return state.reviewMedia;
  const url = manifestAssetUrl("review_media");
  if (!url) return null;
  const parsed = decodeMediaManifest(await fetchJson(url, null), "review");
  if (parsed.rejected) throw new Error("The review-media manifest failed collection or audience validation.");
  state.reviewMedia = parsed;
  return parsed;
}

async function setReviewerMode(unlocked) {
  const review = state.collectionManifest?.review;
  if (!review?.enabled) return;
  if (unlocked && !state.activeCorpus?.data?.review_media) {
    state.reviewUnlocked = false;
    state.reviewMedia = null;
    try { sessionStorage.removeItem(review.session_key); } catch (_) { /* Session storage may be unavailable. */ }
    dom.reviewerModeBanner.hidden = true;
    return;
  }
  state.reviewUnlocked = Boolean(unlocked);
  if (unlocked) {
    try { sessionStorage.setItem(review.session_key, "unlocked"); } catch (_) { /* Review remains tab-local in memory. */ }
    await loadReviewMedia();
  } else {
    try { sessionStorage.removeItem(review.session_key); } catch (_) { /* Session storage may be unavailable. */ }
    state.reviewMedia = null;
  }
  dom.reviewerModeBanner.hidden = !state.reviewUnlocked;
  syncModeBannerHeight();
  dom.reviewerModeStatus.textContent = review.warning;
  dom.openReviewerMode.textContent = state.reviewUnlocked ? "Reviewer mode active" : "Reviewer mode";
  const selected = state.recordMap.get(state.selectedId);
  if (selected && state.collectionId === "jefferson") void renderCoverEvidence(selected);
}

async function submitReviewerCode(event) {
  event.preventDefault();
  if (!state.collectionManifest?.review?.enabled) return;
  dom.reviewerCodeError.textContent = "The reviewer code was not accepted.";
  dom.reviewerCodeError.hidden = true;
  const supplied = await sha256Text(dom.reviewerCode.value);
  const expected = state.collectionManifest.review.code_sha256.replace(/^sha256:/i, "").toLocaleLowerCase();
  if (supplied !== expected) {
    dom.reviewerCodeError.hidden = false;
    dom.reviewerCode.select();
    return;
  }
  try {
    await setReviewerMode(true);
    dom.reviewerCode.value = "";
    dom.reviewerDialog.close();
    showToast("Review mode enabled for this tab");
  } catch (error) {
    state.reviewUnlocked = false;
    state.reviewMedia = null;
    try { sessionStorage.removeItem(state.collectionManifest.review.session_key); } catch (_) { /* Session storage may be unavailable. */ }
    dom.reviewerModeBanner.hidden = true;
    dom.reviewerCodeError.textContent = `Review media could not be loaded: ${error.message}`;
    dom.reviewerCodeError.hidden = false;
  }
}

function authorLabel(record) {
  return record.authors.length
    ? record.authors.join(", ")
    : (state.collectionId === "jefferson" ? "Creator not established" : "Creator not recorded");
}

function compactMeta(record) {
  if (state.collectionId === "jefferson") {
    return [record.authors[0] || "Creator not established", record.yearPrimary || record.year || "Date not established"].join(" · ");
  }
  return [record.authors[0], record.yearPrimary, record.call_number].filter(Boolean).join(" · ");
}

function coverLabel(cover = {}) {
  if (state?.collectionId === "jefferson") return featureEnabled("digital_surrogates")
    ? "Metadata-derived form · digital-object status is evidence-scoped"
    : "Metadata-derived form · no digital object relation established";
  if (cover.status === "verified") return REVIEWED_COVER_LABEL;
  if (cover.status === "provider_reference") return PROVIDER_REFERENCE_LABEL;
  return UNRESOLVED_COVER_LABEL;
}

function setApplicationBusy(busy) {
  document.body.dataset.appState = busy ? "loading" : "ready";
  dom.loading?.setAttribute("aria-busy", busy ? "true" : "false");
  dom.pageRegions.forEach(region => {
    region.inert = busy || Boolean(state.activeDrawer);
    if (busy) region.setAttribute("aria-busy", "true");
    else region.removeAttribute("aria-busy");
  });
}

function compactCoverEvidence(cover = {}) {
  if (state.collectionId === "jefferson") return featureEnabled("digital_surrogates")
    ? "Metadata-derived form · open the record for digital-object evidence"
    : "Metadata-derived form · no digital object relation established";
  if (!canDisplayCover(cover)) return UNRESOLVED_COVER_LABEL;
  const provider = cover.provider === "openlibrary" ? "Open Library" : titleCase(cover.provider || "provider");
  const review = cover.status === "verified" ? "human reviewed" : "visual review pending";
  return `${provider} · exact-edition reference · ${review} · remote only; artwork rights not established`;
}

function editionForRecord(record) {
  return getRecordEditionEnrichment(record, state.editions);
}

function physicalRecord(record) {
  if (!record.physicalProfile) record.physicalProfile = mergeEditionPhysicalProfile(record, editionForRecord(record));
  return record;
}

function validatedSpineProfile(record) {
  const profile = getRecordSpineProfile(record, state.spineIndex || {});
  return canDisplaySpine(profile) ? profile : null;
}

function spineRenderRecord(record) {
  const profile = validatedSpineProfile(record);
  return {
    ...record,
    physicalProfile: profile || {}
  };
}

function yieldToBrowser() {
  return new Promise(resolve => {
    if ("requestIdleCallback" in window) window.requestIdleCallback(resolve, { timeout: 60 });
    else setTimeout(resolve, 0);
  });
}

function runWhenNear(element, task, { rootMargin = "240px 0px" } = {}) {
  if (!element) return () => {};
  let started = false;
  const run = () => {
    if (started) return;
    started = true;
    element.setAttribute("aria-busy", "true");
    Promise.resolve(task())
      .catch(error => console.warn("ShelfSignals deferred section could not be prepared:", error))
      .finally(() => element.removeAttribute("aria-busy"));
  };
  if (!("IntersectionObserver" in window)) {
    if ("requestIdleCallback" in window) window.requestIdleCallback(run, { timeout: 1800 });
    else setTimeout(run, 0);
    return run;
  }
  const observer = new IntersectionObserver(entries => {
    if (!entries.some(entry => entry.isIntersecting)) return;
    observer.disconnect();
    run();
  }, { rootMargin, threshold: 0 });
  observer.observe(element);
  state.deferredObservers.push(observer);
  return run;
}

function scheduleSecondarySections() {
  if (featureEnabled("journeys")) {
    if (state.journeyId) void renderJourneyFeature();
    else runWhenNear(dom.journeyFeature, renderJourneyFeature);
  }
  if (featureEnabled("curated_paths")) runWhenNear(dom.pathGrid, renderPaths);
}

function restoreScrollImmediately(top) {
  const root = document.documentElement;
  const previous = root.style.scrollBehavior;
  root.style.scrollBehavior = "auto";
  window.scrollTo(0, top);
  if (previous) root.style.scrollBehavior = previous;
  else root.style.removeProperty("scroll-behavior");
}

async function enrichInBatches(rawRecords) {
  const enriched = [];
  const progress = dom.loading?.querySelector("p");
  for (let index = 0; index < rawRecords.length; index += 300) {
    const slice = rawRecords.slice(index, index + 300);
    for (const record of slice) {
      const projected = record.detail_hydrated === false;
      const placements = projected && Array.isArray(record.placements) ? record.placements : [];
      const signals = projected && Array.isArray(record.signals) ? record.signals : [];
      const item = enrichRecord(record);
      if (projected) {
        item.placements = placements;
        item.signals = signals;
        item.searchText = [item.id, item.title, ...item.authors, item.year, item.call_number, item.material_type, ...placements.map(placement => placement.label)]
          .filter(Boolean)
          .join(" \u241f ")
          .toLocaleLowerCase();
      }
      enriched.push(item);
    }
    if (progress && index % 1200 === 0) progress.textContent = `Reading catalog metadata · ${formatNumber(Math.min(index + slice.length, rawRecords.length))}`;
    await yieldToBrowser();
  }
  return enriched;
}

async function fetchJson(url, fallback, options = {}) {
  try {
    const response = await fetch(url, options);
    if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
    return await response.json();
  } catch (error) {
    if (error?.name === "AbortError") throw error;
    console.warn(`ShelfSignals could not load ${url}:`, error);
    return fallback;
  }
}

async function ensureCatalogSearchIndex() {
  if (state.catalogSearchStatus === "ready") return state.catalogSearchById;
  if (state.catalogSearchStatus === "failed") return null;
  if (state.catalogSearchPromise) return state.catalogSearchPromise;
  const controller = new AbortController();
  state.catalogSearchAbortController = controller;
  state.catalogSearchStatus = "loading";
  const attempt = (async () => {
    try {
      const searchUrl = manifestAssetUrl("search");
      if (!searchUrl) throw new Error("the collection manifest does not declare a search projection");
      const raw = await fetchJson(searchUrl, null, { signal: controller.signal });
      if (!raw) throw new Error("the full-field search projection is unavailable");
      const parsed = parseCatalogSearchIndex(raw, {
        datasetSha256: state.catalogSha256,
        catalogIds: state.recordIds,
        collectionId: state.collectionId,
        corpusId: state.activeCorpus?.id || "",
        recordIdPrefix: state.activeCorpus?.record_id_prefix || "",
        catalogSource: state.catalogSource
      });
      if (parsed.rejected) throw new Error(parsed.errors.map(error => `${error.path}: ${error.message}`).join(", "));
      state.catalogSearchById = parsed.searchById;
      state.records.forEach(record => {
        const searchText = parsed.searchById.get(record.id);
        if (searchText) record.searchText = searchText;
      });
      state.catalogSearchStatus = "ready";
      return parsed.searchById;
    } catch (error) {
      if (error?.name === "AbortError") {
        if (state.catalogSearchAbortController === controller) state.catalogSearchStatus = "idle";
        return null;
      }
      state.catalogSearchStatus = "failed";
      console.warn("ShelfSignals could not apply the collection search projection:", error);
      return null;
    }
  })();
  state.catalogSearchPromise = attempt;
  void attempt.finally(() => {
    if (state.catalogSearchPromise === attempt) state.catalogSearchPromise = null;
    if (state.catalogSearchAbortController === controller) state.catalogSearchAbortController = null;
  });
  return attempt;
}

function cancelCatalogSearch() {
  if (state.catalogSearchStatus === "loading") state.catalogSearchAbortController?.abort();
}

function reenrichHydratedRecord(record) {
  const detailShard = record.detail_shard;
  const fullSearchText = state.catalogSearchById.get(record.id);
  const contributorAssertions = Array.isArray(record.contributors) ? record.contributors : [];
  delete record.physicalProfile;
  const enriched = enrichRecord(record);
  Object.assign(record, enriched, { detail_shard: detailShard, detail_hydrated: true });
  if (state.collectionId === "jefferson") {
    record.other_contributors = contributorAssertions
      .filter(contributor => contributor && typeof contributor === "object" && contributor.primary === false && contributor.name)
      .map(contributor => String(contributor.name));
  }
  if (fullSearchText) record.searchText = fullSearchText;
  return record;
}

async function ensureCatalogDetailShard(shard) {
  if (state.detailShardsReady.has(shard)) return true;
  if (state.detailShardPromises.has(shard)) return state.detailShardPromises.get(shard);
  const url = catalogDetailUrl(shard);
  if (!url) return false;
  const attempt = (async () => {
    try {
      const raw = await fetchJson(url, null);
      if (!raw) throw new Error("the detail projection is unavailable");
      const parsed = parseCatalogDetailShard(raw, {
        datasetSha256: state.catalogSha256,
        catalogIds: state.recordIds,
        expectedShard: shard,
        collectionId: state.collectionId,
        corpusId: state.activeCorpus?.id || "",
        entityType: activeEntityType(),
        recordIdPrefix: state.activeCorpus?.record_id_prefix || "",
        catalogSource: state.catalogSource
      });
      if (parsed.rejected) throw new Error(parsed.errors.map(error => `${error.path}: ${error.message}`).join(", "));
      parsed.detailsById.forEach((details, id) => {
        const record = state.recordMap.get(id);
        if (record) reenrichHydratedRecord(hydrateCatalogRecord(record, details));
      });
      state.detailShardsReady.add(shard);
      return true;
    } catch (error) {
      console.warn(`ShelfSignals could not apply ${url}:`, error);
      return false;
    }
  })();
  state.detailShardPromises.set(shard, attempt);
  void attempt.finally(() => {
    if (state.detailShardPromises.get(shard) === attempt) state.detailShardPromises.delete(shard);
  });
  return attempt;
}

function setStyles(element, properties) {
  for (const [property, value] of Object.entries(properties)) element.style.setProperty(property, value);
}

function coverStateForRecord(record) {
  const cover = getRecordCoverState(record, state.covers || {});
  if (!state.failedCoverIds.has(record.id)) return cover;
  return {
    ...cover,
    status: "unresolved",
    image: null,
    label: UNRESOLVED_COVER_LABEL
  };
}

function recordVisual(record) {
  const cover = coverStateForRecord(record);
  if (!canDisplayCover(cover)) return null;
  return {
    image_url: cover.image.image_url,
    thumbnail_url: cover.image.thumbnail_url,
    width: cover.image.width,
    height: cover.image.height,
    aspect_ratio: cover.image.width / cover.image.height
  };
}

function responsiveImage(image, alt = "", { eager = false, sizes = "(max-width: 900px) 100vw, 66vw" } = {}) {
  const img = document.createElement("img");
  img.alt = alt;
  img.loading = eager ? "eager" : "lazy";
  img.decoding = "async";
  img.fetchPriority = eager ? "high" : "low";
  img.src = image.thumbnail_url || image.image_url;
  if (image.thumbnail_url && image.image_url && image.thumbnail_url !== image.image_url) {
    img.srcset = `${image.thumbnail_url} 960w, ${image.image_url} 1920w`;
    img.sizes = sizes;
  }
  if (image.width) img.width = image.width;
  if (image.height) img.height = image.height;
  return img;
}

function appendCoverImage(container, record, visual, eager = false) {
  if (!visual) return;
  const image = document.createElement("img");
  image.className = "cover-image";
  image.alt = "";
  image.loading = eager ? "eager" : "lazy";
  image.decoding = "async";
  image.fetchPriority = eager ? "high" : "low";
  image.referrerPolicy = "no-referrer";
  image.draggable = false;
  if (visual.width) image.width = visual.width;
  if (visual.height) image.height = visual.height;
  image.addEventListener("load", async () => {
    try { await image.decode(); } catch (_) { /* Loaded images are still safe to reveal. */ }
    requestAnimationFrame(() => container.classList.add("cover-ready"));
  }, { once: true });
  image.addEventListener("error", () => {
    state.failedCoverIds.add(record.id);
    image.remove();
    container.classList.remove("has-cover");
    container.classList.remove("cover-ready");
    container.style.removeProperty("--cover-image");
    container.dataset.coverStatus = "unresolved";
    const stateLabel = container.querySelector(".cover-state-label");
    if (stateLabel) stateLabel.textContent = UNRESOLVED_COVER_LABEL;
    const updateCardEvidence = () => {
      const cardEvidence = container.closest(".book-open")?.querySelector(".book-card-cover-scope");
      if (cardEvidence) cardEvidence.textContent = UNRESOLVED_COVER_LABEL;
      if (container.matches(".hero-book.is-focused")) {
        dom.heroFocusMeta.textContent = [compactMeta(record), UNRESOLVED_COVER_LABEL].filter(Boolean).join(" · ");
      }
    };
    updateCardEvidence();
    // A cached/blocked image can fail while its book object is still being
    // assembled off-DOM. Reconcile the sibling evidence line once attached.
    requestAnimationFrame(updateCardEvidence);
    if (state.selectedId === record.id) void renderCoverEvidence(record);
  }, { once: true });
  image.src = visual.thumbnail_url || visual.image_url;
  container.prepend(image);
}

function makeBookObject(record, { eager = false } = {}) {
  const cover = coverStateForRecord(record);
  const visual = recordVisual(record);
  const object = document.createElement("div");
  object.className = "book-object";
  object.dataset.coverStatus = cover.status;
  applyBookStyle(object, physicalRecord(record), visual);
  appendCoverImage(object, record, visual, eager);

  object.append(
    textElement("span", "book-cover-class", [record.material_type, record.call_number].filter(Boolean).join(" · ")),
    textElement("strong", "book-cover-title", record.displayTitle),
    (() => {
      const meta = document.createElement("span");
      meta.className = "book-cover-meta";
      meta.append(textElement("span", "", authorLabel(record)));
      meta.append(textElement("span", "", record.yearPrimary || record.year || (state.collectionId === "jefferson" ? "Date not established" : "Date unknown")));
      return meta;
    })(),
    textElement("span", "cover-state-label", coverLabel(cover))
  );
  object.setAttribute("aria-hidden", "true");
  return object;
}

function renderHero() {
  clear(dom.heroStage);
  const featured = resolveFeaturedItems(state.records, state.featuredConfig, state.visuals, 11);
  featured.forEach((record, index) => {
    const visual = recordVisual(record);
    const cover = coverStateForRecord(record);
    const button = document.createElement("button");
    button.type = "button";
    button.className = "hero-book";
    button.dataset.recordId = record.id;
    button.dataset.coverStatus = cover.status;
    button.setAttribute("aria-label", `Open ${record.title}${record.authors[0] ? ` by ${record.authors[0]}` : ""}. ${coverLabel(cover)}`);
    applyBookStyle(button, physicalRecord(record), visual);
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
      dom.heroFocusMeta.textContent = [compactMeta(record), coverLabel(cover)].filter(Boolean).join(" · ");
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
  if (!state.collectionManifest?.facets?.includes("signals")) return;
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
  const facets = state.facets || collectionFacets(state.records);
  const historical = activeEntityType() === "sowerby_entry";
  dom.collectionCount.textContent = formatNumber(state.records.length);
  dom.classCount.textContent = historical ? formatNumber(state.hierarchy?.chapters?.length || 44) : formatNumber(facets.classes.length);
  dom.yearSpan.textContent = historical
    ? "Not established"
    : (facets.minYear && facets.maxYear ? `${facets.minYear}–${facets.maxYear}` : "Cataloged dates");
  if (dom.classCount.nextElementSibling) dom.classCount.nextElementSibling.textContent = historical ? "historical chapters" : "LC classes";
  if (dom.yearSpan.nextElementSibling) dom.yearSpan.nextElementSibling.textContent = historical ? "publication dates" : "publication span";
}

function sourceAnchor(label, url, className = "") {
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.target = "_blank";
  anchor.rel = "noopener noreferrer";
  anchor.className = className;
  anchor.textContent = label;
  return anchor;
}

function placementControl(record, { card = false } = {}) {
  if (!featureEnabled("placement")) {
    const omitted = textElement("span", "placement-disabled", "");
    omitted.hidden = true;
    return omitted;
  }
  const placements = Array.isArray(record.placements) ? record.placements : [];
  if (!placements.length) {
    return textElement("span", card ? "placement-unknown book-card-placement" : "placement-unknown", "Original Sekula placement not supplied in this record");
  }
  const placement = placements[0];
  const button = document.createElement("button");
  button.type = "button";
  button.className = card ? "placement-badge book-card-placement" : "placement-badge";
  button.textContent = `${placement.label}${placements.length > 1 ? ` +${placements.length - 1}` : ""}`;
  button.title = `Browse records with the Clark placement ${placement.label}${placement.roomLabel ? ` in ${placement.roomLabel}` : ""}`;
  button.addEventListener("click", () => applyPlacement(placement));
  return button;
}

function journeyContextPhoto(manifest) {
  return manifest?.photographs?.find(photo => photo.image) || null;
}

function journeyCitation(manifest, id) {
  return manifest?.citations?.find(citation => citation.id === id) || null;
}

function journeyContextFigure(photo, citation, className, { eager = false } = {}) {
  const figure = document.createElement("figure");
  figure.className = className;
  if (!photo?.image) {
    figure.classList.add("is-withheld");
    figure.append(
      textElement("strong", "", "Context image withheld"),
      textElement("p", "", "The journey manifest does not currently authorize a context image for public display.")
    );
    return figure;
  }
  const picture = document.createElement("picture");
  picture.append(responsiveImage({
    image_url: photo.image.url,
    thumbnail_url: photo.image.thumbnail_url,
    width: photo.image.width,
    height: photo.image.height
  }, photo.alt, { eager }));
  const caption = document.createElement("figcaption");
  caption.append(document.createTextNode(`${photo.rights.credit_line} Library context only—not a Sekula artwork or association evidence. `));
  if (citation?.url) caption.append(sourceAnchor("Source ↗", citation.url));
  figure.append(picture, caption);
  return figure;
}

async function renderJourneyFeature() {
  clear(dom.journeyFeature);
  const journey = state.journeyIndex.journeys?.[0];
  if (!journey) {
    const unavailable = textElement("div", "journey-feature-loading", "No reviewed journey is currently available.");
    dom.journeyFeature.append(unavailable);
    return;
  }
  dom.journeyFeature.append(textElement("div", "journey-feature-loading", "Preparing the cited journey…"));
  const manifest = await loadJourneyManifest(journey.id);
  if (!manifest) {
    clear(dom.journeyFeature);
    dom.journeyFeature.append(textElement("div", "journey-feature-loading", "The journey evidence could not be loaded."));
    return;
  }
  const contextPhoto = journeyContextPhoto(manifest);
  const contextCitation = journeyCitation(manifest, contextPhoto?.source_citation_id);
  clear(dom.journeyFeature);
  const article = document.createElement("article");
  article.className = "journey-feature-card";
  article.append(journeyContextFigure(contextPhoto, contextCitation, "journey-feature-media", { eager: false }));
  const copy = document.createElement("div");
  copy.className = "journey-feature-copy";
  const status = document.createElement("div");
  status.className = "journey-status";
  status.append(
    textElement("span", "is-live", "Research preview"),
    textElement("span", "", "Artwork images rights-pending"),
    textElement("span", "", "No inferred relations")
  );
  copy.append(status, textElement("h3", "", journey.title), textElement("p", "", journey.subtitle));
  const meta = document.createElement("div");
  meta.className = "journey-feature-meta";
  [
    [journey.cluster_count, "photo movements"],
    [journey.association_count, "published associations"],
    [1, "Clark work record"]
  ].forEach(([value, label]) => {
    const item = document.createElement("div");
    item.append(textElement("strong", "", String(value)), textElement("span", "", label));
    meta.append(item);
  });
  const open = textElement("button", "journey-open", "Open the journey →");
  open.type = "button";
  open.addEventListener("click", () => { void openJourney(journey.id, { updateHistory: true, scroll: true }); });
  copy.append(meta, open);
  article.append(copy);
  dom.journeyFeature.append(article);
}

async function loadJourneyManifest(id) {
  if (state.journeyManifests.has(id)) return state.journeyManifests.get(id);
  const entry = journeyById(state.journeyIndex, id);
  if (!entry) return null;
  const raw = await fetchJson(new URL(entry.manifest_ref, document.baseURI), null);
  if (!raw) return null;
  const manifest = parseJourneyManifest(raw, { catalogIds: state.recordIds });
  if (manifest.rejected || manifest.id !== id) {
    console.warn("ShelfSignals rejected a journey manifest:", manifest.errors);
    return null;
  }
  state.journeyManifests.set(id, manifest);
  return manifest;
}

function journeyPhotoMedia(photo, citation) {
  if (photo?.image) {
    const figure = document.createElement("figure");
    figure.className = "journey-cluster-media";
    const image = {
      image_url: photo.image.url,
      thumbnail_url: photo.image.thumbnail_url,
      width: photo.image.width,
      height: photo.image.height
    };
    figure.append(responsiveImage(image, photo.alt));
    const caption = document.createElement("figcaption");
    caption.append(document.createTextNode(`${photo.caption} ${photo.rights.credit_line || ""} `));
    if (citation?.url) caption.append(sourceAnchor("Source ↗", citation.url));
    figure.append(caption);
    return figure;
  }
  const withheld = document.createElement("div");
  withheld.className = "journey-cluster-media is-withheld";
  withheld.append(
    textElement("strong", "", photo?.title || "Photograph metadata"),
    textElement("p", "", `${photo?.caption || "The source record is available, but ShelfSignals has no permission to reproduce the image."} Rights status: permission required.`)
  );
  if (citation?.url) withheld.append(sourceAnchor("Open the cited source ↗", citation.url, "journey-source-link"));
  return withheld;
}

function setActiveJourneyCluster(id = "") {
  let activeButton = null;
  dom.journeyTimeline?.querySelectorAll("button[data-cluster-id]").forEach(button => {
    const active = button.dataset.clusterId === id;
    button.classList.toggle("active", active);
    if (active) {
      activeButton = button;
      button.setAttribute("aria-current", "step");
    }
    else button.removeAttribute("aria-current");
  });
  if (activeButton && dom.journeyTimeline.scrollWidth > dom.journeyTimeline.clientWidth) {
    const left = activeButton.offsetLeft - (dom.journeyTimeline.clientWidth - activeButton.offsetWidth) / 2;
    dom.journeyTimeline.scrollTo({
      left: Math.max(0, left),
      behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth"
    });
  }
}

function journeyClusterAtReadingLine() {
  const clusters = [...dom.journeyClusters.querySelectorAll(".journey-cluster[data-cluster-id]")];
  if (!clusters.length) return "";
  const headerHeight = Number.parseFloat(getComputedStyle(document.documentElement).getPropertyValue("--header-h")) || 0;
  const readingLine = headerHeight + 116;
  return clusters
    .map(cluster => ({ id: cluster.dataset.clusterId, distance: Math.abs(cluster.getBoundingClientRect().top - readingLine) }))
    .sort((left, right) => left.distance - right.distance)[0]?.id || "";
}

function navigateJourneyCluster(id, { push = false, focus = false, behavior = "smooth" } = {}) {
  const target = document.getElementById(`journey-cluster-${id}`);
  if (!target || dom.journeyReader.hidden) return false;
  const navigationToken = ++state.journeyNavigationToken;
  state.journeyNavigationLock = id;
  state.clusterId = id;
  setActiveJourneyCluster(id);
  updateUrl({ replace: !push, scrollY: target.offsetTop });
  target.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : behavior, block: "start" });
  if (focus) requestAnimationFrame(() => target.focus({ preventScroll: true }));
  let settled = false;
  let timeout = 0;
  const settleHistory = () => {
    if (settled || navigationToken !== state.journeyNavigationToken) return;
    settled = true;
    clearTimeout(timeout);
    state.journeyNavigationLock = "";
    const activeId = journeyClusterAtReadingLine() || id;
    state.clusterId = activeId;
    setActiveJourneyCluster(activeId);
    if (state.journeyId) updateUrl({ scrollY: window.scrollY });
  };
  if ("onscrollend" in window) window.addEventListener("scrollend", settleHistory, { once: true });
  timeout = window.setTimeout(settleHistory, behavior === "auto" || matchMedia("(prefers-reduced-motion: reduce)").matches ? 100 : 1100);
  return true;
}

function renderJourneyTimeline(manifest) {
  clear(dom.journeyTimeline);
  [...manifest.clusters].sort((left, right) => left.order - right.order).forEach(cluster => {
    const button = document.createElement("button");
    button.type = "button";
    button.dataset.clusterId = cluster.id;
    button.append(textElement("span", "", String(cluster.order).padStart(2, "0")), document.createTextNode(cluster.title));
    button.addEventListener("click", () => navigateJourneyCluster(cluster.id, { push: true, focus: true }));
    dom.journeyTimeline.append(button);
  });
  setActiveJourneyCluster(state.clusterId);
}

function renderJourneyMosaic(manifest) {
  clear(dom.journeyMosaic);
  const photos = new Map(manifest.photographs.map(photo => [photo.id, photo]));
  const citations = new Map(manifest.citations.map(citation => [citation.id, citation]));
  const header = document.createElement("header");
  header.append(textElement("p", "section-index", "Five cited sequence movements"), textElement("h3", "", "A disassembled photo-text work, held at the rights boundary"));
  const grid = document.createElement("div");
  grid.className = "journey-mosaic-grid";
  [...manifest.clusters].sort((left, right) => left.order - right.order).forEach(cluster => {
    const photo = photos.get(cluster.photograph_ids[0]);
    const citation = citations.get(photo?.source_citation_id);
    const card = document.createElement("article");
    card.className = "journey-mosaic-card";
    const media = journeyPhotoMedia(photo, citation);
    media.classList.add("journey-mosaic-media");
    const open = document.createElement("button");
    open.type = "button";
    open.append(textElement("span", "", String(cluster.order).padStart(2, "0")), document.createTextNode(cluster.title));
    open.addEventListener("click", () => navigateJourneyCluster(cluster.id, { push: true, focus: true }));
    card.append(media, open);
    grid.append(card);
  });
  dom.journeyMosaic.append(header, grid);
}

function observeJourneyClusters() {
  state.journeyObserver?.disconnect();
  if (!("IntersectionObserver" in window)) return;
  state.journeyObserver = new IntersectionObserver(entries => {
    if (state.journeyNavigationLock) return;
    const current = entries
      .filter(entry => entry.isIntersecting)
      .sort((left, right) => right.intersectionRatio - left.intersectionRatio || Math.abs(left.boundingClientRect.top) - Math.abs(right.boundingClientRect.top))[0];
    const id = current?.target?.dataset?.clusterId;
    if (!id || id === state.clusterId || state.syncingHistory) return;
    state.clusterId = id;
    setActiveJourneyCluster(id);
    updateUrl({ scrollY: window.scrollY });
  }, { rootMargin: "-32% 0px -58% 0px", threshold: 0 });
  dom.journeyClusters.querySelectorAll(".journey-cluster").forEach(cluster => state.journeyObserver.observe(cluster));
}

function renderJourneyClusters(manifest) {
  clear(dom.journeyClusters);
  const photos = new Map(manifest.photographs.map(photo => [photo.id, photo]));
  const citations = new Map(manifest.citations.map(citation => [citation.id, citation]));
  [...manifest.clusters].sort((left, right) => left.order - right.order).forEach(cluster => {
    const photo = photos.get(cluster.photograph_ids[0]);
    const citation = citations.get(photo?.source_citation_id);
    const article = document.createElement("article");
    article.className = "journey-cluster";
    article.id = `journey-cluster-${cluster.id}`;
    article.dataset.clusterId = cluster.id;
    article.tabIndex = -1;
    const copy = document.createElement("div");
    copy.className = "journey-cluster-copy";
    copy.append(
      textElement("span", "cluster-index", `${String(cluster.order).padStart(2, "0")} / ${cluster.period_label || "Sequence movement"}`),
      textElement("h3", "", cluster.title),
      textElement("p", "", cluster.narrative),
      textElement("p", "cluster-scope", `${cluster.shelf_label} · Editorial navigation label. Rights-pending work imagery remains metadata-only; no substitute image is presented as Sekula’s photograph.`)
    );
    if (citation?.url) copy.append(sourceAnchor(`Read the source · ${citation.creator || citation.publisher} ↗`, citation.url, "journey-source-link"));
    article.append(journeyPhotoMedia(photo, citation), copy);
    dom.journeyClusters.append(article);
  });
  observeJourneyClusters();
}

const JOURNEY_PHASE_LABELS = Object.freeze({
  preliminary_context: "Preliminary context",
  early_research: "Early research",
  direct_alignment: "Direct alignment with the work",
  post_reflection: "Post-project reflection"
});

function targetWorkCard(manifest) {
  const target = manifest.target_works[0];
  const record = target ? state.recordMap.get(target.id) : null;
  if (!record) return null;
  const article = document.createElement("article");
  article.className = "journey-book-card";
  const open = document.createElement("button");
  open.type = "button";
  open.className = "book-open";
  open.setAttribute("aria-label", `Open the Clark record for ${record.title}`);
  open.append(makeBookObject(record), textElement("h4", "", record.displayTitle), textElement("span", "book-card-meta", `${record.yearPrimary || record.year} · Work identity, not an influence claim`));
  open.addEventListener("click", () => openDetail(record.id, true));
  article.append(open, placementControl(record, { card: true }));
  return article;
}

function renderJourneyShelves(manifest) {
  clear(dom.journeyPhaseShelves);
  const publicAssociations = getPublicAssociations(manifest);
  const citations = new Map(manifest.citations.map(citation => [citation.id, citation]));
  JOURNEY_PHASES.forEach((phase, index) => {
    const section = document.createElement("section");
    section.className = "journey-phase";
    const header = document.createElement("header");
    const phaseAssociations = publicAssociations.filter(association => association.phase === phase);
    header.append(textElement("strong", "", JOURNEY_PHASE_LABELS[phase]), textElement("span", "", `${String(index + 1).padStart(2, "0")} · ${phaseAssociations.length} reviewed relation${phaseAssociations.length === 1 ? "" : "s"}`));
    const shelf = document.createElement("div");
    shelf.className = "journey-book-shelf";
    if (phase === "direct_alignment") {
      const anchor = targetWorkCard(manifest);
      if (anchor) shelf.append(anchor);
    }
    phaseAssociations.forEach(association => {
      const record = state.recordMap.get(association.catalog_id);
      if (!record) return;
      const card = document.createElement("article");
      card.className = "journey-book-card";
      const open = document.createElement("button");
      open.type = "button";
      open.className = "book-open";
      open.setAttribute("aria-label", `Open the Clark record for ${record.title}`);
      open.append(makeBookObject(record), textElement("h4", "", record.displayTitle), textElement("span", "book-card-meta", association.reasoning));
      open.addEventListener("click", () => openDetail(record.id, true));
      const evidence = document.createElement("div");
      evidence.className = "journey-association-evidence";
      evidence.append(
        textElement("strong", "", associationClaimLabel(association)),
        textElement("span", "", `${titleCase(association.evidence_grade)} evidence`),
        textElement("span", "", `Reviewed by ${association.review.reviewer} · ${association.review.reviewed_at}`)
      );
      const links = document.createElement("div");
      links.className = "journey-association-citations";
      association.citation_ids.forEach(id => {
        const citation = citations.get(id);
        if (citation?.url) links.append(sourceAnchor(`Source · ${citation.title} ↗`, citation.url));
      });
      if (links.childElementCount) evidence.append(links);
      card.append(open, evidence, placementControl(record, { card: true }));
      shelf.append(card);
    });
    if (!shelf.childElementCount) {
      const empty = document.createElement("div");
      empty.className = "journey-empty-shelf";
      empty.append(textElement("strong", "", "No reviewed relation published"), document.createTextNode("A source-backed candidate may enter here only after a named librarian records a decision, date, and reasoning."));
      shelf.append(empty);
    }
    section.append(header, shelf);
    dom.journeyPhaseShelves.append(section);
  });
}

function evidenceItem(title, copy, link = null) {
  const item = document.createElement("article");
  item.className = "journey-evidence-item";
  item.append(textElement("strong", "", title), textElement("p", "", copy));
  if (link?.url) item.append(sourceAnchor(link.label || "Open source ↗", link.url));
  return item;
}

function renderJourneyEvidence(manifest) {
  clear(dom.journeyEvidenceBody);
  dom.journeyEvidenceBody.className = "journey-evidence-body";
  const contextPhoto = journeyContextPhoto(manifest);
  const contextCitation = journeyCitation(manifest, contextPhoto?.source_citation_id);
  const derivativeNote = contextPhoto?.image?.sha256
    ? ` Local derivative retrieved ${contextPhoto.image.retrieved_at}; committed full-size SHA-256 ${contextPhoto.image.sha256.slice(7, 19)}… and thumbnail SHA-256 ${contextPhoto.image.thumbnail_sha256.slice(7, 19)}…. ${contextPhoto.image.derivative.reproducibility_status}.`
    : "";
  const contextEvidence = contextPhoto?.image
    ? evidenceItem("Context photograph", `${contextPhoto.caption} ${contextPhoto.rights.credit_line}${derivativeNote}`, contextCitation?.url ? { label: "Open image source and license ↗", url: contextCitation.url } : null)
    : evidenceItem("Context photograph", "No context photograph is authorized by the active journey manifest; the interface displays no hardcoded fallback image.");
  if (contextPhoto?.image && contextPhoto.rights?.license_url) {
    contextEvidence.append(sourceAnchor("Read the image license ↗", contextPhoto.rights.license_url));
  }
  dom.journeyEvidenceBody.append(
    evidenceItem("Publication gate", "No machine-suggested book relation is bundled with this public manifest. Empty shelves are evidence of restraint, not missing interface content.", { label: "Open the local-only review tool →", url: "./review.html" }),
    evidenceItem("Artwork rights", "Getty access is not reproduction permission, and Generali routes image reuse through a permission request. Sekula work images therefore appear as cited metadata frames only.", { label: "Getty permissions policy ↗", url: "https://www.getty.edu/research-conservation/library/reproductions-permissions/" }),
    contextEvidence,
    evidenceItem("Editorial scope", `${manifest.editorial.editor}; source audit recorded ${manifest.editorial.reviewed_at}. This approves the rights-aware journey structure, not any candidate association.`)
  );
  manifest.citations.forEach(citation => {
    dom.journeyEvidenceBody.append(evidenceItem(citation.title, [citation.creator, citation.publisher, citation.date, citation.locator].filter(Boolean).join(" · "), citation.url ? { label: "Open cited source ↗", url: citation.url } : null));
  });
}

function renderJourneyReader(manifest) {
  dom.journeyReaderTitle.textContent = manifest.title;
  dom.journeyKicker.textContent = "Photo-sequence research · work images pending permission";
  dom.journeyDeck.textContent = manifest.introduction;
  dom.journeyProgress.textContent = `${manifest.title} · ${manifest.clusters.length} movements · rights-aware preview`;
  clear(dom.journeyFacts);
  [["Work", manifest.target_works[0]?.date || "1973"], ["Movements", manifest.clusters.length], ["Published relations", getPublicAssociations(manifest).length]].forEach(([label, value]) => {
    const item = document.createElement("div");
    item.append(textElement("dt", "", label), textElement("dd", "", String(value)));
    dom.journeyFacts.append(item);
  });
  clear(dom.journeyHeroImage);
  const contextPhoto = journeyContextPhoto(manifest);
  const context = journeyContextFigure(contextPhoto, journeyCitation(manifest, contextPhoto?.source_citation_id), "journey-hero-image", { eager: true });
  dom.journeyHeroImage.replaceWith(context);
  context.id = "journeyHeroImage";
  dom.journeyHeroImage = context;
  renderJourneyTimeline(manifest);
  renderJourneyMosaic(manifest);
  renderJourneyClusters(manifest);
  renderJourneyShelves(manifest);
  renderJourneyEvidence(manifest);
}

async function openJourney(id, { updateHistory = false, scroll = false, guard = null } = {}) {
  const manifest = await loadJourneyManifest(id);
  if (guard && !guard()) return false;
  if (!manifest) {
    showToast("This journey could not be opened");
    return false;
  }
  if (updateHistory) {
    state.journeyLastFocus = document.activeElement;
    history.replaceState({ ...(history.state || {}), shelfsignals: true, scrollY: window.scrollY }, "", location.href);
    state.journeyReturnScroll = window.scrollY;
  }
  state.journeyId = id;
  state.journeyNavigationToken += 1;
  state.journeyNavigationLock = "";
  if (state.clusterId && !manifest.clusters.some(cluster => cluster.id === state.clusterId)) state.clusterId = "";
  renderJourneyReader(manifest);
  dom.journeyReader.hidden = false;
  if (updateHistory) updateUrl({ replace: false, scrollY: dom.journeyReader.offsetTop });
  if (updateHistory) requestAnimationFrame(() => dom.closeJourney.focus({ preventScroll: true }));
  if (scroll) requestAnimationFrame(() => {
    if (state.clusterId) navigateJourneyCluster(state.clusterId, { behavior: "auto" });
    else dom.journeyReader.scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth", block: "start" });
  });
  return true;
}

function closeJourney({ updateHistory = true, restoreScroll = true } = {}) {
  if (!state.journeyId && dom.journeyReader.hidden) return;
  state.journeyId = "";
  state.clusterId = "";
  state.journeyNavigationToken += 1;
  state.journeyNavigationLock = "";
  state.journeyObserver?.disconnect();
  dom.journeyReader.hidden = true;
  if (updateHistory) updateUrl({ replace: false, scrollY: state.journeyReturnScroll });
  if (restoreScroll) requestAnimationFrame(() => {
    const target = state.journeyReturnScroll || document.querySelector("#journeys")?.offsetTop || 0;
    window.scrollTo({ top: target, behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
  });
  const focusTarget = state.journeyLastFocus?.isConnected ? state.journeyLastFocus : dom.journeyFeature?.querySelector(".journey-open");
  if (focusTarget) requestAnimationFrame(() => focusTarget.focus({ preventScroll: true }));
}

function pathColor(path, index) {
  const signal = SIGNALS.find(item => path.signals?.includes(item.id));
  return signal?.color || ["#785842", "#3e5d63", "#5a4d68", "#5f6045"][index % 4];
}

function renderPaths() {
  clear(dom.pathGrid);
  if (!featureEnabled("curated_paths")) return;
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
    button.append(textElement("span", "path-title", path.title));
    button.append(textElement("span", "path-description", path.subtitle || path.narrative || "A dynamic route through catalog metadata."));
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

function evidenceStatusLabel(value) {
  if (value === "sowerby_510_exact_bounded") return "Bounded Sowerby link established";
  if (value === "sowerby_entry_page_resolved") return "Exact LOC scan page resolved";
  if (value === "sowerby_entry_aggregate_spine") return "LOC aggregate scan-spine support";
  return "Collection-heading membership only";
}

function initFacetControls() {
  const facets = state.facets || collectionFacets(state.records);
  if (activeFacetIds().includes("classes")) facets.classes.forEach(value => addOption(dom.lcFilter, value, value));
  if (activeFacetIds().includes("materials")) facets.materials.forEach(value => addOption(dom.materialFilter, value, titleCase(value)));
  if (activeFacetIds().includes("decades")) facets.decades.forEach(value => addOption(dom.decadeFilter, String(value), `${value}s`));
  if (activeFacetIds().includes("evidence_status")) {
    [...new Set(state.records.map(record => record.evidence_status).filter(Boolean))]
      .sort()
      .forEach(value => addOption(dom.evidenceFilter, value, evidenceStatusLabel(value)));
  }
  if (featureEnabled("photo_likelihood")) ["Strongly Likely", "Likely", "Plausible", "Unlikely"].forEach(value => addOption(dom.photoFilter, value, value));

  clear(dom.signalFilters);
  if (!activeFacetIds().includes("signals")) return;
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
  dom.evidenceFilter.value = state.filters.evidence;
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

async function applyCatalogQuery(value, { scroll = false, syncControls = false } = {}) {
  const query = String(value || "").trim();
  const requestToken = ++state.searchRequestToken;
  if (!query) cancelCatalogSearch();
  if (query && state.catalogSearchStatus !== "ready") {
    dom.collectionGrid.setAttribute("aria-busy", "true");
    dom.resultSummary.textContent = "Preparing the complete catalog search index…";
    dom.renderedCount.textContent = "Loading full-field search metadata…";
    const searchIndex = await ensureCatalogSearchIndex();
    if (requestToken !== state.searchRequestToken) return false;
    if (!searchIndex) showToast("Full-field search is unavailable; searching core catalog fields");
  }
  if (requestToken !== state.searchRequestToken) return false;
  state.filters = normalizeFilterState({ ...state.filters, query, path: "" });
  if (syncControls) syncFilterControls();
  applyFilters({ scroll });
  dom.collectionGrid.setAttribute("aria-busy", "false");
  return true;
}

function setFiltersExpanded(expanded) {
  dom.filtersPanel.classList.toggle("mobile-collapsed", !expanded);
  dom.toggleFilters.setAttribute("aria-expanded", expanded ? "true" : "false");
  dom.toggleFilters.textContent = expanded ? "Hide filters" : "Show filters";
}

function syncResponsiveFilters() {
  setFiltersExpanded(!matchMedia("(max-width: 620px)").matches);
}

function resetFilters({ scroll = false } = {}) {
  state.filters = normalizeFilterState({ group: state.filters.group });
  state.renderLimit = PAGE_SIZE;
  dom.heroSearchInput.value = "";
  syncFilterControls();
  applyFilters({ scroll });
}

function updateUrl({ selectedId = state.selectedId, replace = true, scrollY = window.scrollY } = {}) {
  if (state.syncingHistory) return;
  const url = serializeUrlState({
    ...state.filters,
    collection: state.collectionId,
    corpus: state.corpus,
    order: state.order,
    record: selectedId,
    journey: state.journeyId,
    cluster: state.clusterId,
    view: state.view
  });
  history[replace ? "replaceState" : "pushState"]({ shelfsignals: true, scrollY }, "", url);
}

function applyFilters({ scroll = false, push = false } = {}) {
  state.filters = normalizeFiltersForActiveCorpus(state.filters);
  state.renderLimit = PAGE_SIZE;
  state.filtered = orderedRecords(filterRecords(state.records, state.filters));
  renderCollection();
  renderActiveFilters();
  updateUrl({ replace: !push });
  if (scroll) $("#collection").scrollIntoView({ behavior: matchMedia("(prefers-reduced-motion: reduce)").matches ? "auto" : "smooth" });
}

function placementDisplayLabel(key) {
  for (const record of state.records) {
    const placement = record.placements?.find(item => item.key === key);
    if (placement) return placement.label;
  }
  return key;
}

function applyPlacement(placement) {
  if (!placement?.key) return;
  if (state.activeDrawer === dom.detailDrawer) closeDetail({ updateHistory: false });
  if (state.journeyId) closeJourney({ updateHistory: false, restoreScroll: false });
  state.filters = normalizeFilterState({ ...state.filters, placement: placement.key, path: "" });
  state.selectedId = "";
  syncFilterControls();
  applyFilters({ scroll: true, push: true });
}

function activeFilterEntries() {
  const entries = [];
  if (state.filters.path) entries.push({ key: "path", label: `Path: ${state.pathMap.get(state.filters.path)?.title || state.filters.path}` });
  if (state.filters.query) entries.push({ key: "query", label: `Search: ${state.filters.query}` });
  state.filters.signals.forEach(signal => entries.push({ key: `signal:${signal}`, label: SIGNAL_LABELS[signal]?.split(" /")[0] || signal }));
  if (state.filters.lc) entries.push({ key: "lc", label: `LC ${state.filters.lc}` });
  if (state.filters.material) entries.push({ key: "material", label: titleCase(state.filters.material) });
  if (state.filters.decade) entries.push({ key: "decade", label: `${state.filters.decade}s` });
  if (state.filters.evidence) entries.push({
    key: "evidence",
    label: `Evidence: ${evidenceStatusLabel(state.filters.evidence)}`
  });
  if (state.filters.photo) entries.push({ key: "photo", label: state.filters.photo });
  if (state.filters.placement) entries.push({ key: "placement", label: `Placement: ${placementDisplayLabel(state.filters.placement)}` });
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
  const article = document.createElement("article");
  article.className = "book-card";
  article.dataset.recordId = record.id;
  article.dataset.index = String(index);
  const button = document.createElement("button");
  button.type = "button";
  button.className = "book-open";
  button.setAttribute("aria-label", `Open ${record.title}${record.authors[0] ? ` by ${record.authors[0]}` : ""}`);
  button.append(makeBookObject(record));
  button.append(textElement("strong", "book-card-title", record.displayTitle));
  button.append(textElement("span", "book-card-meta", compactMeta(record) || record.material_type));
  const cover = coverStateForRecord(record);
  button.append(textElement("span", "book-card-cover-scope", compactCoverEvidence(cover)));
  button.addEventListener("click", () => openDetail(record.id, true));
  article.append(button, placementControl(record, { card: true }));
  return article;
}

function createListBook(record, index) {
  const article = document.createElement("article");
  article.className = "list-book-row";
  const button = document.createElement("button");
  button.type = "button";
  button.className = "list-book";
  button.append(textElement("span", "list-book-index", String(index + 1).padStart(3, "0")));
  button.append(textElement("span", "list-book-title", record.title));
  button.append(textElement("span", "list-book-author", authorLabel(record)));
  button.append(textElement("span", "list-book-year", record.yearPrimary || record.year || (state.collectionId === "jefferson" ? "Date not established" : "—")));
  button.append(textElement("span", "list-book-call", record.call_number || (state.collectionId === "jefferson" ? "Call number not established" : "—")));
  button.append(textElement("span", "", "→"));
  button.addEventListener("click", () => openDetail(record.id, true));
  article.append(button, placementControl(record));
  return article;
}

function createSpine(record) {
  const renderRecord = spineRenderRecord(record);
  const profile = renderRecord.physicalProfile;
  const enrichment = editionForRecord(record);
  const article = document.createElement("article");
  article.className = "spine-entry";
  article.dataset.recordId = record.id;
  article.dataset.spineStatus = profile.status || "unavailable";
  article.dataset.warningCount = String(profile.warnings?.length || 0);
  const button = document.createElement("button");
  button.type = "button";
  button.className = "spine-book";
  button.classList.toggle("has-edition-evidence", Boolean(enrichment));
  button.dataset.recordId = record.id;
  button.dataset.binding = profile.binding?.term || "";
  button.dataset.housing = profile.housing?.term || "";
  button.dataset.objectForm = profile.object_form?.term || "unknown";
  const metadata = [record.authors[0], record.yearPrimary || record.year, record.call_number].filter(Boolean).join(" · ");
  const editionLabel = externalEditionLabel(enrichment);
  const evidenceDescription = enrichment
    ? ` Open Library provider-edition details are available${editionLabel ? `: ${editionLabel}` : ` (${enrichment.preferred.source_id})`}; they do not shape this spine or describe the Clark copy.`
    : "";
  const placementDescription = record.placements?.length ? ` Original placement: ${record.placements.map(item => item.label).join("; ")}.` : " Original Sekula placement not supplied in this record.";
  const profileDescription = canDisplaySpine(profile)
    ? ` Metadata-derived physical representation; ${profile.axis_evidence?.height?.status === "stated" ? "height follows the Clark catalog" : "height uses a neutral renderer fallback"}${profile.axis_evidence?.depth?.status === "estimated" ? ", and depth is modeled from Clark-stated extent rather than measured" : ", with no factual depth asserted"}.`
    : " Neutral physical placeholder; no validated spine geometry is available.";
  button.title = `${record.title}${metadata ? ` — ${metadata}` : ""}.${profileDescription}${placementDescription}${evidenceDescription}`.trim();
  button.setAttribute("aria-label", `Open ${record.title}${record.authors[0] ? ` by ${record.authors[0]}` : ""}${record.call_number ? `, call number ${record.call_number}` : ""}.${profileDescription}${placementDescription}${evidenceDescription}`);
  button.append(textElement("span", "spine-title", record.displayTitle));
  if (metadata) button.append(textElement("span", "spine-meta", metadata));
  if (!canDisplaySpine(profile)) button.append(textElement("span", "spine-status-marker", "Evidence unavailable"));
  if (enrichment) {
    const evidence = textElement("span", "spine-evidence", "");
    evidence.setAttribute("aria-hidden", "true");
    button.append(evidence);
  }
  // Shelf geometry is intentionally independent of covers and provider image
  // analysis. Only the validated compact Clark-derived profile is supplied.
  applyBookStyle(article, renderRecord, null);
  applyBookStyle(button, renderRecord, null);
  button.addEventListener("click", () => openDetail(record.id, true));
  const placement = placementControl(record);
  placement.classList.add("spine-placement");
  article.append(button, placement);
  return article;
}

function updateCollectionProgress(count, rendered) {
  dom.loadMoreWrap.hidden = count === 0;
  dom.loadMore.hidden = rendered >= count;
  const remaining = Math.max(0, count - rendered);
  dom.loadMore.textContent = remaining ? `Reveal next ${formatNumber(Math.min(PAGE_SIZE, remaining))} records` : "All matching records revealed";
  if (state.view === "spines" && state.spineIndexStatus === "loading") {
    dom.renderedCount.textContent = `${formatNumber(rendered)} rendered · validating physical evidence…`;
  } else if (state.view === "spines" && state.spineIndexStatus === "failed") {
    dom.renderedCount.textContent = `${formatNumber(rendered)} rendered · physical evidence unavailable; neutral placeholders shown`;
  } else {
    dom.renderedCount.textContent = count ? `${formatNumber(rendered)} rendered · ${formatNumber(remaining)} remaining` : "";
  }
}

function renderCollection() {
  clear(dom.collectionGrid);
  const total = state.records.length;
  const count = state.filtered.length;
  const rendered = Math.min(state.renderLimit, count);
  const unit = activeUnitLabel();
  dom.resultSummary.textContent = `${formatNumber(count)} of ${formatNumber(total)} ${unit}${state.filters.path ? ` · dynamic path “${state.pathMap.get(state.filters.path)?.title || state.filters.path}”` : ""}${state.filters.placement ? ` · recorded placement “${placementDisplayLabel(state.filters.placement)}”` : ""}`;
  dom.collectionGrid.className = `collection-grid ${state.view}-view`;
  dom.profileMethod.hidden = state.view !== "spines" || !featureEnabled("physical");
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
        shelf.setAttribute("role", "group");
        shelf.setAttribute("aria-label", `${group.label} books`);
        group.items.forEach(record => shelf.append(createSpine(record)));
        section.append(header, shelf);
        dom.collectionGrid.append(section);
      });
    }
  }

  updateCollectionProgress(count, rendered);
}

function appendCollectionPage() {
  const count = state.filtered.length;
  if (!count || state.renderLimit >= count) return;
  if (state.view === "spines") {
    state.renderLimit = Math.min(state.renderLimit + PAGE_SIZE, count);
    renderCollection();
    return;
  }

  const selector = state.view === "covers" ? ".book-card" : ".list-book-row";
  const start = dom.collectionGrid.querySelectorAll(selector).length;
  const end = Math.min(start + PAGE_SIZE, count);
  if (start >= end) {
    state.renderLimit = end;
    updateCollectionProgress(count, end);
    return;
  }

  state.renderLimit = end;
  dom.collectionGrid.setAttribute("aria-busy", "true");
  dom.loadMore.disabled = true;
  const fragment = document.createDocumentFragment();
  state.filtered.slice(start, end).forEach((record, offset) => {
    const index = start + offset;
    fragment.append(state.view === "covers" ? createCoverCard(record, index) : createListBook(record, index));
  });
  dom.collectionGrid.append(fragment);
  updateCollectionProgress(count, end);
  requestAnimationFrame(() => {
    dom.collectionGrid.setAttribute("aria-busy", "false");
    dom.loadMore.disabled = false;
  });
}

function metadataRow(label, value) {
  if (!value && value !== 0) return null;
  const wrapper = document.createElement("div");
  wrapper.append(textElement("dt", "", label), textElement("dd", "", String(value)));
  return wrapper;
}

function physicalMetricRow(label, value, status = "") {
  const row = document.createElement("div");
  const description = document.createElement("dd");
  description.append(document.createTextNode(value || "Not recorded"));
  if (status) description.append(textElement("span", "metric-status", status));
  row.append(textElement("dt", "", label), description);
  return row;
}

function formatCentimeters(value, minimum, maximum, approximate = false) {
  if (!Number.isFinite(value)) return "Not recorded";
  const range = Number.isFinite(minimum) && Number.isFinite(maximum) && minimum !== maximum
    ? `${minimum}–${maximum} cm`
    : `${value} cm`;
  return `${approximate ? "≈ " : ""}${range}`;
}

function extentLabel(extent) {
  if (!extent) return "Not recorded";
  return [
    [extent.pages, "pages"],
    [extent.leaves, "leaves"],
    [extent.sheets, "sheets"],
    [extent.volumes, "volumes"]
  ].filter(([value]) => Number.isFinite(value)).map(([value, unit]) => `${value} ${unit}`).join(" · ") || "Not recorded";
}

function bindingLabel(binding) {
  return binding?.term ? titleCase(binding.term.replaceAll("-", " ")) : "Not recorded";
}

function statedEvidenceStatus(value) {
  if (!value) return "Unknown";
  return value.status === "external_edition_stated" ? "Open Library edition" : "Clark catalog";
}

function dimensionAxisEvidenceStatus(dimensions, axis) {
  if (!Number.isFinite(dimensions?.[`${axis}_cm`])) return "Unknown";
  const provenance = dimensions.provenance?.[`${axis}_cm`];
  return provenance?.status === "external_edition_stated" ? "Open Library edition" : "Clark catalog";
}

function thicknessEvidenceStatus(thickness) {
  if (!thickness) return "Not modeled";
  if (thickness.status === "external_edition_stated") return "Open Library edition · stated";
  if (thickness.method === "catalog-extent-external-binding-model-v1") return "Estimated from extent · Clark + edition binding";
  if (thickness.method === "external-edition-extent-model-v1" || thickness.status === "estimated_external") return "Estimated from extent · Open Library edition";
  return "Estimated from extent · Clark catalog";
}

function thicknessIsModeled(thickness) {
  return Boolean(thickness) && (String(thickness.status || "").startsWith("estimated") || String(thickness.method || "").includes("model"));
}

function externalPhysicalInputs(profile) {
  const inputs = [];
  if (profile.dimensions?.provenance?.height_cm?.status === "external_edition_stated") inputs.push("height");
  if (profile.dimensions?.provenance?.width_cm?.status === "external_edition_stated") inputs.push("width");
  if (profile.thickness?.status === "external_edition_stated") inputs.push("stated depth");
  if (profile.binding?.status === "external_edition_stated") inputs.push("binding");
  if (profile.extent?.status === "external_edition_stated") inputs.push("page extent");
  return inputs;
}

function spineAxisEvidenceLabel(profile, axis) {
  const evidence = profile?.axis_evidence?.[axis];
  if (!evidence) {
    if (state.spineIndexStatus === "loading") return "Validating Clark-derived index";
    if (state.spineIndexStatus === "failed") return "Unavailable · index validation failed";
    return "Unknown";
  }
  const selected = {
    clark_catalog_stated: "Clark catalog stated",
    catalog_extent_model: "Estimated from extent · Clark catalog stated",
    neutral_renderer_default: "Neutral renderer fallback"
  }[evidence.selected_source] || titleCase(String(evidence.selected_source || evidence.status).replaceAll("_", " "));
  return `${selected} · precedence ${evidence.precedence_rank}/${evidence.precedence.length}`;
}

function controlledTerm(value, fallback = "Not recorded") {
  const term = value?.term || value;
  return term ? titleCase(String(term).replaceAll("_", " ").replaceAll("-", " ")) : fallback;
}

function renderPhysicalProfile(record) {
  // The drawer's physical contract is Clark-only. Provider edition metadata
  // is optional context in its own panel and never fills a Clark axis here.
  const catalogProfile = profileFromRecord(record);
  const profile = validatedSpineProfile(record);
  const renderProfile = profile || {};
  const renderRecord = { ...record, physicalProfile: renderProfile };
  dom.physicalBook.removeAttribute("style");
  dom.physicalBook.classList.remove("has-cover", "cover-ready");
  dom.physicalBook.dataset.binding = renderProfile.binding?.term || "";
  dom.physicalBook.dataset.housing = renderProfile.housing?.term || "";
  dom.physicalBook.dataset.spineStatus = profile ? "indexed" : "unavailable";
  applyBookStyle(dom.physicalBook, renderRecord, null);

  clear(dom.physicalMetrics);
  const dimensions = renderProfile.dimensions;
  const thickness = renderProfile.thickness;
  dom.physicalMetrics.append(
    physicalMetricRow("Height", formatCentimeters(dimensions?.height_cm, dimensions?.height_min_cm, dimensions?.height_max_cm), spineAxisEvidenceLabel(renderProfile, "height")),
    physicalMetricRow("Width", formatCentimeters(dimensions?.width_cm, dimensions?.width_min_cm, dimensions?.width_max_cm), spineAxisEvidenceLabel(renderProfile, "width")),
    physicalMetricRow("Depth", formatCentimeters(thickness?.value_cm, thickness?.min_cm, thickness?.max_cm, Boolean(thickness)), spineAxisEvidenceLabel(renderProfile, "depth")),
    physicalMetricRow("Catalog extent", extentLabel(catalogProfile.extent), statedEvidenceStatus(catalogProfile.extent)),
    physicalMetricRow("Binding", controlledTerm(renderProfile.binding), renderProfile.binding ? "Clark catalog" : "Not stated"),
    physicalMetricRow("Housing", controlledTerm(renderProfile.housing), renderProfile.housing ? "Clark catalog · separate from binding" : "Not stated"),
    physicalMetricRow("Object form", controlledTerm(renderProfile.object_form, "Unknown"), renderProfile.object_form ? `${titleCase(renderProfile.object_form.evidence_status)} · ${renderProfile.object_form.basis.replaceAll("_", " ")}` : "Unavailable"),
    physicalMetricRow("Representation", profile ? "Synthetic metadata derived" : "Neutral placeholder", profile ? "Metadata only · not a photograph" : "No validated geometry")
  );
  clear(dom.physicalEvidence);
  if (!profile) {
    const reason = state.spineIndexStatus === "loading"
      ? "The compact Clark-derived physical index is being validated. Neutral geometry is shown until that check finishes."
      : state.spineIndexStatus === "failed"
        ? "The compact physical index failed source or schema validation. ShelfSignals is fail-closed: neutral geometry is shown and no measurement is asserted."
        : "No validated compact physical record is available. Neutral geometry is shown and no measurement is asserted.";
    dom.physicalEvidence.append(textElement("p", "", reason));
    if (catalogProfile.source_format) dom.physicalEvidence.append(textElement("p", "", `Uninterpreted Clark catalog wording remains available as source evidence: ${catalogProfile.source_format}.`));
    return;
  }

  dom.physicalEvidence.append(textElement("p", "", `${profile.rights.credit_line}. Scope: metadata only; reuse status ${profile.rights.reuse_status.replaceAll("_", " ")}. Provenance: ${profile.provenance_ref}.`));
  if (catalogProfile.source_format) dom.physicalEvidence.append(textElement("p", "", `Clark catalog wording: ${catalogProfile.source_format}.`));
  const details = document.createElement("details");
  details.className = "physical-contract";
  details.append(textElement("summary", "", `Evidence precedence and ${profile.warnings.length} representation note${profile.warnings.length === 1 ? "" : "s"}`));
  const list = document.createElement("ul");
  ["height", "width", "depth"].forEach(axis => {
    const evidence = profile.axis_evidence[axis];
    list.append(textElement("li", "", `${titleCase(axis)} selected ${evidence.selected_source.replaceAll("_", " ")} at precedence ${evidence.precedence_rank}/${evidence.precedence.length}; order: ${evidence.precedence.join(" → ").replaceAll("_", " ")}. Copy-specific: no.`));
  });
  profile.warnings.forEach(warning => list.append(textElement("li", "", `${warning.code.replaceAll("_", " ")}: ${warning.message}`)));
  details.append(list);
  dom.physicalEvidence.append(details);
}

function editionMatchLabel(candidate) {
  const types = [...new Set(candidate.match.identifiers.map(identifier => identifier.type.toUpperCase()))];
  const identifiers = candidate.match.identifiers.map(identifier => `${identifier.type.toUpperCase()} ${identifier.value}`).join(" · ");
  return `${candidate.match.method === "isbn_exact" ? "Exact ISBN" : `Exact ${types.join(" / ")}`} match${identifiers ? ` · ${identifiers}` : ""}`;
}

function renderEditionLoader(record) {
  const enrichment = editionForRecord(record);
  dom.detailEditionLoader.setAttribute("aria-busy", state.editionStatus === "loading" ? "true" : "false");
  dom.loadEditionEvidence.hidden = state.editionStatus === "ready";
  dom.loadEditionEvidence.disabled = state.editionStatus === "loading";

  if (state.editionStatus === "loading") {
    dom.loadEditionEvidence.textContent = "Loading external edition evidence…";
    dom.editionLoaderStatus.textContent = "Downloading and validating the optional provider snapshot. Clark-copy facts and physical geometry remain unchanged.";
  } else if (state.editionStatus === "ready") {
    dom.editionLoaderStatus.textContent = enrichment
      ? "The provider snapshot is loaded and contains an exact-identifier edition reference for this record. Its evidence appears below and remains separate from the Clark copy."
      : "The provider snapshot is loaded; it contains no validated exact-identifier edition reference for this record.";
  } else if (state.editionStatus === "failed") {
    dom.loadEditionEvidence.textContent = "Try external edition evidence again · 17 MB";
    dom.editionLoaderStatus.textContent = "The optional provider snapshot could not be loaded or validated. The Clark record and Clark-derived physical evidence remain available.";
  } else {
    dom.loadEditionEvidence.textContent = "Load external edition evidence · 17 MB";
    dom.editionLoaderStatus.textContent = "Load the external provider snapshot only if you want to check for an exact-identifier edition reference. This is optional provider evidence, not evidence about the Clark copy.";
  }
}

function renderEditionEvidence(record) {
  renderEditionLoader(record);
  const enrichment = editionForRecord(record);
  clear(dom.editionMetadata);
  dom.editionEvidenceLink.removeAttribute("href");
  if (!enrichment) {
    dom.detailEdition.hidden = true;
    dom.editionEvidenceNote.textContent = "";
    return;
  }

  const profile = physicalRecord(record).physicalProfile;
  const appliedSourceId = profile.external_evidence?.source_id;
  const candidate = enrichment.candidates.find(item => item.source_id === appliedSourceId) || enrichment.preferred;
  const edition = candidate.edition;
  const snapshot = /^\d{4}-\d{2}-\d{2}$/.test(state.editions.source?.provider_snapshot || "")
    ? state.editions.source.provider_snapshot
    : "";
  const extent = [
    edition.number_of_pages ? `${formatNumber(edition.number_of_pages)} pages` : "",
    edition.pagination
  ].filter(Boolean).join(" · ");
  [
    metadataRow("Open Library ID", candidate.source_id),
    metadataRow("Match", editionMatchLabel(candidate)),
    metadataRow("Source snapshot", snapshot),
    metadataRow("Record modified", candidate.record_modified),
    metadataRow("Edition", externalEditionLabel({ preferred: candidate })),
    metadataRow("Publisher", edition.publishers?.join(" · ")),
    metadataRow("Physical format", edition.physical_format),
    metadataRow("Dimensions", edition.physical_dimensions),
    metadataRow("Weight", edition.weight),
    metadataRow("Extent", extent),
    metadataRow("Series", edition.series?.join(" · ")),
    metadataRow("Languages", edition.languages?.join(" · "))
  ].filter(Boolean).forEach(row => dom.editionMetadata.append(row));
  dom.editionEvidenceNote.textContent = "This is metadata for a matched Open Library provider edition, not evidence about the Clark copy. It does not establish the Clark copy’s dimensions, texture, wear, or side profile.";
  dom.editionEvidenceLink.href = candidate.source_url;
  dom.editionEvidenceLink.textContent = `View ${candidate.source_id} in Open Library ↗`;
  dom.detailEdition.hidden = false;
}

async function requestEditionEvidence() {
  const recordId = state.selectedId;
  const record = state.recordMap.get(recordId);
  if (!record || state.editionStatus === "loading") return;
  state.editionStatus = "loading";
  renderEditionLoader(record);
  const manifest = await loadEditionEnrichment();
  if (state.selectedId !== recordId) return;
  renderEditionEvidence(record);
  if (manifest && editionForRecord(record)) dom.detailEdition.querySelector("h3")?.focus({ preventScroll: true });
  else if (!manifest) dom.loadEditionEvidence.focus({ preventScroll: true });
  else {
    dom.editionLoaderStatus.tabIndex = -1;
    dom.editionLoaderStatus.focus({ preventScroll: true });
  }
}

function renderPlacementEvidence(record) {
  clear(dom.detailPlacementList);
  const placements = Array.isArray(record.placements) ? record.placements : [];
  if (!placements.length) {
    dom.detailPlacementList.append(textElement("span", "placement-unknown", "Original Sekula placement not supplied in this record"));
    const currentLocation = record.best_location?.subLocation || record.holdings?.[0]?.subLocation;
    if (currentLocation) dom.detailPlacementList.append(textElement("span", "placement-current", `Current Clark service location: ${currentLocation}`));
    return;
  }
  placements.forEach(placement => {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "placement-badge";
    button.textContent = placement.label;
    button.title = `Browse the same recorded placement${placement.roomLabel ? ` · ${placement.roomLabel}` : ""}`;
    button.addEventListener("click", () => applyPlacement(placement));
    dom.detailPlacementList.append(button);
  });
}

async function loadCoverProvenance() {
  if (state.coverProvenance) return state.coverProvenance;
  if (state.coverProvenancePromise) return state.coverProvenancePromise;
  state.coverProvenancePromise = (async () => {
    const provenanceUrl = manifestAssetUrl("cover_provenance");
    if (!provenanceUrl) return null;
    const raw = await fetchJson(provenanceUrl, null);
    if (!raw) return null;
    const parsed = parseCoverProvenance(raw, { catalogIds: state.recordIds, datasetSha256: state.catalogSha256 });
    if (parsed.rejected) {
      console.warn("ShelfSignals rejected cover provenance:", parsed.errors);
      return null;
    }
    state.coverProvenance = parsed;
    return parsed;
  })().finally(() => { state.coverProvenancePromise = null; });
  return state.coverProvenancePromise;
}

async function renderCoverEvidence(record) {
  const requestToken = ++state.coverEvidenceRequestToken;
  clear(dom.detailCoverEvidenceBody);
  if (state.collectionId === "jefferson") {
    const publicItems = state.publicMedia?.items || [];
    const reviewItems = state.reviewUnlocked ? (state.reviewMedia?.items || []) : [];
    const media = [...publicItems, ...reviewItems].find(item => item.record_id === record.id);
    if (!media) {
      dom.detailCoverEvidenceBody.append(
        textElement("p", "cover-evidence-status unresolved", "Digital surrogate not established"),
        textElement("p", "evidence-scope", state.reviewUnlocked
          ? "No exact, reviewed digital-object relation is present in the current evidence manifest. This does not assert that no surrogate exists."
          : "Public mode contains only manually approved media. Rights-pending preview metadata is loaded only after reviewer-mode unlock; absence here does not assert that no surrogate exists.")
      );
      return;
    }
    if (media.thumbnail_url) {
      const image = document.createElement("img");
      image.src = media.thumbnail_url;
      image.alt = "Library of Congress digital-object preview; rights review required";
      image.loading = "lazy";
      image.referrerPolicy = "no-referrer";
      dom.detailCoverEvidenceBody.append(image);
    }
    const rights = Array.isArray(media.rights_access) ? media.rights_access.join(" · ") : String(media.rights_access || "Not established");
    const list = document.createElement("dl");
    list.className = "edition-metadata";
    [
      metadataRow("Entity", `Digital object linked to this ${record.entity_type === "sowerby_entry" ? "Sowerby entry" : "catalog instance"}`),
      metadataRow("Match basis", media.match_basis || "Not established"),
      metadataRow("Sowerby candidate", Array.isArray(media.sowerby_numbers) ? media.sowerby_numbers.join(" · ") : media.sowerby_numbers),
      metadataRow("Rights & Access", rights),
      metadataRow("Review", titleCase(media.review_status || "not established"))
    ].filter(Boolean).forEach(row => list.append(row));
    dom.detailCoverEvidenceBody.append(textElement("p", "cover-evidence-status provider_reference", "Review media—not cleared for reuse"), list);
    if (media.url) dom.detailCoverEvidenceBody.append(sourceAnchor("View LOC item and Rights & Access ↗", media.url, "edition-evidence-link"));
    dom.detailCoverEvidenceBody.append(textElement("p", "evidence-scope", `The linked digital object, ${record.entity_type === "sowerby_entry" ? "Sowerby entry" : "catalog instance"}, edition, and physical copy remain separate evidence entities. Review mode is interface friction, not access control or rights clearance.`));
    return;
  }
  const cover = coverStateForRecord(record);
  if (!canDisplayCover(cover)) {
    dom.detailCoverEvidenceBody.append(
      textElement("p", "cover-evidence-status unresolved", UNRESOLVED_COVER_LABEL),
      textElement("p", "evidence-scope", "The interface keeps a labeled surrogate front face. No work-level or look-alike image is substituted for this Clark edition.")
    );
    return;
  }
  dom.detailCoverEvidenceBody.append(
    textElement("p", `cover-evidence-status ${cover.status}`, coverLabel(cover)),
    textElement("p", "evidence-scope", "Loading the source match, rights scope, and retrieval record…")
  );
  const provenance = await loadCoverProvenance();
  if (state.selectedId !== record.id || requestToken !== state.coverEvidenceRequestToken) return;
  clear(dom.detailCoverEvidenceBody);
  if (!canDisplayCover(coverStateForRecord(record))) {
    dom.detailCoverEvidenceBody.append(
      textElement("p", "cover-evidence-status unresolved", UNRESOLVED_COVER_LABEL),
      textElement("p", "evidence-scope", "The provider image could not be displayed, so ShelfSignals reverted to the real metadata-derived front face.")
    );
    return;
  }
  const evidence = provenance ? getRecordCoverProvenance(record, provenance) : null;
  if (!evidence || !canDisplayCover(evidence)) {
    dom.detailCoverEvidenceBody.append(textElement("p", "evidence-scope", "The compact cover is available, but its detailed provenance record could not be loaded."));
    return;
  }
  const list = document.createElement("dl");
  list.className = "edition-metadata";
  const identifiers = evidence.matched_identifiers.map(identifier => `${identifier.type.toUpperCase()} ${identifier.value}`).join(" · ");
  [
    metadataRow("Scope", "Exact provider edition — not Clark-copy photography"),
    metadataRow("Provider", titleCase(evidence.provider || "")),
    metadataRow("Exact match", identifiers),
    metadataRow("Selection", evidence.selection_rationale),
    metadataRow("Retrieved", evidence.retrieved_at),
    metadataRow("Display basis", titleCase(evidence.rights?.basis || "unknown")),
    metadataRow("Review", evidence.status === "verified"
      ? `${evidence.review.reviewer} · ${evidence.review.reviewed_at}`
      : "Legacy exact-identifier reference · named visual review not yet recorded"),
    metadataRow("Cache", evidence.cache_policy === "remote_only" ? "Remote provider image; binary not cached" : titleCase(evidence.cache_policy))
  ].filter(Boolean).forEach(row => list.append(row));
  dom.detailCoverEvidenceBody.append(textElement("p", `cover-evidence-status ${evidence.status}`, coverLabel(evidence)), list);
  if (evidence.source?.source_url) dom.detailCoverEvidenceBody.append(sourceAnchor("View cover source record ↗", evidence.source.source_url, "edition-evidence-link"));
  dom.detailCoverEvidenceBody.append(textElement("p", "evidence-scope", "Provider display availability does not establish that the underlying cover artwork is openly licensed, and it does not describe this Clark copy’s texture, wear, or side profile."));
}

function setDrawer(drawer, open) {
  if (open) {
    if (state.activeDrawer && state.activeDrawer !== drawer) setDrawer(state.activeDrawer, false);
    state.activeDrawer = drawer;
    state.lastFocus = document.activeElement;
    drawer.inert = false;
    drawer.classList.add("open");
    drawer.setAttribute("aria-hidden", "false");
    dom.drawerBackdrop.hidden = false;
    document.body.classList.add("drawer-open");
    dom.pageRegions.forEach(region => { region.inert = true; });
    requestAnimationFrame(() => {
      const target = drawer.querySelector("#closeDetail, #closeShelf") || drawer.querySelector("button:not(:disabled), a[href]");
      target?.focus();
    });
  } else {
    drawer.classList.remove("open");
    drawer.setAttribute("aria-hidden", "true");
    drawer.inert = true;
    if (state.activeDrawer === drawer) state.activeDrawer = null;
    if (!state.activeDrawer) {
      dom.drawerBackdrop.hidden = true;
      document.body.classList.remove("drawer-open");
      dom.pageRegions.forEach(region => { region.inert = false; });
      if (state.lastFocus?.isConnected) state.lastFocus.focus();
    }
  }
}

function setDetailLoadState(status, record) {
  const loading = status === "loading";
  dom.detailContent.classList.toggle("is-loading", loading);
  dom.detailLoading.classList.toggle("error", status === "failed");
  if (status === "ready") {
    dom.detailLoading.hidden = true;
    dom.detailLoading.textContent = "";
    return;
  }
  dom.detailLoading.hidden = false;
  const source = activeCorpusCopy().source_label || "source catalog";
  dom.detailLoading.textContent = status === "failed"
    ? `Complete catalog detail could not be loaded. Core source-backed fields from ${source} remain available; empty detail fields are not asserted as absent.`
    : `Loading the complete ${source} detail for ${record?.displayTitle || record?.title || "this record"}…`;
}

function renderDetail(record) {
  const position = state.filtered.findIndex(item => item.id === record.id);
  const positionUnit = record.entity_type === "sowerby_entry" ? "Entry" : "Record";
  dom.detailPosition.textContent = position >= 0 ? `${positionUnit} ${formatNumber(position + 1)} of ${formatNumber(state.filtered.length)}` : `Collection ${positionUnit.toLocaleLowerCase()}`;
  clear(dom.detailVisual);
  dom.detailVisual.append(makeBookObject(record, { eager: true }));
  dom.detailKicker.textContent = record.entity_type === "sowerby_entry"
    ? ["Sowerby entry", record.sowerby_identifier ? `No. ${record.sowerby_identifier}` : ""].filter(Boolean).join(" · ")
    : [record.material_type, record.call_number].filter(Boolean).join(" · ");
  dom.detailTitle.textContent = record.title;
  dom.detailByline.textContent = [record.authors.length ? `By ${record.authors.join(", ")}` : "", record.year].filter(Boolean).join(" · ");
  dom.catalogLink.href = record.catalogLink;
  dom.catalogLink.hidden = !record.catalogLink;
  updateDetailShelfButton(record.id);
  dom.detailShelfButton.onclick = () => toggleShelf(record.id);
  dom.previousBook.disabled = position <= 0;
  dom.nextBook.disabled = position < 0 || position >= state.filtered.length - 1;

  clear(dom.detailMetadata);
  if (state.collectionId === "jefferson") {
    const values = value => Array.isArray(value) ? value.filter(Boolean).join(" · ") : String(value || "");
    const sowerby = values(record.sowerby_candidates || record.sowerby_numbers);
    const reconstructionLabel = !record.ownership_or_reconstruction_status || ["unresolved", "not_established"].includes(record.ownership_or_reconstruction_status)
      ? "Not established"
      : record.ownership_or_reconstruction_status;
    if (record.entity_type === "sowerby_entry") {
      const sowerbyNumber = record.sowerby_identifier || sowerby;
      const historicalLinks = record.historical_links || {};
      const linkValue = field => values(historicalLinks[field]) || "Not established";
      const sequence = Number.isInteger(record.orders?.sowerby) ? formatNumber(record.orders.sowerby + 1) : "Not established";
      [
        metadataRow("Entity", "Sowerby entry"),
        metadataRow("Sowerby entry ID", record.id),
        metadataRow("Sowerby number", sowerbyNumber || "Not established"),
        metadataRow("Source-backed order rank", sequence),
        metadataRow("Faculty", record.faculty || "Not established"),
        metadataRow("Chapter", [record.chapter_number, record.chapter_label].filter(Boolean).join(" · ") || "Not established"),
        metadataRow("Identifier evidence", evidenceStatusLabel(record.evidence_status)),
        metadataRow("Primary creators", record.authors.length ? record.authors.join(" · ") : "Not established"),
        metadataRow("Other contributors", record.other_contributors?.length ? record.other_contributors.join(" · ") : "Not established"),
        metadataRow("Publication", record.year || "Not established"),
        metadataRow("Place", values(record.publication_places) || "Not established"),
        metadataRow("Publisher", record.publishers.length ? record.publishers.join(" · ") : "Not established"),
        metadataRow("Languages", values(record.languages) || "Not established"),
        metadataRow("Format", record.formats.length ? record.formats.join(" · ") : "Not established"),
        metadataRow("Current LOC catalog relation", linkValue("catalog_instances")),
        metadataRow("Edition relation", linkValue("editions")),
        metadataRow("Volume relation", linkValue("volumes")),
        metadataRow("Physical copy identity", linkValue("physical_copies")),
        metadataRow("Holding relation", linkValue("holdings")),
        metadataRow("Digital object relation", linkValue("digital_objects")),
        metadataRow("Reconstruction status", reconstructionLabel)
      ].forEach(row => dom.detailMetadata.append(row));
    } else {
      const holdingCalls = [
        ...(Array.isArray(record.holdings) ? record.holdings : []),
        ...(Array.isArray(record.items) ? record.items : [])
      ].flatMap(item => [item?.call_number, item?.callNumber, item?.shelving_location]).filter(Boolean);
      const classifications = Array.isArray(record.classifications)
        ? record.classifications.map(item => item?.value || item).filter(Boolean).join(" · ")
        : values(record.classifications || record.facets?.classifications || record.call_number);
      const holdingIds = (Array.isArray(record.holdings) ? record.holdings : []).map(item => item?.hrid || item?.id).filter(Boolean);
      const itemIds = (Array.isArray(record.items) ? record.items : []).map(item => item?.hrid || item?.id).filter(Boolean);
      const itemStatusCounts = new Map();
      (Array.isArray(record.items) ? record.items : []).forEach(item => {
        const status = String(item?.status || "").trim();
        if (status) itemStatusCounts.set(status, (itemStatusCounts.get(status) || 0) + 1);
      });
      const itemStatuses = [...itemStatusCounts].map(([status, count]) => `${status}${count > 1 ? ` (${count})` : ""}`).join(" · ");
      const itemLocations = [...new Set((Array.isArray(record.items) ? record.items : []).map(item => String(item?.effective_location || "").trim()).filter(Boolean))];
      const holdingLocations = [...new Set((Array.isArray(record.holdings) ? record.holdings : []).map(item => String(item?.permanent_location || "").trim()).filter(Boolean))];
      const evidenceLabel = record.evidence_status === "sowerby_510_exact_bounded"
        ? "Exact LOC collection-heading membership with a bounded source-MARC Sowerby link"
        : "Exact LOC collection-heading membership; Sowerby link not established";
      const relationshipLabel = record.relationship_to_jefferson === "exact_collection_heading_membership"
        ? "Exact LOC collection-heading match; ownership not established"
        : "Not established";
      [
        metadataRow("Entity", "Catalog instance"),
        metadataRow("Catalog instance ID", record.id),
        metadataRow("Evidence", evidenceLabel),
        metadataRow("Other contributors", record.other_contributors?.length ? record.other_contributors.join(" · ") : "Not established"),
        metadataRow("Publication", record.year || "Not established"),
        metadataRow("Place", values(record.publication_places) || "Not established"),
        metadataRow("Publisher", record.publishers.length ? record.publishers.join(" · ") : "Not established"),
        metadataRow("Languages", values(record.languages) || "Not established"),
        metadataRow("Format", record.formats.length ? record.formats.join(" · ") : (record.material_type || "Not established")),
        metadataRow("Modern classification", classifications || "Not established"),
        metadataRow("Holding call number", [...new Set(holdingCalls)].join(" · ") || "Not established"),
        metadataRow("Holdings", holdingIds.length ? `${holdingIds.length} current LOC holding${holdingIds.length === 1 ? "" : "s"} · ${holdingIds.join(" · ")}` : "Not established"),
        metadataRow("Catalog items", itemIds.length ? `${itemIds.length} current LOC item${itemIds.length === 1 ? "" : "s"} · ${itemIds.join(" · ")}` : "Not established"),
        metadataRow("Current LOC item status", itemStatuses || "Not established"),
        metadataRow("Current LOC item location", itemLocations.join(" · ") || "Not established"),
        metadataRow("Current LOC holding location", holdingLocations.join(" · ") || "Not established"),
        metadataRow("Historical Sowerby order", sowerby ? `Candidate ${sowerby} · bounded evidence only` : "Not established"),
        metadataRow("Edition relation", "Not established"),
        metadataRow("Physical copy identity", "Not established"),
        metadataRow("Collection membership", relationshipLabel),
        metadataRow("Reconstruction status", reconstructionLabel)
      ].forEach(row => dom.detailMetadata.append(row));
    }
  } else {
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
    metadataRow("Photo likelihood", photoValue)
  ].filter(Boolean).forEach(row => dom.detailMetadata.append(row));
  }

  if (featureEnabled("placement")) renderPlacementEvidence(record);
  void renderCoverEvidence(record);
  if (featureEnabled("physical")) renderPhysicalProfile(record);
  if (featureEnabled("provider_editions")) renderEditionEvidence(record);

  clear(dom.subjectList);
  record.subjects.slice(0, 24).forEach(subject => dom.subjectList.append(textElement("span", "", subject)));
  dom.detailSubjects.hidden = !record.subjects.length;
  clear(dom.notesList);
  const assertionNotes = record.field_evidence && typeof record.field_evidence === "object"
    ? Object.entries(record.field_evidence).map(([field, assertion]) => {
      const status = !assertion?.status || assertion.status === "unresolved" ? "not established" : assertion.status;
      return `${titleCase(field)} — ${status}: ${assertion?.assertion || "No assertion supplied"}. Source: ${assertion?.source || "not established"}.`;
    })
    : [];
  const sowerbyNotes = Array.isArray(record.sowerby_evidence)
    ? record.sowerby_evidence.map(assertion => `Sowerby ${assertion.sowerby_number} — ${assertion.status}: ${assertion.evidence} (${assertion.assessment_scope?.selected_catalog_entity_count || 0} records assessed; ${assertion.assessment_scope?.catalog_entities_not_assessed || 0} not assessed).`)
    : [];
  const historicalNotes = Array.isArray(record.historical_assertions)
    ? record.historical_assertions.map(assertion => {
      const paragraph = textElement("p", "", `${titleCase(assertion.field)} — ${assertion.status}: ${assertion.value || "No value asserted"}. Source: ${assertion.source}. `);
      const source = document.createElement("a");
      source.href = assertion.source_url;
      source.target = "_blank";
      source.rel = "noopener noreferrer";
      source.textContent = "Evidence page ↗";
      paragraph.append(source, document.createTextNode(` Evidence SHA-256: ${assertion.evidence_sha256}. As of: ${assertion.as_of}.`));
      return paragraph;
    })
    : [];
  const evidenceNotes = state.collectionId === "jefferson"
    ? [...record.notes, ...assertionNotes, ...sowerbyNotes, ...historicalNotes]
    : [...record.notes, ...record.sekula_notes, ...record.provenance_notes];
  evidenceNotes.slice(0, 16).forEach(note => dom.notesList.append(note instanceof Node
    ? note
    : textElement("p", "", typeof note === "string" ? note : JSON.stringify(note))));
  dom.detailNotes.hidden = !dom.notesList.childElementCount;
}

async function openDetail(id, updateHistory = false) {
  const record = state.recordMap.get(id);
  if (!record) return;
  const detailRequestToken = ++state.detailRequestToken;
  const spineIndexPromise = ensureSpineIndex();
  dom.detailPhysical.setAttribute("aria-busy", state.spineIndexStatus === "ready" ? "false" : "true");
  state.selectedId = id;
  setDetailLoadState("loading", record);
  if (state.activeDrawer !== dom.detailDrawer) setDrawer(dom.detailDrawer, true);
  updateUrl({ selectedId: id, replace: !updateHistory });
  const hydrated = record.detail_hydrated || await ensureCatalogDetailShard(record.detail_shard);
  if (detailRequestToken !== state.detailRequestToken || state.selectedId !== id) return;
  renderDetail(record);
  setDetailLoadState(hydrated && record.detail_hydrated ? "ready" : "failed", record);
  void spineIndexPromise.then(() => {
    if (state.selectedId === id) {
      renderPhysicalProfile(record);
      dom.detailPhysical.setAttribute("aria-busy", "false");
    }
  });
}

function closeDetail({ updateHistory = true } = {}) {
  state.detailRequestToken += 1;
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
  const saved = saveShelfIds(next, globalThis.localStorage, collectionShelfKey());
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
      const open = document.createElement("button");
      open.type = "button";
      open.className = "shelf-item-open";
      open.setAttribute("aria-label", `Open ${record.title}`);
      open.append(textElement("strong", "", record.displayTitle), textElement("small", "", compactMeta(record)));
      open.addEventListener("click", () => openDetail(record.id, true));
      copy.append(open);
      copy.append(placementControl(record, { card: true }));
      const remove = document.createElement("button");
      remove.type = "button";
      remove.textContent = "✕";
      remove.setAttribute("aria-label", `Remove ${record.title} from My Shelf`);
      remove.addEventListener("click", () => toggleShelf(record.id));
      item.append(copy, remove);
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
    datasetId: state.collectionId,
    datasetName: state.collectionManifest.copy.name,
    datasetCorpus: state.corpus,
    datasetHash: state.catalogSha256.replace(/^sha256:/, ""),
    appVersion: APP_VERSION
  });
  downloadReceipt(receipt, state.collectionManifest.shelf.receipt_name);
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
      const restored = restoreShelfFromReceipt(receipt, state.records, {
        collectionId: state.collectionId,
        corpusId: state.corpus,
        datasetHash: state.catalogSha256
      });
      if (!restored.valid) throw new Error("Receipt belongs to another collection, corpus, or dataset version");
      state.shelfIds = mergeShelfIdsForCorpus(state.shelfIds, restored.ids, state.records, {
        recordIdPrefix: state.activeCorpus?.record_id_prefix || ""
      });
      saveShelfIds(state.shelfIds, globalThis.localStorage, collectionShelfKey());
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
  void renderSearchSuggestions(dom.globalSearchInput.value);
  requestAnimationFrame(() => dom.globalSearchInput.focus());
}

async function renderSearchSuggestions(query) {
  const requestToken = ++state.suggestionRequestToken;
  clear(dom.searchSuggestions);
  const trimmed = String(query || "").trim();
  if (trimmed && state.catalogSearchStatus !== "ready") {
    const loading = textElement("p", "shelf-empty", "Preparing the complete catalog search…");
    loading.setAttribute("role", "status");
    dom.searchSuggestions.append(loading);
    await ensureCatalogSearchIndex();
    if (requestToken !== state.suggestionRequestToken) return;
    clear(dom.searchSuggestions);
  }
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
  dom.collectionSwitcher?.addEventListener("change", event => changeCollection(event.currentTarget.value));
  dom.corpusSwitcher?.addEventListener("change", event => changeCorpus(event.currentTarget.value));
  dom.orderFilter?.addEventListener("change", () => {
    const declared = new Set((state.activeCorpus?.orders || state.collectionManifest.orders).map(option => option.id));
    if (!declared.has(dom.orderFilter.value)) return;
    state.order = dom.orderFilter.value;
    state.renderLimit = PAGE_SIZE;
    state.filtered = orderedRecords(filterRecords(state.records, state.filters));
    renderCollection();
    updateUrl({ replace: false });
  });
  $("#reviewerModeForm")?.addEventListener("submit", event => { void submitReviewerCode(event); });
  dom.openReviewerMode?.addEventListener("click", () => {
    dom.reviewerCodeError.hidden = true;
    if (!dom.reviewerDialog.open) dom.reviewerDialog.showModal();
    requestAnimationFrame(() => dom.reviewerCode.focus());
  });
  dom.closeReviewerDialog?.addEventListener("click", () => dom.reviewerDialog.close());
  dom.exitReviewerMode?.addEventListener("click", () => {
    void setReviewerMode(false).then(() => showToast("Review mode ended"));
  });
  syncResponsiveFilters();
  const filterBreakpoint = matchMedia("(max-width: 620px)");
  const handleFilterBreakpoint = event => setFiltersExpanded(!event.matches);
  if (filterBreakpoint.addEventListener) filterBreakpoint.addEventListener("change", handleFilterBreakpoint);
  else filterBreakpoint.addListener(handleFilterBreakpoint);
  const updateSearch = debounce(value => { void applyCatalogQuery(value); });
  dom.collectionSearch.addEventListener("input", event => updateSearch(event.target.value));
  dom.heroSearchForm.addEventListener("submit", async event => {
    event.preventDefault();
    await applyCatalogQuery(dom.heroSearchInput.value, { scroll: true, syncControls: true });
  });
  [[dom.lcFilter, "lc"], [dom.materialFilter, "material"], [dom.decadeFilter, "decade"], [dom.evidenceFilter, "evidence"], [dom.photoFilter, "photo"], [dom.groupFilter, "group"]].forEach(([select, key]) => {
    select.addEventListener("change", () => {
      state.filters = normalizeFilterState({ ...state.filters, [key]: select.value, path: key === "group" ? state.filters.path : "" });
      applyFilters();
    });
  });
  dom.resetFilters.addEventListener("click", () => resetFilters());
  dom.toggleFilters.addEventListener("click", () => {
    setFiltersExpanded(dom.toggleFilters.getAttribute("aria-expanded") !== "true");
  });
  dom.emptyReset.addEventListener("click", () => resetFilters());
  dom.loadMore.addEventListener("click", appendCollectionPage);
  $$(".view-button").forEach(button => button.addEventListener("click", async () => {
    state.view = button.dataset.view;
    $$(".view-button").forEach(candidate => {
      const active = candidate === button;
      candidate.classList.toggle("active", active);
      candidate.setAttribute("aria-pressed", active ? "true" : "false");
    });
    state.renderLimit = PAGE_SIZE;
    const spineIndexPromise = state.view === "spines" ? ensureSpineIndex() : null;
    dom.collectionGrid.setAttribute("aria-busy", spineIndexPromise ? "true" : "false");
    renderCollection();
    updateUrl();
    if (spineIndexPromise) {
      await spineIndexPromise;
      if (state.view === "spines") renderCollection();
      dom.collectionGrid.setAttribute("aria-busy", "false");
    }
  }));
  dom.openSearch.addEventListener("click", openSearchDialog);
  dom.closeJourney.addEventListener("click", () => closeJourney());
  dom.globalSearchInput.addEventListener("input", debounce(event => { void renderSearchSuggestions(event.target.value); }, 120));
  dom.globalSearchInput.addEventListener("keydown", async event => {
    if (event.key === "Enter") {
      event.preventDefault();
      dom.searchDialog.close();
      await applyCatalogQuery(event.currentTarget.value, { scroll: true, syncControls: true });
    }
  });
  dom.closeDetail.addEventListener("click", () => closeDetail());
  dom.loadEditionEvidence.addEventListener("click", () => { void requestEditionEvidence(); });
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
    saveShelfIds([], globalThis.localStorage, collectionShelfKey());
    renderShelf();
    showToast("My Shelf cleared");
  });
  document.addEventListener("keydown", event => {
    if (!state.activeDrawer && (event.metaKey || event.ctrlKey) && event.key.toLocaleLowerCase() === "k") {
      event.preventDefault();
      openSearchDialog();
    }
    if (event.key === "Escape") {
      if (dom.searchDialog.open) return;
      if (state.activeDrawer === dom.detailDrawer) closeDetail();
      else if (state.activeDrawer) setDrawer(state.activeDrawer, false);
      else if (state.journeyId) closeJourney();
    }
    if (event.key === "Tab" && state.activeDrawer) {
      const focusable = [...state.activeDrawer.querySelectorAll("button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), [tabindex]:not([tabindex='-1'])")]
        .filter(element => !element.hidden && element.getClientRects().length);
      if (focusable.length) {
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (!state.activeDrawer.contains(document.activeElement)) {
          event.preventDefault();
          (event.shiftKey ? last : first).focus();
        } else if (event.shiftKey && document.activeElement === first) {
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
  window.addEventListener("popstate", async event => {
    const syncToken = ++state.historySyncToken;
    const isCurrent = () => state.historySyncToken === syncToken;
    const restored = parseUrlState();
    const restoredCollection = Object.hasOwn(COLLECTION_MANIFEST_URLS, restored.collection) ? restored.collection : DEFAULT_COLLECTION_ID;
    if (restoredCollection !== state.collectionId) {
      location.reload();
      return;
    }
    state.syncingHistory = true;
    const restoredCorpus = resolveCollectionCorpusForState(state.collectionManifest, {
      requestedCorpus: restored.corpus,
      recordId: restored.record
    });
    if (!restoredCorpus || restoredCorpus.id !== state.activeCorpus?.id) {
      location.reload();
      return;
    }
    state.activeCorpus = restoredCorpus;
    const declaredOrders = new Set(restoredCorpus.orders.map(option => option.id));
    state.order = declaredOrders.has(restored.order) ? restored.order : restoredCorpus.default_order;
    state.corpus = state.collectionId === "jefferson" ? restoredCorpus.id : "";
    state.filters = normalizeFiltersForActiveCorpus(restored);
    state.view = ["covers", "list", ...(featureEnabled("physical") ? ["spines"] : [])].includes(restored.view) ? restored.view : "covers";
    state.selectedId = restored.record;
    state.clusterId = restored.cluster;
    syncFilterControls();
    if (dom.orderFilter) dom.orderFilter.value = state.order;
    state.filtered = orderedRecords(filterRecords(state.records, state.filters));
    if (state.view === "spines") {
      await ensureSpineIndex();
      if (!isCurrent()) return;
    }
    renderCollection();
    renderActiveFilters();
    $$(".view-button").forEach(button => {
      const active = button.dataset.view === state.view;
      button.classList.toggle("active", active);
      button.setAttribute("aria-pressed", active ? "true" : "false");
    });
    if (state.selectedId && state.recordMap.has(state.selectedId)) openDetail(state.selectedId);
    else if (state.selectedId) {
      state.selectedId = "";
      if (state.activeDrawer === dom.detailDrawer) closeDetail({ updateHistory: false });
      updateUrl({ selectedId: "", replace: true });
    } else if (state.activeDrawer === dom.detailDrawer) closeDetail({ updateHistory: false });
    if (featureEnabled("journeys") && restored.journey && journeyById(state.journeyIndex, restored.journey)) {
      await openJourney(restored.journey, { updateHistory: false, scroll: false, guard: isCurrent });
      if (!isCurrent()) return;
    } else if (state.journeyId || !dom.journeyReader.hidden) {
      closeJourney({ updateHistory: false, restoreScroll: false });
    }
    if (!isCurrent()) return;
    const scrollY = Number(event.state?.scrollY);
    // Restore before releasing the popstate transaction. This keeps the
    // newly revealed journey and its scroll position observable as one state,
    // and prevents the cluster observer from replacing the saved position.
    if (Number.isFinite(scrollY)) restoreScrollImmediately(scrollY);
    requestAnimationFrame(() => {
      if (state.historySyncToken === syncToken) state.syncingHistory = false;
    });
  });
}

async function ensureSpineIndex() {
  if (!featureEnabled("physical")) return null;
  if (state.spineIndex?.rejected === false) return state.spineIndex;
  if (state.spineIndexPromise) return state.spineIndexPromise;
  state.spineIndexStatus = "loading";
  if (!state.catalogSha256) {
    state.spineIndexStatus = "failed";
    console.warn("ShelfSignals cannot validate the spine index without the active catalog checksum.");
    return null;
  }
  const spineUrl = manifestAssetUrl("spines");
  if (!spineUrl) {
    state.spineIndexStatus = "failed";
    return null;
  }
  const attempt = loadSpineIndex(spineUrl, {
    catalogIds: state.recordIds,
    datasetSha256: state.catalogSha256
  })
    .then(index => {
      if (index.rejected) throw new Error(index.errors?.join(", ") || "the compact index failed validation");
      if (index.source.record_count !== state.records.length) throw new Error("the compact index does not match the active catalog record count");
      state.spineIndex = index;
      state.spineIndexStatus = "ready";
      return index;
    })
    .catch(error => {
      state.spineIndexStatus = "failed";
      console.warn(`ShelfSignals could not apply ${spineUrl}:`, error);
      return null;
    });
  state.spineIndexPromise = attempt;
  void attempt.finally(() => {
    if (state.spineIndexPromise === attempt) state.spineIndexPromise = null;
  });
  return attempt;
}

async function loadEditionEnrichment() {
  if (!featureEnabled("provider_editions")) return null;
  if (state.editionStatus === "ready") return state.editions;
  if (state.editionLoadPromise) return state.editionLoadPromise;
  state.editionStatus = "loading";
  const attempt = (async () => {
    try {
      const editionsUrl = manifestAssetUrl("editions");
      if (!editionsUrl) throw new Error("the collection manifest does not declare provider-edition data");
      const response = await fetch(editionsUrl);
      if (!response.ok) throw new Error(`${response.status} ${response.statusText}`);
      const manifest = await parseEditionEnrichmentManifestAsync(await response.json(), {
        batchSize: 400,
        yieldControl: yieldToBrowser
      });
      if (manifest.rejected) throw new Error("the manifest failed provenance or schema validation");
      if (manifest.source.record_count !== state.records.length) throw new Error("the manifest does not match the active catalog record count");

      state.editions = manifest;
      state.editionStatus = "ready";
      state.records.forEach(record => { delete record.physicalProfile; });
      await yieldToBrowser();

      $$(".hero-book[data-record-id]").forEach(button => {
        const record = state.recordMap.get(button.dataset.recordId);
        if (record) applyBookStyle(button, physicalRecord(record), recordVisual(record));
      });
      if (state.view === "spines") {
        renderCollection();
      } else if (state.view === "covers") {
        $$(".book-card[data-record-id]").forEach(card => {
          const record = state.recordMap.get(card.dataset.recordId);
          const object = card.querySelector(".book-object");
          if (record && object) applyBookStyle(object, physicalRecord(record), recordVisual(record));
        });
      }
      const selected = state.recordMap.get(state.selectedId);
      if (selected) {
        renderPhysicalProfile(selected);
        renderEditionEvidence(selected);
      }
      return manifest;
    } catch (error) {
      state.editionStatus = "failed";
      console.warn("ShelfSignals could not apply the provider-edition projection:", error);
      return null;
    }
  })();
  state.editionLoadPromise = attempt;
  const manifest = await attempt;
  if (!manifest && state.editionLoadPromise === attempt) state.editionLoadPromise = null;
  return manifest;
}

async function init() {
  setApplicationBusy(true);
  try {
    if ("scrollRestoration" in history) history.scrollRestoration = "manual";
    const canonicalUrl = new URL(location.href);
    const rawCollection = (canonicalUrl.searchParams.get("collection") || "").toLocaleLowerCase();
    if (rawCollection && !Object.hasOwn(COLLECTION_MANIFEST_URLS, rawCollection)) {
      canonicalUrl.searchParams.delete("collection");
      canonicalUrl.searchParams.delete("corpus");
      canonicalUrl.searchParams.delete("order");
    }
    const initialHistoryUrl = `${canonicalUrl.pathname}${canonicalUrl.search}${canonicalUrl.hash}`;
    if (!history.state?.shelfsignals || initialHistoryUrl !== `${location.pathname}${location.search}${location.hash}`) {
      history.replaceState({ shelfsignals: true, scrollY: window.scrollY }, "", initialHistoryUrl);
    }

    const rawManifest = await fetchJson(state.collectionManifestUrl, null);
    if (!rawManifest) throw new Error("The selected collection manifest is unavailable.");
    const parsedManifest = parseCollectionManifest(rawManifest, { expectedId: state.collectionId });
    if (parsedManifest.rejected) {
      throw new Error(`The selected collection manifest failed validation: ${parsedManifest.errors.map(error => `${error.path}: ${error.message}`).join(", ")}`);
    }
    state.collectionManifest = parsedManifest.manifest;
    state.activeCorpus = resolveCollectionCorpusForState(state.collectionManifest, {
      requestedCorpus: initialUrl.corpus,
      recordId: initialUrl.record
    });
    if (!state.activeCorpus) throw new Error("The selected collection has no available corpus package.");
    state.corpus = state.collectionId === "jefferson" ? state.activeCorpus.id : "";
    const declaredOrders = new Set(state.activeCorpus.orders.map(option => option.id));
    state.order = declaredOrders.has(initialUrl.order) ? initialUrl.order : state.activeCorpus.default_order;
    if (!featureEnabled("physical") && state.view === "spines") state.view = "covers";
    if (!featureEnabled("journeys")) {
      state.journeyId = "";
      state.clusterId = "";
    }
    state.filters = normalizeFiltersForActiveCorpus(state.filters);
    state.shelfIds = loadShelfIds(globalThis.localStorage, collectionShelfKey());
    setCollectionSpecificCopy();

    const optionalJson = (field, fallback) => {
      const url = manifestAssetUrl(field);
      return url ? fetchJson(url, fallback) : Promise.resolve(fallback);
    };
    const [rawCoreCatalog, rawCovers, featuredConfig, pathConfig, rawJourneyIndex, rawHierarchy, rawPublicMedia, rawValidation] = await Promise.all([
      fetchJson(manifestAssetUrl("core"), null),
      optionalJson("covers", {}),
      optionalJson("featured", {}),
      optionalJson("paths", { paths: [] }),
      optionalJson("journeys", { schema: "shelfsignals-journey-index@1", journeys: [] }),
      optionalJson("hierarchy", null),
      optionalJson("public_media", null),
      optionalJson("validation", null)
    ]);
    if (!rawCoreCatalog) throw new Error("The compact browser catalog is unavailable.");
    const coreCatalog = parseBrowserCatalog(rawCoreCatalog, {
      collectionId: state.collectionId,
      corpusId: state.activeCorpus.id,
      entityType: activeEntityType(),
      recordIdPrefix: state.activeCorpus.record_id_prefix || "",
      detailPathTemplate: state.activeCorpus.data?.detail_template || "",
      searchPath: state.activeCorpus.data?.search || ""
    });
    if (coreCatalog.rejected) throw new Error(`The compact browser catalog failed validation: ${coreCatalog.errors.map(error => `${error.path}: ${error.message}`).join(", ")}`);
    if (coreCatalog.source.record_count !== activeCoverage().record_count) {
      throw new Error("The compact catalog count does not match the selected corpus manifest.");
    }
    state.catalogSource = coreCatalog.source;
    state.catalogSha256 = coreCatalog.source.dataset_sha256;
    state.historicalNumbering = coreCatalog.numbering || null;
    if (activeEntityType() === "sowerby_entry") {
      const historicalCounts = historicalCoverageCounts();
      const gapIds = state.historicalNumbering?.gaps?.map(gap => gap.identifier) || [];
      if (state.historicalNumbering?.max_source_serial !== historicalCounts.positions
        || state.historicalNumbering?.source_backed_entry_count !== activeCoverage().record_count
        || historicalCounts.positions - historicalCounts.entries !== gapIds.length
        || gapIds.join("\u241f") !== JEFFERSON_SOURCE_NUMBERING_GAPS.join("\u241f")) {
        throw new Error("The historical numbering ledger does not match the selected corpus coverage.");
      }
    }
    const rawRecords = coreCatalog.records;
    if (!rawRecords.length) throw new Error("The collection dataset is empty or unavailable.");
    state.recordIds = new Set(rawRecords.map(record => String(record.id || "")).filter(Boolean));
    if (manifestAssetUrl("covers")) {
      state.covers = parseCoverIndex(rawCovers, { catalogIds: state.recordIds, datasetSha256: state.catalogSha256 });
      if (state.covers.rejected) console.warn("ShelfSignals rejected the cover index:", state.covers.errors);
    }
    state.visuals = parseVisualManifest({});
    if (featureEnabled("journeys")) {
      state.journeyIndex = parseJourneyIndex(rawJourneyIndex);
      if (state.journeyIndex.rejected) console.warn("ShelfSignals rejected the journey index:", state.journeyIndex.errors);
    }
    if (featureEnabled("historical_hierarchy")) {
      const historicalCounts = historicalCoverageCounts();
      const chapterNumbers = Array.isArray(rawHierarchy?.chapters) ? rawHierarchy.chapters.map(chapter => chapter?.chapter_number) : [];
      const facultyNames = Array.isArray(rawHierarchy?.faculties) ? new Set(rawHierarchy.faculties.map(faculty => faculty?.name)) : new Set();
      const hierarchyValid = rawHierarchy?.schema === "shelfsignals-jefferson-hierarchy@1"
        && rawHierarchy.collection_id === state.collectionId
        && rawHierarchy.base_integer_identifier_count === historicalCounts.positions
        && chapterNumbers.length === 44 && new Set(chapterNumbers).size === 44
        && chapterNumbers.every((number, index) => number === index + 1)
        && facultyNames.size === 3
        && rawHierarchy.chapters.every(chapter => facultyNames.has(chapter.faculty) && String(chapter.heading || "").trim());
      if (!hierarchyValid) throw new Error("The historical hierarchy failed its 44-chapter coverage contract.");
      state.hierarchy = rawHierarchy;
    }
    if (rawValidation) {
      const sameValidationSource = rawValidation.source
        && Object.keys(state.catalogSource).length === Object.keys(rawValidation.source).length
        && Object.keys(state.catalogSource).every(key => rawValidation.source[key] === state.catalogSource[key]);
      const expectedValidationSchema = activeEntityType() === "sowerby_entry"
        ? "shelfsignals-jefferson-historical-validation@1"
        : "shelfsignals-jefferson-browser-validation@1";
      if (rawValidation.schema !== expectedValidationSchema || rawValidation.collection_id !== state.collectionId
        || (activeEntityType() === "sowerby_entry" && rawValidation.corpus_id !== "historical") || !sameValidationSource) {
        throw new Error("The collection validation summary does not match the active corpus source.");
      }
      state.validation = rawValidation;
    }
    if (rawPublicMedia) {
      state.publicMedia = decodeMediaManifest(rawPublicMedia, "public");
      if (state.publicMedia.rejected) throw new Error("The public-media manifest failed collection or audience validation.");
    }
    state.featuredConfig = featuredConfig || {};
    state.paths = featureEnabled("curated_paths") && Array.isArray(pathConfig.paths) ? pathConfig.paths : [];
    state.pathMap = new Map(state.paths.map(path => [path.id, path]));
    state.records = await enrichInBatches(rawRecords);
    state.recordMap = new Map(state.records.map(record => [record.id, record]));
    state.facets = collectionFacets(state.records);
    if (state.filters.query) await ensureCatalogSearchIndex();
    state.filtered = orderedRecords(filterRecords(state.records, state.filters));
    if (state.view === "spines") await ensureSpineIndex();

    renderHero();
    renderHeroSignals();
    renderStats();
    updateJeffersonOverview();
    scheduleSecondarySections();
    initFacetControls();
    syncFilterControls();
    bindEvents();
    addRestoreReceiptControl();
    if (state.collectionManifest.review?.enabled && state.activeCorpus?.data?.review_media) {
      let persistedUnlock = false;
      try { persistedUnlock = sessionStorage.getItem(state.collectionManifest.review.session_key) === "unlocked"; } catch (_) { /* Session storage may be unavailable. */ }
      if (persistedUnlock) {
        try {
          await setReviewerMode(true);
        } catch (error) {
          console.warn("ShelfSignals could not restore reviewer mode; continuing in public mode:", error);
          state.reviewUnlocked = false;
          state.reviewMedia = null;
          try { sessionStorage.removeItem(state.collectionManifest.review.session_key); } catch (_) { /* Session storage may be unavailable. */ }
          dom.reviewerModeBanner.hidden = true;
        }
      } else {
        dom.reviewerModeBanner.hidden = true;
        dom.reviewerModeStatus.textContent = state.collectionManifest.review.warning;
      }
    }
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
    if (state.journeyId && journeyById(state.journeyIndex, state.journeyId)) {
      await openJourney(state.journeyId, { updateHistory: false, scroll: true });
    } else if (state.journeyId) {
      state.journeyId = "";
      updateUrl();
    }
    updateUrl();
    setApplicationBusy(false);
    dom.loading.classList.add("ready");
    setTimeout(() => dom.loading.remove(), 320);
  } catch (error) {
    console.error("ShelfSignals initialization failed:", error);
    const progress = dom.loading?.querySelector("p");
    if (progress) progress.textContent = `The library could not be opened: ${error.message}`;
    document.body.dataset.appState = "error";
    dom.loading?.setAttribute("aria-busy", "false");
    dom.loading?.classList.add("error");
    if (dom.retryApp) {
      dom.retryApp.hidden = false;
      dom.retryApp.focus();
    } else dom.loading?.focus();
  }
}

dom.retryApp?.addEventListener("click", () => location.reload());
init();
