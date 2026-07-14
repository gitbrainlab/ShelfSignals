/**
 * Local-only evidence review for ShelfSignals.
 *
 * This module deliberately has no network or persistence adapter. Candidate
 * data enters through a user-selected File and leaves only through a download.
 */

export const REVIEW_QUEUE_SCHEMA = "shelfsignals-association-review-queue@1";
export const REVIEW_EXPORT_SCHEMA = "shelfsignals-association-review-export@1";
export const COVER_REVIEW_QUEUE_SCHEMA = "shelfsignals-cover-review-queue@1";
export const COVER_REVIEWS_SCHEMA = "shelfsignals-cover-reviews@1";
export const REVIEW_DECISIONS = Object.freeze(["approve", "reject", "needs_work"]);
export const COVER_LEDGER_DECISIONS = Object.freeze(["approve", "reject", "defer"]);

const MAX_FILE_BYTES = 32 * 1024 * 1024;
const MAX_CANDIDATES = 5000;
const MAX_COVER_RECORDS = 20_000;
const MAX_COVER_CANDIDATES = 25_000;
const COVER_RENDER_BATCH = 120;
const MAX_REASON_LENGTH = 4000;
const MIN_COVER_EVIDENCE_LENGTH = 12;
const MAX_COVER_VALIDATION_ERRORS = 50;
const OPEN_LIBRARY_DISCOVERY_METHOD = "monthly_editions_dump_exact_isbn_join";
const OPEN_LIBRARY_DOCUMENT_PATHS = Object.freeze({
  cover_documentation: "/dev/docs/api/covers",
  dump_documentation: "/developers/dumps",
  licensing: "/developers/licensing"
});
const SHA256_CONSTANTS = Object.freeze([
  0x428a2f98, 0x71374491, 0xb5c0fbcf, 0xe9b5dba5, 0x3956c25b, 0x59f111f1, 0x923f82a4, 0xab1c5ed5,
  0xd807aa98, 0x12835b01, 0x243185be, 0x550c7dc3, 0x72be5d74, 0x80deb1fe, 0x9bdc06a7, 0xc19bf174,
  0xe49b69c1, 0xefbe4786, 0x0fc19dc6, 0x240ca1cc, 0x2de92c6f, 0x4a7484aa, 0x5cb0a9dc, 0x76f988da,
  0x983e5152, 0xa831c66d, 0xb00327c8, 0xbf597fc7, 0xc6e00bf3, 0xd5a79147, 0x06ca6351, 0x14292967,
  0x27b70a85, 0x2e1b2138, 0x4d2c6dfc, 0x53380d13, 0x650a7354, 0x766a0abb, 0x81c2c92e, 0x92722c85,
  0xa2bfe8a1, 0xa81a664b, 0xc24b8b70, 0xc76c51a3, 0xd192e819, 0xd6990624, 0xf40e3585, 0x106aa070,
  0x19a4c116, 0x1e376c08, 0x2748774c, 0x34b0bcb5, 0x391c0cb3, 0x4ed8aa4a, 0x5b9cca4f, 0x682e6ff3,
  0x748f82ee, 0x78a5636f, 0x84c87814, 0x8cc70208, 0x90befffa, 0xa4506ceb, 0xbef9a3f7, 0xc67178f2
]);
const HAS_OWN = (object, key) => Object.prototype.hasOwnProperty.call(object, key);

function isPlainObject(value) {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const prototype = Object.getPrototypeOf(value);
  return prototype === Object.prototype || prototype === null;
}

function nonemptyString(value, maximum = 500) {
  return typeof value === "string" && value.trim().length > 0 && value.length <= maximum;
}

function validIsoDate(value) {
  if (!/^\d{4}-\d{2}-\d{2}$/.test(value || "")) return false;
  const parsed = new Date(`${value}T00:00:00Z`);
  return Number.isFinite(parsed.valueOf()) && parsed.toISOString().slice(0, 10) === value;
}

export function currentUtcTimestamp() {
  return new Date().toISOString().replace(/\.\d{3}Z$/, "Z");
}

function validUtcTimestamp(value) {
  if (!/^20\d{2}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$/.test(value || "")) return false;
  const parsed = new Date(value);
  return Number.isFinite(parsed.valueOf()) && parsed.toISOString().replace(/\.000Z$/, "Z") === value;
}

function canonicalJson(value) {
  if (value === null || typeof value === "boolean" || typeof value === "number" || typeof value === "string") {
    return JSON.stringify(value);
  }
  if (Array.isArray(value)) return `[${value.map(canonicalJson).join(",")}]`;
  if (isPlainObject(value)) {
    return `{${Object.keys(value).sort().map(key => `${JSON.stringify(key)}:${canonicalJson(value[key])}`).join(",")}}`;
  }
  throw new TypeError("Canonical JSON supports only JSON values.");
}

function rotateRight(value, amount) {
  return (value >>> amount) | (value << (32 - amount));
}

function sha256Hex(value) {
  const bytes = new TextEncoder().encode(value);
  const paddedLength = Math.ceil((bytes.length + 9) / 64) * 64;
  const padded = new Uint8Array(paddedLength);
  padded.set(bytes);
  padded[bytes.length] = 0x80;
  const view = new DataView(padded.buffer);
  const bitLength = BigInt(bytes.length) * 8n;
  view.setUint32(paddedLength - 8, Number((bitLength >> 32n) & 0xffffffffn), false);
  view.setUint32(paddedLength - 4, Number(bitLength & 0xffffffffn), false);

  const hash = new Uint32Array([
    0x6a09e667, 0xbb67ae85, 0x3c6ef372, 0xa54ff53a,
    0x510e527f, 0x9b05688c, 0x1f83d9ab, 0x5be0cd19
  ]);
  const words = new Uint32Array(64);
  for (let offset = 0; offset < paddedLength; offset += 64) {
    for (let index = 0; index < 16; index += 1) words[index] = view.getUint32(offset + index * 4, false);
    for (let index = 16; index < 64; index += 1) {
      const a = words[index - 15];
      const b = words[index - 2];
      const sigma0 = rotateRight(a, 7) ^ rotateRight(a, 18) ^ (a >>> 3);
      const sigma1 = rotateRight(b, 17) ^ rotateRight(b, 19) ^ (b >>> 10);
      words[index] = (words[index - 16] + sigma0 + words[index - 7] + sigma1) >>> 0;
    }
    let [a, b, c, d, e, f, g, h] = hash;
    for (let index = 0; index < 64; index += 1) {
      const sum1 = rotateRight(e, 6) ^ rotateRight(e, 11) ^ rotateRight(e, 25);
      const choice = (e & f) ^ (~e & g);
      const temp1 = (h + sum1 + choice + SHA256_CONSTANTS[index] + words[index]) >>> 0;
      const sum0 = rotateRight(a, 2) ^ rotateRight(a, 13) ^ rotateRight(a, 22);
      const majority = (a & b) ^ (a & c) ^ (b & c);
      const temp2 = (sum0 + majority) >>> 0;
      h = g; g = f; f = e; e = (d + temp1) >>> 0;
      d = c; c = b; b = a; a = (temp1 + temp2) >>> 0;
    }
    hash[0] = (hash[0] + a) >>> 0;
    hash[1] = (hash[1] + b) >>> 0;
    hash[2] = (hash[2] + c) >>> 0;
    hash[3] = (hash[3] + d) >>> 0;
    hash[4] = (hash[4] + e) >>> 0;
    hash[5] = (hash[5] + f) >>> 0;
    hash[6] = (hash[6] + g) >>> 0;
    hash[7] = (hash[7] + h) >>> 0;
  }
  return [...hash].map(word => word.toString(16).padStart(8, "0")).join("");
}

function canonicalChecksum(value) {
  return `sha256:${sha256Hex(canonicalJson(value))}`;
}

export function coverCandidateFingerprint(recordId, catalog, candidate, providerDumpChecksum) {
  const catalogIsbns = [...new Set(Array.isArray(catalog?.normalized_isbns) ? catalog.normalized_isbns : [])].sort();
  const matchedIsbns = [...new Set(
    Array.isArray(candidate?.matched_identifiers)
      ? candidate.matched_identifiers.filter(item => item?.type === "isbn").map(item => item.value)
      : []
  )].sort();
  return canonicalChecksum({
    catalog_id: recordId,
    catalog_isbns: catalogIsbns,
    matched_isbns: matchedIsbns,
    provider: "openlibrary",
    provider_edition_id: candidate?.provider_edition_id,
    cover_id: candidate?.cover_id,
    provider_dump_checksum: providerDumpChecksum
  });
}

function validCanonicalIsbn13(value) {
  if (!/^\d{13}$/.test(value || "")) return false;
  const checksum = [...value].reduce((sum, digit, index) => sum + Number(digit) * (index % 2 ? 3 : 1), 0);
  return checksum % 10 === 0;
}

function validProviderUrl(value, hostname, pathname, requireDefaultFalse = false) {
  if (!nonemptyString(value, 2000)) return false;
  try {
    const parsed = new URL(value);
    if (
      parsed.protocol !== "https:" ||
      parsed.hostname !== hostname ||
      parsed.port || parsed.username || parsed.password || parsed.hash ||
      parsed.pathname !== pathname
    ) return false;
    if (!requireDefaultFalse) return parsed.search === "";
    return parsed.searchParams.get("default") === "false" && [...parsed.searchParams.keys()].length === 1;
  } catch {
    return false;
  }
}

function coverError(errors, message) {
  if (errors.length < MAX_COVER_VALIDATION_ERRORS) errors.push(message);
}

export function validateReviewQueue(value) {
  const errors = [];
  if (!isPlainObject(value)) {
    return { ok: false, errors: ["The imported JSON must be an object."], data: null };
  }
  if (value.schema !== REVIEW_QUEUE_SCHEMA) {
    errors.push(`schema must be ${REVIEW_QUEUE_SCHEMA}.`);
  }
  if (!Array.isArray(value.candidates)) {
    errors.push("candidates must be an array.");
    return { ok: false, errors, data: null };
  }
  if (value.candidates.length > MAX_CANDIDATES) {
    errors.push(`candidates exceeds the ${MAX_CANDIDATES.toLocaleString()}-record local review limit.`);
    return { ok: false, errors, data: null };
  }

  const seen = new Set();
  value.candidates.forEach((candidate, index) => {
    const at = `candidates[${index}]`;
    if (!isPlainObject(candidate)) {
      errors.push(`${at} must be an object.`);
      return;
    }
    if (!nonemptyString(candidate.candidate_id, 240)) {
      errors.push(`${at}.candidate_id must be a nonempty string of 240 characters or fewer.`);
    } else if (seen.has(candidate.candidate_id)) {
      errors.push(`${at}.candidate_id duplicates ${candidate.candidate_id}.`);
    } else {
      seen.add(candidate.candidate_id);
    }
    if (candidate.publication_status !== "unpublished") {
      errors.push(`${at}.publication_status must be "unpublished".`);
    }
    if (!HAS_OWN(candidate, "reviewer") || candidate.reviewer !== null) {
      errors.push(`${at}.reviewer must be present and null before review.`);
    }
    if (!HAS_OWN(candidate, "reviewed_at") || candidate.reviewed_at !== null) {
      errors.push(`${at}.reviewed_at must be present and null before review.`);
    }
    if (HAS_OWN(candidate, "review_decision") && candidate.review_decision !== null) {
      errors.push(`${at}.review_decision must be absent or null before review.`);
    }
    if (HAS_OWN(candidate, "review_reason") && candidate.review_reason !== null) {
      errors.push(`${at}.review_reason must be absent or null before review.`);
    }
  });

  return { ok: errors.length === 0, errors, data: errors.length ? null : value };
}

export function validateCoverReviewQueue(value) {
  const errors = [];
  const reviewItems = [];
  if (!isPlainObject(value)) {
    return { ok: false, errors: ["The imported JSON must be an object."], data: null, reviewItems };
  }
  if (value.schema !== COVER_REVIEW_QUEUE_SCHEMA) {
    coverError(errors, `schema must be ${COVER_REVIEW_QUEUE_SCHEMA}.`);
  }
  if (!isPlainObject(value.items)) {
    coverError(errors, "items must be an object keyed by Clark catalog ID.");
    return { ok: false, errors, data: null, reviewItems };
  }
  if (!isPlainObject(value.inputs)) {
    coverError(errors, "inputs must preserve the queue's catalog and provider provenance.");
  } else {
    if (!validIsoDate(value.inputs.provider_snapshot)) {
      coverError(errors, "inputs.provider_snapshot must be an ISO snapshot date.");
    }
    if (!/^(?:md5:[a-f0-9]{32}|sha256:[a-f0-9]{64})$/.test(value.inputs.provider_dump_checksum || "")) {
      coverError(errors, "inputs.provider_dump_checksum must be a provider dump checksum.");
    }
    for (const field of ["catalog_sha256", "editions_sha256"]) {
      if (!/^sha256:[a-f0-9]{64}$/.test(value.inputs[field] || "")) {
        coverError(errors, `inputs.${field} must preserve the source-file checksum.`);
      }
    }
  }
  if (!isPlainObject(value.provider)) {
    coverError(errors, "provider must document the external source and terms.");
  } else {
    if (value.provider.name !== "Open Library") coverError(errors, "provider.name must be Open Library for this queue schema.");
    if (value.provider.discovery_method !== OPEN_LIBRARY_DISCOVERY_METHOD) {
      coverError(errors, `provider.discovery_method must be ${OPEN_LIBRARY_DISCOVERY_METHOD}.`);
    }
    for (const [field, pathname] of Object.entries(OPEN_LIBRARY_DOCUMENT_PATHS)) {
      if (!validProviderUrl(value.provider[field], "openlibrary.org", pathname)) {
        coverError(errors, `provider.${field} must be the documented Open Library source URL.`);
      }
    }
  }

  const records = Object.entries(value.items);
  if (records.length > MAX_COVER_RECORDS) {
    coverError(errors, `items exceeds the ${MAX_COVER_RECORDS.toLocaleString()}-record local review limit.`);
    return { ok: false, errors, data: null, reviewItems };
  }

  const seen = new Set();
  let candidateCount = 0;
  for (const [recordId, item] of records) {
    const at = `items[${JSON.stringify(recordId)}]`;
    if (!nonemptyString(recordId, 240)) {
      coverError(errors, `${at} has an invalid Clark catalog ID.`);
      continue;
    }
    if (!isPlainObject(item)) {
      coverError(errors, `${at} must be an object.`);
      continue;
    }
    const catalog = item.catalog;
    if (!isPlainObject(catalog)) {
      coverError(errors, `${at}.catalog must be an object.`);
      continue;
    }
    if (!nonemptyString(catalog.title, 4000)) coverError(errors, `${at}.catalog.title must be supplied.`);
    if (!Array.isArray(catalog.normalized_isbns) || !catalog.normalized_isbns.every(validCanonicalIsbn13)) {
      coverError(errors, `${at}.catalog.normalized_isbns must contain only canonical ISBN-13 values.`);
    }
    if (!Array.isArray(item.candidates)) {
      coverError(errors, `${at}.candidates must be an array.`);
      continue;
    }
    candidateCount += item.candidates.length;
    if (candidateCount > MAX_COVER_CANDIDATES) {
      coverError(errors, `Cover candidates exceed the ${MAX_COVER_CANDIDATES.toLocaleString()}-candidate local review limit.`);
      break;
    }

    const catalogIsbns = new Set(Array.isArray(catalog.normalized_isbns) ? catalog.normalized_isbns : []);
    item.candidates.forEach((candidate, index) => {
      const candidateAt = `${at}.candidates[${index}]`;
      const errorCountBefore = errors.length;
      if (!isPlainObject(candidate)) {
        coverError(errors, `${candidateAt} must be an object.`);
        return;
      }
      if (!nonemptyString(candidate.candidate_key, 500)) {
        coverError(errors, `${candidateAt}.candidate_key must be supplied.`);
      } else if (seen.has(candidate.candidate_key)) {
        coverError(errors, `${candidateAt}.candidate_key duplicates ${candidate.candidate_key}.`);
      } else {
        seen.add(candidate.candidate_key);
      }
      if (!/^sha256:[a-f0-9]{64}$/.test(candidate.candidate_fingerprint || "")) {
        coverError(errors, `${candidateAt}.candidate_fingerprint must be a SHA-256 fingerprint.`);
      }
      if (candidate.provider !== "openlibrary") coverError(errors, `${candidateAt}.provider must be openlibrary.`);
      if (candidate.scope !== "external_exact_edition") coverError(errors, `${candidateAt}.scope must be external_exact_edition.`);
      if (!/^OL\d+M$/.test(candidate.provider_edition_id || "")) {
        coverError(errors, `${candidateAt}.provider_edition_id must be an Open Library edition ID.`);
      }
      if (!Number.isInteger(candidate.cover_id) || candidate.cover_id <= 0 || candidate.cover_id >= 1_000_000_000) {
        coverError(errors, `${candidateAt}.cover_id must be a positive provider Cover ID.`);
      }
      const expectedKey = `${recordId}:${candidate.provider_edition_id}:${candidate.cover_id}`;
      if (candidate.candidate_key !== expectedKey) {
        coverError(errors, `${candidateAt}.candidate_key does not agree with its catalog, edition, and Cover IDs.`);
      }
      if (!Array.isArray(candidate.matched_identifiers) || !candidate.matched_identifiers.length) {
        coverError(errors, `${candidateAt}.matched_identifiers must contain an exact ISBN.`);
      } else {
        for (const identifier of candidate.matched_identifiers) {
          if (
            !isPlainObject(identifier) || identifier.type !== "isbn" ||
            !validCanonicalIsbn13(identifier.value) || !catalogIsbns.has(identifier.value)
          ) {
            coverError(errors, `${candidateAt}.matched_identifiers must be exact canonical ISBNs present on the Clark record.`);
            break;
          }
        }
      }
      if (!validProviderUrl(candidate.source_url, "openlibrary.org", `/books/${candidate.provider_edition_id}`)) {
        coverError(errors, `${candidateAt}.source_url does not agree with the provider edition ID.`);
      }
      if (!validProviderUrl(candidate.thumbnail_url, "covers.openlibrary.org", `/b/id/${candidate.cover_id}-M.jpg`, true)) {
        coverError(errors, `${candidateAt}.thumbnail_url does not agree with the Cover ID.`);
      }
      if (!validProviderUrl(candidate.image_url, "covers.openlibrary.org", `/b/id/${candidate.cover_id}-L.jpg`, true)) {
        coverError(errors, `${candidateAt}.image_url does not agree with the Cover ID.`);
      }
      if (candidate.review_required !== true || candidate.public_eligible !== false) {
        coverError(errors, `${candidateAt} must remain review_required and not public_eligible.`);
      }
      if (HAS_OWN(candidate, "edition_summary") && !isPlainObject(candidate.edition_summary)) {
        coverError(errors, `${candidateAt}.edition_summary must be an object when supplied.`);
      }
      try {
        const expectedFingerprint = coverCandidateFingerprint(
          recordId,
          catalog,
          candidate,
          value.inputs?.provider_dump_checksum
        );
        if (candidate.candidate_fingerprint !== expectedFingerprint) {
          coverError(errors, `${candidateAt}.candidate_fingerprint does not match its exact queue evidence.`);
        }
      } catch {
        coverError(errors, `${candidateAt}.candidate_fingerprint could not be recomputed from the queue evidence.`);
      }

      if (errors.length === errorCountBefore) {
        const searchable = [
          recordId, catalog.title, catalog.authors, catalog.year, catalog.call_number,
          catalog.normalized_isbns, candidate.provider_edition_id, candidate.cover_id,
          candidate.matched_identifiers.map(identifier => identifier.value)
        ].flat(3).filter(valuePart => valuePart != null).join(" ").toLocaleLowerCase();
        reviewItems.push({
          recordId,
          catalog,
          queueItem: item,
          candidate,
          position: reviewItems.length,
          searchText: searchable
        });
      }
    });
  }

  if (isPlainObject(value.summary)) {
    if (Number.isInteger(value.summary.catalog_records) && value.summary.catalog_records !== records.length) {
      coverError(errors, "summary.catalog_records does not agree with items.");
    }
    if (Number.isInteger(value.summary.candidate_references) && value.summary.candidate_references !== candidateCount) {
      coverError(errors, "summary.candidate_references does not agree with the candidate count.");
    }
  }

  return {
    ok: errors.length === 0,
    errors,
    data: errors.length ? null : value,
    reviewItems: errors.length ? [] : reviewItems
  };
}

export function validateImportedQueue(value) {
  if (!isPlainObject(value)) {
    return { ok: false, errors: ["The imported JSON must be an object."], data: null, mode: null, reviewItems: [] };
  }
  if (value.schema === REVIEW_QUEUE_SCHEMA) {
    const result = validateReviewQueue(value);
    return { ...result, mode: "association", reviewItems: result.ok ? value.candidates : [] };
  }
  if (value.schema === COVER_REVIEW_QUEUE_SCHEMA) {
    return { ...validateCoverReviewQueue(value), mode: "cover" };
  }
  return {
    ok: false,
    errors: [`schema must be ${REVIEW_QUEUE_SCHEMA} or ${COVER_REVIEW_QUEUE_SCHEMA}.`],
    data: null,
    mode: null,
    reviewItems: []
  };
}

function decisionMap(value) {
  if (value instanceof Map) return value;
  return isPlainObject(value) ? new Map(Object.entries(value)) : new Map();
}

function coverReviewSignature(review) {
  return canonicalJson({
    candidate_fingerprint: review?.candidateFingerprint || "",
    decision: review?.decision || "",
    evidence_note: String(review?.reason || "").trim(),
    exact_edition_confirmed: review?.exactEditionConfirmed === true,
    visual_check: review?.visualCheck === true,
    rights_scope: review?.rightsScope || "remote_reference_only",
    reviewer: String(review?.reviewer || "").trim(),
    reviewed_at: review?.reviewedAt || ""
  });
}

export function validateCoverReviewsLedger(queue, value) {
  const queueValidation = validateCoverReviewQueue(queue);
  if (!queueValidation.ok) {
    return { ok: false, errors: queueValidation.errors, decisions: new Map() };
  }
  const errors = [];
  const decisions = new Map();
  if (!isPlainObject(value) || value.schema !== COVER_REVIEWS_SCHEMA) {
    return { ok: false, errors: [`The review ledger must use ${COVER_REVIEWS_SCHEMA}.`], decisions };
  }
  if (!isPlainObject(value.decisions)) {
    return { ok: false, errors: ["The review ledger must contain a decisions object."], decisions };
  }
  if (!isPlainObject(value.queue_inputs) || canonicalJson(value.queue_inputs) !== canonicalJson(queue.inputs)) {
    errors.push("The review ledger queue_inputs do not match the open cover queue.");
  }
  const entries = Object.entries(value.decisions);
  if (entries.length > MAX_COVER_CANDIDATES) {
    errors.push(`The review ledger exceeds the ${MAX_COVER_CANDIDATES.toLocaleString()}-decision local limit.`);
    return { ok: false, errors, decisions: new Map() };
  }

  const itemByKey = new Map(queueValidation.reviewItems.map(item => [item.candidate.candidate_key, item]));
  const approvedRecords = new Set();
  for (const [candidateKey, rawReview] of entries.sort(([left], [right]) => left.localeCompare(right))) {
    const item = itemByKey.get(candidateKey);
    if (!item) {
      errors.push(`The review ledger contains an unknown candidate_key: ${candidateKey}.`);
      continue;
    }
    if (!isPlainObject(rawReview)) {
      errors.push(`The review for ${candidateKey} must be an object.`);
      continue;
    }
    const decision = rawReview.decision;
    const reviewer = String(rawReview.reviewer || "").trim();
    const evidenceNote = String(rawReview.evidence_note || "").trim();
    if (rawReview.candidate_fingerprint !== item.candidate.candidate_fingerprint) {
      errors.push(`The review for ${candidateKey} has a stale or conflicting candidate_fingerprint.`);
    }
    if (!COVER_LEDGER_DECISIONS.includes(decision)) {
      errors.push(`The review for ${candidateKey} must use approve, reject, or defer.`);
    }
    if (!nonemptyString(reviewer, 200)) {
      errors.push(`The review for ${candidateKey} must name a reviewer.`);
    }
    if (!validUtcTimestamp(rawReview.reviewed_at)) {
      errors.push(`The review for ${candidateKey} must contain a valid 20xx UTC reviewed_at timestamp.`);
    }
    if (evidenceNote.length < MIN_COVER_EVIDENCE_LENGTH || evidenceNote.length > MAX_REASON_LENGTH) {
      errors.push(`The review for ${candidateKey} must contain a ${MIN_COVER_EVIDENCE_LENGTH}–${MAX_REASON_LENGTH.toLocaleString()} character evidence_note.`);
    }
    if (typeof rawReview.exact_edition_confirmed !== "boolean" || typeof rawReview.visual_check !== "boolean") {
      errors.push(`The review for ${candidateKey} must contain boolean edition and visual confirmations.`);
    }
    if (rawReview.rights_scope !== "remote_reference_only") {
      errors.push(`The review for ${candidateKey} has an unsafe rights_scope.`);
    }
    if (decision === "approve") {
      if (rawReview.exact_edition_confirmed !== true || rawReview.visual_check !== true) {
        errors.push(`The approval for ${candidateKey} is missing required confirmations.`);
      }
      if (approvedRecords.has(item.recordId)) {
        errors.push(`The review ledger approves more than one front cover for Clark record ${item.recordId}.`);
      }
      approvedRecords.add(item.recordId);
    }
    decisions.set(candidateKey, {
      candidateFingerprint: rawReview.candidate_fingerprint,
      decision: decision === "defer" ? "needs_work" : decision,
      reason: evidenceNote,
      exactEditionConfirmed: rawReview.exact_edition_confirmed === true,
      visualCheck: rawReview.visual_check === true,
      rightsScope: rawReview.rights_scope,
      reviewer,
      reviewedAt: rawReview.reviewed_at,
      imported: true,
      dirty: false
    });
  }
  return { ok: errors.length === 0, errors, decisions: errors.length ? new Map() : decisions };
}

export function mergeCoverReviewDecisions(existing, incoming) {
  const merged = new Map([...decisionMap(existing)].map(([key, review]) => [key, { ...review }]));
  const conflicts = [];
  for (const [key, review] of [...decisionMap(incoming)].sort(([left], [right]) => left.localeCompare(right))) {
    const prior = merged.get(key);
    if (prior && coverReviewSignature(prior) !== coverReviewSignature(review)) {
      conflicts.push(key);
      continue;
    }
    if (!prior) merged.set(key, { ...review });
  }
  return {
    ok: conflicts.length === 0,
    errors: conflicts.map(key => `Conflicting review decisions exist for ${key}.`),
    conflicts,
    decisions: conflicts.length ? new Map() : merged
  };
}

export function createReviewedExport(queue, decisions, reviewer, reviewedAt, sourceFilename = "") {
  const validation = validateReviewQueue(queue);
  if (!validation.ok) throw new Error(validation.errors.join(" "));
  const reviewerName = String(reviewer || "").trim();
  if (!nonemptyString(reviewerName, 200)) throw new Error("Reviewer name is required and must be 200 characters or fewer.");
  if (!validIsoDate(reviewedAt)) throw new Error("Review date must be a valid ISO calendar date.");

  const decisionMap = decisions instanceof Map ? decisions : new Map(Object.entries(decisions || {}));
  const reviewedCandidates = queue.candidates.map(candidate => {
    const review = decisionMap.get(candidate.candidate_id);
    if (!review || !REVIEW_DECISIONS.includes(review.decision)) {
      throw new Error(`A decision is required for ${candidate.candidate_id}.`);
    }
    const reason = String(review.reason || "").trim();
    if (!reason || reason.length > MAX_REASON_LENGTH) {
      throw new Error(`A review reason of 1–${MAX_REASON_LENGTH.toLocaleString()} characters is required for ${candidate.candidate_id}.`);
    }
    return {
      ...candidate,
      publication_status: "unpublished",
      review_decision: review.decision,
      reviewer: reviewerName,
      reviewed_at: reviewedAt,
      review_reason: reason
    };
  });

  return {
    schema: REVIEW_EXPORT_SCHEMA,
    exported_at: new Date().toISOString(),
    source_schema: queue.schema,
    source_filename: String(sourceFilename || ""),
    publication_effect: "none",
    notice: "This export records human review decisions only. Every candidate remains unpublished until a separate editorial publication gate is completed.",
    candidates: reviewedCandidates
  };
}

function hasCoverDraft(review) {
  return Boolean(
    review && (
      review.decision || String(review.reason || "").trim() ||
      review.exactEditionConfirmed || review.visualCheck
    )
  );
}

function coverReviewIsComplete(review) {
  if (!review || !REVIEW_DECISIONS.includes(review.decision)) return false;
  const reason = String(review.reason || "").trim();
  if (reason.length < MIN_COVER_EVIDENCE_LENGTH || reason.length > MAX_REASON_LENGTH) return false;
  return review.decision !== "approve" || (review.exactEditionConfirmed === true && review.visualCheck === true);
}

export function createCoverReviewsExport(queue, decisions, reviewer = "", reviewedAt = "", sourceFilename = "") {
  const validation = validateCoverReviewQueue(queue);
  if (!validation.ok) throw new Error(validation.errors.join(" "));

  const reviews = decisionMap(decisions);
  const itemByKey = new Map(validation.reviewItems.map(item => [item.candidate.candidate_key, item]));
  const approvedRecords = new Set();
  const exportedDecisions = {};
  const reviewerName = String(reviewer || "").trim();
  const sessionReviewedAt = reviewedAt || currentUtcTimestamp();
  let sessionIdentityRequired = false;

  for (const [candidateKey, review] of reviews) {
    const item = itemByKey.get(candidateKey);
    if (!item) throw new Error(`The review ledger contains an unknown cover candidate: ${candidateKey}.`);
    if (!hasCoverDraft(review)) continue;
    if (!coverReviewIsComplete(review)) {
      throw new Error(`Complete the decision and a ${MIN_COVER_EVIDENCE_LENGTH}–${MAX_REASON_LENGTH.toLocaleString()} character evidence note for ${candidateKey}; approvals also require both confirmations.`);
    }
    if (review.decision === "approve") {
      if (approvedRecords.has(item.recordId)) {
        throw new Error(`Approve at most one front-cover candidate for Clark record ${item.recordId}.`);
      }
      approvedRecords.add(item.recordId);
    }
    const preserveImportedAudit = (
      review.imported === true && review.dirty !== true &&
      review.candidateFingerprint === item.candidate.candidate_fingerprint &&
      nonemptyString(String(review.reviewer || "").trim(), 200) &&
      validUtcTimestamp(review.reviewedAt) &&
      review.rightsScope === "remote_reference_only"
    );
    if (review.imported === true && review.dirty !== true && !preserveImportedAudit) {
      throw new Error(`The imported review audit fields conflict with the current queue for ${candidateKey}.`);
    }
    if (!preserveImportedAudit) sessionIdentityRequired = true;
    exportedDecisions[candidateKey] = {
      candidate_fingerprint: item.candidate.candidate_fingerprint,
      decision: review.decision === "needs_work" ? "defer" : review.decision,
      reviewer: preserveImportedAudit ? String(review.reviewer).trim() : reviewerName,
      reviewed_at: preserveImportedAudit ? review.reviewedAt : sessionReviewedAt,
      exact_edition_confirmed: review.exactEditionConfirmed === true,
      visual_check: review.visualCheck === true,
      rights_scope: "remote_reference_only",
      evidence_note: String(review.reason).trim()
    };
  }

  if (!Object.keys(exportedDecisions).length) {
    throw new Error("Complete at least one cover-candidate decision before exporting a partial review ledger.");
  }
  if (sessionIdentityRequired && !nonemptyString(reviewerName, 200)) {
    throw new Error("Reviewer name is required for every new or changed cover decision and must be 200 characters or fewer.");
  }
  if (sessionIdentityRequired && !validUtcTimestamp(sessionReviewedAt)) {
    throw new Error("New or changed cover decisions require a valid current 20xx UTC timestamp.");
  }

  return {
    schema: COVER_REVIEWS_SCHEMA,
    version: nonemptyString(queue.version, 100) ? queue.version : "1.0.0",
    generated_at: currentUtcTimestamp(),
    source_filename: String(sourceFilename || ""),
    queue_inputs: queue.inputs,
    instructions: {
      decision: "Use approve, reject, or defer. The browser's needs_work decision is exported as defer.",
      approval_gate: "Approval requires candidate_fingerprint, reviewer, reviewed_at, exact_edition_confirmed=true, visual_check=true, rights_scope=remote_reference_only, an evidence_note, and a separate current positive probe.",
      selection: "Approve at most one front-cover candidate per catalog record."
    },
    publication_effect: "none",
    decisions: exportedDecisions
  };
}

function element(tag, className = "", text = "") {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== "") node.textContent = text;
  return node;
}

function displayValue(value) {
  if (value == null || value === "") return "Not supplied";
  if (Array.isArray(value)) {
    if (!value.length) return "Not supplied";
    const text = value.map(displayValue).join(" · ");
    return text.length > 2400 ? `${text.slice(0, 2399)}…` : text;
  }
  if (isPlainObject(value)) {
    const text = Object.entries(value).map(([key, item]) => `${key}: ${displayValue(item)}`).join(" · ");
    return text.length > 2400 ? `${text.slice(0, 2399)}…` : (text || "Not supplied");
  }
  const text = String(value);
  return text.length > 2400 ? `${text.slice(0, 2399)}…` : text;
}

function localDate() {
  const now = new Date();
  return new Date(now.valueOf() - now.getTimezoneOffset() * 60_000).toISOString().slice(0, 10);
}

function safeFilename(value = "review-queue.json", mode = "association") {
  const stem = String(value).replace(/\.json$/i, "").replace(/[^a-z0-9._-]+/gi, "-").replace(/^-+|-+$/g, "") || "review-queue";
  return mode === "cover" ? `${stem}.reviews.json` : `${stem}.reviewed.json`;
}

function initializeReviewPage() {
  const dom = {
    file: document.querySelector("#candidateFile"),
    clear: document.querySelector("#clearQueue"),
    status: document.querySelector("#reviewStatus"),
    reviewerPanel: document.querySelector("#reviewerPanel"),
    reviewerHelp: document.querySelector("#reviewerHelp"),
    reviewer: document.querySelector("#reviewerName"),
    dateWrap: document.querySelector("#reviewDateWrap"),
    date: document.querySelector("#reviewDate"),
    resumeWrap: document.querySelector("#resumeReviewWrap"),
    resumeFile: document.querySelector("#resumeReviewFile"),
    queueTitle: document.querySelector("#queueTitle"),
    searchWrap: document.querySelector("#queueSearchWrap"),
    search: document.querySelector("#queueSearch"),
    queue: document.querySelector("#reviewQueue"),
    progress: document.querySelector("#reviewProgress"),
    export: document.querySelector("#exportReviewed")
  };
  if (Object.values(dom).some(node => !node)) return;

  const state = {
    queue: null,
    mode: null,
    sourceFilename: "",
    decisions: new Map(),
    cards: new Map(),
    reviewItems: [],
    itemByKey: new Map(),
    resumedFilenames: [],
    renderLimit: COVER_RENDER_BATCH,
    filteredCount: 0,
    visibleCount: 0
  };
  dom.date.value = localDate();

  function setStatus(message, tone = "") {
    dom.status.textContent = message;
    if (tone) dom.status.dataset.tone = tone;
    else delete dom.status.dataset.tone;
  }

  function associationReviewIsComplete(candidateId) {
    const review = state.decisions.get(candidateId);
    return Boolean(review && REVIEW_DECISIONS.includes(review.decision) && String(review.reason || "").trim());
  }

  function reviewIsComplete(key) {
    return state.mode === "cover" ? coverReviewIsComplete(state.decisions.get(key)) : associationReviewIsComplete(key);
  }

  function duplicateApprovedRecord() {
    if (state.mode !== "cover") return "";
    const approved = new Set();
    for (const [key, review] of state.decisions) {
      if (!coverReviewIsComplete(review) || review.decision !== "approve") continue;
      const recordId = state.itemByKey.get(key)?.recordId;
      if (!recordId) continue;
      if (approved.has(recordId)) return recordId;
      approved.add(recordId);
    }
    return "";
  }

  function syncProgress() {
    const total = state.reviewItems.length;
    let drafted = 0;
    let completed = 0;
    let imported = 0;
    let sessionIdentityRequired = false;
    for (const [key, review] of state.decisions) {
      if (!state.itemByKey.has(key)) continue;
      const isDrafted = state.mode === "cover" ? hasCoverDraft(review) : Boolean(review?.decision || String(review?.reason || "").trim());
      if (isDrafted) drafted += 1;
      if (reviewIsComplete(key)) completed += 1;
      if (isDrafted && review?.imported === true && review?.dirty !== true) imported += 1;
      if (isDrafted && (review?.imported !== true || review?.dirty === true)) sessionIdentityRequired = true;
    }
    const incompleteDrafts = drafted - completed;
    const duplicateRecord = duplicateApprovedRecord();

    if (!total) {
      dom.progress.textContent = state.queue ? "The imported queue has no review candidates." : "Import a local queue to begin.";
    } else if (state.mode === "cover") {
      const visible = `${state.visibleCount.toLocaleString()} shown of ${state.filteredCount.toLocaleString()} matching`;
      const draftNote = incompleteDrafts ? ` · ${incompleteDrafts.toLocaleString()} incomplete draft${incompleteDrafts === 1 ? "" : "s"}` : "";
      const duplicateNote = duplicateRecord ? ` · duplicate approval for ${duplicateRecord}` : "";
      const importedNote = imported ? ` · ${imported.toLocaleString()} resumed` : "";
      dom.progress.textContent = `${completed.toLocaleString()} completed of ${total.toLocaleString()} cover candidates · ${visible}${importedNote}${draftNote}${duplicateNote}`;
    } else {
      dom.progress.textContent = `${completed.toLocaleString()} of ${total.toLocaleString()} decisions complete`;
    }

    for (const [key, card] of state.cards) card.dataset.complete = reviewIsComplete(key) ? "true" : "false";
    const associationIdentityReady = nonemptyString(dom.reviewer.value.trim(), 200) && validIsoDate(dom.date.value);
    const coverIdentityReady = !sessionIdentityRequired || nonemptyString(dom.reviewer.value.trim(), 200);
    const ready = state.mode === "cover"
      ? completed > 0 && incompleteDrafts === 0 && !duplicateRecord && coverIdentityReady
      : total > 0 && completed === total && associationIdentityReady;
    dom.export.disabled = !ready;
  }

  function candidateField(label, value) {
    const wrapper = element("div", "candidate-field");
    wrapper.append(element("dt", "", label), element("dd", "", displayValue(value)));
    return wrapper;
  }

  function citationText(citation, index) {
    if (typeof citation === "string") return citation;
    if (!isPlainObject(citation)) return `Citation ${index + 1}: ${displayValue(citation)}`;
    const label = citation.label || citation.title || citation.source || `Citation ${index + 1}`;
    return [label, citation.locator, citation.url].filter(Boolean).map(String).join(" · ");
  }

  function renderDecisionFields(key, index, cover = false) {
    const current = state.decisions.get(key) || {};
    const fields = element("div", "decision-fields");
    const selectLabel = element("label");
    const idPrefix = cover ? "cover" : "association";
    const selectId = `${idPrefix}-review-decision-${index}`;
    selectLabel.append(element("span", "", "Human decision"));
    const select = element("select");
    select.id = selectId;
    select.required = true;
    [
      ["", "Choose a decision…"],
      ["approve", cover ? "Approve for cover pipeline gate" : "Approve for publication gate"],
      ["reject", "Reject"],
      ["needs_work", "Needs work"]
    ].forEach(([value, label]) => {
      const option = element("option", "", label);
      option.value = value;
      select.append(option);
    });
    select.value = current.decision || "";
    selectLabel.htmlFor = selectId;
    selectLabel.append(select);

    const reasonLabel = element("label");
    const reasonId = `${idPrefix}-review-reason-${index}`;
    reasonLabel.append(element("span", "", cover ? "Evidence note / reason" : "Reason for this decision"));
    const textarea = element("textarea");
    textarea.id = reasonId;
    textarea.maxLength = MAX_REASON_LENGTH;
    textarea.required = true;
    textarea.value = current.reason || "";
    textarea.placeholder = cover
      ? "Record what you compared, what is visible, and any unresolved edition or front-cover ambiguity (minimum 12 characters)."
      : "State what the evidence supports, what remains unresolved, or why this association should not proceed.";
    reasonLabel.htmlFor = reasonId;
    reasonLabel.append(textarea);
    fields.append(selectLabel, reasonLabel);

    let exactEdition;
    let visualCheck;
    if (cover) {
      const confirmations = element("div", "cover-confirmations");
      confirmations.setAttribute("role", "group");
      confirmations.setAttribute("aria-label", "Approval confirmations");
      const exactLabel = element("label");
      exactEdition = element("input");
      exactEdition.type = "checkbox";
      exactEdition.checked = current.exactEditionConfirmed === true;
      exactLabel.append(exactEdition, document.createTextNode("Exact provider edition compared with the Clark record"));
      const visualLabel = element("label");
      visualCheck = element("input");
      visualCheck.type = "checkbox";
      visualCheck.checked = current.visualCheck === true;
      visualLabel.append(visualCheck, document.createTextNode("Candidate visually checked as a front-cover image"));
      confirmations.append(exactLabel, visualLabel);
      fields.append(confirmations);
    }

    const update = () => {
      const review = { ...current, decision: select.value, reason: textarea.value, dirty: true };
      if (cover) {
        review.exactEditionConfirmed = exactEdition.checked;
        review.visualCheck = visualCheck.checked;
      }
      state.decisions.set(key, review);
      syncProgress();
    };
    select.addEventListener("change", update);
    textarea.addEventListener("input", update);
    exactEdition?.addEventListener("change", update);
    visualCheck?.addEventListener("change", update);
    return fields;
  }

  function renderAssociationCandidate(candidate, index) {
    const card = element("article", "review-card");
    card.dataset.complete = "false";
    const headingId = `association-candidate-heading-${index}`;
    card.setAttribute("aria-labelledby", headingId);
    const header = element("header");
    const heading = element("h3", "candidate-id", candidate.candidate_id);
    heading.id = headingId;
    heading.tabIndex = -1;
    header.append(
      element("span", "candidate-index", String(index + 1).padStart(2, "0")),
      heading
    );

    const metadata = element("dl", "candidate-grid");
    [
      ["Catalog record", candidate.catalog_id],
      ["Journey", candidate.journey_id],
      ["Cluster", candidate.cluster_id],
      ["Phase", candidate.phase],
      ["Target work", candidate.target_work],
      ["Evidence grade", candidate.evidence_grade],
      ["Recorded placement", candidate.placement],
      ["Candidate source", candidate.candidate_source],
      ["Publication status", candidate.publication_status]
    ].forEach(([label, value]) => metadata.append(candidateField(label, value)));

    const evidence = element("div", "candidate-evidence");
    const reasoning = element("section");
    reasoning.append(element("h4", "", "Proposed reasoning"));
    reasoning.append(element("blockquote", "", displayValue(candidate.reasoning || candidate.proposed_reasoning)));
    const citations = element("section");
    citations.append(element("h4", "", "Citations supplied"));
    const citationList = element("ol", "citation-list");
    const sourceCitations = Array.isArray(candidate.citations) ? candidate.citations : [];
    if (sourceCitations.length) {
      sourceCitations.forEach((citation, citationIndex) => citationList.append(element("li", "", citationText(citation, citationIndex))));
    } else {
      citationList.append(element("li", "", "No citations supplied; approval cannot pass the publication gate."));
    }
    citations.append(citationList);
    evidence.append(reasoning, citations);

    card.append(header, metadata, evidence, renderDecisionFields(candidate.candidate_id, index));
    state.cards.set(candidate.candidate_id, card);
    return card;
  }

  function renderCoverCandidate(item) {
    const { recordId, catalog, candidate, position } = item;
    const card = element("article", "review-card cover-review-card");
    card.dataset.complete = "false";
    const headingId = `cover-candidate-heading-${position}`;
    card.setAttribute("aria-labelledby", headingId);
    const header = element("header");
    const heading = element("h3", "candidate-id", candidate.candidate_key);
    heading.id = headingId;
    heading.tabIndex = -1;
    header.append(
      element("span", "candidate-index", String(position + 1).padStart(5, "0")),
      heading
    );

    const matchedIdentifiers = candidate.matched_identifiers.map(identifier => `${identifier.type.toUpperCase()} ${identifier.value}`);
    const metadata = element("dl", "candidate-grid");
    [
      ["Clark title", catalog.title],
      ["Clark catalog ID", recordId],
      ["Clark author", catalog.authors],
      ["Clark date", catalog.year],
      ["Clark call number", catalog.call_number],
      ["Clark canonical ISBN", catalog.normalized_isbns],
      ["Provider edition ID", candidate.provider_edition_id],
      ["Provider Cover ID", candidate.cover_id],
      ["Exact matched identifier", matchedIdentifiers],
      ["Provider edition evidence", candidate.edition_summary],
      ["Evidence scope", candidate.scope],
      ["Candidate fingerprint", candidate.candidate_fingerprint],
      ["Clark catalog URL (text only)", catalog.catalog_url],
      ["Provider record URL (text only)", candidate.source_url],
      ["Thumbnail URL (text only; not loaded)", candidate.thumbnail_url],
      ["Large cover URL (text only; not loaded)", candidate.image_url]
    ].forEach(([label, value]) => metadata.append(candidateField(label, value)));

    const evidence = element("div", "candidate-evidence");
    const rationale = element("section");
    rationale.append(element("h4", "", "Candidate rationale and limit"));
    rationale.append(element(
      "blockquote",
      "",
      `The Clark record and this provider edition share ${matchedIdentifiers.join(" · ")}. This exact identifier creates a review candidate; it does not prove that the remote image depicts the Clark copy's jacket, binding, texture, condition, or side profile.`
    ));
    const provenance = element("section");
    provenance.append(element("h4", "", "Queue provenance / source citations"));
    const provenanceList = element("ol", "citation-list");
    [
      `Provider: ${displayValue(state.queue.provider?.name)} · discovery: ${displayValue(state.queue.provider?.discovery_method)}`,
      `Provider snapshot: ${displayValue(state.queue.inputs?.provider_snapshot)} · dump checksum: ${displayValue(state.queue.inputs?.provider_dump_checksum)}`,
      `Dump documentation: ${displayValue(state.queue.provider?.dump_documentation)}`,
      `Cover API documentation: ${displayValue(state.queue.provider?.cover_documentation)}`,
      `Licensing statement: ${displayValue(state.queue.provider?.licensing)}`
    ].forEach(value => provenanceList.append(element("li", "", value)));
    provenance.append(provenanceList);
    evidence.append(rationale, provenance);

    const guidance = element("p", "workflow-guidance");
    guidance.append(
      element("strong", "", "Probe and review workflow. "),
      document.createTextNode("This page does not fetch, probe, or display the URL. Inspect the text URL in a separate, authorized workflow; run the pipeline's bounded resumable probe separately; compare edition evidence and visible front-cover text; then record a decision here. An approval export still cannot publish without a current positive probe and the pipeline's remaining gates.")
    );

    card.append(header, metadata, evidence, guidance, renderDecisionFields(candidate.candidate_key, position, true));
    state.cards.set(candidate.candidate_key, card);
    return card;
  }

  function filteredCoverItems() {
    const query = dom.search.value.trim().toLocaleLowerCase();
    return query ? state.reviewItems.filter(item => item.searchText.includes(query)) : state.reviewItems;
  }

  function renderQueue(focusKey = "") {
    dom.queue.replaceChildren();
    state.cards.clear();
    if (!state.reviewItems.length) {
      state.filteredCount = 0;
      state.visibleCount = 0;
      dom.queue.append(element("p", "empty-state", "The imported queue contains no review candidates."));
      syncProgress();
      return;
    }

    const fragment = document.createDocumentFragment();
    if (state.mode === "association") {
      state.filteredCount = state.reviewItems.length;
      state.visibleCount = state.reviewItems.length;
      state.reviewItems.forEach((candidate, index) => fragment.append(renderAssociationCandidate(candidate, index)));
    } else {
      const matching = filteredCoverItems();
      const visible = matching.slice(0, state.renderLimit);
      state.filteredCount = matching.length;
      state.visibleCount = visible.length;
      if (!visible.length) {
        fragment.append(element("p", "empty-state", "No cover candidates match this local filter."));
      } else {
        visible.forEach(item => fragment.append(renderCoverCandidate(item)));
      }
      if (visible.length < matching.length) {
        const nextKey = matching[visible.length]?.candidate.candidate_key || "";
        const reveal = element("button", "reveal-more", `Show next ${Math.min(COVER_RENDER_BATCH, matching.length - visible.length).toLocaleString()}`);
        reveal.type = "button";
        reveal.addEventListener("click", () => {
          state.renderLimit += COVER_RENDER_BATCH;
          renderQueue(nextKey);
        });
        fragment.append(reveal);
      }
    }
    dom.queue.append(fragment);
    syncProgress();
    if (focusKey) {
      requestAnimationFrame(() => state.cards.get(focusKey)?.querySelector(".candidate-id")?.focus());
    }
  }

  function clearQueue() {
    state.queue = null;
    state.mode = null;
    state.sourceFilename = "";
    state.reviewItems = [];
    state.itemByKey.clear();
    state.resumedFilenames = [];
    state.decisions.clear();
    state.cards.clear();
    state.renderLimit = COVER_RENDER_BATCH;
    state.filteredCount = 0;
    state.visibleCount = 0;
    dom.file.value = "";
    dom.reviewer.value = "";
    dom.date.value = localDate();
    dom.dateWrap.hidden = false;
    dom.resumeFile.value = "";
    dom.resumeWrap.hidden = true;
    dom.reviewerHelp.textContent = "The same reviewer and ISO date are written to each association decision in this export.";
    dom.search.value = "";
    dom.searchWrap.hidden = true;
    dom.queueTitle.textContent = "Private review queue";
    dom.reviewerPanel.hidden = true;
    dom.clear.disabled = true;
    dom.export.disabled = true;
    dom.queue.replaceChildren(element("p", "empty-state", "No candidate records are bundled with this page."));
    dom.progress.textContent = "Import a local queue to begin.";
    setStatus("No candidate file is open.");
  }

  async function importFile(file) {
    if (!file) return;
    if (file.size > MAX_FILE_BYTES) {
      setStatus(`The selected file exceeds the ${(MAX_FILE_BYTES / 1024 / 1024).toFixed(0)} MB local review limit.`, "error");
      return;
    }
    try {
      const parsed = JSON.parse(await file.text());
      const validation = validateImportedQueue(parsed);
      if (!validation.ok) {
        const shown = validation.errors.slice(0, 12).join(" ");
        const remainder = validation.errors.length > 12 ? ` ${validation.errors.length - 12} additional validation errors were omitted.` : "";
        setStatus(`Import rejected. ${shown}${remainder}`, "error");
        return;
      }
      state.queue = validation.data;
      state.mode = validation.mode;
      state.sourceFilename = file.name;
      state.reviewItems = validation.reviewItems;
      state.itemByKey = new Map(state.reviewItems.map(item => [
        state.mode === "cover" ? item.candidate.candidate_key : item.candidate_id,
        item
      ]));
      state.decisions.clear();
      state.resumedFilenames = [];
      state.renderLimit = COVER_RENDER_BATCH;
      dom.search.value = "";
      dom.searchWrap.hidden = state.mode !== "cover";
      dom.resumeFile.value = "";
      dom.resumeWrap.hidden = state.mode !== "cover";
      dom.dateWrap.hidden = state.mode === "cover";
      dom.reviewerHelp.textContent = state.mode === "cover"
        ? "Imported decisions keep their named reviewer and UTC timestamp. This reviewer is assigned only to new or changed decisions; their current UTC time is captured at export."
        : "The same reviewer and ISO date are written to each association decision in this export.";
      dom.queueTitle.textContent = state.mode === "cover" ? "Exact-edition cover candidates" : "Unpublished association candidates";
      dom.reviewer.value = "";
      dom.date.value = localDate();
      dom.reviewerPanel.hidden = false;
      dom.clear.disabled = false;
      renderQueue();
      const label = state.mode === "cover" ? "exact-edition cover candidate" : "unpublished association candidate";
      setStatus(`Opened ${file.name}: ${state.reviewItems.length.toLocaleString()} ${label}${state.reviewItems.length === 1 ? "" : "s"}. Data remains local to this tab.`, "success");
    } catch (error) {
      setStatus(`Import rejected. ${error instanceof SyntaxError ? "The file is not valid JSON." : "The local file could not be read."}`, "error");
    }
  }

  async function importCoverLedger(file) {
    if (!file) return;
    if (state.mode !== "cover" || !state.queue) {
      setStatus("Open a compatible cover candidate queue before resuming a review ledger.", "error");
      dom.resumeFile.value = "";
      return;
    }
    if (file.size > MAX_FILE_BYTES) {
      setStatus(`The selected ledger exceeds the ${(MAX_FILE_BYTES / 1024 / 1024).toFixed(0)} MB local review limit.`, "error");
      dom.resumeFile.value = "";
      return;
    }
    try {
      const parsed = JSON.parse(await file.text());
      const validation = validateCoverReviewsLedger(state.queue, parsed);
      if (!validation.ok) {
        const shown = validation.errors.slice(0, 12).join(" ");
        const remainder = validation.errors.length > 12 ? ` ${validation.errors.length - 12} additional validation errors were omitted.` : "";
        setStatus(`Review resume rejected. ${shown}${remainder}`, "error");
        return;
      }
      const merged = mergeCoverReviewDecisions(state.decisions, validation.decisions);
      if (!merged.ok) {
        setStatus(`Review resume rejected. ${merged.errors.slice(0, 5).join(" ")}`, "error");
        return;
      }
      state.decisions = merged.decisions;
      if (!state.resumedFilenames.includes(file.name)) state.resumedFilenames.push(file.name);
      renderQueue();
      setStatus(`Merged ${validation.decisions.size.toLocaleString()} decision${validation.decisions.size === 1 ? "" : "s"} from ${file.name}. Exact duplicates were retained once; conflicts would reject the entire import.`, "success");
    } catch (error) {
      setStatus(`Review resume rejected. ${error instanceof SyntaxError ? "The file is not valid JSON." : "The local review ledger could not be read."}`, "error");
    } finally {
      dom.resumeFile.value = "";
    }
  }

  function exportReviewed() {
    try {
      const reviewed = state.mode === "cover"
        ? createCoverReviewsExport(state.queue, state.decisions, dom.reviewer.value, currentUtcTimestamp(), state.sourceFilename)
        : createReviewedExport(state.queue, state.decisions, dom.reviewer.value, dom.date.value, state.sourceFilename);
      const blob = new Blob([`${JSON.stringify(reviewed, null, 2)}\n`], { type: "application/json" });
      const url = URL.createObjectURL(blob);
      const link = element("a");
      link.href = url;
      link.download = safeFilename(state.sourceFilename, state.mode);
      document.body.append(link);
      link.click();
      link.remove();
      setTimeout(() => URL.revokeObjectURL(url), 0);
      setStatus(
        state.mode === "cover"
          ? "Private cover review ledger exported. No URL was probed, fetched, displayed, cached, or published."
          : "Reviewed JSON exported. No candidate was uploaded or published; every publication_status remains unpublished.",
        "success"
      );
    } catch (error) {
      setStatus(error instanceof Error ? error.message : "The reviewed export could not be created.", "error");
    }
  }

  dom.file.addEventListener("change", () => { void importFile(dom.file.files?.[0]); });
  dom.resumeFile.addEventListener("change", () => { void importCoverLedger(dom.resumeFile.files?.[0]); });
  dom.clear.addEventListener("click", clearQueue);
  dom.search.addEventListener("input", () => {
    state.renderLimit = COVER_RENDER_BATCH;
    if (state.mode === "cover") renderQueue();
  });
  dom.reviewer.addEventListener("input", syncProgress);
  dom.date.addEventListener("input", syncProgress);
  dom.export.addEventListener("click", exportReviewed);
}

if (typeof document !== "undefined") initializeReviewPage();
