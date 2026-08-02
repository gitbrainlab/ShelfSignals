# Thomas Jefferson collection

ShelfSignals presents Thomas Jefferson's library as a second collection inside the primary cinematic interface. The default `?collection=jefferson` route remains the 2,748-instance current-catalog beta. A separate historical beta at `?collection=jefferson&corpus=historical&order=sowerby` presents all 4,928 source-backed base Sowerby entries without claiming that the 1815 physical library, its surviving copies, or its current reconstruction have been fully resolved.

## Public scope and units

| Unit | Current count | Meaning |
|---|---:|---|
| LOC catalog instances | 2,748 | Current Library of Congress instances carrying the exact `Thomas Jefferson Library Collection (Library of Congress)` heading |
| Catalog instances in the bounded source-MARC sample | 25 | Records for which the current snapshot retained an allowlisted source-MARC projection |
| Established Sowerby links | 17 | Links supported by one plain base-integer MARC 510 identifier in that bounded sample |
| Ordered Sowerby catalog positions | 4,931 | Historical hierarchy spine and maximum source serial |
| Source-backed Sowerby entries | 4,928 | Bibliographic entries after preserving non-book numbering gaps 2323, 4707, and 4708 |
| Source-backed display titles | 1,351 | Short titles that passed the conservative LOC scan-OCR publication rules |
| Titles not established | 3,577 | Entries retained in sequence without invented title text |
| Exact-page entry evidence | 4,675 | Entries resolved to an exact page in an official LOC Sowerby PDF |
| Aggregate scan-spine evidence | 253 | Entries supported by the audited LOC scan spine without an exact page assignment |
| Historical physical volumes | 6,487 | Standard 1815 transfer count; not the grain of either browser corpus |
| Sowerby chapters | 44 | Historical hierarchy preview across History, Philosophy, and Fine Arts |
| Reviewed life-event lenses | 9 | Dated contextual routes through the historical chapter graph; not claims of reading or influence |
| Chapter clusters | 44 | Every historical entry participates through its source-backed Sowerby chapter |
| Direct documentary relationships | 5 | Record-to-event links with named LOC evidence and explicit limitations |
| Public media | 0 | No item has yet passed the public media reuse gate |
| Reviewer-mode media | 1 | Exact normalized-LCCN relation with item-level rights review still required |

Every current-catalog record is a `catalog_instance` with an ID such as `jefferson-loc-89f398bf-0d30-50a0-8129-3ecccdc869de`. Every historical record is a distinct `sowerby_entry` with an ID such as `jefferson-sowerby-3259`. Exact collection-heading membership does not establish that Jefferson owned a particular copy, that it survived, or that a current holding is an original, replacement, surrogate, or missing-item placeholder. Those states display as **not established**.

The 2,748 catalog instances and 4,928 historical entries are different, overlapping evidence layers. They must not be added together as 7,676 unique books.

Modern classification, holding call number, historical catalog order, and historical physical placement remain separate. The interface does not derive Sowerby order or Jefferson's shelving from an LC call number. The 44-chapter view is a coverage preview in the catalog corpus and an intellectual-order navigator in the historical corpus; it is never a physical shelf or room reconstruction.

The ignored research package and its methodology are documented in [`research/jefferson/README.md`](../research/jefferson/README.md). Raw responses, cache generations, JSONL research files, and SQLite are not deployed beneath `docs/`.

## Routes and collection behavior

Serve `docs/` over HTTP and open:

```text
http://localhost:8000/?collection=jefferson
```

The runtime loads `docs/data/collections/jefferson/manifest.json` before any Jefferson projection. Its backward-compatible default is:

```text
?collection=jefferson&corpus=catalog&order=title
```

Supported collection parameters are:

- `collection=jefferson` selects the Jefferson manifest; no parameter or `collection=sekula` selects Sekula.
- `corpus=catalog` selects the current catalog-instance layer; `corpus=historical` selects the 4,928-entry historical evidence layer.
- `order=title` is the catalog default. `order=lc` sorts catalog instances by modern classification/call number. `order=sowerby` is the historical default; historical title order is also available.
- `record=jefferson-loc-…` opens a catalog-instance deep link.
- `record=jefferson-sowerby-…` opens a historical-entry deep link and infers the historical corpus when an old URL omitted `corpus`.
- `event=…` selects one of the reviewed life-event lenses only in the historical corpus; it is removed from catalog and Sekula URLs.
- `evidence=sowerby_510_exact_bounded` limits the current beta to the 17 explicitly linked records.
- Existing search, compatible facets, list/cover view, and paginated rendering continue to work.

The visible collection and corpus switchers perform clean reloads. Unknown collection values fall back to Sekula and remove invalid collection/corpus/order state. Sekula-only journeys, placement, photo likelihood, provider-edition evidence, curated paths, and physical view are disabled rather than rendered empty. Browser history and record deep links retain the selected collection and corpus.

## Public package

The committed package is `docs/data/collections/jefferson/`. It contains two identifier- and path-disjoint deterministic projection namespaces for those overlapping evidence layers:

| Path | Role |
|---|---|
| `manifest.json` | Collection identity, editorial copy, feature flags, data paths, coverage counts, order choices, shelf key, and reviewer configuration |
| `catalog-core.json` | Compact first-load projection for all 2,748 catalog instances |
| `catalog-search.json` | Lazy full-field search projection |
| `catalog-details/000.json` through `063.json` | 64 deterministic, on-demand detail shards |
| `catalog-details/index.json` | Shard count, item counts, byte sizes, hashes, fields, and shared source identity |
| `hierarchy.json` | Three faculties, 44 chapters, five volume bounds, and the 4,931-position historical spine |
| `featured_items.json` | Real record IDs for the Jefferson hero and highlights |
| `media-public.json` | Strict public-media manifest; currently empty |
| `media-review.json` | Strict rights-pending review manifest; currently one exact-LCCN relation |
| `validation.json` | Source hashes, counts, privacy/evidence invariants, output hashes, warnings, and performance measurements |
| `historical/catalog-core.json` | Compact first-load projection for all 4,928 source-backed Sowerby entries |
| `historical/catalog-search.json` | Lazy historical search projection |
| `historical/catalog-details/000.json` through `063.json` | 64 deterministic historical detail shards |
| `historical/catalog-details/index.json` | Hash-bound historical shard inventory |
| `historical/validation.json` | Historical source, gap, provenance, title-coverage, and performance ledger |
| `historical/insights.json` | Nine reviewed life-event lenses, 44 chapter clusters, five documentary record relations, source links, confidence rules, and limitations |

Core, search, detail, hierarchy, validation, and media payloads carry collection/source identity and fail closed when those identities disagree. Search and details remain lazy; the browser never requests the raw research JSONL, SQLite database, cache, or whole research package. The committed core is 1,221,436 decoded bytes and 331,084 gzip bytes, within the 1.25 MB decoded and 350 KB gzip budgets.

Detail records retain source-backed titles, explicit primary creators and other contributors, publication statements, languages, subjects, formats, classifications, modern call numbers, holdings, items, identifiers, source-supplied catalog URLs, Sowerby evidence, and field-level evidence. The five records without a validated LCCN or public record URL intentionally have no synthesized catalog link.

## Life-event evidence graph

The historical corpus adds a question-led discovery layer: **Why is it here?**, **What was happening?**, **Was it used?**, and **What connects it?** Nine dated lenses connect Jefferson's life to Sowerby's 44 source-backed chapter clusters. Selecting a lens filters the historical corpus to the related chapters while preserving the 4,928-entry corpus, the selected event, and the active record as separate URL state.

Chapter-to-event edges are reviewed contextual associations. Their `context_score` is an ordinal navigation and evidence-strength score, not the probability that Jefferson read, consulted, endorsed, acquired, or was influenced by an entry. Membership, title words, and chapter placement never create a use claim.

A `use_confidence_score` appears only when a named source documents a bounded interaction with a specific entry, such as receipt, correspondence, later commentary, or excerpting. The graph currently contains five such record-level relationships. Every one carries a claim, relationship type, source, score, and limitation; an event for which use is not documented displays **not established** instead of a numeric zero. The public graph accepts only allowlisted Library of Congress sources and is bound to the exact historical dataset and record-ID set.

This completes the public membership-and-sequence projection, not full bibliographic metadata for every entry: 1,351 titles are source-backed by conservative LOC scan OCR and 3,577 remain visibly not established. Full title, edition, copy, holding, ownership, and use coverage still requires authoritative structured sources and curatorial review.

## Build and verification

The browser-package builder reads the hashed, ignored source snapshot at `research/jefferson/work/data/` by default. It uses a public field allowlist, validates the source files against the research manifest, makes no network requests, and fails closed on identity, count, privacy, evidence, media, hierarchy, or performance violations.

Build both corpora and the combined `@2` manifest with the aggregate owner:

```bash
python3 scripts/build_jefferson_collection_package.py
```

Validate entirely in memory, then compare generated bytes with the committed package:

```bash
python3 scripts/build_jefferson_collection_package.py --self-test
python3 scripts/build_jefferson_collection_package.py --check
```

Run the package and runtime contracts:

```bash
python3 scripts/build_jefferson_browser_package_unit_tests.py
python3 scripts/build_jefferson_historical_browser_package_unit_tests.py
python3 scripts/build_jefferson_collection_package_unit_tests.py
python3 scripts/build_jefferson_insight_graph_unit_tests.py
node --test \
  scripts/collection_contract_unit_tests.mjs \
  scripts/collection_runtime_unit_tests.mjs \
  scripts/jefferson_insight_unit_tests.mjs \
  scripts/jefferson_committed_package_tests.mjs
```

For a real-browser collection journey, start the static server in one terminal and run the Playwright test in another:

```bash
python3 -m http.server 8000 --directory docs
node scripts/collection_browser_journey.mjs http://127.0.0.1:8000/
```

The browser journey checks the default Sekula route, both Jefferson corpora, clean switching, canonical URL state, beta copy, 44-chapter hierarchy, source-number gaps, the nine-event evidence graph, contextual filtering, documentary confidence and limits, entity-specific drawers, independent shelves, receipt boundaries, Back/Forward behavior, lazy reviewer media, invalid collection fallback, keyboard access, reduced motion, forced colors, and mobile overflow. It requires Playwright and a compatible Chrome/Chromium binary.

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

## Authenticated photograph edition

Four contributor photographs of the reconstructed Library of Congress exhibition are packaged separately from the public site. The builder strips EXIF/XMP/GPS metadata, assigns content-hash filenames, records their exhibition-context-only evidence scope, and fails if any source or sanitized photo hash appears beneath `docs/`. The complete review site is written only beneath the ignored `research/jefferson/work/private-review/` workspace.

The deployable gateway under `infrastructure/private-review/cloudflare/` serves one immutable review release from a private R2 bucket. Cloudflare Access authenticates the reviewer, and the Worker independently verifies the Access JWT issuer, audience, signature, lifetime, and approved email before reading an exact object key. The bucket has no public domain or listing endpoint. Responses are `no-store`, `noindex`, same-origin isolated, and limited to `GET`/`HEAD`. This is access control, not DRM: an authorized reviewer can still save or photograph what they can see.

Build and validate the ignored release with:

```bash
python3 scripts/build_jefferson_private_media_bundle.py --help
python3 scripts/build_jefferson_private_review_release.py --help
python3 scripts/upload_jefferson_private_review_release.py --bucket shelfsignals-private-review --dry-run
```

Account provisioning, upload verification, Access policy configuration, and deployment are documented in [`infrastructure/private-review/cloudflare/README.md`](../infrastructure/private-review/cloudflare/README.md). Credentials and local deployment values are never command-line arguments, committed files, or public bundle content.

## Historical beta contract and promotion gates

### Runtime and builder payload contract

Sekula remains `shelfsignals-collection-manifest@1`. Jefferson uses `shelfsignals-collection-manifest@2` because both catalog and historical corpora are now present. Its top-level copy, coverage, data, features, facets, orders, and defaults mirror the default catalog corpus, preserving existing URLs and consumers. `hierarchy` remains collection-level; every other supplied data path is corpus-routed and disjoint.

Each `corpora[]` descriptor has exactly these fields:

```json
{
  "id": "historical",
  "label": "Historical Sowerby corpus",
  "record_id_prefix": "jefferson-sowerby-",
  "copy": {
    "status_label": "Historical corpus beta",
    "introduction": "…",
    "coverage_statement": "…",
    "source_label": "Library of Congress Sowerby scans"
  },
  "coverage": {
    "status": "beta",
    "entity_type": "sowerby_entry",
    "record_count": 4928,
    "historical_entry_count": 4928,
    "historical_position_count": 4931,
    "historical_volume_count": 6487,
    "established_sowerby_links": 0
  },
  "data": {
    "core": "historical/catalog-core.json",
    "search": "historical/catalog-search.json",
    "detail_template": "historical/catalog-details/{shard}.json",
    "detail_index": "historical/catalog-details/index.json",
    "validation": "historical/validation.json",
    "insights": "historical/insights.json"
  },
  "features": { "…": "all declared feature booleans" },
  "facets": ["evidence_status"],
  "orders": [
    { "id": "sowerby", "label": "Sowerby order" },
    { "id": "title", "label": "Title" }
  ],
  "default_order": "sowerby"
}
```

The 4,931 ordered positions contain 4,928 source-backed entries and three explicit non-book `source_number_absent` gaps—2323, 4707, and 4708. `record_count` and `source_backed_entry_count` are therefore 4,928 while `max_source_serial` and `historical_position_count` are 4,931. The catalog descriptor uses `catalog`, `jefferson-loc-`, `catalog_instance`, and the existing catalog paths and title default. Prefixes cannot overlap. An old deep link without `corpus` is inferred from these prefixes; an explicit corpus is never silently changed to fit a foreign record ID.

Historical projections use separate schemas and never reuse catalog-instance `@2` rows:

| Payload | Schema |
|---|---|
| core | `shelfsignals-browser-historical@1` |
| lazy search | `shelfsignals-historical-search@1` |
| detail shard | `shelfsignals-historical-detail-shard@1` |
| detail index | `shelfsignals-historical-detail-index@1` |
| validation | `shelfsignals-jefferson-historical-validation@1` |

The exported `HISTORICAL_CORE_FIELDS`, `HISTORICAL_SEARCH_FIELDS`, and `HISTORICAL_DETAIL_FIELDS` arrays in `docs/js/catalog-data.js` are the normative row order. All four projections repeat one exact source object with `collection_id`, `corpus_id`, `authority`, `publication_basis`, `rights_statement_url`, `rights_statement_sha256`, `dataset`, `dataset_sha256`, `record_count`, and `id_set_sha256`. Public historical data accepts only Library of Congress authority with `publication_basis` equal to `loc_scan_ocr_factual_extraction` or `loc_authorized_export`; rights URLs must resolve to `loc.gov`. Monticello transcripts may inform private segmentation QA but cannot be the public publication source.

Core rows retain an explicit `sowerby_identifier` and independent dense zero-based `orders.sowerby` sequence rank, so `3259`, `3259a`, and `3260` sort distinctly. The top-level `numbering` object distinguishes `max_source_serial` from `source_backed_entry_count` and records source-number gaps as `{identifier, status: "source_number_absent", evidence, source_url}`. A gap such as `2323` cannot also appear as a source-backed entry. `title_status` is `source_backed` or `not_established`; an unresolved title stays empty in the payload and receives the visibly qualified runtime label “Sowerby entry {identifier} — title not established.”

Historical `evidence_status` remains split between `sowerby_entry_page_resolved` and `sowerby_entry_aggregate_spine`. The former identifies an exact LOC PDF page; the latter preserves membership supported by the complete, audited scan spine when the OCR pipeline cannot assign an exact page. The interface exposes both counts and filters. No entity type is reused as a material or format: those fields remain blank and display as **not established** until source-backed bibliographic evidence exists.

Detail rows carry bibliographic fields plus typed relationship arrays for catalog instances, editions, volumes, physical copies, holdings, and digital objects. They never flatten those entities into the Sowerby entry. Assertions are exact objects with `field`, `status`, `value`, `source`, `source_url`, `evidence_sha256`, and `as_of`; the source URL must resolve to LOC and the evidence digest is mandatory. Title, membership, chapter, and sequence provenance are required, and any established ownership/reconstruction status requires its own assertion. The executable fixtures and rejection cases are in `scripts/collection_contract_unit_tests.mjs`.

One aggregate builder owns the combined Jefferson output and manifest. The individual builders remain independently testable and namespace-safe, but only `build_jefferson_collection_package.py` may write or check the complete release. Promotion changes the `@2` top-level mirror/default to historical; it does not overwrite catalog paths or IDs.

The historical route remains a prominently labeled beta. It may become the default, or be described as a complete scholarly edition, only after the evidence layer clears all of these gates:

1. Obtain an LOC-supported full MARC/holdings export, a maintained Sowerby crosswalk if one exists, and a curator-controlled original/replacement/surrogate/missing ledger.
2. Obtain structured Sowerby text or approved OCR/transcription for all five volumes, including suffixed and added identifiers without collapsing them into base integers.
3. Assign every source-backed entry a stable `jefferson-sowerby-{identifier}` identity, explicit title status, faculty, chapter, sequence, source provenance, and temporal/status semantics; represent source numbering gaps without inventing bibliographic entries.
4. Model `SowerbyEntry`, `Edition`, `Volume`, `PhysicalCopy`, `Holding`, `CatalogRecord`, `DigitalObject`, and `Assertion` separately, including multi-volume sets, bound-withs, incomplete sets, uncertain links, and missing entries.
5. Preserve the explicit per-corpus core, search, detail, and index routes when changing the default; keep the catalog package and deep links addressable instead of pointing both `corpus` values at one dataset.
6. Reconcile the actual entry count, maximum source serial, suffix/addition identifiers, numbering gaps, all 44 chapters, and all faculty boundaries; retain catalog records and deep links as a separate evidence layer.
7. Attach evidence and an as-of date to every published historical, ownership, and reconstruction-status assertion.
8. Demonstrate at least 98% precision for auto-accepted concordance links and keep every ambiguous or unmatched case visible in a review queue.
9. Complete item-level rights review for all public media.
10. Obtain bibliographic, curatorial, critical-historical, and accessibility sign-off.

Until every applicable gate is satisfied, both evidence layers remain betas and the current-catalog layer remains the default. Neither may be relabeled as the complete Jefferson library, and neither may claim to reproduce Jefferson's historical physical shelves.
