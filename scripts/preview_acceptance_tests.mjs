import assert from "node:assert/strict";

import { SIGNALS } from "../docs/js/signals.js";
import {
  buildReceiptAnnotations,
  computeSignalEvidence,
  computeSignalOverlaps,
  parsePhysicalIdentifier,
  parseSNumber,
  resolveSpatialPosition,
  spatialDiagnostics
} from "../docs/js/spatial.js";
import {
  buildNextCycleConfig,
  buildParticipationAnnotations,
  createPresenceToken,
  createVote,
  getActiveCycle,
  getCycleFilteredItems,
  isPresenceTokenEligible,
  tallyVotes
} from "../docs/js/exhibition.js";

const { createReceipt, verifyReceipt } = await import("../docs/js/receipt.js");

const sample = {
  id: "sample",
  title: "Dock workers and documentary photography",
  call_number: "NE2698 .S4637L 02895",
  subjects: ["Labor unions", "Documentary photography", "Shipping"],
  sekula_notes: ["Gift; Sally Stein, in memory of her husband; 2015; Sekula Library Identifier: Front Bedroom A"],
  provenance_notes: []
};

assert.equal(parseSNumber(sample.call_number), 2895, "S-number should parse from Clark call number suffix");
assert.equal(parseSNumber("S-10422"), 10422, "S-number should parse from explicit S-form");
assert.equal(parsePhysicalIdentifier(sample), "Front Bedroom A", "physical identifier should parse from provenance note");

const position = resolveSpatialPosition(sample);
assert.equal(position.wallLabel, "East Wall", "S02895 should map to East Wall");
assert.equal(position.zoneId, "E2", "S02895 should map to E2");
assert.equal(position.clusterId, "B", "S02895 should map to Cluster B");

const evidence = computeSignalEvidence(sample, ["labor", "image", "sea"], SIGNALS);
assert.ok(evidence.labor.length >= 1, "labor signal needs explainable evidence");
assert.ok(evidence.image.length >= 1, "image signal needs explainable evidence");
assert.ok(evidence.sea.length >= 1, "sea signal needs explainable evidence");

const overlaps = computeSignalOverlaps([
  { signals: ["labor", "image", "sea"], spatial: position },
  { signals: ["labor", "image"], spatial: position },
  { signals: ["sea", "capital"], spatial: position }
]);
assert.deepEqual(overlaps[0].signals, ["image", "labor"], "top overlap should be deterministic and sorted");
assert.equal(overlaps[0].count, 2, "top overlap count should be correct");

const diagnostics = spatialDiagnostics([{ spatial: position }, { spatial: resolveSpatialPosition({ call_number: "" }) }]);
assert.equal(diagnostics.total, 2, "diagnostics should count records");
assert.equal(diagnostics.withSNumber, 1, "diagnostics should count S-number coverage");
assert.equal(diagnostics.unmapped, 1, "diagnostics should count unmapped rows");

const annotations = buildReceiptAnnotations({
  groupBy: "zone",
  activePath: { id: "labor-images", label: "Labor And Images" },
  printMode: "view",
  diagnostics
});
assert.equal(annotations.spatialModel, "clark-reading-room@1", "receipt annotations should declare spatial model");
assert.equal(annotations.activePath.id, "labor-images", "receipt annotations should keep active path");

const receipt = await createReceipt({
  mode: "view",
  items: [sample],
  filters: { groupBy: "zone" },
  annotations
});
assert.equal(receipt.annotations.groupBy, "zone", "receipt should preserve annotations");
assert.equal((await verifyReceipt(receipt)).valid, true, "annotated receipt should verify");

const cycleConfig = {
  current_cycle_id: "cycle-004",
  cycles: [
    {
      cycle_id: "cycle-004",
      title: "Maritime Capitalism",
      status: "active",
      starts_at: "2026-06-01T10:00:00Z",
      ends_at: "2026-06-07T22:00:00Z",
      active_signals: ["capital", "sea"],
      active_zones: ["W3"],
      visual_behavior: "logistics_clusters",
      public_output: "reading_list",
      vote_count: 187
    }
  ]
};
const activeCycle = getActiveCycle(cycleConfig, new Date("2026-06-03T12:00:00Z"));
assert.equal(activeCycle.cycle_id, "cycle-004", "active exhibition cycle should resolve from config");

const token = createPresenceToken({
  cycleId: activeCycle.cycle_id,
  claimedAt: "2026-06-03T18:42:00Z",
  sequence: 184
});
assert.equal(token.token_id, "presence-2026-000184", "presence token should be human-readable and deterministic");
assert.equal(isPresenceTokenEligible(token, activeCycle, []), true, "fresh presence token should unlock voting");

const vote = createVote({
  token,
  cycle: activeCycle,
  selections: {
    selected_signal: "labor",
    selected_overlap: ["image", "labor"],
    selected_zone: "W4",
    selected_visual_behavior: "signal_overlaps",
    selected_output: "reading_list"
  },
  castAt: "2026-06-03T19:05:00Z"
});
assert.equal(vote.vote_id, "vote-004-000184", "vote ID should connect cycle and token sequence");
assert.deepEqual(vote.selected_overlap, ["image", "labor"], "vote should preserve selected overlap signals");
assert.equal(isPresenceTokenEligible({ ...token, has_voted: true }, activeCycle, [vote]), false, "used token should not vote again");

const tally = tallyVotes([
  vote,
  createVote({
    token: createPresenceToken({ cycleId: activeCycle.cycle_id, claimedAt: "2026-06-03T20:00:00Z", sequence: 185 }),
    cycle: activeCycle,
    selections: {
      selected_signal: "labor",
      selected_overlap: "image+labor",
      selected_zone: "W4",
      selected_visual_behavior: "signal_overlaps",
      selected_output: "wall_map"
    }
  })
], activeCycle);
assert.equal(tally.winning_signal.id, "labor", "tally should pick the winning signal");
assert.equal(tally.winning_overlap.id, "image+labor", "tally should pick the winning overlap");
assert.equal(tally.winning_zone.id, "W4", "tally should pick the winning zone");

const nextCycle = buildNextCycleConfig(activeCycle, tally);
assert.equal(nextCycle.cycle_id, "cycle-005", "next cycle should increment cycle ID");
assert.deepEqual(nextCycle.active_signals, ["image", "labor"], "next cycle should adopt winning overlap as active signals");

const cycleItems = getCycleFilteredItems([
  { id: "a", signals: ["image", "labor"], spatial: { zoneId: "W4" } },
  { id: "b", signals: ["capital", "sea"], spatial: { zoneId: "W3" } },
  { id: "c", signals: ["image"], spatial: { zoneId: "W4" } }
], nextCycle);
assert.deepEqual(cycleItems.map(item => item.id), ["a"], "cycle shelf view should prefer items matching overlap and zone");

const participationAnnotations = buildParticipationAnnotations({
  token: { ...token, has_voted: true },
  vote,
  cycle: activeCycle,
  shelf: [sample]
});
assert.equal(participationAnnotations.presence.token_id, "presence-2026-000184", "participation annotations should include token");
assert.equal(participationAnnotations.vote.vote_id, "vote-004-000184", "participation annotations should include vote");
assert.equal(participationAnnotations.shelfTrail[0].id, sample.id, "participation annotations should include shelf trail");

const participationReceipt = await createReceipt({
  mode: "participation",
  items: [sample],
  annotations: participationAnnotations
});
assert.equal(participationReceipt.mode, "participation", "participation receipt should preserve mode");
assert.equal((await verifyReceipt(participationReceipt)).valid, true, "participation receipt should verify");

console.log("Preview spatial and exhibition acceptance tests passed");
