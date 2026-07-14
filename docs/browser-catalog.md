# Browser catalog projections

`docs/data/sekula_index.json` remains ShelfSignals' canonical catalog export. The primary browser does not edit, replace, or reinterpret that file. It loads deterministic projections so a visitor does not have to download and parse the full research record before seeing the collection.

## Public files

| File | Load point | Contents |
|---|---|---|
| `catalog-core.json` | Initial application load | All 11,176 IDs plus the source-backed fields needed for covers, spines, grouping, filters, paths, placement, and Clark links |
| `catalog-search.json` | First non-empty search | Lower-cased full-field search text generated from the canonical records |
| `catalog-details/000.json` … `127.json` | First detail request for a shard | Subjects, notes, provenance, identifiers, holdings, publisher and other drawer metadata |
| `catalog-details/index.json` | Operations and audit only | Per-shard count, byte size, and SHA-256 |

The committed build currently reduces the first catalog response from roughly 39 MB decoded to roughly 3.9 MB decoded (about 0.91 MB with gzip). Search and detail evidence are fetched only when the corresponding interaction needs them.

## Identity and trust boundary

Every projection declares:

- the exact SHA-256 of the raw canonical `sekula_index.json` bytes;
- the canonical record count;
- an ordered catalog-ID checksum;
- an explicit schema and fixed field order.

The browser parsers in `docs/js/catalog-data.js` reject unknown schemas, stale source identity, malformed rows, duplicated or unknown IDs, unsafe Clark URL templates, and records assigned to the wrong detail shard. Detail files are assigned with the same deterministic FNV-1a hash used by the visual runtime. A rejected projection is not partially displayed.

Clark record links are not guessed from titles or identifiers. The generator first proves that every canonical `record_url` matches the Clark discovery URL contract, then stores that audited template once and reconstructs each exact link from its real Alma ID.

Search remains semantically equivalent to the earlier in-memory search. Its text is produced by `enrichRecord` from canonical title, alternate title, creator, contributor, subject, call number, notes, provenance, Sekula notes, placement, description, publisher, format, contents, ISBN, ISSN, OCLC, LCCN, Alma MMS, and record ID values.

## Detail projection

Detail shards retain catalog wording but remove unused holding-system internals such as opaque holding keys. They also exclude the legacy `photo_insert_reasoning` field because its machine-generated `Mock:` prose is not catalog or reviewed editorial evidence. The public drawer receives only the service location, location code, request call number, and availability status needed by the interface. The complete unmodified holdings and legacy research fields remain in the canonical dataset.

Opening one record hydrates every record in that small shard in memory. Reopening a record in the same shard causes no second request. No provider-edition data or cover provenance is mixed into Clark catalog detail.

## Regeneration

From the repository root:

```bash
node scripts/build_browser_catalog.mjs --self-test
node scripts/build_browser_catalog.mjs
node scripts/build_browser_catalog.mjs --check
node --test scripts/browser_catalog_unit_tests.mjs
```

`--check` reuses the committed generation timestamp and compares every byte, including all shard files. CI should run it after any canonical catalog or projection-code change.

For reproducible release timestamps, set `SOURCE_DATE_EPOCH` or pass a whole-second UTC value with `--generated-at`. Shard count is explicit and defaults to 128; changing it requires regenerating the core, search, detail index, and every numbered shard together.

## Failure behavior

- If the core projection is missing or rejected, the application exposes a retryable load error instead of a partial catalog.
- If search cannot load, current browsing state is preserved and the search control reports the failure.
- If a detail shard cannot load or fails validation, the drawer retains core metadata and states that expanded catalog evidence is unavailable.
- The canonical full dataset remains committed for research, pipeline regeneration, receipts, and audit. It is not silently fetched as a browser fallback because doing so would restore the performance problem this architecture removes.
