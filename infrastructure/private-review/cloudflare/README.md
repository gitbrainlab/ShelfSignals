# Authenticated Jefferson review gateway

This Worker serves a complete, immutable Shelf Signals review release from a
private R2 bucket. Cloudflare Access authenticates the reviewer before the
request reaches the Worker; the Worker then validates the Access JWT against
the account JWKS, checks its issuer and application audience, and applies a
second approved-email allowlist.

The public GitHub Pages deployment remains the home of public bibliographic
data. User photographs, rights-pending media, credentials, and authenticated
manifests must never be placed under `docs/` or committed to Git.

Build the bounded OCR evidence pilot, then the immutable review site before
upload. The pilot includes three page-resolved entries from each of the 44
Sowerby chapters (132 entries total), the five records carrying direct
documentary graph relationships, machine transcripts, and 192 LOC IIIF source
regions. The private bundle contains the index and source coordinates; its
inline scan regions are requested from the official public LOC image service.

```bash
python3 scripts/build_jefferson_private_ocr_review.py \
  --generated-at 2026-08-02T14:10:00Z
```

Then build the authenticated release:

```bash
python3 scripts/build_jefferson_private_review_release.py \
  --generated-at 2026-08-02T14:20:00Z
```

The release builder copies the public cinematic runtime, adds the authenticated
photo manifest and four sanitized images, adds the private OCR index, injects
the field-note gallery and OCR evidence lab, and writes
`research/jefferson/work/private-review/active.json`. The private OCR layer
also hides the public site's non-secure reviewer-code affordance and provides a
Cloudflare Access logout link. The output is git-ignored and must only be
uploaded to the private bucket.

## Cost and security boundary

The intended small review deployment fits comfortably within the current R2
and Access free allowances. R2 includes 10 GB-month of Standard storage, one
million Class A operations, and 10 million Class B operations per month. The
Zero Trust Free plan supports up to 50 active users. Pricing can change, so
confirm the current [R2 pricing](https://developers.cloudflare.com/r2/pricing/)
and [Zero Trust plan](https://www.cloudflare.com/plans/zero-trust-services/)
before provisioning. Cloudflare may still require payment details and R2
subscription activation during onboarding even when projected usage remains
inside the free allowance.

Do not assume that makes the complete gateway cost-free. Workers Free allows
100,000 requests per day but only 10 ms of CPU per invocation, and Cloudflare
notes that authentication workloads commonly use 10–20 ms. This Worker
performs JWT verification for every requested asset. Measure deployed CPU use;
reliable headroom may require the Workers Paid plan, whose current minimum is
$5 USD per month. See the current [Workers limits](https://developers.cloudflare.com/workers/platform/limits/)
and [Workers pricing](https://developers.cloudflare.com/workers/platform/pricing/).

The R2 bucket itself stays private; do not enable its `r2.dev` URL or attach a
public bucket domain. Access is the identity gateway, while JWT validation in
the Worker prevents a forged header from bypassing that gateway. This does not
provide DRM: an authorized reviewer can still save or screenshot a photograph.

The OCR index, coordinates, and contextual graph remain behind the gateway,
but the displayed scan regions are requested directly from the public
`tile.loc.gov` IIIF service. Those LOC-hosted bytes are not made private by this
gateway, and LOC can observe the reviewer request. Proxy or cache them only
after the relevant reuse and request-privacy requirements are approved.

AWS S3 remains a viable storage substitute, but it is not required for this
release. Preserve the same immutable `releases/<id>/` layout and place
CloudFront or another authenticating origin gateway in front of a private S3
bucket; never make the bucket or object URLs public. R2 is the default because
this small bundle fits its free storage/operation allowance and standard
Internet egress is not billed.

## Account setup

1. Create a Cloudflare account and choose the account `workers.dev` subdomain,
   or place a custom review hostname in a Cloudflare-managed zone.
2. Install the lockfile-pinned dependencies in this directory with `npm ci`.
3. Authenticate Wrangler locally with `npx wrangler login`. Never paste an API
   token into chat or commit one to this repository.
4. Create a private bucket:

   ```bash
   npx wrangler r2 bucket create shelfsignals-private-review
   ```

5. Return to the repository root and validate the ignored active release. A
   dry run performs the complete local inventory and hash preflight without
   invoking Wrangler or making any network call:

   ```bash
   python3 scripts/upload_jefferson_private_review_release.py \
     --bucket shelfsignals-private-review \
     --dry-run
   ```

6. Upload and independently verify the release:

   ```bash
   python3 scripts/upload_jefferson_private_review_release.py \
     --bucket shelfsignals-private-review
   ```

   The uploader uses the pinned local Wrangler executable. It uploads only
   `release.json` and the exact `site_files` declared by that manifest, always
   beneath `releases/<64-hex-release-id>/`. It never lists or deletes objects.
   After all uploads finish, it retrieves every object into a mode-`700`
   temporary directory and verifies its byte count and SHA-256 digest. Any
   local validation, Wrangler, download, or digest error fails the run. A
   failed run can leave a partial immutable prefix; fix the cause and rerun the
   same command. Do not switch `ACTIVE_RELEASE` until this command reports
   `"verified": true`.

7. Copy `wrangler.example.jsonc` to the ignored `wrangler.local.jsonc`. Set:

   - `ACTIVE_RELEASE` to the release's bare 64-character hexadecimal ID;
   - `TEAM_DOMAIN` to `https://<team>.cloudflareaccess.com`;
   - `POLICY_AUD` to the Access application's Audience tag; and
   - `ALLOWED_EMAILS` to a comma-separated reviewer allowlist.

8. Deploy once, then in **Workers & Pages → the Worker → Settings → Domains &
   Routes**, enable Cloudflare Access for the production `workers.dev` URL.
   Configure a default-deny Allow policy for the same exact reviewer emails.
   Email one-time PIN is the recommended simple passcode experience for this
   small review group; it must be added on new Zero Trust organizations because
   Cloudflare's identity provider is now the default. Set the Access session to
   four hours, avoid domain-wide policies and shared mailboxes, and disable
   public preview URLs. An organizational IdP is also supported.
9. Redeploy after the Access application exists so the real audience tag is in
   `wrangler.local.jsonc`.

Authentication remains in Wrangler's local OAuth session or a caller-supplied
environment variable. The uploader has no credential arguments, does not emit
Wrangler output, and does not write credentials or S3 keys to the repository.

Cloudflare documents both the one-click
[Access protection for workers.dev](https://developers.cloudflare.com/workers/configuration/routing/workers-dev/)
and the requirement to
[validate the Access JWT](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/authorization-cookie/validating-json/).

## Object layout and release switch

The Worker never lists bucket contents. It maps a request for `/js/app.js` to:

```text
releases/<ACTIVE_RELEASE>/site/js/app.js
```

The uploader places a complete staged site beneath one immutable release prefix
and verifies the remote bytes. Only after it succeeds should you change
`ACTIVE_RELEASE` and redeploy. Retain the preceding release for rollback. A
release contains the pinned public runtime and projections plus the ignored
authenticated media overlay; its `release.json` records hashes and the dataset
identity but no credentials.

Before sharing the URL, verify all of these from a signed-out browser:

- the Worker URL redirects to Access or returns a denial before any asset;
- an unapproved email cannot sign in;
- a direct R2 URL is unavailable;
- authenticated HTML, JavaScript, JSON, all four photographs, the 132-entry OCR
  index, inline LOC regions, search, and drawer evidence load;
- the public static reviewer-code dialog is absent and the Access logout link
  ends the session;
- a fabricated or expired Access JWT receives `403`;
- `POST`, traversal paths, directory listing attempts, and unknown objects fail;
- responses contain `no-store`, `noindex`, and same-origin isolation headers.

From this directory, run the local contract checks with:

```bash
npm test
python3 ../../../scripts/build_jefferson_private_media_bundle_unit_tests.py
python3 ../../../scripts/build_jefferson_private_ocr_review_unit_tests.py
python3 ../../../scripts/build_jefferson_private_review_release_unit_tests.py
python3 ../../../scripts/upload_jefferson_private_review_release_unit_tests.py
python3 ../../../scripts/private_review_browser_test_unit_tests.py
python3 ../../../scripts/private_review_public_tree_audit.py
```
