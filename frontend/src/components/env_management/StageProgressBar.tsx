'use client';

/**
 * StageProgressBar — premium horizontal stage navigator (cycle
 * 20260427_2 PR-3 → polished in PR-4).
 *
 * Layout fix: circle row + label row are split so the connecting rail
 * passes exactly through the circle centres (was hitting the label
 * gap before).
 *
 * Active state: stages active in the manifest get a clearly distinct
 * GOLD/AMBER look, regardless of category. Selected (currently being
 * edited) gets a strong PRIMARY-blue gradient + ring + glow that's
 * visible in both light and dark themes.
 *
 * Drag fix: previous version used setPointerCapture inside
 * pointerdown, which on some browsers pre-empts the child button's
 * click event. Switched to window-level pointermove/pointerup listeners
 * attached on pointerdown and removed on pointerup — child clicks
 * fire normally.
 */

import { useCallback, useEffect, useRef } from 'react';
import { ArrowLeft } from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import { useTheme } from '@/lib/theme';
import { getStageMetaByOrder } from '@/components/session-env/stageMetadata';

// Theme-aware palettes for the three stage states. Light values are
// the gentle pastels we landed on in PR #471; dark values flip to
// translucent deep tints with brighter foregrounds so the green/blue
// signal still reads cleanly against the dark card background.
const PALETTE = {
  light: {
    activeBg: 'rgb(220 252 231)', // emerald-100
    activeFg: 'rgb(4 120 87)', // emerald-700
    activeBorder: 'rgb(16 185 129)', // emerald-500
    activeShadow: '0 1px 4px -1px rgb(16 185 129 / 0.25)',
    selectedBg: 'rgb(219 234 254)', // blue-100
    selectedFg: 'rgb(29 78 216)', // blue-700
    selectedBorder: 'rgb(59 130 246)', // blue-500
    selectedRing:
      '0 0 0 3px hsl(var(--card)), 0 0 0 4.5px rgb(59 130 246 / 0.55), 0 3px 10px -3px rgb(59 130 246 / 0.3)',
    connectorActive: 'rgb(16 185 129)',
  },
  dark: {
    activeBg: 'rgb(6 78 59 / 0.45)', // emerald-900 @ 45%
    activeFg: 'rgb(110 231 183)', // emerald-300
    activeBorder: 'rgb(52 211 153)', // emerald-400
    activeShadow:
      '0 0 0 1px rgb(16 185 129 / 0.15), 0 1px 6px -1px rgb(16 185 129 / 0.3)',
    selectedBg: 'rgb(30 58 138 / 0.5)', // blue-900 @ 50%
    selectedFg: 'rgb(147 197 253)', // blue-300
    selectedBorder: 'rgb(96 165 250)', // blue-400
    selectedRing:
      '0 0 0 3px hsl(var(--card)), 0 0 0 4.5px rgb(96 165 250 / 0.55), 0 3px 12px -2px rgb(96 165 250 / 0.4)',
    connectorActive: 'rgb(52 211 153)',
  },
} as const;

export interface StageProgressBarProps {
  selectedOrder: number;
  onSelect: (order: number) => void;
  onBack: () => void;
  dirtyOrders: ReadonlySet<number>;
  activeOrders: ReadonlySet<number>;
}

const ALL_ORDERS = Array.from({ length: 21 }, (_, i) => i + 1);

const DRAG_THRESHOLD_PX = 5;
const FRICTION = 0.92;
const MIN_VELOCITY = 0.4; // px/frame at ~60fps
const ROW_HEIGHT = 64; // circle row height (so circles align with rail)
const RAIL_TOP = ROW_HEIGHT / 2; // 32 — circle vertical centre

export default function StageProgressBar({
  selectedOrder,
  onSelect,
  onBack,
  dirtyOrders,
  activeOrders,
}: StageProgressBarProps) {
  const { t } = useI18n();
  const locale = useI18n((s) => s.locale);
  const { theme } = useTheme();
  const palette = PALETTE[theme === 'dark' ? 'dark' : 'light'];

  const scrollRef = useRef<HTMLDivElement | null>(null);
  const itemRefs = useRef<Map<number, HTMLButtonElement>>(new Map());
  const rafRef = useRef<number | null>(null);
  const wasDraggingRef = useRef(false);

  // Auto-centre selected stage on change.
  useEffect(() => {
    const el = itemRefs.current.get(selectedOrder);
    if (el && scrollRef.current) {
      el.scrollIntoView({
        behavior: 'smooth',
        block: 'nearest',
        inline: 'center',
      });
    }
  }, [selectedOrder]);

  // Cancel any in-flight momentum on unmount.
  useEffect(() => {
    return () => {
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
    };
  }, []);

  // ─── Drag state (window-level, no setPointerCapture) ─────────────
  const dragRef = useRef<{
    tracking: boolean;
    dragging: boolean;
    startX: number;
    startScroll: number;
    lastX: number;
    lastT: number;
    velocity: number; // px/ms; positive = scrolling content right→left
  }>({
    tracking: false,
    dragging: false,
    startX: 0,
    startScroll: 0,
    lastX: 0,
    lastT: 0,
    velocity: 0,
  });

  const stopMomentum = () => {
    if (rafRef.current != null) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
  };

  // Defined as refs so handleWindowPointerUp can remove them.
  const handleWindowPointerMoveRef = useRef<((e: PointerEvent) => void) | null>(null);
  const handleWindowPointerUpRef = useRef<((e: PointerEvent) => void) | null>(null);

  const handleWindowPointerMove = useCallback((e: PointerEvent) => {
    const s = dragRef.current;
    if (!s.tracking || !scrollRef.current) return;
    const dx = e.clientX - s.startX;
    if (!s.dragging && Math.abs(dx) > DRAG_THRESHOLD_PX) {
      s.dragging = true;
      wasDraggingRef.current = true;
    }
    if (s.dragging) {
      scrollRef.current.scrollLeft = s.startScroll - dx;
      const dt = e.timeStamp - s.lastT;
      if (dt > 0) {
        s.velocity = -(e.clientX - s.lastX) / dt;
        s.lastX = e.clientX;
        s.lastT = e.timeStamp;
      }
    }
  }, []);

  const handleWindowPointerUp = useCallback(() => {
    const s = dragRef.current;
    if (!s.tracking) return;
    s.tracking = false;
    if (handleWindowPointerMoveRef.current) {
      window.removeEventListener('pointermove', handleWindowPointerMoveRef.current);
    }
    if (handleWindowPointerUpRef.current) {
      window.removeEventListener('pointerup', handleWindowPointerUpRef.current);
      window.removeEventListener('pointercancel', handleWindowPointerUpRef.current);
    }

    if (s.dragging && Math.abs(s.velocity) > MIN_VELOCITY / 16) {
      let v = s.velocity * 16;
      const tick = () => {
        if (!scrollRef.current) return;
        scrollRef.current.scrollLeft += v;
        v *= FRICTION;
        if (Math.abs(v) > MIN_VELOCITY) {
          rafRef.current = requestAnimationFrame(tick);
        } else {
          rafRef.current = null;
        }
      };
      rafRef.current = requestAnimationFrame(tick);
    }

    if (s.dragging) {
      // Suppress the next click for one tick so the drag-end doesn't
      // fall through onto whatever button the pointer happened to land on.
      setTimeout(() => {
        wasDraggingRef.current = false;
      }, 0);
    }
    s.dragging = false;
  }, []);

  // Stash refs so the cleanup paths can find the same function instance.
  useEffect(() => {
    handleWindowPointerMoveRef.current = handleWindowPointerMove;
    handleWindowPointerUpRef.current = handleWindowPointerUp;
  }, [handleWindowPointerMove, handleWindowPointerUp]);

  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!scrollRef.current) return;
    if (e.button !== 0) return; // primary button only
    stopMomentum();
    dragRef.current = {
      tracking: true,
      dragging: false,
      startX: e.clientX,
      startScroll: scrollRef.current.scrollLeft,
      lastX: e.clientX,
      lastT: e.timeStamp,
      velocity: 0,
    };
    if (handleWindowPointerMoveRef.current) {
      window.addEventListener('pointermove', handleWindowPointerMoveRef.current);
    }
    if (handleWindowPointerUpRef.current) {
      window.addEventListener('pointerup', handleWindowPointerUpRef.current);
      window.addEventListener('pointercancel', handleWindowPointerUpRef.current);
    }
  };

  // Wheel: vertical → horizontal
  const onWheel = (e: React.WheelEvent<HTMLDivElement>) => {
    if (!scrollRef.current) return;
    if (Math.abs(e.deltaY) > Math.abs(e.deltaX)) {
      scrollRef.current.scrollLeft += e.deltaY;
    }
  };

  const handleStageClick = (order: number) => {
    if (wasDraggingRef.current) return;
    onSelect(order);
  };

  return (
    <div className="relative flex items-center gap-3 h-[112px] pl-3 pr-3 border-b border-[hsl(var(--border))] bg-[hsl(var(--card))] shrink-0 overflow-hidden">
      {/* Backdrop accent */}
      <div
        className="pointer-events-none absolute inset-0 opacity-40"
        style={{
          background:
            'radial-gradient(ellipse 60% 100% at 50% 50%, hsl(var(--primary) / 0.06) 0%, transparent 70%)',
        }}
      />

      {/* Back button */}
      <button
        type="button"
        onClick={onBack}
        className="relative z-10 inline-flex items-center gap-1.5 h-11 px-3 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--background))] text-[0.8125rem] font-medium text-[hsl(var(--foreground))] hover:border-[hsl(var(--primary)/0.4)] hover:bg-[hsl(var(--accent))] hover:text-[hsl(var(--primary))] transition-all shrink-0 shadow-sm"
        title={t('envManagement.progress.backTip')}
      >
        <ArrowLeft className="w-4 h-4" />
        {t('envManagement.progress.back')}
      </button>

      <div className="relative z-10 w-px h-12 bg-gradient-to-b from-transparent via-[hsl(var(--border))] to-transparent shrink-0" />

      {/* Scroll container with edge fade for the cylinder feel */}
      <div
        ref={scrollRef}
        onWheel={onWheel}
        onPointerDown={onPointerDown}
        className="relative z-10 flex flex-col flex-1 min-w-0 overflow-x-auto overflow-y-hidden scrollbar-hide cursor-grab active:cursor-grabbing select-none"
        style={{
          maskImage:
            'linear-gradient(to right, transparent 0px, black 36px, black calc(100% - 36px), transparent 100%)',
          WebkitMaskImage:
            'linear-gradient(to right, transparent 0px, black 36px, black calc(100% - 36px), transparent 100%)',
          touchAction: 'pan-x',
        }}
      >
        <div className="relative flex items-start px-4 min-h-[96px]">
          {/* Rail — passes through circle vertical centres */}
          <div
            aria-hidden
            className="absolute left-0 right-0 pointer-events-none"
            style={{
              top: RAIL_TOP,
              height: 1,
              background:
                'linear-gradient(to right, transparent 0%, hsl(var(--border)) 6%, hsl(var(--border)) 94%, transparent 100%)',
            }}
          />

          {/* Items + connectors share a flex row aligned to the circle level */}
          <div className="relative flex items-start">
            {ALL_ORDERS.map((order, idx) => {
              const meta = getStageMetaByOrder(order, locale);
              const isSelected = order === selectedOrder;
              const isStageActive = activeOrders.has(order);
              const isDirty = dirtyOrders.has(order);
              const label = meta?.displayName ?? `Stage ${order}`;
              const isLast = idx === ALL_ORDERS.length - 1;
              const nextActive = activeOrders.has(order + 1);

              return (
                <div key={order} className="flex items-start">
                  <div className="flex flex-col items-center min-w-[84px]">
                    {/* Circle row — fixed height so circles align with rail */}
                    <div
                      style={{ height: ROW_HEIGHT }}
                      className="flex items-center justify-center"
                    >
                      <button
                        ref={(el) => {
                          if (el) itemRefs.current.set(order, el);
                          else itemRefs.current.delete(order);
                        }}
                        data-stage-button
                        type="button"
                        onClick={() => handleStageClick(order)}
                        className="group relative outline-none focus-visible:ring-2 focus-visible:ring-[hsl(var(--ring))] rounded-full"
                        title={label}
                      >
                        {/* The circle — uniform 48px for all states so the
                            ring/halo never clips against the row bounds.
                            The visual difference is colour + ring, not size. */}
                        <span
                          className="relative flex items-center justify-center rounded-full font-semibold tabular-nums transition-all duration-200 w-[48px] h-[48px] text-[0.9375rem] group-hover:scale-105"
                          style={
                            isSelected
                              ? {
                                  // Subtle blue (은은한 파란빛). Light/dark
                                  // tints from PALETTE so the contrast stays
                                  // legible against either card background.
                                  background: palette.selectedBg,
                                  color: palette.selectedFg,
                                  border: `2px solid ${palette.selectedBorder}`,
                                  boxShadow: palette.selectedRing,
                                }
                              : isStageActive
                                ? {
                                    // Subtle green (은은한 초록빛) — clear
                                    // "this stage is on" signal, theme-aware.
                                    background: palette.activeBg,
                                    color: palette.activeFg,
                                    border: `2px solid ${palette.activeBorder}`,
                                    boxShadow: palette.activeShadow,
                                  }
                                : {
                                    background: 'hsl(var(--background))',
                                    color: 'hsl(var(--muted-foreground))',
                                    border: '2px solid hsl(var(--border))',
                                  }
                          }
                        >
                          {order}
                          {/* Dirty marker */}
                          {isDirty && (
                            <span
                              aria-label="edited"
                              className="absolute -top-0.5 -right-0.5 w-3 h-3 rounded-full"
                              style={{
                                background: 'hsl(var(--primary))',
                                boxShadow: '0 0 0 2.5px hsl(var(--card))',
                              }}
                            />
                          )}
                        </span>
                      </button>
                    </div>

                    {/* Label below the circle */}
                    <span
                      className={`mt-1.5 text-[0.75rem] tracking-tight truncate max-w-[88px] leading-tight transition-colors ${
                        isSelected
                          ? 'font-semibold'
                          : isStageActive
                            ? 'font-medium'
                            : ''
                      }`}
                      style={{
                        color: isSelected
                          ? palette.selectedFg
                          : isStageActive
                            ? palette.activeFg
                            : 'hsl(var(--muted-foreground))',
                      }}
                    >
                      {label}
                    </span>
                  </div>

                  {/* Connector — sits at the same vertical level as the
                      circle row so it visually bridges the rail. */}
                  {!isLast && (
                    <div
                      style={{ height: ROW_HEIGHT }}
                      className="flex items-center"
                    >
                      <span
                        aria-hidden
                        className="block h-[3px] rounded-full"
                        style={{
                          width: 22,
                          background:
                            isStageActive && nextActive
                              ? palette.connectorActive
                              : 'hsl(var(--border))',
                          opacity: isStageActive && nextActive ? 0.6 : 0.5,
                        }}
                      />
                    </div>
                  )}
                </div>
              );
            })}
          </div>
        </div>
      </div>
    </div>
  );
}
