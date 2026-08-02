# ShelfSignals Digital Receipts

Digital Receipts are client-side JSON exports for carrying a ShelfSignals reading list or filtered view between browser sessions. The primary `2.0.0` interface supports shelf export and restore without an account or backend, while keeping Sekula and Jefferson selections in separate collection namespaces.

## Current schema

```json
{
  "schema": "shelfsignals-receipt@2",
  "createdAt": "2026-08-01T00:00:00.000Z",
  "app": {
    "name": "ShelfSignals",
    "channel": "primary",
    "version": "2.0.0"
  },
  "dataset": {
    "id": "jefferson",
    "name": "Thomas Jefferson's Library",
    "corpus": "catalog",
    "indexHash": "dc446e2530f3946719d927a82ffe6bbe93deccd3cd85b06bc81b693656954c92"
  },
  "mode": "shelf",
  "items": ["jefferson-loc-89f398bf-0d30-50a0-8129-3ecccdc869de"],
  "filters": {},
  "annotations": {},
  "hash": {
    "alg": "sha256",
    "value": "…"
  },
  "receiptId": "SS-XXXX-XXXX-XXXX"
}
```

The export intentionally stores stable item IDs rather than trusting stale embedded catalog metadata. Receipt v2 also records the collection ID, active corpus, and source hash already validated by the active compact dataset. Restore first verifies receipt integrity, collection, corpus, and exact source hash, then resolves IDs against the currently loaded dataset and reports missing items.

`dataset.indexHash` identifies the source snapshot used when the receipt was created. It supports auditing and explains later missing records; it is not a signature and is not by itself a promise that two snapshots have identical metadata.

## Integrity

`docs/js/receipt.js` serializes the payload with sorted object keys and computes SHA-256 through WebCrypto. Restore verifies the hash before checking collection identity or changing My Shelf. The hash detects accidental or deliberate modification; it is not a digital signature and does not establish authorship.

## Collection isolation

Each collection has its own localStorage key and manifest-supplied receipt filename:

| Collection | Shelf key | Receipt schema accepted |
|---|---|---|
| Allan Sekula Library | `shelfsignals_shelf` | matching `@2`, plus legacy `@1` |
| Thomas Jefferson catalog beta | `shelfsignals_shelf:jefferson` | matching `@2` only |

A `shelfsignals-receipt@2` file restores only when `dataset.id`, `dataset.corpus`, and `dataset.indexHash` match the active package. Legacy Jefferson v2 receipts without `dataset.corpus` are interpreted only as Phase 1 `catalog` receipts. Wrong-collection, wrong-corpus, and stale-dataset receipts are rejected before either shelf is mutated. Catalog and historical IDs coexist under the Jefferson collection key; restoring one corpus replaces only that corpus slice and preserves saved IDs from its sibling corpus.

## Export and restore

1. Add records to My Shelf.
2. Open My Shelf and choose **Digital Receipt**.
3. Keep or share the downloaded JSON file.
4. Choose **Restore receipt** in the primary interface.
5. Select the JSON file. ShelfSignals verifies the hash, confirms that its collection matches the active view, and resolves its item IDs.

Text-list export is also available and includes a record's dataset-supplied catalog URL when one is present. ShelfSignals does not synthesize a catalog link when the active projection has no validated URL.

## URL fragments

The module retains base64url encode/decode helpers for compatibility experiments. Large shelves can exceed practical URL limits, so the primary interface uses ordinary query parameters for browse state and JSON files for shelf transfer.

## QR status

QR export is disabled. The previous implementation returned a placeholder SVG rather than a functional QR symbol. `generateQRCode()` now reports `available: false`; interfaces must not present it as a completed feature. A future implementation should bundle and test a lightweight encoder locally instead of calling a remote service.

## Privacy

- Receipt generation and verification run in the browser.
- No receipt is uploaded by ShelfSignals.
- The receipt contains the collection ID, corpus ID, dataset hash, selected record IDs, and optional filter/annotation state; it contains no account identifier.
- Users control where exported files are stored or shared.

## Compatibility

New exports use `shelfsignals-receipt@2`. The primary importer accepts v2 only for the active dataset identity; it also accepts `shelfsignals-receipt@1` with an `items` array **only while Sekula is active**. A v1 receipt has no collection identity and is therefore never interpreted as Jefferson data.

Unknown schemas, invalid JSON, hash mismatches, and wrong-collection receipts are rejected. Items that no longer exist in the active dataset are reported and omitted from the restored shelf. Legacy receipt support does not merge, migrate, or copy the Sekula shelf into Jefferson storage.
