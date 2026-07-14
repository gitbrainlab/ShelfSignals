# Reviewed association promotion

`scripts/promote_journey_associations.mjs` is the only repository workflow for turning an association-review export into a proposed public journey manifest. It is deliberately not a deployment command. It never changes the source queue or source manifest, updates the journey index, commits, pushes, or deploys.

The publisher consumes four evidence inputs:

1. the original `shelfsignals-association-review-queue@1` file;
2. the complete `shelfsignals-association-review-export@1` produced by the local review utility;
3. the current public `shelfsignals-journey@1` manifest; and
4. the current Clark `sekula_index.json` catalog snapshot.

All candidates in the queue must have a named reviewer, ISO review date, decision, and reason in the export. Only `approve` enters the proposed public manifest. `reject` and `needs_work` remain private decisions and are counted in the preview without copying their evidence or reviewer identities into the public output.

## Required two-step run

First run a read-only preview. Supply the publication editor and new editorial version explicitly:

```sh
node scripts/promote_journey_associations.mjs \
  --queue research/review-queues/aerospace-folktales.json \
  --reviews /path/to/aerospace-folktales-reviewed.json \
  --manifest docs/data/journeys/aerospace-folktales.json \
  --catalog docs/data/sekula_index.json \
  --editor "Named publication editor" \
  --editor-date 2026-07-14 \
  --version 1.1.0
```

The command validates the inputs, constructs the complete proposed manifest in memory, runs the production journey parser against it, and prints `proposed_manifest_sha256`. It performs zero writes.

Review that preview, then repeat the unchanged command with a **new** output path and the exact digest:

```sh
node scripts/promote_journey_associations.mjs \
  --queue research/review-queues/aerospace-folktales.json \
  --reviews /path/to/aerospace-folktales-reviewed.json \
  --manifest docs/data/journeys/aerospace-folktales.json \
  --catalog docs/data/sekula_index.json \
  --editor "Named publication editor" \
  --editor-date 2026-07-14 \
  --version 1.1.0 \
  --output /path/to/aerospace-folktales.promoted.json \
  --confirm-preview sha256:PREVIEW_DIGEST
```

The digest binds the proposed manifest to the exact queue, reviewed export, source manifest, relevant catalog records, editor, date, and version. Changed input produces a different digest and stops the write. The output must not exist and cannot be any input path. This makes the generated file a reviewable proposal rather than an in-place publication.

After generation, inspect the source-to-output diff, run the repository tests, update the public journey-index association count in the same editorial change, and only then replace the manifest through the ordinary source-controlled review process.

## Evidence preserved in public associations

Each promoted association retains:

- the stable candidate and Clark catalog IDs;
- the catalog snapshot, original placement transcription, and placement source;
- journey, target-work, cluster, and four-phase identifiers;
- the controlled relation type and non-causal public claim kind;
- the exact source reasoning, temporal basis, object-identity scope, and inference limit;
- the evidence grade;
- every citation, precise locator, URL, and stated evidence scope; and
- the approving reviewer, review date, and review reason.

The public `reasoning` field combines the reviewed reasoning with the explicit evidence limit so the runtime does not display an association without its boundary. Citations receive deterministic content-addressed IDs. Identical citations already in the manifest are reused; an ID/body collision is fatal.

The proposed manifest also records canonical SHA-256 values for the queue, review export, source manifest, and relevant Clark catalog evidence under `association_promotion`. These values support later provenance checks without exposing rejected candidates.

## Hard refusals

The publisher stops without an output when:

- the review export omits a candidate or changes any queue evidence;
- a reviewer, date, decision, or reason is missing, stale, or future-dated;
- the Clark catalog record, catalog snapshot, target work, cluster, journey, or manifest identity differs;
- a citation lacks HTTPS provenance, a precise locator, evidence scope, or the exact Clark catalog record;
- a relation type is outside the fixed non-causal allowlist, its phase conflicts, or its evidence grade is too weak;
- reasoning or an approval reason adds affirmative influence, inspiration, shaping, prompting, or causation language;
- an association ID or Clark record conflicts with an association already in the public manifest;
- the manifest or affected cluster still says that approved material is absent or awaiting review;
- runtime journey validation rejects or filters the proposed result; or
- the output path exists, aliases an input, lacks a preview confirmation, or receives a mismatched digest.

The publisher intentionally cannot emit `documented_influence`. Creating a causal-claim workflow would require a separate contract and tests; adding a plausible relation label must never escalate a contextual record into influence.

## Aerospace Folktales copy-identity gate

The private *Effects of Nuclear Weapons* candidate records a copy-specific institutional claim that was still pending librarian confirmation when the queue was prepared. Approval for `documented_object_in_work` therefore requires the named reviewer to include the exact attestation words **“copy identity confirmed”** as an affirmative, independent clause in the review reason—for example, “Copy identity confirmed against the cited Clark evidence.” Negated or qualified uses do not pass. Without that attestation, the publisher refuses both the direct-alignment claim and the unresolved object identity.

That attestation does not convert the OSTI edition surrogate into Clark-copy evidence. The public association continues to preserve the surrogate’s limited scope and the explicit statement that it cannot establish the Clark copy’s cover, dimensions, annotations, texture, or side profile.

## Editorial prose is evidence too

The publisher does not silently rewrite journey prose. If the current introduction says that only the work record is displayed, or an affected cluster says a candidate remains excluded pending review, promotion stops. An editor must revise those statements in the source manifest to neutral, evidence-safe language, review that change, and rerun the preview. This prevents structurally valid associations from being published beside contradictory editorial copy.

Run the focused checks with:

```sh
node --test scripts/association_promotion_tests.mjs
```
