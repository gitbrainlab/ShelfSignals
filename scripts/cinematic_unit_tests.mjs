import assert from "node:assert/strict";
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
  loadShelfIds,
  resolveShelfRecords,
  restoreShelfFromReceipt,
  saveShelfIds,
  toggleShelfId
} from "../docs/js/shelf.js";
import { parseSNumber } from "../docs/js/spatial.js";
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
const dataset = JSON.parse(await readFile(new URL("sekula_index.json", dataDirectory), "utf8"));
const featuredConfig = JSON.parse(await readFile(new URL("featured_items.json", dataDirectory), "utf8"));
const visualConfig = JSON.parse(await readFile(new URL("book_visuals.json", dataDirectory), "utf8"));
const physicalConfig = JSON.parse(await readFile(new URL("book_profiles.json", dataDirectory), "utf8"));
const rawById = new Map(dataset.map(record => [record.id, record]));

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
  assert.ok(malformed.searchText.includes("9780520270947"));
});

test("catalog search covers identifiers, call numbers, and collection notes", () => {
  const camera = enrichRecord(realRecord("alma991002311449708431"));
  assert.equal(camera.title, "U.S. Camera");

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
    group: "material",
    path: "labor-images",
    view: "spines"
  }, "https://example.test/ShelfSignals/?record=old&unrelated=kept#archive");

  assert.ok(serialized.startsWith("/ShelfSignals/?"));
  assert.ok(serialized.includes("unrelated=kept"));
  assert.ok(serialized.endsWith("#archive"));
  assert.deepEqual(parseUrlState(`https://example.test${serialized}`), {
    record: "alma991002293459708431",
    query: "Allan Sekula",
    signals: ["image", "labor"],
    signalMode: "all",
    lc: "NE",
    material: "book",
    decade: "1970",
    photo: "Strongly Likely",
    group: "material",
    path: "labor-images",
    view: "spines"
  });
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
