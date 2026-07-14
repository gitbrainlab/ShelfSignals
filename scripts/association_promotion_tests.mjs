import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { mkdtemp, readFile, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import test from "node:test";

import { parseJourneyManifest } from "../docs/js/journeys.js";
import {
  ASSOCIATION_PROMOTION_SCHEMA,
  AssociationPromotionError,
  buildAssociationPromotion,
  canonicalSha256,
  validateAssociationPromotion
} from "./promote_journey_associations.mjs";

const ROOT = new URL("../", import.meta.url);
const SCRIPT = new URL("scripts/promote_journey_associations.mjs", ROOT);
const [queue, fullCatalog, publicManifest] = await Promise.all([
  readFile(new URL("research/review-queues/aerospace-folktales.json", ROOT), "utf8").then(JSON.parse),
  readFile(new URL("docs/data/sekula_index.json", ROOT), "utf8").then(JSON.parse),
  readFile(new URL("docs/data/journeys/aerospace-folktales.json", ROOT), "utf8").then(JSON.parse)
]);

const relevantIds = new Set([queue.target_work.catalog_id, ...queue.candidates.map(candidate => candidate.catalog_id)]);
const catalog = fullCatalog.filter(record => relevantIds.has(record.id));
const fixedNow = new Date("2026-07-14T12:00:00Z");

function clone(value) {
  return structuredClone(value);
}

function preparedManifest() {
  const manifest = clone(publicManifest);
  manifest.introduction = "A rights-aware research preview following five source-described movements. Public shelf relations appear only after named review and retain their evidence limits; phase labels do not imply influence.";
  manifest.clusters = manifest.clusters.map(cluster => cluster.id === "ordered-world" ? {
    ...cluster,
    narrative: "The analysis describes carefully ordered rooms, aircraft models, and three page spreads from a nuclear-effects manual. Any approved shelf relation below remains bounded by its citations, copy-identity scope, and evidence limit."
  } : cluster);
  return manifest;
}

function reviewExport(approvedIds = [], reasonOverrides = {}) {
  const approved = new Set(approvedIds);
  return {
    schema: "shelfsignals-association-review-export@1",
    exported_at: "2026-07-14T10:30:00.000Z",
    source_schema: queue.schema,
    source_filename: "aerospace-folktales.json",
    publication_effect: "none",
    notice: "Human decisions only; this export has no publication effect.",
    candidates: queue.candidates.map(candidate => {
      const decision = approved.has(candidate.candidate_id) ? "approve" : "reject";
      return {
        ...clone(candidate),
        publication_status: "unpublished",
        review_decision: decision,
        reviewer: "Clark research librarian",
        reviewed_at: "2026-07-14",
        review_reason: reasonOverrides[candidate.candidate_id] || (decision === "approve"
          ? "Approved as a bounded, non-causal relation after rechecking every cited locator and the stated evidence limit."
          : "Not approved for this publication pass; the negative decision is retained to prevent unsupported reuse.")
      };
    })
  };
}

function build(overrides = {}) {
  return buildAssociationPromotion({
    queue: overrides.queue || queue,
    reviewExport: overrides.reviewExport || reviewExport(),
    manifest: overrides.manifest || preparedManifest(),
    catalog: overrides.catalog || catalog,
    editor: overrides.editor || "Journey publication editor",
    editorReviewedAt: overrides.editorReviewedAt || "2026-07-14",
    editorialVersion: overrides.editorialVersion || "1.1.0",
    now: overrides.now || fixedNow
  });
}

test("promotion preserves approved evidence, review identity, catalog identity, phase, and cluster", () => {
  const candidate = queue.candidates.find(item => item.candidate_id.includes("one-dimensional-man"));
  const reviews = reviewExport([candidate.candidate_id]);
  const result = build({ reviewExport: reviews });
  assert.equal(result.preview.schema, ASSOCIATION_PROMOTION_SCHEMA);
  assert.equal(result.preview.writes_performed, 0);
  assert.equal(result.preview.approved_association_count, 1);
  assert.match(result.preview.proposed_manifest_sha256, /^sha256:[a-f0-9]{64}$/);

  const association = result.proposedManifest.associations[0];
  assert.equal(association.id, candidate.candidate_id);
  assert.equal(association.catalog_id, candidate.catalog_id);
  assert.equal(association.cluster_id, candidate.cluster_id);
  assert.equal(association.phase, candidate.phase);
  assert.equal(association.claim_kind, "contextual_proximity");
  assert.equal(association.evidence_grade, candidate.evidence_grade);
  assert.equal(association.source_reasoning, candidate.proposed_reasoning);
  assert.equal(association.inference_limit, candidate.inference_limit);
  assert.match(association.reasoning, new RegExp(candidate.inference_limit.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  assert.deepEqual(association.catalog_snapshot, candidate.catalog_snapshot);
  assert.equal(association.review.reviewer, "Clark research librarian");
  assert.equal(association.review.reviewed_at, "2026-07-14");
  assert.equal(association.review.reason, reviews.candidates.find(item => item.candidate_id === candidate.candidate_id).review_reason);
  assert.deepEqual(
    result.proposedManifest.clusters.find(cluster => cluster.id === candidate.cluster_id).association_ids,
    [candidate.candidate_id]
  );

  const promotedCitations = association.citation_ids.map(id => result.proposedManifest.citations.find(citation => citation.id === id));
  assert.equal(promotedCitations.length, candidate.citations.length);
  promotedCitations.forEach((citation, index) => {
    const withoutId = clone(citation);
    delete withoutId.id;
    assert.deepEqual(withoutId, candidate.citations[index]);
  });
  assert.equal(result.proposedManifest.association_promotion.queue_canonical_sha256, canonicalSha256(queue));
});

test("direct object-in-work relation requires and preserves copy-identity attestation", () => {
  const candidate = queue.candidates.find(item => item.relation_type === "documented_object_in_work");
  const attestation = "Approved as object-in-work evidence after every locator was reopened; copy identity confirmed against the cited Clark institutional evidence. This is not an inspiration claim.";
  const result = build({
    reviewExport: reviewExport([candidate.candidate_id], { [candidate.candidate_id]: attestation })
  });
  const association = result.proposedManifest.associations[0];
  assert.equal(association.claim_kind, "documented_alignment");
  assert.equal(association.evidence_grade, "archival");
  assert.equal(association.review.reason, attestation);
  assert.match(association.inference_limit, /not documented inspiration/i);
  assert.equal(association.citation_ids.length, 4);
});

test("runtime journey validator accepts the complete proposed manifest without filtering associations", () => {
  const candidate = queue.candidates.find(item => item.candidate_id.includes("american-photography"));
  const result = build({ reviewExport: reviewExport([candidate.candidate_id]) });
  const parsed = parseJourneyManifest(result.proposedManifest, { catalogIds: catalog.map(record => record.id) });
  assert.equal(parsed.rejected, false, JSON.stringify(parsed.errors));
  assert.equal(parsed.associations.length, 1);
  assert.equal(parsed.associations[0].id, candidate.candidate_id);
  assert.equal(parsed.associations[0].claim_kind, "documented_post_reflection");
});

test("all six real queue candidates can flow only through their controlled claim mappings", () => {
  const direct = queue.candidates.find(item => item.relation_type === "documented_object_in_work");
  const approvedIds = queue.candidates.map(candidate => candidate.candidate_id);
  const result = build({
    reviewExport: reviewExport(approvedIds, {
      [direct.candidate_id]: "Every direct-relation locator was reopened; copy identity confirmed against the cited Clark catalog and institutional article. This remains not an inspiration claim."
    })
  });
  assert.equal(result.proposedManifest.associations.length, 6);
  assert.deepEqual(
    [...new Set(result.proposedManifest.associations.map(association => association.claim_kind))].sort(),
    ["contextual_proximity", "documented_alignment", "documented_post_reflection"]
  );
  assert.equal(result.proposedManifest.associations.some(association => association.claim_kind === "documented_influence"), false);
  const directPublic = result.proposedManifest.associations.find(association => association.id === direct.candidate_id);
  assert.equal(directPublic.object_identity_review.status, "confirmed");
  assert.match(directPublic.reasoning, /Review resolution: copy identity confirmed by Clark research librarian on 2026-07-14\./);
});

test("changed evidence and incomplete review exports fail closed", () => {
  const tampered = reviewExport();
  tampered.candidates[0].proposed_reasoning = "A reviewer replaced the research evidence.";
  assert.throws(() => build({ reviewExport: tampered }), error => {
    assert.ok(error instanceof AssociationPromotionError);
    assert.ok(error.issues.some(item => item.code === "review_evidence_changed"));
    return true;
  });

  const incomplete = reviewExport();
  incomplete.candidates.pop();
  const validation = validateAssociationPromotion({
    queue,
    reviewExport: incomplete,
    manifest: preparedManifest(),
    catalog,
    editor: "Journey publication editor",
    editorReviewedAt: "2026-07-14",
    editorialVersion: "1.1.0",
    now: fixedNow
  });
  assert.equal(validation.ok, false);
  assert.ok(validation.errors.some(item => item.code === "incomplete_review_export"));
  assert.ok(validation.errors.some(item => item.code === "missing_reviewed_candidate"));
});

test("unsupported relation types and affirmative causal overclaims fail closed", () => {
  const unsafeQueue = clone(queue);
  unsafeQueue.candidates[0].relation_type = "machine_inferred_influence";
  unsafeQueue.candidates[0].proposed_reasoning += " This book inspired the project.";
  const unsafeReviews = reviewExport();
  unsafeReviews.candidates = unsafeQueue.candidates.map((candidate, index) => ({
    ...candidate,
    reviewer: "Reviewer",
    reviewed_at: "2026-07-14",
    review_decision: index === 0 ? "approve" : "reject",
    review_reason: index === 0 ? "Approved." : "Rejected."
  }));
  assert.throws(() => build({ queue: unsafeQueue, reviewExport: unsafeReviews }), error => {
    assert.ok(error.issues.some(item => item.code === "unsupported_relation"));
    assert.ok(error.issues.some(item => item.code === "unsupported_causal_claim"));
    return true;
  });
});

test("direct relation without the exact copy-identity attestation is refused", () => {
  const candidate = queue.candidates.find(item => item.relation_type === "documented_object_in_work");
  assert.throws(() => build({ reviewExport: reviewExport([candidate.candidate_id]) }), error => {
    assert.ok(error.issues.some(item => item.code === "missing_copy_identity_attestation"));
    assert.ok(error.issues.some(item => item.code === "unresolved_object_identity"));
    return true;
  });

  const negated = reviewExport([candidate.candidate_id], {
    [candidate.candidate_id]: "Copy identity confirmed against the source was not established by this review, so this direct relation needs more work."
  });
  assert.throws(() => build({ reviewExport: negated }), error => {
    assert.ok(error.issues.some(item => item.code === "missing_copy_identity_attestation"));
    return true;
  });
});

test("stale absence claims must be editorially corrected before an approved relation is promoted", () => {
  const candidate = queue.candidates[0];
  assert.throws(() => build({
    reviewExport: reviewExport([candidate.candidate_id]),
    manifest: publicManifest
  }), error => {
    assert.ok(error.issues.some(item => item.code === "stale_manifest_narrative"));
    return true;
  });
});

test("existing association IDs or competing catalog associations cannot be silently updated", () => {
  const candidate = queue.candidates[0];
  const first = build({ reviewExport: reviewExport([candidate.candidate_id]) });
  assert.throws(() => build({
    reviewExport: reviewExport([candidate.candidate_id]),
    manifest: first.proposedManifest,
    editorialVersion: "1.2.0"
  }), error => {
    assert.ok(error.issues.some(item => item.code === "association_id_conflict" || item.code === "catalog_association_conflict"));
    return true;
  });
});

test("editor date must follow human review and all review dates are bounded", () => {
  const candidate = queue.candidates[0];
  const reviews = reviewExport([candidate.candidate_id]);
  reviews.candidates[0].reviewed_at = "2026-07-15";
  assert.throws(() => build({ reviewExport: reviews }), error => {
    assert.ok(error.issues.some(item => item.code === "future_review"));
    return true;
  });

  const laterReviews = reviewExport([candidate.candidate_id]);
  laterReviews.candidates[0].reviewed_at = "2026-07-14";
  assert.throws(() => build({ reviewExport: laterReviews, editorReviewedAt: "2026-07-13" }), error => {
    assert.ok(error.issues.some(item => item.code === "editor_predates_review"));
    return true;
  });
});

test("CLI enforces preview digest, explicit new output, non-overwrite, and no source mutation", async () => {
  const directory = await mkdtemp(join(tmpdir(), "shelfsignals-association-promotion-"));
  const candidate = queue.candidates[0];
  const paths = {
    queue: join(directory, "queue.json"),
    reviews: join(directory, "reviews.json"),
    manifest: join(directory, "manifest.json"),
    catalog: join(directory, "catalog.json"),
    output: join(directory, "promoted.json")
  };
  const manifest = preparedManifest();
  await Promise.all([
    writeFile(paths.queue, JSON.stringify(queue)),
    writeFile(paths.reviews, JSON.stringify(reviewExport([candidate.candidate_id]))),
    writeFile(paths.manifest, JSON.stringify(manifest)),
    writeFile(paths.catalog, JSON.stringify(catalog))
  ]);
  const sourceBefore = await readFile(paths.manifest, "utf8");
  const baseArgs = [
    SCRIPT.pathname,
    "--queue", paths.queue,
    "--reviews", paths.reviews,
    "--manifest", paths.manifest,
    "--catalog", paths.catalog,
    "--editor", "Journey publication editor",
    "--editor-date", "2026-07-14",
    "--version", "1.1.0"
  ];
  const previewRun = spawnSync(process.execPath, baseArgs, { encoding: "utf8" });
  assert.equal(previewRun.status, 0, previewRun.stderr);
  const preview = JSON.parse(previewRun.stdout);
  assert.equal(preview.mode, "preview");
  assert.equal(preview.writes_performed, 0);
  assert.equal(await readFile(paths.manifest, "utf8"), sourceBefore);

  const missingConfirmation = spawnSync(process.execPath, [...baseArgs, "--output", paths.output], { encoding: "utf8" });
  assert.equal(missingConfirmation.status, 2);
  await assert.rejects(readFile(paths.output, "utf8"), /ENOENT/);

  const wrongConfirmation = spawnSync(process.execPath, [...baseArgs, "--output", paths.output, "--confirm-preview", `sha256:${"f".repeat(64)}`], { encoding: "utf8" });
  assert.equal(wrongConfirmation.status, 2);
  await assert.rejects(readFile(paths.output, "utf8"), /ENOENT/);

  const writeRun = spawnSync(process.execPath, [...baseArgs, "--output", paths.output, "--confirm-preview", preview.proposed_manifest_sha256], { encoding: "utf8" });
  assert.equal(writeRun.status, 0, writeRun.stderr);
  const receipt = JSON.parse(writeRun.stdout);
  assert.equal(receipt.mode, "write");
  assert.equal(receipt.writes_performed, 1);
  const output = JSON.parse(await readFile(paths.output, "utf8"));
  assert.equal(canonicalSha256(output), preview.proposed_manifest_sha256);
  assert.equal(await readFile(paths.manifest, "utf8"), sourceBefore);

  const overwrite = spawnSync(process.execPath, [...baseArgs, "--output", paths.output, "--confirm-preview", preview.proposed_manifest_sha256], { encoding: "utf8" });
  assert.equal(overwrite.status, 2);
  assert.match(overwrite.stderr, /refusing to overwrite/i);
});
