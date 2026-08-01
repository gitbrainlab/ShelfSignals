# ShelfSignals

**Collection intelligence framework** for browsing the Allan Sekula Library and the Thomas Jefferson catalog beta through catalog truth, evidence-scoped visuals, and reproducible research pathways.

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

### 🌐 Try it live

- [**Independent HTTPS mirror**](https://evcatalyst.github.io/ShelfSignals-live/) — primary cinematic interface (recommended)
- [**Thomas Jefferson catalog beta**](https://gitbrainlab.github.io/ShelfSignals/?collection=jefferson) — 2,748 current Library of Congress catalog instances, explicitly separate from the historical Sowerby corpus
- [**Aerospace Folktales journey route**](https://evcatalyst.github.io/ShelfSignals-live/?journey=aerospace-folktales) — cited five-movement research journey
- [**Project GitHub Pages route**](https://gitbrainlab.github.io/ShelfSignals/) — canonical repository deployment
- [**Legacy interface**](https://evcatalyst.github.io/ShelfSignals-live/legacy/) — preserved v1 experience

### 💻 Run Locally

```bash
# Clone and serve the static site
git clone https://github.com/gitbrainlab/ShelfSignals.git
cd ShelfSignals
python3 -m http.server 8000 --directory docs
# Open http://localhost:8000/
# Jefferson catalog beta: http://localhost:8000/?collection=jefferson
# Direct journey: http://localhost:8000/?journey=aerospace-folktales
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

### Verify the production interface

```bash
# Build and validate the compact public cover manifests (no network access)
python3 scripts/build_cover_index.py --self-test
python3 scripts/build_cover_index.py --check
python3 scripts/ingest_cleared_covers.py self-test
python3 scripts/ingest_cleared_covers.py encoder-self-test  # requires Pillow
python3 scripts/cleared_cover_ingest_unit_tests.py
python3 scripts/google_books_cover_source.py self-test
python3 scripts/google_books_cover_source_unit_tests.py
python3 scripts/build_spine_index.py --self-test
python3 scripts/build_spine_index.py
node scripts/build_browser_catalog.mjs --self-test
node scripts/build_browser_catalog.mjs --check

# Build and verify the committed Jefferson browser package (no network access)
python3 scripts/build_jefferson_browser_package.py --self-test
python3 scripts/build_jefferson_browser_package.py --check
python3 scripts/build_jefferson_browser_package_unit_tests.py
node --test scripts/collection_contract_unit_tests.mjs scripts/collection_runtime_unit_tests.mjs

# Validate the private cover-review pipeline and browser contracts
python3 scripts/cover_source_pipeline.py self-test
node --test scripts/browser_catalog_unit_tests.mjs scripts/cinematic_unit_tests.mjs scripts/phase_one_unit_tests.mjs scripts/review_unit_tests.mjs scripts/spine_index_unit_tests.mjs scripts/aerospace_review_queue_tests.mjs scripts/association_promotion_tests.mjs
node scripts/preview_acceptance_tests.mjs

# Optional full-browser suite; requires Playwright and a Chromium/Chrome binary
python3 scripts/browser_smoke_test.py --start-server --browser-channel chrome
# With the local server running, verify collection switching and isolation:
node scripts/collection_browser_journey.mjs http://127.0.0.1:8000/
```

The browser test covers the primary route, direct journey URL and history behavior, placement filtering, cover failure states, responsive layouts, and the Legacy/Preview/Exhibit compatibility routes.

---

## Documentation

### 📚 Core Documentation

- **[docs/index.md](docs/index.md)** - Overview, concepts, use cases, and navigation map
- **[docs/pipeline.md](docs/pipeline.md)** - Data model, normalization, AI enrichment, reproducibility
- **[docs/interfaces.md](docs/interfaces.md)** - Production/Preview/Exhibit interface documentation
- **[docs/receipts.md](docs/receipts.md)** - Digital Receipt system for portable, verifiable exports
- **[docs/operations.md](docs/operations.md)** - Running locally, scheduling, storage layout, export formats
- **[docs/edition-enrichment.md](docs/edition-enrichment.md)** - Exact-edition metadata, provenance, physical evidence, and regeneration
- **[docs/cover-source-pipeline.md](docs/cover-source-pipeline.md)** - Conservative cover discovery, review gates, rights, and cache policy
- **[docs/cleared-cover-ingest.md](docs/cleared-cover-ingest.md)** - Clark/rights-cleared image intake, bounded WebP derivatives, and publication gates
- **[docs/google-books-cover-source.md](docs/google-books-cover-source.md)** - Temporary exact-ISBN research leads under Google cache, rights, and branding constraints
- **[docs/browser-catalog.md](docs/browser-catalog.md)** - Compact first load, lazy full-field search/details, source identity, and regeneration
- **[docs/jefferson-collection.md](docs/jefferson-collection.md)** - Jefferson catalog-beta scope, collection routes, package build, reviewer-mode limits, and Phase 2 gates
- **[docs/association-promotion.md](docs/association-promotion.md)** - Dry-run-first, digest-confirmed journey association publication
- **[docs/journey-method.md](docs/journey-method.md)** - Journey evidence grades, publication gate, placement scope, and photograph rights
- **[research/review-queues/aerospace-folktales-methodology.md](research/review-queues/aerospace-folktales-methodology.md)** - Unpublished Aerospace Folktales association audit and inference limits

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
- **Evidence-Aware Book Forms**: Clark catalog geometry plus exact-edition physical metadata with property-level provenance
- **Copy-Specific Placement**: Source-transcribed Sekula shelf identifiers on cards and drawers, with same-placement filtering
- **Evidence-Led Journeys**: Photograph-record research narratives whose citations, image-rights state, review status, and association reasoning remain inspectable; rights-pending work images stay visibly withheld
- **AI Deep Facets**: Embedded Photography Likelihood scorer (xAI Grok API)

### 🎨 Primary and compatibility interfaces

| Interface | Status | Best For |
|-----------|--------|----------|
| [**Primary**](https://evcatalyst.github.io/ShelfSignals-live/) | Active | Collection-aware cinematic browsing, Sekula research journeys, the Jefferson catalog beta, and isolated My Shelves |
| [**Legacy**](https://evcatalyst.github.io/ShelfSignals-live/legacy/) | Archived | Preserved v1 behavior |
| [**Preview**](https://evcatalyst.github.io/ShelfSignals-live/preview/) | Compatibility | Earlier research and spatial experiments |
| [**Exhibit**](https://evcatalyst.github.io/ShelfSignals-live/preview/exhibit/) | Compatibility | Kiosk and exhibition experiments |

See [**docs/interfaces.md**](docs/interfaces.md) for detailed comparison.

### 🎫 Digital Receipts

**Portable, verifiable exports** of curated collections:
- RFC 8785 canonical JSON + SHA-256 verification
- Collection-bound `shelfsignals-receipt@2` exports and isolated shelf storage
- No server storage (fully client-side)
- Shareable via JSON download; URL-fragment helpers remain available for compatibility experiments
- Human-readable IDs: `SS-XXXX-XXXX-XXXX`

See [**docs/receipts.md**](docs/receipts.md) for complete documentation.

---

## Screenshots

### Primary interface

![ShelfSignals primary interface](docs/images/cinematic-desktop.png)

*Cinematic catalog browsing with progressively rendered records, evidence-scoped covers, placement controls, and physical/list views.*

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
│   ├── index.html           # Primary cinematic interface
│   ├── legacy/              # Archived v1 interface
│   ├── preview/             # Research compatibility route
│   │   ├── index.html
│   │   └── exhibit/         # Exhibit compatibility route
│   ├── review.html          # Local-only association and cover review handoff
│   ├── js/                  # Shared JavaScript and evidence contracts
│   └── data/                # Catalog, cover, placement-derived, and journey manifests
├── scripts/                 # Data pipeline tools
│   ├── build_cover_index.py # Compact cover/provenance manifest generator
│   ├── build_spine_index.py # Compact Clark-derived spine geometry generator
│   ├── cover_source_pipeline.py # Private cover discovery and review queue
│   ├── ingest_cleared_covers.py # Rights-cleared local derivative ingest
│   ├── cleared_cover_contract.py # Strict local-cover evidence contract
│   ├── sekula_indexer.py    # Primo API harvester
│   ├── photo_feature_extractor.py  # AI feature extraction
│   ├── photo_likelihood_scorer.py  # Grok API scoring
│   └── merge_scores_to_json.py     # Merge enriched data
├── research/                # Non-deployed editorial evidence packets
│   └── review-queues/       # Explicitly unpublished association queues + methods
├── README.md                # This file
└── INTRODUCTION.md          # Visual user guide
```

---

## Core Principles

1. **Source-Agnostic**: Works with any metadata source (API, CSV, HTML scraping)
2. **Collection-Neutral**: Adaptable to any library, archive, or museum catalog
3. **Reproducible Pipelines**: Version-controlled scripts with frozen parameters
4. **Visual Intelligence**: Transform metadata into spatial, chromatic representations
5. **Evidence Scope**: Keep Clark-copy facts, provider-edition evidence, work-level context, estimates, and unresolved states distinct
6. **Human Review**: Never publish machine-suggested book/work associations without cited reasoning and named review
7. **Research-Oriented**: Designed for discovery and insight, not end-user search

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
- Runs on modern browsers with native modal isolation (Chrome 102+, Firefox 112+, Safari 15.5+)
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
