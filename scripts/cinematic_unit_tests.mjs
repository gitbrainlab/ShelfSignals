import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  enrichRecord,
  filterRecords,
  groupRecords,
  parseUrlState,
  recordMatchesSignals,
  serializeUrlState
} from "../docs/js/catalog.js";
import {
  groupPlacementsByRoom,
  normalizePlacementKey,
  parsePhysicalIdentifiers,
  recordMatchesPlacement,
  roomForPlacement
} from "../docs/js/placement.js";
import {
  loadShelfIds,
  resolveShelfRecords,
  restoreShelfFromReceipt,
  saveShelfIds,
  toggleShelfId
} from "../docs/js/shelf.js";
import { parseSNumber } from "../docs/js/spatial.js";
import { createReceipt } from "../docs/js/receipt.js";
import {
  PHYSICAL_MANIFEST_SCHEMA,
  estimateBookThickness,
  getRecordPhysicalProfile,
  parseCatalogBinding,
  parseCatalogDimensions,
  parseCatalogExtent,
  parsePhysicalDescription,
  parsePhysicalManifest,
  profileFromRecord
} from "../docs/js/physical.js";
import {
  EDITION_ENRICHMENT_SCHEMA,
  canonicalEditionIsbn,
  getRecordEditionEnrichment,
  mergeEditionPhysicalProfile,
  normalizeEditionLccn,
  normalizeEditionOclc,
  parseOpenLibraryDimensions,
  parseEditionEnrichmentManifest,
  parseEditionEnrichmentManifestAsync
} from "../docs/js/enrichment.js";
import {
  VISUAL_MANIFEST_SCHEMA,
  bookStyleProperties,
  deterministicBookColors,
  getRecordVisual,
  isAllowedCoverUrl,
  normalizeIsbn,
  normalizeLccn,
  normalizeOclc,
  parsePhysicalHeight,
  parseVisualManifest,
  physicalBookHeight,
  resolveFeaturedItems
} from "../docs/js/visuals.js";

const scriptsDirectory = new URL("./", import.meta.url);
const dataDirectory = new URL("../docs/data/", scriptsDirectory);
const datasetText = await readFile(new URL("sekula_index.json", dataDirectory), "utf8");
const dataset = JSON.parse(datasetText);
const featuredConfig = JSON.parse(await readFile(new URL("featured_items.json", dataDirectory), "utf8"));
const visualConfig = JSON.parse(await readFile(new URL("book_visuals.json", dataDirectory), "utf8"));
const physicalConfig = JSON.parse(await readFile(new URL("book_profiles.json", dataDirectory), "utf8"));
let editionConfig = null;
try {
  editionConfig = JSON.parse(await readFile(new URL("book_editions.json", dataDirectory), "utf8"));
} catch (error) {
  if (error?.code !== "ENOENT") throw error;
}
const rawById = new Map(dataset.map(record => [record.id, record]));

const FIXTURE_ISBN = "9780374226268";

function editionSource(recordCount = 1) {
  return {
    catalog: "Clark Library Catalog",
    provider: "Open Library",
    record_count: recordCount,
    dataset_sha256: `sha256:${"a".repeat(64)}`,
    provider_dump_checksum: `md5:${"b".repeat(32)}`
  };
}

function editionCandidate({
  sourceId = "OL1M",
  isbn = FIXTURE_ISBN,
  method = "isbn_exact",
  identifiers,
  edition = { physical_format: "Hardcover", number_of_pages: 207 },
  sourceUrl = `https://openlibrary.org/books/${sourceId}`
} = {}) {
  return {
    source_id: sourceId,
    source_url: sourceUrl,
    record_modified: "2026-06-30T00:00:00",
    match: {
      method,
      confidence: method === "isbn_exact" ? 1 : .95,
      identifiers: identifiers || [{ type: method.startsWith("isbn") ? "isbn" : method.startsWith("oclc") ? "oclc" : "lccn", value: isbn }]
    },
    edition
  };
}

function editionClaim(value, {
  sourceId = "OL1M",
  matchedIsbns = [FIXTURE_ISBN],
  provider = "openlibrary",
  method = "isbn_exact"
} = {}) {
  return {
    value,
    status: "external_edition_stated",
    provider,
    source_id: sourceId,
    source_url: `https://openlibrary.org/books/${sourceId}`,
    match_method: method,
    matched_isbns: matchedIsbns
  };
}

function editionFixture({
  recordId = "alma1",
  candidates = [editionCandidate()],
  resolved = {
    physical_format: editionClaim("Hardcover"),
    number_of_pages: editionClaim(207)
  },
  preferredSourceId = candidates[0]?.source_id
} = {}) {
  return {
    schema: EDITION_ENRICHMENT_SCHEMA,
    generated_at: "2026-07-13T00:00:00Z",
    source: editionSource(),
    summary: {},
    items: {
      [recordId]: {
        status: "resolved",
        preferred_source_id: preferredSourceId,
        resolved,
        candidates
      }
    }
  };
}

function realRecord(id) {
  const record = rawById.get(id);
  assert.ok(record, `expected real catalog record ${id}`);
  return record;
}

function relativeLuminance(color) {
  const channels = color.slice(1).match(/.{2}/g).map(value => Number.parseInt(value, 16) / 255)
    .map(value => value <= .04045 ? value / 12.92 : ((value + .055) / 1.055) ** 2.4);
  return .2126 * channels[0] + .7152 * channels[1] + .0722 * channels[2];
}

function colorContrast(left, right) {
  return (Math.max(relativeLuminance(left), relativeLuminance(right)) + .05)
    / (Math.min(relativeLuminance(left), relativeLuminance(right)) + .05);
}

class MemoryStorage {
  constructor() {
    this.values = new Map();
  }

  getItem(key) {
    return this.values.has(key) ? this.values.get(key) : null;
  }

  setItem(key, value) {
    this.values.set(key, String(value));
  }
}

test("normalizes supported catalog identifiers conservatively", () => {
  assert.equal(normalizeIsbn("978-0-520-27094-7"), "9780520270947");
  assert.equal(normalizeIsbn("0-89236-811-X"), "089236811X");
  assert.equal(normalizeIsbn("978-0-520"), "");
  assert.equal(normalizeIsbn("978-0-520-27094-8"), "", "invalid check digits must be rejected");

  assert.equal(normalizeOclc("(OCoLC)6103237"), "6103237");
  assert.equal(normalizeOclc("ocm00012345"), "12345");
  assert.equal(normalizeOclc("not an OCLC number"), "");

  assert.equal(normalizeLccn("LCCN  2001-123456"), "2001123456");
  assert.equal(normalizeLccn("  35-024291 "), "35024291");
});

test("rejects malformed manifests and admits only resolved, allowlisted images", () => {
  const rejected = parseVisualManifest({ schema: "unknown@1", items: {} });
  assert.equal(rejected.rejected, true);
  assert.deepEqual(rejected.items, {});

  const accepted = parseVisualManifest({
    schema: VISUAL_MANIFEST_SCHEMA,
    generated_at: "2026-07-12T00:00:00Z",
    items: {
      safe: {
        status: "resolved",
        image_url: "https://covers.openlibrary.org/b/isbn/9780520270947-L.jpg",
        thumbnail_url: "https://covers.openlibrary.org/b/isbn/9780520270947-M.jpg"
      },
      thumbnailOnly: {
        status: "resolved",
        thumbnail_url: "https://books.googleusercontent.com/books/content?id=verified"
      },
      failed: {
        status: "failed",
        image_url: "https://covers.openlibrary.org/b/isbn/0000000000-L.jpg"
      },
      unsafe: {
        status: "resolved",
        image_url: "https://images.example.test/plausible-but-unverified.jpg"
      }
    }
  });

  assert.equal(accepted.rejected, false);
  assert.deepEqual(Object.keys(accepted.items).sort(), ["safe", "thumbnailOnly"]);
  assert.equal(accepted.items.thumbnailOnly.image_url, accepted.items.thumbnailOnly.thumbnail_url);
  assert.equal(getRecordVisual({ id: "safe" }, accepted)?.status, "resolved");
  assert.equal(getRecordVisual({ id: "failed" }, accepted), null);
});

test("cover URL eligibility is safe after resolution failures", () => {
  assert.equal(isAllowedCoverUrl("https://covers.openlibrary.org/b/isbn/0374226261-M.jpg?default=false"), true);
  assert.equal(isAllowedCoverUrl("https://books.google.com/books/content?id=known"), true);
  assert.equal(isAllowedCoverUrl("http://covers.openlibrary.org/b/isbn/0374226261-M.jpg"), false);
  assert.equal(isAllowedCoverUrl("https://covers.openlibrary.org.evil.example/cover.jpg"), false);
  assert.equal(isAllowedCoverUrl("data:image/png;base64,AAAA"), false);
  assert.equal(isAllowedCoverUrl("not a URL"), false);

  const failed = parseVisualManifest({
    schema: VISUAL_MANIFEST_SCHEMA,
    items: {
      book: {
        status: "failed",
        image_url: "https://covers.openlibrary.org/b/isbn/0374226261-M.jpg"
      }
    }
  });
  assert.equal(getRecordVisual({ id: "book" }, failed), null, "failed lookups must fall back to a generated book");
});

test("generated book colors are deterministic and record-specific", () => {
  const aerospace = realRecord("alma991002293459708431");
  assert.equal(aerospace.title, "Aerospace folktales / Allan Sekula");

  const first = deterministicBookColors(aerospace);
  assert.deepEqual(first, deterministicBookColors({ ...aerospace }));
  assert.match(first.color, /^#[0-9a-f]{6}$/i);
  assert.match(first.light, /^#[0-9a-f]{6}$/i);
  assert.match(first.dark, /^#[0-9a-f]{6}$/i);
  assert.notDeepEqual(first, deterministicBookColors(realRecord("alma991002035079708431")));
  for (const record of dataset) {
    const colors = deterministicBookColors(record);
    assert.ok(colorContrast(colors.color, colors.ink) >= 4.5, `${record.id} generated spine ink must meet AA contrast`);
  }
});

test("placement parsing preserves source labels, finds every explicit placement, and groups rooms", () => {
  const placements = parsePhysicalIdentifiers({
    provenance_notes: [
      "Gift; Sekula Library Identifier: STUDY G",
      "Copy two; Sekula Library identifier: Study G; copy three; Sekula Library Identifier: Allan Studio Book Room Shelf D4, Front Bedroom F"
    ],
    sekula_notes: "Sekula Library Identifier: Garden Shed Drawer A, C, H, J"
  });

  assert.deepEqual(placements.map(placement => placement.label), [
    "STUDY G",
    "Allan Studio Book Room Shelf D4",
    "Front Bedroom F",
    "Garden Shed Drawer A, C, H, J"
  ]);
  assert.equal(placements[0].sources.length, 2, "case variants should dedupe without losing their source references");
  assert.equal(placements[0].key, "study g");
  assert.deepEqual(roomForPlacement(placements[1]), { key: "allan studio book room", label: "Allan Studio Book Room" });
  assert.deepEqual(groupPlacementsByRoom(placements).map(group => group.label), [
    "Study",
    "Allan Studio Book Room",
    "Front Bedroom",
    "Garden Shed"
  ]);
  assert.equal(normalizePlacementKey("  Front   Bedroom AB. "), "front bedroom ab");
  assert.equal(recordMatchesPlacement({ placements }, "study g"), true);
  assert.equal(recordMatchesPlacement({ placements }, "Study H"), false);
});

test("placement parsing applies only explicit audited catalog-tail corrections", () => {
  const ragged = parsePhysicalIdentifiers(realRecord("alma991002003019708431"));
  assert.deepEqual(ragged.map(placement => placement.label), ["Allan Studio Book Room Box A6"]);
  assert.equal(ragged[0].sources[0].sourceLabel, "Allan Studio Book Room Box A6 7102 Sterling and Francine Clark Art Institute. Library");
  assert.deepEqual(ragged[0].sources[0].warnings, ["audited_trailing_catalog_text_removed"]);

  const animation = parsePhysicalIdentifiers(realRecord("alma991002009929708431"));
  assert.deepEqual(animation.map(placement => placement.label), ["Allan Studio Book Room Box C5", "Bottom Front Column F"]);
  assert.equal(animation[0].sources[0].sourceLabel, "Allan Studio Book Room Box C5 5411 CAI copy 2");
});

test("enrichment tolerates malformed and scalar metadata", () => {
  const malformed = enrichRecord({
    id: 42,
    title: null,
    authors: "One creator",
    contributors: [null, "Second creator"],
    subjects: ["Photography", null, 17, "Photography"],
    notes: 99,
    provenance_notes: null,
    sekula_notes: { unexpected: true },
    formats: "1 volume ; 24 cm",
    isbns: 9780520270947,
    oclc_numbers: null,
    lccn: { number: 123 },
    call_number: 123,
    year: { approximate: 1999 },
    material_type: null,
    record_url: null
  });

  assert.equal(malformed.id, "42");
  assert.equal(malformed.title, "Untitled");
  assert.deepEqual(malformed.authors, ["One creator"]);
  assert.deepEqual(malformed.contributors, ["Second creator"]);
  assert.deepEqual(malformed.subjects, ["Photography", "17"]);
  assert.deepEqual(malformed.formats, ["1 volume ; 24 cm"]);
  assert.equal(malformed.lcClass, null);
  assert.equal(malformed.yearPrimary, null);
  assert.equal(malformed.catalogLink, "");
  assert.deepEqual(malformed.placements, []);
  assert.ok(malformed.searchText.includes("9780520270947"));
});

test("catalog search covers identifiers, call numbers, and collection notes", () => {
  const camera = enrichRecord(realRecord("alma991002311449708431"));
  assert.equal(camera.title, "U.S. Camera");
  assert.deepEqual(camera.placements.map(placement => placement.label), ["Front Bedroom AB", "Front Bedroom E"]);

  for (const query of [
    "alma991002311449708431",
    "6103237",
    "35024291",
    "NE2610 U7",
    "Front Bedroom AB"
  ]) {
    assert.deepEqual(filterRecords([camera], { query }).map(record => record.title), ["U.S. Camera"], `expected search match for ${query}`);
  }
  assert.deepEqual(filterRecords([camera], { query: "identifier that is absent" }), []);
  assert.deepEqual(filterRecords([camera], { placement: "front bedroom ab" }).map(record => record.title), ["U.S. Camera"]);
  assert.deepEqual(filterRecords([camera], { placement: "Garden Shed Shelf A1" }), []);
});

test("signal filters preserve strict any/all semantics", () => {
  const records = [
    { id: "both", signals: ["image", "labor"], searchText: "" },
    { id: "image", signals: ["image"], searchText: "" },
    { id: "labor", signals: ["labor"], searchText: "" },
    { id: "none", signals: [], searchText: "" }
  ];

  assert.deepEqual(filterRecords(records, { signals: ["image", "labor"], signalMode: "any" }).map(record => record.id), ["both", "image", "labor"]);
  assert.deepEqual(filterRecords(records, { signals: ["image", "labor"], signalMode: "all" }).map(record => record.id), ["both"]);
  assert.deepEqual(filterRecords(records, { signals: ["image", "missing"], signalMode: "all" }), []);
  assert.equal(recordMatchesSignals(records[3], [], "all"), true, "no selected signals must not exclude records");
});

test("LC groups are stable and keep real catalog titles", () => {
  const poseidon = enrichRecord(realRecord("alma991000988109708431"));
  const camera = enrichRecord(realRecord("alma991002311449708431"));
  assert.equal(poseidon.title, "Capturing Poseidon : photographic encounters with the sea / Daniel Finamore");
  assert.equal(camera.title, "U.S. Camera");

  const groups = groupRecords([
    camera,
    enrichRecord({ id: "unclassified", title: "Test-only unclassified record", call_number: "1234" }),
    poseidon
  ], "lc");

  assert.deepEqual(groups.map(group => group.label), ["LC N", "LC NE", "Other call numbers"]);
  assert.deepEqual(groups[0].items.map(record => record.title), [poseidon.title]);
  assert.deepEqual(groups[1].items.map(record => record.title), ["U.S. Camera"]);
});

test("featured records honor configured order, discard bad IDs, and fill deterministically", () => {
  const records = dataset.map(enrichRecord);
  const manifest = parseVisualManifest(visualConfig);
  const configured = resolveFeaturedItems(records, {
    hero: ["missing-record", featuredConfig.hero[0], featuredConfig.hero[0], featuredConfig.hero[1]]
  }, manifest, 4);

  assert.deepEqual(configured.slice(0, 2).map(record => record.title), [
    "Aerospace folktales / Allan Sekula",
    "Iron muse : photographing the Transcontinental Railroad / Glenn Willumson"
  ]);
  assert.equal(new Set(configured.map(record => record.id)).size, configured.length);
  assert.equal(configured.length, 4);

  const fallback = resolveFeaturedItems(records, {}, { items: {} }, 2);
  assert.deepEqual(fallback.map(record => record.title), ["U.S. Camera", "Dodge boats ; Marmon big eight"]);
});

test("shelf persistence normalizes IDs and receipt restore reports missing records", () => {
  const storage = new MemoryStorage();
  const ids = [
    "alma991002311449708431",
    { id: "alma991000988109708431" },
    "alma991002311449708431",
    null
  ];
  const saved = saveShelfIds(ids, storage);
  assert.deepEqual(saved, {
    ok: true,
    ids: ["alma991002311449708431", "alma991000988109708431"]
  });
  assert.deepEqual(loadShelfIds(storage), saved.ids);
  assert.deepEqual(toggleShelfId(saved.ids, "alma991002311449708431"), ["alma991000988109708431"]);

  const records = saved.ids.map(id => enrichRecord(realRecord(id)));
  assert.deepEqual(resolveShelfRecords([...saved.ids].reverse(), records).map(record => record.title), [
    "Capturing Poseidon : photographic encounters with the sea / Daniel Finamore",
    "U.S. Camera"
  ]);

  const restored = restoreShelfFromReceipt({
    schema: "shelfsignals-receipt@1",
    items: [{ id: saved.ids[0] }, "missing-record", saved.ids[1], saved.ids[0]]
  }, records);
  assert.equal(restored.valid, true);
  assert.deepEqual(restored.ids, saved.ids);
  assert.deepEqual(restored.missing, ["missing-record"]);
  assert.deepEqual(restoreShelfFromReceipt({ schema: "wrong", items: saved.ids }, records), { valid: false, ids: [], missing: [] });

  storage.setItem("shelfsignals_shelf", "not-json");
  assert.deepEqual(loadShelfIds(storage), []);
});

test("receipt export reuses the already-validated canonical hash without refetching 39 MB", async () => {
  const originalFetch = globalThis.fetch;
  let fetchCount = 0;
  globalThis.fetch = async () => {
    fetchCount += 1;
    throw new Error("dataset fetch should not occur");
  };
  try {
    const datasetHash = "a".repeat(64);
    const receipt = await createReceipt({
      items: [{ id: "alma1", title: "Real catalog title" }],
      datasetHash: `sha256:${datasetHash}`,
      datasetUrl: "https://example.invalid/large-catalog.json"
    });
    assert.equal(receipt.dataset.indexHash, datasetHash);
    assert.equal(fetchCount, 0);
  } finally {
    globalThis.fetch = originalFetch;
  }
});

test("URL state round-trips record deep links and browsing controls", () => {
  const serialized = serializeUrlState({
    record: "alma991002293459708431",
    query: "Allan Sekula",
    signals: ["image", "labor", "image"],
    signalMode: "all",
    lc: "NE",
    material: "book",
    decade: 1970,
    photo: "Strongly Likely",
    placement: "Front Bedroom AB",
    group: "material",
    path: "labor-images",
    journey: "aerospace-folktales",
    cluster: "domestic-interior",
    view: "spines"
  }, "https://example.test/ShelfSignals/?record=old&unrelated=kept#archive");

  assert.ok(serialized.startsWith("/ShelfSignals/?"));
  assert.ok(serialized.includes("unrelated=kept"));
  assert.ok(serialized.endsWith("#archive"));
  assert.deepEqual(parseUrlState(`https://example.test${serialized}`), {
    collection: "sekula",
    corpus: "",
    order: "",
    record: "alma991002293459708431",
    query: "Allan Sekula",
    signals: ["image", "labor"],
    signalMode: "all",
    lc: "NE",
    material: "book",
    decade: "1970",
    evidence: "",
    photo: "Strongly Likely",
    placement: "front bedroom ab",
    group: "material",
    path: "labor-images",
    journey: "aerospace-folktales",
    cluster: "domestic-interior",
    view: "spines"
  });
  assert.equal(parseUrlState("https://example.test/ShelfSignals/?path=labor-images").path, "labor-images", "legacy path links must remain unchanged");
  assert.equal(parseUrlState("https://example.test/ShelfSignals/?journey=aerospace-folktales").journey, "aerospace-folktales");
  assert.equal(serializeUrlState({ cluster: "orphan" }, "https://example.test/ShelfSignals/").includes("cluster="), false, "cluster state is valid only inside a journey");
});

test("physical height parsing follows catalog height-first dimensions", () => {
  const ironMuse = realRecord("alma991002035079708431");
  const seacoal = realRecord("alma991002036209708431");
  assert.equal(ironMuse.title, "Iron muse : photographing the Transcontinental Railroad / Glenn Willumson");
  assert.equal(parsePhysicalHeight(ironMuse.formats), 27);
  assert.equal(parsePhysicalHeight(seacoal.formats), 24, "24 x 28 cm should use the stated height dimension");
  assert.equal(parsePhysicalHeight("1 folded sheet ; 35 x 28 cm"), 35);
  assert.equal(parsePhysicalHeight("4 cm"), null);
  assert.equal(parsePhysicalHeight("101 cm"), null);
  assert.equal(parsePhysicalHeight("242 pages; no dimensions recorded"), null);
  assert.deepEqual(physicalBookHeight({ formats: [] }), { cm: null, ratio: 5 / 16 });
});

test("book geometry uses catalog profiles instead of record hashes", () => {
  const first = bookStyleProperties({ id: "first", formats: ["300 pages ; 24 x 28 cm"] });
  const second = bookStyleProperties({ id: "second", formats: ["300 pages ; 24 x 28 cm"] });
  assert.equal(first["--book-ratio"], String(28 / 24));
  assert.equal(first["--spine-width"], second["--spine-width"]);
  assert.equal(first["--hero-width"], second["--hero-width"]);
  assert.notEqual(first["--spine-width"], "22px", "a page extent should produce a non-neutral depth");

  const multiVolume = bookStyleProperties({ id: "set", formats: ["15 volumes ; 31-33 cm"] });
  assert.equal(multiVolume["--spine-width"], "22px", "ambiguous multi-volume depth should stay neutral");
  assert.equal(multiVolume["--book-height"], "470px", "catalog height ranges should use their midpoint");
});

test("exact cover analysis supplies optical palette and aspect only when catalog width is absent", () => {
  const visual = {
    aspect_ratio: .75,
    thumbnail_url: "https://covers.openlibrary.org/example.jpg",
    image_analysis: {
      aspect_ratio: .75,
      palette: [{ hex: "#21170f" }, { hex: "#d8c9a8" }],
      optical_metrics: { mean_luminance: .31, high_frequency_energy: .02 }
    }
  };
  const coverOnly = bookStyleProperties({ id: "cover", formats: ["224 pages ; 24 cm"] }, visual);
  assert.equal(coverOnly["--book-ratio"], "0.75");
  assert.equal(coverOnly["--book-color"], "#21170f");
  assert.equal(coverOnly["--book-light"], "#d8c9a8");
  const catalogWidth = bookStyleProperties({ id: "measured", formats: ["224 pages ; 24 x 20 cm"] }, visual);
  assert.equal(catalogWidth["--book-ratio"], String(20 / 24));

  for (const [recordId, committedVisual] of Object.entries(visualConfig.items)) {
    const record = realRecord(recordId);
    const style = bookStyleProperties(record, committedVisual);
    assert.ok(colorContrast(style["--book-color"], style["--book-ink"]) >= 4.5, `${recordId} cover-derived spine ink must meet AA contrast`);
  }
});

test("physical profiles preserve catalog H x W order, bounds, fractions, and folded size", () => {
  assert.deepEqual(parseCatalogDimensions("116 pages ; 24 x 28 cm"), {
    height_cm: 24,
    height_min_cm: 24,
    height_max_cm: 24,
    width_cm: 28,
    width_min_cm: 28,
    width_max_cm: 28,
    status: "stated",
    order: "height_x_width",
    presentation: "as_cataloged"
  });

  const ranged = parseCatalogDimensions("volumes : illustrations ; 31-33 cm");
  assert.deepEqual(
    { value: ranged.height_cm, minimum: ranged.height_min_cm, maximum: ranged.height_max_cm },
    { value: 32, minimum: 31, maximum: 33 }
  );
  assert.equal(parseCatalogDimensions("277 pages ; 25 x 31 1/2 cm").width_cm, 31.5);
  assert.equal(parseCatalogDimensions("498 pages ; 21 ½ cm").height_cm, 21.5);
  const varied = parseCatalogDimensions("4 cards ; 11 x 23 cm - 13 x 18 cm");
  assert.deepEqual(
    { height: varied.height_cm, heightBounds: [varied.height_min_cm, varied.height_max_cm], width: varied.width_cm, widthBounds: [varied.width_min_cm, varied.width_max_cm] },
    { height: 12, heightBounds: [11, 13], width: 20.5, widthBounds: [18, 23] }
  );

  const folded = parseCatalogDimensions("1 sheet ; 56 x 43 (folded to 28 x 22 cm) + disc ; 12 cm");
  assert.equal(folded.presentation, "folded");
  assert.deepEqual([folded.height_cm, folded.width_cm], [28, 22]);
  assert.deepEqual([folded.unfolded.height_cm, folded.unfolded.width_cm], [56, 43]);
  assert.equal(parseCatalogDimensions("191 pages ; 29 cm + pamphlet ; 28 x 11 cm").height_cm, 29);
  assert.equal(parseCatalogDimensions("263 pages : color illustrations + suppl. ; 30 cm +").height_cm, 30);
});

test("physical profiles separate stated extent and binding from estimated thickness", () => {
  const extent = parseCatalogExtent("xv, 619 pages, 14 unnumbered leaves of plates ; 21 cm");
  assert.deepEqual(extent, { status: "stated", pages: 634, leaves: 14 });
  assert.deepEqual(parseCatalogExtent("xvi, 1,323 pages"), { status: "stated", pages: 1339 });
  assert.equal(parseCatalogExtent("1,005 pages").pages, 1005);
  assert.equal(parseCatalogExtent("5 preliminary leaves, 13-299 pages").pages, 287);
  assert.deepEqual(parseCatalogBinding("1 accordion folded sheet (8 unnumbered pages) ; 14 cm"), {
    status: "stated",
    term: "accordion-folded"
  });
  assert.deepEqual(parseCatalogBinding("80 sheets in loose-leaf binder + 1 cassette"), {
    status: "stated",
    term: "loose-leaf-binder"
  });
  assert.equal(parseCatalogBinding("1 sheet, in a slipcase ; 26 cm").term, "slipcase");

  const thickness = estimateBookThickness(extent);
  assert.equal(thickness.status, "estimated");
  assert.equal(thickness.method, "catalog-extent-model-v1");
  assert.equal(thickness.basis_pages, 662);
  assert.ok(thickness.min_cm < thickness.value_cm && thickness.value_cm < thickness.max_cm);
  assert.equal(estimateBookThickness({ status: "stated", pages: 300, volumes: 2 }), null, "multi-volume side profiles are ambiguous");
  assert.equal(estimateBookThickness({ status: "stated", pages: 80 }, { status: "stated", term: "portfolio" }), null);
  assert.equal(parsePhysicalDescription("1 accordion folded sheet (8 unnumbered pages) ; 14 cm").thickness, undefined);
  assert.equal(parsePhysicalDescription("1 folded sheet (8 unnumbered pages) ; 27 x 18 cm").thickness, undefined);
  assert.equal(parsePhysicalDescription("242 pages; no dimensions recorded").thickness.status, "estimated");
});

test("physical manifest covers every real record and falls back safely", () => {
  const manifest = parsePhysicalManifest(physicalConfig);
  assert.equal(manifest.rejected, false);
  assert.equal(manifest.schema, PHYSICAL_MANIFEST_SCHEMA);
  assert.equal(manifest.source.catalog, "Clark Library Catalog");
  assert.equal(manifest.source.physical_description_field, "formats");
  assert.equal(Object.keys(manifest.items).length, dataset.length);
  assert.equal(manifest.summary.records, 11176);
  assert.equal(manifest.summary.dimensions_stated, 10956);
  assert.equal(manifest.summary.binding_or_housing_stated, 25);
  assert.equal(manifest.summary.thickness_estimated, 10006);
  assert.ok(dataset.every(record => Object.prototype.hasOwnProperty.call(manifest.items, record.id)));

  const camera = getRecordPhysicalProfile(realRecord("alma991002311449708431"), manifest);
  assert.deepEqual(
    { height: camera.dimensions.height_cm, min: camera.dimensions.height_min_cm, max: camera.dimensions.height_max_cm },
    { height: 32, min: 31, max: 33 }
  );
  assert.equal(camera.extent.volumes, 15);
  assert.equal(camera.thickness, undefined, "a range of journal volumes must not get one invented spine width");

  const fallbackRecord = { id: "not-in-manifest", formats: ["224 pages ; 18 cm ; paperback"] };
  assert.deepEqual(getRecordPhysicalProfile(fallbackRecord, manifest), profileFromRecord(fallbackRecord));
  assert.equal(getRecordPhysicalProfile(fallbackRecord, manifest).binding.term, "paperback");

  const rejected = parsePhysicalManifest({
    schema: PHYSICAL_MANIFEST_SCHEMA,
    source: { catalog: "unknown", dataset: "sekula_index.json", dataset_sha256: "sha256:bad", record_count: 1 },
    items: { unsafe: { status: "parsed", source_format: "300 pages ; 24 cm" } }
  });
  assert.equal(rejected.rejected, true);
  assert.deepEqual(rejected.items, {});
});

test("edition manifests reject untrusted sources and sanitize every candidate and claim", () => {
  for (const raw of [
    { ...editionFixture(), schema: "unknown@1" },
    { ...editionFixture(), source: { ...editionSource(), provider: "Common Crawl" } },
    { ...editionFixture(), source: { ...editionSource(), dataset_sha256: "sha256:not-a-digest" } }
  ]) {
    const rejected = parseEditionEnrichmentManifest(raw);
    assert.equal(rejected.rejected, true);
    assert.deepEqual(rejected.items, {});
  }

  const safe = editionCandidate({
    edition: {
      physical_format: "  Hardcover\n edition  ",
      number_of_pages: "207",
      publishers: ["Farrar, Straus and Giroux", "Farrar, Straus and Giroux", null],
      source_records: ["  marc:oclc:3223849 ", "marc:oclc:3223849", null],
      cover_ids: [123, 123, -1, "bad"],
      untrusted_field: "must not survive"
    }
  });
  const acceptedRaw = editionFixture({
    candidates: [
      safe,
      editionCandidate({ sourceId: "OL2M", sourceUrl: "https://openlibrary.org.evil.example/books/OL2M" }),
      editionCandidate({ sourceId: "../../escape" })
    ],
    preferredSourceId: "OL2M",
    resolved: {
      physical_format: editionClaim("Hardcover edition"),
      number_of_pages: editionClaim(999, { sourceId: "OL2M" }),
      description: editionClaim("not an allowlisted physical claim")
    }
  });
  acceptedRaw.items["unsafe-id"] = acceptedRaw.items.alma1;

  const accepted = parseEditionEnrichmentManifest(acceptedRaw);
  assert.equal(accepted.rejected, false);
  assert.deepEqual(Object.keys(accepted.items), ["alma1"]);
  assert.equal(accepted.items.alma1.preferred_source_id, "OL1M", "an invalid preferred candidate must fall back safely");
  assert.equal(accepted.items.alma1.candidates.length, 1);
  assert.deepEqual(accepted.items.alma1.candidates[0].edition, {
    physical_format: "Hardcover edition",
    number_of_pages: 207,
    publishers: ["Farrar, Straus and Giroux"],
    cover_ids: [123],
    source_records: ["marc:oclc:3223849"]
  });
  assert.deepEqual(Object.keys(accepted.items.alma1.resolved), ["physical_format"]);
});

test("async edition manifest validation yields per batch with synchronous parity", async () => {
  const fixture = editionFixture();
  fixture.items = Object.fromEntries(Array.from({ length: 7 }, (_, index) => [
    `alma${index + 1}`,
    structuredClone(fixture.items.alma1)
  ]));
  const yields = [];
  const asyncManifest = await parseEditionEnrichmentManifestAsync(fixture, {
    batchSize: 3,
    yieldControl: progress => { yields.push(progress); }
  });

  assert.deepEqual(asyncManifest, parseEditionEnrichmentManifest(fixture));
  assert.deepEqual(yields, [
    { batch: 1, processed: 3, total: 7 },
    { batch: 2, processed: 6, total: 7 },
    { batch: 3, processed: 7, total: 7 }
  ]);
});

test("Open Library dimensions require plausible complete three-axis measurements", () => {
  assert.deepEqual(parseOpenLibraryDimensions("8.5 x 5.4 x 0.5 inches"), {
    status: "parsed_external_edition",
    raw: "8.5 x 5.4 x 0.5 inches",
    order: "height_x_width_x_thickness",
    source_order: "height_x_depth_x_width",
    interpretation: "first_height_larger_remaining_width_smaller_remaining_thickness",
    unit: "in",
    height_cm: 21.59,
    width_cm: 13.72,
    thickness_cm: 1.27
  });
  for (const [raw, unit] of [["24 × 16 × 3 cm", "cm"], ["240 x 160 x 30 millimeters", "mm"]]) {
    const parsed = parseOpenLibraryDimensions(raw);
    assert.deepEqual(
      { unit: parsed.unit, height: parsed.height_cm, width: parsed.width_cm, thickness: parsed.thickness_cm },
      { unit, height: 24, width: 16, thickness: 3 }
    );
  }

  for (const unsafe of [
    "24 cm",
    "24 x 16 cm",
    "24 x 16 x 3",
    "20-24 x 16 x 3 cm",
    "24 cm x 16 cm x 3 cm",
    "4 x 3 x 1 cm",
    "101 x 16 x 3 cm",
    "24 x 16 x 14 cm"
  ]) {
    assert.equal(parseOpenLibraryDimensions(unsafe), null, `${unsafe} must remain on the catalog/model fallback`);
  }
});

test("edition evidence is revalidated against the current catalog record by match method", () => {
  assert.equal(canonicalEditionIsbn("0-374-22626-1"), FIXTURE_ISBN);
  assert.equal(canonicalEditionIsbn("978-0-374-22626-2"), "");
  assert.equal(normalizeEditionOclc("(OCoLC)0006103237"), "6103237");
  assert.equal(normalizeEditionLccn("LCCN 35-024291"), "35024291");

  const exact = editionCandidate({
    identifiers: [
      { type: "isbn", value: "0-374-22626-1" },
      { type: "oclc", value: "6103237" }
    ]
  });
  const oclc = editionCandidate({
    sourceId: "OL2M",
    method: "oclc_exact",
    identifiers: [{ type: "oclc", value: "6103237" }],
    edition: { edition_name: "OCLC corroboration only" }
  });
  const manifest = parseEditionEnrichmentManifest(editionFixture({
    candidates: [exact, oclc],
    resolved: {
      physical_format: editionClaim("Hardcover"),
      weight: editionClaim("1.2 kg", { matchedIsbns: ["9780520270947"] })
    }
  }));

  const exactRecord = getRecordEditionEnrichment({
    id: "alma1",
    isbns: ["0-374-22626-1"],
    oclc_numbers: ["(OCoLC)6103237"]
  }, manifest);
  assert.deepEqual(exactRecord.candidates.map(candidate => candidate.source_id), ["OL1M", "OL2M"]);
  assert.deepEqual(Object.keys(exactRecord.resolved), ["physical_format"], "a claim for another ISBN must not leak onto this record");

  const oclcOnly = getRecordEditionEnrichment({
    id: "alma1",
    isbns: ["9780520270947"],
    oclc_numbers: ["(OCoLC)6103237"]
  }, manifest);
  assert.deepEqual(oclcOnly.candidates.map(candidate => candidate.source_id), ["OL2M"], "an isbn_exact candidate cannot match solely through its incidental OCLC");
  assert.deepEqual(oclcOnly.resolved, {}, "OCLC-only evidence cannot drive physical geometry");
  assert.equal(oclcOnly.preferred.source_id, "OL2M");
  assert.equal(getRecordEditionEnrichment({ id: "alma1", isbns: [], oclc_numbers: [] }, manifest), null);
});

test("resolved edition claims reject source-value mismatches and exact-ISBN conflicts", () => {
  const hardcover = editionCandidate({ sourceId: "OL1M", edition: { physical_format: "Hardcover" } });
  const paperback = editionCandidate({ sourceId: "OL2M", edition: { physical_format: "Paperback" } });

  const mismatched = parseEditionEnrichmentManifest(editionFixture({
    candidates: [hardcover],
    resolved: { physical_format: editionClaim("Paperback") }
  }));
  assert.deepEqual(mismatched.items.alma1.resolved, {}, "a resolved value must be stated by its cited candidate");

  const wrongIsbn = parseEditionEnrichmentManifest(editionFixture({
    candidates: [hardcover],
    resolved: { physical_format: editionClaim("Hardcover", { matchedIsbns: ["9780520270947"] }) }
  }));
  assert.deepEqual(wrongIsbn.items.alma1.resolved, {}, "a resolved ISBN must occur in its cited exact-match evidence");

  const conflicted = parseEditionEnrichmentManifest(editionFixture({
    candidates: [hardcover, paperback],
    resolved: { physical_format: editionClaim("Hardcover") }
  }));
  assert.deepEqual(conflicted.items.alma1.resolved, {}, "disagreeing exact-ISBN editions must remain candidates rather than a resolved fact");
});

test("edition geometry fills gaps while Clark catalog facts remain authoritative", () => {
  const manifest = parseEditionEnrichmentManifest(editionFixture());
  const enrichment = getRecordEditionEnrichment({ id: "alma1", isbns: [FIXTURE_ISBN] }, manifest);

  const externalOnly = mergeEditionPhysicalProfile({ id: "alma1", isbns: [FIXTURE_ISBN], formats: [] }, enrichment);
  assert.equal(externalOnly.status, "enriched");
  assert.deepEqual(
    { status: externalOnly.binding.status, term: externalOnly.binding.term },
    { status: "external_edition_stated", term: "hardcover" }
  );
  assert.deepEqual(
    { status: externalOnly.extent.status, pages: externalOnly.extent.pages },
    { status: "external_edition_stated", pages: 207 }
  );
  assert.equal(externalOnly.thickness.status, "estimated_external");
  assert.equal(externalOnly.thickness.method, "external-edition-extent-model-v1");
  assert.equal(externalOnly.external_evidence.scope, "provider edition, not Clark copy");

  const catalogRecord = { id: "alma1", isbns: [FIXTURE_ISBN], formats: ["200 pages ; 24 x 18 cm ; paperback"] };
  const catalog = profileFromRecord(catalogRecord);
  const preserved = mergeEditionPhysicalProfile(catalogRecord, enrichment);
  assert.deepEqual(preserved.dimensions, catalog.dimensions);
  assert.deepEqual(preserved.extent, catalog.extent);
  assert.deepEqual(preserved.binding, catalog.binding);
  assert.deepEqual(preserved.thickness, catalog.thickness);
  assert.equal(preserved.external_evidence, undefined, "unused external facts must not be presented as evidence for Clark's copy");

  const extentRecord = { id: "alma1", isbns: [FIXTURE_ISBN], formats: ["300 pages ; 24 cm"] };
  const refined = mergeEditionPhysicalProfile(extentRecord, enrichment);
  assert.equal(refined.extent.status, "stated");
  assert.equal(refined.extent.pages, 300, "the Clark page extent must win over the provider edition");
  assert.equal(refined.binding.status, "external_edition_stated");
  assert.equal(refined.thickness.method, "catalog-extent-external-binding-model-v1");
  assert.equal(refined.thickness.evidence, "Clark extent + exact-ISBN Open Library physical format");
});

test("three-axis edition geometry merges per axis with explicit provenance", () => {
  const value = "24 x 16 x 3 cm";
  const manifest = parseEditionEnrichmentManifest(editionFixture({
    candidates: [editionCandidate({ edition: { physical_dimensions: value } })],
    resolved: { physical_dimensions: editionClaim(value) }
  }));
  const enrichment = getRecordEditionEnrichment({ id: "alma1", isbns: [FIXTURE_ISBN] }, manifest);

  const partialRecord = { id: "alma1", isbns: [FIXTURE_ISBN], formats: ["1 volume ; 25 cm"] };
  const partial = mergeEditionPhysicalProfile(partialRecord, enrichment);
  assert.equal(partial.dimensions.height_cm, 25, "the Clark height must not be replaced by a provider-edition height");
  assert.equal(partial.dimensions.provenance?.height_cm, undefined);
  assert.deepEqual(
    {
      width: partial.dimensions.width_cm,
      status: partial.dimensions.provenance.width_cm.status,
      source: partial.dimensions.provenance.width_cm.source_id,
      match: partial.dimensions.provenance.width_cm.match_method,
      scope: partial.dimensions.provenance.width_cm.scope
    },
    {
      width: 16,
      status: "external_edition_stated",
      source: "OL1M",
      match: "isbn_exact",
      scope: "provider edition, not Clark copy"
    }
  );
  assert.deepEqual(
    {
      value: partial.thickness.value_cm,
      status: partial.thickness.status,
      method: partial.thickness.method,
      source: partial.thickness.source_id
    },
    {
      value: 3,
      status: "external_edition_stated",
      method: "open-library-three-axis-dimensions-v1",
      source: "OL1M"
    }
  );

  const modeledRecord = { id: "alma1", isbns: [FIXTURE_ISBN], formats: ["300 pages ; 25 cm"] };
  const modeled = mergeEditionPhysicalProfile(modeledRecord, enrichment);
  assert.equal(modeled.dimensions.width_cm, 16, "the missing Clark width may be filled");
  assert.equal(modeled.thickness.value_cm, 3);
  assert.equal(modeled.thickness.status, "external_edition_stated", "exact-ISBN stated thickness should outrank a generic page-count model");
  assert.ok(modeled.external_evidence.fields.includes("thickness"));

  const completeRecord = { id: "alma1", isbns: [FIXTURE_ISBN], formats: ["300 pages ; 25 x 18 cm"] };
  const completeCatalog = profileFromRecord(completeRecord);
  const complete = mergeEditionPhysicalProfile(completeRecord, enrichment);
  assert.deepEqual(complete.dimensions, completeCatalog.dimensions);
  assert.equal(complete.thickness.value_cm, 3);
  assert.equal(complete.thickness.status, "external_edition_stated");
  assert.deepEqual(complete.external_evidence.fields, ["thickness"]);
});

test("generated edition enrichment preserves dataset-wide provenance invariants", {
  skip: editionConfig ? false : "docs/data/book_editions.json has not been generated yet"
}, () => {
  const manifest = parseEditionEnrichmentManifest(editionConfig);
  assert.equal(manifest.rejected, false);
  assert.equal(manifest.schema, EDITION_ENRICHMENT_SCHEMA);
  assert.equal(manifest.source.record_count, dataset.length);
  assert.equal(
    manifest.source.dataset_sha256,
    `sha256:${createHash("sha256").update(datasetText).digest("hex")}`,
    "the manifest must name the exact committed catalog input"
  );

  const rawItems = Object.entries(editionConfig.items);
  assert.equal(rawItems.length, editionConfig.summary.matched_records);
  assert.equal(Object.keys(manifest.items).length, rawItems.length, "generated evidence must survive client sanitization intact");
  const resolvedCounts = {};

  for (const [recordId] of rawItems) {
    const record = rawById.get(recordId);
    assert.ok(record, `${recordId} must exist in the Clark dataset`);
    const enrichment = getRecordEditionEnrichment(record, manifest);
    assert.ok(enrichment, `${recordId} must retain at least one exact record-identifier match`);

    const recordIdentifiers = {
      isbn: new Set((record.isbns || []).map(canonicalEditionIsbn).filter(Boolean)),
      oclc: new Set((record.oclc_numbers || []).map(normalizeEditionOclc).filter(Boolean)),
      lccn: new Set((record.lccn || []).map(normalizeEditionLccn).filter(Boolean))
    };
    for (const candidate of enrichment.candidates) {
      const identifiers = type => candidate.match.identifiers.filter(item => item.type === type).map(item => item.value);
      const requiredTypes = candidate.match.method === "isbn_exact"
        ? ["isbn"]
        : candidate.match.method === "oclc_lccn_exact"
          ? ["oclc", "lccn"]
          : [candidate.match.method.split("_", 1)[0]];
      for (const type of requiredTypes) {
        assert.ok(identifiers(type).some(value => recordIdentifiers[type].has(value)), `${recordId} ${candidate.source_id} must match its declared ${type} method`);
      }
    }

    for (const [field, claim] of Object.entries(enrichment.resolved)) {
      resolvedCounts[field] = (resolvedCounts[field] || 0) + 1;
      const source = enrichment.candidates.find(candidate => candidate.source_id === claim.source_id);
      assert.equal(source?.match.method, "isbn_exact", `${recordId} ${field} must cite exact ISBN evidence`);
      assert.ok(claim.matched_isbns.some(isbn => recordIdentifiers.isbn.has(isbn)), `${recordId} ${field} must match the Clark ISBN`);
      assert.ok(claim.matched_isbns.some(isbn => source.match.identifiers.some(identifier => identifier.type === "isbn" && identifier.value === isbn)), `${recordId} ${field} must cite an ISBN on its source candidate`);
      assert.deepEqual(claim.value, source.edition[field], `${recordId} ${field} must equal the cited source value`);
      const exactValues = enrichment.candidates
        .filter(candidate => candidate.match.method === "isbn_exact" && candidate.edition[field] != null && candidate.edition[field] !== "")
        .map(candidate => JSON.stringify(candidate.edition[field]));
      assert.equal(new Set(exactValues).size, 1, `${recordId} ${field} cannot resolve when exact-ISBN candidates conflict`);
    }
  }

  assert.deepEqual(
    Object.fromEntries(Object.entries(resolvedCounts).sort(([left], [right]) => left.localeCompare(right))),
    editionConfig.summary.resolved_fields
  );
});

test("S-number parsing excludes ordinary cutters and publication years", () => {
  assert.equal(parseSNumber("NE2698 .S4637L 02895"), 2895);
  assert.equal(parseSNumber("S-10422"), 10422);

  for (const callNumber of [
    "NE2610 .S65",
    "N734 .A8 1998",
    "HD8039.S42 U57 2007",
    "NE2698 .S4637 2005",
    "NE2698 .S4637L",
    "QA76.9 .S43 2024"
  ]) {
    assert.equal(parseSNumber(callNumber), null, `${callNumber} must not be treated as a physical S-number`);
  }
});
