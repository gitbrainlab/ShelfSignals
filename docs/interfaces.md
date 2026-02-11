# ShelfSignals Interfaces

## Overview

ShelfSignals provides **three specialized web interfaces** for exploring collection metadata, each optimized for different user personas and contexts:

1. **Production** (`/`) - Stable, research-oriented interface
2. **Preview** (`/preview/`) - Experimental features and enhanced accessibility
3. **Exhibit** (`/preview/exhibit/`) - Museum-ready installation with curated paths

All interfaces share the same underlying data but differ in **UI design**, **feature sets**, and **intended audience**.

## Interface Comparison

| Feature | Production | Preview | Exhibit |
|---------|-----------|---------|---------|
| **Status** | Deprecated (v1.x) | Active development (v2.x) | Active (v2.x) |
| **Data Format** | CSV-compatible JSON | JSON-native (Primo API) | JSON-native (Primo API) |
| **Target Audience** | Researchers | Researchers, librarians | Museum visitors, public |
| **UI Philosophy** | Functional, data-dense | Modular, accessible | Minimal, exhibition-ready |
| **Accessibility** | Basic | Enhanced (ARIA, keyboard nav) | Enhanced + kiosk mode |
| **Key Features** | Virtual shelf, LC coloring | All Production + AI overlays | Curated paths, Digital Receipts |
| **Performance** | Known issues (freezing) | Optimized | Optimized |
| **Recommended Use** | Legacy compatibility | Current best practice | Public installations |

## Production Interface (`/`)

### Purpose
Stable, proven interface for general collection exploration and research.

### Location
- **File**: `docs/index.html`
- **URL**: https://gitbrainlab.github.io/ShelfSignals/
- **Data Source**: `docs/data/sekula_inventory.json` (CSV-compatible format)

### Status
⚠️ **Deprecated**: Known performance issues with large datasets (freezing, slow rendering). Users are automatically redirected to Preview v2.x for the best experience.

### Features
- **Virtual Shelf**: Books rendered as colored spines in LC call number order
- **LC Classification Coloring**: Color-coded by main LC class (TR = red, N = blue, etc.)
- **Search**: Real-time filtering across title, author, subject fields
- **Detail Panel**: Click any spine to view full catalog metadata
- **Signal Overlays**: Toggle Photography, Labor, Maritime, Theory themes
- **Photo Likelihood Overlay**: Show/hide AI-scored embedded photography facet

### Architecture
- **Monolithic HTML**: Single-file interface with embedded CSS/JavaScript
- **CSV-to-JSON data loading**: Flattened structure for backward compatibility
- **Synchronous rendering**: All spines rendered at once (performance bottleneck)

### Known Issues
1. **Freezing with large datasets** (>5,000 items): Synchronous DOM manipulation blocks UI thread
2. **Memory leaks**: Event listeners not properly cleaned up
3. **Slow search**: No debouncing or index optimization

### Build/Run Steps
No build required—pure static HTML:

```bash
# Local development
cd /home/runner/work/ShelfSignals/ShelfSignals/docs
python -m http.server 8000
# Open http://localhost:8000 in browser

# Production deployment (GitHub Pages)
# Automatically deployed from docs/ folder on push to main branch
```

### Migration Notes
New features are **not** backported to Production. Users should migrate to Preview for:
- Better performance
- Accessibility improvements
- New deep facets and analysis modules

## Preview Interface (`/preview/`)

### Purpose
Experimental environment for testing new features before promotion to production. Showcases modular architecture with enhanced accessibility.

### Location
- **File**: `docs/preview/index.html`
- **URL**: https://gitbrainlab.github.io/ShelfSignals/preview/
- **Data Source**: `docs/data/sekula_index.json` (JSON-native from Primo API)

### Status
✅ **Active Development**: Recommended interface for all users. Serves as staging ground for production-bound features.

### Features

#### Core Visualization
- **Virtual Shelf**: Progressive rendering with lazy loading
- **Color Modes**:
  - LC Classification (default)
  - Thematic signals (Photography, Labor, Maritime, Theory)
  - Photo Likelihood (AI-scored overlay with 4 buckets)
- **Detail Panel**: Enhanced metadata display with:
  - LC class breakdown with ranges
  - Signal counts and keywords
  - Direct catalog links
  - Photo likelihood score and reasoning (when available)

#### Search & Filtering
- **Debounced Search**: 300ms delay prevents UI lag during typing
- **Multi-Field Matching**: Title, author, subjects, call number, notes
- **Match Highlighting**: Visual feedback showing which fields matched
- **Empty States**: Explicit messaging when no results found
- **Signal Filters**: Toggle visibility of items by thematic signal
- **LC Class Filters**: Filter by main class or subclass ranges
- **Photo Bucket Filters**: Filter by AI likelihood bands (Strongly Likely, Likely, Plausible, Unlikely)

#### Accessibility
- **ARIA Roles**: Screen reader support for all interactive elements
- **Keyboard Navigation**: Tab order, Enter/Space for activation, Escape to close
- **Focus Management**: Proper focus trapping in modals and detail panels
- **High Contrast Mode**: Toggle for visual impairments
- **Colorblind-Friendly Palettes**: Alternative color schemes (stored in localStorage)
- **Scalable Typography**: Responsive font sizing

#### Performance Optimizations
- **Lazy Loading**: Books render progressively as they enter viewport
- **Debounced Search**: Prevents excessive re-rendering during typing
- **IndexedDB Caching**: Faster subsequent loads (data cached locally)
- **Modular JavaScript**: Load only needed utilities

### Architecture

#### Modular JavaScript Utilities
Located in `docs/js/`:

1. **`signals.js`** - Signal registry and keyword matching
   ```javascript
   // Detect thematic signals in metadata
   detectSignals(item)  // → ["photography", "maritime"]
   getSignalColor(signalId)  // → "#e74c3c"
   ```

2. **`lc.js`** - LC call number parser
   ```javascript
   // Parse and sort LC call numbers
   parseCallNumber("TR820 .S45 1995")
   // → { class: "TR", subclass: "TR820", cutter: "S45", year: "1995", sortKey: "TR 0820 S45 1995" }
   ```

3. **`colors.js`** - Color palette management
   ```javascript
   // Unified color logic with persistence
   getColorForClass(lcClass)  // → "#ff6b6b"
   setPalette("colorblind")  // Switch to colorblind-friendly palette
   ```

4. **`search.js`** - Debounced search state
   ```javascript
   // Search with match computation
   performSearch(query, items)  // → { matches: [...], count: 42 }
   ```

5. **`year.js`** - Year normalization
   ```javascript
   // Handle messy temporal data
   normalizeYear("c1995")  // → 1995
   normalizeYear("[1990-1995]")  // → 1990
   ```

6. **`receipt.js`** - Digital Receipt system
   ```javascript
   // Generate verifiable exports (see docs/receipts.md)
   generateReceipt(state)  // → { id: "SS-A1B2-C3D4-E5F6", hash: "...", data: {...} }
   ```

### Build/Run Steps
No build required—pure static HTML + modular JavaScript:

```bash
# Local development
cd /home/runner/work/ShelfSignals/ShelfSignals/docs/preview
python -m http.server 8001
# Open http://localhost:8001 in browser

# Production deployment (GitHub Pages)
# Automatically deployed from docs/preview/ folder on push to main branch
```

### Data Loading Flow
1. Fetch `docs/data/sekula_index.json` (JSON array of ~11,000 items)
2. Parse LC call numbers and compute sort keys (`lc.js`)
3. Detect signals in metadata (`signals.js`)
4. Normalize years and decades (`year.js`)
5. Render virtual shelf with lazy loading
6. Attach event listeners for search, filters, detail panel

### User Workflow Example
1. **Browse**: Scroll through virtual shelf, see colored spines by LC class
2. **Search**: Type "maritime labor" → see highlighted matches
3. **Filter**: Toggle "Labor" signal → only Labor-related items visible
4. **Inspect**: Click spine → detail panel with full metadata, LC breakdown, signals
5. **Export**: Generate Digital Receipt → download JSON or QR code

## Exhibit Interface (`/preview/exhibit/`)

### Purpose
Museum-ready interface for public-facing exhibitions, gallery installations, and educational kiosks. Emphasizes **curated paths**, **progressive disclosure**, and **take-home collections** via Digital Receipts.

### Location
- **File**: `docs/preview/exhibit/index.html`
- **URL**: https://gitbrainlab.github.io/ShelfSignals/preview/exhibit/
- **Data Source**: `docs/data/sekula_index.json` (same as Preview)
- **Curated Paths**: `docs/preview/exhibit/curated-paths.json`

### Status
✅ **Active**: Recommended for museum installations, library kiosks, and public engagement.

### Design Philosophy

#### Jony Ive Aesthetic
- **Minimal interface**: Strong hierarchy, generous whitespace
- **Calm interactions**: Subtle animations, no visual clutter
- **Typography-first**: Large, readable text (3.5rem headings in kiosk mode)
- **Progressive disclosure**: Hide complexity until needed

#### Fast & Focused
- **3 Primary Actions** (front and center):
  1. 🎨 **Explore Themes** - Browse by signal overlays
  2. 🔍 **Search** - Direct item lookup
  3. 🗺️ **Curated Paths** - Pre-selected thematic journeys
- **Advanced filters hidden by default** - Click "Advanced Filters" to expand
- **Details drawer (not modal)** - Non-intrusive item presentation

#### Portable & Verifiable
- **Digital Receipt System**: Export curated collections without server storage
- **QR Code Sharing**: Generate scannable codes for mobile access
- **URL Fragment Encoding**: Shareable links with embedded state
- **No login required**: Fully client-side, privacy-respecting

### Features

#### 1. Curated Paths
**8 thematic journeys** through the collection, hand-picked by curators:

| Path | Icon | Description | Items |
|------|------|-------------|-------|
| **Labor & Images** | ⚙️📷 | Photography as documentary labor practice | 18 |
| **Maritime Globalization** | 🚢🌊 | Shipping, ports, and global capital flows | 15 |
| **Borders & Migration** | 🌍✈️ | Movement, displacement, border regimes | 12 |
| **Archives & Museums** | 🏛️📚 | Institutional memory and collection politics | 14 |
| **Cities & Logistics** | 🏙️🚛 | Urban infrastructure and distribution networks | 16 |
| **Theory & Method** | 💭📖 | Critical frameworks and research practice | 20 |
| **Documentary Practice** | 📹🎬 | Film, video, and observational methods | 13 |
| **Industrial Capital** | 🏭💰 | Manufacturing, automation, financialization | 17 |

**Data structure** (`curated-paths.json`):
```json
{
  "paths": [
    {
      "id": "labor-images",
      "title": "Labor & Images",
      "icon": "⚙️📷",
      "description": "Photography as documentary labor practice",
      "curator_note": "Explores how photographic work intersects with labor history...",
      "item_ids": [
        "alma991002311449708431",
        "alma991002311450008431",
        ...
      ]
    }
  ]
}
```

**User flow**:
1. Click "🗺️ Curated Paths" button
2. Select a path from the menu
3. Virtual shelf filters to show only path items
4. Curator note appears in header
5. Navigate between items or return to full shelf

#### 2. Digital Receipt System
**Portable, verifiable exports** of user-curated collections.

**Features**:
- **RFC 8785 canonical JSON** - Deterministic serialization
- **SHA-256 verification** - Tamper-proof integrity checking
- **Human-readable IDs** - `SS-A1B2-C3D4-E5F6` format
- **No server storage** - Fully client-side (privacy-respecting)

**Export formats**:
- **JSON Download**: `receipt-SS-A1B2-C3D4-E5F6.json`
- **QR Code**: PNG image for mobile scanning
- **URL Fragment**: `#receipt=...` shareable link

**Import/Restore**:
- Drag-and-drop JSON file
- Scan QR code with mobile camera
- Navigate to URL with `#receipt=...` fragment

**See [docs/receipts.md](receipts.md) for complete documentation.**

#### 3. Kiosk Mode
**Optimized for unattended public installations.**

**Activation**: Add `?kiosk=1` to URL
```
https://gitbrainlab.github.io/ShelfSignals/preview/exhibit/?kiosk=1
```

**Kiosk-specific features**:
- **Large typography**: 3.5rem headings, 1.25rem body text
- **High contrast**: Optimized for exhibition lighting conditions
- **Inactivity timer**: Auto-reset to attract screen after 2 minutes of no interaction
- **Controlled navigation**: External links open in same tab (not new windows)
- **Simplified UI**: Hide advanced features, focus on primary actions
- **Fullscreen mode**: Recommended for touchscreen kiosks

**Reset behavior** (after 2 min idle):
1. Clear all filters and search
2. Return to full shelf view
3. Show attract screen: "Touch to explore the collection"
4. Resume normal interaction on any touch/click

#### 4. Progressive Disclosure
**Hide complexity until needed.**

**Primary actions** (always visible):
- 🎨 Explore Themes (signal overlays)
- 🔍 Search (text input)
- 🗺️ Curated Paths (dropdown menu)

**Secondary actions** (revealed on demand):
- Advanced Filters (click to expand)
  - LC Class filters
  - Photo Likelihood buckets
  - Signal toggles
- Color Palette selector (settings icon)
- Digital Receipt export (share icon)

**Detail drawer** (not modal):
- Slides in from right
- Doesn't block shelf view
- Dismissable with Escape or click outside
- Shows full metadata, signals, photo likelihood

### Architecture

#### Parallel UI Shell
Exhibit is a **separate HTML file** (`docs/preview/exhibit/index.html`) that:
- Shares JavaScript modules from `docs/js/` (signals, lc, colors, search, receipt)
- Loads same data (`docs/data/sekula_index.json`)
- Implements different UI layout and interaction patterns
- Adds curated paths layer (`curated-paths.json`)

#### Code Reuse
- **Data loading**: Same JSON parsing logic as Preview
- **Search logic**: Same `search.js` module
- **LC parsing**: Same `lc.js` module
- **Receipt generation**: Same `receipt.js` module
- **Signal detection**: Same `signals.js` module

#### Divergence from Preview
- **Layout**: Horizontal navigation bar (not sidebar)
- **Detail view**: Drawer (not modal)
- **Primary actions**: Curated paths front and center
- **Advanced filters**: Hidden by default
- **Typography**: Larger scale for public viewing
- **Kiosk mode**: Additional UI state for unattended operation

### Build/Run Steps
No build required—pure static HTML + shared JavaScript modules:

```bash
# Local development
cd /home/runner/work/ShelfSignals/ShelfSignals/docs/preview/exhibit
python -m http.server 8002
# Open http://localhost:8002 in browser

# Kiosk mode
# Open http://localhost:8002?kiosk=1

# Production deployment (GitHub Pages)
# Automatically deployed from docs/preview/exhibit/ folder on push to main branch
```

### User Workflow Examples

#### Casual Visitor (Kiosk)
1. **Attract screen**: "Touch to explore the Allan Sekula Library collection"
2. **Touch screen** → shelf loads with colored spines
3. **See prompt**: "Try: Explore Themes | Search | Curated Paths"
4. **Click "Curated Paths"** → menu of 8 themed journeys
5. **Select "Labor & Images"** → shelf filters to 18 items, curator note appears
6. **Click spine** → detail drawer with photo, metadata, signals
7. **Idle for 2 min** → auto-reset to attract screen

#### Museum Visitor (Take-Home Collection)
1. **Browse shelf** via search or curated paths
2. **Click 5-10 items** of interest (spines marked as "selected")
3. **Click share icon** → "Export Digital Receipt"
4. **Download JSON** or **scan QR code** with phone
5. **Email to self** or **save to cloud**
6. **At home**: Upload JSON to retrieve exact collection

#### Researcher (Advanced Exploration)
1. **Search**: "maritime labor"
2. **Click "Advanced Filters"** → expand LC class, signals, photo likelihood
3. **Filter**: LC class = "HD" (Economics), Signal = "Labor", Photo Likelihood = "Likely"
4. **Review results**: ~50 items matching all criteria
5. **Export Receipt**: Download JSON for citation in paper
6. **Verify integrity**: Check SHA-256 hash in receipt

### Curated Paths Management

#### Editing Paths
**File**: `docs/preview/exhibit/curated-paths.json`

To add or modify paths:
1. Edit JSON file with text editor
2. Verify `item_ids` exist in `sekula_index.json`
3. Test in browser (paths auto-reload on file change during development)
4. Commit changes to Git

**Example path entry**:
```json
{
  "id": "new-path-id",
  "title": "New Thematic Path",
  "icon": "🎨📐",
  "description": "Brief one-line description",
  "curator_note": "Longer explanation of curatorial choices, themes, and connections between items...",
  "item_ids": [
    "alma991002311449708431",
    "alma991002311450008431"
  ]
}
```

#### Best Practices
- **Path size**: 10-20 items (enough depth, not overwhelming)
- **Thematic coherence**: Clear conceptual thread across items
- **Diverse formats**: Mix books, catalogs, monographs
- **LC spread**: Don't cluster too narrowly in one class
- **Curator notes**: 2-3 sentences explaining the selection rationale

## Interface Selection Guide

### Choose **Production** if:
- ❌ **Not recommended** - Use Preview instead

### Choose **Preview** if:
- ✅ You're a **researcher** exploring the collection
- ✅ You need **advanced filtering** and **AI-powered facets**
- ✅ You want the **latest features** and **best performance**
- ✅ You value **accessibility** (screen readers, keyboard nav)
- ✅ You're **developing** new analysis modules or UI features

### Choose **Exhibit** if:
- ✅ You're **installing in a museum** or gallery
- ✅ You need **kiosk mode** for public touchscreens
- ✅ You want **curated paths** for guided exploration
- ✅ You're enabling **take-home collections** via Digital Receipts
- ✅ You value **minimal, exhibition-ready UI**
- ✅ You're presenting at **conferences** or **workshops**

## Where Outputs Live

### Interface Artifacts
All interfaces generate **client-side only** artifacts (no server storage):

| Artifact | Location | Persistence |
|----------|----------|-------------|
| **Search state** | Browser memory | Lost on page reload |
| **Active filters** | Browser memory | Lost on page reload |
| **Color palette preference** | `localStorage` | Persists across sessions |
| **Digital Receipts** | User downloads (JSON files) | User-managed |
| **QR codes** | Generated dynamically (PNG) | User-managed |
| **Screenshots** | User-captured via browser | User-managed |

### Data Sources (Read-Only)
- **Production**: `docs/data/sekula_inventory.json` (~5MB)
- **Preview**: `docs/data/sekula_index.json` (~8MB)
- **Exhibit**: `docs/data/sekula_index.json` + `docs/preview/exhibit/curated-paths.json` (~10KB)

### Static Assets
- **HTML**: `docs/*.html`, `docs/preview/*.html`, `docs/preview/exhibit/*.html`
- **JavaScript**: `docs/js/*.js` (shared modules)
- **CSS**: Embedded in HTML files (no separate stylesheets)
- **Images**: `docs/images/*.png` (screenshots for documentation)

## Accessibility Features (Preview & Exhibit)

### Screen Reader Support
- **ARIA roles**: `role="button"`, `role="dialog"`, `role="listitem"`
- **ARIA labels**: `aria-label="Search books"`, `aria-describedby="search-help"`
- **ARIA live regions**: `aria-live="polite"` for search result counts
- **Semantic HTML**: `<nav>`, `<main>`, `<article>`, `<aside>` for structure

### Keyboard Navigation
- **Tab order**: Logical focus sequence through interactive elements
- **Enter/Space**: Activate buttons and toggle controls
- **Escape**: Close modals, detail panels, or menus
- **Arrow keys**: Navigate between search results or shelf items (optional)

### Visual Accessibility
- **High contrast mode**: Toggle for low-vision users
- **Colorblind-friendly palettes**: Deuteranopia/protanopia-optimized colors
- **Scalable typography**: Responsive font sizing (em/rem units)
- **Focus indicators**: Visible outlines on keyboard focus

### Testing
Accessibility features tested with:
- **NVDA** (Windows screen reader)
- **VoiceOver** (macOS/iOS screen reader)
- **ChromeVox** (Chrome extension)
- **Keyboard-only navigation** (no mouse)
- **Color contrast analyzers** (WCAG AA compliance)

## Next Steps

- **Run interfaces locally**: See [docs/operations.md](operations.md)
- **Understand Digital Receipts**: See [docs/receipts.md](receipts.md)
- **Learn about the data pipeline**: See [docs/pipeline.md](pipeline.md)
- **Explore deep facets**: See [docs/PHOTO_LIKELIHOOD_FACET.md](PHOTO_LIKELIHOOD_FACET.md)
