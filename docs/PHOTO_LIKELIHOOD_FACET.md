# Embedded Photography Likelihood Facet

## Overview

The **Embedded Photography Likelihood** facet is a probabilistic deep facet that estimates the likelihood (0–100) that a book matching the provided metadata contains actual photographic inserts or plates, even when not categorized as a photography book.

This facet uses the xAI (Grok) API to provide intelligent, metadata-driven estimates based on disciplinary norms, publisher patterns, subject classifications, and explicit evidence flags extracted from catalog records.

## Core Principles

### Conservative Bias
- **Probabilistic prior, not certainty**: Scores represent likelihood across similar books, not claims about specific physical copies
- **No inference without evidence**: High scores (>70) require converging signals from multiple metadata fields
- **Photography-specific**: Drawings, diagrams, maps, engravings, and artistic reproductions are NOT treated as photographs unless explicitly photographic
- **Stable and aggregable**: Scores are consistent across runs and suitable for visual overlays

### Score Buckets

| Bucket | Score Range | Interpretation |
|--------|-------------|----------------|
| **Strongly Likely** | ≥75 | Multiple converging signals indicate high probability of photographic content |
| **Likely** | 55–74 | Strong evidence from subject headings, publishers, or explicit flags |
| **Plausible** | 35–54 | Weak signals or indirect evidence (e.g., illustration flags in visual domains) |
| **Unlikely** | <35 | Minimal or no evidence of photographic content |

## Architecture

The implementation follows a three-stage pipeline:

### Stage 1: Feature Packet Generation
**Script**: `scripts/photo_feature_extractor.py`

Generates compact, token-optimized feature packets from metadata, including:

#### Extracted Features
- **title** (trimmed if excessively long)
- **year** and **decade**
- **publisher_norm** (canonicalized publisher name)
- **call_number_prefix** (LC class, e.g., TR, NA, HD)
- **domain_tags** (max 3 from controlled vocabulary)
- **page_count_bin** (`<150`, `150–300`, `>300`, or `unknown`)

#### Evidence Flags (Boolean)
Extracted via regex from notes and description fields:
- `has_photographs` - Explicit mention of photographs
- `has_plates` - Mention of plates
- `has_illustrations` - Mention of illustrations
- `frontispiece_only` - Only frontispiece mentioned

#### Format Flags (Boolean)
Inferred from metadata:
- `exhibition_catalog` - Exhibition catalogs
- `survey_report` - Survey or government reports
- `technical_manual` - Technical/engineering manuals
- `fiction` - Fiction or literary works
- `cookbook` - Cookbooks

#### Escalation Logic
Full subject lists and notes are excluded by default for token efficiency. A short **notes_excerpt** (≤240 chars) is only included if trigger words appear (`photo`, `plate`, `ill.`, `fig.`).

**Usage:**
```bash
python scripts/photo_feature_extractor.py \
  --input docs/data/sekula_index.json \
  --output docs/data/photo_feature_packets.jsonl
```

### Stage 2: Grok API Scoring
**Script**: `scripts/photo_likelihood_scorer.py`

Calls the xAI Grok API with a frozen v1 scoring prompt to generate likelihood scores.

#### Features
- **Chunked processing**: Processes 100–250 records per API call for efficiency
- **Checkpointing**: Automatically skips already-scored rows when resuming
- **Retry logic**: Exponential backoff for failed API calls (max 3 retries)
- **Mock mode**: For testing without API calls (`--mock` flag)
- **Deterministic**: Same prompt version + model produce consistent scores

#### Output Fields
For each book, the scorer adds:
- `photo_insert_score` (integer 0–100)
- `photo_insert_bucket` (Strongly Likely | Likely | Plausible | Unlikely)
- `photo_insert_reasoning` (2–4 sentences explaining the score)
- Metadata: `provider`, `model`, `prompt_version`, `run_id`, `timestamp`

**Usage:**
```bash
# With API key
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

### Stage 3: Merging and Export

#### JSON Merge
**Script**: `scripts/merge_scores_to_json.py`

Merges photo scores into the main JSON data files used by the UI.

```bash
python scripts/merge_scores_to_json.py \
  --input docs/data/sekula_index.json \
  --scores docs/data/photo_scored.jsonl \
  --output docs/data/sekula_index.json
```

#### CSV Export
**Script**: `scripts/merge_scores_to_csv.py`

Exports enriched data with photo scores as CSV for analysis.

```bash
python scripts/merge_scores_to_csv.py \
  --input docs/data/sekula_index.json \
  --scores docs/data/photo_scored.jsonl \
  --output docs/data/sekula_index_enriched.csv
```

## GitHub Actions Workflow

**File**: `.github/workflows/photo_scoring.yml`

Automated workflow for scoring the collection with manual or scheduled triggers.

### Manual Trigger
Navigate to **Actions** → **Photo Likelihood Scoring** → **Run workflow**

Options:
- **Use mock responses**: For testing without API calls
- **Chunk size**: Number of records per API chunk (default: 100)

### Workflow Steps
1. Extract feature packets from `sekula_index.json`
2. Score with Grok API (or mock responses)
3. Generate enriched CSV
4. Log statistics (counts, bucket distribution)
5. Commit and push enriched data

### Secrets Configuration
Add your xAI API key to repository secrets:
- **Settings** → **Secrets and variables** → **Actions**
- Add new secret: `XAPIKEY`

## UI Integration

### Toggleable Overlay
The "📷 Embedded Photography" overlay is available in both production and preview interfaces.

**Location**: Header controls (checkbox)

### Visualization
When enabled, spines are tinted with subtle color overlays:
- **Orange** (40% opacity) - Strongly Likely (≥75)
- **Yellow** (30% opacity) - Likely (55–74)
- **Light Blue** (20% opacity) - Plausible (35–54)
- No tint for Unlikely (<35)

### Filtering
When the overlay is enabled, a bucket filter appears allowing users to filter by:
- Strongly Likely
- Likely
- Plausible
- Unlikely

### Detail Panel
For each book, if photo scoring data is available:
- **Photo Likelihood**: Shows score and bucket
- **Reasoning**: Brief explanation of the score

## Quality Assurance

### Data Validation
Current collection statistics (mock data):
```
Total records: 11,176

Bucket distribution:
  Unlikely        : 7,426 (66.4%)  ← Conservative default
  Plausible       : 2,399 (21.5%)
  Likely          :   759 ( 6.8%)
  Strongly Likely :   592 ( 5.3%)

Average score: 35.3
Min score: 15
Max score: 85
```

### Stability Requirements
- Scores must be **deterministic** per prompt version + model
- Same feature packet → same score across runs
- Conservative bias when evidence is absent
- No scores >70 without converging signals

### Token Efficiency
- Feature packets exclude full subject lists and notes by default
- Notes excerpts only included when trigger words present (≤240 chars)
- Average feature packet: ~200-300 bytes vs. 2-3KB full metadata

## Limitations and Future Work

### Current Limitations
1. **No actual visual inspection**: Scores based solely on metadata
2. **No edition-specific information**: Same score for all editions of a title
3. **Mock data in development**: Real API integration pending

### Future Enhancements
1. **Temporal analysis**: Track scoring trends over time
2. **Cluster aggregation**: Precompute cluster-level statistics
3. **Shelf segment means**: Average photo likelihood per shelf segment
4. **Visual similarity**: Detect photographic content from digitized covers/pages
5. **User feedback**: Allow curators to validate/correct scores

## Development and Testing

### Running Tests Locally

1. **Extract features**:
```bash
python scripts/photo_feature_extractor.py \
  --input docs/data/sekula_index.json \
  --output /tmp/features.jsonl
```

2. **Score with mock**:
```bash
python scripts/photo_likelihood_scorer.py \
  --input /tmp/features.jsonl \
  --output /tmp/scored.jsonl \
  --mock
```

3. **Merge to JSON**:
```bash
python scripts/merge_scores_to_json.py \
  --input docs/data/sekula_index.json \
  --scores /tmp/scored.jsonl \
  --output /tmp/enriched.json
```

### CI/CD Integration
The workflow automatically runs in **mock mode** for CI tests to avoid API costs and rate limits.

## Credits

- **Design**: Based on the Embedded Photography Likelihood facet specification
- **API**: xAI (Grok) for metadata-driven likelihood scoring
- **Implementation**: Part of the ShelfSignals analytics framework

## License

Same as parent ShelfSignals project.
