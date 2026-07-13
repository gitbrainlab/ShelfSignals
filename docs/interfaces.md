# ShelfSignals interfaces

ShelfSignals `2.0.0` makes the GitHub Pages root the canonical Allan Sekula Library browser. Earlier interfaces remain available at explicit compatibility routes; none of the routes redirect to one another.

## Route map

| Route | File | Status | Purpose |
|---|---|---|---|
| `/ShelfSignals/` | `docs/index.html` | Primary, `2.0.0` | Cinematic entry, full catalog browser, details, filters, and My Shelf |
| `/ShelfSignals/legacy/` | `docs/legacy/index.html` | Archived | Preserved v1 interface with known large-DOM performance limitations |
| `/ShelfSignals/preview/` | `docs/preview/index.html` | Compatibility | Earlier research UI and spatial experiments |
| `/ShelfSignals/preview/exhibit/` | `docs/preview/exhibit/index.html` | Compatibility | Exhibit cycles, paths, kiosk, and receipt experiments |

The root no longer needs the redirect proposed in PR #20. Its intent—preventing users from landing on the broken v1 selection flow—is addressed by placing v1 at `/legacy/` and serving the new application directly from `/`.

## Primary interface (`2.0.0`)

The primary interface is a zero-build static application composed of semantic HTML, CSS, and ES modules.

### Entry experience

- A shallow CSS-perspective shelf contains a bounded set of real records configured in `docs/data/featured_items.json`.
- Verified cover references from `docs/data/book_visuals.json` can appear on a front or spine surface.
- Exact-identifier edition evidence from `docs/data/book_editions.json` loads after the first render and can fill otherwise unknown synthetic geometry without delaying the initial catalog browser.
- Every fallback book uses the record's real title, creator, date, call number, material type, and deterministic color. It is an interface representation, not a photograph of the object.
- Motion is limited and disabled by `prefers-reduced-motion`.

### Complete collection browser

- Search covers title, creator, contributors, subjects, notes, provenance, call number, formats, publishers, contents, ISBN, OCLC, LCCN, and record ID.
- Filters cover registered signals, parsed call-number class, material type, decade, and the experimental photo-likelihood bucket.
- Cover, spine, and list modes expose the same records.
- The browser renders at most 72 additional records per batch. It never creates 11,176 book elements at once.
- All curated-path counts are derived at runtime. The current path schema contains signal rules rather than fixed reading lists, so the UI labels them as dynamic paths.

### Details and catalog truth

The detail drawer uses text-node DOM construction and treats catalog metadata as untrusted text. It exposes the canonical title, recorded creators, publication string, publisher, material/format, physical request call number, subjects, notes, provenance, availability, identifiers, and the exact `record_url` from the ShelfSignals dataset. A separate panel can expose a validated Open Library edition URL and exact match evidence; it is explicitly labeled provider-edition metadata rather than evidence about the Clark copy. No Amazon or inferred catalog links are generated.

The committed `call_number` is usually the physical Sekula accession mark (`NE2698 .S4637L #####`), not a topical bibliographic LC class. The interface does not present inferred East/West wall positions as catalog facts. A future harvest should export Primo's bibliographic call number separately.

### Deep links

Stable query parameters include:

- `?record=alma…`
- `?q=…`
- `?signals=image,labor`
- `?path=labor-images`
- `?lc=TR`, `?material=book`, `?decade=1970`, `?photo=Likely`
- `?group=decade`, `?view=list`

History state restores the filter/view state and selected record. Unknown record IDs are removed without crashing the page.

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
- `http://localhost:8000/legacy/`
- `http://localhost:8000/preview/`
- `http://localhost:8000/preview/exhibit/`

`file://` is unsupported because ES modules and JSON fetches require an HTTP origin.

## Data and modules

- `docs/data/sekula_index.json`: canonical 11,176-record source used by all metadata display.
- `docs/data/book_visuals.json`: versioned, provider-attributed cover-reference manifest.
- `docs/data/featured_items.json`: version-controlled real record IDs for the hero and highlights.
- `docs/js/cinematic-app.js`: primary application orchestration and safe DOM rendering.
- `docs/js/catalog.js`: record normalization, full-field search, filters, grouping, and URL state.
- `docs/js/visuals.js`: identifier normalization, manifest validation, deterministic book appearance, and featured resolution.
- `docs/js/shelf.js`: ID-only persistence and receipt restoration.
- `docs/js/signals.js`, `lc.js`, `year.js`, `colors.js`, `receipt.js`: shared utilities.

## Known limitations

- The canonical JSON is about 39 MB uncompressed (about 4 MB with normal HTTP compression); initial parsing still depends on the visitor's device.
- The visual manifest covers a small, conservatively verified subset. Most records intentionally use metadata-derived fallback objects.
- Remote cover hosts can fail or rate-limit; layout and metadata remain functional when they do.
- `photo_insert_*` values currently come from a mock heuristic dataset. The UI labels them experimental and does not claim edition inspection.
- The current signal registry is keyword-based. Counts are reproducible, not curatorial endorsements.
- Preview and Exhibit remain historical experiments and may render more DOM than the primary interface.
