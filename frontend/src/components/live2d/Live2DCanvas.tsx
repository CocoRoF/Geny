'use client';

import { useRef, useEffect, useCallback } from 'react';
import { useVTuberStore } from '@/store/useVTuberStore';

/**
 * Live2DCanvas — renders a Live2D Cubism 4 model using pixi.js + pixi-live2d-display.
 *
 * Uses a generation counter (genRef) to guard against race conditions from
 * React Strict Mode double-mounting and rapid re-renders. Each async init
 * checks its generation at every await boundary and bails out if stale.
 * Cleanup always destroys resources via refs, never via closure variables.
 */

interface Live2DCanvasProps {
  sessionId: string;
  className?: string;
  interactive?: boolean;
  background?: number;
  backgroundAlpha?: number;
}

export default function Live2DCanvas({
  sessionId,
  className = '',
  interactive = true,
  background = 0x000000,
  backgroundAlpha = 0,
}: Live2DCanvasProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const pixiAppRef = useRef<any>(null);
  // eslint-disable-next-line @typescript-eslint/no-explicit-any
  const modelRef = useRef<any>(null);
  /** Generation counter — each effect run gets a unique gen; stale inits bail out. */
  const genRef = useRef(0);

  const model = useVTuberStore((s) => s.getModelForSession(sessionId));
  const avatarState = useVTuberStore((s) => s.avatarStates[sessionId]);
  const interactAction = useVTuberStore((s) => s.interact);

  // ── Initialise Pixi + load Live2D model ────────────────────
  useEffect(() => {
    if (!model || !containerRef.current) return;

    const gen = ++genRef.current;
    const isStale = () => gen !== genRef.current;

    const init = async () => {
      // Load Live2D Cubism Core SDK programmatically.
      // beforeInteractive <Script> is unreliable with Turbopack, so we inject
      // the script ourselves and wait for it to finish before importing the
      // pixi-live2d-display module (which throws at import time if the SDK is missing).
      // eslint-disable-next-line @typescript-eslint/no-explicit-any
      const win = window as any;
      if (!win.Live2DCubismCore) {
        await new Promise<void>((resolve, reject) => {
          // Check if a script tag already exists (e.g. from beforeInteractive)
          const existing = document.querySelector('script[src*="live2dcubismcore"]');
          if (existing) {
            // Script tag exists but hasn't finished loading yet — wait for it
            const poll = () => {
              if (win.Live2DCubismCore) return resolve();
              setTimeout(poll, 50);
            };
            poll();
            return;
          }
          const script = document.createElement('script');
          script.src = '/lib/live2d/live2dcubismcore.min.js';
          script.onload = () => {
            // SDK sets window.Live2DCubismCore synchronously on load
            resolve();
          };
          script.onerror = () => reject(new Error('Failed to load Live2D Cubism Core SDK'));
          document.head.appendChild(script);
        });
      }
      if (isStale()) return;

      // Dynamic import — pixi.js is browser-only
      const PIXI = await import('pixi.js');
      const { Live2DModel } = await import('pixi-live2d-display/cubism4');

      // pixi-live2d-display needs access to PIXI.Ticker.shared for animations.
      // Without this, the model renders as a static image (no breathing, idle, physics).
      Live2DModel.registerTicker(PIXI.Ticker);

      if (isStale()) return;

      const container = containerRef.current;
      if (!container) return;

      // Destroy any orphaned resources from a previous stale init
      // (can happen when React Strict Mode double-mounts or rapid deps change)
      if (modelRef.current) {
        try { modelRef.current.parent?.removeChild(modelRef.current); } catch { /* ignore */ }
        try { modelRef.current.destroy(); } catch { /* already destroyed */ }
        modelRef.current = null;
      }
      if (pixiAppRef.current) {
        try { pixiAppRef.current.destroy(true); } catch { /* already destroyed */ }
        pixiAppRef.current = null;
      }
      container.innerHTML = '';

      if (isStale()) return;

      // Create Pixi Application
      const app = new PIXI.Application({
        width: container.clientWidth || 600,
        height: container.clientHeight || 600,
        backgroundAlpha,
        backgroundColor: background,
        antialias: true,
        autoDensity: true,
        resolution: window.devicePixelRatio || 1,
      });

      if (isStale()) {
        app.destroy(true);
        return;
      }

      container.appendChild(app.view as unknown as HTMLElement);
      // Make the canvas fill the container (PIXI sets width/height attributes for resolution)
      const canvas = app.view as unknown as HTMLCanvasElement;
      canvas.style.width = '100%';
      canvas.style.height = '100%';
      canvas.style.display = 'block';
      pixiAppRef.current = app;

      // Load the Live2D model
      const live2dModel = await Live2DModel.from(model.url, { autoInteract: false });

      if (isStale()) {
        live2dModel.destroy();
        // app is in pixiAppRef — cleanup or next init will handle it
        return;
      }

      modelRef.current = live2dModel;

      // Scale model to fit canvas
      const scaleX = app.screen.width / live2dModel.width;
      const scaleY = app.screen.height / live2dModel.height;
      const scale = Math.min(scaleX, scaleY) * 0.85;
      live2dModel.scale.set(scale);

      // Center model with anchor for eye-tracking
      live2dModel.anchor.set(0.5, 0.5);
      live2dModel.x = app.screen.width / 2;
      live2dModel.y = app.screen.height / 2;

      app.stage.addChild(live2dModel);

      // Start an idle motion
      try {
        await live2dModel.motion(model.idleMotionGroupName || 'Idle');
      } catch {
        // Idle group might not exist
      }
    };

    init().catch((err) => console.error('[Live2DCanvas] Init error:', err));

    return () => {
      // Bump generation — invalidates any in-flight async init
      genRef.current++;
      // Remove model from stage FIRST, then destroy model, then app.
      // This avoids app.destroy trying to destroy an already-destroyed model
      // which causes _clippingManager._currentFrameNo errors.
      if (modelRef.current) {
        try { modelRef.current.parent?.removeChild(modelRef.current); } catch { /* ignore */ }
        try { modelRef.current.destroy(); } catch { /* ignore */ }
        modelRef.current = null;
      }
      if (pixiAppRef.current) {
        try { pixiAppRef.current.destroy(true); } catch { /* ignore */ }
        pixiAppRef.current = null;
      }
      if (containerRef.current) {
        containerRef.current.innerHTML = '';
      }
    };
    // Re-run only when the model identity changes
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [model?.name, model?.url]);

  // ── Apply avatar state changes (expression + motion) ──────
  useEffect(() => {
    if (!avatarState || !modelRef.current) return;
    const live2dModel = modelRef.current;

    // Apply expression
    try {
      live2dModel.expression(avatarState.expression_index);
    } catch {
      // Expression index may be out of range
    }

    // Apply motion (skip idle triggers — idle loops automatically)
    if (avatarState.trigger !== 'system') {
      try {
        live2dModel.motion(avatarState.motion_group, avatarState.motion_index);
      } catch {
        // Motion group may not exist
      }
    }
  }, [avatarState?.emotion, avatarState?.expression_index, avatarState?.motion_group, avatarState?.motion_index, avatarState?.trigger, avatarState?.timestamp]);

  // ── Handle click/tap on canvas ────────────────────────────
  const handleClick = useCallback(
    (e: React.MouseEvent<HTMLDivElement>) => {
      if (!interactive || !modelRef.current || !containerRef.current) return;

      const rect = containerRef.current.getBoundingClientRect();
      const x = (e.clientX - rect.left) / rect.width;
      const y = (e.clientY - rect.top) / rect.height;

      // Determine hit area based on click position (simple heuristic)
      const hitArea = y < 0.4 ? 'HitAreaHead' : 'HitAreaBody';
      interactAction(sessionId, hitArea, x, y);
    },
    [interactive, sessionId, interactAction],
  );

  // ── Resize observer ────────────────────────────────────────
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const ro = new ResizeObserver((entries) => {
      const entry = entries[0];
      if (!entry || !pixiAppRef.current) return;
      const { width, height } = entry.contentRect;
      if (width > 0 && height > 0) {
        pixiAppRef.current.renderer.resize(width, height);
        // Re-center model
        if (modelRef.current) {
          const m = modelRef.current;
          const scaleX = width / (m.width / m.scale.x);
          const scaleY = height / (m.height / m.scale.y);
          const scale = Math.min(scaleX, scaleY) * 0.85;
          m.scale.set(scale);
          m.x = width / 2;
          m.y = height / 2;
        }
      }
    });
    ro.observe(container);
    return () => ro.disconnect();
  }, []);

  // ── Focus tracking (eye follow mouse) ─────────────────────
  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;

    const handleMouseMove = (e: MouseEvent) => {
      if (!modelRef.current) return;
      const rect = container.getBoundingClientRect();
      const x = (e.clientX - rect.left) / rect.width;
      const y = (e.clientY - rect.top) / rect.height;
      // focus() expects pixel coordinates relative to the model
      modelRef.current.focus(
        x * (pixiAppRef.current?.screen?.width ?? rect.width),
        y * (pixiAppRef.current?.screen?.height ?? rect.height),
      );
    };

    container.addEventListener('mousemove', handleMouseMove);
    return () => container.removeEventListener('mousemove', handleMouseMove);
  }, []);

  return (
    <div
      ref={containerRef}
      className={`w-full h-full overflow-hidden ${className}`}
      onClick={handleClick}
      style={{ cursor: interactive ? 'pointer' : 'default', position: 'relative' }}
    />
  );
}
