const MANIFEST_URL = "./data/collections/jefferson/media-authenticated.json";
const MANIFEST_SCHEMA = "shelfsignals-private-media-bundle@1";
const SAFE_ASSET_PATH = /^private\/jefferson\/display\/[a-f0-9]{64}\.jpg$/;
const SHA256 = /^sha256:[a-f0-9]{64}$/;

function textElement(tagName, className, text) {
  const element = document.createElement(tagName);
  if (className) element.className = className;
  element.textContent = String(text || "");
  return element;
}

function safeAssetUrl(path) {
  if (!SAFE_ASSET_PATH.test(String(path || ""))) return null;
  const resolved = new URL(`./${path}`, document.baseURI);
  return resolved.origin === location.origin ? resolved.href : null;
}

function validItem(item) {
  return item
    && typeof item === "object"
    && item.entity_type === "exhibition_context_photograph"
    && item.context_scope === "exhibition_context_only"
    && typeof item.id === "string"
    && typeof item.alt === "string" && item.alt.trim()
    && typeof item.caption === "string" && item.caption.trim()
    && safeAssetUrl(item.asset_path)
    && SHA256.test(String(item.sha256 || ""))
    && item.rights?.public_reuse === "not_granted";
}

function validateManifest(raw) {
  if (!raw
    || raw.schema !== MANIFEST_SCHEMA
    || raw.collection_id !== "jefferson"
    || raw.audience !== "authenticated_review"
    || raw.unit_of_count !== "exhibition context photograph"
    || !Array.isArray(raw.items)
    || raw.items.length !== 4
    || !raw.items.every(validItem)) {
    throw new Error("The authenticated photo manifest failed validation.");
  }
  if (new Set(raw.items.map(item => item.id)).size !== raw.items.length) {
    throw new Error("The authenticated photo manifest contains duplicate IDs.");
  }
  if (new Set(raw.items.map(item => item.asset_path)).size !== raw.items.length
    || new Set(raw.items.map(item => item.sha256)).size !== raw.items.length) {
    throw new Error("The authenticated photo manifest must contain four distinct image binaries.");
  }
  return raw;
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
    textElement("span", "private-photo-credit", `${item.creator} · ${item.captured_on}`)
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
    "Contributor photographs of the Library of Congress exhibition, shown as visual context only. They do not establish a book-level match, ownership status, or Jefferson’s historical shelf adjacency."
  );
  header.append(copy, note);

  const grid = document.createElement("div");
  grid.className = "private-photo-grid";
  grid.setAttribute("role", "list");
  manifest.items.forEach((item, index) => grid.append(photoCard(item, index)));

  const rights = textElement(
    "p",
    "private-photo-rights",
    "Authenticated review copy. Public reuse is not granted; downloading or screenshotting does not change the rights status."
  );
  section.append(header, grid, rights);
  anchor.insertAdjacentElement("afterend", section);
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

async function init() {
  document.documentElement.classList.add("authenticated-review-host");
  const reviewMarker = textElement("div", "authenticated-review-marker", "Authenticated review · private photographs");
  reviewMarker.setAttribute("role", "status");
  reviewMarker.setAttribute("aria-live", "polite");
  document.body.prepend(reviewMarker);
  if (defaultToJefferson()) return;
  if (new URL(location.href).searchParams.get("collection") !== "jefferson") return;
  const response = await fetch(MANIFEST_URL, {
    credentials: "same-origin",
    headers: { Accept: "application/json" },
    cache: "no-store"
  });
  if (!response.ok) throw new Error(`Authenticated photo manifest request failed (${response.status}).`);
  renderGallery(validateManifest(await response.json()));
}

init().catch(error => {
  console.error("ShelfSignals private review overlay failed:", error);
  const anchor = document.querySelector("#jeffersonOverview");
  if (!anchor) return;
  const status = textElement("p", "private-photo-error", "Authenticated field photographs could not be loaded.");
  status.setAttribute("role", "alert");
  anchor.insertAdjacentElement("afterend", status);
});
