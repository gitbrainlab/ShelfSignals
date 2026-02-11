# ShelfSignals

**Collection intelligence framework** that reveals hidden patterns in library and archive metadata through visual analytics, AI-powered deep facets, and reproducible data pipelines.

> **Start Here**: New users should read the [**Introduction & User Guide**](INTRODUCTION.md) for a visual walkthrough, or jump to the [**📚 Complete Documentation**](docs/index.md).

---

## What is ShelfSignals?

ShelfSignals transforms catalog metadata into interactive visualizations that expose the implicit knowledge encoded in:
- **Classification systems** (LC call numbers, subject headings)
- **Numbering sequences** (accession patterns, shelf arrangement)
- **Thematic signals** (photography, labor, maritime, critical theory)
- **Deep facets** (AI-powered content detection)

The framework is **source-agnostic** and **collection-neutral**—adapt it to any institution's catalog (Primo, OCLC, ArchivesSpace, CSV exports).

---

## Quick Start

### 🌐 Try it Live
- [**Preview Interface**](https://gitbrainlab.github.io/ShelfSignals/preview/) - Explore the virtual shelf (recommended)
- [**Exhibit Interface**](https://gitbrainlab.github.io/ShelfSignals/preview/exhibit/) - Museum-ready with curated paths

### 💻 Run Locally
```bash
# Clone and serve
git clone https://github.com/gitbrainlab/ShelfSignals.git
cd ShelfSignals/docs
python -m http.server 8000
# Open http://localhost:8000/preview/
```

### 🔧 Run the Pipeline
```bash
# Harvest catalog data
python scripts/sekula_indexer.py

# Extract AI features
python scripts/photo_feature_extractor.py \
  --input docs/data/sekula_index.json \
  --output docs/data/photo_feature_packets.jsonl

# Score with AI (mock mode)
python scripts/photo_likelihood_scorer.py \
  --input docs/data/photo_feature_packets.jsonl \
  --output docs/data/photo_scored.jsonl \
  --mock

# Merge scores and export
python scripts/merge_scores_to_json.py \
  --input docs/data/sekula_index.json \
  --scores docs/data/photo_scored.jsonl \
  --output docs/data/sekula_index.json
```

See [**docs/operations.md**](docs/operations.md) for complete pipeline documentation.

---

## Documentation

### 📚 Core Documentation
- **[docs/index.md](docs/index.md)** - Overview, concepts, use cases, and navigation map
- **[docs/pipeline.md](docs/pipeline.md)** - Data model, normalization, AI enrichment, reproducibility
- **[docs/interfaces.md](docs/interfaces.md)** - Production/Preview/Exhibit interface documentation
- **[docs/receipts.md](docs/receipts.md)** - Digital Receipt system for portable, verifiable exports
- **[docs/operations.md](docs/operations.md)** - Running locally, scheduling, storage layout, export formats

### 📖 Getting Started Guides
- **[INTRODUCTION.md](INTRODUCTION.md)** - Visual user guide with screenshots and workflows
- **[docs/PHOTO_LIKELIHOOD_FACET.md](docs/PHOTO_LIKELIHOOD_FACET.md)** - AI-powered deep facets implementation

### 🎯 Quick Navigation
- **What problem does this solve?** → [docs/index.md](docs/index.md#what-problems-does-shelfsignals-solve)
- **How does data flow through the pipeline?** → [docs/pipeline.md](docs/pipeline.md)
- **How do I run the interfaces?** → [docs/interfaces.md](docs/interfaces.md) or [docs/operations.md](docs/operations.md#running-locally)
- **How do receipts work?** → [docs/receipts.md](docs/receipts.md)
- **How do I adapt this to my collection?** → [docs/operations.md](docs/operations.md#adapting-to-new-collections)

---

## Features

### 🔍 Core Capabilities
- **Metadata Harvesting**: API connectors (Primo, OCLC), CSV imports, HTML/DOM extraction
- **Normalization Layer**: LC parsing, publisher canonicalization, year normalization, subject cleanup
- **Pattern Detection**: Sequence analysis, signal matching, classification clustering
- **Visual Intelligence**: Virtual shelf, LC coloring, thematic overlays, interactive exploration
- **AI Deep Facets**: Embedded Photography Likelihood scorer (xAI Grok API)

### 🎨 Three Specialized Interfaces
| Interface | Status | Best For |
|-----------|--------|----------|
| [**Production**](https://gitbrainlab.github.io/ShelfSignals/) | Deprecated (v1.x) | Legacy compatibility |
| [**Preview**](https://gitbrainlab.github.io/ShelfSignals/preview/) | ✅ Active (v2.x) | Research, accessibility |
| [**Exhibit**](https://gitbrainlab.github.io/ShelfSignals/preview/exhibit/) | ✅ Active (v2.x) | Museums, kiosks, public engagement |

See [**docs/interfaces.md**](docs/interfaces.md) for detailed comparison.

### 🎫 Digital Receipts
**Portable, verifiable exports** of curated collections:
- RFC 8785 canonical JSON + SHA-256 verification
- No server storage (fully client-side)
- Shareable via JSON download, QR code, or URL fragment
- Human-readable IDs: `SS-XXXX-XXXX-XXXX`

See [**docs/receipts.md**](docs/receipts.md) for complete documentation.

---

## Screenshots

### Preview Interface
![ShelfSignals Preview Interface](docs/images/preview-interface.png)
*Virtual shelf with LC classification coloring, real-time search, and interactive book spines*

*For more screenshots and use cases, see the [Introduction & User Guide](INTRODUCTION.md).*

---

## Repository Structure

```
ShelfSignals/
├── docs/                    # Documentation + GitHub Pages deployment
│   ├── index.md             # Documentation index
│   ├── pipeline.md          # Data pipeline guide
│   ├── interfaces.md        # Interface documentation
│   ├── receipts.md          # Digital Receipt system
│   ├── operations.md        # Running locally, scheduling
│   ├── PHOTO_LIKELIHOOD_FACET.md  # Deep facets guide
│   ├── index.html           # Production interface (deprecated)
│   ├── preview/             # Preview interface (v2.x)
│   │   ├── index.html
│   │   └── exhibit/         # Exhibit interface
│   ├── js/                  # Shared JavaScript modules
│   └── data/                # Collection data (JSON, CSV)
├── scripts/                 # Data pipeline tools
│   ├── sekula_indexer.py    # Primo API harvester
│   ├── photo_feature_extractor.py  # AI feature extraction
│   ├── photo_likelihood_scorer.py  # Grok API scoring
│   └── merge_scores_to_json.py     # Merge enriched data
├── README.md                # This file
└── INTRODUCTION.md          # Visual user guide
```

---

## Core Principles

1. **Source-Agnostic**: Works with any metadata source (API, CSV, HTML scraping)
2. **Collection-Neutral**: Adaptable to any library, archive, or museum catalog
3. **Reproducible Pipelines**: Version-controlled scripts with frozen parameters
4. **Visual Intelligence**: Transform metadata into spatial, chromatic representations
5. **Research-Oriented**: Designed for discovery and insight, not end-user search

See [**docs/index.md**](docs/index.md#key-principles) for detailed principles.

---

## External Dependencies

### Required (Harvesting)
- Python 3.8+
- `requests` library (`pip install requests`)
- Institution-specific API access (may require VPN or authentication)

### Optional (AI Enrichment)
- xAI (Grok) API key for deep facet scoring
- Free tier: ~100 requests/hour
- Safe default: Mock mode (`--mock` flag) for testing

### Web Interfaces
- **No dependencies**: Pure HTML/CSS/JavaScript
- Runs on any modern browser (Chrome 90+, Firefox 88+, Safari 14+)
- GitHub Pages hosting (free for public repositories)

See [**docs/pipeline.md**](docs/pipeline.md#external-api-dependencies) for API details.

---

## Use Cases

ShelfSignals serves multiple personas and research workflows:

### 📚 Researchers
- **Pattern discovery**: Find thematic clusters across traditional subject boundaries
- **Collection analysis**: Understand topic distribution and relationships
- **Reproducible workflows**: Document methodology with Digital Receipts

### 🏛️ Librarians & Curators
- **Collection visualization**: See shelf organization from a bird's-eye view
- **Gap analysis**: Identify underrepresented subject areas
- **Exhibition planning**: Build curated pathways through collections

### 👥 Museum Visitors
- **Guided exploration**: Follow curated paths through themed content
- **Take-home collections**: Export selections via Digital Receipts (QR codes, JSON)
- **Self-guided learning**: Kiosk mode for unattended installations

See [**docs/index.md - Use Case Map**](docs/index.md#use-case-map) for detailed workflows.

---

## About the Sekula Library

The inaugural ShelfSignals deployment visualizes the **Allan Sekula Library Collection**—a research library focused on photography, labor history, maritime culture, and critical theory. The collection's thematic coherence makes it an ideal test case for pattern detection, but ShelfSignals is **collection-neutral** and adaptable to any catalog with structured metadata.

See [**INTRODUCTION.md**](INTRODUCTION.md#about-the-sekula-library) for more context.

---

## Contributing

ShelfSignals is an open research project. We welcome:
- **Feature requests**: Open an issue on GitHub
- **Bug reports**: Include browser version and reproduction steps
- **Data contributions**: Adapt to new collections with metadata connectors
- **Code improvements**: Pull requests for modular utilities or pipeline scripts

See [**docs/operations.md - Adapting to New Collections**](docs/operations.md#adapting-to-new-collections) for integration guidance.

---

## License

ShelfSignals is an open-source research project. See repository for license details.


