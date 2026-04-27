'use client';

import { useState, useRef, useCallback, useEffect } from 'react';

interface Transform {
  scale: number;
  x: number;
  y: number;
}

/**
 * Zoom & pan hook using a callback-ref pattern so the wheel listener
 * is reliably attached even when the container mounts after the
 * initial render. Ported from geny-executor-web's `useZoomPan`.
 *
 * `interactive=false` (cycle 20260427_2) — disables wheel zoom and
 * pointer drag entirely. `fitToView` still works, so the canvas can
 * be used as a fixed-display surface that just auto-fits to its
 * container. Returned pointer handlers become no-ops.
 */
export function useZoomPan(minScale = 0.3, maxScale = 3, interactive = true) {
  const [container, setContainer] = useState<HTMLDivElement | null>(null);
  const containerRef = useCallback((node: HTMLDivElement | null) => {
    setContainer(node);
  }, []);

  const [transform, setTransform] = useState<Transform>({ scale: 1, x: 0, y: 0 });
  const isPanning = useRef(false);
  const lastPos = useRef({ x: 0, y: 0 });

  useEffect(() => {
    if (!container || !interactive) return;

    const handleWheel = (e: WheelEvent) => {
      e.preventDefault();
      e.stopPropagation();

      const factor = e.deltaY < 0 ? 1.08 : 0.92;

      setTransform((t) => {
        const next = Math.min(maxScale, Math.max(minScale, t.scale * factor));
        if (next === t.scale) return t;

        const rect = container.getBoundingClientRect();
        const px = e.clientX - rect.left;
        const py = e.clientY - rect.top;
        const r = next / t.scale;

        return {
          scale: next,
          x: px - (px - t.x) * r,
          y: py - (py - t.y) * r,
        };
      });
    };

    container.addEventListener('wheel', handleWheel, { passive: false });
    return () => container.removeEventListener('wheel', handleWheel);
  }, [container, minScale, maxScale, interactive]);

  const onPointerDown = useCallback(
    (e: React.PointerEvent) => {
      if (!interactive || e.button !== 0) return;
      isPanning.current = true;
      lastPos.current = { x: e.clientX, y: e.clientY };
      (e.currentTarget as HTMLElement).setPointerCapture(e.pointerId);
    },
    [interactive],
  );

  const onPointerMove = useCallback(
    (e: React.PointerEvent) => {
      if (!interactive || !isPanning.current) return;
      const dx = e.clientX - lastPos.current.x;
      const dy = e.clientY - lastPos.current.y;
      lastPos.current = { x: e.clientX, y: e.clientY };
      setTransform((t) => ({ ...t, x: t.x + dx, y: t.y + dy }));
    },
    [interactive],
  );

  const onPointerUp = useCallback(() => {
    isPanning.current = false;
  }, []);

  const resetView = useCallback(() => {
    setTransform({ scale: 1, x: 0, y: 0 });
  }, []);

  const fitToView = useCallback(
    (contentW: number, contentH: number, padding = 40) => {
      if (!container) return;
      const rect = container.getBoundingClientRect();
      if (!rect.width || !rect.height) return;
      const sx = (rect.width - padding * 2) / contentW;
      const sy = (rect.height - padding * 2) / contentH;
      const s = Math.min(sx, sy, maxScale);
      setTransform({
        scale: s,
        x: (rect.width - contentW * s) / 2,
        y: (rect.height - contentH * s) / 2,
      });
    },
    [container, maxScale],
  );

  return {
    containerRef,
    /** Live container element — useful for parent ResizeObserver setup. */
    containerEl: container,
    transform,
    onPointerDown,
    onPointerMove,
    onPointerUp,
    resetView,
    fitToView,
  };
}
