# ShelfSignals Documentation

## What is ShelfSignals?

ShelfSignals is a **collection intelligence framework** that reveals hidden patterns and organizational structures embedded within library and archive metadata. Rather than treating catalogs as flat databases, ShelfSignals recognizes that classification systems, numbering sequences, and subject arrangements encode implicit knowledge about how collections were built, organized, and curated over time.

The framework is **source-agnostic** and **collection-neutral**—it can ingest metadata from any institution's catalog (API, CSV, HTML scraping) and apply configurable pattern detection modules to reveal structure, anomalies, and thematic relationships.

## Core Concepts

ShelfSignals uses a specific vocabulary to describe its approach to metadata analytics:

### Facets
Attributes or dimensions of metadata that can be analyzed independently or in combination:
- **Standard facets**: Subject headings, LC classification, publication year, publisher
- **Deep facets**: AI-powered probabilistic content detection (e.g., Embedded Photography Likelihood)
- **Derived facets**: Computed attributes like sequence gaps, cluster membership, temporal patterns

### Signals
Thematic patterns or conceptual threads detected in metadata through keyword matching, subject analysis, or statistical clustering. Examples from the Sekula Library deployment:
- Photography & Visual Culture
- Labor & Working Class
- Maritime & Globalization
- Critical Theory & Method

Signals can overlap—a single item might carry multiple thematic signals.

### Harvesting
The process of collecting catalog records from external sources:
- API connectors (e.g., Primo VE, OCLC, ArchivesSpace)
- CSV/Excel imports
- HTML/DOM extraction for web-based catalogs
- Batch exports from ILS systems

### Receipts
Portable, verifiable exports of curated collections or interface states:
- **RFC 8785 canonical JSON** for deterministic serialization
- **SHA-256 verification** for integrity checking
- **Human-readable IDs**: `SS-XXXX-XXXX-XXXX`
- **No server storage required**—fully client-side

See [docs/receipts.md](receipts.md) for detailed documentation.

### Interfaces
User-facing environments for exploring analyzed collections:
- **Production**: Stable interface for general research
- **Preview**: Experimental features and enhanced accessibility
- **Exhibit**: Museum-ready installation with curated paths and kiosk mode

Each interface serves different personas (researchers, curators, public visitors) while sharing the same underlying data and analysis pipeline.

See [docs/interfaces.md](interfaces.md) for complete interface documentation.

## What Problems Does ShelfSignals Solve?

### 1. Hidden Structure in Metadata
Traditional catalog searches return individual items. ShelfSignals reveals:
- **Sequence patterns**: Accession number gaps that indicate missing items or collection reorganization
- **Classification clusters**: How subject areas are distributed across the shelf
- **Temporal patterns**: Publication trends within specific LC classes or topics
- **Provenance signals**: Numbering systems that encode donor collections or acquisition batches

### 2. Cross-Domain Discovery
Subject headings often partition knowledge into rigid silos. ShelfSignals:
- **Detects thematic overlaps**: Items that bridge multiple subject areas
- **Maps conceptual relationships**: Finds items connected by non-obvious keywords or patterns
- **Surfaces latent content**: AI-powered deep facets detect content not captured in traditional cataloging

### 3. Collection Intelligence for Curation
For librarians, archivists, and curators:
- **Visual gap analysis**: Identify underrepresented subject areas
- **Weeding decisions**: Spot duplicates, outliers, or low-use clusters
- **Exhibition planning**: Build thematic pathways that follow shelf logic
- **Acquisition strategy**: Understand collection strengths and weaknesses at scale

### 4. Research-Oriented Metadata Analysis
For scholars and digital humanities researchers:
- **Exploratory data analysis**: Pattern mining in catalog metadata
- **Reproducible pipelines**: Version-controlled analysis scripts with verifiable outputs
- **Portable results**: Export curated subsets for external analysis
- **Integration-ready**: JSON/CSV exports for R, Python, Excel, or visualization tools

## Use Case Map

### Researcher: Pattern Discovery
**Goal**: Find thematic clusters that cross traditional subject boundaries

**Workflow**:
1. Browse the virtual shelf visualization (Preview or Exhibit interface)
2. Toggle signal overlays to highlight thematic patterns (Photography, Labor, Maritime)
3. Use search to refine by keyword, LC class, or year range
4. Export curated subsets using Digital Receipts for citation or further analysis

**Outputs**:
- Visual exploration via web interface
- Portable JSON/CSV exports with verification hashes
- Screenshot documentation for publications

---

### Librarian: Collection Assessment
**Goal**: Understand shelf density, gaps, and organizational structure

**Workflow**:
1. Run harvesting scripts to ingest current catalog state (`sekula_indexer.py`)
2. Generate facet analysis reports (`facet_scout.py`)
3. Review LC classification distribution and sequence gaps
4. Identify areas for targeted acquisition or weeding

**Outputs**:
- Aggregate statistics (items per LC class, year distribution)
- JSON index with normalized metadata
- CSV exports for spreadsheet analysis

---

### Curator: Exhibition Planning
**Goal**: Build thematic narratives that follow shelf logic

**Workflow**:
1. Use Exhibit interface to explore curated paths
2. Search and filter to find items matching exhibition themes
3. Annotate selections with curatorial notes (via Digital Receipt metadata)
4. Generate QR codes or shareable URLs for installation labels

**Outputs**:
- Curated paths configuration (JSON)
- Digital Receipts for visitor take-home
- Verifiable exports for catalog integration

---

### Archivist: Provenance Analysis
**Goal**: Detect donor collections or accession batches in mixed holdings

**Workflow**:
1. Analyze call number sequences and accession patterns
2. Use temporal facets (publication year, acquisition date) to identify clusters
3. Generate reports on numbering anomalies or gaps
4. Cross-reference with donor records or historical acquisition logs

**Outputs**:
- Sequence analysis reports (gaps, overlaps, outliers)
- Cluster visualizations by temporal or spatial patterns
- Provenance hypotheses for further research

---

### Data Scientist: Metadata Analytics
**Goal**: Integrate collection metadata into machine learning or network analysis

**Workflow**:
1. Export enriched JSON with AI-scored deep facets
2. Load into Python/R for statistical analysis or visualization
3. Build predictive models (e.g., missing subject headings, content detection)
4. Validate with reproducible pipeline scripts

**Outputs**:
- Training datasets with ground truth labels
- Feature engineering from controlled vocabularies
- Model performance metrics and validation reports

## Documentation Map

### Getting Started
- **[README.md](../README.md)**: Quick overview and repository structure
- **[INTRODUCTION.md](../INTRODUCTION.md)**: Visual walkthrough with screenshots and use cases

### Deep Dive
- **[docs/pipeline.md](pipeline.md)**: Data model, normalization, enrichment, and reproducibility practices
- **[docs/interfaces.md](interfaces.md)**: Production/Preview/Exhibit interface documentation
- **[docs/receipts.md](receipts.md)**: Digital Receipt system for portable, verifiable exports
- **[docs/operations.md](operations.md)**: Running locally, scheduling, storage layout, and export formats

### Advanced Topics
- **[docs/PHOTO_LIKELIHOOD_FACET.md](PHOTO_LIKELIHOOD_FACET.md)**: AI-powered content detection implementation
- **Technical Architecture**: See [INTRODUCTION.md - Technical Architecture](../INTRODUCTION.md#technical-architecture)

## Key Principles

### 1. Source-Agnostic Ingestion
ShelfSignals is designed to work with **any metadata source**:
- **No vendor lock-in**: Adapt connectors to any catalog system
- **Heterogeneous formats**: Normalize CSV, JSON, MARC, Dublin Core, or custom schemas
- **API-first design**: Automated harvesting with checkpointing and retry logic

### 2. Normalization Layer
A consistent data model ensures analysis modules work across diverse collections:
- **Field mapping**: Translate local vocabularies to standard facets
- **LC classification parsing**: Extract class, subclass, cutter, year from call numbers
- **Date normalization**: Handle messy temporal data (ranges, circa, unknowns)
- **Publisher canonicalization**: Merge variant names and imprints

### 3. Configurable Analysis
Modular pattern detection adaptable to different collections:
- **Pluggable modules**: Sequence detection, clustering, anomaly detection
- **Parameter tuning**: Adjust thresholds, weights, or scoring functions
- **Custom vocabularies**: Define domain-specific signals or facets

### 4. Visual Intelligence
Transform metadata into spatial, chromatic, and interactive representations:
- **Virtual shelf**: Books as colored spines positioned by LC class
- **Overlay modes**: Toggle between classification, thematic signals, or AI-scored facets
- **Progressive disclosure**: Detail panels, filtering, and drill-down navigation

### 5. Research-Oriented Design
Built for discovery and insight, not end-user search:
- **Reproducible pipelines**: Version-controlled scripts with documented parameters
- **Verifiable outputs**: Cryptographic hashes for data integrity
- **Portable results**: JSON/CSV exports with canonical serialization
- **Open methods**: Transparent algorithms and scoring rubrics

## External Dependencies

### Required for Harvesting
- **Python 3.8+**: Scripting runtime
- **requests library**: HTTP API calls (`pip install requests`)
- **Institution-specific API access**: May require authentication or VPN

### Optional for AI Enrichment
- **xAI (Grok) API key**: For deep facet scoring (Embedded Photography Likelihood)
  - Conservative rate limits: ~100 requests/hour (batch processing)
  - Safe default: Mock mode for testing without API calls
  - Cost: Billed per prompt (volume-dependent)

### Web Interfaces (No Dependencies)
- **Static HTML/CSS/JavaScript**: No server, database, or runtime required
- **GitHub Pages**: Free hosting for public repositories
- **Browser compatibility**: Chrome 90+, Firefox 88+, Safari 14+

### Safe Defaults
- **Mock API mode**: Test pipelines without external API costs
- **Checkpointing**: Resume interrupted harvests without re-fetching
- **Rate limiting**: Configurable delays and exponential backoff
- **Offline-capable interfaces**: Data caches locally after first load

## Next Steps

1. **Explore a live deployment**: [Preview Interface](https://gitbrainlab.github.io/ShelfSignals/preview/) or [Exhibit Interface](https://gitbrainlab.github.io/ShelfSignals/preview/exhibit/)
2. **Understand the data pipeline**: Read [docs/pipeline.md](pipeline.md)
3. **Learn about interfaces**: See [docs/interfaces.md](interfaces.md)
4. **Run locally**: Follow [docs/operations.md](operations.md)
5. **Explore advanced features**: [docs/PHOTO_LIKELIHOOD_FACET.md](PHOTO_LIKELIHOOD_FACET.md)

## Contributing

ShelfSignals is an open research project. We welcome:
- **Feature requests**: Open an issue on GitHub
- **Bug reports**: Include browser/environment details and reproduction steps
- **Data contributions**: Adapt to new collections with metadata connectors
- **Code improvements**: Pull requests for modular utilities or analysis modules

See [README.md - Contributing](../README.md#contributing) for details.

## License

ShelfSignals is an open-source research project. See the repository for license details.
