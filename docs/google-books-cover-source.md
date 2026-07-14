# Google Books exact-ISBN cover leads

Last policy check: 2026-07-14

`scripts/google_books_cover_source.py` is a bounded, resumable research tool for finding additional exact-ISBN cover leads in the Google Books Volumes API. It is intentionally separate from the public cover index. It writes only to an ignored private `.cache/` directory, never downloads an image, never treats a title or author similarity as an edition match, never commits an API key, and never publishes a result.

This source is supplementary. Clark copy photography and rights-cleared assets remain preferable because a Google Books record cannot establish the jacket, binding, texture, wear, or side profile of the physical copy held at Clark.

## Official-source findings and resulting constraints

Only current first-party Google documentation was used for this implementation:

- Google documents public-data identification with an API key or OAuth token and the case-sensitive `isbn:` query operator in [Using the API](https://developers.google.com/books/docs/v1/using). The script queries only `q=isbn:{canonical ISBN-13}` and requires the returned volume's own `industryIdentifiers` to contain that exact catalog ISBN.
- The official [Volume resource](https://developers.google.com/books/docs/v1/reference/volumes) defines stable Volume IDs, `ISBN_10` / `ISBN_13` industry identifiers, provider image links, page count, print type, and raw physical dimensions including height, width, and thickness. These raw physical fields are kept only as private provider-volume evidence. They are never described as measurements of Clark's copy and are never inferred from cover pixels.
- Google's [performance guidance](https://developers.google.com/books/docs/v1/performance) recommends gzip and partial responses. Requests use both and cap each response at one megabyte.
- The [Google APIs Terms of Service](https://developers.google.com/terms) says developer credentials may not be embedded in open-source projects, restricts permanent copies/databases and cache retention beyond response headers, warns that returned content may have third-party intellectual-property rights, and requires documented attribution. The tool therefore reads the key only from an environment variable, stores no response body or image binary, retains minimal result evidence only while response headers grant positive freshness, and removes expired API content.
- The Books-specific [Terms of Service](https://developers.google.com/books/terms) requires removal of allegedly infringing Books API content when required by law or requested by Google. Every candidate records that a removal process is required before public use.
- The [Google Books branding guidelines](https://developers.google.com/books/branding) require Google attribution, adjacent “Powered by Google” branding for results, prominent per-result Google Books links, preservation of provider results, and compliance with current branding. The private queue retains provider result position and the required link/attribution contract. The current local review page is not yet a compliant renderer for this schema.

The Terms, cache headers, and branding rules can change. Re-check all linked first-party documents before enabling a public adapter.

## Safety model

The workflow fails closed at each boundary:

1. The plan contains only checksum-valid ISBNs present in `docs/data/sekula_index.json`. ISBN-10 and ISBN-13 forms for the same identifier collapse to one canonical ISBN-13 query.
2. The request uses the official Volumes endpoint, `printType=books`, a maximum of ten provider results, gzip, and a named user agent. It uses the full Volume projection only because page count and dimensions are not documented as LITE fields, then bounds transfer with a narrow `fields` selector and one-megabyte response ceiling.
3. A result becomes a candidate only if its own `industryIdentifiers` contains the exact query ISBN and that ISBN belongs to the Clark record.
4. A result must carry a provider-hosted cover URL. The URL remains text evidence; the CLI does not request it.
5. API result evidence is retained only when the response has an explicit positive `max-age` or future `Expires` value. `no-store`, zero freshness, absent freshness, and malformed cache headers produce `retention_blocked` without retaining candidate content. Retention is hard-capped at 24 hours even when a provider grants longer freshness.
6. State is bound to the catalog checksum, complete deterministic query plan, and per-query fingerprints. Edited, reordered, truncated, stale, or cross-plan state fails.
7. Queue construction recomputes each candidate fingerprint, exact ISBN evidence, provider URL/ID agreement, rights state, and physical-evidence scope. Tampering fails before output.
8. All candidates remain `review_required: true`, `public_eligible: false`, and `publication_effect: none`. There is no publisher command.

The tool does not interpret a Google Books `publicDomain` access flag as an open license for cover artwork. It records the access flag as provider metadata while keeping `underlying_cover_rights: not_established` and `binary_download_or_cache_allowed: false`.

## Private workflow

All commands below are local except `discover`.

Audit the current real catalog scope without writing or using the network:

```bash
python3 scripts/google_books_cover_source.py audit
```

Create a deterministic private plan:

```bash
python3 scripts/google_books_cover_source.py plan
```

Create and restrict a Google Books API key in the Google Cloud console, then place it in the process environment. Do not add it to a command, JSON file, `.env` file in the repository, or commit:

```bash
export GOOGLE_BOOKS_API_KEY='…'
```

Run a small batch. The default is ten queries at no more than one request every two seconds; the hard maximum is 50 queries per invocation and the interval cannot be less than one second:

```bash
python3 scripts/google_books_cover_source.py discover --limit 10
```

Each completed request is written atomically to `.cache/google-books-cover-source/state.json`, so rerunning the command resumes at the next pending query. A transient network, server, credential, quota, or rate-limit error stops the current batch rather than accelerating requests. `retention_blocked` and permanent errors are not retried automatically; retry them only after reviewing the cause:

```bash
python3 scripts/google_books_cover_source.py discover --limit 10 --retry-blocked
```

Inspect progress without network access:

```bash
python3 scripts/google_books_cover_source.py status
```

Rebuild the queue from currently fresh private evidence:

```bash
python3 scripts/google_books_cover_source.py queue
```

Remove expired API-derived fields and rebuild the queue:

```bash
python3 scripts/google_books_cover_source.py purge
```

The ignored outputs are:

- `.cache/google-books-cover-source/plan.json`: deterministic real-catalog query plan; no credentials;
- `.cache/google-books-cover-source/state.json`: resumable minimal API evidence with cache expiry; no response bodies or image binaries;
- `.cache/google-books-cover-source/candidates.json`: temporary, private review leads; no public effect.

The script refuses to write anywhere inside the repository except `.cache/`. It may write to an explicitly selected path outside the repository for a private operator handoff.

## Candidate evidence

Every retained lead includes:

- Clark catalog ID, exact catalog ISBN set, record title/authors/date/call number, and catalog link;
- query ISBN, provider Volume ID, provider result position, provider ISBN evidence, response checksum, ETag, credential-free API resource/query URLs, fetch time, and cache expiry;
- provider source link and unmodified provider image/thumbnail URLs as text-only remote references;
- provider title, authors, publisher, publication date, and language for human edition comparison;
- raw `pageCount`, `printType`, and `dimensions` with the explicit scope `raw_google_books_provider_volume_metadata_only`;
- “Powered by Google” and prominent-link requirements;
- unresolved underlying-cover rights, no-binary-cache policy, review requirement, and a stable fingerprint.

The physical metadata caveat is part of every candidate:

> These fields describe the exact-ISBN Google Books volume record, not Clark's physical copy, binding, jacket, texture, condition, or side profile.

## Exact adapter needed for the local review page

The queue deliberately uses `shelfsignals-google-books-cover-review-queue@1`, not the Open-Library-specific `shelfsignals-cover-review-queue@1`. The current `docs/js/review.js` validator hard-codes Open Library edition IDs, Cover IDs, hosts, URLs, and fingerprints; pretending a Google Volume is an Open Library candidate would corrupt provenance.

A future provider-neutral review adapter must make these changes without weakening the existing Open Library validator:

1. Register `shelfsignals-google-books-cover-review-queue@1` as an additional cover-review input.
2. Validate `provider: google_books`, the stable Volume ID, result position, exact canonical ISBN intersection, source and image hosts, cache validity, remote-only rights state, physical-evidence scope, and the queue's candidate fingerprint formula.
3. Keep URLs text-only under the review page's existing `img-src 'none'` and `connect-src 'none'` Content Security Policy. Reviewers should inspect a provider link in a separate authorized session; the local page must not silently fetch covers.
4. Render the current official “Powered by Google” attribution adjacent to every Google-derived result and provide its prominent `source_url`, following the branding guide. Preserve `provider_result_position`; do not mix, rerank, or imply that ShelfSignals authored provider metadata.
5. Export a provider-neutral private ledger containing provider, queue schema/fingerprint, candidate fingerprint, cache expiry, reviewer/time, exact-edition confirmation, visual-front-cover confirmation, evidence note, and `remote_reference_only` rights scope.
6. Refuse reviews and exports at or after `valid_until`. Rediscover/revalidate instead of extending or editing an expiry.
7. Keep Google and Open Library candidates separate during provider review. A later editorial reconciliation step may select at most one approved front-cover reference per Clark record while preserving every source receipt.

No adapter is added to `build_cover_index.py` by this work. A separate, explicitly approved publisher extension would need to revalidate the live Google reference, exact ISBN, current Terms/branding/removal requirements, named human review, and transport safety immediately before public output. Until that exists, the Google queue is research evidence only.

## Deterministic validation

Neither command uses the network:

```bash
python3 scripts/google_books_cover_source.py self-test
python3 scripts/google_books_cover_source_unit_tests.py
```

The unit suite covers ISBN checksums/canonicalization, real-catalog plan construction, stale/tampered state rejection, exact-provider-ISBN selection, cover URL filtering, raw physical-field scope, cache-header gates and expiry, API-key-free persisted URLs, bounded/resumable execution, transient-stop behavior, remote-only rights, attribution, adapter status, and no-publication guarantees.
