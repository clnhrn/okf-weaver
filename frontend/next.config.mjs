/** @type {import('next').NextConfig} */

// The backend the browser must be allowed to reach (ingest/generate/download).
// connect-src has to include its origin or CSP would block every API call.
const API_BASE = process.env.NEXT_PUBLIC_API_BASE ?? "http://127.0.0.1:8000";
let apiOrigin = API_BASE;
try {
  apiOrigin = new URL(API_BASE).origin;
} catch {
  // Leave the raw value; a malformed base is a deploy-config error, not ours.
}

// Defence-in-depth CSP + security headers. 'unsafe-inline' for scripts/styles is
// required by Next's inline bootstrap, the pre-paint theme script, and the
// CodeMirror/React Flow inline styles; XSS is already prevented at the source
// (react-markdown with no rehype-raw, React auto-escaping). The high-value
// clickjacking/sniffing/base-tag protections below are exact, not relaxed.
//
// 'unsafe-eval' is added in development only: Next's React Fast Refresh (HMR)
// runtime evaluates code at module init, and blocking it aborts the client
// bundle so interactive components (the CodeMirror editor) never mount.
// Production builds strip Fast Refresh, so the deployed CSP stays strict.
const isDev = process.env.NODE_ENV !== "production";
const scriptSrc = `script-src 'self' 'unsafe-inline'${isDev ? " 'unsafe-eval'" : ""}`;
const csp = [
  "default-src 'self'",
  scriptSrc,
  "style-src 'self' 'unsafe-inline'",
  "img-src 'self' data:",
  "font-src 'self' data:",
  `connect-src 'self' ${apiOrigin}`,
  "object-src 'none'",
  "base-uri 'self'",
  "form-action 'self'",
  "frame-ancestors 'none'",
].join("; ");

const securityHeaders = [
  { key: "Content-Security-Policy", value: csp },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
];

const nextConfig = {
  async headers() {
    return [{ source: "/:path*", headers: securityHeaders }];
  },
};

export default nextConfig;
