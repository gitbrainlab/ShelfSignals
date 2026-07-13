# Physical book profiles

ShelfSignals renders a physical browsing mode from evidence already present in the Allan Sekula Library catalog. The interface distinguishes catalog facts from estimates and leaves unavailable measurements unknown.

## What is authoritative

The canonical source is each Clark Library catalog record's physical description. ShelfSignals parses the height-first convention in that field, including height × width, ranges, fractional measurements, folded dimensions, and accompanying-material clauses. It also records page, leaf, sheet, or volume extent and the small number of explicit binding terms.

The generated `docs/data/book_profiles.json` manifest covers all 11,176 records:

- 10,956 have a catalog-stated dimension;
- 10,566 have a catalog-stated extent;
- 25 state a binding or housing term;
- 10,006 support an explicitly labeled depth estimate;
- 61 contain no parseable physical profile.

The manifest is produced by `scripts/build_book_profiles.py`. The browser-side parser in `docs/js/physical.js` uses the same rules and has full 11,176-record parity with the generator.

## Depth is an estimate

Clark's records rarely state book-block thickness. When a book record gives pages or leaves, ShelfSignals calculates a bounded interface estimate from page-equivalent count plus a modest cover allowance. Folded sheets, portfolios, folders, housings, loose-leaf objects, and multi-volume sets are excluded. The result is labeled `Estimated from extent` everywhere it appears. It is not written back to the catalog and must not be described as a measured collection fact.

If extent is missing, multi-volume, or structurally unsuitable, the depth remains unknown and the interface uses a neutral fallback width. No record receives a random physical width. A conflict-free, exact-ISBN three-axis edition specification may replace the generic model, but it remains visibly labeled external provider-edition evidence rather than a measurement of the Clark copy.

## Cover-image optical analysis

For the small exact-ISBN cover sample, `scripts/analyze_cover_visuals.py` uses Pillow locally to measure the raster's actual aspect ratio, palette, luminance, contrast, entropy, frequency energy, and border variation. Those values help avoid a generic visual treatment. They describe pixels in a provider image, not material texture, condition, embossing, page edges, or the physical side of Clark's copy.

## External enrichment hierarchy

For future exact-edition enrichment, use identifiers rather than title similarity:

1. Clark/Alma physical description and local copy measurements;
2. exact ISBN edition data from the official [Open Library monthly Editions dump](https://openlibrary.org/data), whose records can include format, dimensions, weight, pagination, and page count;
3. licensed publisher/distributor ONIX data, whose product records can include shelf height, cover width, spine thickness, weight, binding, and spine imagery;
4. exact ISBN data from the [Google Books Volumes API](https://developers.google.com/books/docs/v1/reference/volumes), whose volume schema can include height, width, and thickness, used only within its live-API terms and project quota;
5. exact control-number MARC records using the Library of Congress [MARC 21 physical-description field](https://www.loc.gov/marc/bibliographic/bd300.html) and, where present, [physical-medium details](https://www.loc.gov/marc/bibliographic/bd340.html);
6. Internet Archive scans as evidence for front/back cover imagery, never as an assumed spine measurement.

Store source, identifier, match method, confidence, unit, and raw evidence with every enriched value. A title-only or similar-edition match must never become factual geometry.

Open Library explicitly directs collection-scale work to its monthly dumps. ShelfSignals therefore builds edition metadata locally without per-book API traffic. The matching, conflict, provenance, Common Crawl, and runtime rules are documented in [Edition metadata enrichment](./edition-enrichment.md). The cover analyzer remains limited to the 13 already verified exact-ISBN image references and keeps a local cache.

## What would provide a true side profile

No public bibliographic API can reliably show the actual spine, fore-edge, binding material, wear, or thickness of the specific Clark copy at collection scale. That requires a local capture program: a scale-calibrated front, spine, and fore-edge photograph (or a short photogrammetry turntable sequence) tied to the Alma record ID. The current interface is ready to accept exact thickness later while preserving the distinction between cataloged, externally sourced, estimated, and locally measured evidence.

## Regeneration and verification

From the repository root:

```bash
python3 scripts/build_book_profiles.py --self-test
python3 scripts/build_book_profiles.py
node --test scripts/cinematic_unit_tests.mjs
```

The generated manifest includes a schema version, source dataset checksum, record count, summary totals, and the original catalog physical description used for each profile. The production browser reparses only the records it renders instead of loading the full manifest at startup; generator/browser parity is covered by the test suite.
