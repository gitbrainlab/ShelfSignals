export const PRIVATE_OCR_SCHEMA = "shelfsignals-jefferson-private-ocr-review@1";

const SHA256 = /^sha256:[a-f0-9]{64}$/;
const UTC = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/;
const RECORD_ID = /^jefferson-sowerby-([1-9]\d{0,3})$/;
const ROOT_FIELDS = ["schema", "collection_id", "corpus_id", "audience", "generated_at", "source", "methodology", "coverage", "entries"];
const SOURCE_FIELDS = ["authority", "item_url", "rights_statement_url", "rights_clearance", "source_identity_sha256", "ocr_manifest_sha256", "historical_core_sha256", "insight_graph_sha256"];
const METHOD_FIELDS = ["selection", "sectioning", "visual_evidence", "confidence", "use_boundary"];
const COVERAGE_FIELDS = ["historical_entries", "page_resolved_entries", "pilot_entries", "chapters", "entries_per_chapter", "section_regions", "source_backed_titles", "direct_documentary_records"];
const ENTRY_FIELDS = ["record_id", "sowerby_number", "title", "title_status", "faculty", "chapter_number", "chapter_label", "volume", "terminal_pdf_page", "pdf_url", "section", "snapshots", "event_contexts"];
const SECTION_FIELDS = ["type", "classification_status", "transcript", "transcript_truncated", "line_count", "mean_confidence", "marker_confidence", "title_confidence"];
const SNAPSHOT_FIELDS = ["pdf_page", "region_pct", "image_url", "full_page_image_url", "line_count", "mean_confidence"];
const REGION_FIELDS = ["x", "y", "width", "height"];
const EVENT_FIELDS = ["event_id", "title", "date_label", "relationship", "context_score", "direct_relation", "event_use_status", "use_confidence_score"];
const LOC_ITEM_URL = "https://www.loc.gov/item/52060000/";
const LOC_PDF_URLS = new Map(Array.from({ length: 5 }, (_, index) => {
  const volume = index + 1;
  return [volume, `https://tile.loc.gov/storage-services/service/rbc/rbc0001/2007/2007jeffcat${volume}/2007jeffcat${volume}.pdf`];
}));

function object(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function exactFields(value, fields) {
  return object(value) && Object.keys(value).sort().join("\u241f") === [...fields].sort().join("\u241f");
}

function text(value) {
  return typeof value === "string" ? value.trim() : "";
}

function integer(value, minimum = 0, maximum = Number.MAX_SAFE_INTEGER) {
  return Number.isInteger(value) && value >= minimum && value <= maximum;
}

function score(value) {
  return Number.isFinite(value) && value >= 0 && value <= 100;
}

export function safeLocUrl(value, { image = false } = {}) {
  try {
    const url = new URL(value);
    if (url.protocol !== "https:" || url.username || url.password || url.port || url.search || url.hash) return false;
    if (!image) return ["www.loc.gov", "tile.loc.gov"].includes(url.hostname);
    return url.hostname === "tile.loc.gov"
      && url.pathname.startsWith("/image-services/iiif/")
      && url.pathname.endsWith("/default.jpg");
  } catch (_) {
    return false;
  }
}

function validRegion(region) {
  if (!exactFields(region, REGION_FIELDS)) return false;
  const { x, y, width, height } = region;
  return [x, y, width, height].every(Number.isFinite)
    && x >= 0 && y >= 0 && width > 0 && height > 0
    && x + width <= 100.002 && y + height <= 100.002;
}

function validSnapshot(snapshot, terminalPage, volume) {
  if (!(exactFields(snapshot, SNAPSHOT_FIELDS)
    && integer(snapshot.pdf_page, 1, terminalPage)
    && validRegion(snapshot.region_pct)
    && safeLocUrl(snapshot.image_url, { image: true })
    && safeLocUrl(snapshot.full_page_image_url, { image: true })
    && integer(snapshot.line_count, 1, 10_000)
    && score(snapshot.mean_confidence))) return false;
  try {
    const image = new URL(snapshot.image_url);
    const fullPage = new URL(snapshot.full_page_image_url);
    const marker = `:2007jeffcat${volume}:`;
    const match = image.pathname.match(/\/pct:([^/]+)\/1000,\/0\/default\.jpg$/);
    if (!match || !image.pathname.includes(marker) || !fullPage.pathname.includes(marker)
      || !fullPage.pathname.endsWith("/full/pct:100/0/default.jpg")) return false;
    if (image.pathname.split("/pct:", 1)[0] !== fullPage.pathname.split("/full/", 1)[0]) return false;
    const coordinates = match[1].split(",").map(Number);
    const expected = [snapshot.region_pct.x, snapshot.region_pct.y, snapshot.region_pct.width, snapshot.region_pct.height];
    return coordinates.length === 4 && coordinates.every((value, index) => Number.isFinite(value) && Math.abs(value - expected[index]) <= 0.0006);
  } catch (_) {
    return false;
  }
}

function validEvent(context) {
  return exactFields(context, EVENT_FIELDS)
    && /^[a-z][a-z0-9-]{1,63}$/.test(text(context.event_id))
    && text(context.title) && text(context.date_label) && text(context.relationship)
    && score(context.context_score)
    && typeof context.direct_relation === "boolean"
    && ["not_established", "documented_interaction", "documented_excerpting", "documented_correspondence_context"].includes(context.event_use_status)
    && (context.use_confidence_score === null || score(context.use_confidence_score))
    && (!context.direct_relation ? context.event_use_status === "not_established" && context.use_confidence_score === null : true);
}

function validEntry(entry) {
  if (!exactFields(entry, ENTRY_FIELDS)) return false;
  const match = RECORD_ID.exec(text(entry.record_id));
  if (!match || Number(match[1]) !== entry.sowerby_number || !integer(entry.sowerby_number, 1, 4931)) return false;
  if (!["source_backed", "not_established"].includes(entry.title_status)
    || (entry.title_status === "source_backed" ? !text(entry.title) : Boolean(text(entry.title)))) return false;
  if (!text(entry.faculty) || !integer(entry.chapter_number, 1, 44) || !text(entry.chapter_label)
    || !integer(entry.volume, 1, 5) || !integer(entry.terminal_pdf_page, 1, 700) || !safeLocUrl(entry.pdf_url)) return false;
  const section = entry.section;
  if (!exactFields(section, SECTION_FIELDS)
    || section.type !== "sowerby_entry_block"
    || section.classification_status !== "machine_detected_unreviewed"
    || !text(section.transcript) || typeof section.transcript_truncated !== "boolean"
    || !integer(section.line_count, 1, 100_000)
    || !score(section.mean_confidence) || !score(section.marker_confidence) || !score(section.title_confidence)) return false;
  if (entry.pdf_url !== LOC_PDF_URLS.get(entry.volume)) return false;
  if (!Array.isArray(entry.snapshots) || !entry.snapshots.length || entry.snapshots.length > 3
    || entry.snapshots.some(snapshot => !validSnapshot(snapshot, entry.terminal_pdf_page, entry.volume))) return false;
  const snapshotPages = entry.snapshots.map(snapshot => snapshot.pdf_page);
  if (snapshotPages.some((page, index) => index && page <= snapshotPages[index - 1])) return false;
  if (!Array.isArray(entry.event_contexts) || !entry.event_contexts.length || entry.event_contexts.some(context => !validEvent(context))) return false;
  return new Set(entry.event_contexts.map(context => context.event_id)).size === entry.event_contexts.length;
}

export function validateOcrManifest(raw) {
  if (!exactFields(raw, ROOT_FIELDS)
    || raw.schema !== PRIVATE_OCR_SCHEMA
    || raw.collection_id !== "jefferson"
    || raw.corpus_id !== "historical"
    || raw.audience !== "authenticated_review"
    || !UTC.test(text(raw.generated_at))) {
    throw new Error("The authenticated OCR manifest has an invalid identity.");
  }
  if (!exactFields(raw.source, SOURCE_FIELDS)
    || raw.source.authority !== "Library of Congress"
    || raw.source.item_url !== LOC_ITEM_URL
    || raw.source.rights_statement_url !== LOC_ITEM_URL
    || !safeLocUrl(raw.source.item_url)
    || !safeLocUrl(raw.source.rights_statement_url)
    || raw.source.rights_clearance !== "not granted; item-level assessment remains required"
    || [raw.source.source_identity_sha256, raw.source.ocr_manifest_sha256, raw.source.historical_core_sha256, raw.source.insight_graph_sha256].some(value => !SHA256.test(text(value)))) {
    throw new Error("The authenticated OCR manifest has invalid source evidence.");
  }
  if (!exactFields(raw.methodology, METHOD_FIELDS) || METHOD_FIELDS.some(field => !text(raw.methodology[field]))) {
    throw new Error("The authenticated OCR methodology is incomplete.");
  }
  const coverage = raw.coverage;
  if (!exactFields(coverage, COVERAGE_FIELDS)
    || coverage.historical_entries !== 4928 || coverage.page_resolved_entries !== 4675
    || coverage.chapters !== 44 || coverage.entries_per_chapter !== 3
    || coverage.pilot_entries !== coverage.chapters * coverage.entries_per_chapter
    || !integer(coverage.section_regions, coverage.pilot_entries)
    || !integer(coverage.source_backed_titles, 0, coverage.pilot_entries)
    || coverage.direct_documentary_records !== 5) {
    throw new Error("The authenticated OCR coverage is inconsistent.");
  }
  if (!Array.isArray(raw.entries) || raw.entries.length !== coverage.pilot_entries || raw.entries.some(entry => !validEntry(entry))) {
    throw new Error("The authenticated OCR entry set is invalid.");
  }
  const ids = new Set(raw.entries.map(entry => entry.record_id));
  if (ids.size !== raw.entries.length) throw new Error("The authenticated OCR entry set contains duplicate records.");
  const chapterCounts = new Map();
  raw.entries.forEach(entry => chapterCounts.set(entry.chapter_number, (chapterCounts.get(entry.chapter_number) || 0) + 1));
  if (chapterCounts.size !== 44 || [...chapterCounts.values()].some(count => count !== 3)) {
    throw new Error("The authenticated OCR entry set does not cover every chapter equally.");
  }
  if (raw.entries.reduce((sum, entry) => sum + entry.snapshots.length, 0) !== coverage.section_regions
    || raw.entries.filter(entry => entry.title_status === "source_backed").length !== coverage.source_backed_titles
    || raw.entries.filter(entry => entry.event_contexts.some(context => context.direct_relation)).length !== coverage.direct_documentary_records) {
    throw new Error("The authenticated OCR counts do not reconcile.");
  }
  return {
    ...raw,
    entryById: new Map(raw.entries.map(entry => [entry.record_id, entry])),
  };
}
