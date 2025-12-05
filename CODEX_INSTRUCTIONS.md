# Codex / LLM Assistant Instructions for ShelfSignals

ShelfSignals is an adaptable toolkit for collection intelligence and metadata analysis, designed to reveal shelf-level signals in catalogs, archives, and inventory systems. It relies on an external metadata standards library for descriptive standards and metadata schemas.

## Repository Context

- Core objective: surface patterns, gaps, and anomalies in collection metadata, not to build end-user UIs.  
- Integration: defer to the project’s shared metadata schemas for field names, types, and validation rules.  
- Scope: small, composable analysis modules and utilities; experimental features can live in notebooks or clearly marked prototypes.

## How You Should Behave in This Repo

1. Respect shared metadata standards first  
   - Reuse existing metadata data structures and naming wherever possible.  
   - Do not introduce parallel schemas unless explicitly required.

2. Optimize for analysis, not scaffolding  
   - Prioritize utilities for ingest, normalization, enrichment, scoring, and reporting.  
   - Avoid generating generic boilerplate (full web apps, complex APIs, or infrastructure code) unless the user asks for it.

3. Keep changes surgical and well-scoped  
   - Prefer minimal, targeted edits over broad refactors.  
   - Preserve existing interfaces when possible; if they must change, describe the impact.

4. Design small, composable primitives  
   - Implement new behavior as focused functions or modules with clear inputs/outputs.  
   - Avoid mixing business logic with I/O, configuration, or presentation layers.

5. Document intent and integration points  
   - When adding or changing analysis logic, ensure README or local docs mention how it relates to the shared metadata standards and to the broader ShelfSignals objective.  
   - Use concise comments only where necessary to clarify non-obvious behavior.

6. Be explicit about uncertainty  
   - If metadata semantics or mappings to the shared metadata standards are ambiguous, surface options and trade-offs instead of silently choosing one.  
   - Suggest tests or small example datasets when they would clarify behavior.

Follow these instructions as your default operating mode when working in the ShelfSignals repository so your contributions stay aligned with the project’s goals and the metadata standards integration.

## Current Crawl Status (Nov 27, 2025)

- `scripts/sekula_indexer.py` now talks directly to Primo’s `pnxs` API, captures full MARC-derived metadata, and checkpoints every 5 pages.
- Long-running crawl is in progress; 5,050 Sekula records have been persisted to `sekula_index.json/.csv` (root). Resume logic will continue from roughly offset 5,050.
- The Clark API rate-limits aggressively after ~5k rows. The script backs off up to 15 minutes on HTTP 403 responses, so expect pauses; do not delete the checkpoint files unless you want to restart.
- Empty pages occasionally appear; the crawler already retries them with increasing delays. If it stops early, rerun the script to continue from the last checkpoint.
- When editing the crawler, keep politeness (delays, jitter, backoff) and resume safety (checkpointing, dedupe) intact so we can eventually reach all ~11k records without restarting from zero.
