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
- **Access**: Deployed at the repository's GitHub Pages root URL

The production site provides a mature interface with CSV-based data loading and legacy controls. It includes shelf visualization, cluster mapping, and detailed item views.

### Preview Environment (`/preview/`)
- **Location**: `docs/preview/index.html`
- **Data Source**: `docs/data/sekula_index.json` (JSON-native format from Primo API)
- **Status**: Experimental, modular architecture
- **Access**: Available at `/preview/` relative to the repository URL

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

## Repository Structure (proposed)


