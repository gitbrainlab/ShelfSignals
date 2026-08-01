# Jefferson / Library of Congress extraction report

Status: **successful research extraction; verified with exceptions; suitable
for an engineering pilot, not yet an authoritative 1815 corpus or concordance**.

Snapshot built 2026-08-01 from the current LOC catalog application, loc.gov,
and LOC's published Sowerby reference files. The resumable package is under
`research/jefferson/work/` and is intentionally git-ignored because raw catalog
responses are large and are not publication-safe.

## Extracted result

| Evidence layer | Result | Unit and qualification |
|---|---:|---|
| Exact current LOC catalog | 2,748 | Unique FOLIO instances carrying the normalized exact contributor heading; not Sowerby entries or physical volumes |
| Attached holdings | 5,502 | Inventory objects attached to those instances; not all are necessarily Jefferson-collection holdings |
| Attached items | 5,209 | Inventory objects attached to those instances; 813 instances have no item and 6 have no holding |
| Ordered source MARC | 25 | First 25 instances in explicit title-ascending order; complete raw fields remain only in ignored cache, while derivatives use a public-safe allowlisted projection |
| loc.gov digital subset | 125 | Unique search items with 125 item-detail responses |
| LOC Sowerby base spine | 4,931 | Base integer identifiers expanded from five consecutive published ranges; suffix/addition IDs are not represented |
| Historical hierarchy | 44 | Chapters I–XLIV; History 1–15, Philosophy 16–29, Fine Arts 30–44 |
| LOC alphabetical index | 8,895 | Logical text rows; 8,850 have quarantined numeric candidates, none treated as validated references |

These counts describe different entities and cannot be substituted for the
standard historical count of physical volumes or for a copy/status inventory.
One matching bibliographic instance can include holdings in several LOC
locations, so 5,502 holdings and 5,209 items are not collection-size totals.

## Conservative concordance result

Expanded catalog notes frequently contain Sowerby ranges, page numbers, dates,
negations, corrections, OCR-like forms, and suffixed identifiers. They are
preserved as unparsed review candidates but are not converted into links.

The asserted crosswalk uses only a bounded source-MARC 510 whose `$c` contains
one plain base integer. Within the 25-record MARC sample:

- 25 catalog instances were assessed: 17 link to one base-integer Sowerby
  identifier and 8 have no qualifying 510 in the sample;
- the remaining 2,723 exact instances were not assessed for Sowerby matching;
- 17 of 4,931 base identifiers have one catalog candidate, none have multiple
  candidates, and 4,914 are not established in the sample; and
- one of 125 digital items connects through an exact normalized LCCN.

“No candidate” here means **not established by this 25-record MARC sample**. It
does not mean LOC lacks the title or copy. The crosswalk is a proof of the
evidence model, not meaningful full-corpus coverage.

Every machine-readable row carries the bounded assessment scope. Negative rows
use `not_established_in_bounded_marc_sample`, never “no match in the full result
set.” SQLite exposes the same status and scope as dedicated columns and labels
the LOC base spine, LOC index, and optional Monticello fragment units separately.

Catalog-to-digital edges retain their exact LCCN evidence. SQLite no longer
materializes a catalog-by-digital Cartesian product for records that merely
share a Sowerby identifier.

## Integrity and hierarchy findings

The primary current-catalog query is:

```text
contributors == "Thomas Jefferson Library Collection (Library of Congress)"
sortby title/sort.ascending
```

The explicit sort is essential. An earlier unsorted diagnostic pass returned
2,748 rows but only 2,444 unique instance UUIDs. The active sorted snapshot has:

- 110/110 expected pages;
- 2,748/2,748 reported instances;
- unique UUIDs, HRIDs, holding IDs, item IDs, and digital IDs;
- zero missing holding/item IDs and zero exact-heading misses;
- 406/406 cached response bodies matching their recorded byte counts and SHA-256
  retrieval sidecars;
- 25/25 declared raw source-MARC records present in ignored cache and 25/25
  public-safe projections present in derivatives; and
- SQLite `PRAGMA integrity_check = ok`, with FTS5 enabled.

Refreshes now write to inactive generation directories and activate only after
page, count, identity, and heading checks pass. Package builds fail before a
new manifest when an applicable invariant fails.

LOC's Sowerby TOC validates the consecutive base ranges 1–1237, 1238–2322,
2323–3662, 3663–4615, and 4616–4931 and the 44-chapter sequence. The base spine
does not claim that suffixed additions, titles, editions, volume counts, copy
identities, or reconstruction statuses have been resolved.

The LOC alphabetical index is retained for text search. Numeric parses remain
`reference_candidates_unvalidated`; dates, OCR confusions, suffixes, shorthand
ranges, and volume/page forms make automatic typing unsafe.

## Privacy, rights, and access boundary

Raw expanded catalog responses contain operational data returned by the public
application. They remain only in the ignored source snapshot. Derivative JSON,
SQLite, and indexes remove:

- 28,811 staff-only nodes;
- 26,918 internal created/updated-user ID fields;
- 13,459 administrative-note fields;
- 5,209 circulation-note fields;
- 1,528 item barcode fields;
- 2,784 tag fields; and
- all instance, holding, and item fields outside explicit derivative allowlists.

Raw MARC is likewise cache-only. The derivative projection drops unallowlisted
control/data fields, every local 9XX field, local subfield `9` values, and any
541/561/583 note explicitly marked private. A build invariant rejects a projected
record that does not reproduce identically under that policy.

All 2,748 exact records are labeled as exact collection-heading membership,
not Jefferson ownership. Ownership/survival/replacement/surrogate/missing status
is unresolved at collection scale. The bounded MARC layer separately preserves
controlled former-owner access points when present.

All 125 loc.gov detail responses are present, but only 102 contain a nonempty
item rights statement and 101 contain resources. The remaining items require
manual item-level rights review; absence is not permission.

The current catalog API is used by LOC's public application but is not documented
as a supported bulk interface. LOC should confirm rate, caching, reuse, and
refresh expectations before maintained use. The anonymous guest credential is
held in memory only.

The Thomas Jefferson Foundation/Monticello transcript was **not harvested**.
The CLI terms acknowledgement is self-attestation, not permission. Obtain and
retain permission evidence plus a validated completeness model before adding
that source to any public package.

## Source snapshot and reproducibility

Primary external-response snapshot:

```text
files: 267
bytes: 149,348,549
sha256: 3a51a0b80eea12a8f8906e8edeeb4d15237238b46e30776169b454ef171eeb6f
```

The full source manifest has 410 rows / 173,374,504 bytes. Its 143 non-primary
rows comprise 132 inactive catalog-generation files, eight incomplete broad-SRU
files, two local control manifests, and one unavailable-source ledger. The full
combined hash is:

```text
4bc396ee1d1985e324b4f932a4c5106ac256c56c8775fac7ce171cf5bbbb492a
```

The broad SRU phrase query reports 3,128 results but is known to include false
positives and failed during pagination with `First record position out of range`.
No SRU row is promoted. LOC's advertised Sowerby IIIF manifest returned 403;
the unavailable-source ledger records that limitation.

Two fixed-timestamp builds were required to match byte-for-byte across every
derived JSON, JSONL, and SQLite artifact. Use:

```bash
python3 scripts/jefferson_loc_extractor.py build \
  --generated-at 2026-08-01T17:30:00Z
```

## Main artifacts

| File | Purpose |
|---|---|
| `work/data/loc_catalog_instances.jsonl` | Privacy-filtered, allowlisted exact catalog instances |
| `work/data/loc_catalog_index.json` | Normalized primary catalog index |
| `work/data/loc_digital_items.jsonl` | Search and available item-detail metadata for 125 digital items |
| `work/data/loc_sowerby_entry_spine.jsonl` | Base-integer 1–4,931 identifier spine |
| `work/data/loc_sowerby_reference.json` | LOC ranges, chapters, resource summary, and rights context |
| `work/data/loc_sowerby_index_terms.jsonl` | Logical index text plus quarantined reference candidates |
| `work/data/sowerby_loc_crosswalk.jsonl` | Evidence-scoped MARC/LCCN pilot links |
| `work/data/jefferson_catalog.sqlite` | Searchable relational/FTS package with explicit source-layer units and bounded crosswalk status/scope |
| `work/data/source_files.jsonl` | Per-file role, retrieval evidence, size, and hash |
| `work/data/validation.json` | Explicit invariant results and coverage gaps |
| `work/data/manifest.json` | Snapshot identity, hashes, scope, and caveats |

## Decision and next gates

This supports a bounded **extraction-architecture pilot**: exact catalog search,
source snapshots, privacy-safe projections, slim/searchable derivatives,
evidence-scoped links, and fail-closed validation all work. It does not yet
support a public scholarly concordance or copy-status reconstruction.

Before expansion:

1. obtain an LOC-supported full MARC/holdings export or approved machine-access
   path and refresh policy;
2. obtain the curator-maintained original/replacement/surrogate/missing ledger;
3. model and verify Sowerby suffix/addition identifiers and full entry metadata;
4. build and manually validate a full-corpus Sowerby-to-catalog concordance;
5. complete item-level rights, curatorial, critical-historical, and accessibility
   review; and
6. obtain separate permission evidence before any Monticello transcript reuse.

Official entry points: [current LOC catalog](https://search.catalog.loc.gov/),
[LOC Sowerby item](https://www.loc.gov/item/52060000/),
[LOC Sowerby table of contents](https://catdir.loc.gov/catdir/toc/becites/main/jefferson/52060000.toc.html),
[LOC Sowerby index](https://catdir.loc.gov/catdir/toc/becites/main/jefferson/52060000.idx.html),
and [loc.gov JSON API guidance](https://www.loc.gov/apis/json-and-yaml/).
