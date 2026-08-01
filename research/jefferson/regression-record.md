# Jefferson extractor regression record

## Stable catalog pagination

Defect: Offset pagination without an explicit sort silently duplicated and omitted instances.

Trigger: The exact LOC query was harvested with offset pagination and no sort.

Expected: 2,748 reported rows map to 2,748 unique instance UUIDs.

Observed: The live unsorted snapshot had 2,748 rows but only 2,444 unique UUIDs.

Chosen test layer: URL/query contract unit test plus active-snapshot identity gates.

Fixture and provenance: Synthetic offset URL assertions; raw live attempt remains ignored and is classified as an inactive diagnostic generation.

Red evidence: The live unsorted count/UUID discrepancy above.

Fix: Require `sortby title/sort.ascending`, validate every page and identity, and activate a refresh generation only after it passes.

Green evidence: `test_catalog_query_has_explicit_stable_sort_for_offset_pagination`, stale-page tests, and the current 2,748/2,748 validation result.

## Partial and transient HTTP responses

Defect: A truncated body or transient 5xx could abort a long harvest or risk a partial cache; caught HTTP errors could retain response resources.

Trigger: The live loc.gov run encountered an incomplete body and an HTTP 520.

Expected: Partial bytes never reach the cache, retryable failures retry, and response objects close.

Observed: Live exceptions interrupted the first attempts. Red-state source rewriting was unnecessary because the live failures supplied the failing evidence.

Chosen test layer: HTTP-client unit tests with synthetic response objects.

Fixture and provenance: No live response bodies; synthetic `IncompleteRead`, HTTP 520, and guest-auth HTTP errors.

Fix: Retry `HTTPException` and retryable 5xx responses, write only complete bodies atomically, and close HTTP-error responses on all paths.

Green evidence: `test_truncated_response_retries_without_committing_partial_cache`, `test_http_520_is_retried_as_transient_server_failure`, and `test_guest_authentication_closes_http_error_response`.

## Relationship and identifier semantics

Defect: Untyped note numerals, suffixes, ranges, and exhibit language produced
false Sowerby/ownership assertions; SQLite multiplied catalog and digital IDs
within one Sowerby row and initially omitted the bounded assessment scope/status
carried by JSONL.

Trigger: Free-text notes such as “not in Sowerby,” dates after “Sowerby,” suffixed IDs, bound ranges, and “LC copy forms part of the Jefferson Exhibit Collection.”

Expected: Only typed evidence creates an asserted edge; collection membership is not ownership; catalog/digital pairs require an intersecting normalized LCCN.

Observed: Earlier derivatives overlinked free-text integers, labeled exhibit membership as ownership, and contained 406 SQLite catalog/digital rows without an intersecting LCCN.

Chosen test layer: Normalizer/crosswalk unit tests plus SQLite contract test.

Fixture and provenance: Synthetic MARC 510, suffix/range, exhibit-note, multi-catalog, and digital-LCCN fixtures.

Fix: Preserve expanded notes and index numerals as unvalidated candidates, accept
only one plain base-integer MARC 510 for pilot links, label all exact records as
collection membership, materialize only explicit catalog→LCCN→digital pairs,
and carry assessment status/scope plus distinct source-layer units into SQLite.

Green evidence: `test_exact_collection_or_exhibit_note_does_not_assert_jefferson_ownership`, `test_sowerby_suffixes_and_ranges_are_not_collapsed_to_base_entry_links`, `test_crosswalk_uses_explicit_marc_510_and_lccn_only`, and `test_sqlite_crosswalk_does_not_invent_catalog_digital_pairs`.

## Derivative privacy and schema drift

Defect: A denylist-only derivative retained operational catalog fields, and the
first allowlisted implementation still bypassed that boundary for bounded MARC.

Trigger: Expanded public-application responses contained barcodes,
administrative/circulation notes, tags, staff-only nodes, internal user IDs, and
fields not reviewed for publication; source MARC contained local 9XX UUID and
workflow fields.

Expected: Raw evidence remains local; derivatives fail closed to a reviewed field set.

Observed: The pre-fix derivative retained 1,528 barcode fields and thousands of
administrative-note fields. A later audit also found tags 952/955/999 and other
local 9XX data in the bounded MARC projection.

Chosen test layer: Recursive sanitizer and allowlist unit test plus full-package audit.

Fixture and provenance: Synthetic restricted fields; no protected live value is committed to a test fixture.

Fix: Remove restricted/suppressed nodes and known operational fields, apply
explicit instance/holding/item allowlists, and keep lossless MARC in ignored raw
cache while publishing only an ordered bibliographic allowlist that excludes all
9XX fields, subfield `9`, and explicitly private 541/561/583 notes.

Green evidence: `test_staff_only_catalog_nodes_and_internal_user_ids_are_not_republished`,
`test_public_marc_projection_removes_local_and_private_fields`; the final package
audit found zero restricted keys, local MARC fields, and allowlist violations.

## Retrieval evidence integrity

Defect: Cache hits and package builds trusted response bodies without checking
them against the byte count and SHA-256 recorded at retrieval.

Trigger: A cached body is changed after its sidecar is written but remains valid
JSON/XML, so ordinary parsing still succeeds.

Expected: A changed or unattested network-source body cannot inherit the original
retrieval URL/time as if the evidence were unchanged.

Observed: Static review found the missing comparison; all 406 live sidecars still
matched, so no harvested evidence had actually drifted.

Chosen test layer: HTTP cache-hit unit test, build preflight contract test, and
full-package source-manifest audit.

Fixture and provenance: A synthetic valid-JSON body is modified after its
synthetic sidecar is recorded.

Fix: Verify sidecar byte count and SHA-256 on every cache hit and before any build
loads source data; reject unattested network-source files when sidecars are in use.

Green evidence: `test_cache_hit_rejects_body_that_no_longer_matches_retrieval_sidecar`,
`test_build_rejects_valid_json_tampered_after_retrieval`, and the final 406/406
sidecar audit.

## Snapshot and hierarchy validity

Defect: Stale extra cache pages could mix generations, empty/invalid snapshots could emit outputs, incomplete requested digital details could be activated, and chapter XXX was assigned to Philosophy rather than Fine Arts.

Trigger: Reusing mutable cache directories, treating every absent layer as “not applicable,” activating before checking requested detail files, or validating chapter numbers without checking faculty boundaries.

Expected: Active generations contain exactly their declared pages, identities, and requested details; an empty or invalid input produces no new manifest; chapters 30–44 are Fine Arts.

Observed: Static review found the cache-generation hazard, and the prior hierarchy output mislabeled chapter XXX. Reverting the active worktree was unnecessary; small synthetic fixtures reproduce both contracts safely.

Chosen test layer: Loader/build contract tests and TOC parser unit test.

Fixture and provenance: Synthetic stale pages, count mismatch, and minimal LOC-shaped TOC text.

Fix: Isolated pending/active generations, exact page-set and requested-detail checks before activation, a required minimum-source invariant, fail-closed pre-build gates, and corrected independent faculty-boundary validation.

Green evidence: `test_active_snapshot_loaders_reject_stale_extra_pages`, `test_build_fails_closed_before_manifest_on_invalid_exact_snapshot`, `test_build_rejects_an_empty_all_not_applicable_package`, `test_digital_detail_failure_does_not_activate_incomplete_snapshot`, `test_search_only_refresh_does_not_inherit_old_detail_requirement`, and `test_loc_sowerby_toc_and_index_remain_reference_layers`.

## Broader gates and residual risk

Broader gates: Jefferson extractor tests, all repository Python unit suites, syntax compilation, deterministic double-build comparison, manifest/source hash audit, SQLite integrity/count/FTS checks, privacy/allowlist scan, and `git diff --check`.

Residual risk: The current catalog API is not documented for supported bulk use; source MARC covers only 25 stable sample records; the full Sowerby concordance, suffix/addition model, and curator-maintained copy-status ledger remain unavailable; item-level rights review remains required; Monticello content is absent pending permission and completeness evidence.
