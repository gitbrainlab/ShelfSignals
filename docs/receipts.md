# ShelfSignals Digital Receipts

Digital Receipts are client-side JSON exports for carrying a ShelfSignals reading list or filtered view between browser sessions. The primary `2.0.0` interface supports shelf export and restore without an account or backend.

## Current schema

```json
{
  "schema": "shelfsignals-receipt@1",
  "createdAt": "2026-07-12T00:00:00.000Z",
  "app": {
    "name": "ShelfSignals",
    "channel": "primary",
    "version": "2.0.0"
  },
  "dataset": {
    "name": "Allan Sekula Library",
    "indexHash": "sha256-or-status"
  },
  "mode": "shelf",
  "items": ["alma991002035079708431"],
  "filters": {},
  "annotations": {},
  "hash": {
    "alg": "sha256",
    "value": "…"
  },
  "receiptId": "SS-XXXX-XXXX-XXXX"
}
```

The export intentionally stores stable item IDs rather than trusting stale embedded catalog metadata. Restore resolves those IDs against the currently loaded dataset and reports missing items.

## Integrity

`docs/js/receipt.js` serializes the payload with sorted object keys and computes SHA-256 through WebCrypto. Restore verifies the hash before changing My Shelf. The hash detects accidental or deliberate modification; it is not a digital signature and does not establish authorship.

## Export and restore

1. Add records to My Shelf.
2. Open My Shelf and choose **Digital Receipt**.
3. Keep or share the downloaded JSON file.
4. Choose **Restore receipt** in the primary interface.
5. Select the JSON file. ShelfSignals verifies the hash and resolves its item IDs.

Text-list export is also available and includes each record's dataset-supplied Clark catalog URL.

## URL fragments

The module retains base64url encode/decode helpers for compatibility experiments. Large shelves can exceed practical URL limits, so the primary interface uses ordinary query parameters for browse state and JSON files for shelf transfer.

## QR status

QR export is disabled. The previous implementation returned a placeholder SVG rather than a functional QR symbol. `generateQRCode()` now reports `available: false`; interfaces must not present it as a completed feature. A future implementation should bundle and test a lightweight encoder locally instead of calling a remote service.

## Privacy

- Receipt generation and verification run in the browser.
- No receipt is uploaded by ShelfSignals.
- The receipt contains selected record IDs and optional filter/annotation state; it contains no account identifier.
- Users control where exported files are stored or shared.

## Compatibility

The primary importer accepts `shelfsignals-receipt@1` with an `items` array. Unknown schemas, invalid JSON, and hash mismatches are rejected. Items that no longer exist in the dataset are reported and omitted from the restored shelf.
