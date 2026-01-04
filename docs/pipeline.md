# ShelfSignals Data Pipeline

## Overview

The ShelfSignals pipeline transforms raw catalog metadata into enriched, analysis-ready datasets through four stages:

1. **Harvest**: Collect catalog records from external sources
2. **Normalize**: Standardize fields, identifiers, and vocabularies
3. **Analyze**: Detect patterns, extract features, and compute deep facets
4. **Visualize/Export**: Generate web interfaces and portable data formats

Each stage is **deterministic** and **reproducible**—given the same inputs and parameters, the pipeline produces identical outputs.

## Data Model

ShelfSignals uses a **normalized schema** that maps diverse catalog formats to a consistent internal structure:

### Core Fields

```json
{
  "id": "alma991002311449708431",           // Unique identifier (institution-specific)
  "title": "Fish Story",                     // Full title
  "author": "Sekula, Allan",                 // Primary creator
  "year": "1995",                            // Publication year (normalized)
  "publisher": "Richter Verlag",             // Publisher name (canonicalized)
  "call_number": "TR820 .S45 1995",          // LC call number (raw)
  "subjects": [                              // Subject headings (array)
    "Photography, Artistic",
    "Documentary photography",
    "Shipping -- Pictorial works"
  ],
  "notes": "Includes bibliographical references", // Catalog notes
  "pages": "208 p.",                         // Pagination
  "format": "Book",                          // Material type
  "language": "eng"                          // ISO 639 language code
}
```

### Enriched Fields (Added by Analysis Pipeline)

```json
{
  // Signal detection
  "signals": ["photography", "maritime", "labor"],
  
  // LC classification parsing
  "lc_class": "TR",                          // Main class
  "lc_subclass": "TR820",                    // Subclass
  "lc_cutter": "S45",                        // Cutter number
  "lc_year": "1995",                         // Call number year
  "lc_sort_key": "TR 0820 S45 1995",         // Sortable form
  
  // Deep facets (AI-powered)
  "photo_insert_score": 85,                  // 0-100 likelihood
  "photo_insert_bucket": "Strongly Likely",  // Categorical band
  "photo_insert_reasoning": "Explicit mention of photographic plates...",
  
  // Temporal normalization
  "year_normalized": 1995,                   // Integer year
  "decade": "1990s",                         // Decade label
  
  // Domain tags (controlled vocabulary)
  "domain_tags": ["photography", "maritime", "labor"]
}
```

### Data Files

ShelfSignals maintains multiple data formats for different use cases:

| File | Format | Purpose | Location |
|------|--------|---------|----------|
| `sekula_index.json` | JSON (array of objects) | Primary web interface data | `docs/data/` |
| `sekula_inventory.json` | JSON (CSV-compatible) | Legacy production interface | `docs/data/` |
| `sekula_index.csv` | CSV | Spreadsheet analysis, external tools | `docs/data/` |
| `photo_feature_packets.jsonl` | JSONL | Intermediate AI scoring input | `docs/data/` (generated) |
| `photo_scored.jsonl` | JSONL | AI scoring results | `docs/data/` (generated) |

**Note**: JSONL files (`.jsonl`) contain one JSON object per line for streaming/chunked processing.

## Stage 1: Harvest

### Purpose
Collect catalog records from external sources and convert to ShelfSignals' normalized schema.

### Harvesting Script: `sekula_indexer.py`

**Location**: `scripts/sekula_indexer.py`

**What it does**:
- Connects to Primo VE JSON API to fetch catalog records
- Paginates through result sets with offset-based traversal
- Applies collection filter (Sekula deployment example: `lds07` field = "Allan Sekula Library"; adapt to your institution, e.g., appropriate `lds07` value for Clark Art Institute)
- Shards queries by publication decade to avoid API offset limits (5,000 max)
- Implements rate limiting, retry logic, and checkpointing

**Key Features**:
- **Checkpointing**: Writes intermediate results every 5 pages (250 records)
- **Rate limiting**: 1.2s base delay + 0.8s random jitter between requests
- **Exponential backoff**: Handles 403 responses with escalating wait times (60s → 900s max)
- **Shard-based traversal**: Splits large collections into manageable chunks (e.g., by decade)

**Configuration** (in script):
```python
BASE_URL = "https://library.clarkart.edu/primaws/rest/pub/pnxs"
VID = "01CLARKART_INST:01CLARKART_INST_FRANCINE"
COLLECTION_NAME = "Allan Sekula Library"

LIMIT = 50          # Records per API call
DELAY_SEC = 1.2     # Base delay between requests
JITTER_SEC = 0.8    # Random jitter
RETRY_LIMIT = 3     # Max retries per request
```

**Usage**:
```bash
cd /home/runner/work/ShelfSignals/ShelfSignals
python scripts/sekula_indexer.py
```

**Outputs**:
- `sekula_index.json` - Full JSON array of normalized records
- `sekula_index.csv` - CSV export (auto-generated)

**Adapting to other collections**:
1. Update `BASE_URL`, `VID`, `TAB`, `SCOPE` for your institution's Primo instance
2. Modify collection filter query (e.g., `lds07` field or custom facet)
3. Adjust sharding strategy (decade ranges, call number prefixes, etc.)
4. Update field mappings in parsing logic to match your Primo PNX schema

### Facet Scout: `facet_scout.py`

**Location**: `scripts/facet_scout.py`

**Purpose**: Probe API to understand result counts per facet (decade, call number prefix) to design optimal sharding strategy.

**Usage**:
```bash
python scripts/facet_scout.py
```

**Output** (console):
```
=== Creation Decades ===
Decade:1940s         245
Decade:1950s         412
Decade:1960s         687
...

=== Call Number Prefix ===
CallNumber:H         1,234
CallNumber:N         891
CallNumber:T         2,345
...
```

**When to use**: Before harvesting a new collection or after major catalog updates to verify shard boundaries stay under API limits.

## Stage 2: Normalize

### Purpose
Standardize heterogeneous metadata fields into consistent, analysis-ready formats.

### Normalization Tasks

#### 1. LC Call Number Parsing
**Module**: `docs/js/lc.js` (client-side) and embedded in harvester

**Extracts**:
- **Main class**: `TR`, `N`, `HD`, etc.
- **Subclass**: Full numeric portion (e.g., `TR820`)
- **Cutter number**: Author/title code (e.g., `S45`)
- **Year**: Call number year suffix (if present)
- **Sort key**: Normalized form for shelf-order sorting

**Examples**:
```javascript
parseCallNumber("TR820 .S45 1995")
// → { class: "TR", subclass: "TR820", cutter: "S45", year: "1995", sortKey: "TR 0820 S45 1995" }

parseCallNumber("N7433.4 .S45 F57 2002")
// → { class: "N", subclass: "N7433.4", cutter: "S45", year: "2002", sortKey: "N 7433.4 S45 F57 2002" }
```

#### 2. Publisher Canonicalization
**Logic**: Embedded in `photo_feature_extractor.py`

**Handles**:
- **Imprint variants**: "MIT Press", "The MIT Press", "M.I.T. Press" → "MIT Press"
- **Corporate suffixes**: Remove "Inc.", "Ltd.", "Publishers", "Verlag"
- **Punctuation**: Normalize hyphens, periods, ampersands

**Example**:
```python
canonicalize_publisher("The Museum of Modern Art, New York")
# → "Museum of Modern Art"

canonicalize_publisher("University of California Press, Ltd.")
# → "University of California Press"
```

#### 3. Year Normalization
**Module**: `docs/js/year.js` (client-side)

**Handles**:
- **Ranges**: "1995-2000" → 1995 (earliest year)
- **Circa**: "c1985", "[1985?]" → 1985
- **Brackets**: "[2000]", "2000?" → 2000
- **Decades**: "199-" → 1990
- **Unknowns**: Missing or "n.d." → null

**Example**:
```javascript
normalizeYear("c1995")     // → 1995
normalizeYear("1990-1995") // → 1990
normalizeYear("[1985?]")   // → 1985
normalizeYear("n.d.")      // → null
```

#### 4. Subject Heading Cleanup
**Logic**: Remove trailing punctuation, normalize spacing, deduplicate

**Example**:
```
"Photography, Artistic."  → "Photography, Artistic"
"Labor -- History"        → "Labor -- History"
```

## Stage 3: Analyze

### Pattern Detection

#### Signal Matching
**Module**: `docs/js/signals.js`

**Purpose**: Detect thematic patterns in metadata using keyword dictionaries.

**Signal Registry** (example):
```javascript
{
  "photography": {
    "keywords": ["photograph", "camera", "photographic", "photojournalism"],
    "color": "#e74c3c"  // Signal color for visualization
  },
  "labor": {
    "keywords": ["labor", "labour", "working class", "union", "factory"],
    "color": "#3498db"
  },
  "maritime": {
    "keywords": ["maritime", "shipping", "port", "harbor", "ocean", "seafaring"],
    "color": "#1abc9c"
  }
}
```

**Matching logic**: Case-insensitive regex search across title, subjects, and notes fields.

**Output**: Array of signal IDs per item (e.g., `["photography", "maritime"]`)

#### Feature Extraction for AI Scoring

**Script**: `scripts/photo_feature_extractor.py`

**Purpose**: Generate compact, token-optimized feature packets for AI deep facet scoring.

**Extracted features**:
```json
{
  "id": "alma991002311449708431",
  "title": "Fish Story",
  "year": 1995,
  "decade": "1990s",
  "publisher_norm": "Richter Verlag",
  "call_number_prefix": "TR",
  "domain_tags": ["photography", "maritime"],
  "page_count_bin": "150-300",
  
  // Evidence flags (boolean)
  "has_photographs": true,
  "has_plates": false,
  "has_illustrations": true,
  "frontispiece_only": false,
  
  // Format flags (boolean)
  "exhibition_catalog": false,
  "survey_report": false,
  "technical_manual": false,
  "fiction": false,
  
  // Escalation: only included if trigger words present
  "notes_excerpt": "Includes 68 color photographic plates"
}
```

**Token efficiency**:
- Full metadata: ~2-3KB per item
- Feature packet: ~200-300 bytes per item
- **10x reduction** in API token costs

**Usage**:
```bash
python scripts/photo_feature_extractor.py \
  --input docs/data/sekula_index.json \
  --output docs/data/photo_feature_packets.jsonl
```

### AI Enrichment (Deep Facets)

**Script**: `scripts/photo_likelihood_scorer.py`

**Purpose**: Use xAI (Grok) API to estimate likelihood of embedded photographic content.

**Architecture**:
- **Chunked processing**: 100-250 records per API call
- **Deterministic prompts**: Frozen v1 scoring rubric for consistency
- **Conservative bias**: High scores (>70) require converging evidence
- **Checkpointing**: Resume from last completed chunk

**Scoring rubric** (v1 prompt excerpt):
```
Score 0-100 based on converging evidence:

High (75-100): Multiple signals (explicit "photographs" + visual domain + appropriate publisher)
Medium (55-74): Strong single signal (explicit mention OR photography domain + evidence flags)
Low (35-54): Weak signals (illustration flags in visual domains, borderline publishers)
Minimal (<35): No evidence or contradictory signals (fiction, poetry, theory-only)

Conservative prior: Assume unlikely unless metadata provides clear evidence.
```

**Output fields** (added to each record):
```json
{
  "photo_insert_score": 85,
  "photo_insert_bucket": "Strongly Likely",
  "photo_insert_reasoning": "Explicit mention of 'photographic plates' in notes, TR classification (photography), visual arts publisher",
  "photo_insert_metadata": {
    "provider": "xai",
    "model": "grok-beta",
    "prompt_version": "v1",
    "run_id": "2024-01-15T10:30:00Z",
    "timestamp": "2024-01-15T10:35:42Z"
  }
}
```

**Usage**:
```bash
# With API key
export XAI_API_KEY="your-api-key-here"
python scripts/photo_likelihood_scorer.py \
  --input docs/data/photo_feature_packets.jsonl \
  --output docs/data/photo_scored.jsonl \
  --api-key $XAI_API_KEY

# Mock mode (for testing)
python scripts/photo_likelihood_scorer.py \
  --input docs/data/photo_feature_packets.jsonl \
  --output docs/data/photo_scored.jsonl \
  --mock
```

**API parameters**:
- **Model**: `grok-beta` (or latest stable)
- **Temperature**: 0.0 (deterministic)
- **Max tokens**: 150 per item (score + bucket + reasoning)

**Rate limits** (xAI):
- ~100 requests/hour (free tier)
- Exponential backoff on 429 responses
- Batch processing recommended for large collections

## Stage 4: Merge and Export

### Merging AI Scores

**Script**: `scripts/merge_scores_to_json.py`

**Purpose**: Join AI-scored deep facets back into primary data files.

**Merge logic**:
1. Load base data (`sekula_index.json`)
2. Load scored features (`photo_scored.jsonl`)
3. Match on `id` field (unique identifier)
4. Add `photo_insert_*` fields to matched records
5. Write updated JSON (in-place or new file)

**Usage**:
```bash
python scripts/merge_scores_to_json.py \
  --input docs/data/sekula_index.json \
  --scores docs/data/photo_scored.jsonl \
  --output docs/data/sekula_index.json
```

**Verification**: Run `scripts/verify_photo_identifiers.py` to confirm 100% match rate:
```bash
python scripts/verify_photo_identifiers.py
# Expected: All tests pass, 100% match rate
```

### CSV Export

**Script**: `scripts/merge_scores_to_csv.py`

**Purpose**: Export enriched data with AI scores as CSV for spreadsheet analysis.

**Usage**:
```bash
python scripts/merge_scores_to_csv.py \
  --input docs/data/sekula_index.json \
  --scores docs/data/photo_scored.jsonl \
  --output docs/data/sekula_index.csv
```

**CSV columns**:
- All core fields (id, title, author, year, call_number, etc.)
- Enriched fields (signals, lc_class, domain_tags)
- AI scores (photo_insert_score, photo_insert_bucket, photo_insert_reasoning)

## Reproducibility Practices

ShelfSignals follows **research reproducibility standards** to ensure verifiable, auditable results:

### 1. Version-Controlled Scripts
All pipeline scripts are committed to Git with:
- **Semantic versioning** for major changes
- **Inline documentation** explaining parameters and logic
- **Test data samples** for validation

### 2. Frozen Parameters
Critical configuration is **embedded in scripts** (not environment variables):
- API endpoints and authentication
- Prompt versions for AI scoring
- Normalization rules and vocabularies
- Shard boundaries and pagination limits

**Changing parameters** requires:
1. Update script constants
2. Document change in commit message
3. Re-run affected pipeline stages
4. Verify outputs with validation scripts

### 3. Checkpointing and Idempotency
All long-running scripts support **resume-from-checkpoint**:
- Harvest: Resume from last completed shard/page
- AI scoring: Skip already-scored records
- Merge: Detect existing enriched fields and skip or update

**Example** (resuming harvest):
```python
# In sekula_indexer.py
START_SHARD = 5  # Skip first 5 shards (already completed)
```

### 4. Data Provenance
Every enriched field includes **metadata tracking**:
```json
{
  "photo_insert_metadata": {
    "provider": "xai",              // Data source
    "model": "grok-beta",            // Model version
    "prompt_version": "v1",          // Scoring rubric
    "run_id": "2024-01-15T10:30:00Z", // Pipeline run timestamp
    "timestamp": "2024-01-15T10:35:42Z" // Individual score timestamp
  }
}
```

This allows **auditing**:
- Which prompt version generated a score?
- When was the data last enriched?
- Which model parameters were used?

### 5. Verification Tools
**Script**: `scripts/verify_photo_identifiers.py`

**Checks**:
- All scored records have valid IDs
- All scores merged correctly into primary data
- ID consistency across all data formats (JSON, JSONL, CSV)
- Sample data quality (no missing required fields)

**Usage**:
```bash
python scripts/verify_photo_identifiers.py
# Output: Pass/fail for each validation check
```

### 6. Deterministic Outputs
Given identical inputs and parameters:
- **Harvesting**: Same API results (assuming catalog unchanged)
- **Normalization**: Identical parsed fields (pure functions)
- **AI scoring**: Same scores (temperature=0, frozen prompts)
- **Merging**: Identical enriched datasets (idempotent joins)

**Testing reproducibility**:
```bash
# Run pipeline twice
python scripts/sekula_indexer.py > run1.json
python scripts/sekula_indexer.py > run2.json

# Compare outputs (should be identical)
diff run1.json run2.json
```

### 7. Input/Output Manifests
Each pipeline run can log:
- Input file paths and checksums (SHA-256)
- Parameter values and script versions
- Output file paths and checksums
- Timestamp and runtime duration

**Example manifest**:
```json
{
  "run_id": "2024-01-15T10:30:00Z",
  "pipeline": "harvest_and_enrich",
  "inputs": {
    "api_base": "https://library.clarkart.edu/primaws/rest/pub/pnxs",
    "collection": "Allan Sekula Library"
  },
  "scripts": {
    "sekula_indexer.py": "v1.2.0",
    "photo_feature_extractor.py": "v1.0.1",
    "photo_likelihood_scorer.py": "v1.0.0"
  },
  "outputs": {
    "sekula_index.json": {
      "path": "docs/data/sekula_index.json",
      "sha256": "a3f2e1b8c4d5e6f7a8b9c0d1e2f3a4b5c6d7e8f9a0b1c2d3e4f5a6b7c8d9e0f1",
      "records": 11176,
      "timestamp": "2024-01-15T12:45:30Z"
    }
  },
  "runtime_seconds": 3847
}
```

## Where Data Lives

### During Pipeline Execution
- **Source catalogs**: External APIs (Primo, OCLC, etc.)
- **Intermediate files**: `docs/data/*.jsonl` (generated, not committed by default)
- **Checkpoint files**: Temporary `.checkpoint.json` files in script directory

### After Pipeline Completion
- **Primary data**: `docs/data/sekula_index.json` (committed to Git)
- **Legacy data**: `docs/data/sekula_inventory.json` (CSV-compatible format)
- **CSV exports**: `docs/data/sekula_index.csv` (committed to Git)
- **AI scores**: Merged into primary data (separate `.jsonl` files optional)

### Web Interfaces
- **Static files**: `docs/index.html`, `docs/preview/index.html`, `docs/preview/exhibit/index.html`
- **JavaScript modules**: `docs/js/*.js` (loaded by interfaces)
- **Data loaded by UI**: `docs/data/sekula_index.json` (for Preview/Exhibit), `docs/data/sekula_inventory.json` (for Production)

### Exported/User-Generated
- **Digital Receipts**: Client-side only (browser localStorage or downloads)
- **QR codes**: Generated dynamically from Receipt data (no server storage)
- **Screenshots**: User-captured via browser tools

## External API Dependencies

### Required for Harvesting
- **Primo VE API**: Institution-specific endpoint
  - Authentication: Usually public read access (no API key)
  - Rate limits: Varies by institution (typically 1-2 requests/second)
  - Safe default: 1.2s delay + random jitter

### Optional for AI Enrichment
- **xAI (Grok) API**: `https://api.x.ai/v1`
  - Authentication: API key required (set `XAI_API_KEY` environment variable or pass `--api-key`)
  - Rate limits: ~100 requests/hour (free tier), higher for paid plans
  - Safe default: Mock mode (`--mock` flag) for testing

### None for Web Interfaces
- **Static hosting**: GitHub Pages, Netlify, or local file://
- **No server-side dependencies**: Pure HTML/CSS/JavaScript

## Next Steps

- **Run the pipeline locally**: See [docs/operations.md](operations.md)
- **Explore interfaces**: See [docs/interfaces.md](interfaces.md)
- **Understand Digital Receipts**: See [docs/receipts.md](receipts.md)
- **Learn about deep facets**: See [docs/PHOTO_LIKELIHOOD_FACET.md](PHOTO_LIKELIHOOD_FACET.md)
