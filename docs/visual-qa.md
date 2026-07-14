# ShelfSignals 2.0.0 visual QA

These images are produced by `scripts/browser_smoke_test.py --screenshot-dir docs/images` against a local static server after the browser assertions pass. The screenshots are presentation checks; the suite also exercises evidence, rights, routing, and compatibility behavior that is not fully visible in a single frame.

## Before: archived v1 at 1440 × 900

![Archived v1 interface before the primary-route migration](images/legacy-before.png)

## After: primary 2.0.0 at 1440 × 900

![Primary ShelfSignals 2.0.0 desktop interface](images/cinematic-desktop.png)

## Tablet: 1024 × 768

![Primary ShelfSignals 2.0.0 tablet interface](images/cinematic-tablet.png)

## Mobile: 390 × 844

![Primary ShelfSignals 2.0.0 mobile interface](images/cinematic-mobile.png)

## Verification checklist

- Featured titles, authors, dates, and call numbers resolve from the canonical-SHA-bound browser projection of `sekula_index.json`.
- First paint loads `catalog-core.json` once and does not request the 39 MB canonical catalog, full-field search, any detail shard, spine evidence, or provider-edition evidence.
- The first non-empty query loads `catalog-search.json` once; opening a record loads one deterministic detail shard and reopening it does not refetch that shard.
- Clearing an in-flight query cancels its search transfer; a failed search projection falls back to core fields and is not retried on each later keystroke.
- The sparse `cover_index.json` and universal **Cover not yet verified for this edition** state resolve without loading full provenance at first paint.
- Human-reviewed covers, unreviewed exact-ISBN provider references, and metadata-derived book objects remain visibly distinct; a failed remote image returns the hero, card, and open drawer to the exact unresolved label.
- Full cover provenance loads only when its corresponding record drawer opens.
- The compact spine contract loads only on first Physical view or detail; the 17 MB provider-edition manifest loads only from its explicit drawer control and remains optional.
- A rejected spine index renders visibly neutral unavailable placeholders, not ordinary book geometry, and the drawer remains fail-closed.
- Physical placement controls expose at least a 24 × 24 CSS-pixel target before expansion.
- Every catalog card and drawer exposes a source-backed placement badge or an explicit missing-placement state; selecting a badge filters to that exact normalized source label.
- Navigation and search remain readable over the dark editorial surface.
- No document-level horizontal overflow occurs at 390 px.
- The mobile collection browser renders two columns and the featured shelf remains horizontally browsable.
- The application renders 72 results initially rather than all 11,176 DOM elements.
- The `?journey=aerospace-folktales` direct route renders a sticky timeline, a rights-gated five-movement mosaic, five cited clusters, and four relationship shelves.
- All five rights-pending Sekula work images remain withheld. The separately licensed library-context image is labeled as context, directly links its CC BY-SA license, and is not presented as target-work imagery.
- The journey contains only its Clark catalog identity anchor and zero public associations; missing original placement is not invented.
- Direct `journey` + `cluster` links, reload, close, Browser Back/Forward, and scroll restoration preserve URL state. Existing `?path=` behavior remains unchanged.
- Detail, search, signal and placement filtering, exact Clark URL, My Shelf reload, reduced motion, and Legacy/Preview/Exhibit routes pass without console errors.

## Reproduce the checks

From the repository root, with Playwright and an installed Chrome/Chromium browser available:

```bash
python3 scripts/browser_smoke_test.py \
  --start-server \
  --browser-channel chrome \
  --screenshot-dir docs/images
```

Run the non-browser contracts separately:

```bash
python3 scripts/build_cover_index.py --self-test
python3 scripts/build_cover_index.py --check
python3 scripts/cover_source_pipeline.py self-test
python3 scripts/ingest_cleared_covers.py self-test
python3 scripts/ingest_cleared_covers.py encoder-self-test  # requires Pillow
python3 scripts/google_books_cover_source.py self-test
node scripts/build_browser_catalog.mjs --check
node --test scripts/browser_catalog_unit_tests.mjs scripts/cinematic_unit_tests.mjs scripts/phase_one_unit_tests.mjs scripts/spine_index_unit_tests.mjs scripts/review_unit_tests.mjs scripts/association_promotion_tests.mjs
node scripts/preview_acceptance_tests.mjs
```
