# ShelfSignals interfaces

ShelfSignals `2.0.0` makes the GitHub Pages root the canonical Allan Sekula Library browser. Earlier interfaces remain available at explicit compatibility routes; none of the routes redirect to one another.

## Route map

| Route | File | Status | Purpose |
|---|---|---|---|
| `/ShelfSignals/` | `docs/index.html` | Primary, `2.0.0` | Cinematic entry, full catalog browser, details, filters, and My Shelf |
| `/ShelfSignals/legacy/` | `docs/legacy/index.html` | Archived | Preserved v1 interface with known large-DOM performance limitations |
| `/ShelfSignals/preview/` | `docs/preview/index.html` | Compatibility | Earlier research UI and spatial experiments |
| `/ShelfSignals/preview/exhibit/` | `docs/preview/exhibit/index.html` | Compatibility | Exhibit cycles, paths, kiosk, and receipt experiments |

The independent HTTPS mirror uses the same document-root layout at `https://evcatalyst.github.io/ShelfSignals-live/`. Its separate repository syncs `gitbrainlab/ShelfSignals@main`; the first journey will appear at `/?journey=aerospace-folktales` after this branch merges and the next mirror sync. Locally, the route is `http://localhost:8000/?journey=aerospace-folktales`.

The root no longer needs the redirect proposed in PR #20. Its intent—preventing users from landing on the broken v1 selection flow—is addressed by placing v1 at `/legacy/` and serving the new application directly from `/`.

## Primary interface (`2.0.0`)

The primary interface is a zero-build static application composed of semantic HTML, CSS, and ES modules.

### Entry experience

- A shallow CSS-perspective shelf contains a bounded set of real records configured in `docs/data/featured_items.json`.
- The small `docs/data/cover_index.json` loads with the catalog. It stores only displayable exceptions to a universal unresolved default; absent or failed images display the exact label **Cover not yet verified for this edition**.
- `docs/data/cover_provenance.json` contains the heavier identifier match, source, image, rights, retrieval, review, and optical-analysis evidence. It is fetched only after a researcher opens a drawer for a displayable cover reference.
- The 13 legacy entries in `docs/data/book_visuals.json` are exact-ISBN provider references without structured human visual review. They are labeled **Exact-ISBN provider cover · visual review pending**, not verified approvals. Reviewed outputs from the private cover pipeline can enter the compact index through `build_cover_index.py --reviewed-references …`.
- Compact Clark-derived spine geometry comes from the separately loadable `docs/data/spine_index.json`. The runtime verifies its catalog SHA, record set, representation, rights, warning bits, and per-axis contract before rendering. A rejection produces visibly neutral unavailable placeholders.
- Physical view does not request the 17 MB provider-edition manifest. That separate evidence loads only after record detail is requested and never changes shelf geometry.
- Every fallback book uses the record's real title, creator, date, call number, material type, and deterministic color. It is an interface representation, not a photograph of the object.
- Provider-edition cover references remain remote-only and visibly scoped. They never establish the cover, binding, texture, wear, or side profile of the Clark copy.
- Motion is limited and disabled by `prefers-reduced-motion`.

### Evidence-led journey

The public journey index currently exposes one research preview, **Aerospace Folktales**, at `?journey=aerospace-folktales`.

- The route contains five cited photo movements and four chronological relationship shelves: preliminary context, early research, production and collaboration, and post-project reflection.
- Five Sekula work-image records are retained as cited metadata with `pending` rights; the browser renders calm withheld-image states rather than those photographs.
- One separately labeled Allan Sekula Library context photograph is displayed under its recorded open license. It is context for the collection, not a photograph from the target work.
- The journey publishes zero book/work associations. Its only book card is the real Clark catalog identity anchor for the named work; empty shelf positions are an intentional evidence state.
- Candidate associations and ambiguous cover matches stay outside deployed manifests. The local-only `docs/review.html` handoff validates unpublished association queues and exact-edition cover queues, resumes conflict-free cover ledgers, records named human decisions, and exports artifacts that still have no publication effect.
- Citations, locators, reasoning limits, rights state, editorial scope, and the publication gate are documented in `docs/journey-method.md`.

The sticky five-movement timeline and rights-gated photo mosaic use canonical `journey` and `cluster` URL state. Opening, closing, Browser Back, Browser Forward, reload, and scroll restoration preserve direct journey state without changing legacy path semantics.

### Complete collection browser

- Search covers title, creator, contributors, subjects, notes, provenance, call number, formats, publishers, contents, ISBN, OCLC, LCCN, and record ID.
- Filters cover registered signals, parsed call-number class, material type, decade, the experimental photo-likelihood bucket, and source-backed Sekula placement.
- Cover, spine, and list modes expose the same records. Every physical spine has a visible 24 × 24-or-larger placement target/state; the drawer exposes axis precedence, object form, separate binding/housing, metadata rights, provenance, and decoded warnings.
- The browser renders at most 72 additional records per batch. It never creates 11,176 book elements at once.
- All curated-path counts are derived at runtime. The current path schema contains signal rules rather than fixed reading lists, so the UI labels them as dynamic paths.

### Details and catalog truth

The detail drawer uses text-node DOM construction and treats catalog metadata as untrusted text. It exposes the canonical title, recorded creators, publication string, publisher, material/format, physical request call number, subjects, notes, provenance, availability, identifiers, and the exact `record_url` from the ShelfSignals dataset. A separate panel can expose a validated Open Library edition URL and exact match evidence; it is explicitly labeled provider-edition metadata rather than evidence about the Clark copy. No Amazon or inferred catalog links are generated.

Placement badges transcribe `Sekula Library Identifier` values from Clark provenance notes. A card shows the first recorded placement and a count when more exist; the drawer exposes every recorded value. Selecting a badge applies `?placement=...` to browse records with the same normalized source label. The displayed transcription is not replaced by normalization, and missing values are stated rather than inferred from call-number order or nearby records.

The committed `call_number` is usually the physical Sekula accession mark (`NE2698 .S4637L #####`), not a topical bibliographic LC class. The interface does not present inferred East/West wall positions as catalog facts. A future harvest should export Primo's bibliographic call number separately.

### Deep links

Stable query parameters include:

- `?record=alma…`
- `?journey=aerospace-folktales`
- `?journey=aerospace-folktales&cluster=domestic-interior`
- `?q=…`
- `?signals=image,labor`
- `?path=labor-images`
- `?placement=allan%20studio%20book%20room%20shelf%20d4`
- `?lc=TR`, `?material=book`, `?decade=1970`, `?photo=Likely`
- `?group=decade`, `?view=list`

History state restores the filter/view state, selected record, journey, and saved scroll position. Unknown record or journey IDs are removed without crashing the page. Existing `?path=` routes retain their prior meaning and serialization; placement and journey support do not rewrite them.

### My Shelf and Digital Receipts

My Shelf persists a de-duplicated list of Alma record IDs under the existing `shelfsignals_shelf` localStorage key. This preserves earlier Preview selections while avoiding stale embedded metadata.

Users can:

- add and remove records;
- clear the shelf;
- export a human-readable text list with Clark catalog URLs;
- export a `shelfsignals-receipt@1` JSON receipt;
- restore and verify a receipt before resolving its IDs against the current dataset.

QR export is deliberately disabled. The earlier implementation returned a placeholder image, not a real QR code.

### Accessibility

- semantic page landmarks and native buttons/links;
- skip link and visible focus styling;
- keyboard search with Command/Ctrl+K;
- keyboard-operable featured shelf, results, drawers, previous/next navigation, and Escape close;
- a research-oriented list mode;
- text alternatives for book controls and decorative cover images hidden from assistive technology;
- reduced-motion support and no scroll hijacking.

## Preview compatibility route

Preview retains earlier modular utilities, spatial research controls, explainable signal evidence, overlap discovery, Data Sandbox diagnostics, and annotated receipts. It remains useful for research comparison, but it is not the recommended public landing route.

The physical S-number parser now accepts the Clark collection mark or an explicit S-number label and rejects ordinary `.S43` LC cutters and trailing publication years.

## Exhibit compatibility route

Exhibit preserves dynamic paths, exhibition cycles, presence/voting prototypes, and kiosk-oriented display. Its path definitions in `curated-paths.json` are signal rules, not hand-picked lists. QR is shown as unavailable until a real static client-side encoder is bundled.

## Local development

Run from the repository root:

```bash
python3 -m http.server 8000 --directory docs
```

Open:

- `http://localhost:8000/`
- `http://localhost:8000/?journey=aerospace-folktales`
- `http://localhost:8000/legacy/`
- `http://localhost:8000/preview/`
- `http://localhost:8000/preview/exhibit/`

`file://` is unsupported because ES modules and JSON fetches require an HTTP origin.

## Data and modules

- `docs/data/sekula_index.json`: canonical 11,176-record research source and projection input; the primary browser no longer downloads it at first paint.
- `docs/data/catalog-core.json`: compact all-record first-load projection, bound to the canonical dataset SHA-256.
- `docs/data/catalog-search.json`: lazy full-field search projection fetched on the first non-empty query.
- `docs/data/catalog-details/`: 128 deterministic lazy detail shards plus an operational checksum index.
- `docs/js/catalog-data.js`: fail-closed projection validation, Clark-link reconstruction, search parsing, shard parsing, and record hydration.
- `docs/data/cover_index.json`: compact sparse first-paint cover contract plus the universal unresolved state.
- `docs/data/cover_provenance.json`: lazy exact-match, source, rights, retrieval, review, and analysis evidence for displayable covers.
- `docs/data/book_visuals.json`: legacy exact-ISBN provider-reference input; its records are not treated as human-reviewed approvals.
- `docs/data/spine_index.json`: compact, separately loaded Clark-derived shelf geometry with explicit estimated-depth scope.
- `docs/data/journeys/index.json`: small public index containing published journey routes only.
- `docs/data/journeys/aerospace-folktales.json`: cited, rights-aware journey manifest; it currently contains no public book/work associations.
- `docs/data/featured_items.json`: version-controlled real record IDs for the hero and highlights.
- `docs/js/cinematic-app.js`: primary application orchestration and safe DOM rendering.
- `docs/js/catalog.js`: record normalization, full-field search, filters, grouping, and URL state.
- `docs/js/covers.js`: cover index/provenance validation and provider/rights gates.
- `docs/js/journeys.js`: journey schema, publication, citation, rights, and human-review gates.
- `docs/js/placement.js`: source-label parsing, display preservation, grouping, and placement matching.
- `docs/js/spines.js`: compact spine-index validation and one-record decoding.
- `docs/js/visuals.js`: identifier normalization, manifest validation, deterministic book appearance, and featured resolution.
- `docs/js/shelf.js`: ID-only persistence and receipt restoration.
- `docs/js/signals.js`, `lc.js`, `year.js`, `colors.js`, `receipt.js`: shared utilities.

## Known limitations

- The canonical JSON remains about 39 MB uncompressed for audit and research. The primary interface initially fetches the roughly 3.9 MB core projection (about 0.91 MB with gzip), then loads full-field search and one small detail shard only when requested.
- Thirteen legacy exact-ISBN provider cover references are displayable but still await named visual review. Most records intentionally use metadata-derived fallback objects.
- Public journey shelves remain deliberately sparse until evidence is cited, rights are resolved, and a named human reviewer approves each association. Machine or keyword suggestions are not public content.
- Remote cover hosts can fail or rate-limit; layout and metadata remain functional when they do.
- `photo_insert_*` values currently come from a mock heuristic dataset. The UI labels them experimental and does not claim edition inspection.
- The current signal registry is keyword-based. Counts are reproducible, not curatorial endorsements.
- Preview and Exhibit remain historical experiments and may render more DOM than the primary interface.

## Regeneration and verification

From the repository root:

```bash
python3 scripts/build_cover_index.py --self-test
python3 scripts/build_cover_index.py
python3 scripts/ingest_cleared_covers.py self-test
python3 scripts/ingest_cleared_covers.py encoder-self-test  # requires Pillow
python3 scripts/cleared_cover_ingest_unit_tests.py
python3 scripts/google_books_cover_source.py self-test
python3 scripts/google_books_cover_source_unit_tests.py
python3 scripts/build_spine_index.py --self-test
python3 scripts/build_spine_index.py
node scripts/build_browser_catalog.mjs --self-test
node scripts/build_browser_catalog.mjs --check
python3 scripts/cover_source_pipeline.py self-test
node --test scripts/browser_catalog_unit_tests.mjs scripts/cinematic_unit_tests.mjs scripts/phase_one_unit_tests.mjs scripts/review_unit_tests.mjs scripts/spine_index_unit_tests.mjs scripts/aerospace_review_queue_tests.mjs scripts/association_promotion_tests.mjs
node scripts/preview_acceptance_tests.mjs
python3 scripts/browser_smoke_test.py --start-server --browser-channel chrome
```

The cover generator is deterministic apart from its generation timestamp and makes no network requests. The cover-source pipeline writes discovery and review state beneath ignored `.cache/cover-review/` by default. The final browser command is optional and requires Playwright plus an installed compatible browser.
