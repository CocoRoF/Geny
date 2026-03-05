/**
 * Streaming SSE proxy for chat room broadcast.
 *
 * Next.js `rewrites()` buffers the entire upstream response before forwarding it
 * to the browser, which means SSE events only arrive after the last agent finishes.
 *
 * This Route Handler bypasses that limitation by explicitly reading chunks from
 * the backend and forwarding them to the client via a ReadableStream so each
 * SSE event is delivered as soon as the backend yields it.
 */

import { NextRequest } from "next/server";

/* Prevent Next.js from caching or statically rendering this route */
export const dynamic = "force-dynamic";

/* Allow long-running broadcasts (5 minutes) */
export const maxDuration = 300;

const API_URL = process.env.API_URL || "http://localhost:8000";

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

  if (!upstream.ok) {
    const errorBody = await upstream.text();
    return new Response(errorBody, {
      status: upstream.status,
      headers: { "Content-Type": "application/json" },
    });
  }

  // Explicitly read chunks from upstream and forward them — avoids any
  // internal buffering that may occur when passing upstream.body directly.
  const upstreamReader = upstream.body?.getReader();
  if (!upstreamReader) {
    return new Response(JSON.stringify({ error: "No upstream body" }), {
      status: 502,
      headers: { "Content-Type": "application/json" },
    });
  }

  const stream = new ReadableStream({
    async pull(controller) {
      try {
        const { done, value } = await upstreamReader.read();
        if (done) {
          controller.close();
          return;
        }
        controller.enqueue(value);
      } catch {
        controller.close();
      }
    },
    cancel() {
      upstreamReader.cancel();
    },
  });

  return new Response(stream, {
    status: 200,
    headers: {
      "Content-Type": "text/event-stream",
      "Cache-Control": "no-cache, no-transform",
      Connection: "keep-alive",
      "X-Accel-Buffering": "no",
    },
  });
}
