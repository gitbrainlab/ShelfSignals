# Thomas Jefferson Library extraction research

This directory contains a resumable research extractor for testing a Jefferson
collection package without changing Shelf Signals' Sekula runtime. The working
package under `research/jefferson/work/` is git-ignored because it is large and
contains raw catalog responses that are evidence, not publication-ready data.

## Source layers and boundaries

The extractor keeps these layers distinct:

1. **Exact current-catalog instances** — the LOC catalog application's exact
   contributor-heading query, expanded with attached holdings and items. These
   are current FOLIO instances, not Sowerby entries, titles, editions, physical
   volumes, Jefferson-owned copies, or reconstruction-status assertions. One
   matching instance can include holdings outside the Jefferson collection.
2. **Bounded source MARC** — complete ordered raw MARC is retained only in the
   ignored cache for an explicitly recorded prefix of the stable title-sorted
   result. Derivatives contain an allowlisted public-safe projection. The present
   snapshot has 25 such records. It is a parser/evidence sample, not full-corpus
   MARC coverage.
3. **LOC digital items** — the loc.gov JSON facet plus optional item-detail
   responses. A response can lack rights or resources; presence is reported
   separately and never inferred.
4. **LOC Sowerby references** — item JSON, table of contents, and alphabetical
   index. Published volume ranges support a 1–4,931 **base-integer identifier
   spine** and the TOC supports 44 chapters. Suffixed/addition identifiers are
   not silently collapsed into those integers.
5. **Optional Monticello fragments** — disabled by default. A CLI acknowledgement
   records only that the operator reviewed the terms; it is not reuse permission.
   Any future transcript crawl remains a separate, unreconciled fragment layer.

The LOC alphabetical index currently yields 8,895 logical text rows. Numeric
parses on 8,850 rows are retained only as `reference_candidates_unvalidated`:
dates, OCR confusions, suffixes, volume/page forms, and shorthand ranges make an
automatic typed crosswalk unsafe. The asserted `references` array is therefore
empty, and index candidates do not participate in concordance counts.

## Publication boundary

Raw expanded catalog pages can expose operational metadata despite coming from
the public catalog application. Raw responses remain only in the ignored source
snapshot. Derivatives:

- remove nodes marked `staffOnly` or suppressed from discovery;
- remove internal user IDs, administrative/circulation notes, item barcodes,
  and tags;
- apply explicit instance/holding/item field allowlists; and
- project raw MARC through an explicit bibliographic tag allowlist, removing
  local 9XX fields, local subfield `9` values, and private 541/561/583 notes; and
- retain untyped public Sowerby note text only as review candidates.

All exact records are labeled `exact_collection_heading_membership`. Ownership,
survival, replacement, surrogate, and missing status remain unresolved unless a
reviewed evidence model supports them. The bounded MARC projection may preserve
a controlled `700` former-owner access point, but that does not promote a
collection-wide copy-status assertion.

## Run it

No third-party Python packages are required.

```bash
python3 scripts/jefferson_loc_extractor.py catalog --source-marc-limit 25
python3 scripts/jefferson_loc_extractor.py digital --item-details
python3 scripts/jefferson_loc_extractor.py loc-sowerby
python3 scripts/jefferson_loc_extractor.py build
```

Or run all default LOC layers:

```bash
python3 scripts/jefferson_loc_extractor.py all \
  --item-details --source-marc-limit 25
```

Successful responses are cached with request URL, retrieval time, byte count,
content type, and SHA-256 sidecars. Cache hits and package builds verify the
stored body against those sidecars; a valid-JSON mutation still fails closed.
Refreshes write into an inactive generation and switch `active.json` only after
count, page, identity, and exact-heading
checks pass; interrupted refreshes resume from `pending.json`. The package build
fails closed on applicable source invariants and writes its manifest last.

Use `--refresh` only to create a deliberate new source snapshot. Default delays
are 0.8 seconds for catalog/SRU requests and at least 3.05 seconds for loc.gov
item requests. The broad SRU phrase query is opt-in and never defines the corpus:

```bash
python3 scripts/jefferson_loc_extractor.py sru
```

Monticello is not included in the LOC extractor's present snapshot. Do not
enable it for public reuse without separate permission evidence and a validated
completeness model.
The option below is self-attestation only:

```bash
python3 scripts/jefferson_loc_extractor.py sowerby \
  --acknowledge-monticello-terms
```

The separate focused harvester can create and validate a complete private
research snapshot of the five-volume HTML transcription. Its outputs remain
under the same ignored workspace and must not be copied to `docs/` unless reuse
permission is recorded:

```bash
python3 scripts/harvest_jefferson_sowerby.py crawl \
  --acknowledge-monticello-terms
python3 scripts/harvest_jefferson_sowerby.py build \
  --generated-at 2026-08-02T02:01:25Z
python3 scripts/harvest_jefferson_sowerby_unit_tests.py -v
```

The focused build publishes only bibliographic facts to its private derivative:
base identifier/order, faculty/chapter, explicit J marker, short title, author,
bibliographic title/imprint, explicit language/edition/format spans, Sowerby
call number, and source links. It excludes notes, annotations, bibliography,
`AltTitleLoc`, quotations, and other editorial prose. Validation distinguishes
source-backed entries, inferred HTML omissions, explicit ranges, suffixed or
unnumbered exceptions, source BID corrections, repeated aggregate pages, and
non-book placeholders for independently verified gaps. A contiguous numeric
spine is never represented as 4,931 source-backed books.

Focused outputs are `sowerby_entries.jsonl`,
`sowerby_entry_exceptions.jsonl`, `sowerby_source_pages.jsonl`,
`sowerby_validation.json`, and `sowerby_manifest.json` under
`research/jefferson/work/data/`.

Public historical display text is built independently from the official five
Library of Congress Sowerby PDFs. The OCR pipeline hashes the source PDFs and
every rendered/text/TSV page sidecar, resolves a conservative marker spine,
publishes a short title only when a strict layout rule passes, and retains all
other source-backed identifiers with `title_status: not_established`:

```bash
python3 scripts/extract_jefferson_sowerby_loc_ocr.py audit
python3 scripts/extract_jefferson_sowerby_loc_ocr.py all --workers 8
python3 scripts/extract_jefferson_sowerby_loc_ocr_unit_tests.py -v
python3 scripts/build_loc_sowerby_chapter_ranges.py --check
```

The tracked `research/jefferson/loc-sowerby-chapter-ranges.json` is a separate
44-row, scan-audited LOC hierarchy artifact. Its entry ranges and exact heading
page hashes drive the public chapter mapping. The private transcript is used
only afterward as an equality check; its text, identifiers, hashes, and source
labels never enter the public validation or browser package.

The aggregate writer then builds both public Jefferson corpora and the combined
manifest without making a network request:

```bash
python3 scripts/build_jefferson_collection_package.py --self-test
python3 scripts/build_jefferson_collection_package.py
python3 scripts/build_jefferson_collection_package.py --check
```

## Generated evidence

`research/jefferson/work/data/` contains:

| File | Grain and role |
|---|---|
| `loc_catalog_instances.jsonl` | One privacy-filtered, allowlisted exact catalog instance per line, with normalized holdings/items and a bounded public-safe source-MARC projection where active |
| `loc_catalog_index.json` | Normalized exact-instance projection; primary current-catalog index |
| `loc_sru_marc_records.jsonl` | Public-safe ordered MARC projection for the separately labeled broad SRU evidence set, if a complete opt-in harvest succeeds; raw XML remains only in ignored cache |
| `loc_digital_items.jsonl` | Whole loc.gov search results and available item-detail responses |
| `loc_sowerby_reference.json` | LOC volume ranges, chapter hierarchy, resource summary, rights context, and source roles |
| `loc_sowerby_entry_spine.jsonl` | Base integer identifiers 1–4,931; no titles, suffix additions, copy/status, or holding claims |
| `loc_sowerby_index_terms.jsonl` | Verbatim logical index rows plus quarantined, unvalidated numeric candidates |
| `monticello_sowerby_fragments.jsonl` | Optional, permission-gated HTML fragments; empty in this snapshot |
| `sowerby_loc_crosswalk.jsonl` | Conservative candidate links from one plain base-integer MARC 510 identifier, then exact normalized LCCN for digital links; every row declares the 25-record assessment scope |
| `jefferson_catalog.sqlite` | Searchable instances, holdings, items, public-safe MARC sample, explicitly unit-labeled Sowerby layers, bounded assessment status/scope on every crosswalk row, and FTS |
| `source_files.jsonl` | Per-file role, retrieval evidence where applicable, byte count, and SHA-256 |
| `validation.json` | Counts, uniqueness, completeness, privacy-removal counts, crosswalk evidence checks, and SQLite integrity |
| `manifest.json` | Scope, source snapshot hash, output hashes, counts, and caveats |

Example SQLite query:

```sql
SELECT id, title, lccn, sowerby_numbers_json
FROM catalog_instances
WHERE id IN (
  SELECT id FROM instance_fts WHERE instance_fts MATCH 'architecture'
);
```

## Verification

Run the no-network contracts:

```bash
PYTHONWARNINGS=error::ResourceWarning \
  python3 scripts/jefferson_loc_extractor_unit_tests.py -v
```

Tests cover stable pagination, retrieval-sidecar integrity, stale-page rejection,
fail-closed builds, retry behavior, privacy filtering and catalog/MARC field
allowlists, exact-membership versus ownership, suffix/range non-conflation,
evidence-scoped catalog/digital links, source preservation, Sowerby hierarchy
boundaries, and SQLite integrity.

For a byte-reproducible rebuild from one source snapshot, pass the same fixed
whole-second UTC value twice:

```bash
python3 scripts/jefferson_loc_extractor.py build \
  --generated-at 2026-08-01T17:30:00Z
```

## Scope boundary

This is a successful extraction/indexing attempt and an architecture pilot
asset. It is not a complete source-MARC export, a validated full Sowerby-to-LOC
concordance, or an authoritative current copy-status ledger. Before public or
maintained use, obtain LOC guidance on API access/refresh/reuse, curator-approved
ownership/reconstruction evidence, item-level rights review, and scholarly and
accessibility sign-off.
