# Edition metadata enrichment

ShelfSignals can augment a rendered book spine with edition-level evidence from the official Open Library monthly Editions dump. This is a background enhancement: the primary interface renders immediately from the Clark catalog, then adopts validated external fields when the compact manifest becomes available.

## Evidence boundary

Clark catalog facts always win. External values describe a provider edition matched to a catalog identifier; they do not describe the condition, wear, texture, or measurements of the individual Clark copy.

The browser and generator enforce these rules:

1. Normalize and checksum ISBN-10/13 values; normalize OCLC and LCCN control numbers.
2. Reject an OCLC/LCCN candidate when both sides also have nonempty but disjoint ISBN sets.
3. Resolve physical fields only from an exact ISBN match.
4. Suppress a field when exact-ISBN candidates disagree.
5. Fill only missing Clark fields. Never replace a catalog-stated height, width, extent, or binding.
6. Keep provider, edition ID, source URL, match method, matched ISBN, snapshot date, and dump checksum with every resolved claim.

The resulting manifest is `docs/data/book_editions.json`, with schema `shelfsignals-edition-enrichment@1`. It is intentionally separate from the primary catalog so an enrichment failure cannot prevent browsing.

## Source choice

[Open Library asks bulk users to use its monthly data dumps](https://openlibrary.org/data) instead of harvesting the Books API. Edition records may include physical format, physical dimensions, weight, pagination, page count, edition statement, publisher, language, classifications, cover IDs, and Internet Archive identifiers. The underlying metadata can come from several contributors, so ShelfSignals retains the provider record rather than presenting a field as independently verified.

Common Crawl was evaluated as a discovery layer, not a bibliographic authority. Its public index searches captured URLs rather than ISBN text inside every page, predictable ISBN URL probes produced negligible coverage, and original-site rights still apply. A future crawl-derived claim would need the exact ISBN in the captured payload plus the original URL, crawl ID, capture time, WARC location, raw value, and extraction version. Common Crawl data is not used in the current manifest.

No public bulk source reliably provides the actual spine surface or fore-edge of Clark's copy. That requires a local, scale-calibrated capture tied to the Alma MMS ID. Provider cover pixels may inform a clearly synthetic palette, but they are not evidence of cloth, paper, embossing, wear, or copy-specific texture.

## Build from the official dump

Download the current Editions dump and retain the published checksum. The build is a sequential local scan and makes no per-book network requests:

```bash
python3 scripts/enrich_book_editions.py --self-test
python3 scripts/enrich_book_editions.py \
  --dump .cache/openlibrary/ol_dump_editions_2026-06-30.txt.gz \
  --expected-md5 4d949c666755d2d69bd6f44e292c6c07
node --test scripts/cinematic_unit_tests.mjs
```

The generator reads `docs/data/sekula_index.json`, streams the compressed dump, and atomically writes the browser manifest. It parses JSON only for rows sharing a normalized catalog identifier. Up to six deduplicated candidates are retained per record so every resolved field keeps its evidence while conflicts are evaluated across every candidate before truncation.

The source dump is deliberately ignored by Git. Only the derived, provenance-bearing manifest belongs in the repository.

## Committed snapshot coverage

The committed manifest was generated from the checksum-pinned 2026-06-30 Editions snapshot:

- 56,442,419 provider rows scanned locally;
- 9,073 of 11,176 ShelfSignals records have at least one safe exact-identifier candidate (81.2%);
- 7,530 of the 7,860 ISBN-bearing catalog records have exact-ISBN candidates (95.8%);
- 632 candidates with conflicting ISBN evidence were rejected;
- 1,810 records have a conflict-free, parseable three-axis edition specification;
- those specifications add 1,732 otherwise-missing front widths, 21 otherwise-missing heights, and 1,810 stated provider-edition depths;
- exact physical format adds 2,615 otherwise-missing binding terms and refines another 865 bounded depth models;
- the manifest is 17.1 MB uncompressed and approximately 2.5 MB with ordinary gzip transfer compression.

Open Library contains more raw claims than ShelfSignals applies. The build suppressed 355 conflicting dimension fields, 478 conflicting format fields, 344 conflicting weights, 1,711 conflicting page counts, and 1,149 conflicting pagination statements. A lower coverage number with intact evidence boundaries is preferable to silently selecting one disagreeing edition.

## Runtime behavior

The interface loads enrichment after the first complete render. A missing, malformed, stale, or unreachable manifest leaves the Clark-only interface intact. When enrichment arrives, cached physical profiles are invalidated and visible spines/detail evidence are refreshed.

Status language remains explicit:

- **Clark catalog** — transcribed catalog evidence;
- **Open Library edition** — exact-ISBN external edition evidence;
- **Modeled: Clark extent + external binding** — a bounded depth model using both sources;
- **Modeled from external edition extent** — a bounded fallback when Clark has no extent;
- **Unknown** — no defensible value.

The external dimensions convention is parsed conservatively and values outside book-like ranges are rejected. Clark-stated or locally measured depth would remain authoritative, but a conflict-free exact-ISBN provider thickness outranks the interface's generic page-count model. It can therefore control the synthetic side profile while remaining labeled as an external edition specification.

## Higher-confidence next source

Publisher or distributor ONIX feeds are the strongest next step because ONIX can carry shelf height, cover width, spine thickness, weight, binding, and dedicated spine imagery. Those feeds are licensed rather than a public universal database; image display, caching, and redistribution must follow the feed agreement. A Clark capture program remains the only route to copy-specific texture and side-profile evidence.
