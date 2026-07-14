/**
 * Runtime contracts for evidence-first ShelfSignals journeys.
 *
 * Published manifests contain only human-approved associations. Photographs
 * without public-display authority remain useful, cited metadata records, but
 * their image URLs are removed. Generated interface labels never turn
 * contextual proximity into a claim of influence or inspiration.
 */

// @ts-check

export const JOURNEY_INDEX_SCHEMA = "shelfsignals-journey-index@1";
export const JOURNEY_MANIFEST_SCHEMA = "shelfsignals-journey@1";

export const JOURNEY_PHASES = Object.freeze([
  "preliminary_context",
  "early_research",
  "direct_alignment",
  "post_reflection"
]);

export const JOURNEY_CLAIM_KINDS = Object.freeze([
  "identity_anchor",
  "documented_influence",
  "documented_research_use",
  "documented_alignment",
  "documented_post_reflection",
  "contextual_proximity"
]);

export const JOURNEY_EVIDENCE_GRADES = Object.freeze(["primary", "archival", "scholarly", "contextual"]);
export const PHOTO_RIGHTS_BASES = Object.freeze([
  "institution_permission",
  "open_license",
  "public_domain",
  "provider_display_terms",
  "pending",
  "unknown"
]);

const PUBLICATION_STATUSES = Object.freeze(["draft", "published"]);
const INFLUENCE_EVIDENCE = new Set(["primary", "archival"]);
const ID_PATTERN = /^[a-z0-9][a-z0-9._-]*$/;
const ISO_DATE = /^\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?Z)?$/;
const SHA256 = /^sha256:[a-f0-9]{64}$/i;

/** @typedef {{path: string, code: string, message: string}} ContractIssue */

function isObject(value) {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function cleanString(value) {
  return typeof value === "string" ? value.trim() : "";
}

function cleanStringArray(value) {
  return Array.isArray(value) ? [...new Set(value.map(cleanString).filter(Boolean))] : [];
}

function issue(path, code, message) {
  return { path, code, message };
}

function isValidId(value) {
  return ID_PATTERN.test(cleanString(value));
}

function isIsoDate(value) {
  const text = cleanString(value);
  return Boolean(text && ISO_DATE.test(text) && Number.isFinite(Date.parse(text)));
}

function isSafeHttpsUrl(value) {
  try {
    return new URL(String(value)).protocol === "https:";
  } catch (_) {
    return false;
  }
}

function isSafeLocalUrl(value) {
  const text = cleanString(value);
  if (!text || text.startsWith("//") || /^[a-z][a-z\d+.-]*:/i.test(text)) return false;
  return !text.split(/[?#]/, 1)[0].split("/").includes("..");
}

/** Public images may be same-origin or explicitly rights-cleared HTTPS assets. */
export function isAllowedJourneyImageUrl(value) {
  return isSafeLocalUrl(value) || isSafeHttpsUrl(value);
}

export function isSafeJourneyManifestRef(value) {
  const text = cleanString(value);
  if (!isSafeLocalUrl(text)) return false;
  try {
    const url = new URL(text, "https://shelfsignals.invalid/");
    return url.origin === "https://shelfsignals.invalid" && /\.json$/i.test(url.pathname);
  } catch (_) {
    return false;
  }
}

function enumValue(value, allowed, fallback = "") {
  const candidate = cleanString(value);
  return allowed.includes(candidate) ? candidate : fallback;
}

function catalogIdSet(value) {
  if (value instanceof Set) return new Set([...value].map(String));
  return new Set(Array.isArray(value) ? value.filter(Boolean).map(String) : []);
}

function rejectedJourneyIndex(errors, warnings = []) {
  return {
    schema: JOURNEY_INDEX_SCHEMA,
    generated_at: null,
    journeys: [],
    rejected: true,
    errors,
    warnings
  };
}

/** Parse the small public index. Draft journeys are omitted, not advertised. */
export function parseJourneyIndex(raw = {}) {
  if (!isObject(raw) || raw.schema !== JOURNEY_INDEX_SCHEMA) {
    return rejectedJourneyIndex([issue("schema", "unsupported_schema", `Expected ${JOURNEY_INDEX_SCHEMA}.`)]);
  }
  if (!Array.isArray(raw.journeys)) {
    return rejectedJourneyIndex([issue("journeys", "invalid_journeys", "Journey index must contain an array.")]);
  }

  const errors = [];
  const warnings = [];
  const journeys = [];
  const seen = new Set();
  raw.journeys.forEach((entry, index) => {
    const path = `journeys.${index}`;
    if (!isObject(entry) || !isValidId(entry.id)) {
      errors.push(issue(path, "invalid_journey", "Journey index entry needs a stable lowercase ID."));
      return;
    }
    if (seen.has(entry.id)) {
      errors.push(issue(`${path}.id`, "duplicate_id", "Journey IDs must be unique."));
      return;
    }
    seen.add(entry.id);
    const status = enumValue(entry.publication_status || entry.status, PUBLICATION_STATUSES);
    if (status !== "published") {
      warnings.push(issue(path, "unpublished_journey_omitted", "Only published journeys appear in the public index."));
      return;
    }
    const title = cleanString(entry.title);
    const manifestRef = cleanString(entry.manifest_ref || entry.manifest_url);
    if (!title) errors.push(issue(`${path}.title`, "missing_title", "Published journey needs a title."));
    if (!isSafeJourneyManifestRef(manifestRef)) errors.push(issue(`${path}.manifest_ref`, "unsafe_manifest_ref", "Journey manifest must be a same-origin JSON path."));
    if (!title || !isSafeJourneyManifestRef(manifestRef)) return;
    journeys.push({
      id: entry.id,
      publication_status: "published",
      title,
      subtitle: cleanString(entry.subtitle),
      manifest_ref: manifestRef,
      cluster_count: Math.max(0, Number.parseInt(entry.cluster_count, 10) || 0),
      association_count: Math.max(0, Number.parseInt(entry.association_count, 10) || 0)
    });
  });

  if (errors.length) return rejectedJourneyIndex(errors, warnings);
  return {
    schema: JOURNEY_INDEX_SCHEMA,
    generated_at: isIsoDate(raw.generated_at) ? raw.generated_at : null,
    journeys,
    rejected: false,
    errors: [],
    warnings
  };
}

function normalizeCitation(raw, path, errors) {
  if (!isObject(raw) || !isValidId(raw.id)) {
    errors.push(issue(path, "invalid_citation", "Citation needs a stable ID."));
    return null;
  }
  const title = cleanString(raw.title);
  const locator = cleanString(raw.locator);
  const url = cleanString(raw.url || raw.source_url);
  if (!title) errors.push(issue(`${path}.title`, "missing_title", "Citation needs a title."));
  if (!locator) errors.push(issue(`${path}.locator`, "missing_locator", "Citation needs a precise page, box, folder, item, or section locator."));
  if (url && !isSafeHttpsUrl(url)) errors.push(issue(`${path}.url`, "unsafe_url", "Citation URL must use HTTPS."));
  if (!title || !locator || (url && !isSafeHttpsUrl(url))) return null;
  return {
    id: raw.id,
    kind: cleanString(raw.kind || raw.type) || "source",
    title,
    creator: cleanString(raw.creator),
    publisher: cleanString(raw.publisher || raw.repository),
    date: cleanString(raw.date),
    locator,
    url
  };
}

function normalizeTargetWork(raw, path, errors) {
  if (!isObject(raw) || !isValidId(raw.id)) {
    errors.push(issue(path, "invalid_target_work", "Target work needs a stable ID."));
    return null;
  }
  const title = cleanString(raw.title);
  if (!title) {
    errors.push(issue(`${path}.title`, "missing_title", "Target work needs a title."));
    return null;
  }
  return {
    id: raw.id,
    title,
    date: cleanString(raw.date),
    type: cleanString(raw.type) || "work"
  };
}

function normalizePhotoRights(raw) {
  const rights = isObject(raw) ? raw : {};
  const basis = enumValue(rights.basis || rights.status, PHOTO_RIGHTS_BASES, "unknown");
  return {
    public_display: rights.public_display === true || rights.display === "allowed",
    basis,
    credit_line: cleanString(rights.credit_line),
    rights_holder: cleanString(rights.rights_holder),
    derivatives_allowed: rights.derivatives_allowed === true || rights.derivatives === "allowed",
    license_url: isSafeHttpsUrl(rights.license_url) ? cleanString(rights.license_url) : ""
  };
}

function normalizePhotoImage(raw) {
  if (!isObject(raw)) return null;
  const url = cleanString(raw.url || raw.image_url);
  const thumbnailUrl = cleanString(raw.thumbnail_url || raw.thumbnail || url);
  const width = Number(raw.width);
  const height = Number(raw.height);
  const derivative = isObject(raw.derivative) ? raw.derivative : {};
  const sourceDimensions = Array.isArray(derivative.source_dimensions)
    && derivative.source_dimensions.length === 2
    && derivative.source_dimensions.every(value => Number.isInteger(value) && value > 0)
    ? [...derivative.source_dimensions]
    : [];
  if (!url && !thumbnailUrl) return null;
  return {
    url: url || thumbnailUrl,
    thumbnail_url: thumbnailUrl || url,
    width: Number.isInteger(width) && width > 0 ? width : 0,
    height: Number.isInteger(height) && height > 0 ? height : 0,
    sha256: SHA256.test(cleanString(raw.sha256)) ? cleanString(raw.sha256).toLowerCase() : "",
    thumbnail_sha256: SHA256.test(cleanString(raw.thumbnail_sha256)) ? cleanString(raw.thumbnail_sha256).toLowerCase() : "",
    retrieved_at: isIsoDate(raw.retrieved_at) ? cleanString(raw.retrieved_at) : "",
    derivative: {
      source_dimensions: sourceDimensions,
      transform: cleanString(derivative.transform),
      tooling: cleanString(derivative.tooling),
      reproducibility_status: cleanString(derivative.reproducibility_status)
    }
  };
}

function normalizePhotograph(raw, path, citationIds, errors, warnings) {
  if (!isObject(raw) || !isValidId(raw.id)) {
    errors.push(issue(path, "invalid_photograph", "Photograph needs a stable ID."));
    return null;
  }
  const title = cleanString(raw.title);
  const caption = cleanString(raw.caption);
  const alt = cleanString(raw.alt);
  const citationId = cleanString(raw.source_citation_id || raw.citation_id);
  if (!title) errors.push(issue(`${path}.title`, "missing_title", "Photograph needs a title or archival description."));
  if (!caption) errors.push(issue(`${path}.caption`, "missing_caption", "Photograph needs a caption."));
  if (!alt) errors.push(issue(`${path}.alt`, "missing_alt", "Photograph needs alternative text."));
  if (!citationIds.has(citationId)) errors.push(issue(`${path}.source_citation_id`, "unknown_citation", "Photograph must reference a valid provenance citation."));

  const rights = normalizePhotoRights(raw.rights);
  const image = normalizePhotoImage(raw.image);
  const rightsPermitDisplay = rights.public_display && !["pending", "unknown"].includes(rights.basis);
  let displayImage = image;
  if (image && !rightsPermitDisplay) {
    displayImage = null;
    warnings.push(issue(`${path}.image`, "rights_gated", "Image URL was removed because public-display rights are unresolved."));
  }
  if (displayImage) {
    if (!displayImage.width || !displayImage.height) errors.push(issue(`${path}.image`, "missing_dimensions", "Displayed photograph needs positive pixel dimensions."));
    if (!isAllowedJourneyImageUrl(displayImage.url) || !isAllowedJourneyImageUrl(displayImage.thumbnail_url)) errors.push(issue(`${path}.image`, "unsafe_url", "Photograph URL must be same-origin or HTTPS."));
    if (!rights.credit_line) errors.push(issue(`${path}.rights.credit_line`, "missing_credit", "Displayed photograph needs its credit line."));
    if (isSafeLocalUrl(displayImage.url)) {
      if (!rights.derivatives_allowed) errors.push(issue(`${path}.rights`, "uncleared_derivative", "Locally served photograph needs derivative permission."));
      if (!displayImage.sha256 || !displayImage.thumbnail_sha256) errors.push(issue(`${path}.image`, "missing_derivative_checksum", "Locally served photograph and thumbnail need SHA-256 checksums."));
      if (!displayImage.retrieved_at) errors.push(issue(`${path}.image`, "missing_retrieval_date", "Locally served photograph needs a source retrieval date."));
      if (!displayImage.derivative.source_dimensions.length || !displayImage.derivative.transform || !displayImage.derivative.reproducibility_status) {
        errors.push(issue(`${path}.image.derivative`, "missing_derivative_recipe", "Locally served photograph needs source dimensions, a resize recipe, and reproducibility status."));
      }
    }
  }
  if (!title || !caption || !alt || !citationIds.has(citationId)) return null;
  return {
    id: raw.id,
    title,
    date: cleanString(raw.date),
    caption,
    alt,
    source_citation_id: citationId,
    image: displayImage,
    display_status: displayImage ? "cleared" : "metadata_only",
    rights
  };
}

function normalizeReview(raw) {
  const review = isObject(raw) ? raw : {};
  return {
    status: cleanString(review.status),
    reviewer: cleanString(review.reviewer),
    reviewed_at: cleanString(review.reviewed_at)
  };
}

function associationHasCoreApproval(association) {
  return association?.review?.status === "approved"
    && Boolean(cleanString(association.review.reviewer))
    && isIsoDate(association.review.reviewed_at)
    && Boolean(cleanString(association.reasoning))
    && Array.isArray(association.citation_ids)
    && association.citation_ids.length > 0;
}

/** Only explicitly documented, approved primary/archival claims may use influence language. */
export function canClaimInfluence(association = {}) {
  return association.claim_kind === "documented_influence"
    && INFLUENCE_EVIDENCE.has(association.evidence_grade)
    && associationHasCoreApproval(association);
}

/** Safe, controlled UI wording; no generic phase is labeled "inspiration." */
export function associationClaimLabel(association = {}) {
  if (canClaimInfluence(association)) return "Documented influence";
  const labels = {
    identity_anchor: "Work represented in the library",
    documented_research_use: "Documented research use",
    documented_alignment: "Direct alignment",
    documented_post_reflection: "Post-project reflection",
    contextual_proximity: "Contextual proximity"
  };
  return labels[association.claim_kind] || "Contextual relationship";
}

function normalizeAssociation(raw, path, context, errors) {
  if (!isObject(raw) || !isValidId(raw.id)) {
    errors.push(issue(path, "invalid_association", "Association needs a stable ID."));
    return null;
  }
  const catalogId = cleanString(raw.catalog_id);
  const phase = enumValue(raw.phase, JOURNEY_PHASES);
  const requestedClaim = raw.claim_kind || (raw.association_kind === "identity" ? "identity_anchor" : "");
  const claimKind = enumValue(requestedClaim, JOURNEY_CLAIM_KINDS);
  const evidenceGrade = enumValue(raw.evidence_grade, JOURNEY_EVIDENCE_GRADES);
  const citationIds = cleanStringArray(raw.citation_ids);
  const review = normalizeReview(raw.review);
  const reasoning = cleanString(raw.reasoning);
  const clusterId = cleanString(raw.cluster_id);
  const targetWorkId = cleanString(raw.target_work_id);
  const journeyId = cleanString(raw.journey_id);

  if (!catalogId || (context.catalogIds.size && !context.catalogIds.has(catalogId))) errors.push(issue(`${path}.catalog_id`, "unknown_catalog_id", "Association must reference a real catalog record."));
  if (journeyId !== context.journeyId) errors.push(issue(`${path}.journey_id`, "journey_mismatch", "Association journey ID must match its manifest."));
  if (!context.clusterIds.has(clusterId)) errors.push(issue(`${path}.cluster_id`, "unknown_cluster", "Association must reference a journey cluster."));
  if (!context.targetWorkIds.has(targetWorkId)) errors.push(issue(`${path}.target_work_id`, "unknown_target_work", "Association must reference a target work."));
  if (!phase) errors.push(issue(`${path}.phase`, "invalid_phase", "Association phase is not recognized."));
  if (!claimKind) errors.push(issue(`${path}.claim_kind`, "invalid_claim_kind", "Association claim kind is not recognized."));
  if (!evidenceGrade) errors.push(issue(`${path}.evidence_grade`, "invalid_evidence_grade", "Association evidence grade is not recognized."));
  if (!reasoning) errors.push(issue(`${path}.reasoning`, "missing_reasoning", "Association needs concise editorial reasoning."));
  if (!citationIds.length || citationIds.some(id => !context.citationIds.has(id))) errors.push(issue(`${path}.citation_ids`, "invalid_citations", "Association needs valid, precisely located citations."));
  if (!associationHasCoreApproval({ review, reasoning, citation_ids: citationIds })) errors.push(issue(`${path}.review`, "not_approved", "Published association needs a reviewer and review date."));

  const association = {
    id: raw.id,
    catalog_id: catalogId,
    journey_id: journeyId,
    cluster_id: clusterId,
    phase,
    target_work_id: targetWorkId,
    reasoning,
    evidence_grade: evidenceGrade,
    claim_kind: claimKind,
    citation_ids: citationIds,
    review
  };
  if (claimKind === "documented_influence" && !canClaimInfluence(association)) {
    errors.push(issue(`${path}.claim_kind`, "unsupported_influence_claim", "Influence claims require approved primary or archival evidence."));
  }
  return association;
}

/** Defensive publication filter for callers handling editorial fixtures. */
export function getPublicAssociations(manifest = {}) {
  if (manifest.publication_status !== "published" || !Array.isArray(manifest.associations)) return [];
  return manifest.associations.filter(association => {
    if (!associationHasCoreApproval(association)) return false;
    if (!JOURNEY_PHASES.includes(association.phase)) return false;
    if (!JOURNEY_CLAIM_KINDS.includes(association.claim_kind)) return false;
    if (!JOURNEY_EVIDENCE_GRADES.includes(association.evidence_grade)) return false;
    return association.claim_kind !== "documented_influence" || canClaimInfluence(association);
  });
}

function normalizeCluster(raw, path, context, errors) {
  if (!isObject(raw) || !isValidId(raw.id)) {
    errors.push(issue(path, "invalid_cluster", "Cluster needs a stable ID."));
    return null;
  }
  const order = Number(raw.order);
  const title = cleanString(raw.title);
  const narrative = cleanString(raw.narrative);
  const photographIds = cleanStringArray(raw.photograph_ids);
  const associationIds = cleanStringArray(raw.association_ids);
  if (!Number.isInteger(order) || order < 1) errors.push(issue(`${path}.order`, "invalid_order", "Cluster order must be a positive integer."));
  if (!title) errors.push(issue(`${path}.title`, "missing_title", "Cluster needs a title."));
  if (!narrative) errors.push(issue(`${path}.narrative`, "missing_narrative", "Cluster needs an evidence-conscious narrative."));
  if (!photographIds.length || photographIds.some(id => !context.photographIds.has(id))) errors.push(issue(`${path}.photograph_ids`, "invalid_photographs", "Cluster needs valid photograph records."));
  if (associationIds.some(id => !context.associationIds.has(id))) errors.push(issue(`${path}.association_ids`, "invalid_associations", "Cluster references an unavailable association."));
  if (!title || !narrative || !photographIds.length) return null;
  return {
    id: raw.id,
    order,
    title,
    period_label: cleanString(raw.period_label),
    narrative,
    shelf_label: cleanString(raw.shelf_label) || "Books in this cluster",
    photograph_ids: photographIds,
    association_ids: associationIds
  };
}

function rejectedJourneyManifest(errors, warnings = []) {
  return {
    schema: JOURNEY_MANIFEST_SCHEMA,
    id: "",
    publication_status: "draft",
    title: "",
    target_works: [],
    citations: [],
    photographs: [],
    clusters: [],
    associations: [],
    editorial: null,
    rejected: true,
    errors,
    warnings
  };
}

/** Parse and cross-check a complete journey manifest. */
export function parseJourneyManifest(raw = {}, { catalogIds = [] } = {}) {
  if (!isObject(raw) || raw.schema !== JOURNEY_MANIFEST_SCHEMA) {
    return rejectedJourneyManifest([issue("schema", "unsupported_schema", `Expected ${JOURNEY_MANIFEST_SCHEMA}.`)]);
  }
  const errors = [];
  const warnings = [];
  const journeyId = cleanString(raw.id);
  const publicationStatus = enumValue(raw.publication_status || raw.status, PUBLICATION_STATUSES);
  const title = cleanString(raw.title);
  if (!isValidId(journeyId)) errors.push(issue("id", "invalid_id", "Journey needs a stable lowercase ID."));
  if (!publicationStatus) errors.push(issue("publication_status", "invalid_status", "Journey status must be draft or published."));
  if (!title) errors.push(issue("title", "missing_title", "Journey needs a title."));
  for (const field of ["target_works", "citations", "photographs", "clusters", "associations"]) {
    if (!Array.isArray(raw[field])) errors.push(issue(field, "invalid_array", `${field} must be an array.`));
  }
  if (errors.length) return rejectedJourneyManifest(errors, warnings);

  function normalizeUnique(values, name, normalizer) {
    const output = [];
    const seen = new Set();
    values.forEach((value, index) => {
      const normalized = normalizer(value, `${name}.${index}`);
      if (!normalized) return;
      if (seen.has(normalized.id)) errors.push(issue(`${name}.${index}.id`, "duplicate_id", `${name} IDs must be unique.`));
      else {
        seen.add(normalized.id);
        output.push(normalized);
      }
    });
    return output;
  }

  const citations = normalizeUnique(raw.citations, "citations", (value, path) => normalizeCitation(value, path, errors));
  const citationIds = new Set(citations.map(value => value.id));
  const targetWorks = normalizeUnique(raw.target_works, "target_works", (value, path) => normalizeTargetWork(value, path, errors));
  const targetWorkIds = new Set(targetWorks.map(value => value.id));
  const rawClusterIds = new Set(raw.clusters.filter(isObject).map(cluster => cleanString(cluster.id)).filter(isValidId));
  const photographs = normalizeUnique(raw.photographs, "photographs", (value, path) => normalizePhotograph(value, path, citationIds, errors, warnings));
  const photographIds = new Set(photographs.map(value => value.id));

  const context = {
    catalogIds: catalogIdSet(catalogIds),
    journeyId,
    clusterIds: rawClusterIds,
    targetWorkIds,
    citationIds
  };
  const associations = [];
  const associationIds = new Set();
  raw.associations.forEach((value, index) => {
    const path = `associations.${index}`;
    const reviewStatus = cleanString(value?.review?.status);
    if (reviewStatus !== "approved") {
      const problem = issue(`${path}.review`, "unpublished_association", "Unapproved association cannot enter a public journey manifest.");
      if (publicationStatus === "published") errors.push(problem);
      else warnings.push(problem);
      return;
    }
    const association = normalizeAssociation(value, path, context, errors);
    if (!association) return;
    if (associationIds.has(association.id)) errors.push(issue(`${path}.id`, "duplicate_id", "Association IDs must be unique."));
    else {
      associationIds.add(association.id);
      associations.push(association);
    }
  });

  const clusters = normalizeUnique(raw.clusters, "clusters", (value, path) => normalizeCluster(value, path, {
    photographIds,
    associationIds
  }, errors));
  const orders = clusters.map(cluster => cluster.order).sort((left, right) => left - right);
  if (new Set(orders).size !== orders.length || orders.some((order, index) => order !== index + 1)) {
    errors.push(issue("clusters", "noncontiguous_order", "Cluster order must be unique and contiguous from 1."));
  }

  const editorialRaw = isObject(raw.editorial) ? raw.editorial : {};
  const editorial = {
    editor: cleanString(editorialRaw.editor || editorialRaw.reviewer),
    reviewed_at: cleanString(editorialRaw.reviewed_at),
    version: cleanString(editorialRaw.version) || "1.0.0"
  };
  if (publicationStatus === "published" && (!editorial.editor || !isIsoDate(editorial.reviewed_at))) {
    errors.push(issue("editorial", "missing_editorial_review", "Published journey needs an editor and ISO review date."));
  }
  if (!targetWorks.length) errors.push(issue("target_works", "empty_target_works", "Journey needs at least one target work."));
  if (!citations.length) errors.push(issue("citations", "empty_citations", "Journey needs cited evidence."));
  if (!photographs.length) errors.push(issue("photographs", "empty_photographs", "Journey needs at least one photograph record."));
  if (!clusters.length) errors.push(issue("clusters", "empty_clusters", "Journey needs at least one cluster."));
  if (errors.length) return rejectedJourneyManifest(errors, warnings);

  const manifest = {
    schema: JOURNEY_MANIFEST_SCHEMA,
    id: journeyId,
    publication_status: publicationStatus,
    title,
    subtitle: cleanString(raw.subtitle),
    introduction: cleanString(raw.introduction),
    target_works: targetWorks,
    citations,
    photographs,
    clusters,
    associations,
    editorial,
    rejected: false,
    errors: [],
    warnings
  };
  manifest.associations = getPublicAssociations(manifest);
  return manifest;
}

export function journeyById(index = {}, id = "") {
  return Array.isArray(index.journeys) ? index.journeys.find(journey => journey.id === id) || null : null;
}

export function clusterById(manifest = {}, id = "") {
  return Array.isArray(manifest.clusters) ? manifest.clusters.find(cluster => cluster.id === id) || null : null;
}
