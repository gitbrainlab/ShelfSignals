import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { validateImportedQueue } from "../docs/js/review.js";

const ROOT = new URL("../", import.meta.url);
const QUEUE_URL = new URL("research/review-queues/aerospace-folktales.json", ROOT);
const METHOD_URL = new URL("research/review-queues/aerospace-folktales-methodology.md", ROOT);
const CATALOG_URL = new URL("docs/data/sekula_index.json", ROOT);
const JOURNEY_URL = new URL("docs/data/journeys/aerospace-folktales.json", ROOT);
const JOURNEY_INDEX_URL = new URL("docs/data/journeys/index.json", ROOT);

const [queue, catalog, journey, journeyIndex, methodology, queueText, journeyText, indexText] = await Promise.all([
  readFile(QUEUE_URL, "utf8").then(JSON.parse),
  readFile(CATALOG_URL, "utf8").then(JSON.parse),
  readFile(JOURNEY_URL, "utf8").then(JSON.parse),
  readFile(JOURNEY_INDEX_URL, "utf8").then(JSON.parse),
  readFile(METHOD_URL, "utf8"),
  readFile(QUEUE_URL, "utf8"),
  readFile(JOURNEY_URL, "utf8"),
  readFile(JOURNEY_INDEX_URL, "utf8")
]);

const catalogById = new Map(catalog.map((record) => [record.id, record]));
const clusters = new Set(journey.clusters.map((cluster) => cluster.id));
const phases = new Set(["preliminary_context", "early_research", "direct_alignment", "post_reflection"]);
const grades = new Set(["primary", "archival", "scholarly", "contextual"]);
const missingPlacement = "Original Sekula placement not supplied in this record.";

function countBy(items, key) {
  return Object.fromEntries([...items.reduce((counts, item) => {
    counts.set(item[key], (counts.get(item[key]) || 0) + 1);
    return counts;
  }, new Map()).entries()].sort(([left], [right]) => left.localeCompare(right)));
}

test("queue is an unpublished, non-deployed editorial artifact", () => {
  assert.equal(queue.schema, "shelfsignals-association-review-queue@1");
  assert.equal(queue.publication_status, "unpublished");
  assert.equal(queue.publication_effect, "none");
  assert.equal(queue.journey_id, "aerospace-folktales");
  assert.equal(queue.target_work.catalog_id, "alma991002293459708431");
  assert.ok(queue.candidates.length >= 6 && queue.candidates.length <= 12);
  assert.equal(queue.summary.candidate_count, queue.candidates.length);
  assert.deepEqual(queue.summary.phase_counts, {
    preliminary_context: 2,
    early_research: 1,
    direct_alignment: 1,
    post_reflection: 2
  });
  assert.deepEqual(countBy(queue.candidates, "phase"), {
    direct_alignment: 1,
    early_research: 1,
    post_reflection: 2,
    preliminary_context: 2
  });
  assert.deepEqual(countBy(queue.candidates, "evidence_grade"), {
    archival: 2,
    contextual: 3,
    scholarly: 1
  });
  assert.equal(JOURNEY_URL.pathname.includes("/docs/"), true);
  assert.equal(QUEUE_URL.pathname.includes("/docs/"), false);
  assert.equal(methodology.includes("outside the deployed `docs/` tree"), true);
  assert.equal(validateImportedQueue(queue).mode, "association");
});

test("every candidate is review-safe, cited, and bound to a real catalog record", () => {
  const candidateIds = new Set();
  for (const candidate of queue.candidates) {
    assert.equal(candidateIds.has(candidate.candidate_id), false, `duplicate ${candidate.candidate_id}`);
    candidateIds.add(candidate.candidate_id);
    assert.equal(candidate.publication_status, "unpublished", candidate.candidate_id);
    assert.equal(candidate.reviewer, null, candidate.candidate_id);
    assert.equal(candidate.reviewed_at, null, candidate.candidate_id);
    assert.equal(candidate.review_decision, null, candidate.candidate_id);
    assert.equal(candidate.review_reason, null, candidate.candidate_id);
    assert.equal(candidate.journey_id, queue.journey_id, candidate.candidate_id);
    assert.equal(candidate.target_work, queue.target_work.catalog_id, candidate.candidate_id);
    assert.equal(clusters.has(candidate.cluster_id), true, candidate.candidate_id);
    assert.equal(phases.has(candidate.phase), true, candidate.candidate_id);
    assert.equal(grades.has(candidate.evidence_grade), true, candidate.candidate_id);
    assert.ok(candidate.relation_type.length > 8, candidate.candidate_id);
    assert.ok(candidate.temporal_basis.length > 40, candidate.candidate_id);
    assert.ok(candidate.object_identity_scope.length > 20, candidate.candidate_id);
    assert.ok(candidate.proposed_reasoning.length > 120, candidate.candidate_id);
    assert.ok(candidate.inference_limit.length > 60, candidate.candidate_id);
    assert.ok(candidate.candidate_source.length > 40, candidate.candidate_id);

    const source = catalogById.get(candidate.catalog_id);
    assert.ok(source, `unknown catalog id ${candidate.catalog_id}`);
    assert.equal(candidate.catalog_snapshot.title, source.title, candidate.candidate_id);
    assert.deepEqual(candidate.catalog_snapshot.authors, source.authors, candidate.candidate_id);
    assert.equal(candidate.catalog_snapshot.year, source.year, candidate.candidate_id);
    assert.equal(candidate.catalog_snapshot.material_type, source.material_type, candidate.candidate_id);
    assert.deepEqual(candidate.catalog_snapshot.formats, source.formats, candidate.candidate_id);
    assert.deepEqual(candidate.catalog_snapshot.publishers, source.publishers, candidate.candidate_id);
    assert.equal(candidate.catalog_snapshot.call_number, source.call_number, candidate.candidate_id);
    assert.equal(candidate.catalog_snapshot.catalog_url, source.record_url, candidate.candidate_id);

    if (source.provenance_notes.some((note) => note.includes(candidate.placement))) {
      assert.equal(source.provenance_notes.includes(candidate.placement_source), true, candidate.candidate_id);
    } else {
      assert.equal(candidate.placement, missingPlacement, candidate.candidate_id);
    }

    assert.ok(Array.isArray(candidate.citations) && candidate.citations.length >= 2, candidate.candidate_id);
    for (const citation of candidate.citations) {
      assert.match(citation.url, /^https:\/\//, `${candidate.candidate_id}: ${citation.url}`);
      assert.ok(citation.locator.length >= 24, candidate.candidate_id);
      assert.ok(citation.scope.length >= 16, candidate.candidate_id);
    }
    assert.equal(candidate.citations.some((citation) => citation.url === source.record_url), true, candidate.candidate_id);
  }
});

test("contextual and post-project candidates retain explicit anti-causal limits", () => {
  for (const candidate of queue.candidates) {
    if (candidate.evidence_grade === "contextual") {
      assert.match(candidate.inference_limit, /contextual only/i, candidate.candidate_id);
      assert.match(candidate.proposed_reasoning, /does not|do not|no source/i, candidate.candidate_id);
    }
    if (candidate.phase === "post_reflection") {
      assert.match(candidate.inference_limit, /not|cannot/i, candidate.candidate_id);
      assert.notEqual(candidate.relation_type, "influence", candidate.candidate_id);
    }
  }
  const nuclear = queue.candidates.find((candidate) => candidate.catalog_id === "alma991002077699708431");
  assert.equal(nuclear.relation_type, "documented_object_in_work");
  assert.match(nuclear.inference_limit, /not documented inspiration/i);
  assert.equal(nuclear.citations.some((citation) => citation.kind === "government_report_surrogate" && /not the Clark/i.test(citation.scope)), true);
});

test("the queue has no public manifest connection or artwork imagery", () => {
  assert.deepEqual(journey.associations, []);
  assert.equal(journey.clusters.every((cluster) => Array.isArray(cluster.association_ids) && cluster.association_ids.length === 0), true);
  assert.equal(journeyText.includes("research/review-queues"), false);
  assert.equal(indexText.includes("research/review-queues"), false);
  assert.equal(JSON.stringify(journeyIndex).includes("aerospace-folktales.json") || JSON.stringify(journeyIndex).includes("aerospace-folktales"), true);
  for (const candidate of queue.candidates) {
    assert.equal(journeyText.includes(candidate.candidate_id), false, candidate.candidate_id);
    assert.equal(indexText.includes(candidate.candidate_id), false, candidate.candidate_id);
  }
  assert.equal(/"(?:image|image_url|thumbnail_url)"\s*:/.test(queueText), false);
});

test("every public journey image byte is license-gated and checksum-bound", async () => {
  const publicImages = journey.photographs.filter((photograph) => photograph.image);
  assert.equal(publicImages.length, 1);
  for (const photograph of publicImages) {
    assert.equal(photograph.rights.public_display, true);
    assert.equal(photograph.rights.derivatives_allowed, true);
    assert.match(photograph.rights.license_url, /^https:\/\//);
    for (const [pathKey, checksumKey] of [["url", "sha256"], ["thumbnail_url", "thumbnail_sha256"]]) {
      const relative = photograph.image[pathKey].replace(/^\.\//, "");
      const bytes = await readFile(new URL(`docs/${relative}`, ROOT));
      assert.equal(`sha256:${createHash("sha256").update(bytes).digest("hex")}`, photograph.image[checksumKey]);
    }
  }
});

test("methodology documents provenance, copy scope, rights, and the human publication gate", () => {
  assert.match(methodology, /title-level/i);
  assert.match(methodology, /surviving Clark physical copy/i);
  assert.match(methodology, /does not.*influence/is);
  assert.match(methodology, /OSTI.*surrogate/is);
  assert.match(methodology, /No Allan Sekula artwork photograph is included/i);
  assert.match(methodology, /named reviewer/i);
  assert.match(methodology, /separate editorial publication commit/i);
});
