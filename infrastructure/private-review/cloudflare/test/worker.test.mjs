import assert from "node:assert/strict";
import test, { after, before } from "node:test";

import {
  exportJWK,
  generateKeyPair,
  SignJWT,
} from "jose";

import worker, {
  allowedReviewers,
  normalizeAssetPath,
  secureHeaders,
  validReleaseId,
} from "../src/worker.js";


const RELEASE_ID = "a".repeat(64);
const TEAM_DOMAIN = "https://shelfsignals-test.cloudflareaccess.com";
const POLICY_AUD = "shelfsignals-private-review-test";
const APPROVED_EMAIL = "approved@example.org";
const encoder = new TextEncoder();

let signingKey;
let forgedSigningKey;
let originalFetch;
let jwksFetches;


before(async () => {
  const signingPair = await generateKeyPair("RS256", { extractable: true });
  const forgedPair = await generateKeyPair("RS256", { extractable: true });
  signingKey = signingPair.privateKey;
  forgedSigningKey = forgedPair.privateKey;
  const publicJwk = await exportJWK(signingPair.publicKey);
  Object.assign(publicJwk, { alg: "RS256", kid: "approved-test-key", use: "sig" });

  originalFetch = globalThis.fetch;
  jwksFetches = [];
  globalThis.fetch = async (input, init = {}) => {
    jwksFetches.push({ input: String(input), method: init.method });
    assert.equal(String(input), `${TEAM_DOMAIN}/cdn-cgi/access/certs`);
    assert.equal(init.method, "GET");
    return new Response(JSON.stringify({ keys: [publicJwk] }), {
      status: 200,
      headers: { "Content-Type": "application/json" },
    });
  };
});


after(() => {
  globalThis.fetch = originalFetch;
});


async function accessToken({
  audience = POLICY_AUD,
  email = APPROVED_EMAIL,
  expirationTime = Math.floor(Date.now() / 1000) + 3600,
  key = signingKey,
} = {}) {
  const now = Math.floor(Date.now() / 1000);
  return new SignJWT({ email })
    .setProtectedHeader({ alg: "RS256", kid: "approved-test-key", typ: "JWT" })
    .setIssuer(TEAM_DOMAIN)
    .setAudience(audience)
    .setIssuedAt(now - 30)
    .setNotBefore(now - 30)
    .setExpirationTime(expirationTime)
    .sign(key);
}


function reviewRequest(path = "/", { method = "GET", token } = {}) {
  const headers = new Headers();
  if (token) headers.set("cf-access-jwt-assertion", token);
  return new Request(`https://review.example${path}`, { method, headers });
}


function mockR2(entries = {}) {
  const calls = [];
  const values = new Map(Object.entries(entries).map(([key, value]) => {
    const body = encoder.encode(value.body);
    return [key, {
      body,
      httpEtag: value.httpEtag || `"${body.byteLength}-test"`,
      size: body.byteLength,
    }];
  }));
  return {
    calls,
    async get(key) {
      calls.push({ method: "get", key });
      return values.get(key) || null;
    },
    async head(key) {
      calls.push({ method: "head", key });
      const value = values.get(key);
      return value ? { httpEtag: value.httpEtag, size: value.size } : null;
    },
  };
}


function gatewayEnv(r2, overrides = {}) {
  return {
    ACTIVE_RELEASE: RELEASE_ID,
    ALLOWED_EMAILS: APPROVED_EMAIL,
    POLICY_AUD,
    PRIVATE_REVIEW: r2,
    TEAM_DOMAIN,
    ...overrides,
  };
}


function assertPrivateResponseHeaders(response, contentType) {
  assert.equal(response.headers.get("content-type"), contentType);
  assert.match(response.headers.get("cache-control"), /private/);
  assert.match(response.headers.get("cache-control"), /no-store/);
  assert.match(response.headers.get("content-security-policy"), /default-src 'self'/);
  assert.match(response.headers.get("content-security-policy"), /frame-ancestors 'none'/);
  assert.match(response.headers.get("x-robots-tag"), /noindex/);
  assert.equal(response.headers.get("cross-origin-opener-policy"), "same-origin");
  assert.equal(response.headers.get("cross-origin-resource-policy"), "same-origin");
  assert.match(response.headers.get("permissions-policy"), /geolocation=\(\)/);
  assert.equal(response.headers.get("referrer-policy"), "no-referrer");
  assert.equal(response.headers.get("x-content-type-options"), "nosniff");
  assert.equal(response.headers.get("x-frame-options"), "DENY");
}


test("asset paths normalize without allowing traversal or alternate separators", () => {
  assert.equal(normalizeAssetPath("/"), "index.html");
  assert.equal(normalizeAssetPath("/data/collections/jefferson/"), "data/collections/jefferson/index.html");
  assert.equal(normalizeAssetPath("/private/jefferson/photo.jpg"), "private/jefferson/photo.jpg");
  for (const unsafe of ["/%2e%2e/secret", "/../secret", "/a//b", "/a\\b", "/%00secret", "relative"] ) {
    assert.equal(normalizeAssetPath(unsafe), null, unsafe);
  }
});


test("release and reviewer configuration fail closed", () => {
  assert.equal(validReleaseId("a".repeat(64)), true);
  assert.equal(validReleaseId(`sha256:${"a".repeat(64)}`), false);
  assert.equal(validReleaseId("A".repeat(64)), false);
  assert.deepEqual([...allowedReviewers(" One@Example.org, two@example.org,invalid ")], ["one@example.org", "two@example.org"]);
  assert.equal(allowedReviewers("").size, 0);
});


test("private responses carry anti-indexing and browser isolation headers", () => {
  const headers = secureHeaders("image/jpeg");
  assert.equal(headers.get("content-type"), "image/jpeg");
  assert.match(headers.get("cache-control"), /no-store/);
  assert.match(headers.get("content-security-policy"), /default-src 'self'/);
  assert.match(headers.get("content-security-policy"), /script-src 'self'/);
  assert.match(headers.get("content-security-policy"), /frame-ancestors 'none'/);
  assert.match(headers.get("x-robots-tag"), /noindex/);
  assert.equal(headers.get("cross-origin-resource-policy"), "same-origin");
});


test("default handler fails closed for missing binding, configuration, or Access header", async () => {
  const r2 = mockR2();

  const missingBinding = await worker.fetch(reviewRequest(), {});
  assert.equal(missingBinding.status, 503);
  assert.equal(await missingBinding.text(), "Gateway unavailable");
  assertPrivateResponseHeaders(missingBinding, "text/plain; charset=utf-8");

  const missingConfiguration = await worker.fetch(reviewRequest(), { PRIVATE_REVIEW: r2 });
  assert.equal(missingConfiguration.status, 503);
  assert.equal(await missingConfiguration.text(), "Gateway unavailable");
  assertPrivateResponseHeaders(missingConfiguration, "text/plain; charset=utf-8");

  const missingHeader = await worker.fetch(reviewRequest(), gatewayEnv(r2));
  assert.equal(missingHeader.status, 403);
  assert.equal(await missingHeader.text(), "Access denied");
  assertPrivateResponseHeaders(missingHeader, "text/plain; charset=utf-8");

  assert.deepEqual(r2.calls, []);
  assert.deepEqual(jwksFetches, []);
});


test("signed Access JWT must have the configured audience, reviewer email, lifetime, and signature", async (t) => {
  const invalidTokens = [
    {
      label: "wrong audience",
      token: await accessToken({ audience: "another-application" }),
    },
    {
      label: "unapproved email",
      token: await accessToken({ email: "not-approved@example.org" }),
    },
    {
      label: "expired token",
      token: await accessToken({ expirationTime: 1 }),
    },
    {
      label: "forged signature",
      token: await accessToken({ key: forgedSigningKey }),
    },
  ];

  for (const { label, token } of invalidTokens) {
    await t.test(label, async () => {
      const r2 = mockR2();
      const response = await worker.fetch(reviewRequest("/index.html", { token }), gatewayEnv(r2));
      assert.equal(response.status, 403);
      assert.equal(await response.text(), "Access denied");
      assertPrivateResponseHeaders(response, "text/plain; charset=utf-8");
      assert.deepEqual(r2.calls, []);
    });
  }

  assert.equal(jwksFetches.length, 1);
});


test("authenticated GET maps only inside the active R2 release and returns private headers", async () => {
  const assetPath = `private/jefferson/display/${"b".repeat(64)}.jpg`;
  const key = `releases/${RELEASE_ID}/site/${assetPath}`;
  const r2 = mockR2({
    [key]: { body: "private-image", httpEtag: '"private-image-etag"' },
  });
  const token = await accessToken();

  const response = await worker.fetch(reviewRequest(`/${assetPath}`, { token }), gatewayEnv(r2));

  assert.equal(response.status, 200);
  assert.equal(await response.text(), "private-image");
  assert.deepEqual(r2.calls, [{ method: "get", key }]);
  assert.equal(response.headers.get("content-length"), String(encoder.encode("private-image").byteLength));
  assert.equal(response.headers.get("etag"), '"private-image-etag"');
  assert.equal(response.headers.get("content-disposition"), "inline");
  assertPrivateResponseHeaders(response, "image/jpeg");
});


test("authenticated HEAD uses R2 head, maps root to index, and returns no body", async () => {
  const key = `releases/${RELEASE_ID}/site/index.html`;
  const r2 = mockR2({
    [key]: { body: "<!doctype html>", httpEtag: '"index-etag"' },
  });
  const token = await accessToken();

  const response = await worker.fetch(reviewRequest("/", { method: "HEAD", token }), gatewayEnv(r2));

  assert.equal(response.status, 200);
  assert.equal(await response.text(), "");
  assert.deepEqual(r2.calls, [{ method: "head", key }]);
  assert.equal(response.headers.get("content-length"), String(encoder.encode("<!doctype html>").byteLength));
  assert.equal(response.headers.get("etag"), '"index-etag"');
  assert.equal(response.headers.get("content-disposition"), null);
  assertPrivateResponseHeaders(response, "text/html; charset=utf-8");
});


test("authenticated unsupported methods are denied before any R2 operation", async () => {
  const r2 = mockR2();
  const token = await accessToken();

  const response = await worker.fetch(reviewRequest("/index.html", { method: "POST", token }), gatewayEnv(r2));

  assert.equal(response.status, 405);
  assert.equal(response.headers.get("allow"), "GET, HEAD");
  assert.equal(await response.text(), "Method not allowed");
  assertPrivateResponseHeaders(response, "text/plain; charset=utf-8");
  assert.deepEqual(r2.calls, []);
});


test("authenticated missing and unsafe paths return 404 without escaping the release prefix", async () => {
  const missingKey = `releases/${RELEASE_ID}/site/missing.json`;
  const r2 = mockR2();
  const token = await accessToken();

  const missing = await worker.fetch(reviewRequest("/missing.json", { token }), gatewayEnv(r2));
  assert.equal(missing.status, 404);
  assert.equal(await missing.text(), "Not found");
  assertPrivateResponseHeaders(missing, "text/plain; charset=utf-8");
  assert.deepEqual(r2.calls, [{ method: "get", key: missingKey }]);

  const unsafe = await worker.fetch(reviewRequest("/a//b", { token }), gatewayEnv(r2));
  assert.equal(unsafe.status, 404);
  assert.equal(await unsafe.text(), "Not found");
  assertPrivateResponseHeaders(unsafe, "text/plain; charset=utf-8");
  assert.deepEqual(r2.calls, [{ method: "get", key: missingKey }]);
});
