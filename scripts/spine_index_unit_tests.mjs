import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { readFile, stat } from "node:fs/promises";
import test from "node:test";

import {
  SPINE_AXIS_PRECEDENCE,
  SPINE_BINDING_CODES,
  SPINE_DEPTH_METHOD,
  SPINE_INDEX_SCHEMA,
  SPINE_HOUSING_CODES,
  SPINE_OBJECT_FORM_CODES,
  SPINE_REPRESENTATION_TYPE,
  SPINE_RIGHTS,
  SPINE_WARNING_BITS,
  canDisplaySpine,
  getRecordSpineProfile,
  parseSpineIndex
} from "../docs/js/spines.js";

const dataDirectory = new URL("../docs/data/", import.meta.url);
const [catalogText, profileBytes, indexText] = await Promise.all([
  readFile(new URL("sekula_index.json", dataDirectory), "utf8"),
  readFile(new URL("book_profiles.json", dataDirectory)),
  readFile(new URL("spine_index.json", dataDirectory), "utf8")
]);
const catalog = JSON.parse(catalogText);
const fullProfiles = JSON.parse(profileBytes.toString("utf8"));
const rawIndex = JSON.parse(indexText);
const catalogIds = catalog.map(record => record.id);

function fixture() {
  return {
    schema: SPINE_INDEX_SCHEMA,
    version: "1.0.0",
    generated_at: "2026-07-13T04:00:00Z",
    source: {
      catalog: "Clark Library Catalog",
      dataset: "sekula_index.json",
      dataset_sha256: `sha256:${"a".repeat(64)}`,
      record_count: 2,
      physical_description_field: "formats",
      profile_dataset: "book_profiles.json",
      profile_dataset_sha256: `sha256:${"b".repeat(64)}`,
      profile_schema: "shelfsignals-book-profiles@1"
    },
    policy: {},
    contract: {
      representation_type: SPINE_REPRESENTATION_TYPE,
      scope: "clark_catalog_metadata",
      rights: { ...SPINE_RIGHTS },
      axis_precedence: Object.fromEntries(Object.entries(SPINE_AXIS_PRECEDENCE).map(([axis, order]) => [axis, [...order]])),
      shared_warnings: [{
        code: "synthetic_metadata_representation",
        message: "Shelf geometry is a metadata-derived representation, not a photograph or measurement of Clark's copy."
      }]
    },
    encoding: {
      id_prefix: "alma",
      fields: {},
      binding_codes: { ...SPINE_BINDING_CODES },
      housing_codes: { ...SPINE_HOUSING_CODES },
      object_form_codes: Object.fromEntries(Object.entries(SPINE_OBJECT_FORM_CODES).map(([code, descriptor]) => [code, { ...descriptor }])),
      warning_bits: Object.fromEntries(Object.entries(SPINE_WARNING_BITS).map(([code, bit]) => [String(bit), code]))
    },
    summary: {
      catalog_records: 2,
      indexed_records: 1,
      defaulted_unavailable: 1,
      geometry_unavailable: 0,
      height_stated: 1,
      width_stated: 1,
      depth_estimated: 1,
      binding_stated: 1,
      housing_stated: 0,
      object_form_unknown: 0,
      folded_presentation: 0
    },
    items: {
      "1": { h: 24, w: [18, 17, 19], d: [2, 1.5, 2.5, 300], b: 4, o: 1, q: 4 }
    }
  };
}

test("the committed spine index is compact, catalog-bound, and covers every record", async () => {
  const parsed = parseSpineIndex(rawIndex, {
    catalogIds,
    datasetSha256: rawIndex.source.dataset_sha256
  });
  assert.equal(parsed.rejected, false, parsed.errors?.join(", "));
  assert.equal(parsed.schema, SPINE_INDEX_SCHEMA);
  assert.equal(parsed.source.catalog, "Clark Library Catalog");
  assert.equal(parsed.source.record_count, catalog.length);
  assert.equal(parsed.summary.catalog_records, 11176);
  assert.equal(parsed.summary.indexed_records, 11176);
  assert.equal(parsed.summary.defaulted_unavailable, 0);
  assert.equal(parsed.summary.geometry_unavailable, 75);
  assert.equal(parsed.summary.height_stated, 10956);
  assert.equal(parsed.summary.width_stated, 644);
  assert.equal(parsed.summary.depth_estimated, 10006);
  assert.equal(parsed.summary.binding_stated, 4);
  assert.equal(parsed.summary.housing_stated, 21);
  assert.equal(parsed.summary.object_form_unknown, 97);

  const expectedProfileDigest = createHash("sha256").update(profileBytes).digest("hex");
  assert.equal(parsed.source.profile_dataset_sha256, `sha256:${expectedProfileDigest}`);

  const [indexStats, profileStats] = await Promise.all([
    stat(new URL("spine_index.json", dataDirectory)),
    stat(new URL("book_profiles.json", dataDirectory))
  ]);
  assert.ok(indexStats.size < 820_000, `spine index unexpectedly grew to ${indexStats.size} bytes`);
  assert.ok(indexStats.size < profileStats.size * 0.12, "compact index should remain below 12% of the full provenance manifest");
});

test("one-record decoding preserves stated dimensions and labels modeled depth", () => {
  const parsed = parseSpineIndex(rawIndex, { catalogIds });
  const aerospace = getRecordSpineProfile({ id: "alma991002293459708431" }, parsed);
  assert.equal(aerospace.status, "indexed");
  assert.equal(aerospace.representation_type, SPINE_REPRESENTATION_TYPE);
  assert.equal(aerospace.source_scope, "clark_catalog_record");
  assert.equal(canDisplaySpine(aerospace), true);
  assert.deepEqual(aerospace.rights, SPINE_RIGHTS);
  assert.deepEqual(aerospace.object_form, {
    term: "paged_object",
    evidence_status: "derived",
    basis: "clark_catalog_extent_semantics",
    copy_specific: false
  });
  assert.equal(aerospace.dimensions.height_cm, 29);
  assert.equal(aerospace.dimensions.status, "stated");
  assert.equal(aerospace.thickness.value_cm, 0.62);
  assert.equal(aerospace.thickness.status, "estimated");
  assert.equal(aerospace.thickness.method, SPINE_DEPTH_METHOD);
  assert.equal(aerospace.thickness.basis_pages, 56);
  assert.equal(aerospace.copy_specific_depth, false);
  assert.match(aerospace.thickness.evidence, /not measured/i);
  assert.equal(aerospace.provenance_ref, "book_profiles.json#alma991002293459708431");
  assert.equal(aerospace.axis_evidence.height.selected_source, "clark_catalog_stated");
  assert.equal(aerospace.axis_evidence.height.precedence_rank, 2);
  assert.equal(aerospace.axis_evidence.height.copy_specific, false);
  assert.equal(aerospace.axis_evidence.width.selected_source, "neutral_renderer_default");
  assert.equal(aerospace.axis_evidence.depth.selected_source, "catalog_extent_model");
  assert.equal(aerospace.axis_evidence.depth.precedence_rank, 4);
  assert.equal(aerospace.axis_evidence.depth.factual_metadata, false);
  assert.ok(aerospace.warnings.some(warning => warning.code === "synthetic_metadata_representation"));
  assert.ok(aerospace.warnings.some(warning => warning.code === "depth_not_measured"));
  assert.ok(aerospace.warnings.some(warning => warning.code === "width_unavailable"));

  const multivolume = getRecordSpineProfile({ id: "alma991002311449708431" }, parsed);
  assert.deepEqual(
    [multivolume.dimensions.height_cm, multivolume.dimensions.height_min_cm, multivolume.dimensions.height_max_cm],
    [32, 31, 33]
  );
  assert.equal(multivolume.object_form.term, "multi_volume_set");
  assert.equal(multivolume.thickness, undefined, "multi-volume records must not receive one invented spine depth");
  assert.ok(multivolume.warnings.some(warning => warning.code === "multi_object_no_single_depth"));

  const bound = getRecordSpineProfile({ id: "alma991002092679708431" }, parsed);
  assert.equal(bound.binding.term, "paperback");
  assert.equal(bound.housing, null);
  const housed = getRecordSpineProfile({ id: "alma991002003579708431" }, parsed);
  assert.equal(housed.binding, null);
  assert.equal(housed.housing.term, "slipcase");

  const unavailable = getRecordSpineProfile({ id: "alma-not-present" }, parsed);
  assert.equal(unavailable.status, "unavailable");
  assert.equal(unavailable.representation_type, "neutral_placeholder");
  assert.equal(canDisplaySpine(unavailable), false);
  assert.ok(unavailable.warnings.some(warning => warning.code === "spine_record_unavailable"));
});

test("compact decoding has full geometry parity with the Clark profile manifest", () => {
  const parsed = parseSpineIndex(rawIndex, { catalogIds });
  for (const record of catalog) {
    const source = fullProfiles.items[record.id];
    const compact = getRecordSpineProfile(record, parsed);
    if (source.dimensions) {
      assert.deepEqual(compact.dimensions, {
        height_cm: source.dimensions.height_cm,
        height_min_cm: source.dimensions.height_min_cm,
        height_max_cm: source.dimensions.height_max_cm,
        ...(source.dimensions.width_cm == null ? {} : {
          width_cm: source.dimensions.width_cm,
          width_min_cm: source.dimensions.width_min_cm,
          width_max_cm: source.dimensions.width_max_cm
        }),
        status: "stated",
        order: "height_x_width",
        presentation: source.dimensions.presentation
      }, record.id);
    } else {
      assert.equal(compact.dimensions, undefined, record.id);
    }
    if (source.thickness) {
      assert.deepEqual({
        status: compact.thickness.status,
        value_cm: compact.thickness.value_cm,
        min_cm: compact.thickness.min_cm,
        max_cm: compact.thickness.max_cm,
        basis_pages: compact.thickness.basis_pages,
        method: compact.thickness.method
      }, source.thickness, record.id);
    } else {
      assert.equal(compact.thickness, undefined, record.id);
    }
    const sourceTerm = source.binding?.term;
    const housingTerms = new Set(["portfolio", "slipcase", "folder", "envelope", "binder", "case", "box", "container"]);
    if (sourceTerm && housingTerms.has(sourceTerm)) {
      assert.equal(compact.binding, null, record.id);
      assert.deepEqual(compact.housing, { status: "stated", term: sourceTerm, source_scope: "clark_catalog_record" }, record.id);
    } else if (sourceTerm) {
      assert.deepEqual(compact.binding, { status: "stated", term: sourceTerm, source_scope: "clark_catalog_record" }, record.id);
      assert.equal(compact.housing, null, record.id);
    } else {
      assert.equal(compact.binding, null, record.id);
      assert.equal(compact.housing, null, record.id);
    }
    assert.equal(compact.representation_type, SPINE_REPRESENTATION_TYPE, record.id);
    assert.equal(compact.rights.scope, "metadata_only", record.id);
    assert.equal(compact.axis_evidence.height.cover_image_inference, false, record.id);
    assert.ok(Array.isArray(compact.warnings) && compact.warnings.length >= 2, record.id);
  }
});

test("encoded items cannot carry covers, provider geometry, or unlabeled depth", () => {
  const parsed = parseSpineIndex(rawIndex, { catalogIds });
  for (const item of Object.values(parsed.items)) {
    assert.ok(Object.keys(item).every(key => ["h", "w", "d", "b", "g", "f", "o", "q"].includes(key)));
    assert.equal(Number.isInteger(item.o), true);
    assert.equal(Number.isInteger(item.q), true);
  }

  const external = fixture();
  external.items["1"].image = "https://example.test/cover.jpg";
  assert.equal(parseSpineIndex(external, { catalogIds: ["alma1", "alma2"] }).rejected, true);

  const malformedDepth = fixture();
  malformedDepth.items["1"].d = [2, 1.5, 2.5];
  assert.equal(parseSpineIndex(malformedDepth, { catalogIds: ["alma1", "alma2"] }).rejected, true);

  const forgedWarnings = fixture();
  forgedWarnings.items["1"].q = 0;
  assert.equal(parseSpineIndex(forgedWarnings, { catalogIds: ["alma1", "alma2"] }).rejected, true);
});

test("catalog identity and source scope are fail-closed", () => {
  const valid = parseSpineIndex(fixture(), { catalogIds: ["alma1", "alma2"] });
  assert.equal(valid.rejected, false);
  assert.equal(getRecordSpineProfile({ id: "alma1" }, valid).binding.term, "paperback");

  const stale = fixture();
  assert.equal(parseSpineIndex(stale, { datasetSha256: `sha256:${"c".repeat(64)}` }).rejected, true);

  const wrongCatalog = fixture();
  wrongCatalog.source.catalog = "Cover provider";
  assert.equal(parseSpineIndex(wrongCatalog).rejected, true);

  const wrongRepresentation = fixture();
  wrongRepresentation.contract.representation_type = "photographic_spine";
  assert.equal(parseSpineIndex(wrongRepresentation).rejected, true);

  const blockedRights = fixture();
  blockedRights.contract.rights.public_display = false;
  assert.equal(parseSpineIndex(blockedRights).rejected, true);

  const mergedHousing = fixture();
  mergedHousing.encoding.housing_codes["1"] = "paperback";
  assert.equal(parseSpineIndex(mergedHousing).rejected, true);

  const objectFormWithAsset = fixture();
  objectFormWithAsset.encoding.object_form_codes["1"].image_url = "https://example.test/not-allowed.jpg";
  assert.equal(parseSpineIndex(objectFormWithAsset).rejected, true);

  const unknownId = fixture();
  unknownId.items["999"] = unknownId.items["1"];
  unknownId.summary.indexed_records = 2;
  unknownId.summary.defaulted_unavailable = 0;
  assert.equal(parseSpineIndex(unknownId, { catalogIds: ["alma1", "alma2"] }).rejected, true);
});
