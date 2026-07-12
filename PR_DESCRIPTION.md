# ShelfSignals 2.0.0 — cinematic Allan Sekula Library browser

## Summary

This change replaces the deprecated GitHub Pages root with a cinematic, editorial, data-driven ShelfSignals interface. It preserves the former root at `/legacy/`, keeps Preview and Exhibit functional, and addresses the intent of open PR #20 without adding another redirect layer.

Every displayed catalog title, creator, date, call number, subject, note, identifier, and Clark destination is resolved from `docs/data/sekula_index.json`. Verified cover references are produced offline and attributed in a versioned manifest; missing or failed images use deterministic metadata-derived book objects.

## Primary changes

- Add the `2.0.0` root shell, cinematic CSS shelf, dynamic paths, and full-library browser.
- Add cover, spine, and list modes with a bounded 72-record render batch.
- Add full-field search plus signal, call-number class, material, decade, and experimental photo-likelihood filters.
- Add safe detail rendering, previous/next navigation, exact dataset `record_url`, and query-parameter deep links.
- Preserve My Shelf localStorage compatibility while storing stable IDs; add text export and verified receipt export/restore.
- Move v1 to `/legacy/`; retain `/preview/` and `/preview/exhibit/` with no redirect loops.
- Disable the placeholder QR option honestly.
- Tighten signal word boundaries and reject ordinary LC cutters/publication years as physical S-numbers.
- Add featured-record and book-visual manifests using real Alma IDs.
- Add a cached, conservative Open Library identifier pipeline; no cover binaries or browser secrets.
- Update interface, receipt, pipeline, operations, cover-attribution, migration, and visual-QA documentation.

## Verification

```bash
node scripts/cinematic_unit_tests.mjs
node scripts/preview_acceptance_tests.mjs
python3 scripts/enrich_book_visuals.py --self-test
python3 scripts/enrich_book_visuals.py --provider none --dry-run --limit 1
python3 scripts/browser_smoke_test.py --start-server --screenshot-dir docs/images
```

Browser coverage includes root load, real hero metadata, strict signal count changes, real-ID search, exact Clark link, detail drawer, My Shelf persistence after reload, reduced motion, forced remote-cover failure, 390px mobile, Legacy, and Exhibit. All tested routes finish without unexpected console or page errors.

## Visual QA

- `docs/images/legacy-before.png` — 1440 × 900
- `docs/images/cinematic-desktop.png` — 1440 × 900
- `docs/images/cinematic-tablet.png` — 1024 × 768
- `docs/images/cinematic-mobile.png` — 390 × 844

## Visual manifest

The committed featured sample contains 13 exact-ISBN cover references: 13 checked, 13 resolved, 0 rejected, and 0 ambiguous. That is approximately 0.12% of the full 11,176-record collection; all other records intentionally use complete metadata fallbacks.

## Known limitations

- The canonical JSON remains roughly 39 MB uncompressed (about 4 MB over ordinary HTTP compression).
- Remote cover availability is outside ShelfSignals control.
- The committed photo-likelihood values are mock heuristic outputs and are labeled experimental.
- Current `call_number` values are usually physical Sekula accession marks. A future harvest should export Primo's bibliographic call number separately for richer topical LC browsing.
- Signals remain keyword rules and should be treated as discovery aids, not item-level curatorial endorsements.
