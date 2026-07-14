# Clark and rights-cleared cover ingest

`scripts/ingest_cleared_covers.py` is the publication gate for locally supplied cover photographs. It accepts only a photograph of the identified Clark copy or a rights-cleared photograph of an exact edition. It never searches for or downloads an image. The source original stays in private storage; only two bounded, metadata-stripped WebP derivatives can enter `docs`.

This route has priority over external provider references because it can establish both object identity and the authority to publish a local derivative. Priority is not automatic evidence: every item must still pass the catalog, identity, file, rights, and named-review gates below.

## What the gate requires

Every `shelfsignals-cleared-cover-intake@1` item is bound to the current canonical `sekula_index.json` bytes and must contain:

- the exact Alma catalog ID;
- the current catalog title, call number, catalog URL, and a checksum of the versioned record-identity packet;
- either `provider: clark` with `scope: clark_copy`, or `provider: licensed` with `scope: exact_edition`;
- the private source file's SHA-256 checksum, byte count, decoded format, oriented pixel width, and oriented pixel height;
- an explicit front-cover confirmation and Clark-copy or exact-edition confirmation;
- the catalog ID as the Clark-copy match, or at least one exact ISBN, OCLC, or LCCN match for an exact-edition asset;
- a named reviewer, second-precision UTC review time, and evidence note;
- a rights basis of `institution_permission`, `open_license`, or `public_domain`;
- explicit `public_display: true` and `derivatives_allowed: true` decisions;
- a stable license or permission reference, an HTTPS evidence URL, rights holder, required credit line, and evidence note; and
- a source/asset identifier, creator, date, and HTTPS source record.

Unknown fields are rejected. False or missing booleans are rejected. Placeholder reviewers are rejected. A stale catalog checksum, changed record fingerprint, identifier mismatch, path traversal, symlinked source, changed source bytes, decoded-dimension mismatch, animation, oversized source, or absent rights evidence stops the entire run before a reviewed-reference manifest is written.

For a Clark photograph, `source.source_reference_url` must be the record's exact Clark catalog URL. The institutional capture or asset number belongs in `source.source_id`. For a licensed exact-edition asset, the source URL must cite the source record that carries the exact-edition evidence.

## Pillow dependency

Source inspection and derivative generation require Pillow with WebP support. Use an isolated environment; do not install into the system Python:

```bash
python3 -m venv .cache/cover-ingest-venv
. .cache/cover-ingest-venv/bin/activate
python -m pip install Pillow
```

The schema, identifier, checksum, rights, and publication-boundary tests remain Pillow-free and run in the minimal repository environment:

```bash
python3 scripts/ingest_cleared_covers.py self-test
python3 scripts/cleared_cover_ingest_unit_tests.py
```

## Operator workflow

Keep original captures outside `docs`. The example private directory below is illustrative; use the approved institutional storage location.

First scaffold one intake entry. The scaffold decodes the local image and writes the exact catalog identity and file evidence, but intentionally leaves all human and rights gates false or marked `REPLACE`. It cannot be ingested until an operator completes them.

```bash
python3 scripts/ingest_cleared_covers.py scaffold \
  --catalog-id ALMA_CATALOG_ID \
  --source-root /approved/private/cover-captures \
  --source-file RELATIVE_SOURCE_FILENAME \
  --provider clark \
  --scope clark_copy \
  --output .cache/cover-review/ALMA_CATALOG_ID.intake.json
```

For a cleared external asset, use `--provider licensed --scope exact_edition`, replace the source URL, and add one or more exact identifiers from the canonical Clark record. Never approve a title-only or visually plausible match.

Open the scaffold, replace every placeholder, and set an attestation or rights boolean to `true` only after the named reviewer has inspected the cited evidence. Then run the read-only validation pass:

```bash
python3 scripts/ingest_cleared_covers.py validate \
  --intake .cache/cover-review/ALMA_CATALOG_ID.intake.json \
  --source-root /approved/private/cover-captures
```

Validation decodes and checks every source but writes nothing. Ingest only after it succeeds:

```bash
python3 scripts/ingest_cleared_covers.py ingest \
  --intake .cache/cover-review/ALMA_CATALOG_ID.intake.json \
  --source-root /approved/private/cover-captures \
  --references-output .cache/cover-review/cleared-cover-references.json
```

Ingest validates the full batch before writing assets. It refuses any original beneath `docs`. It then writes only:

- `images/covers/{catalog_id}/{asset_fingerprint}/cover-thumbnail.webp`, bounded to 480 × 640 pixels; and
- `images/covers/{catalog_id}/{asset_fingerprint}/cover-display.webp`, bounded to 1280 × 1600 pixels.

Images are never upscaled. EXIF orientation is applied, alpha is composited on white, metadata is omitted, and both outputs are converted to RGB WebP. The immutable asset-directory fingerprint binds the original SHA-256, declared source dimensions and format, encoder version, metadata policy, and exact derivative profiles. Existing bytes at the same immutable path must match or the run fails. A partial rendering failure can leave an unreferenced immutable file, but it cannot expose a reviewed reference.

The output `shelfsignals-cleared-cover-references@1` manifest contains no source original. Before writing it, the ingest command reopens each WebP, recomputes its checksum and byte count, and independently reads its dimensions. The default manifest stays in ignored `.cache`. Writing that detailed reference itself beneath `docs` is refused unless the operator adds `--allow-docs-output` after a separate review of its public provenance fields.

## Public-index boundary

Inspect the reviewed-reference manifest and the generated derivatives. Then pass it to the offline index builder:

```bash
python3 scripts/build_cover_index.py \
  --cleared-references .cache/cover-review/cleared-cover-references.json
```

The index builder repeats the catalog, identifier, rights, reviewer, gate-receipt, fingerprint, local-path, SHA-256, byte-count, WebP-format, and decoded-dimension checks. It does not trust the ingest output merely because the generating script wrote it. When both external Open Library reviews and cleared local images are available, both inputs may be supplied:

```bash
python3 scripts/build_cover_index.py \
  --reviewed-references .cache/cover-review/reviewed-cover-references.json \
  --cleared-references .cache/cover-review/cleared-cover-references.json
```

A cleared Clark-copy image overrides all provider references for the same record. A cleared exact-edition image also overrides a remote provider reference. The compact index records `provider`, `scope`, rights basis, credit line, review decision, local-derivative cache policy, source-manifest filename, and source-manifest SHA-256. The lazy provenance record retains the source-file checksum and dimensions, both derivative checksums and dimensions, source citation, license/permission citation, human evidence, and both fingerprints.

Omitting `--cleared-references` preserves the current provider-only build. Merely placing an image beneath `docs/images/covers` has no effect: an asset is displayable only after the reviewed-reference and index-builder gates succeed.

## Rights and provenance rules

`institution_permission` means the cited written permission explicitly authorizes public display and local derivatives. `open_license` means the cited license covers the asset and intended derivative use. `public_domain` means the cited evidence establishes that status for the asset; age, search-result availability, or an unlabeled repository page is not sufficient.

The public credit line must be copied from the controlling permission or license. The evidence URL is a citation, not a substitute for reading the permission. If the rights basis changes, rebuild the intake from reviewed evidence; never edit a generated reference to make it pass. No source original, private filesystem path, access token, or unpublished permission document is placed in the public provenance manifest.

## Operational verification

```bash
python3 -m py_compile \
  scripts/cleared_cover_contract.py \
  scripts/ingest_cleared_covers.py \
  scripts/build_cover_index.py
python3 scripts/ingest_cleared_covers.py self-test
python3 scripts/ingest_cleared_covers.py encoder-self-test
python3 scripts/cleared_cover_ingest_unit_tests.py
python3 scripts/cover_source_pipeline_unit_tests.py
python3 scripts/build_cover_index.py --self-test
```

The dedicated unit suite covers exact catalog rebinding, source-file checks, Clark-copy and exact-edition identifier rules, rights and review gates, unknown fields, traversal, derivative byte reopening, dimension parsing, stale fingerprints, and end-to-end promotion into a verified Clark-copy index state. `encoder-self-test` creates a temporary fixture, executes the real Pillow/WebP encoder, verifies bounds, RGB output, single-frame output, and stripped EXIF, then removes the fixture without touching `docs`. Neither check uses a downloaded or invented production asset.
