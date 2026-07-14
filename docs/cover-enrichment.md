# Book visual enrichment and attribution

ShelfSignals resolves cover references before deployment. The production browser reads the compact `cover_index.json` contract and never queries a bibliographic API per visitor. `book_visuals.json` is retained only as a 13-record legacy migration input; it is not the production cover contract and none of its references is a named-human approval.

## Files

- Canonical input: `docs/data/sekula_index.json`
- Collection-scale source pipeline: `scripts/cover_source_pipeline.py`
- Production index generator: `scripts/build_cover_index.py`
- Clark/cleared local ingest: `scripts/ingest_cleared_covers.py` and `scripts/cleared_cover_contract.py`
- Compact production output: `docs/data/cover_index.json`
- Lazy production provenance: `docs/data/cover_provenance.json`
- Private candidate/review state: `.cache/cover-review/` (ignored by Git)
- Private deterministic batch plan and browser shards: `.cache/cover-review/batch-plan.json` and `.cache/cover-review/batches/`
- Legacy bounded resolver/analyzer: `scripts/enrich_book_visuals.py`, `scripts/analyze_cover_visuals.py`, and `docs/data/book_visuals.json`
- Hero selection: `docs/data/featured_items.json`

No uncleared third-party cover binary is written to the repository. A local WebP derivative may enter `docs/images/covers` only through the separate [Clark and rights-cleared cover ingest](./cleared-cover-ingest.md), which requires record identity, named review, public-display authority, derivative authority, source and derivative checksums, and a cited license or permission.

The analyzer downloads only the already allowlisted, exact-ISBN sample into an ignored local cache. It records source pixels, actual aspect ratio, checksum, dominant colors, luminance, contrast, entropy, gradient energy, high-frequency energy, and border-to-inner optical variation. These are measurements of a cover image—not claims about a copy's paper, cloth, wear, binding, or tactile texture.

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

## Legacy resolver: small dry run

From the repository root:

```bash
python3 scripts/enrich_book_visuals.py --limit 5 --dry-run
```

`--dry-run` performs resolution and reports counts without changing the output or cache.

To test normalization and schema logic without network access:

```bash
python3 scripts/enrich_book_visuals.py --self-test
python3 scripts/enrich_book_visuals.py --provider none --limit 1 --dry-run
python3 scripts/build_cover_index.py --check
```

The final command rebuilds both public cover manifests in memory using their committed generation time and fails if either artifact is stale relative to the current catalog, migration input, or builder contract. CI runs the same check.

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

## Production manifest and review contract

The browser accepts `shelfsignals-cover-index@1`. Records absent from its sparse `items` object receive the universal unresolved state and the exact visible label **Cover not yet verified for this edition**. Displayable items are either:

- `provider_reference`: exact-edition remote reference, visual review pending; or
- `verified`: either a reviewed remote reference whose named-review and provider probe receipts passed, or a checksum-verified local Clark-copy/exact-edition derivative whose identity and rights gates passed.

The heavier `shelfsignals-cover-provenance@1` artifact records:

- Alma record ID key;
- display/review status and exact source scope;
- HTTPS `image_url` and `thumbnail_url`;
- provider and exact source identifier;
- source/work URL;
- `match_method` and confidence;
- checked timestamp;
- dimensions/aspect ratio when validated;
- attribution;
- a normalized-identifier checksum in provenance.

The top-level manifest records generator version, catalog SHA-256, record count, policy, generated time, and summary counts. Candidate discovery and human decisions remain private until `cover_source_pipeline.py publish` produces remote reviewed references or `ingest_cleared_covers.py ingest` produces local derivative references. `build_cover_index.py` independently revalidates either source. See [Cover source pipeline](./cover-source-pipeline.md) and [Clark and rights-cleared cover ingest](./cleared-cover-ingest.md).

## Browser validation and failure behavior

`docs/js/covers.js` rejects stale catalog identity, unsafe providers, malformed review evidence, or blocked rights. Both the compact index and the lazy detailed provenance manifest must carry the active canonical catalog SHA-256 and record count. Images are lazy-decoded outside the hero. If a remote request fails, the image element is removed and the hero, card, and open detail drawer all return to the exact unresolved phrase; failed URLs are memoized for the session.

Fallback books use:

- the real title and recorded creator;
- publication date and call number;
- material type;
- physical height parsed from `formats` when possible;
- a color hash derived from the stable record ID.

They are interface objects, not simulated scans.

Physical dimensions and side-profile treatment are documented separately in [Physical profiles](./physical-profiles.md). The strict Physical shelf never consumes cover pixels, cover aspect ratios, optical analysis, or provider geometry.

## Committed sample and hit rate

The current production index contains 0 verified covers, 13 exact-ISBN Open Library `provider_reference` entries awaiting visual review, and 11,163 unresolved editions. This is not a claim of collection coverage. The local June 2026 Open Library dump audit found exact-ISBN cover candidates for 6,313 of 11,176 records (56.49%); those candidates still require the private probe and human review workflow before publication. Every unresolved record retains a real-metadata surrogate and its exact unresolved label.

The enrichment script's live bounded audit also demonstrated positive, negative, and error-free resolution paths. Operational hit rates will vary by selected record range and provider availability and should be reported from the generated manifest summary rather than extrapolated.

## Licensing and attribution

ShelfSignals stores provider-hosted references and attribution metadata. It does not claim ownership of cover art and does not redistribute third-party image files. Open Library availability does not itself grant a new copyright license; downstream users remain responsible for provider terms and applicable law.

If a new provider is added, document its API terms, attribution requirements, credential model, request limits, identifier matching rules, and redistribution constraints before committing references.
