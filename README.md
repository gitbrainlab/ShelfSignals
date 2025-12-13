# ShelfSignals

ShelfSignals is a system-agnostic analytics framework for extracting structure,
patterns, and insights from collection inventories. It is designed for research
libraries, archives, and any environment where catalog metadata and numbering
systems contain implicit signals about provenance, organization, or workflow
history.

ShelfSignals ingests catalog records, normalizes metadata, and uses configurable
analysis modules to detect patterns in numbering sequences, item groupings,
descriptive fields, and other latent structures. The project is entirely
collection-neutral and adaptable to future datasets.

---

## Features

- **Metadata Harvesting**  
  Connectors for scraping, exporting, or ingesting catalog data (API, CSV,
  HTML/DOM extraction, etc.).

- **Normalization Layer**  
  Standardizes fields, numbering systems, identifiers, and formats across
  heterogeneous sources.

- **Pattern Analysis Engine**  
  Modules for:
  - sequence detection  
  - call number pattern clustering  
  - accession/cutter analysis  
  - temporal or spatial grouping  
  - anomaly detection  

- **Visualization Tools**  
  Heatmaps, sequence plots, cluster maps, and lineage timelines.

- **Export & Reporting**  
  Configurable output formats (CSV, JSON, Markdown reports, visual dashboards).

---

## Goals

ShelfSignals aims to:

1. Reveal hidden organizational structure in collection metadata.  
2. Identify sequential numbering patterns and anomalies.  
3. Provide a reusable toolkit for ongoing research and cross-collection studies.  
4. Support data preparation for external reporting or downstream machine-learning tasks.

---

## Web Interfaces

ShelfSignals provides two web interfaces for exploring the Sekula Library collection:

### Production Site (`/`)
- **Location**: `docs/index.html`
- **Data Source**: `docs/data/sekula_inventory.json` (CSV-compatible format)
- **Status**: Stable, current production interface
- **Access URL**: https://evcatalyst.github.io/ShelfSignals/
- **Direct link**: [Production Site](https://evcatalyst.github.io/ShelfSignals/)

The production site provides a mature interface with CSV-based data loading and legacy controls. It includes shelf visualization, cluster mapping, and detailed item views.

### Preview Environment (`/preview/`)
- **Location**: `docs/preview/index.html`
- **Data Source**: `docs/data/sekula_index.json` (JSON-native format from Primo API)
- **Status**: Experimental, modular architecture
- **Access URL**: https://evcatalyst.github.io/ShelfSignals/preview/
- **Direct link**: [Preview Environment](https://evcatalyst.github.io/ShelfSignals/preview/)

The preview environment showcases a modernized, modular architecture with:
- **Modular JavaScript utilities** in `docs/js/`:
  - `signals.js` - Centralized signals (theme) registry and keyword matching
  - `lc.js` - LC call-number parser extracting class, number, and sorting keys
  - `colors.js` - Unified color logic with colorblind-friendly palettes and localStorage persistence
  - `search.js` - Debounced search state with match computation across multiple fields
  - `year.js` - Year normalization utility for messy date strings
- **Enhanced features**:
  - JSON-based data loading from Primo API harvests
  - Improved accessibility (ARIA roles, keyboard navigation, focus management)
  - Search highlighting and explicit empty states
  - Enhanced detail panel with LC ranges, signal counts, and catalog links
  - Color palette selector with accessibility options
  - Real-time search with match counts and field-level feedback

The preview environment serves as a testing ground for new features before they are promoted to production.

---

## Repository Structure

```
ShelfSignals/
├── docs/                           # GitHub Pages deployment
│   ├── index.html                  # Production interface
│   ├── preview/
│   │   └── index.html              # Preview interface
│   ├── js/                         # Shared JavaScript modules
│   │   ├── signals.js              # Signal detection & registry
│   │   ├── lc.js                   # LC call number parser
│   │   ├── colors.js               # Color palette management
│   │   ├── search.js               # Search state & matching
│   │   └── year.js                 # Year normalization
│   └── data/                       # Collection data
│       ├── sekula_inventory.json   # CSV-compatible format
│       ├── sekula_index.json       # Primo API JSON format
│       └── sekula_index.csv        # CSV export
├── scripts/                        # Data collection tools
│   ├── sekula_indexer.py           # Primo API harvester
│   └── facet_scout.py              # Facet analysis utility
├── README.md                       # This file
├── CODEX_INSTRUCTIONS.md           # LLM assistant guidelines
└── COPILOT_INSTRUCTIONS.md         # Copilot behavior guidelines
```

---

## Thematic Alignment

ShelfSignals is purpose-built to reveal the **implicit structure** embedded within library collections. Rather than treating catalogs as flat databases, it recognizes that:

- **Numbering systems encode organization**: Call numbers, accession numbers, and shelf locations reflect historical decisions about classification and proximity.
- **Subjects reveal themes**: Subject headings and notes contain rich semantic signals about content, provenance, and research focus.
- **Patterns emerge at scale**: Clustering, sequence analysis, and visual representation make latent structures visible.

The Allan Sekula Library serves as the prototype collection because its thematic focus—photography, labor, maritime culture, critical theory—creates distinct signals that can be detected, visualized, and analyzed. This approach is **collection-neutral** and can be adapted to any catalog with structured metadata.

### Core Principles

1. **System-agnostic ingestion**: Works with any metadata source (APIs, CSV, HTML scraping)
2. **Normalization layer**: Standardizes heterogeneous field formats and vocabularies
3. **Configurable analysis**: Modular pattern detection adaptable to different collections
4. **Visual intelligence**: Transforms metadata into spatial, chromatic, and interactive representations
5. **Research-oriented**: Designed for discovery and insight, not end-user search

---

## Version History & Roadmap

### Current Versions

- **Production (v1.x)**: Stable interface with proven workflows and CSV-based data loading
- **Preview (v2.x)**: Experimental modular architecture with enhanced accessibility and JSON-native data

### Migration Path

Features proven in the preview environment will be selectively promoted to production. The modular JavaScript utilities (`signals.js`, `lc.js`, `colors.js`, `search.js`, `year.js`) represent reusable components that can be integrated into future analysis tools beyond the web interface.


