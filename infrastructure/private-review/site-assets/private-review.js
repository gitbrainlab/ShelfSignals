import { validateOcrManifest } from "./private-ocr-contract.js";

const PHOTO_MANIFEST_URL = "./data/collections/jefferson/media-authenticated.json";
const OCR_MANIFEST_URL = "./data/collections/jefferson/ocr-review.json";
const PHOTO_MANIFEST_SCHEMA = "shelfsignals-private-media-bundle@1";
const SAFE_ASSET_PATH = /^private\/jefferson\/display\/[a-f0-9]{64}\.jpg$/;
const SHA256 = /^sha256:[a-f0-9]{64}$/;
const PHOTO_ROOT_FIELDS = ["schema", "collection_id", "audience", "generated_at", "unit_of_count", "security_notice", "items"];
const PHOTO_ITEM_FIELDS = ["id", "entity_type", "context_scope", "asset_path", "thumbnail_path", "mime_type", "bytes", "sha256", "width", "height", "alt", "caption", "captured_on", "creator", "rights", "evidence"];
const PHOTO_RIGHTS_FIELDS = ["status", "public_reuse", "credit_line"];
const PHOTO_EVIDENCE_FIELDS = ["source", "book_level_matches", "chapter_labels"];
const PHOTO_SECURITY_NOTICE = "This manifest requires gateway authentication. Possession of this bundle is not access control or public-reuse permission.";
const RESULT_LIMIT = 18;

let ocrManifest = null;

function exactFields(value, fields) {
  return value && typeof value === "object" && !Array.isArray(value)
    && Object.keys(value).sort().join("\u241f") === [...fields].sort().join("\u241f");
}

function textElement(tagName, className, text) {
  const element = document.createElement(tagName);
  if (className) element.className = className;
  element.textContent = String(text ?? "");
  return element;
}

function safeAssetUrl(path) {
  if (!SAFE_ASSET_PATH.test(String(path || ""))) return null;
  const resolved = new URL(`./${path}`, document.baseURI);
  return resolved.origin === location.origin ? resolved.href : null;
}

function validPhoto(item) {
  const pathHash = typeof item?.asset_path === "string" ? item.asset_path.match(/^private\/jefferson\/display\/([a-f0-9]{64})\.jpg$/)?.[1] : null;
  return exactFields(item, PHOTO_ITEM_FIELDS)
    && /^jefferson-exhibition-0[1-4]$/.test(item.id)
    && item.entity_type === "exhibition_context_photograph"
    && item.context_scope === "exhibition_context_only"
    && typeof item.alt === "string" && item.alt.trim()
    && typeof item.caption === "string" && item.caption.trim()
    && safeAssetUrl(item.asset_path)
    && item.thumbnail_path === item.asset_path
    && item.mime_type === "image/jpeg"
    && Number.isInteger(item.bytes) && item.bytes > 0 && item.bytes <= 50 * 1024 * 1024
    && Number.isInteger(item.width) && item.width > 0 && item.width <= 16384
    && Number.isInteger(item.height) && item.height > 0 && item.height <= 16384
    && /^\d{4}-\d{2}-\d{2}$/.test(item.captured_on)
    && typeof item.creator === "string" && item.creator.trim()
    && SHA256.test(String(item.sha256 || ""))
    && pathHash === item.sha256.slice(7)
    && exactFields(item.rights, PHOTO_RIGHTS_FIELDS)
    && item.rights.status === "contributor_authorized_private_review"
    && item.rights.public_reuse === "not_granted"
    && item.rights.credit_line === item.creator
    && exactFields(item.evidence, PHOTO_EVIDENCE_FIELDS)
    && item.evidence.source === "project_contributor_upload"
    && item.evidence.book_level_matches === "not_established"
    && item.evidence.chapter_labels === "visible_in_photograph_only";
}

function validatePhotoManifest(raw) {
  if (!exactFields(raw, PHOTO_ROOT_FIELDS)
    || raw.schema !== PHOTO_MANIFEST_SCHEMA
    || raw.collection_id !== "jefferson"
    || raw.audience !== "authenticated_review"
    || !/^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/.test(raw.generated_at)
    || raw.unit_of_count !== "exhibition context photograph"
    || raw.security_notice !== PHOTO_SECURITY_NOTICE
    || !Array.isArray(raw.items)
    || raw.items.length !== 4
    || !raw.items.every(validPhoto)) {
    throw new Error("The authenticated photo manifest failed validation.");
  }
  if (new Set(raw.items.map(item => item.id)).size !== raw.items.length
    || new Set(raw.items.map(item => item.asset_path)).size !== raw.items.length
    || new Set(raw.items.map(item => item.sha256)).size !== raw.items.length) {
    throw new Error("The authenticated photo manifest contains duplicate evidence.");
  }
  return raw;
}

async function fetchJson(path) {
  const response = await fetch(path, {
    credentials: "same-origin",
    headers: { Accept: "application/json" },
    cache: "no-store",
  });
  if (!response.ok) throw new Error(`Authenticated manifest request failed (${response.status}).`);
  return response.json();
}

function photoCard(item, index) {
  const figure = document.createElement("figure");
  figure.className = "private-photo-card";
  figure.dataset.privatePhotoId = item.id;
  figure.setAttribute("role", "listitem");

  const image = document.createElement("img");
  image.src = safeAssetUrl(item.asset_path);
  image.alt = item.alt;
  image.loading = index === 0 ? "eager" : "lazy";
  image.decoding = "async";
  image.width = Number(item.width) || 1280;
  image.height = Number(item.height) || 960;

  const caption = document.createElement("figcaption");
  caption.append(
    textElement("strong", "private-photo-number", String(index + 1).padStart(2, "0")),
    textElement("span", "private-photo-caption", item.caption),
    textElement("span", "private-photo-credit", `${item.creator} · ${item.captured_on}`),
  );
  figure.append(image, caption);
  return figure;
}

function renderGallery(manifest) {
  const anchor = document.querySelector("#jeffersonOverview");
  if (!anchor) throw new Error("The Jefferson overview anchor is unavailable.");

  const section = document.createElement("section");
  section.className = "private-photo-section";
  section.id = "jeffersonFieldNotes";
  section.setAttribute("aria-labelledby", "jeffersonFieldNotesTitle");

  const header = document.createElement("header");
  header.className = "private-photo-header";
  const copy = document.createElement("div");
  const heading = textElement("h2", "", "Inside the reconstructed library");
  heading.id = "jeffersonFieldNotesTitle";
  copy.append(textElement("p", "section-index", "Authenticated field notes · 01"), heading);
  const note = textElement(
    "p",
    "private-photo-scope",
    "Contributor photographs of the Library of Congress exhibition, shown as visual context only. They do not establish a book-level match, ownership status, or Jefferson’s historical shelf adjacency.",
  );
  header.append(copy, note);

  const grid = document.createElement("div");
  grid.className = "private-photo-grid";
  grid.setAttribute("role", "list");
  manifest.items.forEach((item, index) => grid.append(photoCard(item, index)));

  const rights = textElement(
    "p",
    "private-photo-rights",
    "Authenticated review copy. Public reuse is not granted; downloading or screenshotting does not change the rights status.",
  );
  section.append(header, grid, rights);
  anchor.insertAdjacentElement("afterend", section);
  return section;
}

function recordUrl(recordId) {
  const url = new URL(location.href);
  url.searchParams.set("collection", "jefferson");
  url.searchParams.set("corpus", "historical");
  url.searchParams.set("order", "sowerby");
  url.searchParams.set("record", recordId);
  url.hash = "collection";
  return `${url.pathname}${url.search}${url.hash}`;
}

function eventPill(context) {
  const label = context.direct_relation
    ? `${context.title} · documentary ${context.context_score}/100`
    : `${context.title} · context ${context.context_score}/100`;
  return textElement("span", context.direct_relation ? "ocr-event direct" : "ocr-event", label);
}

function ocrResult(entry) {
  const article = document.createElement("article");
  article.className = "ocr-result";
  const title = entry.title || `Sowerby entry ${entry.sowerby_number} · title not established`;
  article.append(
    textElement("p", "ocr-result-kicker", `${entry.faculty} · Chapter ${entry.chapter_number}, ${entry.chapter_label}`),
    textElement("h3", "", title),
    textElement("p", "ocr-result-excerpt", entry.section.transcript.slice(0, 330) + (entry.section.transcript.length > 330 ? "…" : "")),
  );
  const events = document.createElement("div");
  events.className = "ocr-event-list";
  entry.event_contexts.slice(0, 3).forEach(context => events.append(eventPill(context)));
  const link = textElement("a", "ocr-open-record", "Open entry and source snapshots →");
  link.href = recordUrl(entry.record_id);
  article.append(events, link);
  return article;
}

function renderOcrLab(manifest, after) {
  const section = document.createElement("section");
  section.className = "private-ocr-lab";
  section.id = "jeffersonOcrLab";
  section.setAttribute("aria-labelledby", "jeffersonOcrLabTitle");

  const heading = textElement("h2", "", "Read the catalogue through its evidence");
  heading.id = "jeffersonOcrLabTitle";
  const coverage = manifest.coverage;
  const introduction = textElement(
    "p",
    "private-ocr-introduction",
    `${coverage.pilot_entries} machine-readable entry blocks—three from each of 44 chapters—are indexed here with ${coverage.section_regions} direct LOC image regions. Open a result to compare OCR, visual source, and life-event context inline.`,
  );
  const caveat = textElement(
    "p",
    "private-ocr-caveat",
    "Pilot evidence only. Machine OCR may be wrong; a Sowerby entry may include bibliographic description, editorial annotation, references, or copy notes. Context scores are not probabilities of reading or influence.",
  );

  const controls = document.createElement("form");
  controls.className = "private-ocr-controls";
  controls.setAttribute("role", "search");
  controls.addEventListener("submit", event => event.preventDefault());
  const searchLabel = textElement("label", "", "Search OCR, titles, chapters, and events");
  searchLabel.htmlFor = "privateOcrSearch";
  const search = document.createElement("input");
  search.id = "privateOcrSearch";
  search.type = "search";
  search.placeholder = "Try Tacitus, architecture, correspondence…";
  search.autocomplete = "off";
  const chapterLabel = textElement("label", "", "Chapter");
  chapterLabel.htmlFor = "privateOcrChapter";
  const chapter = document.createElement("select");
  chapter.id = "privateOcrChapter";
  chapter.append(new Option("All 44 chapters", ""));
  const chapters = new Map();
  manifest.entries.forEach(entry => chapters.set(entry.chapter_number, entry.chapter_label));
  [...chapters].sort((left, right) => left[0] - right[0]).forEach(([number, label]) => chapter.append(new Option(`${number}. ${label}`, String(number))));
  controls.append(searchLabel, search, chapterLabel, chapter);

  const status = textElement("p", "private-ocr-status", "");
  status.setAttribute("role", "status");
  status.setAttribute("aria-live", "polite");
  const results = document.createElement("div");
  results.className = "private-ocr-results";

  const update = () => {
    const query = search.value.trim().toLocaleLowerCase();
    const chapterNumber = Number(chapter.value || 0);
    const filtered = manifest.entries.filter(entry => {
      if (chapterNumber && entry.chapter_number !== chapterNumber) return false;
      if (!query) return true;
      const haystack = [
        entry.title,
        entry.faculty,
        entry.chapter_label,
        entry.section.transcript,
        ...entry.event_contexts.flatMap(context => [context.title, context.relationship]),
      ].join(" ").toLocaleLowerCase();
      return haystack.includes(query);
    });
    results.replaceChildren(...filtered.slice(0, RESULT_LIMIT).map(ocrResult));
    status.textContent = `${filtered.length} pilot entr${filtered.length === 1 ? "y" : "ies"}${filtered.length > RESULT_LIMIT ? ` · showing first ${RESULT_LIMIT}` : ""}`;
    if (!filtered.length) results.append(textElement("p", "private-ocr-empty", "No pilot entry matches this search. The full 4,928-entry corpus remains available in the historical browser."));
  };
  search.addEventListener("input", update);
  chapter.addEventListener("change", update);
  update();

  section.append(textElement("p", "section-index", "Authenticated evidence lab · 02"), heading, introduction, caveat, controls, status, results);
  after.insertAdjacentElement("afterend", section);
}

function confidenceLabel(value) {
  return Number.isFinite(value) ? `${Math.round(value)}%` : "not established";
}

function sourceSnapshot(snapshot, entry, index) {
  const figure = document.createElement("figure");
  figure.className = "ocr-source-snapshot";
  const link = document.createElement("a");
  link.href = snapshot.full_page_image_url;
  link.target = "_blank";
  link.rel = "noopener noreferrer";
  link.setAttribute("aria-label", `Open the full LOC scan page ${snapshot.pdf_page}`);
  const image = document.createElement("img");
  image.src = snapshot.image_url;
  image.alt = `LOC scan region for Sowerby entry ${entry.sowerby_number}, volume ${entry.volume}, PDF page ${snapshot.pdf_page}`;
  image.loading = "lazy";
  image.decoding = "async";
  link.append(image);
  const caption = document.createElement("figcaption");
  caption.append(
    textElement("strong", "", `Source region ${index + 1}`),
    textElement("span", "", `Volume ${entry.volume} · PDF page ${snapshot.pdf_page} · ${snapshot.line_count} OCR lines · mean OCR ${confidenceLabel(snapshot.mean_confidence)}`),
  );
  figure.append(link, caption);
  return figure;
}

function ensureOcrDrawerSection() {
  let section = document.querySelector("#privateOcrEvidence");
  if (section) return section;
  section = document.createElement("section");
  section.className = "detail-section private-ocr-evidence";
  section.id = "privateOcrEvidence";
  section.hidden = true;
  const anchor = document.querySelector("#detailInsights");
  if (!anchor) throw new Error("The detail evidence anchor is unavailable.");
  anchor.insertAdjacentElement("afterend", section);
  return section;
}

function renderOcrDrawer() {
  const section = ensureOcrDrawerSection();
  const recordId = new URL(location.href).searchParams.get("record") || "";
  const entry = ocrManifest?.entryById.get(recordId);
  section.replaceChildren();
  section.hidden = !entry;
  if (!entry) return;

  const heading = textElement("h3", "", "Source OCR and visual evidence");
  const status = textElement(
    "p",
    "ocr-evidence-status",
    `Machine-detected Sowerby entry block · mean OCR ${confidenceLabel(entry.section.mean_confidence)} · marker ${confidenceLabel(entry.section.marker_confidence)} · not yet human reviewed`,
  );
  const snapshots = document.createElement("div");
  snapshots.className = "ocr-source-grid";
  entry.snapshots.forEach((snapshot, index) => snapshots.append(sourceSnapshot(snapshot, entry, index)));

  const excerpt = textElement("blockquote", "ocr-inline-transcript", entry.section.transcript.slice(0, 900) + (entry.section.transcript.length > 900 ? "…" : ""));
  const transcript = document.createElement("details");
  transcript.className = "ocr-full-transcript";
  transcript.append(textElement("summary", "", `Read complete machine transcript · ${entry.section.line_count} lines`));
  transcript.append(textElement("pre", "", entry.section.transcript));

  const contexts = document.createElement("div");
  contexts.className = "ocr-drawer-contexts";
  contexts.append(textElement("h4", "", "Graph connections carried into this review"));
  entry.event_contexts.forEach(context => contexts.append(eventPill(context)));

  const source = textElement("a", "ocr-source-link", "Open the official LOC volume at this PDF page ↗");
  source.href = `${entry.pdf_url}#page=${entry.terminal_pdf_page}`;
  source.target = "_blank";
  source.rel = "noopener noreferrer";
  const rights = textElement(
    "p",
    "ocr-rights-note",
    `${ocrManifest.source.rights_clearance}. This authenticated demonstration does not grant reuse permission.`,
  );
  section.append(heading, status, snapshots, excerpt, transcript, contexts, source, rights);
}

function observeDrawer() {
  const title = document.querySelector("#detailTitle");
  const drawer = document.querySelector("#detailDrawer");
  if (!title || !drawer) return;
  const observer = new MutationObserver(renderOcrDrawer);
  observer.observe(title, { childList: true, characterData: true, subtree: true });
  observer.observe(drawer, { attributes: true, attributeFilter: ["aria-hidden"] });
  window.addEventListener("popstate", renderOcrDrawer);
  renderOcrDrawer();
}

function hideStaticReviewerFriction() {
  const trigger = document.querySelector("#openReviewerMode");
  const banner = document.querySelector("#reviewerModeBanner");
  const dialog = document.querySelector("#reviewerDialog");
  if (trigger) trigger.hidden = true;
  if (banner) banner.hidden = true;
  if (dialog) dialog.remove();
}

function renderAuthenticatedMarker() {
  const marker = document.createElement("div");
  marker.className = "authenticated-review-marker";
  marker.setAttribute("role", "status");
  marker.setAttribute("aria-live", "polite");
  marker.append(textElement("span", "", "Authenticated review · private evidence demo"));
  const logout = textElement("a", "authenticated-review-logout", "End session");
  logout.href = "/cdn-cgi/access/logout";
  marker.append(logout);
  document.body.prepend(marker);
}

function defaultToJefferson() {
  const url = new URL(location.href);
  if (url.searchParams.has("collection")) return false;
  url.searchParams.set("collection", "jefferson");
  url.searchParams.set("corpus", "historical");
  url.searchParams.set("order", "sowerby");
  location.replace(`${url.pathname}${url.search}${url.hash}`);
  return true;
}

function renderLoadError(anchor, message) {
  if (!anchor) return;
  const status = textElement("p", "private-photo-error", message);
  status.setAttribute("role", "alert");
  anchor.insertAdjacentElement("afterend", status);
}

async function init() {
  document.documentElement.classList.add("authenticated-review-host");
  hideStaticReviewerFriction();
  renderAuthenticatedMarker();
  if (defaultToJefferson()) return;
  if (new URL(location.href).searchParams.get("collection") !== "jefferson") return;

  const anchor = document.querySelector("#jeffersonOverview");
  const [photoResult, ocrResult] = await Promise.allSettled([
    fetchJson(PHOTO_MANIFEST_URL).then(validatePhotoManifest),
    fetchJson(OCR_MANIFEST_URL).then(validateOcrManifest),
  ]);
  let insertionAnchor = anchor;
  if (photoResult.status === "fulfilled") insertionAnchor = renderGallery(photoResult.value);
  else {
    console.error("Shelf Signals private photograph layer failed:", photoResult.reason);
    renderLoadError(anchor, "Authenticated field photographs could not be loaded.");
  }
  if (ocrResult.status === "fulfilled") {
    ocrManifest = ocrResult.value;
    renderOcrLab(ocrManifest, insertionAnchor || anchor);
    observeDrawer();
  } else {
    console.error("Shelf Signals private OCR layer failed:", ocrResult.reason);
    renderLoadError(insertionAnchor || anchor, "Authenticated OCR evidence could not be loaded.");
  }
}

init().catch(error => {
  console.error("Shelf Signals private review overlay failed:", error);
  renderLoadError(document.querySelector("#jeffersonOverview"), "The authenticated review overlay could not be loaded.");
});
