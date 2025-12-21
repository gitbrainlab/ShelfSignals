# ShelfSignals: Introduction & User Guide

## Table of Contents
- [What is ShelfSignals?](#what-is-shelfsignals)
- [Why ShelfSignals?](#why-shelfsignals)
- [Core Features](#core-features)
- [Getting Started](#getting-started)
- [Interface Overview](#interface-overview)
- [Use Cases](#use-cases)
- [Exhibit Interface Features](#exhibit-interface-features)
- [Technical Architecture](#technical-architecture)
- [Data Pipeline](#data-pipeline)
- [Privacy & Data Ethics](#privacy--data-ethics)
- [Accessibility](#accessibility)
- [Browser Support](#browser-support)
- [Advanced Features](#advanced-features)
- [Contributing](#contributing)
- [Documentation](#documentation)
- [About the Sekula Library](#about-the-sekula-library)

---

## What is ShelfSignals?

**ShelfSignals** is an innovative visual analytics framework designed to reveal the hidden patterns and organizational structures embedded within library collections. Rather than treating library catalogs as simple databases, ShelfSignals transforms metadata into rich, interactive visualizations that expose the implicit knowledge encoded in call numbers, subject classifications, and collection histories.

## Why ShelfSignals?

Traditional library interfaces focus on finding specific items. ShelfSignals takes a different approach—it helps you **discover patterns**, **explore themes**, and **understand relationships** across entire collections. It's designed for researchers, curators, librarians, and anyone interested in understanding how knowledge is organized on library shelves.

### Key Insights

Library collections contain implicit signals that reveal:
- **Historical organization**: How classifications evolved over time
- **Thematic clusters**: Books grouped by invisible conceptual threads
- **Sequential patterns**: Numbering systems that encode provenance
- **Subject relationships**: Connections between seemingly distant topics

## Core Features

### 🎨 Visual Collection Browser

Transform library metadata into an interactive "virtual shelf" where:
- **Books are represented as colored spines** based on their subject classification
- **LC call numbers** determine shelf position and visual proximity
- **Color themes** highlight different subject areas (Photography, Labor, Maritime, etc.)
- **Search and filtering** reveal patterns across thousands of items

### 🔍 Smart Search & Filtering

- **Real-time search** across titles, authors, subjects, and call numbers
- **Multi-field matching** with highlighted results
- **Subject-based filtering** using thematic signals
- **LC class filtering** for precise call number ranges

### 📊 Deep Facets: AI-Powered Content Detection

ShelfSignals includes **Embedded Photography Likelihood**—a probabilistic facet that estimates whether books contain photographic content, even when not cataloged as photography books.

**Features:**
- Conservative, metadata-driven scoring (0-100)
- Visual overlay with color-coded likelihood
- Detailed reasoning for each score
- Toggleable display in all interfaces

### 🎭 Three User Interfaces

ShelfSignals provides three specialized interfaces for different use cases:

#### 1. Production Interface (`/`)
- **URL**: https://evcatalyst.github.io/ShelfSignals/
- **Status**: Stable, proven workflows
- **Best for**: General exploration and research

#### 2. Preview Interface (`/preview/`)
- **URL**: https://evcatalyst.github.io/ShelfSignals/preview/
- **Status**: Experimental, enhanced features
- **Best for**: Testing new features and improved accessibility

#### 3. Exhibit Interface (`/preview/exhibit/`)
- **URL**: https://evcatalyst.github.io/ShelfSignals/preview/exhibit/
- **Status**: Museum-ready, public-facing
- **Best for**: Exhibitions, installations, and public engagement

## Getting Started

### Screenshots & Visual Examples

ShelfSignals provides rich visual interfaces for exploring library collections. Below is the main Preview interface:

![ShelfSignals Preview Interface](docs/images/preview-interface.png)
*The Preview interface showing the virtual shelf, search panel, and collection visualization*

**Additional Visual Examples:**
- **Loading State**: The interface displays "Loading Sekula Library data..." while fetching collection metadata
- **Detail Panels**: Click any book spine to view full catalog information, LC call numbers, and subject classifications
- **Color Overlays**: Toggle between different visualization modes (LC class, thematic signals, photo likelihood)
- **Exhibit Interface**: Museum-ready UI with curated paths and kiosk mode (see [live demo](https://evcatalyst.github.io/ShelfSignals/preview/exhibit/))

> **Tip**: Visit the [live Preview interface](https://evcatalyst.github.io/ShelfSignals/preview/) to explore all features interactively.

### Accessing ShelfSignals

Visit any of the three interfaces (no installation required):
- **Try it now**: [Preview Interface](https://evcatalyst.github.io/ShelfSignals/preview/)
- **Museum mode**: [Exhibit Interface](https://evcatalyst.github.io/ShelfSignals/preview/exhibit/)

### Basic Workflow

1. **Browse the virtual shelf** - Scroll through the visual representation of the collection
2. **Search for topics** - Use the search box to find books by title, author, or subject
3. **Filter by theme** - Toggle color overlays to highlight specific subject areas
4. **Explore details** - Click any book spine to view complete catalog information
5. **Export selections** - Use the Digital Receipt system to save and share curated collections

### Interface Overview

![ShelfSignals Preview Interface](docs/images/preview-interface.png)
*The ShelfSignals Preview interface displaying the virtual shelf with LC classification-based coloring and search capabilities*

> **Note**: Additional screenshots showing the loading state, detail panels, and exhibit interface can be found in the live applications. Screenshots in this documentation show the actual working interface as deployed on GitHub Pages.

The interface consists of three main areas:

#### Left Panel: Signals & Search
- **Search box**: Real-time filtering across all fields
- **Color by LC Class**: Toggle classification-based coloring
- **Signal themes**: Filter by Photography, Labor, Maritime, etc.
- **Legend**: Visual guide to active color schemes

#### Center Panel: Collection View
- **Virtual shelf**: Visual representation of the collection
- **Book spines**: Click to view details
- **Loading indicator**: Shows data processing status
- **Scroll navigation**: Browse through the entire collection

#### Right Panel: Details
- **Item information**: Full catalog metadata
- **LC call number**: Classification details
- **Subject headings**: Topical classifications
- **Catalog links**: Direct access to library records
- **Photo likelihood**: AI-powered content detection (when available)

## Use Cases

### For Researchers
- **Pattern discovery**: Find thematic clusters across subject boundaries
- **Collection analysis**: Understand how topics are distributed
- **Sequence detection**: Identify numbering patterns and anomalies
- **Cross-collection studies**: Compare organizational structures

### For Librarians & Curators
- **Collection visualization**: See the shelf from a bird's-eye view
- **Gap analysis**: Identify underrepresented areas
- **Weeding decisions**: Visual assessment of shelf density
- **Exhibition planning**: Curate thematic pathways through the collection

### For Educators
- **Library instruction**: Demonstrate classification systems visually
- **Information literacy**: Teach subject relationships and discovery
- **Research workshops**: Guide students through collection exploration
- **Digital humanities**: Integrate with metadata analysis courses

### For Museum Visitors
- **Curated paths**: Explore pre-selected thematic journeys
- **Digital receipts**: Take home personalized collections
- **Kiosk mode**: Self-guided exploration in exhibition spaces
- **Accessibility**: Enhanced interfaces for diverse needs

## Exhibit Interface Features

The **Exhibit environment** is purpose-built for public-facing installations:

### 🗺️ Curated Paths
Eight thematic journeys through the collection:
- **Labor & Images** ⚙️📷
- **Maritime Globalization** 🚢🌊
- **Borders & Migration** 🌍✈️
- **Archives & Museums** 🏛️📚
- **Cities & Logistics** 🏙️🚛
- **Theory & Method** 💭📖
- **Documentary Practice** 📹🎬
- **Industrial Capital** 🏭💰

### 🎫 Digital Receipt System
Take home your curated collections:
- **Export/import** shelf configurations
- **SHA-256 verification** for data integrity
- **QR codes** for easy sharing
- **Human-readable IDs**: `SS-XXXX-XXXX-XXXX`
- **No server storage** required—fully portable

### 🖥️ Kiosk Mode
Optimized for exhibition installations:
- **Large typography** for readability (3.5rem headings)
- **High contrast** for various lighting conditions
- **Inactivity timer** (2 minutes) auto-resets to attract screen
- **Controlled navigation** for public touchscreens
- **URL parameter**: Add `?kiosk=1` to any Exhibit URL

### Design Philosophy
- **Jony Ive aesthetic**: Minimal, calm, strong hierarchy
- **Fast & focused**: Progressive disclosure with 3 primary actions
- **Portable & verifiable**: Digital Receipt system for take-home curation
- **Exhibition-ready**: Tested in museum and gallery environments

## Technical Architecture

### Static Site, No Server Required
- **Pure HTML/CSS/JavaScript**—no backend dependencies
- **GitHub Pages deployment**—instant global availability
- **Offline-capable**—data loads once and caches locally
- **Mobile-responsive**—works on any device

### Modular JavaScript Utilities
Located in `docs/js/`:
- **`signals.js`**: Centralized signal (theme) registry and keyword matching
- **`lc.js`**: LC call number parser for classification and sorting
- **`colors.js`**: Color palette management with accessibility options
- **`search.js`**: Debounced search with multi-field matching
- **`year.js`**: Date normalization for messy temporal data
- **`receipt.js`**: Digital Receipt system (RFC 8785 + SHA-256)

### Data Formats
- **JSON-native**: `sekula_index.json` from Primo API harvests
- **CSV-compatible**: `sekula_inventory.json` for spreadsheet analysis
- **CSV export**: `sekula_index.csv` for external tools

### Performance Optimizations
- **Lazy loading**: Books render progressively as you scroll
- **Debounced search**: Prevents UI lag during typing
- **IndexedDB caching**: Faster subsequent loads
- **Modular architecture**: Load only what you need

## Data Pipeline

ShelfSignals uses a multi-stage pipeline for data collection and enrichment:

### 1. Harvesting
**Script**: `scripts/sekula_indexer.py`
- Connects to Primo API to harvest catalog records
- Normalizes metadata fields
- Extracts LC call numbers and subject headings

### 2. Analysis
**Scripts**: `scripts/facet_scout.py`, `scripts/photo_feature_extractor.py`
- Detects thematic patterns in metadata
- Generates feature packets for AI scoring
- Identifies classification clusters

### 3. AI Enrichment
**Script**: `scripts/photo_likelihood_scorer.py`
- Uses xAI (Grok) API for content detection
- Conservative, evidence-based scoring
- Provides reasoning for each assessment

### 4. Merging & Export
**Scripts**: `scripts/merge_scores_to_json.py`, `scripts/merge_scores_to_csv.py`
- Integrates AI scores with catalog data
- Exports enriched datasets
- Maintains data integrity with verification tools

## Privacy & Data Ethics

ShelfSignals is designed with privacy and transparency:
- **No user tracking**: No analytics, cookies, or user profiling
- **Public metadata only**: All data is from public library catalogs
- **Open source**: Full transparency in code and methods
- **Portable exports**: Users control their curated data
- **No server storage**: Digital Receipts are client-side only

## Accessibility

All interfaces include:
- **ARIA roles** for screen reader compatibility
- **Keyboard navigation** for mouse-free operation
- **High contrast modes** for visual impairments
- **Colorblind-friendly palettes** for diverse color perception
- **Scalable typography** for readability
- **Focus management** for logical tab order

## Browser Support

ShelfSignals works on all modern browsers:
- **Chrome/Edge** 90+
- **Firefox** 88+
- **Safari** 14+
- **Mobile browsers**: iOS Safari, Chrome Mobile

## Advanced Features

### Color Palettes
Choose from multiple visualization schemes:
- **Default**: Balanced, general-purpose palette
- **Colorblind-friendly**: Optimized for deuteranopia and protanopia
- **High contrast**: Enhanced visibility for low-vision users
- **Custom themes**: Persistent localStorage preferences

### Search Operators
Use advanced search syntax:
- **Exact phrases**: `"maritime labor"`
- **Field prefixes**: `author:sekula`, `subject:photography`
- **Boolean logic**: Implicit AND across terms
- **Fuzzy matching**: Handles spelling variations

### LC Call Number Navigation
- **Class filtering**: Click LC class badges to filter
- **Range browsing**: Navigate by shelf sections
- **Sorting keys**: Proper LC sort order (not alphabetic)
- **Cutter number support**: Full LC classification parsing

## Contributing

ShelfSignals is an open research project. Contributions welcome:
- **Feature requests**: Open an issue on GitHub
- **Bug reports**: Include browser version and steps to reproduce
- **Data contributions**: Adapt to new collections with metadata connectors
- **Code improvements**: Pull requests for modular utilities

## Documentation

### Full Documentation
- **README.md**: Comprehensive technical documentation
- **PHOTO_LIKELIHOOD_FACET.md**: Deep Facets implementation guide
- **Repository**: https://github.com/evcatalyst/ShelfSignals

### Quick Links
- [Production Interface](https://evcatalyst.github.io/ShelfSignals/)
- [Preview Interface](https://evcatalyst.github.io/ShelfSignals/preview/)
- [Exhibit Interface](https://evcatalyst.github.io/ShelfSignals/preview/exhibit/)
- [GitHub Repository](https://github.com/evcatalyst/ShelfSignals)

## About the Sekula Library

The inaugural ShelfSignals deployment visualizes the **Allan Sekula Library Collection**—a research library focused on:
- **Photography** as documentary practice and critical medium
- **Labor history** and working-class studies
- **Maritime culture** and globalization
- **Critical theory** and visual studies

The collection's thematic coherence makes it an ideal test case for pattern detection, but ShelfSignals is **collection-neutral** and can be adapted to any library catalog with structured metadata.

## License

ShelfSignals is an open-source research project. See the repository for license details.

---

**Ready to explore?** [Launch ShelfSignals Preview →](https://evcatalyst.github.io/ShelfSignals/preview/)
