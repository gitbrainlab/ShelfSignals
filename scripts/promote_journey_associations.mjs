#!/usr/bin/env node

/**
 * Evidence-safe publisher for reviewed ShelfSignals journey associations.
 *
 * The command is deliberately two-step. With no --output it validates and
 * prints a deterministic preview digest. A write requires a new output path
 * plus that exact digest through --confirm-preview. It never overwrites the
 * source manifest, updates the journey index, commits, or deploys anything.
 */

import { createHash } from "node:crypto";
import { constants as fsConstants } from "node:fs";
import { access, readFile, writeFile } from "node:fs/promises";
import { resolve } from "node:path";
import { pathToFileURL } from "node:url";

import {
  JOURNEY_EVIDENCE_GRADES,
  JOURNEY_MANIFEST_SCHEMA,
  JOURNEY_PHASES,
  parseJourneyManifest
} from "../docs/js/journeys.js";

export const ASSOCIATION_QUEUE_SCHEMA = "shelfsignals-association-review-queue@1";
export const ASSOCIATION_REVIEW_EXPORT_SCHEMA = "shelfsignals-association-review-export@1";
export const ASSOCIATION_PROMOTION_SCHEMA = "shelfsignals-association-promotion@1";

const REVIEW_DECISIONS = new Set(["approve", "reject", "needs_work"]);
const PUBLIC_ID = /^[a-z0-9][a-z0-9._-]*$/;
const MAX_REVIEW_REASON = 4000;
const REVIEW_FIELDS = new Set(["reviewer", "reviewed_at", "review_decision", "review_reason"]);
const CATALOG_SNAPSHOT_FIELDS = Object.freeze({
  title: "title",
  authors: "authors",
  year: "year",
  material_type: "material_type",
  formats: "formats",
  publishers: "publishers",
  call_number: "call_number",
  catalog_url: "record_url"
});

/**
 * This allowlist is intentionally non-causal. A future influence publisher
 * needs a separate, higher-bar contract; adding a plausible relation string
 * here must never silently produce a causal public claim.
 */
export const ASSOCIATION_RELATION_RULES = Object.freeze({
  documented_pre_project_reading_context: Object.freeze({
    phase: "preliminary_context",
    claimKind: "contextual_proximity",
    evidenceGrades: Object.freeze(["contextual"])
  }),
  documented_formative_course_reading_context: Object.freeze({
    phase: "preliminary_context",
    claimKind: "contextual_proximity",
    evidenceGrades: Object.freeze(["contextual"])
  }),
  documented_contemporaneous_photography_discussion: Object.freeze({
    phase: "early_research",
    claimKind: "contextual_proximity",
    evidenceGrades: Object.freeze(["contextual"])
  }),
  documented_object_in_work: Object.freeze({
    phase: "direct_alignment",
    claimKind: "documented_alignment",
    evidenceGrades: Object.freeze(["primary", "archival"]),
    copyIdentityAttestation: true
  }),
  post_project_conceptual_dialogue: Object.freeze({
    phase: "post_reflection",
    claimKind: "documented_post_reflection",
    evidenceGrades: Object.freeze(["primary", "archival", "scholarly"])
  }),
  documented_post_project_excerpt_and_circulation: Object.freeze({
    phase: "post_reflection",
    claimKind: "documented_post_reflection",
    evidenceGrades: Object.freeze(["primary", "archival"])
  })
});

function isObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function nonempty(value, maximum = 10_000) {
  return typeof value === "string" && value.trim().length > 0 && value.length <= maximum;
}

function jsonClone(value) {
  return JSON.parse(JSON.stringify(value));
}

function canonicalJson(value) {
  if (value === null || ["boolean", "number", "string"].includes(typeof value)) return JSON.stringify(value);
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (isObject(value)) {
    return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${canonicalJson(value[key])}`).join(",")}}`;
  }
  throw new TypeError("Canonical JSON accepts only JSON values.");
}

function jsonEqual(left, right) {
  if (left === undefined || right === undefined) return left === right;
  return canonicalJson(left) === canonicalJson(right);
}

export function canonicalSha256(value) {
  return `sha256:${createHash("sha256").update(canonicalJson(value)).digest("hex")}`;
}

function reviewDate(value) {
  const text = String(value || "").trim();
  if (!/^20\d{2}-\d{2}-\d{2}(?:T\d{2}:\d{2}:\d{2}Z)?$/.test(text)) return null;
  const parsed = new Date(text.length === 10 ? `${text}T00:00:00Z` : text);
  if (!Number.isFinite(parsed.valueOf())) return null;
  if (parsed.toISOString().slice(0, 10) !== text.slice(0, 10)) return null;
  if (text.length > 10 && parsed.toISOString().replace(".000Z", "Z") !== text) return null;
  return { text, day: text.slice(0, 10), value: parsed.valueOf() };
}

function safeHttpsUrl(value) {
  try {
    const url = new URL(String(value));
    return url.protocol === "https:" && !url.username && !url.password;
  } catch {
    return false;
  }
}

function stripReview(candidate) {
  return Object.fromEntries(Object.entries(candidate).filter(([key]) => !REVIEW_FIELDS.has(key)));
}

function citationBody(citation) {
  const body = jsonClone(citation);
  delete body.id;
  return body;
}

function citationKey(citation) {
  return canonicalJson(citationBody(citation));
}

function citationId(citation) {
  return `association-source-${createHash("sha256").update(citationKey(citation)).digest("hex").slice(0, 20)}`;
}

function catalogEvidenceRecord(record) {
  return {
    id: record.id,
    title: record.title,
    authors: record.authors,
    year: record.year,
    material_type: record.material_type,
    formats: record.formats,
    publishers: record.publishers,
    call_number: record.call_number,
    record_url: record.record_url,
    provenance_notes: record.provenance_notes
  };
}

function issue(code, message, path = "") {
  return { code, path, message };
}

export class AssociationPromotionError extends Error {
  constructor(issues) {
    const list = Array.isArray(issues) ? issues : [issues];
    super(list.map(item => `[${item.code}]${item.path ? ` ${item.path}:` : ""} ${item.message}`).join("\n"));
    this.name = "AssociationPromotionError";
    this.issues = list;
  }
}

function collector() {
  const errors = [];
  return {
    errors,
    add(code, message, path = "") {
      errors.push(issue(code, message, path));
    },
    require(condition, code, message, path = "") {
      if (!condition) errors.push(issue(code, message, path));
      return Boolean(condition);
    },
    throwIfAny() {
      if (errors.length) throw new AssociationPromotionError(errors);
    }
  };
}

function hasAffirmativeCausalLanguage(value) {
  const text = String(value || "");
  const causal = /\b(?:inspir(?:e|ed|es|ing|ation|ational)|influenc(?:e|ed|es|ing)|caus(?:e|ed|es|ing|al|ation)|shap(?:e|ed|es|ing)|prompt(?:ed|s|ing)|led\s+to)\b/gi;
  for (const match of text.matchAll(causal)) {
    const before = text.slice(Math.max(0, match.index - 180), match.index);
    const after = text.slice(match.index + match[0].length, match.index + match[0].length + 80);
    const negatedBefore = /\b(?:not|no|never|neither|without|cannot|can't|does\s+not|do\s+not|did\s+not|doesn't|isn't|aren't|unconfirmed|unsupported|fails?\s+to)\b[^.!?]{0,160}$/i.test(before)
      || /\bnon[-\s]?$/i.test(before);
    const limitedAfter = /^[^.!?]{0,60}\b(?:not\s+(?:established|documented|supported)|unconfirmed|unsupported)\b/i.test(after);
    if (!negatedBefore && !limitedAfter) return true;
  }
  return false;
}

function staleAbsenceClaim(value) {
  const text = String(value || "");
  return /only\s+the\s+Clark\s+record[^.!?]{0,180}(?:shown|displayed)[^.!?]{0,180}await[^.!?]{0,100}review/i.test(text)
    || /\bremains?\s+excluded\b[^.!?]{0,180}\b(?:review|confirm)/i.test(text)
    || /\b(?:association|candidate\s+relation)s?\s+(?:remain|are)\s+(?:unpublished|excluded|withheld|pending\s+review)\b/i.test(text);
}

function hasCopyIdentityAttestation(value) {
  const text = String(value || "");
  const match = /(?:^|[.;!?]\s*)copy\s+identity\s+confirmed(?:[.;:]|\s+(?:against|after|by|through)\b)/i.exec(text);
  if (!match) return false;
  const sameClause = text.slice(match.index + match[0].length).split(/[.;!?]/, 1)[0];
  return !/\b(?:cannot|false|not|pending|unable|unconfirmed)\b/i.test(sameClause);
}

function validateCatalogSnapshot(candidate, source, at, check) {
  if (!isObject(candidate.catalog_snapshot)) {
    check.add("missing_catalog_snapshot", "Candidate needs its Clark catalog snapshot.", `${at}.catalog_snapshot`);
    return;
  }
  for (const [snapshotField, sourceField] of Object.entries(CATALOG_SNAPSHOT_FIELDS)) {
    const left = candidate.catalog_snapshot[snapshotField];
    const right = source[sourceField];
    check.require(
      jsonEqual(left, right),
      "catalog_snapshot_mismatch",
      `${snapshotField} no longer matches catalog record ${candidate.catalog_id}.`,
      `${at}.catalog_snapshot.${snapshotField}`
    );
  }
}

function validateCitation(citation, candidate, source, at, check) {
  if (!isObject(citation)) {
    check.add("invalid_citation", "Citation must be an object.", at);
    return;
  }
  check.require(nonempty(citation.kind, 100), "invalid_citation", "Citation kind is required.", `${at}.kind`);
  check.require(nonempty(citation.title, 1000), "invalid_citation", "Citation title is required.", `${at}.title`);
  check.require(nonempty(citation.creator, 1000), "invalid_citation", "Citation creator is required.", `${at}.creator`);
  check.require(safeHttpsUrl(citation.url), "unsafe_citation_url", "Citation URL must be credential-free HTTPS.", `${at}.url`);
  check.require(nonempty(citation.locator, 2000) && citation.locator.trim().length >= 12, "imprecise_citation", "Citation needs a precise locator.", `${at}.locator`);
  check.require(nonempty(citation.scope, 1000), "missing_citation_scope", "Citation must state its evidentiary scope.", `${at}.scope`);
  if (citation.kind === "catalog" && citation.url === source.record_url) {
    check.require(citation.locator.includes(candidate.catalog_id.replace(/^alma/, "")) || citation.locator.includes(candidate.catalog_id), "catalog_locator_mismatch", "Catalog citation locator must identify the candidate record.", `${at}.locator`);
  }
}

function validateQueueAndCatalog(queue, catalog, manifest, now, check) {
  check.require(isObject(queue), "invalid_queue", "Queue must be a JSON object.", "queue");
  if (!isObject(queue)) return { candidates: [], catalogById: new Map(), clusters: new Set() };
  check.require(queue.schema === ASSOCIATION_QUEUE_SCHEMA, "invalid_queue_schema", `Expected ${ASSOCIATION_QUEUE_SCHEMA}.`, "queue.schema");
  check.require(queue.publication_status === "unpublished", "queue_is_public", "Queue must remain unpublished.", "queue.publication_status");
  check.require(queue.publication_effect === "none", "queue_has_publication_effect", "Queue must declare publication_effect none.", "queue.publication_effect");
  check.require(nonempty(queue.journey_id, 200), "missing_journey_id", "Queue journey ID is required.", "queue.journey_id");
  check.require(Array.isArray(queue.candidates), "invalid_candidates", "Queue candidates must be an array.", "queue.candidates");
  check.require(Array.isArray(catalog), "invalid_catalog", "Catalog must be an array.", "catalog");

  const catalogById = new Map();
  if (Array.isArray(catalog)) {
    catalog.forEach((record, index) => {
      if (!isObject(record) || !nonempty(record.id, 240)) check.add("invalid_catalog_record", "Catalog record needs an ID.", `catalog.${index}`);
      else if (catalogById.has(record.id)) check.add("duplicate_catalog_id", `Duplicate catalog ID ${record.id}.`, `catalog.${index}.id`);
      else catalogById.set(record.id, record);
    });
  }

  check.require(isObject(manifest), "invalid_manifest", "Manifest must be a JSON object.", "manifest");
  const clusters = new Set(Array.isArray(manifest?.clusters) ? manifest.clusters.map(cluster => cluster?.id).filter(Boolean) : []);
  check.require(manifest?.schema === JOURNEY_MANIFEST_SCHEMA, "invalid_manifest_schema", `Expected ${JOURNEY_MANIFEST_SCHEMA}.`, "manifest.schema");
  check.require(manifest?.publication_status === "published", "manifest_not_public", "Association promotion targets an already-public journey manifest.", "manifest.publication_status");
  check.require(manifest?.id === queue.journey_id, "journey_mismatch", "Queue and manifest journey IDs differ.", "manifest.id");

  const target = queue.target_work;
  if (!isObject(target) || !nonempty(target.catalog_id, 240)) {
    check.add("invalid_target_work", "Queue target_work must name a Clark catalog ID.", "queue.target_work");
  } else {
    const targetCatalog = catalogById.get(target.catalog_id);
    check.require(Boolean(targetCatalog), "unknown_target_work", `Unknown target catalog ID ${target.catalog_id}.`, "queue.target_work.catalog_id");
    if (targetCatalog) {
      check.require(target.title === targetCatalog.title, "target_identity_mismatch", "Target title no longer matches the Clark catalog.", "queue.target_work.title");
      check.require(target.date === targetCatalog.year, "target_identity_mismatch", "Target date no longer matches the Clark catalog.", "queue.target_work.date");
      check.require(target.catalog_url === targetCatalog.record_url, "target_identity_mismatch", "Target URL no longer matches the Clark catalog.", "queue.target_work.catalog_url");
    }
    const publicTarget = Array.isArray(manifest?.target_works) ? manifest.target_works.find(work => work?.id === target.catalog_id) : null;
    check.require(Boolean(publicTarget), "missing_public_target", "Public manifest does not contain the queue target work.", "manifest.target_works");
    if (publicTarget && targetCatalog) {
      check.require(publicTarget.title === targetCatalog.title && publicTarget.date === targetCatalog.year, "public_target_mismatch", "Public target title/date do not match the Clark catalog.", "manifest.target_works");
    }
  }

  const generated = reviewDate(String(queue.generated_at || "").slice(0, 10));
  check.require(Boolean(generated), "invalid_queue_date", "Queue generated_at must begin with a valid 20xx ISO date.", "queue.generated_at");
  const today = new Date(now).toISOString().slice(0, 10);
  if (generated) check.require(generated.day <= today, "future_queue", "Queue generation date cannot be in the future.", "queue.generated_at");

  const candidates = Array.isArray(queue.candidates) ? queue.candidates : [];
  const ids = new Set();
  candidates.forEach((candidate, index) => {
    const at = `queue.candidates.${index}`;
    if (!isObject(candidate)) {
      check.add("invalid_candidate", "Candidate must be an object.", at);
      return;
    }
    check.require(PUBLIC_ID.test(candidate.candidate_id || ""), "invalid_candidate_id", "Candidate ID must be a stable public-safe ID.", `${at}.candidate_id`);
    if (ids.has(candidate.candidate_id)) check.add("duplicate_candidate_id", `Duplicate candidate ID ${candidate.candidate_id}.`, `${at}.candidate_id`);
    ids.add(candidate.candidate_id);
    check.require(candidate.publication_status === "unpublished", "candidate_is_public", "Queue candidate must remain unpublished.", `${at}.publication_status`);
    for (const field of REVIEW_FIELDS) check.require(candidate[field] === null, "queue_contains_review", `${field} must be null in the source queue.`, `${at}.${field}`);
    check.require(candidate.journey_id === queue.journey_id, "candidate_journey_mismatch", "Candidate journey ID differs from the queue.", `${at}.journey_id`);
    check.require(candidate.target_work === target?.catalog_id, "candidate_target_mismatch", "Candidate target work differs from the queue.", `${at}.target_work`);
    check.require(clusters.has(candidate.cluster_id), "unknown_cluster", "Candidate cluster does not exist in the public manifest.", `${at}.cluster_id`);
    check.require(JOURNEY_PHASES.includes(candidate.phase), "invalid_phase", "Candidate phase is not supported.", `${at}.phase`);
    check.require(JOURNEY_EVIDENCE_GRADES.includes(candidate.evidence_grade), "invalid_evidence_grade", "Candidate evidence grade is not supported.", `${at}.evidence_grade`);
    const rule = ASSOCIATION_RELATION_RULES[candidate.relation_type];
    check.require(Boolean(rule), "unsupported_relation", "Relation type is not in the non-causal publication allowlist.", `${at}.relation_type`);
    if (rule) {
      check.require(candidate.phase === rule.phase, "relation_phase_conflict", `Relation ${candidate.relation_type} requires phase ${rule.phase}.`, `${at}.phase`);
      check.require(rule.evidenceGrades.includes(candidate.evidence_grade), "relation_grade_conflict", `Evidence grade ${candidate.evidence_grade} is not allowed for ${candidate.relation_type}.`, `${at}.evidence_grade`);
    }
    check.require(nonempty(candidate.proposed_reasoning, 6000), "missing_reasoning", "Candidate reasoning is required.", `${at}.proposed_reasoning`);
    check.require(nonempty(candidate.inference_limit, 3000), "missing_inference_limit", "Candidate needs an explicit inference limit.", `${at}.inference_limit`);
    if (hasAffirmativeCausalLanguage(candidate.proposed_reasoning) || hasAffirmativeCausalLanguage(candidate.inference_limit)) {
      check.add("unsupported_causal_claim", "Non-causal relation contains affirmative influence, inspiration, or causation language.", at);
    }
    const source = catalogById.get(candidate.catalog_id);
    check.require(Boolean(source), "unknown_catalog_id", `Unknown Clark catalog ID ${candidate.catalog_id}.`, `${at}.catalog_id`);
    if (source) validateCatalogSnapshot(candidate, source, at, check);
    check.require(Array.isArray(candidate.citations) && candidate.citations.length >= 2, "insufficient_citations", "Candidate needs at least two precisely located citations.", `${at}.citations`);
    if (source && Array.isArray(candidate.citations)) {
      const seenCitations = new Set();
      candidate.citations.forEach((citation, citationIndex) => {
        validateCitation(citation, candidate, source, `${at}.citations.${citationIndex}`, check);
        if (isObject(citation)) {
          const key = citationKey(citation);
          if (seenCitations.has(key)) check.add("duplicate_candidate_citation", "Candidate repeats an identical citation.", `${at}.citations.${citationIndex}`);
          seenCitations.add(key);
        }
      });
      check.require(candidate.citations.some(citation => citation?.kind === "catalog" && citation.url === source.record_url), "missing_catalog_citation", "Candidate must cite its exact Clark catalog record.", `${at}.citations`);
      check.require(candidate.citations.some(citation => citation?.kind !== "catalog"), "missing_relation_citation", "Candidate needs non-catalog evidence for the proposed relation.", `${at}.citations`);
    }
  });
  return { candidates, catalogById, clusters, generatedDay: generated?.day || "" };
}

function validateReviewExport(queue, reviewExport, candidateContext, now, check) {
  check.require(isObject(reviewExport), "invalid_review_export", "Review export must be a JSON object.", "reviews");
  if (!isObject(reviewExport)) return [];
  check.require(reviewExport.schema === ASSOCIATION_REVIEW_EXPORT_SCHEMA, "invalid_review_schema", `Expected ${ASSOCIATION_REVIEW_EXPORT_SCHEMA}.`, "reviews.schema");
  check.require(reviewExport.source_schema === ASSOCIATION_QUEUE_SCHEMA, "invalid_review_source", "Review export source schema does not match the queue.", "reviews.source_schema");
  check.require(reviewExport.publication_effect === "none", "review_export_is_public", "Review export must retain publication_effect none.", "reviews.publication_effect");
  check.require(Array.isArray(reviewExport.candidates), "invalid_review_candidates", "Review export candidates must be an array.", "reviews.candidates");
  const exported = Array.isArray(reviewExport.candidates) ? reviewExport.candidates : [];
  check.require(exported.length === candidateContext.candidates.length, "incomplete_review_export", "Every queue candidate must appear exactly once in the review export.", "reviews.candidates");

  const queueById = new Map(candidateContext.candidates.map(candidate => [candidate.candidate_id, candidate]));
  const seen = new Set();
  const today = new Date(now).toISOString().slice(0, 10);
  exported.forEach((reviewed, index) => {
    const at = `reviews.candidates.${index}`;
    if (!isObject(reviewed)) {
      check.add("invalid_reviewed_candidate", "Reviewed candidate must be an object.", at);
      return;
    }
    if (seen.has(reviewed.candidate_id)) check.add("duplicate_reviewed_candidate", `Duplicate reviewed candidate ${reviewed.candidate_id}.`, `${at}.candidate_id`);
    seen.add(reviewed.candidate_id);
    const original = queueById.get(reviewed.candidate_id);
    check.require(Boolean(original), "unknown_reviewed_candidate", `Review export contains unknown candidate ${reviewed.candidate_id}.`, `${at}.candidate_id`);
    if (original) {
      check.require(canonicalJson(stripReview(reviewed)) === canonicalJson(stripReview(original)), "review_evidence_changed", "Review export changed immutable candidate evidence.", at);
    }
    check.require(reviewed.publication_status === "unpublished", "review_published_candidate", "Reviewed candidate must remain unpublished.", `${at}.publication_status`);
    check.require(REVIEW_DECISIONS.has(reviewed.review_decision), "missing_review_decision", "Every candidate needs approve, reject, or needs_work.", `${at}.review_decision`);
    check.require(nonempty(reviewed.reviewer, 200), "missing_reviewer", "Every review decision needs a named reviewer.", `${at}.reviewer`);
    const reviewedAt = reviewDate(reviewed.reviewed_at);
    check.require(Boolean(reviewedAt), "invalid_review_date", "Every decision needs a valid 20xx ISO review date or second-precision UTC timestamp.", `${at}.reviewed_at`);
    if (reviewedAt) {
      check.require(reviewedAt.day >= candidateContext.generatedDay, "stale_review", "Review date predates the candidate queue.", `${at}.reviewed_at`);
      check.require(reviewedAt.day <= today, "future_review", "Review date cannot be in the future.", `${at}.reviewed_at`);
    }
    check.require(nonempty(reviewed.review_reason, MAX_REVIEW_REASON), "missing_review_reason", `Every decision needs a 1–${MAX_REVIEW_REASON} character reason.`, `${at}.review_reason`);
    if (reviewed.review_decision === "approve" && hasAffirmativeCausalLanguage(reviewed.review_reason)) {
      check.add("review_overclaim", "Approval reason adds an unsupported affirmative causal claim.", `${at}.review_reason`);
    }
  });
  for (const candidate of candidateContext.candidates) {
    if (!seen.has(candidate.candidate_id)) check.add("missing_reviewed_candidate", `Review export omits ${candidate.candidate_id}.`, "reviews.candidates");
  }
  return exported;
}

function validateSourceManifest(manifest, catalogIds, check) {
  const parsed = parseJourneyManifest(manifest, { catalogIds });
  if (parsed.rejected) {
    for (const error of parsed.errors) check.add(`manifest_${error.code}`, error.message, error.path);
  }
  const rawAssociationIds = new Set();
  const catalogAssociations = new Map();
  for (const association of Array.isArray(manifest.associations) ? manifest.associations : []) {
    if (rawAssociationIds.has(association.id)) check.add("duplicate_public_association", `Duplicate public association ID ${association.id}.`, "manifest.associations");
    rawAssociationIds.add(association.id);
    if (catalogAssociations.has(association.catalog_id)) check.add("duplicate_public_catalog_association", `Multiple public associations already use ${association.catalog_id}.`, "manifest.associations");
    catalogAssociations.set(association.catalog_id, association);
  }
  return { parsed, rawAssociationIds, catalogAssociations };
}

function addCitation(citation, state, check) {
  const bodyKey = citationKey(citation);
  const existingId = state.idByBody.get(bodyKey);
  if (existingId) return existingId;
  const id = citationId(citation);
  const collision = state.bodyById.get(id);
  if (collision && collision !== bodyKey) {
    check.add("citation_id_collision", `Generated citation ID ${id} conflicts with different evidence.`, "manifest.citations");
    return id;
  }
  const promoted = { id, ...jsonClone(citation) };
  state.citations.push(promoted);
  state.bodyById.set(id, bodyKey);
  state.idByBody.set(bodyKey, id);
  state.addedIds.push(id);
  return id;
}

function promotionAssociation(candidate, reviewed, claimKind, citationIds) {
  const copyIdentityConfirmed = hasCopyIdentityAttestation(reviewed.review_reason);
  const identityResolution = copyIdentityConfirmed
    ? ` Review resolution: copy identity confirmed by ${reviewed.reviewer} on ${reviewed.reviewed_at}.`
    : "";
  return {
    id: candidate.candidate_id,
    source_candidate_id: candidate.candidate_id,
    catalog_id: candidate.catalog_id,
    catalog_snapshot: jsonClone(candidate.catalog_snapshot),
    placement: candidate.placement,
    placement_source: candidate.placement_source,
    journey_id: candidate.journey_id,
    cluster_id: candidate.cluster_id,
    phase: candidate.phase,
    phase_label: candidate.phase_label,
    target_work_id: candidate.target_work,
    relation_type: candidate.relation_type,
    claim_kind: claimKind,
    temporal_basis: candidate.temporal_basis,
    object_identity_scope: candidate.object_identity_scope,
    source_reasoning: candidate.proposed_reasoning,
    reasoning: `${candidate.proposed_reasoning}${identityResolution} Evidence limit: ${candidate.inference_limit}`,
    inference_limit: candidate.inference_limit,
    evidence_grade: candidate.evidence_grade,
    candidate_source: candidate.candidate_source,
    citation_ids: citationIds,
    object_identity_review: copyIdentityConfirmed ? {
      status: "confirmed",
      reviewer: reviewed.reviewer,
      reviewed_at: reviewed.reviewed_at,
      attestation: "copy identity confirmed"
    } : {
      status: "bounded_to_stated_scope"
    },
    review: {
      status: "approved",
      decision: "approve",
      reviewer: reviewed.reviewer,
      reviewed_at: reviewed.reviewed_at,
      reason: reviewed.review_reason
    }
  };
}

/**
 * Validate all four evidence inputs and construct a deterministic proposed
 * public manifest. This function performs no filesystem or network writes.
 */
export function buildAssociationPromotion({
  queue,
  reviewExport,
  manifest,
  catalog,
  editor,
  editorReviewedAt,
  editorialVersion,
  now = new Date()
}) {
  const check = collector();
  const nowDate = new Date(now);
  check.require(Number.isFinite(nowDate.valueOf()), "invalid_clock", "Validation clock is invalid.", "now");
  const editorDate = reviewDate(editorReviewedAt);
  check.require(nonempty(editor, 200), "missing_editor", "A named publication editor is required.", "editor");
  check.require(Boolean(editorDate), "invalid_editor_date", "Publication editor date must be a valid 20xx ISO date or second-precision UTC timestamp.", "editorReviewedAt");
  check.require(nonempty(editorialVersion, 100) && /^[0-9]+\.[0-9]+\.[0-9]+(?:[-+][0-9A-Za-z.-]+)?$/.test(editorialVersion), "invalid_editorial_version", "An explicit semantic editorial version is required.", "editorialVersion");
  if (editorDate && Number.isFinite(nowDate.valueOf())) {
    check.require(editorDate.day <= nowDate.toISOString().slice(0, 10), "future_editor_review", "Publication editor date cannot be in the future.", "editorReviewedAt");
  }

  const context = validateQueueAndCatalog(queue, catalog, manifest, nowDate, check);
  const reviewedCandidates = validateReviewExport(queue, reviewExport, context, nowDate, check);
  const manifestContext = validateSourceManifest(manifest, [...context.catalogById.keys()], check);
  check.throwIfAny();

  const queueById = new Map(context.candidates.map(candidate => [candidate.candidate_id, candidate]));
  const approved = reviewedCandidates.filter(candidate => candidate.review_decision === "approve");
  if (approved.length && editorDate) {
    const latestReviewDay = approved.map(item => reviewDate(item.reviewed_at)?.day || "").sort().at(-1);
    check.require(editorDate.day >= latestReviewDay, "editor_predates_review", "Publication editor date cannot precede an approved human review.", "editorReviewedAt");
  }

  const citationState = {
    citations: jsonClone(manifest.citations),
    bodyById: new Map(),
    idByBody: new Map(),
    addedIds: []
  };
  for (const citation of citationState.citations) {
    const key = citationKey(citation);
    if (citationState.bodyById.has(citation.id) && citationState.bodyById.get(citation.id) !== key) {
      check.add("conflicting_existing_citation", `Citation ID ${citation.id} has conflicting bodies.`, "manifest.citations");
    }
    citationState.bodyById.set(citation.id, key);
    if (!citationState.idByBody.has(key)) citationState.idByBody.set(key, citation.id);
  }

  const additions = [];
  const clusterAdditions = new Map();
  const promotedCatalogIds = new Map();
  for (const reviewed of approved) {
    const candidate = queueById.get(reviewed.candidate_id);
    const rule = ASSOCIATION_RELATION_RULES[candidate.relation_type];
    if (manifestContext.rawAssociationIds.has(candidate.candidate_id)) {
      check.add("association_id_conflict", `Public manifest already contains ${candidate.candidate_id}; the publisher is not an updater.`, "manifest.associations");
      continue;
    }
    if (manifestContext.catalogAssociations.has(candidate.catalog_id)) {
      const prior = manifestContext.catalogAssociations.get(candidate.catalog_id);
      check.add("catalog_association_conflict", `${candidate.catalog_id} is already associated as ${prior.id}; competing phases or clusters require manual resolution.`, "manifest.associations");
      continue;
    }
    if (promotedCatalogIds.has(candidate.catalog_id)) {
      check.add("competing_approved_candidates", `${candidate.catalog_id} is approved more than once (${promotedCatalogIds.get(candidate.catalog_id)} and ${candidate.candidate_id}); resolve the competing phase/cluster claims manually.`, "reviews.candidates");
      continue;
    }
    promotedCatalogIds.set(candidate.catalog_id, candidate.candidate_id);
    if (rule.copyIdentityAttestation && !hasCopyIdentityAttestation(reviewed.review_reason)) {
      check.add("missing_copy_identity_attestation", "Direct object-in-work approval must include the exact attestation words ‘copy identity confirmed’ in the review reason.", `reviews.${candidate.candidate_id}.review_reason`);
    }
    if (rule.claimKind === "documented_alignment" && /(?:unconfirmed|pending)/i.test(candidate.object_identity_scope) && !hasCopyIdentityAttestation(reviewed.review_reason)) {
      check.add("unresolved_object_identity", "A direct public claim cannot retain unresolved copy identity without the named-reviewer attestation.", `queue.${candidate.candidate_id}.object_identity_scope`);
    }
    if (staleAbsenceClaim(manifest.introduction)) {
      check.add("stale_manifest_narrative", "Manifest introduction still says reviewed associations are absent; edit the source narrative before promotion.", "manifest.introduction");
    }
    const cluster = manifest.clusters.find(item => item.id === candidate.cluster_id);
    if (staleAbsenceClaim(cluster?.narrative)) {
      check.add("stale_cluster_narrative", `Cluster ${candidate.cluster_id} still says this evidence is excluded pending review; edit it before promotion.`, `manifest.clusters.${candidate.cluster_id}.narrative`);
    }
    const citationIds = candidate.citations.map(citation => addCitation(citation, citationState, check));
    additions.push(promotionAssociation(candidate, reviewed, rule.claimKind, citationIds));
    if (!clusterAdditions.has(candidate.cluster_id)) clusterAdditions.set(candidate.cluster_id, []);
    clusterAdditions.get(candidate.cluster_id).push(candidate.candidate_id);
  }
  check.throwIfAny();

  const proposedManifest = jsonClone(manifest);
  proposedManifest.citations = citationState.citations;
  proposedManifest.associations = [...jsonClone(manifest.associations), ...additions];
  proposedManifest.clusters = proposedManifest.clusters.map(cluster => ({
    ...cluster,
    association_ids: [...new Set([...(cluster.association_ids || []), ...(clusterAdditions.get(cluster.id) || [])])]
  }));
  proposedManifest.editorial = {
    editor: String(editor).trim(),
    reviewed_at: editorDate.text,
    version: editorialVersion
  };
  const relevantCatalog = [queue.target_work.catalog_id, ...context.candidates.map(candidate => candidate.catalog_id)]
    .filter((id, index, values) => values.indexOf(id) === index)
    .sort()
    .map(id => catalogEvidenceRecord(context.catalogById.get(id)));
  proposedManifest.association_promotion = {
    schema: ASSOCIATION_PROMOTION_SCHEMA,
    publication_effect: "proposed_manifest_only",
    editor: String(editor).trim(),
    reviewed_at: editorDate.text,
    queue_canonical_sha256: canonicalSha256(queue),
    review_export_canonical_sha256: canonicalSha256(reviewExport),
    source_manifest_canonical_sha256: canonicalSha256(manifest),
    catalog_evidence_canonical_sha256: canonicalSha256(relevantCatalog),
    approved_candidate_ids: additions.map(association => association.id)
  };

  const parsedOutput = parseJourneyManifest(proposedManifest, { catalogIds: [...context.catalogById.keys()] });
  if (parsedOutput.rejected) {
    throw new AssociationPromotionError(parsedOutput.errors.map(error => issue(`output_${error.code}`, error.message, error.path)));
  }
  if (parsedOutput.associations.length !== proposedManifest.associations.length) {
    throw new AssociationPromotionError(issue("output_association_filter", "Runtime validation filtered one or more proposed public associations.", "manifest.associations"));
  }

  const digest = canonicalSha256(proposedManifest);
  const decisionCounts = reviewedCandidates.reduce((counts, candidate) => {
    counts[candidate.review_decision] += 1;
    return counts;
  }, { approve: 0, reject: 0, needs_work: 0 });
  return {
    proposedManifest,
    preview: {
      schema: ASSOCIATION_PROMOTION_SCHEMA,
      mode: "preview",
      writes_performed: 0,
      journey_id: queue.journey_id,
      proposed_manifest_sha256: digest,
      approved_association_count: additions.length,
      decision_counts: decisionCounts,
      approved_associations: additions.map(association => ({
        id: association.id,
        catalog_id: association.catalog_id,
        cluster_id: association.cluster_id,
        phase: association.phase,
        claim_kind: association.claim_kind,
        evidence_grade: association.evidence_grade,
        reviewer: association.review.reviewer,
        reviewed_at: association.review.reviewed_at
      })),
      added_citation_count: citationState.addedIds.length,
      added_citation_ids: citationState.addedIds,
      notice: "No file was written. Re-run unchanged inputs with --output and --confirm-preview set to proposed_manifest_sha256. The output remains undeployed and unindexed."
    }
  };
}

export function validateAssociationPromotion(input) {
  try {
    const result = buildAssociationPromotion(input);
    return { ok: true, errors: [], ...result };
  } catch (error) {
    if (error instanceof AssociationPromotionError) return { ok: false, errors: error.issues, proposedManifest: null, preview: null };
    throw error;
  }
}

function usage() {
  return `Usage:
  node scripts/promote_journey_associations.mjs \\
    --queue <private-queue.json> \\
    --reviews <review-export.json> \\
    --manifest <public-journey.json> \\
    --catalog <sekula_index.json> \\
    --editor <name> --editor-date <YYYY-MM-DD> --version <semver>

The first run is a read-only preview. To write a new, non-overwriting file:
  [same command] --output <new-manifest.json> \\
    --confirm-preview <sha256-from-preview>

The command never overwrites an input/output, updates the journey index,
commits, pushes, or deploys. A written output is still an editorial proposal.`;
}

function parseArgs(argv) {
  const known = new Set(["queue", "reviews", "manifest", "catalog", "editor", "editor-date", "version", "output", "confirm-preview"]);
  const values = {};
  for (let index = 0; index < argv.length; index += 1) {
    const token = argv[index];
    if (token === "--help" || token === "-h") return { help: true };
    if (!token.startsWith("--") || !known.has(token.slice(2))) throw new Error(`Unknown argument: ${token}`);
    const key = token.slice(2);
    if (values[key] !== undefined) throw new Error(`Duplicate argument: ${token}`);
    const value = argv[index + 1];
    if (!value || value.startsWith("--")) throw new Error(`${token} requires a value.`);
    values[key] = value;
    index += 1;
  }
  for (const required of ["queue", "reviews", "manifest", "catalog", "editor", "editor-date", "version"]) {
    if (!values[required]) throw new Error(`--${required} is required.`);
  }
  if (values["confirm-preview"] && !values.output) throw new Error("--confirm-preview is valid only with an explicit --output path.");
  return values;
}

async function readJson(path, label) {
  let text;
  try {
    text = await readFile(path, "utf8");
  } catch (error) {
    throw new Error(`Could not read ${label} at ${path}: ${error.message}`);
  }
  try {
    return JSON.parse(text);
  } catch (error) {
    throw new Error(`${label} is not valid JSON: ${error.message}`);
  }
}

async function outputExists(path) {
  try {
    await access(path, fsConstants.F_OK);
    return true;
  } catch {
    return false;
  }
}

export async function runCli(argv = process.argv.slice(2)) {
  const args = parseArgs(argv);
  if (args.help) {
    process.stdout.write(`${usage()}\n`);
    return { mode: "help" };
  }
  const inputPaths = [args.queue, args.reviews, args.manifest, args.catalog].map(path => resolve(path));
  const [queue, reviewExport, manifest, catalog] = await Promise.all([
    readJson(inputPaths[0], "association queue"),
    readJson(inputPaths[1], "review export"),
    readJson(inputPaths[2], "journey manifest"),
    readJson(inputPaths[3], "Clark catalog")
  ]);
  const result = buildAssociationPromotion({
    queue,
    reviewExport,
    manifest,
    catalog,
    editor: args.editor,
    editorReviewedAt: args["editor-date"],
    editorialVersion: args.version
  });

  if (!args.output) {
    process.stdout.write(`${JSON.stringify(result.preview, null, 2)}\n`);
    return result.preview;
  }
  if (!args["confirm-preview"]) {
    throw new Error(`--output does not write without --confirm-preview ${result.preview.proposed_manifest_sha256}. Run the preview first.`);
  }
  if (args["confirm-preview"] !== result.preview.proposed_manifest_sha256) {
    throw new Error(`Preview digest mismatch. Expected ${result.preview.proposed_manifest_sha256}; no file was written.`);
  }
  if (result.preview.approved_association_count === 0) throw new Error("No approved associations exist; refusing to write a no-op promoted manifest.");
  const outputPath = resolve(args.output);
  if (!/\.json$/i.test(outputPath)) throw new Error("--output must end in .json.");
  if (inputPaths.includes(outputPath)) throw new Error("--output must be a new path and cannot overwrite any input.");
  if (await outputExists(outputPath)) throw new Error(`Output already exists at ${outputPath}; refusing to overwrite it.`);
  await writeFile(outputPath, `${JSON.stringify(result.proposedManifest, null, 2)}\n`, { encoding: "utf8", flag: "wx" });
  const receipt = {
    schema: ASSOCIATION_PROMOTION_SCHEMA,
    mode: "write",
    writes_performed: 1,
    output: outputPath,
    proposed_manifest_sha256: result.preview.proposed_manifest_sha256,
    approved_association_count: result.preview.approved_association_count,
    notice: "A new manifest proposal was written. It was not indexed, committed, pushed, or deployed. Review its diff and run the repository test suite before manual publication."
  };
  process.stdout.write(`${JSON.stringify(receipt, null, 2)}\n`);
  return receipt;
}

const invokedPath = process.argv[1] ? pathToFileURL(resolve(process.argv[1])).href : "";
if (import.meta.url === invokedPath) {
  runCli().catch(error => {
    process.stderr.write(`${error.message}\n`);
    process.exitCode = 2;
  });
}
