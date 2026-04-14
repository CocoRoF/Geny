import type { NextConfig } from "next";

const nextConfig: NextConfig = {
  async rewrites() {
    const backendPort = process.env.NEXT_PUBLIC_BACKEND_PORT || "8000";
    const apiTarget = process.env.API_URL || `http://localhost:${backendPort}`;
    // Use "fallback" so that App Router Route Handlers (e.g. SSE proxy
    // at /api/chat/rooms/[roomId]/events) are checked FIRST.  Plain
    // array rewrites run before dynamic routes and shadow Route Handlers.
    // NOTE: WebSocket (/ws/*) is NOT proxied here — Next.js rewrites don't
    // support WS upgrade. In dev, the frontend connects directly to the
    // backend port. In production, nginx handles /ws/ routing.
    return {
      fallback: [
        { source: "/api/:path*", destination: `${apiTarget}/api/:path*` },
        { source: "/health", destination: `${apiTarget}/health` },
        { source: "/static/:path*", destination: `${apiTarget}/static/:path*` },
      ],
    };
  },
  // Allow loading GLB models from the backend
  images: {
    remotePatterns: [
      { protocol: "http", hostname: "localhost", port: process.env.NEXT_PUBLIC_BACKEND_PORT || "8000" },
    ],
  },
};

export default nextConfig;
