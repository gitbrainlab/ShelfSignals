# Thomas Jefferson collection

ShelfSignals presents Thomas Jefferson's library as a second collection inside the primary cinematic interface. Phase 1 is a prominently labeled current-catalog beta at `?collection=jefferson`; it is an evidence layer for a later historical edition, not a claim that the complete 1815 library has been reconstructed.

## Phase 1 scope

| Unit | Current count | Meaning |
|---|---:|---|
| LOC catalog instances | 2,748 | Current Library of Congress instances carrying the exact `Thomas Jefferson Library Collection (Library of Congress)` heading |
| Catalog instances in the bounded source-MARC sample | 25 | Records for which the current snapshot retained an allowlisted source-MARC projection |
| Established Sowerby links | 17 | Links supported by one plain base-integer MARC 510 identifier in that bounded sample |
| Sowerby base-integer identifiers | 4,931 | Historical coverage target and hierarchy spine; Phase 1 does not contain complete entry titles |
| Historical physical volumes | 6,487 | Standard 1815 transfer count; not the Phase 1 record grain |
| Sowerby chapters | 44 | Historical hierarchy preview across History, Philosophy, and Fine Arts |
| Public media | 0 | No item has yet passed the public media reuse gate |
| Reviewer-mode media | 1 | Exact normalized-LCCN relation with item-level rights review still required |

Every Phase 1 browser record is a `catalog_instance` with an ID such as `jefferson-loc-89f398bf-0d30-50a0-8129-3ecccdc869de`. Exact collection-heading membership does not establish that Jefferson owned a particular copy, that it survived, or that a current holding is an original, replacement, surrogate, or missing-item placeholder. Those states display as **not established**.

Modern classification, holding call number, historical catalog order, and historical physical placement remain separate. The interface does not derive Sowerby order or Jefferson's shelving from an LC call number. The 44-chapter view is a coverage preview, not a physical shelf or room reconstruction.

The ignored research package and its methodology are documented in [`research/jefferson/README.md`](../research/jefferson/README.md). Raw responses, cache generations, JSONL research files, and SQLite are not deployed beneath `docs/`.

## Routes and collection behavior

Serve `docs/` over HTTP and open:

```text
http://localhost:8000/?collection=jefferson
```

The runtime loads `docs/data/collections/jefferson/manifest.json` before any Jefferson catalog projection. Its defaults are serialized into the canonical Phase 1 URL:

```text
?collection=jefferson&corpus=catalog&order=title
```

Supported collection parameters are:

- `collection=jefferson` selects the Jefferson manifest; no parameter or `collection=sekula` selects Sekula.
- `corpus=catalog` selects the Phase 1 catalog-instance layer. `corpus=historical` is reserved for Phase 2 and currently normalizes back to `catalog`.
- `order=title` is the Phase 1 default. `order=lc` sorts by modern classification/call number. `order=sowerby` is reserved for a validated historical corpus and currently normalizes back to `title`.
- `record=jefferson-loc-…` opens a catalog-instance deep link.
- `evidence=sowerby_510_exact_bounded` limits the current beta to the 17 explicitly linked records.
- Existing search, compatible facets, list/cover view, and paginated rendering continue to work.

The visible collection switcher performs a clean reload. Unknown collection values fall back to Sekula and remove invalid collection/corpus/order state. Sekula-only journeys, placement, photo likelihood, provider-edition evidence, curated paths, and physical view are disabled rather than rendered empty. Browser history and record deep links retain the selected collection.

## Public package

The committed package is `docs/data/collections/jefferson/`. It contains 73 deterministic JSON files:

| Path | Role |
|---|---|
| `manifest.json` | Collection identity, editorial copy, feature flags, data paths, coverage counts, order choices, shelf key, and reviewer configuration |
| `catalog-core.json` | Compact first-load projection for all 2,748 catalog instances |
| `catalog-search.json` | Lazy full-field search projection |
| `catalog-details/000.json` through `063.json` | 64 deterministic, on-demand detail shards |
| `catalog-details/index.json` | Shard count, item counts, byte sizes, hashes, fields, and shared source identity |
| `hierarchy.json` | Three faculties, 44 chapters, volume ranges, and the 4,931 base-integer coverage target |
| `featured_items.json` | Real record IDs for the Jefferson hero and highlights |
| `media-public.json` | Strict public-media manifest; currently empty |
| `media-review.json` | Strict rights-pending review manifest; currently one exact-LCCN relation |
| `validation.json` | Source hashes, counts, privacy/evidence invariants, output hashes, warnings, and performance measurements |

Core, search, detail, hierarchy, validation, and media payloads carry collection/source identity and fail closed when those identities disagree. Search and details remain lazy; the browser never requests the raw research JSONL, SQLite database, cache, or whole research package. The committed core is 1,221,436 decoded bytes and 331,084 gzip bytes, within the 1.25 MB decoded and 350 KB gzip budgets.

Detail records retain source-backed titles, explicit primary creators and other contributors, publication statements, languages, subjects, formats, classifications, modern call numbers, holdings, items, identifiers, source-supplied catalog URLs, Sowerby evidence, and field-level evidence. The five records without a validated LCCN or public record URL intentionally have no synthesized catalog link.

## Build and verification

The browser-package builder reads the hashed, ignored source snapshot at `research/jefferson/work/data/` by default. It uses a public field allowlist, validates the source files against the research manifest, makes no network requests, and fails closed on identity, count, privacy, evidence, media, hierarchy, or performance violations.

Build the committed projection:

```bash
python3 scripts/build_jefferson_browser_package.py
```

Validate entirely in memory, then compare generated bytes with the committed package:

```bash
python3 scripts/build_jefferson_browser_package.py --self-test
python3 scripts/build_jefferson_browser_package.py --check
```

Run the package and runtime contracts:

```bash
python3 scripts/build_jefferson_browser_package_unit_tests.py
node --test \
  scripts/collection_contract_unit_tests.mjs \
  scripts/collection_runtime_unit_tests.mjs
```

For a real-browser collection journey, start the static server in one terminal and run the Playwright test in another:

```bash
python3 -m http.server 8000 --directory docs
node scripts/collection_browser_journey.mjs http://127.0.0.1:8000/
```

The browser journey checks the default Sekula route, clean collection switching, canonical URL state, beta copy, 44-chapter preview, feature isolation, title/LC ordering, the bounded-evidence filter, drawer entity language, independent shelves, wrong-collection receipt rejection, Back/Forward behavior, lazy reviewer media, invalid collection fallback, keyboard access, reduced motion, forced colors, and mobile overflow. It requires Playwright and a compatible Chrome/Chromium binary.

Use the extraction commands in [`research/jefferson/README.md`](../research/jefferson/README.md) only when deliberately refreshing the ignored research snapshot. Rebuilding the public package and refreshing external source evidence are separate operations.

## Reviewer mode is not access control

The Jefferson manifest stores a SHA-256 digest of the reviewer code. The browser hashes the entered value, keeps a successful unlock only in collection-specific `sessionStorage`, and requests `media-review.json` only after unlock. A persistent banner says **Review mode—not access controlled**.

This mechanism provides interface friction and prevents accidental public-mode requests; it does not protect a static asset. The digest, JavaScript, and review-media URL are all shipped on a public site, and a visitor can request that URL directly. Therefore:

- never place confidential metadata, restricted binaries, credentials, or non-public URLs in the review manifest;
- treat every review item as public metadata whose reuse status is unresolved;
- retain its item-level Rights and Access evidence and exact-match basis;
- never describe an unlocked preview as cleared, licensed, or curator-approved; and
- publish media through `media-public.json` only after an explicit item-level review confirms the public gate.

Library of Congress item descriptions can include rights information, but the user remains responsible for assessing intended use. See the [LOC copyright and primary-source guidance](https://www.loc.gov/legal/understanding-copyright/).

## Phase 2: historical corpus gates

Phase 2 may make 4,931 Sowerby entries and Sowerby order the default only after the historical evidence layer clears all of these gates:

1. Obtain an LOC-supported full MARC/holdings export, a maintained Sowerby crosswalk if one exists, and a curator-controlled original/replacement/surrogate/missing ledger.
2. Obtain structured Sowerby text or approved OCR/transcription for all five volumes, including suffixed and added identifiers without collapsing them into base integers.
3. Assign every base entry a stable `jefferson-sowerby-{number}` identity, title, faculty, chapter, sequence, source provenance, and explicit temporal/status semantics.
4. Model `SowerbyEntry`, `Edition`, `Volume`, `PhysicalCopy`, `Holding`, `CatalogRecord`, `DigitalObject`, and `Assertion` separately, including multi-volume sets, bound-withs, incomplete sets, uncertain links, and missing entries.
5. Extend the manifest contract with explicit per-corpus core, search, detail, and index routes before changing the default. Phase 2 must keep the Phase 1 catalog package and deep links addressable instead of pointing both `corpus` values at one dataset.
6. Validate all 4,931 base entries, all 44 chapters, and all faculty boundaries; retain the Phase 1 catalog records and deep links as a separate evidence layer.
7. Attach evidence and an as-of date to every published historical, ownership, and reconstruction-status assertion.
8. Demonstrate at least 98% precision for auto-accepted concordance links and keep every ambiguous or unmatched case visible in a review queue.
9. Complete item-level rights review for all public media.
10. Obtain bibliographic, curatorial, critical-historical, and accessibility sign-off.

Until every applicable gate is satisfied, the product remains the Phase 1 catalog beta. It must not be relabeled as the complete Jefferson library, and it must not claim to reproduce Jefferson's historical physical shelves.
