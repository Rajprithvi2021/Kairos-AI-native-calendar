import type { NextConfig } from "next";

// The browser only talks to this origin; /api/* is proxied to the FastAPI service (no CORS needed).
const API_URL = process.env.KAIROS_API_URL ?? "http://127.0.0.1:8000";

const nextConfig: NextConfig = {
  cacheComponents: true,
  partialPrefetching: true,
  devIndicators: false, // keep the corner clear for the AI-status pill (errors still surface in dev)
  async rewrites() {
    return [{ source: "/api/:path*", destination: `${API_URL}/api/:path*` }];
  },
};

export default nextConfig;
