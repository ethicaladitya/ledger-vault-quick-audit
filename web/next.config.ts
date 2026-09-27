import type { NextConfig } from "next";

// API_URL is read at build time. Docker Compose uses the `api` service; for local
// development run `API_URL=http://localhost:8000 npm run dev`.
const api = process.env.API_URL || "http://api:8000";
const nextConfig: NextConfig = {
  output: "standalone",
  poweredByHeader: false,
  // Large multi-year statements can take longer than the default 30 s to import.
  experimental: { proxyTimeout: 300_000 },
  async rewrites() { return [{ source: "/api/:path*", destination: `${api}/:path*` }]; },
};
export default nextConfig;
