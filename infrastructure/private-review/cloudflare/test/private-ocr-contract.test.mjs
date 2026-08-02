import assert from "node:assert/strict";
import test from "node:test";

import {
  PRIVATE_OCR_SCHEMA,
  safeLocUrl,
  validateOcrManifest,
} from "../../site-assets/private-ocr-contract.js";


const digest = `sha256:${"a".repeat(64)}`;

function fixture() {
  const entries = [];
  for (let chapter = 1; chapter <= 44; chapter += 1) {
    for (let offset = 0; offset < 3; offset += 1) {
      const number = (chapter - 1) * 3 + offset + 1;
      const direct = number <= 5;
      entries.push({
        record_id: `jefferson-sowerby-${number}`,
        sowerby_number: number,
        title: `Source title ${number}`,
        title_status: "source_backed",
        faculty: chapter <= 15 ? "History" : chapter <= 29 ? "Philosophy" : "Fine Arts",
        chapter_number: chapter,
        chapter_label: `Chapter ${chapter}`,
        volume: 1,
        terminal_pdf_page: 50,
        pdf_url: "https://tile.loc.gov/storage-services/service/rbc/rbc0001/2007/2007jeffcat1/2007jeffcat1.pdf",
        section: {
          type: "sowerby_entry_block",
          classification_status: "machine_detected_unreviewed",
          transcript: `Machine OCR evidence for entry ${number}.`,
          transcript_truncated: false,
          line_count: 2,
          mean_confidence: 91.2,
          marker_confidence: 94.1,
          title_confidence: 90,
        },
        snapshots: [{
          pdf_page: 50,
          region_pct: { x: 1, y: 2, width: 50, height: 20 },
          image_url: "https://tile.loc.gov/image-services/iiif/service:rbc:rbc0001:2007:2007jeffcat1:00551029/pct:1,2,50,20/1000,/0/default.jpg",
          full_page_image_url: "https://tile.loc.gov/image-services/iiif/service:rbc:rbc0001:2007:2007jeffcat1:00551029/full/pct:100/0/default.jpg",
          line_count: 2,
          mean_confidence: 91.2,
        }],
        event_contexts: [{
          event_id: `event-${chapter}`,
          title: "Event",
          date_label: "1776",
          relationship: direct ? "documented_interaction" : "chapter_context",
          context_score: direct ? 95 : 70,
          direct_relation: direct,
          event_use_status: direct ? "documented_interaction" : "not_established",
          use_confidence_score: direct ? 90 : null,
        }],
      });
    }
  }
  return {
    schema: PRIVATE_OCR_SCHEMA,
    collection_id: "jefferson",
    corpus_id: "historical",
    audience: "authenticated_review",
    generated_at: "2026-08-02T14:10:00Z",
    source: {
      authority: "Library of Congress",
      item_url: "https://www.loc.gov/item/52060000/",
      rights_statement_url: "https://www.loc.gov/item/52060000/",
      rights_clearance: "not granted; item-level assessment remains required",
      source_identity_sha256: digest,
      ocr_manifest_sha256: digest,
      historical_core_sha256: digest,
      insight_graph_sha256: digest,
    },
    methodology: {
      selection: "Three entries per chapter.",
      sectioning: "Machine detected.",
      visual_evidence: "LOC IIIF regions.",
      confidence: "OCR mechanics only.",
      use_boundary: "Context is not use.",
    },
    coverage: {
      historical_entries: 4928,
      page_resolved_entries: 4675,
      pilot_entries: 132,
      chapters: 44,
      entries_per_chapter: 3,
      section_regions: 132,
      source_backed_titles: 132,
      direct_documentary_records: 5,
    },
    entries,
  };
}


test("private OCR contract binds 132 unique entries across all chapters", () => {
  const parsed = validateOcrManifest(fixture());
  assert.equal(parsed.entryById.size, 132);
  assert.equal(parsed.entryById.get("jefferson-sowerby-1").chapter_number, 1);
  assert.equal(parsed.entryById.get("jefferson-sowerby-132").chapter_number, 44);
});


test("private OCR contract rejects an external or malformed image source", () => {
  const raw = fixture();
  raw.entries[0].snapshots[0].image_url = "https://example.org/private.jpg";
  assert.throws(() => validateOcrManifest(raw), /entry set is invalid/);
  assert.equal(safeLocUrl("https://tile.loc.gov/image-services/iiif/test/full/1000,/0/default.jpg", { image: true }), true);
  assert.equal(safeLocUrl("https://www.loc.gov/item/52060000/", { image: true }), false);
  assert.equal(safeLocUrl("https://tile.loc.gov:444/image-services/iiif/test/full/1000,/0/default.jpg", { image: true }), false);
  assert.equal(safeLocUrl("https://tile.loc.gov/image-services/iiif/test/full/1000,/0/default.jpg?redirect=https://evil.example", { image: true }), false);
  assert.equal(safeLocUrl("https://user@www.loc.gov/item/52060000/"), false);

  const mismatchedPage = fixture();
  mismatchedPage.entries[0].snapshots[0].full_page_image_url = "https://tile.loc.gov/image-services/iiif/service:rbc:rbc0001:2007:2007jeffcat1:00561030/full/pct:100/0/default.jpg";
  assert.throws(() => validateOcrManifest(mismatchedPage), /entry set is invalid/);
});


test("private OCR contract rejects coverage drift and duplicate identities", () => {
  const wrongCount = fixture();
  wrongCount.coverage.section_regions = 131;
  assert.throws(() => validateOcrManifest(wrongCount), /coverage is inconsistent/);

  const duplicate = fixture();
  duplicate.entries[1] = structuredClone(duplicate.entries[0]);
  assert.throws(() => validateOcrManifest(duplicate), /duplicate records/);
});
