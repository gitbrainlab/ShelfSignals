# Aerospace Folktales unpublished association review

This directory holds a repository-local editorial research artifact. It is outside the deployed `docs/` tree, absent from the journey index, and has no runtime import or fetch path. The JSON queue remains `publication_status: "unpublished"` and `publication_effect: "none"`; review approval would still require a separate editorial publication commit.

The queue was built by joining exact named titles in authoritative sources to real records in `docs/data/sekula_index.json`. Six candidates were retained because each has a reproducible title-level, copy-level, or publication-level locator. Attractive thematic matches without a source-stated relation were excluded.

## Relationship rule

The review must keep five assertions separate:

1. Sekula named, read, discussed, or owned a title.
2. The surviving Clark record represents the same title or edition.
3. The surviving Clark physical copy is the object named or photographed.
4. A source connects the title or copy to *Aerospace Folktales*.
5. A source explicitly supports causal words such as “influence” or “inspiration.”

Assertions 1–4 do not imply assertion 5. Publication chronology, subjects, shelf placement, and ownership never establish influence on their own. Each candidate therefore records `relation_type`, `temporal_basis`, `object_identity_scope`, `proposed_reasoning`, and `inference_limit` separately.

## Phase and evidence decisions

- `preliminary_context`: *One-dimensional Man* and *Galileo* are documented pre-project readings. They remain `contextual`, because the oral history does not connect either title to the target work or identify the surviving Clark copy.
- `early_research`: *Suburbia* is a documented contemporaneous discussion in Sekula's photography circle. It remains `contextual`, because overlapping chronology and suburban subject matter do not prove project research or inspiration.
- `direct_alignment`: *The Effects of Nuclear Weapons* is an `archival` candidate for a documented object in the work. Clark's institutional article makes a copy-specific claim and Edwards independently describes the page spreads. A Clark librarian must still confirm that the surviving Clark copy is the photographed object. The relation must not be relabeled inspiration.
- `post_reflection`: *Between Labor and Capital* is a `scholarly` post-project conceptual-dialogue candidate; *American Photography* is an `archival` page-level record of later excerpting and circulation. Neither can be described as preliminary influence.

The queue contains no Grade A `primary` candidate because no located project document explicitly connects one of the retained collection books to the target work in a way that meets that grade's item-and-work threshold.

## Source and copy provenance

For every candidate, the catalog snapshot, call number, URL, and placement label are copied from the current ShelfSignals dataset. The complete provenance note is retained as `placement_source`. When future records lack a placement label, validation requires the exact phrase `Original Sekula placement not supplied in this record.` rather than an inferred location.

The Smithsonian transcript is primary evidence for Sekula's named readings and discussions, but those mentions are title-level. The Getty finding aid is archival evidence for production and publication history. Susan Roeper's Clark article is institutional, copy-specific evidence. Steve Edwards's Nonsite article is scholarly interpretation and is attributed as such.

OSTI is cited only for an open, scrape-friendly digital surrogate of the exact-year 1957 government report *The Effects of Nuclear Weapons*. It is not evidence for the Clark copy's binding, cover, dimensions, annotations, condition, texture, or side profile. No surrogate image is cached in this queue.

## Rights boundary

No Allan Sekula artwork photograph is included. Online access at Generali, Getty, Clark, or another institution is not an open license. The work photographs must remain metadata-only unless item-level permission or an applicable open license is documented separately.

## Human publication gate

Before any candidate can enter `docs/data/journeys/aerospace-folktales.json`, a named reviewer must reopen every citation and confirm the catalog ID, locator, phase, evidence grade, exact-copy scope, reasoning, and inference limit. The reviewer must also resolve photograph and cover rights independently. An editor must then use the two-step workflow in `docs/association-promotion.md`; its preview digest and explicit new output path produce a review copy but do not change, index, commit, or deploy the public manifest. Only a later source-controlled editorial change may add the approved result to the public journey.

Run the repository-local checks with:

```sh
node --test scripts/aerospace_review_queue_tests.mjs
node --test scripts/association_promotion_tests.mjs
```
