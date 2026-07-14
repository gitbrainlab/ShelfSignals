# Cover source review pipeline

ShelfSignals now has a conservative foundation for assigning a front-face visual to every catalog record without turning a plausible image into a false claim. `scripts/cover_source_pipeline.py` inventories all 11,176 Clark records, finds exact-edition cover candidates from the local Open Library dump enrichment, and keeps every candidate private until a person reviews it.

The public unresolved state is always:

> Cover not yet verified for this edition

An unresolved record can still use a metadata-derived interface surface, but that surface is not a scan and must not imply an edition-specific cover, binding, material, condition, or texture.

## Why this source and method

Open Library publishes monthly edition dumps and explicitly asks collection-scale users to use bulk data instead of harvesting its API. The [Open Library data-dump documentation](https://openlibrary.org/developers/dumps) describes the edition records and snapshot format; the [bulk-data guidance](https://openlibrary.org/data) says to use the dumps when downloading everything.

The local `docs/data/book_editions.json` manifest was produced from the June 30, 2026 editions dump. It joins Clark records to provider editions by normalized ISBN, OCLC, or LCCN while retaining the provider snapshot and checksum. The cover queue is stricter: only an ISBN that is identical after ISBN-10/ISBN-13 canonicalization can create a review candidate. Title, author, date, publisher, similarity, and work-level matches never create a public candidate on their own.

The [Open Library Covers API documentation](https://openlibrary.org/dev/docs/api/covers) says:

- do not crawl the cover API;
- use provider-hosted cover URLs on public pages;
- link back to the corresponding Open Library record as a courtesy;
- request `?default=false` to receive a 404 instead of a blank fallback;
- access by identifiers other than Cover ID and OLID is limited to 100 requests per five minutes.

ShelfSignals therefore discovers cover IDs from the monthly dump without network calls. Optional availability probes use Cover IDs, read only a bounded response prefix, default to one request every 3.1 seconds, stop at 100 requests per process, stop on a provider rate-limit response, and save positive and negative outcomes after each request. A full-collection image crawl is intentionally not part of this workflow.

## Coverage from the committed enrichment

The no-network audit of the current committed data produced:

| Measure | Records | Catalog share |
| --- | ---: | ---: |
| Catalog records | 11,176 | 100% |
| Records with a valid ISBN | 7,860 | 70.33% |
| Records with at least one exact-ISBN edition cover candidate | 6,313 | 56.49% |
| Exact-edition candidate references requiring review | 11,872 | — |
| Exact-edition matches with no safe cover candidate | 1,217 | 10.89% |
| Valid-ISBN records with no exact-edition match | 330 | 2.95% |
| Records without a valid ISBN | 3,316 | 29.68% |

The 56.49% figure is *candidate* coverage, not verified public cover coverage. Image availability, edition correctness, front-cover role, and human approval can only reduce it. Multiple Open Library edition records or cover IDs exist for 2,749 catalog records, which is another reason not to choose automatically.

The existing `docs/data/book_visuals.json` contains 13 provider references whose source ISBNs agree with their Clark records. Those entries do not contain structured reviewer identity and review date, so this pipeline reports them as existing exact-identifier references but does not silently import them as reviewed approvals.

## Private files and public boundary

All working state defaults to the ignored `.cache/cover-review/` directory:

- `candidates.json`: all-record queue and exact-edition candidates;
- `probes.json`: resumable bounded-response metadata, never image binaries;
- `reviews.json`: human decisions and evidence notes;
- `reviewed-cover-references.json`: reviewed-only output preview.

The public publisher refuses to write beneath `docs/` unless the operator passes `--allow-docs-output`. Even with that flag, it publishes only a candidate that passes every gate:

1. Exact canonical ISBN intersection between the Clark record and Open Library edition.
2. Stable Open Library edition ID and Cover ID from the checksummed dump snapshot.
3. Successful bounded image probe with parseable dimensions.
4. Human `approve` decision tied to the current candidate fingerprint.
5. Named reviewer and UTC review time.
6. Explicit confirmation that the candidate is the same edition and was visually checked.
7. Evidence note and `remote_reference_only` rights scope.
8. No second approved front cover for the same Clark record.
9. A gate receipt carrying both confirmations and the current bounded positive-probe fingerprint, timestamp, and dimensions.

Stale reviews and stale probes fail closed when catalog identifiers, provider edition, Cover ID, or dump checksum changes.

## Commands

Run deterministic tests without network access:

```bash
python3 scripts/cover_source_pipeline.py self-test
```

Build the all-record private queue. This reads only committed local files:

```bash
python3 scripts/cover_source_pipeline.py audit
```

### Deterministic production batches

The complete queue contains 11,872 candidate references, so operators should not pass one undifferentiated file between reviewers or probe it as one job. Generate a private, reproducible plan plus browser-reviewable queue shards:

```bash
python3 scripts/cover_source_pipeline.py plan-batches \
  --target-candidates 100 \
  --queue-dir .cache/cover-review/batches
```

For the current queue this produces 120 batches. A Clark record is atomic: every candidate for one catalog record stays in the same batch so two reviewers cannot independently approve competing covers for that record. The target is therefore a packing target rather than a reason to split evidence. The current largest batch contains 100 candidates.

The plan records the exact queue-input checksums, a fingerprint of the full candidate set, every candidate fingerprint, record membership, and a fingerprint for each batch. Loading a stale, incomplete, duplicated, split-record, or hand-edited plan fails before probing or reporting. The generated plan and shards remain beneath ignored `.cache/`; they contain no image binaries and have no publication effect.

Review one shard at a time in `docs/review.html`, for example `.cache/cover-review/batches/cover-0001.candidates.json`. Its exported ledger retains the original full queue's `queue_inputs`, so partial ledgers from separate batches can be merged against the full queue with `merge-reviews`.

For an intentionally small audit, the browser can still open `.cache/cover-review/candidates.json` directly. The page remains offline with respect to candidate data and exports a `*.reviews.json` ledger. To resume, reopen the same full or batch queue and use **Resume / merge cover reviews**; exact duplicate decisions are retained once and any same-key conflict rejects the whole import.

Create an empty review ledger only when reviewing the JSON manually instead:

```bash
python3 scripts/cover_source_pipeline.py init-review
```

Multiple browser or manual partial ledgers can also be reconciled without editing JSON by hand:

```bash
python3 scripts/cover_source_pipeline.py merge-reviews \
  --input ~/Downloads/candidates.reviews.json \
  --input ~/Downloads/candidates-second.reviews.json \
  --output .cache/cover-review/reviews.json \
  --force
```

The merge requires identical `queue_inputs`, a current candidate fingerprint for every decision, and exact equality for duplicate candidate keys. Conflicting decisions and multiple approved covers for one Clark record fail without writing output. `--force` is required when replacing an existing ledger.

Probe a small, resumable batch. Already cached positive and negative results are skipped:

```bash
python3 scripts/cover_source_pipeline.py probe \
  --plan .cache/cover-review/batch-plan.json \
  --batch-id cover-0001 \
  --limit 10
```

Run the same command again to continue with the next uncached candidates in that batch. The shared probe cache is still keyed by the full queue candidate fingerprint, so moving between batches does not discard previous work. The result reports selected candidates, attempted requests, reusable terminal results, and remaining candidates. No candidate outside the validated batch is requested.

`--limit` cannot exceed 100 and `--min-interval` cannot be less than three seconds. `--force` reprobes cached results; it should be used sparingly. A probe cache whose `queue_inputs` differ from the current queue is rejected rather than silently reused.

Inspect overall progress without network access or publication:

```bash
python3 scripts/cover_source_pipeline.py status
```

Or inspect a single planned batch:

```bash
python3 scripts/cover_source_pipeline.py status \
  --plan .cache/cover-review/batch-plan.json \
  --batch-id cover-0001
```

The report separates missing, stale, positive, negative, and transient probe states; current review decisions; fully reviewed records; valid approval gates; and records presently eligible for publication. It does not read or write image binaries and does not alter a manifest. Both the status command and publisher require probe and review state to carry the current queue-input identity.

A review decision is keyed by the queue's `candidate_key`:

```json
{
  "candidate_fingerprint": "sha256:…",
  "decision": "approve",
  "reviewer": "Reviewer name",
  "reviewed_at": "2026-07-13T20:00:00Z",
  "exact_edition_confirmed": true,
  "visual_check": true,
  "rights_scope": "remote_reference_only",
  "evidence_note": "ISBN, edition statement, publisher, date, and visible cover text compared with the Clark record."
}
```

The browser records the actual current second-precision UTC time for every new or edited decision. A resumed decision retains its original reviewer and timestamp.

Build a reviewed-only preview in `.cache`. This uses the default merged ledger; for a single browser download, pass `--reviews ~/Downloads/candidates.reviews.json` instead:

```bash
python3 scripts/cover_source_pipeline.py publish
```

Publishing to a browser-readable path requires an explicit boundary crossing:

```bash
python3 scripts/cover_source_pipeline.py publish \
  --output docs/data/reviewed_cover_references.json \
  --allow-docs-output
```

The generated reviewed-reference file contains no rejected, deferred, unreviewed, ambiguous, or title-matched candidates. Import it into the compact runtime index and lazy provenance manifest with:

```bash
python3 scripts/build_cover_index.py \
  --reviewed-references docs/data/reviewed_cover_references.json
```

`build_cover_index.py` validates the reviewed schema again, verifies that every catalog ID exists, rechecks each ISBN against the Clark record, requires the Open Library edition ID and Cover ID to agree with their source/image URLs, and requires complete named-review and probe evidence. The publisher carries an explicit gate receipt containing the human edition/visual confirmations, rights scope, and bounded positive-probe fingerprint, timestamp, and dimensions; the index builder independently revalidates each field and its agreement with the published image and provenance evidence. It also recomputes the candidate fingerprint from the Clark ISBN set, matched ISBNs, Open Library edition ID, Cover ID, and provider-dump checksum, so a stale or edited approval fails closed. A reviewed reference overrides a legacy provider reference for the same catalog record and becomes `status: "verified"` in both `cover_index.json` and `cover_provenance.json`. The 13 legacy references remain `status: "provider_reference"` until they pass this same review path; they are never silently upgraded.

The cover index records the reviewed-reference filename and SHA-256 checksum so a deployment can be traced back to the exact approved input. Omitting `--reviewed-references` preserves the safe legacy-only build.

## Deterministic tests

The pipeline self-test and the dedicated batch suite are local and make no network requests:

```bash
python3 scripts/cover_source_pipeline.py self-test
python3 scripts/cover_source_pipeline_unit_tests.py
```

The batch suite exercises deterministic record-atomic packing, exact coverage, tamper and stale-state rejection, browser queue shards, bounded selection and resume, queue-bound probe caches, offline status reporting, and publisher state isolation.

## Rights, attribution, and caching policy

Open Library's [licensing statement](https://openlibrary.org/developers/licensing) says the Internet Archive does not assert new proprietary rights over Open Library database material and warns that contributions may still carry existing rights issues. That is not an open-content license for the underlying cover artwork.

Accordingly:

- ShelfSignals stores and publishes provider-hosted references and source links, not cover image binaries.
- A cover is labeled as an external exact-edition surrogate, never as a photograph of Clark's physical copy.
- The public manifest records `underlying_cover_rights_not_established`, `provider_hosted_reference_only`, and `binary_cache_allowed: false`.
- Optical measurements from a remote image may describe pixels only. They cannot establish book thickness, spine geometry, cloth, paper, wear, jacket presence, or the condition of Clark's copy.
- A locally cached derivative requires record-level evidence of an open license, public-domain basis, or written permission, plus creator, source citation, license/permission citation, named review, source checksum and dimensions, derivative checksums and dimensions, steps, and attribution text. The implemented fail-closed workflow is documented in [Clark and rights-cleared cover ingest](./cleared-cover-ingest.md).

Google Books is available only as a separate, temporary exact-ISBN research-lead workflow. Current Google cache, content, and branding requirements prevent treating its API output as a permanent precomputed public cover database. The tool stores no image binary, honors positive response freshness with a 24-hour hard cap, and has no publisher adapter. See [Google Books exact-ISBN cover leads](./google-books-cover-source.md).

For performance, the browser should load a compact reviewed-reference index first and fetch detailed provenance only when a record drawer opens. Remote thumbnails can use normal HTTP caching, lazy loading, and decode hints. The application must retain the unresolved state when a provider request fails; it must never substitute a cover from a different edition merely to fill the grid.

## Source expansion rules

A new provider is eligible only if its documentation supports programmatic or bulk access and its operational limits can be honored. Before implementation, document:

- stable edition-level identifiers and exact-match rules;
- API, dump, or feed terms and request limits;
- image attribution and redistribution/derivative permissions;
- negative-result and placeholder behavior;
- cache retention rules;
- source URL, retrieval time, and content checksum strategy.

Search-engine results, retailer pages, publisher pages without an API/feed agreement, and Common Crawl URL discovery are not edition evidence. They may create a private research lead, but they cannot create a public cover reference without an exact identifier in the source payload, retained provenance, rights review, and human approval.
