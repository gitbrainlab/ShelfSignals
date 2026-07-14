import assert from "node:assert/strict";
import test from "node:test";

import {
  COVER_INDEX_SCHEMA,
  COVER_PROVENANCE_SCHEMA,
  LEGACY_VISUAL_SCHEMA,
  PROVIDER_REFERENCE_LABEL,
  UNRESOLVED_COVER_LABEL,
  canDisplayCover,
  coverProvenanceShard,
  getRecordCoverState,
  parseCoverIndex,
  parseCoverProvenance
} from "../docs/js/covers.js";
import {
  JOURNEY_INDEX_SCHEMA,
  JOURNEY_MANIFEST_SCHEMA,
  associationClaimLabel,
  canClaimInfluence,
  getPublicAssociations,
  parseJourneyIndex,
  parseJourneyManifest
} from "../docs/js/journeys.js";

const DATASET_SHA256 = `sha256:${"a".repeat(64)}`;
const IMAGE_SHA256 = `sha256:${"b".repeat(64)}`;
const CATALOG_IDS = ["alma1", "alma2", "alma3"];

function clone(value) {
  return structuredClone(value);
}

function validCoverIndex() {
  return {
    schema: COVER_INDEX_SCHEMA,
    generated_at: "2026-07-14T00:00:00Z",
    source: {
      catalog: "Clark Library Catalog",
      dataset: "sekula_index.json",
      dataset_sha256: DATASET_SHA256,
      record_count: CATALOG_IDS.length
    },
    unresolved_default: {
      status: "unresolved",
      label: UNRESOLVED_COVER_LABEL,
      scope: "none",
      cache_policy: "none"
    },
    items: {
      alma1: {
        status: "verified",
        provider: "openlibrary",
        scope: "exact_edition",
        image: {
          image_url: "https://covers.openlibrary.org/b/id/12345-L.jpg?default=false",
          thumbnail_url: "https://covers.openlibrary.org/b/id/12345-M.jpg?default=false",
          width: 400,
          height: 600
        },
        rights: {
          public_display: true,
          basis: "provider_display_terms",
          credit_line: "Cover reference served by Open Library"
        },
        cache_policy: "remote_only",
        provenance_ref: "cover-provenance/1.json#alma1",
        review: {
          status: "approved",
          reviewer: "Test reviewer",
          reviewed_at: "2026-07-14T00:00:00Z",
          evidence_note: "The exact edition and front-cover role were checked."
        }
      },
      alma3: {
        status: "needs_review",
        provider: "openlibrary",
        scope: "work_level",
        cache_policy: "none",
        provenance_ref: "cover-provenance/3.json#alma3"
      }
    }
  };
}

test("sparse cover index gives every absent catalog ID an honest unresolved state", () => {
  const parsed = parseCoverIndex(validCoverIndex(), {
    catalogIds: CATALOG_IDS,
    datasetSha256: DATASET_SHA256
  });
  assert.equal(parsed.rejected, false);
  assert.equal(canDisplayCover(getRecordCoverState({ id: "alma1" }, parsed)), true);
  assert.deepEqual(getRecordCoverState({ id: "alma2" }, parsed), parsed.unresolved_default);
  assert.equal(getRecordCoverState({ id: "alma2" }, parsed).label, UNRESOLVED_COVER_LABEL);
  assert.equal(getRecordCoverState({ id: "not-in-index" }, parsed).status, "unresolved");
  assert.equal(getRecordCoverState({ id: "alma3" }, parsed).status, "needs_review");
  assert.equal(getRecordCoverState({ id: "alma3" }, parsed).image, null);
});

test("cover index rejects stale catalog identity and unknown item IDs", () => {
  const stale = validCoverIndex();
  stale.source.record_count = 99;
  assert.equal(parseCoverIndex(stale, { catalogIds: CATALOG_IDS }).rejected, true);

  const wrongChecksum = validCoverIndex();
  assert.equal(parseCoverIndex(wrongChecksum, {
    catalogIds: CATALOG_IDS,
    datasetSha256: `sha256:${"c".repeat(64)}`
  }).rejected, true);

  const extra = validCoverIndex();
  extra.items.outside = extra.items.alma1;
  assert.equal(parseCoverIndex(extra, { catalogIds: CATALOG_IDS }).rejected, true);
});

test("rights and provider failures demote a claimed cover instead of exposing it", () => {
  const unreviewed = validCoverIndex();
  delete unreviewed.items.alma1.review;
  const parsedUnreviewed = parseCoverIndex(unreviewed, { catalogIds: CATALOG_IDS });
  assert.equal(parsedUnreviewed.items.alma1.status, "unresolved");
  assert.ok(parsedUnreviewed.warnings.some(warning => warning.code === "missing_human_approval"));

  const pending = validCoverIndex();
  pending.items.alma1.rights = { public_display: false, basis: "pending" };
  const parsedPending = parseCoverIndex(pending, { catalogIds: CATALOG_IDS });
  assert.equal(parsedPending.rejected, false);
  assert.equal(parsedPending.items.alma1.status, "unresolved");
  assert.equal(canDisplayCover(parsedPending.items.alma1), false);
  assert.ok(parsedPending.warnings.some(warning => warning.code === "display_not_allowed"));

  const hostile = validCoverIndex();
  hostile.items.alma1.image.image_url = "https://covers.openlibrary.org.evil.test/cover.jpg";
  const parsedHostile = parseCoverIndex(hostile, { catalogIds: CATALOG_IDS });
  assert.equal(parsedHostile.items.alma1.status, "unresolved");

  const google = validCoverIndex();
  google.items.alma1.provider = "google_books";
  google.items.alma1.image.image_url = "https://books.google.com/books/content?id=one";
  google.items.alma1.image.thumbnail_url = google.items.alma1.image.image_url;
  google.items.alma1.rights.credit_line = "";
  assert.equal(parseCoverIndex(google, { catalogIds: CATALOG_IDS }).items.alma1.status, "unresolved");
});

test("legacy visual evidence normalizes into full provenance without claiming local reuse rights", () => {
  const parsed = parseCoverProvenance({
    schema: LEGACY_VISUAL_SCHEMA,
    generated_at: "2026-07-14T00:00:00Z",
    items: {
      alma1: {
        status: "resolved",
        image_url: "https://covers.openlibrary.org/b/isbn/9780374226268-L.jpg?default=false",
        thumbnail_url: "https://covers.openlibrary.org/b/isbn/9780374226268-M.jpg?default=false",
        source: "openlibrary",
        source_id: "9780374226268",
        source_url: "https://openlibrary.org/isbn/9780374226268",
        match_method: "isbn",
        attribution: "Cover reference served by Open Library Covers",
        checked_at: "2026-07-14T00:00:00Z",
        image_analysis: {
          source_pixels: { width: 400, height: 600 },
          source_sha256: IMAGE_SHA256
        },
        provenance: {
          matched_identifiers: [{ type: "isbn", value: "9780374226268" }]
        }
      }
    }
  }, { recordId: "alma1" });

  assert.equal(parsed.rejected, false);
  assert.equal(parsed.items.alma1.status, "provider_reference");
  assert.equal(parsed.items.alma1.label, PROVIDER_REFERENCE_LABEL);
  assert.equal(parsed.items.alma1.scope, "exact_edition");
  assert.equal(parsed.items.alma1.rights.basis, "provider_display_terms");
  assert.equal(parsed.items.alma1.rights.derivatives_allowed, false);
  assert.equal(canDisplayCover(parsed.items.alma1), true);
  assert.deepEqual(parsed.items.alma1.matched_identifiers, [{ type: "isbn", value: "9780374226268" }]);
});

test("locally cached cover provenance requires derivative authority and a checksum", () => {
  const raw = {
    schema: COVER_PROVENANCE_SCHEMA,
    generated_at: "2026-07-14T00:00:00Z",
    source: {
      catalog: "Clark Library Catalog",
      dataset: "sekula_index.json",
      dataset_sha256: DATASET_SHA256,
      record_count: 1
    },
    items: {
      alma1: {
        status: "verified",
        provider: "clark",
        scope: "clark_copy",
        image: { image_url: "images/covers/alma1.jpg", thumbnail_url: "images/covers/alma1-thumb.jpg", width: 400, height: 600 },
        source: { provider: "clark", source_id: "alma1", source_url: "https://library.clarkart.edu/permalink/alma1" },
        matched_identifiers: [{ type: "catalog_id", value: "alma1" }],
        selection_rationale: "Clark copy-specific photography.",
        retrieved_at: "2026-07-14T00:00:00Z",
        cache_policy: "local_derivatives",
        checksum: IMAGE_SHA256,
        review: {
          status: "approved",
          reviewer: "Test reviewer",
          reviewed_at: "2026-07-14T00:00:00Z",
          evidence_note: "Clark copy photograph and reuse authority checked."
        },
        rights: { public_display: true, basis: "institution_permission", derivatives_allowed: false, credit_line: "Clark Art Institute" }
      }
    }
  };
  const denied = parseCoverProvenance(raw, { recordId: "alma1", datasetSha256: DATASET_SHA256 });
  assert.equal(denied.items.alma1.status, "unresolved");
  raw.items.alma1.rights.derivatives_allowed = true;
  const allowed = parseCoverProvenance(raw, { recordId: "alma1", datasetSha256: DATASET_SHA256 });
  assert.equal(allowed.items.alma1.status, "verified");
  assert.equal(parseCoverProvenance(raw, {
    recordId: "alma1",
    datasetSha256: `sha256:${"c".repeat(64)}`
  }).rejected, true);
});

test("cover provenance sharding is deterministic and bounded", () => {
  assert.equal(coverProvenanceShard("alma991002293459708431"), coverProvenanceShard("alma991002293459708431"));
  assert.match(coverProvenanceShard("alma1"), /^[0-9a-f]$/);
});

function validJourneyIndex() {
  return {
    schema: JOURNEY_INDEX_SCHEMA,
    generated_at: "2026-07-14T00:00:00Z",
    journeys: [
      {
        id: "aerospace-folktales",
        publication_status: "published",
        title: "Aerospace Folktales",
        subtitle: "Work, family, and the domestic economy",
        manifest_ref: "journeys/aerospace-folktales.json",
        cluster_count: 1,
        association_count: 1
      },
      {
        id: "research-draft",
        publication_status: "draft",
        title: "Private research",
        manifest_ref: "journeys/research-draft.json"
      }
    ]
  };
}

function validJourneyManifest() {
  return {
    schema: JOURNEY_MANIFEST_SCHEMA,
    id: "aerospace-folktales",
    publication_status: "published",
    title: "Aerospace Folktales",
    subtitle: "A photo-led journey",
    introduction: "A cited path through the work and the Clark library copy.",
    target_works: [
      { id: "aerospace-folktales-work", title: "Aerospace Folktales", date: "1973", type: "photographic work" }
    ],
    citations: [
      {
        id: "getty-finding-aid",
        kind: "archival_finding_aid",
        title: "Allan Sekula papers",
        publisher: "Getty Research Institute",
        locator: "Series I, project files for Aerospace Folktales",
        url: "https://www.getty.edu/research/collections/collection/1CSKCZ"
      },
      {
        id: "clark-catalog",
        kind: "catalog_record",
        title: "Aerospace folktales / Allan Sekula",
        publisher: "Clark Art Institute Library",
        locator: "Alma record alma1",
        url: "https://library.clarkart.edu/permalink/alma1"
      }
    ],
    photographs: [
      {
        id: "archive-photo-record",
        title: "Aerospace Folktales project photograph",
        date: "1973",
        caption: "Archival record for a photograph in the project sequence.",
        alt: "Archival photograph description.",
        source_citation_id: "getty-finding-aid",
        image: {
          url: "https://media.example.org/permissioned/aerospace.jpg",
          thumbnail_url: "https://media.example.org/permissioned/aerospace-thumb.jpg",
          width: 1200,
          height: 800
        },
        rights: {
          public_display: true,
          basis: "institution_permission",
          credit_line: "© Allan Sekula Studio LLC",
          rights_holder: "Allan Sekula Studio LLC",
          derivatives_allowed: false
        }
      }
    ],
    clusters: [
      {
        id: "work-and-family",
        order: 1,
        title: "Work enters the family room",
        period_label: "1972–1973",
        narrative: "The archival sequence places family testimony beside aerospace labor.",
        shelf_label: "The Clark copy",
        photograph_ids: ["archive-photo-record"],
        association_ids: ["library-work-identity"]
      }
    ],
    associations: [
      {
        id: "library-work-identity",
        association_kind: "identity",
        catalog_id: "alma1",
        journey_id: "aerospace-folktales",
        cluster_id: "work-and-family",
        phase: "direct_alignment",
        target_work_id: "aerospace-folktales-work",
        reasoning: "The catalog record describes the Clark library copy of the journey's named work.",
        evidence_grade: "primary",
        citation_ids: ["clark-catalog"],
        review: {
          status: "approved",
          reviewer: "ShelfSignals editorial review",
          reviewed_at: "2026-07-14T00:00:00Z"
        }
      }
    ],
    editorial: {
      editor: "ShelfSignals editorial review",
      reviewed_at: "2026-07-14T00:00:00Z",
      version: "1.0.0"
    }
  };
}

test("journey index advertises only published lazy manifests", () => {
  const parsed = parseJourneyIndex(validJourneyIndex());
  assert.equal(parsed.rejected, false);
  assert.deepEqual(parsed.journeys.map(journey => journey.id), ["aerospace-folktales"]);
  assert.equal(parsed.journeys[0].manifest_ref, "journeys/aerospace-folktales.json");
  assert.ok(parsed.warnings.some(warning => warning.code === "unpublished_journey_omitted"));
});

test("published journey cross-checks photographs, citations, clusters, and catalog identity", () => {
  const parsed = parseJourneyManifest(validJourneyManifest(), { catalogIds: CATALOG_IDS });
  assert.equal(parsed.rejected, false, JSON.stringify(parsed.errors));
  assert.equal(parsed.photographs[0].display_status, "cleared");
  assert.equal(parsed.clusters[0].association_ids[0], "library-work-identity");
  assert.equal(parsed.associations[0].claim_kind, "identity_anchor");
  assert.equal(associationClaimLabel(parsed.associations[0]), "Work represented in the library");
});

test("rights-pending journey photographs remain cited metadata without leaking image URLs", () => {
  const raw = validJourneyManifest();
  raw.photographs[0].rights = {
    public_display: false,
    basis: "pending",
    credit_line: "Rights pending"
  };
  const parsed = parseJourneyManifest(raw, { catalogIds: CATALOG_IDS });
  assert.equal(parsed.rejected, false);
  assert.equal(parsed.photographs[0].display_status, "metadata_only");
  assert.equal(parsed.photographs[0].image, null);
  assert.ok(parsed.warnings.some(warning => warning.code === "rights_gated"));
});

test("locally served journey imagery requires derivative permission", () => {
  const raw = validJourneyManifest();
  raw.photographs[0].image.url = "images/journeys/aerospace.jpg";
  raw.photographs[0].image.thumbnail_url = "images/journeys/aerospace-thumb.jpg";
  const denied = parseJourneyManifest(raw, { catalogIds: CATALOG_IDS });
  assert.equal(denied.rejected, true);
  assert.ok(denied.errors.some(error => error.code === "uncleared_derivative"));

  raw.photographs[0].rights.derivatives_allowed = true;
  const untracked = parseJourneyManifest(raw, { catalogIds: CATALOG_IDS });
  assert.equal(untracked.rejected, true);
  assert.ok(untracked.errors.some(error => error.code === "missing_derivative_checksum"));
  raw.photographs[0].image.sha256 = `sha256:${"a".repeat(64)}`;
  raw.photographs[0].image.thumbnail_sha256 = `sha256:${"b".repeat(64)}`;
  raw.photographs[0].image.retrieved_at = "2026-07-13";
  raw.photographs[0].image.derivative = {
    source_dimensions: [2400, 1600],
    transform: "Proportional long-edge resize; no crop.",
    tooling: "Fixture encoder",
    reproducibility_status: "fixture"
  };
  assert.equal(parseJourneyManifest(raw, { catalogIds: CATALOG_IDS }).rejected, false);
});

test("published journey rejects missing provenance, unknown records, and unreviewed associations", () => {
  const noLocator = validJourneyManifest();
  noLocator.citations[0].locator = "";
  assert.equal(parseJourneyManifest(noLocator, { catalogIds: CATALOG_IDS }).rejected, true);

  const unknownBook = validJourneyManifest();
  unknownBook.associations[0].catalog_id = "not-a-catalog-record";
  assert.equal(parseJourneyManifest(unknownBook, { catalogIds: CATALOG_IDS }).rejected, true);

  const unreviewed = validJourneyManifest();
  unreviewed.associations[0].review.status = "suggested";
  assert.equal(parseJourneyManifest(unreviewed, { catalogIds: CATALOG_IDS }).rejected, true);
});

test("contextual relationships cannot acquire generated influence language", () => {
  const approvedContext = {
    claim_kind: "contextual_proximity",
    evidence_grade: "contextual",
    reasoning: "The books share a documented shelf location.",
    citation_ids: ["clark-catalog"],
    review: { status: "approved", reviewer: "Researcher", reviewed_at: "2026-07-14T00:00:00Z" }
  };
  assert.equal(canClaimInfluence(approvedContext), false);
  assert.equal(associationClaimLabel(approvedContext), "Contextual proximity");
  assert.doesNotMatch(associationClaimLabel(approvedContext), /inspir|influenc/i);

  const weakInfluence = { ...approvedContext, claim_kind: "documented_influence", evidence_grade: "scholarly" };
  assert.equal(canClaimInfluence(weakInfluence), false);
  assert.doesNotMatch(associationClaimLabel(weakInfluence), /inspir|influenc/i);

  const documented = { ...approvedContext, claim_kind: "documented_influence", evidence_grade: "archival" };
  assert.equal(canClaimInfluence(documented), true);
  assert.equal(associationClaimLabel(documented), "Documented influence");
});

test("public association filter omits machine suggestions and unsupported influence claims", () => {
  const base = validJourneyManifest().associations[0];
  const suggested = clone(base);
  suggested.id = "machine-suggestion";
  suggested.review.status = "suggested";
  const weak = clone(base);
  weak.id = "weak-influence";
  weak.claim_kind = "documented_influence";
  weak.evidence_grade = "scholarly";
  const manifest = {
    publication_status: "published",
    associations: [
      { ...base, claim_kind: "identity_anchor" },
      suggested,
      weak
    ]
  };
  assert.deepEqual(getPublicAssociations(manifest).map(association => association.id), ["library-work-identity"]);
});
