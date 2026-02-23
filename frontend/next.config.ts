import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async rewrites() {
    const apiTarget = process.env.API_URL || "http://localhost:8000";
    return [
      { source: "/api/:path*", destination: `${apiTarget}/api/:path*` },
      { source: "/health", destination: `${apiTarget}/health` },
      { source: "/static/assets/:path*", destination: `${apiTarget}/static/assets/:path*` },
    ];
  },
  // Allow loading GLB models from the backend
  images: {
    remotePatterns: [
      { protocol: "http", hostname: "localhost", port: "8000" },
    ],
  },
};

export default nextConfig;
