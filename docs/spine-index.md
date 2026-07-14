# Compact spine index

`data/spine_index.json` is the shelf renderer's separately loadable geometry and evidence-contract layer. It is derived from the full `data/book_profiles.json` provenance manifest but omits catalog wording and fields that a shelf does not need. The current artifact is about 793 KB, less than 12% of the 6.8 MB full profile manifest, and contains a contract for all 11,176 catalog records.

## Evidence boundary

The compact per-record values are:

- `h`: height in centimeters stated in Clark's physical-description field;
- `w`: front width in centimeters stated by Clark, when present;
- `d`: a bounded interface estimate derived from Clark-stated page/leaf extent, always decoded with status `estimated`, method `catalog-extent-model-v1`, and the text `not measured`;
- `b`: a binding term explicitly stated by Clark;
- `g`: a housing term explicitly stated by Clark, kept separate from binding;
- `o`: a controlled object-form code, including an explicit honest `unknown`;
- `q`: a validated record-warning bitset.

It never reads a cover image, never uses optical analysis to infer geometry, and never imports provider-edition measurements. A provider cover cannot establish thickness, material, wear, jacket presence, or any other copy-specific property. A future local capture or measurement must use a new evidence status and must not silently replace this model.

Every indexed record links back to `book_profiles.json#<Alma ID>` for the complete Clark physical-description wording. The 75 records without a defensible height or depth retain their object-form and warning contract while using neutral renderer geometry; the index does not invent a factual width or depth.

## Per-record evidence contract

`getRecordSpineProfile` expands every compact row into an auditable record containing:

- `representation_type: synthetic_metadata_derived`, which prevents the shelf from masquerading as copy photography;
- `axis_evidence` for height, width, and depth, each with its selected source, rank, full precedence order, scope, factual-metadata status, and explicit `copy_specific: false`;
- controlled `object_form` with `stated`, `derived`, or `unknown` evidence status and its catalog basis;
- separate nullable `binding` and `housing` records;
- metadata-only rights with a Clark credit line, public-display state, `reuse_status: not_assessed`, and image rights marked not applicable;
- decoded record warnings plus the shared synthetic-representation warning.

Axis precedence is explicit. Local Clark-copy measurement ranks first, Clark catalog statements second, conflict-free exact-edition statements third, and neutral renderer defaults last. Depth alone admits `catalog_extent_model` before the neutral fallback. The current index selects only Clark catalog statements or the Clark-extent model; it contains no provider geometry. Cover-image optical inference is forbidden for every axis.

Warnings are calm evidence notes rather than errors: unavailable axes, modeled depth not being measured, unknown form, multi-object sets without one defensible depth, and folded presentation are all visible to the consuming interface. `canDisplaySpine` is the runtime rights gate and returns true only for a validated indexed record with the expected metadata-only rights and representation type.

## Compact encoding

Alma's shared `alma` prefix is stored once. An exact measurement is a scalar; a catalog range is `[midpoint, minimum, maximum]`. Modeled depth is `[midpoint, minimum, maximum, page-equivalent basis]`. Binding, housing, and object form have separate stable code tables. Record warnings use documented powers-of-two flags and are recomputed during validation so a stale warning bitset rejects the index. Each record stays on one JSON line so changes remain reviewable.

The index is catalog-bound: its source block includes the Clark dataset checksum and record count, plus the checksum and schema of the full physical-profile manifest. `js/spines.js` rejects the complete index if those identities are stale, if an unknown record appears, if the representation or rights contract changes, or if an item attempts to carry unsupported fields such as a cover URL.

## Lazy runtime integration

Load the index only when a physical/spine shelf is first requested:

```js
import { canDisplaySpine, getRecordSpineProfile, loadSpineIndex } from "./spines.js";

const spineIndex = await loadSpineIndex("data/spine_index.json", {
  catalogIds: records.map(record => record.id),
  datasetSha256: catalogDatasetSha256
});

const physicalProfile = getRecordSpineProfile(record, spineIndex);
if (canDisplaySpine(physicalProfile)) renderSyntheticSpine(physicalProfile);
```

`getRecordSpineProfile` decodes one record at a time into the existing `dimensions`, `binding`, and `thickness` shape used by the visual shelf renderer, augmented with the strict evidence contract above. The primary interface loads this compact index only when Physical view or a physical-evidence drawer is requested. It compares the source SHA to the exact bytes of the active catalog. Cover imagery and provider-edition geometry are never passed to the shelf renderer, and Physical view alone does not fetch `book_editions.json`.

The drawer exposes the selected evidence and full precedence for each axis, controlled object form and basis, binding and housing as separate fields, representation type, metadata-only rights, provenance reference, and every decoded warning. A failed or unavailable compact record receives neutral dashed geometry plus a visible unavailable-evidence marker; it never inherits ordinary book styling. The complete `book_profiles.json` remains a separate provenance artifact for deeper research and is not part of first render.

## Regeneration and verification

From the repository root:

```bash
python3 scripts/build_spine_index.py --self-test
python3 scripts/build_spine_index.py
node --test scripts/spine_index_unit_tests.mjs
```

Generation is deterministic for a fixed `book_profiles.json`: the timestamp is inherited from that source snapshot, records use stable code tables, and the output stores the input checksum. The unit tests assert full-record geometry parity, source scope, axis precedence, object form, binding/housing separation, representation type, rights gating, warnings, the no-cover boundary, fail-closed catalog identity, depth labeling, and a size ceiling.
