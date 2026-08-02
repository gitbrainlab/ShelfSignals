import { createRemoteJWKSet, jwtVerify } from "jose";


const RELEASE_ID = /^[0-9a-f]{64}$/;
const CONTROL_CHARACTERS = /[\0-\x1f\x7f]/;
const MIME_TYPES = new Map([
  [".css", "text/css; charset=utf-8"],
  [".html", "text/html; charset=utf-8"],
  [".ico", "image/x-icon"],
  [".jpeg", "image/jpeg"],
  [".jpg", "image/jpeg"],
  [".js", "text/javascript; charset=utf-8"],
  [".json", "application/json; charset=utf-8"],
  [".md", "text/markdown; charset=utf-8"],
  [".png", "image/png"],
  [".svg", "image/svg+xml; charset=utf-8"],
  [".webp", "image/webp"],
  [".woff2", "font/woff2"],
]);
const remoteKeySets = new Map();


export function validReleaseId(value) {
  return RELEASE_ID.test(String(value || ""));
}


export function normalizeAssetPath(pathname) {
  let decoded;
  try {
    decoded = decodeURIComponent(String(pathname || "/"));
  } catch (_) {
    return null;
  }
  if (!decoded.startsWith("/") || decoded.includes("\\") || CONTROL_CHARACTERS.test(decoded)) return null;
  if (decoded === "/") return "index.html";
  const trailingDirectory = decoded.endsWith("/");
  const relative = trailingDirectory ? decoded.slice(1, -1) : decoded.slice(1);
  const segments = relative.split("/");
  if (segments.some(segment => !segment || segment === "." || segment === "..")) return null;
  const path = segments.join("/");
  return trailingDirectory ? `${path}/index.html` : path;
}


export function allowedReviewers(value) {
  return new Set(String(value || "")
    .split(",")
    .map(email => email.trim().toLocaleLowerCase())
    .filter(email => /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(email)));
}


export function secureHeaders(contentType = "application/octet-stream") {
  return new Headers({
    "Cache-Control": "private, no-store, max-age=0",
    "Content-Security-Policy": "default-src 'self'; base-uri 'self'; connect-src 'self'; font-src 'self' data:; frame-ancestors 'none'; img-src 'self' data: https:; object-src 'none'; script-src 'self'; style-src 'self' 'unsafe-inline'",
    "Content-Type": contentType,
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "camera=(), geolocation=(), microphone=()",
    "Referrer-Policy": "no-referrer",
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "X-Robots-Tag": "noindex, nofollow, noarchive",
  });
}


function contentType(path) {
  const filename = path.toLocaleLowerCase();
  for (const [extension, type] of MIME_TYPES) {
    if (filename.endsWith(extension)) return type;
  }
  return "application/octet-stream";
}


function plainResponse(message, status) {
  return new Response(message, { status, headers: secureHeaders("text/plain; charset=utf-8") });
}


function normalizedTeamDomain(value) {
  try {
    const url = new URL(String(value || ""));
    if (url.protocol !== "https:" || !url.hostname.endsWith(".cloudflareaccess.com") || url.pathname !== "/") return null;
    return url.origin;
  } catch (_) {
    return null;
  }
}


async function authenticate(request, env) {
  const teamDomain = normalizedTeamDomain(env.TEAM_DOMAIN);
  const audience = String(env.POLICY_AUD || "").trim();
  const reviewers = allowedReviewers(env.ALLOWED_EMAILS);
  if (!teamDomain || !audience || !validReleaseId(env.ACTIVE_RELEASE) || !reviewers.size) {
    throw new Error("gateway_configuration");
  }
  const token = request.headers.get("cf-access-jwt-assertion");
  if (!token) throw new Error("access_denied");
  let keySet = remoteKeySets.get(teamDomain);
  if (!keySet) {
    keySet = createRemoteJWKSet(new URL(`${teamDomain}/cdn-cgi/access/certs`));
    remoteKeySets.set(teamDomain, keySet);
  }
  const { payload } = await jwtVerify(token, keySet, {
    issuer: teamDomain,
    audience,
    algorithms: ["RS256"],
  });
  const email = String(payload.email || "").trim().toLocaleLowerCase();
  if (!reviewers.has(email)) throw new Error("access_denied");
}


async function objectResponse(request, env, path) {
  const key = `releases/${env.ACTIVE_RELEASE}/site/${path}`;
  const object = request.method === "HEAD"
    ? await env.PRIVATE_REVIEW.head(key)
    : await env.PRIVATE_REVIEW.get(key);
  if (!object) return plainResponse("Not found", 404);
  const headers = secureHeaders(contentType(path));
  headers.set("Content-Length", String(object.size));
  if (object.httpEtag) headers.set("ETag", object.httpEtag);
  if (path.startsWith("private/") || path.endsWith("media-authenticated.json")) {
    headers.set("Content-Disposition", "inline");
  }
  if (request.method === "HEAD") return new Response(null, { status: 200, headers });
  return new Response(object.body, { status: 200, headers });
}


export default {
  async fetch(request, env) {
    if (!env.PRIVATE_REVIEW) return plainResponse("Gateway unavailable", 503);
    try {
      await authenticate(request, env);
    } catch (error) {
      const status = error instanceof Error && error.message === "gateway_configuration" ? 503 : 403;
      return plainResponse(status === 503 ? "Gateway unavailable" : "Access denied", status);
    }
    if (!new Set(["GET", "HEAD"]).has(request.method)) {
      const response = plainResponse("Method not allowed", 405);
      response.headers.set("Allow", "GET, HEAD");
      return response;
    }
    const path = normalizeAssetPath(new URL(request.url).pathname);
    if (!path) return plainResponse("Not found", 404);
    return objectResponse(request, env, path);
  },
};
