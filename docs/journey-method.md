# ShelfSignals journey methodology

ShelfSignals journeys are editorial arguments built from collection and archival evidence. They are not recommendation lists and they are not automatically generated claims about Allan Sekula’s influences. The Clark copy, its recorded placement, and the Clark catalog record remain primary throughout.

This document defines the minimum method for moving a private association candidate into a public journey. A reviewer may reject or return a candidate at any point. Uncertainty should remain visible rather than being resolved through plausible-sounding prose.

## The four relationship phases

Every proposed book-to-work association uses one phase. The phase locates the evidence in a project timeline; it does not, by itself, establish influence.

| Phase ID | Editorial label | Use |
|---|---|---|
| `preliminary_context` | Preliminary context | Material demonstrably available before a project’s conception and relevant to its concerns. Call it “inspiration” only when a cited source explicitly supports that word or relationship. |
| `early_research` | Early research | Material connected by dated notes, bibliographies, correspondence, teaching files, annotations, or archival arrangement to the project’s research and planning period. |
| `direct_alignment` | Production and collaboration | Material directly connected to making, editing, publishing, exhibiting, screening, or collaborating on the named photograph series, book, film, exhibition, or major collaboration. |
| `post_reflection` | Post-project reflection | Material dated after the relevant publication, exhibition, screening, or sharing event and connected to later criticism, teaching, revision, circulation, or reflection. |

Chronology alone is insufficient. A publication date before a project does not prove that Sekula read or used the book. A later publication may be relevant to reception but cannot be described as preliminary influence.

## Evidence grades

Evidence grades describe what the current sources can support, not how compelling an association feels.

| Grade ID | Label | Minimum basis | Public language |
|---|---|---|---|
| `primary` | A — Primary evidence | An explicit, locatable statement or project document connects the item and target work: Sekula’s annotation, bibliography, notebook, correspondence, caption sequence, production file, recorded statement, or equivalent evidence. | May state the documented connection precisely. Use “influence” only if the source does. |
| `archival` | B — Archival evidence | A precisely located archival component connects the item to the project and period, with scope and any conflicts recorded. | May state the documented archival connection. Influence language still requires explicit support. |
| `scholarly` | C — Scholarly evidence | A cited scholarly source supports a meaningful project relation, but direct use is not established by primary or archival evidence. | Attribute the interpretation and explain the evidentiary limit. Do not upgrade it to influence. |
| `contextual` | D — Contextual evidence | Catalog subjects, chronology, or recorded placement supports a useful relation without documenting use. | Must be labeled contextual. Explain the relation and the limit of the evidence. |

`discovery_only` is a private queue state, not a public evidence grade. Keyword similarity, machine ranking, shelf adjacency alone, or an incomplete citation may create a discovery lead, but cannot enter a deployed journey manifest.

No generated text may claim influence, inspiration, causation, or intent unless an approved association’s citations and reasoning support that exact claim.

## Citations and reasoning

A publishable association needs:

- the exact ShelfSignals/Alma catalog ID;
- journey, cluster, phase, and target work identifiers;
- a concise evidence-based explanation of the relationship and its limits;
- an evidence grade;
- at least one stable citation with a precise locator, such as box/folder, page, frame, catalog record, finding-aid component, or timecode;
- reviewer name and ISO review date;
- `publication_status` explicitly changed through the separate editorial publication step.

A URL without a locator is usually not enough. Citations should identify what another researcher must inspect to reproduce the judgment. Conflicting evidence belongs in the reasoning rather than being silently omitted.

## Rights and photograph display

Bibliographic or archival availability is not a reuse license. Each displayed photograph needs item-level rights evidence and a credit line. Public image display is allowed only when the manifest records a permission, license, or public-domain determination that covers web display and any cached derivative.

- `institution_permission`: render only within the documented terms and include the required credit.
- `open_license`: record the exact license and required attribution; cache a derivative only when that license permits it.
- `public_domain`: record the source of that determination and the item locator.
- `provider_display_terms`: use only the provider-hosted reference and preserve provider attribution and scope; do not treat it as an open-artwork license.
- `pending`, `unknown`, or missing: render a calm metadata placeholder, not the image.

The Allan Sekula Studio, Getty, Clark, or another holding institution may be authoritative for attribution and project metadata without granting image reuse. A source citation never substitutes for permission.

Book-cover references follow the same restraint. Open Library or Google Books availability does not create a new license. Provider requirements and attribution travel with the reference.

## Placement and the Clark copy

Placement labels such as “Allan Studio Book Room Shelf D4” and “Front Bedroom F” are copy-specific Clark catalog evidence. Preserve the source label, including multiple recorded placements, and cite the note that supplied it. Normalized keys may support filtering and deduplication but must not replace the display transcription.

Placement can establish physical context. It cannot, by itself, establish that two books were read together or that one influenced a project. Do not translate a placement into an inferred east/west wall, topical classification, or exact adjacency unless separate Clark documentation supports that claim.

When a record has no placement identifier, say “Original Sekula placement not supplied in this record.” Do not infer one from its S-number, call number order, subject, or nearby records.

## Exact edition evidence is not Clark-copy evidence

The physical Clark copy is primary. A cover or dimensions matched through an exact ISBN may describe a provider edition, but it does not prove the Clark copy’s cover, binding, texture, wear, annotations, housing, or side profile.

Keep these scopes distinct:

- **Clark-copy evidence:** Clark catalog description, recorded Sekula placement, local measurement, or copy-specific photography.
- **Exact-edition evidence:** a conflict-free identifier match to an external edition record. Label it as provider-edition evidence.
- **Work-level evidence:** information about the intellectual work that may span editions. It cannot supply copy-specific appearance or condition.

If the edition match is ambiguous, place it in cover review. Do not select the most visually plausible cover.

## Private review handoff

`review.html` is a local-file utility. It has no fetch path, server adapter, local storage, or bundled candidate queue. Its Content Security Policy disables network connections. Candidate content exists only after a researcher selects a JSON file from their computer.

The repository includes one deliberately non-deployed, citation-only handoff packet at `research/review-queues/aerospace-folktales.json`, with its method beside it. It is outside `docs/`, has no runtime import, and remains `publication_effect: "none"`. This packet contains no artwork image, cover binary, reviewer identity, or unpublished institutional record; it exists so a librarian can audit the proposed reasoning before any association is considered for publication.

The input contract is `shelfsignals-association-review-queue@1` with a `candidates` array. Every candidate must have a unique `candidate_id`, `publication_status: "unpublished"`, `reviewer: null`, and `reviewed_at: null`. Existing decisions or review reasons must also be null or absent. These conditions prevent already-reviewed or public material from being mistaken for a fresh private queue.

The human reviewer records one of three decisions:

- `approve`: evidence is strong enough to enter the separate publication gate;
- `reject`: the proposed relation should not proceed;
- `needs_work`: a specific citation, rights check, scope correction, or reasoning change is required.

Every decision requires a reviewer name, ISO date, and reason. The exported `shelfsignals-association-review-export@1` file retains `publication_status: "unpublished"` for every candidate and declares `publication_effect: "none"`. Export is a handoff artifact, not a repository write or publication action.

### Cover-candidate review in the local browser

The same utility accepts the private `shelfsignals-cover-review-queue@1` produced by `scripts/cover_source_pipeline.py`. It validates each candidate's Clark catalog ID, canonical ISBN intersection, Open Library edition ID, Cover ID, provider URLs, source-file checksum fields, and fingerprint before showing the record. The fingerprint is recomputed locally from the catalog ID, Clark and matched ISBN sets, provider edition and Cover IDs, and provider-dump checksum. It also preserves the queue's provider snapshot, dump checksum, and documentation URLs as review evidence. A malformed or stale queue is rejected rather than partially rendered.

Cover URLs are rendered as inert text. The page's Content Security Policy keeps `img-src 'none'` and `connect-src 'none'`, so opening the queue never displays an image, runs an availability probe, or contacts Clark or Open Library. The reviewer may copy a candidate URL into a separate authorized visual-check workflow. The bounded, rate-limited probe described in [the cover source pipeline](./cover-source-pipeline.md) must also be run separately; the review page never substitutes for it.

For every cover decision the browser records:

- the queue's current `candidate_fingerprint`;
- `approve`, `reject`, or the interface label `needs_work` (exported as the pipeline value `defer`);
- reviewer identity and a second-precision UTC timestamp;
- exact-edition and visual-front-cover confirmations;
- `rights_scope: "remote_reference_only"`;
- an evidence note describing what was compared and what remains uncertain.

The browser may export a partial `shelfsignals-cover-reviews@1` ledger so a large queue can be handed off in batches. After reopening the same queue, use **Resume / merge cover reviews** to import one or more prior ledgers. Decisions reconcile only by the current `candidate_key` and fingerprint: exact duplicates are retained once, while a changed decision, note, audit identity, timestamp, or fingerprint for the same key rejects the entire import. Imported decisions retain their original reviewer and UTC timestamp; new or edited decisions receive the named session reviewer and the actual current second-precision UTC time at export. The utility will not export an incomplete draft, and it refuses more than one approved front-cover candidate for a Clark record.

An exported cover approval is still private and has `publication_effect: "none"`. The cover publisher separately requires the current fingerprint, a current positive bounded probe, both human confirmations, the evidence note, safe rights scope, and no competing approval for the same Clark record. Its reviewed-reference output carries those confirmations plus the probe's bounded flag, status, timestamp, dimensions, and candidate fingerprint as a gate receipt; `build_cover_index.py` independently revalidates that receipt against the public image and provenance evidence before producing a verified runtime reference. Open Library's [Covers API documentation](https://openlibrary.org/dev/docs/api/covers), [monthly dump documentation](https://openlibrary.org/developers/dumps), and [licensing statement](https://openlibrary.org/developers/licensing) document the source and operational constraints; none grants copy-specific evidence or a new license for the underlying cover artwork.

## Publication gate

An `approve` review never publishes a candidate. A future editor must complete all of the following:

1. Re-open the cited sources and confirm the catalog ID, target work, timeline phase, evidence grade, reasoning, and precise locators.
2. Resolve any conflicts and confirm that causal language does not exceed the evidence.
3. Verify photograph and cover rights independently from bibliographic provenance.
4. Confirm Clark-copy versus provider-edition scope and preserve every relevant placement label.
5. Run the two-step [reviewed association promotion workflow](./association-promotion.md), inspect its preview, and confirm the exact proposed-manifest digest before allowing it to write a new review copy. The publisher preserves the reviewer, review date, citations, reasoning, evidence grade, phase, cluster, target, and Clark catalog identity; it does not edit or deploy the source manifest.
6. Review the source-to-output diff, update any now-stale editorial prose and the journey-index association count, then replace the public manifest only in that source-controlled editorial commit.
7. Run schema, unknown-ID, rights, URL-state, association-promotion, and browser checks before merge.

Until all seven gates pass, the association remains private and unpublished. Machine-ranked suggestions and discovery-only records never bypass human review.

## Researcher handoff checklist

- Keep confidential, machine-ranked, or identity-bearing queues outside both the deployed `docs/` tree and Git history. A citation-only review packet may be source-controlled under `research/review-queues/` only when it contains public source references, no reviewer identity, and an explicit `publication_effect: "none"` contract.
- Use stable candidate IDs so exported decisions can be reconciled without title matching.
- Retain the original queue and reviewed export as research records under the institution’s chosen storage policy.
- Record why a candidate was rejected or returned; negative decisions prevent repeated unsupported claims.
- Add a new journey only through documented schemas and source-controlled manifests—never by embedding prose or IDs directly in UI code.
- Revisit rights and links periodically. Removal or changed terms must be reflected in the public manifest.
