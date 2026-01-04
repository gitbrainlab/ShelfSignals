# ShelfSignals Digital Receipts

## What is a Digital Receipt?

A **Digital Receipt** is a portable, verifiable data structure that captures:
- **User-curated collections** (selected items, filters, search state)
- **Interface configuration** (active signals, color palettes, view settings)
- **Verification metadata** (unique ID, timestamp, integrity hash)

Digital Receipts enable **take-home curation** without server storage—all data lives in the JSON file itself, which can be:
- **Downloaded** as a file
- **Shared** via QR code
- **Embedded** in URL fragments
- **Imported** to restore exact state

This is particularly valuable for:
- **Museum visitors** taking home curated collections
- **Researchers** documenting methodology and evidence
- **Librarians** sharing thematic bibliographies
- **Educators** distributing reading lists

## Key Concepts

### Portability
No server account or login required. Receipt data is **self-contained** in a JSON file that works across:
- Different devices (desktop, mobile, tablet)
- Different browsers (Chrome, Firefox, Safari)
- Different locations (online, offline, air-gapped)
- Different time periods (receipts don't expire)

### Verifiability
Every receipt includes:
- **SHA-256 hash** of canonical JSON (RFC 8785) for tamper detection
- **Unique receipt ID** (`SS-XXXX-XXXX-XXXX`) for human identification
- **Timestamp** of creation
- **Version metadata** for interface compatibility

If receipt data is altered, the hash verification will fail, alerting users to potential corruption or tampering.

### Privacy-Respecting
Receipts are **client-side only**:
- No data sent to servers (unless user explicitly uploads)
- No tracking or analytics
- No personally identifiable information (unless user adds custom notes)
- Fully GDPR-compliant (no data processing)

## Receipt Data Structure

### Core Schema

```json
{
  "receipt_id": "SS-A1B2-C3D4-E5F6",
  "version": "2.0",
  "timestamp": "2024-01-15T14:30:00.000Z",
  "collection": "Allan Sekula Library",
  "interface": "exhibit",
  
  "state": {
    "selected_items": [
      "alma991002311449708431",
      "alma991002311450008431",
      "alma991002311451708431"
    ],
    "active_signals": ["photography", "maritime"],
    "search_query": "labor history",
    "lc_class_filter": "HD",
    "photo_likelihood_filter": "Likely",
    "color_palette": "default",
    "curated_path_id": "labor-images"
  },
  
  "items": [
    {
      "id": "alma991002311449708431",
      "title": "Fish Story",
      "author": "Sekula, Allan",
      "year": "1995",
      "call_number": "TR820 .S45 1995",
      "signals": ["photography", "maritime"],
      "photo_insert_score": 85,
      "user_note": "Key text on maritime photography"
    }
  ],
  
  "verification": {
    "sha256": "a3f2e1b8c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1",
    "canonical_json_rfc8785": true,
    "verified_at": null
  }
}
```

### Field Descriptions

#### Receipt Metadata
- **`receipt_id`**: Human-readable unique identifier (format: `SS-XXXX-XXXX-XXXX`)
  - `SS` = ShelfSignals prefix
  - `XXXX` = 4-character alphanumeric segments (A-Z, 0-9)
  - Used for filename and user communication
  
- **`version`**: Receipt schema version (currently `2.0`)
  - Ensures interface compatibility when importing old receipts
  - Breaking changes increment major version
  
- **`timestamp`**: ISO 8601 UTC timestamp of receipt creation
  - Format: `YYYY-MM-DDTHH:MM:SS.sssZ`
  
- **`collection`**: Source collection name (e.g., "Allan Sekula Library")
  - Helps users track which dataset the receipt references
  
- **`interface`**: Interface type that generated the receipt (`production`, `preview`, or `exhibit`)
  - Allows interface-specific import behavior

#### State Snapshot
- **`selected_items`**: Array of item IDs (unique identifiers from source data)
  - Minimal: just IDs (full metadata fetched on import)
  - Can be empty if receipt captures filter state only
  
- **`active_signals`**: Array of signal IDs currently toggled on
  - Example: `["photography", "labor", "maritime"]`
  
- **`search_query`**: Current search text (if any)
  - Empty string if no search active
  
- **`lc_class_filter`**: LC class or subclass filter (if any)
  - Example: `"TR"`, `"TR820"`, or `null`
  
- **`photo_likelihood_filter`**: Photo likelihood bucket filter (if any)
  - Example: `"Likely"`, `"Strongly Likely"`, or `null`
  
- **`color_palette`**: Active color scheme
  - Example: `"default"`, `"colorblind"`, `"high-contrast"`
  
- **`curated_path_id`**: Active curated path (Exhibit interface only)
  - Example: `"labor-images"`, or `null`

#### Items Array
Full metadata for selected items:
- **`id`**: Unique identifier (matches source data)
- **`title`**: Book title
- **`author`**: Primary creator
- **`year`**: Publication year
- **`call_number`**: LC call number
- **`signals`**: Detected thematic signals
- **`photo_insert_score`**: AI likelihood score (if available)
- **`user_note`**: Optional user annotation (editable in some interfaces)

**Rationale**: Embedding full metadata ensures receipt is self-contained—if source data changes or becomes unavailable, the receipt preserves what user selected.

#### Verification
- **`sha256`**: SHA-256 hash of canonical JSON (excluding `verification` object itself)
  - Computed using RFC 8785 (JCS) canonical serialization
  - Used to detect tampering or corruption
  
- **`canonical_json_rfc8785`**: Boolean flag indicating RFC 8785 compliance
  - Always `true` for ShelfSignals receipts
  
- **`verified_at`**: Timestamp of last successful verification
  - `null` on creation (set on import/verification)
  - Updated each time receipt is re-verified

## How Receipts Work

### 1. Generation (Export)

**User flow** (Exhibit interface):
1. Browse collection, select items of interest
2. Click **Share icon** → "Export Digital Receipt"
3. System generates receipt JSON with current state
4. User chooses export format:
   - **Download JSON** → `receipt-SS-A1B2-C3D4-E5F6.json`
   - **Generate QR Code** → PNG image with embedded receipt URL
   - **Copy URL** → Shareable link with `#receipt=...` fragment

**Technical process**:
1. Collect current interface state (selected items, filters, search)
2. Fetch full metadata for selected items
3. Generate unique receipt ID (random 12-character alphanumeric)
4. Create receipt object with all fields
5. Compute SHA-256 hash of canonical JSON (RFC 8785)
6. Add verification metadata
7. Encode as JSON or Base64 (for URL/QR code)

**Implementation** (`docs/js/receipt.js`):
```javascript
async function generateReceipt(state, selectedItems) {
  const receiptId = generateReceiptID(); // "SS-A1B2-C3D4-E5F6"
  const timestamp = new Date().toISOString();
  
  const receipt = {
    receipt_id: receiptId,
    version: "2.0",
    timestamp: timestamp,
    collection: "Allan Sekula Library",
    interface: "exhibit",
    state: state,
    items: selectedItems,
    verification: {
      sha256: null,
      canonical_json_rfc8785: true,
      verified_at: null
    }
  };
  
  // Compute hash of canonical JSON (excluding verification.sha256)
  const canonical = canonicalStringify(receipt);
  const hash = await hashCanonicalJSON(receipt);
  receipt.verification.sha256 = hash;
  
  return receipt;
}
```

### 2. Sharing (Distribution)

#### Option A: JSON Download
**Format**: Plain JSON file
**Filename**: `receipt-SS-A1B2-C3D4-E5F6.json`
**Use cases**:
- Email to self or colleagues
- Upload to cloud storage (Dropbox, Google Drive)
- Archive in research notes or documentation
- Attach to publications or presentations

**Import method**: Drag-and-drop onto interface or "Import Receipt" button

#### Option B: QR Code
**Format**: PNG image with embedded URL
**Encoding**: `https://example.com/preview/exhibit/#receipt=<Base64-encoded-JSON>`
**Use cases**:
- Print on exhibition labels or gallery walls
- Display on kiosk screens for mobile capture
- Share on social media or websites
- Include in conference posters

**Import method**: Scan with mobile camera → navigate to URL → receipt auto-loads

#### Option C: URL Fragment
**Format**: URL with `#receipt=` fragment
**Encoding**: Base64 JSON in fragment (after `#`)
**Use cases**:
- Share via email, chat, or social media
- Bookmark for quick access
- Embed in web pages or documentation

**Example**:
```
https://evcatalyst.github.io/ShelfSignals/preview/exhibit/#receipt=eyJyZWNlaXB0X2lkIjoi...
```

**Import method**: Navigate to URL → receipt auto-loads from fragment

### 3. Verification (Integrity Check)

When importing a receipt, the system:
1. Parse JSON from file, QR code, or URL fragment
2. Extract `verification.sha256` hash
3. Recompute hash of canonical JSON (excluding `verification.sha256`)
4. Compare computed hash to stored hash
5. If mismatch → warn user of potential tampering
6. If match → proceed with import and set `verification.verified_at`

**Implementation**:
```javascript
async function verifyReceipt(receipt) {
  const storedHash = receipt.verification.sha256;
  
  // Remove hash field before recomputing
  const receiptCopy = JSON.parse(JSON.stringify(receipt));
  delete receiptCopy.verification.sha256;
  
  // Compute canonical hash
  const computedHash = await hashCanonicalJSON(receiptCopy);
  
  if (computedHash !== storedHash) {
    console.warn("Receipt integrity check failed!");
    return { verified: false, message: "Hash mismatch - data may be corrupted or tampered" };
  }
  
  receipt.verification.verified_at = new Date().toISOString();
  return { verified: true, message: "Receipt verified successfully" };
}
```

### 4. Import (Restoration)

**User flow**:
1. Open interface (Preview or Exhibit)
2. Click **Import Receipt** button (or drag-and-drop JSON file)
3. System verifies hash integrity
4. If verified → restore interface state:
   - Load selected items
   - Apply filters and search query
   - Set color palette and signal overlays
   - Highlight curated path (if applicable)
5. User sees exact same view as when receipt was generated

**Technical process**:
1. Parse receipt JSON
2. Verify SHA-256 hash (tamper detection)
3. Check schema version compatibility
4. Match item IDs against current dataset
5. Handle missing items gracefully (if source data changed):
   - Warn user of missing items
   - Show available items from receipt
   - Log discrepancies
6. Restore interface state:
   - Set active filters
   - Populate search box
   - Apply color palette
   - Select curated path
7. Render shelf with receipt state

## What a Receipt Captures

### Included in Receipt
✅ **User selections**: Item IDs of selected books  
✅ **Interface state**: Filters, search query, active signals  
✅ **View configuration**: Color palette, overlay modes  
✅ **Curated path**: Active path ID (Exhibit interface)  
✅ **Full item metadata**: Title, author, year, call number, signals, AI scores  
✅ **User annotations**: Optional notes on selected items  
✅ **Verification data**: Unique ID, timestamp, integrity hash  

### Not Included in Receipt
❌ **Personal information**: No user accounts, logins, or tracking  
❌ **Browse history**: Only final selections, not navigation path  
❌ **Timing data**: When items were selected (only final export timestamp)  
❌ **Full collection data**: Only selected items, not entire dataset  
❌ **Server state**: No backend dependencies or API calls  

## What Guarantees a Receipt Provides

### ✅ Integrity Guarantee
**What it means**: If the receipt's SHA-256 hash verifies successfully, the data has **not been altered** since export.

**What it does NOT mean**:
- ❌ Authenticity (anyone can generate a receipt)
- ❌ Source validation (no way to prove receipt came from official interface)
- ❌ Dataset freshness (receipt may reference outdated catalog data)

**Use case**: Detect accidental corruption (file transfer errors, disk failures) or intentional tampering.

### ✅ Reproducibility Guarantee
**What it means**: Given the same source dataset, importing a receipt will restore **the exact same interface state** as when it was exported.

**What it does NOT mean**:
- ❌ Identical dataset (source catalog may have changed)
- ❌ Identical UI (interface code may have updated)
- ❌ Identical browser (rendering may vary across platforms)

**Use case**: Document research methodology, share curated collections, replicate analysis.

### ✅ Portability Guarantee
**What it means**: Receipts are **platform-independent** and work across devices, browsers, and time periods.

**What it does NOT mean**:
- ❌ Forward compatibility (future interface versions may not support old receipt schemas)
- ❌ Offline functionality (interface must load to import receipt)

**Use case**: Take home collections from museum kiosks, share across teams, archive for future reference.

### ❌ NOT a Guarantee: Authenticity
**Limitation**: Receipts do **not** prove who created them or from which interface they originated.

**Why**: No digital signatures or certificate chains (requires PKI infrastructure, which adds complexity and server dependencies).

**Implication**: Anyone can generate a receipt with arbitrary data. Treat receipts as user-generated content, not authoritative records.

**Mitigation**: Cross-check receipt data against source catalog if authenticity is critical.

## Verification Process Details

### RFC 8785 Canonical JSON
ShelfSignals uses **RFC 8785 (JCS - JSON Canonicalization Scheme)** for deterministic JSON serialization:

1. **Sort object keys** alphabetically at all nesting levels
2. **Remove whitespace** (no pretty-printing)
3. **Normalize numbers** (no leading zeros, consistent float representation)
4. **UTF-8 encoding** for all strings
5. **No trailing commas** or other syntax variations

**Why**: Ensures the same JSON object always produces the same byte sequence, making hash comparisons reliable.

**Example**:
```javascript
// Input (arbitrary order, whitespace)
{
  "year": 1995,
  "title": "Fish Story",
  "author": "Sekula, Allan"
}

// Canonical output (sorted, compact)
{"author":"Sekula, Allan","title":"Fish Story","year":1995}
```

### SHA-256 Hash Computation
1. Serialize receipt as canonical JSON (excluding `verification.sha256` field)
2. Encode as UTF-8 byte array
3. Compute SHA-256 hash via WebCrypto API (`crypto.subtle.digest`)
4. Convert to hexadecimal string (64 characters)

**Implementation**:
```javascript
async function hashCanonicalJSON(obj) {
  const canonical = canonicalStringify(obj);
  const encoder = new TextEncoder();
  const data = encoder.encode(canonical);
  const hashBuffer = await crypto.subtle.digest('SHA-256', data);
  const hashArray = Array.from(new Uint8Array(hashBuffer));
  return hashArray.map(b => b.toString(16).padStart(2, '0')).join('');
}
```

### Verification Failures
If hash verification fails:
1. **Display warning**: "Receipt integrity check failed - data may be corrupted or tampered"
2. **Show details**: Expected hash vs. computed hash
3. **Allow import anyway** (user choice): Some users may want to proceed despite mismatch
4. **Log discrepancy**: Browser console for debugging

**Common causes of verification failure**:
- Manual JSON editing (typos, formatting changes)
- File corruption during transfer (network errors, disk failures)
- Intentional tampering (malicious modification)
- Incorrect canonical serialization (rare, implementation bug)

## Use Cases

### Museum Visitor: Take-Home Collection
**Scenario**: Visitor explores "Labor & Images" curated path at museum kiosk, selects 10 favorite items, wants to remember them.

**Workflow**:
1. Browse curated path, click items to select
2. Click **Share** → **Generate QR Code**
3. Scan QR code with mobile phone
4. At home: Open URL → receipt auto-loads with selected items
5. Download JSON for archival or share with friends

**Receipt benefits**:
- No login required (privacy-respecting)
- Works offline after initial load (mobile-friendly)
- Shareable via social media or email

### Researcher: Methodology Documentation
**Scenario**: Scholar curating bibliography for a paper on maritime photography, wants to document exact search criteria and item selection.

**Workflow**:
1. Search "maritime photography", filter by LC class "TR", photo likelihood "Likely"
2. Review results, select 15 relevant items
3. Click **Export Receipt** → download JSON
4. Include receipt file in research data archive (Zenodo, Dataverse, etc.)
5. In paper: "See receipt-SS-A1B2-C3D4-E5F6.json for full search methodology"

**Receipt benefits**:
- Reproducible search criteria (filters, keywords)
- Verifiable item selection (hash integrity)
- Citable artifact (permanent identifier)

### Librarian: Thematic Bibliography
**Scenario**: Librarian creating reading list for "Photography and Labor" course, wants to share curated list with instructors.

**Workflow**:
1. Search and filter to find 20 relevant items
2. Add curator notes to each item ("Recommended for Week 3")
3. Export receipt as JSON
4. Email to instructor with message: "Import this receipt to see full list"
5. Instructor imports receipt → sees exact same selections with notes

**Receipt benefits**:
- No server account needed (email-friendly)
- Annotations preserved (curator notes)
- Easy updates (generate new receipt with revised selections)

### Educator: Reading List Distribution
**Scenario**: Professor assigning 25 books for semester, wants students to have permanent access to list.

**Workflow**:
1. Curate list in interface
2. Export receipt as JSON
3. Upload to course website or LMS (Canvas, Moodle)
4. Students download receipt → import to see full list
5. Students can re-import anytime (no expiration)

**Receipt benefits**:
- Works across semesters (no time limits)
- Students control their own copy (no platform lock-in)
- Verifiable integrity (hash check ensures correct list)

## Where Receipts Live

### During Generation
- **Browser memory**: Receipt object constructed in JavaScript
- **WebCrypto API**: SHA-256 hash computed client-side

### After Export
- **User downloads**: `receipt-SS-A1B2-C3D4-E5F6.json` file in Downloads folder
- **QR codes**: PNG images (user-saved or displayed on screen)
- **URL fragments**: Encoded in browser URL bar (shareable links)
- **No server storage**: ShelfSignals does **not** store receipts on any server

### During Import
- **Browser memory**: Receipt parsed from JSON, verified, applied to interface state
- **localStorage** (optional): Some interfaces may cache imported receipts for quick access
- **No server communication**: Import is fully client-side

### Permanent Storage (User Responsibility)
Users should store receipts in:
- **Cloud storage**: Google Drive, Dropbox, OneDrive
- **Email**: Send to self or archive in email folders
- **Research data repositories**: Zenodo, Figshare, Dataverse (for published work)
- **Version control**: Git repos for collaborative curation
- **Local backups**: External drives, USB sticks

## Security Considerations

### What Receipts Protect Against
✅ **Accidental corruption**: File transfer errors, disk failures  
✅ **Data integrity**: Detect if receipt data has been modified  
✅ **Reproducibility**: Ensure same receipt → same result  

### What Receipts Do NOT Protect Against
❌ **Authenticity**: No way to prove who created a receipt  
❌ **Authorization**: Anyone can import anyone else's receipt  
❌ **Confidentiality**: Receipt data is **not encrypted** (JSON is plaintext)  
❌ **Non-repudiation**: No digital signatures linking receipt to creator  

### Privacy Implications
- **No PII required**: Receipts work without user accounts or personal data
- **User-controlled**: No server-side storage or tracking
- **GDPR-compliant**: No personal data processing (unless user adds notes with PII)

**Warning**: If users add personal notes with sensitive information, they should treat receipts as private documents.

## Best Practices

### For Users
1. **Verify hash on import**: Always check green "Verified" indicator
2. **Archive important receipts**: Store in multiple locations (cloud + local)
3. **Include metadata in filenames**: `receipt-labor-images-2024-01-15.json` (more descriptive than bare receipt ID)
4. **Cross-check critical data**: For high-stakes research, verify receipt items against original catalog

### For Interface Developers
1. **Document schema versions**: Increment version on breaking changes
2. **Handle missing items gracefully**: If source data changes, warn user but don't fail
3. **Preserve backward compatibility**: Support importing old receipt versions
4. **Expose verification status**: Show clear UI feedback (green checkmark, red warning)

### For Curators/Librarians
1. **Add curator notes**: Explain selection rationale in user annotations
2. **Include creation context**: Document when, why, and for whom receipt was generated
3. **Test import before distributing**: Verify receipt works as expected
4. **Provide instructions**: Explain to users how to import receipts

## Troubleshooting

### Receipt Won't Import
**Symptoms**: "Invalid receipt format" or "Verification failed" error

**Causes & Solutions**:
1. **JSON syntax error**: Validate JSON with linter (jsonlint.com)
2. **Schema version mismatch**: Check `version` field (may need newer interface)
3. **Missing items**: Source dataset may have changed (check console for missing IDs)
4. **Corrupted file**: Re-download original receipt or check file integrity

### Hash Verification Fails
**Symptoms**: "Receipt integrity check failed - hash mismatch"

**Causes & Solutions**:
1. **Manual editing**: JSON was modified after export (revert to original)
2. **File corruption**: Re-download original receipt
3. **Encoding issues**: Ensure UTF-8 encoding (not UTF-16 or ASCII)
4. **Implementation bug**: Report to ShelfSignals developers with receipt file

### Items Missing After Import
**Symptoms**: Some items from receipt don't appear in interface

**Causes & Solutions**:
1. **Catalog updated**: Items may have been removed or IDs changed
2. **Different dataset**: Receipt generated from different collection
3. **Interface version**: Older receipts may reference deprecated fields

**Mitigation**: Receipt JSON includes full metadata, so user can still see what was selected even if items aren't in current dataset.

## Next Steps

- **See receipts in action**: Try [Exhibit Interface](https://evcatalyst.github.io/ShelfSignals/preview/exhibit/)
- **Understand interface features**: See [docs/interfaces.md](interfaces.md)
- **Learn about data pipeline**: See [docs/pipeline.md](pipeline.md)
- **Run locally**: See [docs/operations.md](operations.md)
