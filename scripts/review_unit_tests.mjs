import assert from "node:assert/strict";
import test from "node:test";

import {
  COVER_REVIEWS_SCHEMA,
  REVIEW_EXPORT_SCHEMA,
  coverCandidateFingerprint,
  createCoverReviewsExport,
  createReviewedExport,
  currentUtcTimestamp,
  mergeCoverReviewDecisions,
  validateCoverReviewQueue,
  validateCoverReviewsLedger,
  validateImportedQueue,
  validateReviewQueue
} from "../docs/js/review.js";

function associationQueue() {
  const queue = {
    schema: "shelfsignals-association-review-queue@1",
    candidates: [{
      candidate_id: "association-fixture-1",
      catalog_id: "alma-fixture-1",
      publication_status: "unpublished",
      reviewer: null,
      reviewed_at: null,
      review_decision: null,
      review_reason: null
    }]
  };
  return queue;
}

function coverCandidate(recordId, editionId, coverId) {
  return {
    candidate_key: `${recordId}:${editionId}:${coverId}`,
    candidate_fingerprint: "",
    provider: "openlibrary",
    scope: "external_exact_edition",
    provider_edition_id: editionId,
    cover_id: coverId,
    matched_identifiers: [{ type: "isbn", value: "9780374226268" }],
    source_url: `https://openlibrary.org/books/${editionId}`,
    image_url: `https://covers.openlibrary.org/b/id/${coverId}-L.jpg?default=false`,
    thumbnail_url: `https://covers.openlibrary.org/b/id/${coverId}-M.jpg?default=false`,
    edition_summary: { publish_date: "1995" },
    review_required: true,
    public_eligible: false
  };
}

function coverQueue() {
  const recordId = "alma-fixture-cover";
  const candidates = [
    coverCandidate(recordId, "OL100M", 100),
    coverCandidate(recordId, "OL101M", 101)
  ];
  const queue = {
    schema: "shelfsignals-cover-review-queue@1",
    version: "1.0.0",
    inputs: {
      provider_snapshot: "2026-06-30",
      provider_dump_checksum: `md5:${"d".repeat(32)}`,
      catalog_sha256: `sha256:${"a".repeat(64)}`,
      editions_sha256: `sha256:${"b".repeat(64)}`
    },
    provider: {
      name: "Open Library",
      discovery_method: "monthly_editions_dump_exact_isbn_join",
      cover_documentation: "https://openlibrary.org/dev/docs/api/covers",
      dump_documentation: "https://openlibrary.org/developers/dumps",
      licensing: "https://openlibrary.org/developers/licensing"
    },
    summary: { catalog_records: 1, candidate_references: 2 },
    items: {
      [recordId]: {
        status: "review_required",
        unresolved_label: "Cover not yet verified for this edition",
        catalog: {
          title: "Test-only catalog fixture",
          authors: [],
          year: "1995",
          call_number: "",
          normalized_isbns: ["9780374226268"],
          catalog_url: "https://library.clarkart.edu/fixture"
        },
        candidates
      }
    }
  };
  const catalog = queue.items[recordId].catalog;
  for (const candidate of candidates) {
    candidate.candidate_fingerprint = coverCandidateFingerprint(
      recordId,
      catalog,
      candidate,
      queue.inputs.provider_dump_checksum
    );
  }
  return queue;
}

test("association review contract remains unpublished and unchanged", () => {
  const queue = associationQueue();
  assert.equal(validateReviewQueue(queue).ok, true);
  assert.equal(validateImportedQueue(queue).mode, "association");
  const output = createReviewedExport(queue, {
    "association-fixture-1": {
      decision: "needs_work",
      reason: "A precise archival locator is still required."
    }
  }, "Association reviewer", "2026-07-13", "associations.json");
  assert.equal(output.schema, REVIEW_EXPORT_SCHEMA);
  assert.equal(output.publication_effect, "none");
  assert.equal(output.candidates[0].publication_status, "unpublished");
  assert.equal(output.candidates[0].review_decision, "needs_work");
});

test("cover queue validation binds URLs to exact IDs and rejects tampering", () => {
  const queue = coverQueue();
  const validation = validateCoverReviewQueue(queue);
  assert.equal(validation.ok, true, validation.errors.join(" "));
  assert.equal(validation.reviewItems.length, 2);
  assert.equal(validateImportedQueue(queue).mode, "cover");

  const tampered = structuredClone(queue);
  tampered.items["alma-fixture-cover"].candidates[0].thumbnail_url = "https://example.test/not-a-cover.jpg";
  assert.equal(validateCoverReviewQueue(tampered).ok, false);

  const staleFingerprint = structuredClone(queue);
  staleFingerprint.items["alma-fixture-cover"].candidates[0].candidate_fingerprint = `sha256:${"f".repeat(64)}`;
  assert.equal(validateCoverReviewQueue(staleFingerprint).ok, false);

  const changedEvidence = structuredClone(queue);
  changedEvidence.inputs.provider_dump_checksum = `md5:${"e".repeat(32)}`;
  const changedValidation = validateCoverReviewQueue(changedEvidence);
  assert.equal(changedValidation.ok, false);
  assert.match(changedValidation.errors.join(" "), /fingerprint does not match its exact queue evidence/i);
});

test("cover export is pipeline-compatible and maps needs_work to defer", () => {
  const queue = coverQueue();
  const candidate = queue.items["alma-fixture-cover"].candidates[0];
  const output = createCoverReviewsExport(queue, {
    [candidate.candidate_key]: {
      decision: "needs_work",
      reason: "The provider edition statement remains unresolved.",
      exactEditionConfirmed: false,
      visualCheck: false
    }
  }, "Cover reviewer", "2026-07-13T20:15:30Z", "candidates.json");
  const decision = output.decisions[candidate.candidate_key];
  assert.equal(output.schema, COVER_REVIEWS_SCHEMA);
  assert.equal(output.publication_effect, "none");
  assert.equal(decision.candidate_fingerprint, candidate.candidate_fingerprint);
  assert.equal(decision.decision, "defer");
  assert.equal(decision.reviewed_at, "2026-07-13T20:15:30Z");
  assert.equal(decision.rights_scope, "remote_reference_only");
});

test("cover approvals require confirmations and remain one per Clark record", () => {
  const queue = coverQueue();
  const [first, second] = queue.items["alma-fixture-cover"].candidates;
  const approved = {
    decision: "approve",
    reason: "Exact ISBN, edition statement, and front-cover text were compared.",
    exactEditionConfirmed: true,
    visualCheck: true
  };
  assert.throws(() => createCoverReviewsExport(queue, {
    [first.candidate_key]: { ...approved, visualCheck: false }
  }, "Cover reviewer", "2026-07-13T20:15:30Z"), /both confirmations/i);
  assert.throws(() => createCoverReviewsExport(queue, {
    [first.candidate_key]: approved,
    [second.candidate_key]: approved
  }, "Cover reviewer", "2026-07-13T20:15:30Z"), /at most one/i);
});

test("cover ledgers resume deterministically, preserve audit identity, and reject conflicts", () => {
  const queue = coverQueue();
  const [first, second] = queue.items["alma-fixture-cover"].candidates;
  const firstLedger = createCoverReviewsExport(queue, {
    [first.candidate_key]: {
      decision: "approve",
      reason: "Exact edition and front-cover text were compared by the first reviewer.",
      exactEditionConfirmed: true,
      visualCheck: true
    }
  }, "First reviewer", "2026-07-13T20:15:30Z");
  const secondLedger = createCoverReviewsExport(queue, {
    [second.candidate_key]: {
      decision: "reject",
      reason: "The second candidate shows a conflicting edition statement.",
      exactEditionConfirmed: false,
      visualCheck: true
    }
  }, "Second reviewer", "2026-07-13T21:00:00Z");
  const firstImport = validateCoverReviewsLedger(queue, firstLedger);
  const secondImport = validateCoverReviewsLedger(queue, secondLedger);
  assert.equal(firstImport.ok, true, firstImport.errors.join(" "));
  assert.equal(secondImport.ok, true, secondImport.errors.join(" "));
  const merged = mergeCoverReviewDecisions(firstImport.decisions, secondImport.decisions);
  assert.equal(merged.ok, true, merged.errors.join(" "));
  assert.equal(merged.decisions.size, 2);

  const resumed = createCoverReviewsExport(queue, merged.decisions);
  assert.equal(resumed.decisions[first.candidate_key].reviewer, "First reviewer");
  assert.equal(resumed.decisions[first.candidate_key].reviewed_at, "2026-07-13T20:15:30Z");
  assert.equal(resumed.decisions[second.candidate_key].reviewer, "Second reviewer");

  const conflicting = structuredClone(firstLedger);
  conflicting.decisions[first.candidate_key].evidence_note = "A different complete note creates an explicit merge conflict.";
  const conflictImport = validateCoverReviewsLedger(queue, conflicting);
  assert.equal(conflictImport.ok, true);
  assert.equal(mergeCoverReviewDecisions(firstImport.decisions, conflictImport.decisions).ok, false);
});

test("cover reviews use a real second-precision UTC timestamp contract", () => {
  assert.match(currentUtcTimestamp(), /^20\d{2}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/);
  const queue = coverQueue();
  const candidate = queue.items["alma-fixture-cover"].candidates[0];
  assert.throws(() => createCoverReviewsExport(queue, {
    [candidate.candidate_key]: {
      decision: "reject",
      reason: "This is a complete rejection note for timestamp validation.",
      exactEditionConfirmed: false,
      visualCheck: true
    }
  }, "Reviewer", "1999-12-31T00:00:00Z"), /20xx UTC timestamp/i);
});
