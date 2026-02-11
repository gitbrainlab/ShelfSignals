# ShelfSignals Operations Guide

## Overview

This guide covers **running ShelfSignals locally**, **scheduling automated data collection**, **understanding storage layout**, and **working with export formats**. It is intended for developers, system administrators, and researchers who want to:

- Run the full pipeline on their own infrastructure
- Adapt ShelfSignals to new collections
- Automate data harvesting and enrichment
- Integrate ShelfSignals with external tools

## Running Locally

ShelfSignals has **two operational modes**:
1. **Web interfaces** (no installation required)
2. **Data pipeline** (Python scripts for harvesting and analysis)

### Prerequisites

#### For Web Interfaces
**No installation required**—pure static HTML/CSS/JavaScript.

**Requirements**:
- Modern web browser (Chrome 90+, Firefox 88+, Safari 14+)
- Local web server (for CORS-compliant data loading)

#### For Data Pipeline
**Python 3.8+** with dependencies:
```bash
# Install Python dependencies
pip install requests
```

**Optional** (for AI enrichment):
- **xAI (Grok) API key**: For deep facet scoring
  - Free tier: ~100 requests/hour
  - Sign up at https://x.ai/api

### Running Web Interfaces Locally

#### Quick Start (All Interfaces)
```bash
# Clone repository
git clone https://github.com/gitbrainlab/ShelfSignals.git
cd ShelfSignals/docs

# Start local web server
python -m http.server 8000

# Open in browser
# Production:  http://localhost:8000/
# Preview:     http://localhost:8000/preview/
# Exhibit:     http://localhost:8000/preview/exhibit/
```

#### Interface-Specific Servers

**Production Interface**:
```bash
cd /home/runner/work/ShelfSignals/ShelfSignals/docs
python -m http.server 8000
# Open http://localhost:8000/
```

**Preview Interface**:
```bash
cd /home/runner/work/ShelfSignals/ShelfSignals/docs/preview
python -m http.server 8001
# Open http://localhost:8001/
```

**Exhibit Interface** (with kiosk mode):
```bash
cd /home/runner/work/ShelfSignals/ShelfSignals/docs/preview/exhibit
python -m http.server 8002
# Normal mode: http://localhost:8002/
# Kiosk mode:  http://localhost:8002/?kiosk=1
```

#### Alternative Web Servers

**Node.js (http-server)**:
```bash
npm install -g http-server
cd /home/runner/work/ShelfSignals/ShelfSignals/docs
http-server -p 8000 -c-1
```

**PHP**:
```bash
cd /home/runner/work/ShelfSignals/ShelfSignals/docs
php -S localhost:8000
```

**Caddy** (automatic HTTPS):
```bash
cd /home/runner/work/ShelfSignals/ShelfSignals/docs
caddy file-server --listen :8000
```

### Running Data Pipeline Locally

#### Step 1: Harvest Catalog Data

**Script**: `scripts/sekula_indexer.py`

```bash
cd /home/runner/work/ShelfSignals/ShelfSignals

# Run harvester
python scripts/sekula_indexer.py

# Outputs:
# - docs/data/sekula_index.json   (full JSON)
# - docs/data/sekula_index.csv    (CSV export)
```

**Configuration**:
Edit `scripts/sekula_indexer.py` to customize:
- `BASE_URL`: Primo API endpoint
- `VID`, `TAB`, `SCOPE`, `INSTITUTION`: Primo instance parameters
- `COLLECTION_NAME`: Filter query (e.g., `lds07` field)
- `SHARDS`: Decade ranges for pagination
- `DELAY_SEC`, `JITTER_SEC`: Rate limiting

**Checkpointing**:
Harvester writes intermediate results every 5 pages. To resume from checkpoint:
```python
# In sekula_indexer.py
START_SHARD = 3  # Skip first 3 shards (already completed)
```

**Monitoring**:
```bash
# Watch output in real-time
python scripts/sekula_indexer.py | tee harvest.log

# Count records harvested
grep -c '"id"' docs/data/sekula_index.json
```

#### Step 2: Analyze Facets (Optional)

**Script**: `scripts/facet_scout.py`

```bash
# Probe API to understand facet distribution
python scripts/facet_scout.py

# Output (console):
# === Creation Decades ===
# Decade:1940s         245
# Decade:1950s         412
# ...
```

**Use case**: Design optimal shard boundaries before harvesting large collections.

#### Step 3: Extract AI Features

**Script**: `scripts/photo_feature_extractor.py`

```bash
# Generate compact feature packets for AI scoring
python scripts/photo_feature_extractor.py \
  --input docs/data/sekula_index.json \
  --output docs/data/photo_feature_packets.jsonl

# Output: docs/data/photo_feature_packets.jsonl (one JSON object per line)
```

**Options**:
- `--input`: Source JSON file (default: `docs/data/sekula_index.json`)
- `--output`: Output JSONL file (default: `docs/data/photo_feature_packets.jsonl`)

#### Step 4: Score with AI (Optional)

**Script**: `scripts/photo_likelihood_scorer.py`

```bash
# Score with xAI (Grok) API
export XAI_API_KEY="your-api-key-here"
python scripts/photo_likelihood_scorer.py \
  --input docs/data/photo_feature_packets.jsonl \
  --output docs/data/photo_scored.jsonl \
  --api-key $XAI_API_KEY

# Output: docs/data/photo_scored.jsonl (feature packets + scores)
```

**Options**:
- `--input`: Feature packets file (JSONL)
- `--output`: Scored output file (JSONL)
- `--api-key`: xAI API key (or set `XAI_API_KEY` env var)
- `--mock`: Use mock responses (no API calls)
- `--chunk-size`: Records per API batch (default: 100)

**Mock Mode** (testing without API):
```bash
# Generate deterministic mock scores for testing
python scripts/photo_likelihood_scorer.py \
  --input docs/data/photo_feature_packets.jsonl \
  --output docs/data/photo_scored.jsonl \
  --mock
```

**Checkpointing**:
Scorer skips already-scored records. To resume interrupted run:
```bash
# Just re-run the same command—it will skip existing scores
python scripts/photo_likelihood_scorer.py \
  --input docs/data/photo_feature_packets.jsonl \
  --output docs/data/photo_scored.jsonl \
  --api-key $XAI_API_KEY
```

#### Step 5: Merge Scores into Data

**Script**: `scripts/merge_scores_to_json.py`

```bash
# Merge AI scores into primary JSON data
python scripts/merge_scores_to_json.py \
  --input docs/data/sekula_index.json \
  --scores docs/data/photo_scored.jsonl \
  --output docs/data/sekula_index.json

# Updates docs/data/sekula_index.json in-place
```

**Options**:
- `--input`: Base JSON file (without scores)
- `--scores`: Scored JSONL file (from Step 4)
- `--output`: Output JSON file (can be same as input for in-place update)

#### Step 6: Export CSV (Optional)

**Script**: `scripts/merge_scores_to_csv.py`

```bash
# Export enriched data as CSV
python scripts/merge_scores_to_csv.py \
  --input docs/data/sekula_index.json \
  --scores docs/data/photo_scored.jsonl \
  --output docs/data/sekula_index.csv

# Output: docs/data/sekula_index.csv (all fields + AI scores)
```

#### Step 7: Verify Data Integrity

**Script**: `scripts/verify_photo_identifiers.py`

```bash
# Verify all scores merged correctly
python scripts/verify_photo_identifiers.py

# Expected output:
# ✓ All scored records have valid IDs
# ✓ All scores merged into sekula_index.json
# ✓ ID consistency across all files
# ✓ Sample data quality checks passed
```

### Full Pipeline Example

```bash
#!/bin/bash
# full_pipeline.sh - Run complete ShelfSignals pipeline

cd /home/runner/work/ShelfSignals/ShelfSignals

echo "=== Step 1: Harvest catalog data ==="
python scripts/sekula_indexer.py

echo "=== Step 2: Extract AI features ==="
python scripts/photo_feature_extractor.py \
  --input docs/data/sekula_index.json \
  --output docs/data/photo_feature_packets.jsonl

echo "=== Step 3: Score with AI (mock mode) ==="
python scripts/photo_likelihood_scorer.py \
  --input docs/data/photo_feature_packets.jsonl \
  --output docs/data/photo_scored.jsonl \
  --mock

echo "=== Step 4: Merge scores into JSON ==="
python scripts/merge_scores_to_json.py \
  --input docs/data/sekula_index.json \
  --scores docs/data/photo_scored.jsonl \
  --output docs/data/sekula_index.json

echo "=== Step 5: Export CSV ==="
python scripts/merge_scores_to_csv.py \
  --input docs/data/sekula_index.json \
  --scores docs/data/photo_scored.jsonl \
  --output docs/data/sekula_index.csv

echo "=== Step 6: Verify integrity ==="
python scripts/verify_photo_identifiers.py

echo "=== Pipeline complete! ==="
echo "View results: http://localhost:8000/preview/"
```

Make executable and run:
```bash
chmod +x full_pipeline.sh
./full_pipeline.sh
```

## Scheduled Runs

### GitHub Actions (Automated)

**Workflow**: `.github/workflows/photo_scoring.yml`

**Triggers**:
1. **Manual dispatch**: Navigate to Actions tab → "Photo Likelihood Scoring" → "Run workflow"
2. **Scheduled** (optional): Add cron schedule to workflow file

**Manual Run Steps**:
1. Go to https://github.com/gitbrainlab/ShelfSignals/actions
2. Select "Photo Likelihood Scoring" workflow
3. Click "Run workflow"
4. Configure options:
   - **Use mock responses**: Check for testing (no API costs)
   - **Chunk size**: Records per API batch (default: 100)
5. Click "Run workflow" button

**Workflow Steps** (automated):
1. Checkout repository
2. Set up Python 3.11
3. Install dependencies (`pip install requests`)
4. Extract feature packets from `sekula_index.json`
5. Score with Grok API (or mock responses)
6. Merge scores into `sekula_index.json`
7. Generate CSV export
8. Log statistics (counts, bucket distribution)
9. Commit and push updated data files

**Secrets Configuration**:
Add xAI API key to repository secrets:
1. Go to Settings → Secrets and variables → Actions
2. Click "New repository secret"
3. Name: `XAI_API_KEY`
4. Value: Your xAI API key
5. Click "Add secret"

**Monitoring**:
- View workflow runs in Actions tab
- Check logs for errors or warnings
- Review commit history for data updates

### Cron Scheduling (GitHub Actions)

To run pipeline automatically on a schedule, add cron trigger to `.github/workflows/photo_scoring.yml`:

```yaml
on:
  workflow_dispatch:  # Manual trigger
    inputs:
      use_mock:
        description: 'Use mock responses (no API calls)'
        required: false
        default: 'false'
      chunk_size:
        description: 'Chunk size for API batching'
        required: false
        default: '100'
  
  schedule:
    # Run weekly on Sundays at 2:00 AM UTC
    - cron: '0 2 * * 0'
```

**Cron Examples**:
- Daily at 2 AM: `0 2 * * *`
- Weekly on Sundays: `0 2 * * 0`
- Monthly on 1st: `0 2 1 * *`

### Local Cron (Linux/macOS)

For self-hosted deployments, use system cron:

```bash
# Edit crontab
crontab -e

# Add weekly pipeline run (Sundays at 2 AM)
0 2 * * 0 cd /path/to/ShelfSignals && ./full_pipeline.sh >> /var/log/shelfsignals.log 2>&1
```

**Log rotation**:
```bash
# /etc/logrotate.d/shelfsignals
/var/log/shelfsignals.log {
    weekly
    rotate 12
    compress
    missingok
    notifempty
}
```

### Windows Task Scheduler

For Windows deployments:

1. Open Task Scheduler
2. Create new task: "ShelfSignals Pipeline"
3. Trigger: Weekly on Sundays at 2:00 AM
4. Action: Run `full_pipeline.bat` (batch script wrapper for pipeline)
5. Settings: Run whether user is logged on or not

**Batch Script** (`full_pipeline.bat`):
```batch
@echo off
cd C:\ShelfSignals
python scripts\sekula_indexer.py
python scripts\photo_feature_extractor.py --input docs\data\sekula_index.json --output docs\data\photo_feature_packets.jsonl
python scripts\photo_likelihood_scorer.py --input docs\data\photo_feature_packets.jsonl --output docs\data\photo_scored.jsonl --mock
python scripts\merge_scores_to_json.py --input docs\data\sekula_index.json --scores docs\data\photo_scored.jsonl --output docs\data\sekula_index.json
python scripts\verify_photo_identifiers.py
```

## Data Storage Layout

### Repository Structure

```
/home/runner/work/ShelfSignals/ShelfSignals/
├── docs/                           # GitHub Pages deployment
│   ├── index.html                  # Production interface
│   ├── preview/
│   │   ├── index.html              # Preview interface
│   │   └── exhibit/
│   │       ├── index.html          # Exhibit interface
│   │       └── curated-paths.json  # Curated paths configuration
│   ├── js/                         # Shared JavaScript modules
│   │   ├── signals.js              # Signal detection
│   │   ├── lc.js                   # LC call number parser
│   │   ├── colors.js               # Color palette management
│   │   ├── search.js               # Search state & matching
│   │   ├── year.js                 # Year normalization
│   │   └── receipt.js              # Digital Receipt system
│   ├── data/                       # Collection data
│   │   ├── sekula_index.json       # Primary data (JSON-native)
│   │   ├── sekula_inventory.json   # Legacy data (CSV-compatible)
│   │   ├── sekula_index.csv        # CSV export
│   │   ├── photo_feature_packets.jsonl  # AI scoring input (generated)
│   │   └── photo_scored.jsonl      # AI scoring output (generated)
│   └── images/                     # Screenshots and assets
│       └── preview-interface.png
├── scripts/                        # Data pipeline tools
│   ├── sekula_indexer.py           # Primo API harvester
│   ├── facet_scout.py              # Facet analysis utility
│   ├── photo_feature_extractor.py  # AI feature extraction
│   ├── photo_likelihood_scorer.py  # Grok API scoring
│   ├── merge_scores_to_json.py     # Merge scores into JSON
│   ├── merge_scores_to_csv.py      # Export enriched CSV
│   └── verify_photo_identifiers.py # Verify data integrity
├── .github/
│   └── workflows/
│       └── photo_scoring.yml       # GitHub Actions workflow
├── README.md                       # Repository overview
├── INTRODUCTION.md                 # Visual user guide
├── index.md                        # Documentation index
├── pipeline.md                     # Data pipeline guide
├── interfaces.md                   # Interface documentation
├── receipts.md                     # Digital Receipt system
├── operations.md                   # This file
└── PHOTO_LIKELIHOOD_FACET.md       # Deep facets documentation
```

### Data Files

#### Primary Data
| File | Size | Format | Purpose | Committed to Git |
|------|------|--------|---------|------------------|
| `sekula_index.json` | ~8 MB | JSON array | Primary web interface data | ✅ Yes |
| `sekula_inventory.json` | ~5 MB | JSON (CSV-compat) | Legacy production interface | ✅ Yes |
| `sekula_index.csv` | ~12 MB | CSV | Spreadsheet analysis | ✅ Yes |

#### Generated/Intermediate
| File | Size | Format | Purpose | Committed to Git |
|------|------|--------|---------|------------------|
| `photo_feature_packets.jsonl` | ~2 MB | JSONL | AI scoring input | ❌ No (regenerated) |
| `photo_scored.jsonl` | ~3 MB | JSONL | AI scoring output | ❌ No (regenerated) |
| `.checkpoint.json` | ~1 KB | JSON | Harvester checkpoint | ❌ No (temp) |

#### Configuration
| File | Size | Format | Purpose | Committed to Git |
|------|------|--------|---------|------------------|
| `curated-paths.json` | ~10 KB | JSON | Exhibit paths | ✅ Yes |

### Disk Space Requirements

**Minimal deployment** (interfaces only):
- Web interfaces: ~500 KB (HTML + CSS + JS)
- Data files: ~25 MB (all formats)
- **Total**: ~26 MB

**Full pipeline** (including generated files):
- Web interfaces: ~500 KB
- Data files: ~25 MB
- Generated files: ~5 MB
- Python scripts: ~100 KB
- **Total**: ~31 MB

**With logs and checkpoints** (active development):
- Add ~10 MB per harvest run
- Add ~50 MB for verbose logging (optional)

### Backup Strategy

**Critical files** (must backup):
- `docs/data/sekula_index.json` - Primary data
- `docs/preview/exhibit/curated-paths.json` - Curated paths
- `scripts/*.py` - Pipeline code

**Regenerable files** (can skip backup):
- `photo_feature_packets.jsonl` - Regenerate from `sekula_index.json`
- `photo_scored.jsonl` - Re-run scorer (if API key available)
- `sekula_index.csv` - Export from JSON

**Backup schedule**:
- **Daily**: After successful pipeline runs (automated)
- **Weekly**: Manual snapshot of entire repository
- **Before major changes**: Git commit + tag

**Backup locations**:
- **Git**: Commit to version control (primary backup)
- **GitHub**: Remote repository (offsite backup)
- **External storage**: S3, Dropbox, or local drives (disaster recovery)

## Export Formats

ShelfSignals supports multiple export formats for integration with external tools.

### JSON (Native)

**File**: `docs/data/sekula_index.json`

**Structure**: Array of objects
```json
[
  {
    "id": "alma991002311449708431",
    "title": "Fish Story",
    "author": "Sekula, Allan",
    "year": "1995",
    "publisher": "Richter Verlag",
    "call_number": "TR820 .S45 1995",
    "subjects": ["Photography, Artistic", "Documentary photography"],
    "notes": "Includes bibliographical references",
    "signals": ["photography", "maritime"],
    "lc_class": "TR",
    "photo_insert_score": 85,
    "photo_insert_bucket": "Strongly Likely",
    "photo_insert_reasoning": "Explicit mention of photographic plates..."
  }
]
```

**Use cases**:
- Web interface data loading
- Python/JavaScript analysis scripts
- API integrations (RESTful services)
- Machine learning datasets

**Advantages**:
- Nested structures (arrays, objects)
- Typed values (numbers, booleans)
- Comments and metadata

**Tools**:
- **jq**: Command-line JSON processor (`jq '.[] | select(.signals | contains(["labor"]))' sekula_index.json`)
- **Python**: `import json; data = json.load(open('sekula_index.json'))`
- **JavaScript**: `fetch('sekula_index.json').then(r => r.json())`

### CSV (Tabular)

**File**: `docs/data/sekula_index.csv`

**Structure**: Comma-separated values with header row
```csv
id,title,author,year,publisher,call_number,subjects,signals,lc_class,photo_insert_score,photo_insert_bucket
alma991002311449708431,"Fish Story","Sekula, Allan",1995,"Richter Verlag","TR820 .S45 1995","Photography, Artistic|Documentary photography","photography|maritime",TR,85,"Strongly Likely"
```

**Use cases**:
- Excel/Google Sheets analysis
- R statistical computing
- Database imports (PostgreSQL, MySQL)
- Tableau/PowerBI visualizations

**Advantages**:
- Universal compatibility
- Easy to inspect and edit
- Lightweight file size

**Limitations**:
- No nested structures (arrays flattened with `|` delimiter)
- Limited metadata support
- Type information lost (all strings)

**Tools**:
- **Excel**: File → Open → Import CSV
- **pandas**: `df = pd.read_csv('sekula_index.csv')`
- **R**: `data <- read.csv('sekula_index.csv')`

### JSONL (Streaming)

**File**: `docs/data/photo_feature_packets.jsonl`

**Structure**: One JSON object per line (newline-delimited)
```jsonl
{"id":"alma991002311449708431","title":"Fish Story","year":1995,"domain_tags":["photography","maritime"]}
{"id":"alma991002311450008431","title":"Geography Lesson","year":1997,"domain_tags":["labor","urban"]}
```

**Use cases**:
- Streaming data processing
- Chunked API requests
- Incremental file updates
- Log file analysis

**Advantages**:
- Streamable (process line-by-line)
- Appendable (add new records without re-parsing)
- Memory-efficient (don't load entire file)

**Tools**:
- **jq**: `cat file.jsonl | jq -s '.'` (convert to JSON array)
- **Python**: `for line in open('file.jsonl'): data = json.loads(line)`
- **Shell**: `grep '"year":1995' file.jsonl` (simple filtering)

### Digital Receipts (Portable)

**File**: User-generated (e.g., `receipt-SS-A1B2-C3D4-E5F6.json`)

**Structure**: JSON with receipt metadata (see [docs/receipts.md](receipts.md))

**Use cases**:
- Take-home curated collections
- Research methodology documentation
- Shareable bibliographies
- Reproducible selections

**Advantages**:
- Self-contained (includes full item metadata)
- Verifiable (SHA-256 integrity hash)
- Portable (no server dependencies)

### Integration Examples

#### Import into Python (pandas)
```python
import pandas as pd
import json

# Load JSON
with open('docs/data/sekula_index.json') as f:
    data = json.load(f)
df = pd.DataFrame(data)

# Filter by signal
labor_df = df[df['signals'].apply(lambda x: 'labor' in x if x else False)]

# Export to CSV
labor_df.to_csv('labor_items.csv', index=False)
```

#### Import into R
```r
library(jsonlite)
library(dplyr)

# Load JSON
data <- fromJSON('docs/data/sekula_index.json')

# Filter by LC class
tr_data <- data %>% filter(lc_class == 'TR')

# Analyze photo likelihood
summary(tr_data$photo_insert_score)
```

#### Import into PostgreSQL
```sql
-- Create table
CREATE TABLE sekula_items (
  id TEXT PRIMARY KEY,
  title TEXT,
  author TEXT,
  year INTEGER,
  call_number TEXT,
  signals TEXT[],
  photo_insert_score INTEGER
);

-- Import CSV
COPY sekula_items FROM '/path/to/sekula_index.csv' 
  DELIMITER ',' CSV HEADER;

-- Query
SELECT title, author, photo_insert_score
FROM sekula_items
WHERE 'labor' = ANY(signals)
  AND photo_insert_score >= 70
ORDER BY photo_insert_score DESC;
```

#### Export to Zotero/EndNote
```python
# Convert to BibTeX format
import json

with open('docs/data/sekula_index.json') as f:
    data = json.load(f)

for item in data[:10]:  # First 10 items
    print(f"@book{{{item['id']},")
    print(f"  author = {{{item['author']}}},")
    print(f"  title = {{{item['title']}}},")
    print(f"  year = {{{item['year']}}},")
    print(f"  publisher = {{{item['publisher']}}}")
    print("}\n")
```

## Adapting to New Collections

### Step 1: Configure Harvester

Edit `scripts/sekula_indexer.py`:

```python
# Institution-specific parameters
BASE_URL = "https://your-institution.edu/primaws/rest/pub/pnxs"
VID = "YOUR_VID"
TAB = "YOUR_TAB"
SCOPE = "YOUR_SCOPE"
INSTITUTION = "YOUR_INSTITUTION"
COLLECTION_NAME = "Your Collection Name"

# Collection filter query
PARAMS_BASE = {
    # ... other params ...
    "q": 'your_field,contains,"Your Collection Name"',
}
```

**Find your Primo parameters**:
1. Open your Primo catalog in browser
2. Perform a search
3. Inspect URL parameters:
   - `vid=01CLARKART_INST:01CLARKART_INST_FRANCINE`
   - `tab=LibraryCatalog`
   - `scope=CAI_Library`
4. Copy to harvester configuration

### Step 2: Test with Facet Scout

```bash
# Update facet_scout.py with your parameters
python scripts/facet_scout.py

# Review shard sizes—ensure no shard >5,000 items
```

If any shard exceeds 5,000 items, refine sharding strategy (e.g., split decades into years, add call number prefix filters).

### Step 3: Run Test Harvest

```bash
# Harvest first shard only
# Edit sekula_indexer.py: START_SHARD = 0, comment out SHARDS[1:]
python scripts/sekula_indexer.py

# Inspect output
jq '. | length' docs/data/sekula_index.json  # Count records
jq '.[0]' docs/data/sekula_index.json        # View first record
```

### Step 4: Full Harvest

```bash
# Uncomment all shards
python scripts/sekula_indexer.py

# Monitor progress
tail -f harvest.log
```

### Step 5: Customize Signals

Edit `docs/js/signals.js`:

```javascript
const SIGNALS = {
  "your-signal-id": {
    "keywords": ["keyword1", "keyword2", "keyword3"],
    "color": "#ff6b6b",  // Hex color for visualization
    "label": "Your Signal Name"
  }
};
```

### Step 6: Update Interfaces

**Production/Preview**:
- No changes needed (generic collection display)

**Exhibit**:
- Edit `docs/preview/exhibit/curated-paths.json` with your curated paths
- Update `index.html` with your collection name and branding

### Step 7: Deploy

```bash
# Commit changes to Git
git add .
git commit -m "Adapt ShelfSignals to [Your Collection]"
git push origin main

# GitHub Pages auto-deploys from docs/ folder
# Visit https://[your-username].github.io/ShelfSignals/
```

## Troubleshooting

### Harvester Fails with 403 (Forbidden)
**Cause**: Rate limiting or authentication required

**Solutions**:
1. Increase `DELAY_SEC` and `JITTER_SEC` in harvester
2. Check if API requires authentication (add headers/cookies)
3. Contact institution's API support for rate limits

### Harvester Hits 5,000 Offset Limit
**Cause**: Primo API caps pagination at 5,000 records per facet

**Solution**: Refine shard boundaries
```python
# Split large decades into years
SHARDS = [
    {"label": "1990", "facet": "[1990 TO 1990]"},
    {"label": "1991", "facet": "[1991 TO 1991]"},
    # ...
]
```

### AI Scoring Fails with Rate Limit
**Cause**: xAI API free tier limits (~100 requests/hour)

**Solutions**:
1. Reduce `--chunk-size` (default: 100 → try 50)
2. Add delays between chunks (modify scorer script)
3. Upgrade to paid tier (higher limits)
4. Use `--mock` mode for testing

### Interfaces Don't Load Data
**Cause**: CORS restrictions when opening HTML files directly (`file://`)

**Solution**: Use local web server (see "Running Web Interfaces Locally")

### Search Performance Slow
**Cause**: Large datasets (>10,000 items) with synchronous rendering

**Solution**: Use Preview interface (lazy loading + debounced search) instead of Production

## Next Steps

- **Understand data pipeline**: See [docs/pipeline.md](pipeline.md)
- **Explore interfaces**: See [docs/interfaces.md](interfaces.md)
- **Learn about receipts**: See [docs/receipts.md](receipts.md)
- **Read deep facets guide**: See [docs/PHOTO_LIKELIHOOD_FACET.md](PHOTO_LIKELIHOOD_FACET.md)
