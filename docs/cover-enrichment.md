# Book visual enrichment and attribution

ShelfSignals resolves cover references before deployment. The browser reads a committed manifest and does not query third-party bibliographic APIs for every visitor or every record.

## Files

- Canonical input: `docs/data/sekula_index.json`
- Generator: `scripts/enrich_book_visuals.py`
- Versioned output: `docs/data/book_visuals.json`
- Local metadata cache: `.cache/book_visuals-openlibrary.json` (ignored by Git)
- Hero selection: `docs/data/featured_items.json`

No third-party cover binary is written to the repository. The cache contains lookup metadata and outcomes, not images.

## Provider policy

The initial optional provider is [Open Library's documented Books and Covers APIs](https://openlibrary.org/dev/docs/api/covers). The script uses API endpoints rather than scraping pages.

Provider use is conservative:

1. Normalize and checksum ISBN-10/13 values.
2. Normalize OCLC and LCCN control numbers.
3. Query exact identifiers in ISBN, OCLC, then LCCN order.
4. Require one unambiguous provider candidate whose returned identifiers agree with the query.
5. Require an HTTPS Open Library cover URL.
6. Probe a bounded response prefix, require an image content type, parse dimensions, and reject tiny or placeholder-like responses.
7. Cache positive, negative, ambiguous, and error outcomes.

Title-only matching is not used. A plausible image is not enough.

## Small dry run

From the repository root:

```bash
python3 scripts/enrich_book_visuals.py --limit 5 --dry-run
```

`--dry-run` performs resolution and reports counts without changing the output or cache.

To test normalization and schema logic without network access:

```bash
python3 scripts/enrich_book_visuals.py --self-test
python3 scripts/enrich_book_visuals.py --provider none --limit 1 --dry-run
```

## Refresh a bounded sample

```bash
python3 scripts/enrich_book_visuals.py --limit 100
```

The script preserves valid items outside the selected limit and writes the manifest and metadata cache atomically. `--force` bypasses reusable output and provider-cache results for the selected records:

```bash
python3 scripts/enrich_book_visuals.py --limit 100 --force
```

Other paths can be supplied explicitly:

```bash
python3 scripts/enrich_book_visuals.py \
  --input docs/data/sekula_index.json \
  --output docs/data/book_visuals.json \
  --cache .cache/book_visuals-openlibrary.json \
  --provider openlibrary \
  --limit 100
```

Do not casually run an uncached full-collection refresh against a public service. The current dataset contains 11,176 records; public rate limits and provider operations must be respected. Prefer bounded, resumable batches and preserve the cache.

## Manifest contract

The browser accepts `shelfsignals-book-visuals@1`. Resolved items include:

- Alma record ID key;
- `status: "resolved"` and `lookup_status: "positive"` for current parser compatibility;
- HTTPS `image_url` and `thumbnail_url`;
- provider and exact source identifier;
- source/work URL;
- `match_method` and confidence;
- checked timestamp;
- dimensions/aspect ratio when validated;
- attribution;
- a normalized-identifier checksum in provenance.

The top-level manifest records generator version, input SHA-256, provider endpoint/policy, generated time, and summary counts. Negative, ambiguous, and error items remain useful pipeline evidence but are ignored by the browser's visual resolver.

## Browser validation and failure behavior

`docs/js/visuals.js` rejects an incompatible manifest and only accepts HTTPS image URLs from allowlisted providers. Images are lazy-decoded outside the hero. If a remote request fails, the image element is removed and the deterministic metadata-derived book remains visible.

Fallback books use:

- the real title and recorded creator;
- publication date and call number;
- material type;
- physical height parsed from `formats` when possible;
- a color hash derived from the stable record ID.

They are interface objects, not simulated scans.

## Committed sample and hit rate

The `2.0.0` manifest contains 13 resolved, exact-ISBN Open Library references selected for the featured experience: 13 checked, 13 resolved, 0 rejected, and 0 ambiguous. This is a curated enrichment sample, not a claim of 100% collection coverage. Relative to the full 11,176-record dataset, committed cover coverage is approximately 0.12%; every other record has a complete visual fallback.

The enrichment script's live bounded audit also demonstrated positive, negative, and error-free resolution paths. Operational hit rates will vary by selected record range and provider availability and should be reported from the generated manifest summary rather than extrapolated.

## Licensing and attribution

ShelfSignals stores provider-hosted references and attribution metadata. It does not claim ownership of cover art and does not redistribute third-party image files. Open Library availability does not itself grant a new copyright license; downstream users remain responsible for provider terms and applicable law.

If a new provider is added, document its API terms, attribution requirements, credential model, request limits, identifier matching rules, and redistribution constraints before committing references.
