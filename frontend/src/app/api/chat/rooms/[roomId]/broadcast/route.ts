/**
 * Broadcast route — simple JSON proxy.
 *
 * Broadcast is fire-and-forget: the backend returns JSON immediately.
 * Real-time events are delivered via WebSocket at /ws/chat/rooms/{roomId}.
 *
 * This Route Handler forwards the POST to the backend and returns the
 * JSON response.  It exists because Next.js Route Handlers take priority
 * over rewrites — removing it would also work (the blanket rewrite in
 * next.config.ts would handle it), but keeping it lets us set maxDuration.
 */

import { NextRequest, NextResponse } from "next/server";

export const dynamic = "force-dynamic";

/* Allow generous timeout — the POST itself returns quickly but keep headroom */
export const maxDuration = 60;

const API_URL = process.env.API_URL || `http://localhost:${process.env.NEXT_PUBLIC_BACKEND_PORT || "8000"}`;

export async function POST(
  request: NextRequest,
  { params }: { params: Promise<{ roomId: string }> },
) {
  const { roomId } = await params;
  const body = await request.text();

  const upstream = await fetch(`${API_URL}/api/chat/rooms/${roomId}/broadcast`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body,
    cache: "no-store",
  });

  const responseBody = await upstream.text();
  return new NextResponse(responseBody, {
    status: upstream.status,
    headers: { "Content-Type": "application/json" },
  });
}
