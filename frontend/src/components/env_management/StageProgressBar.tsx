'use client';

/**
 * StageProgressBar — premium horizontal stage navigator (cycle
 * 20260427_2 PR-3 redesign).
 *
 * Drum-feel: drag-to-scroll with momentum decay, edge fade masks so the
 * stages appear to rotate around an invisible cylinder, larger nodes
 * with category-colored gradients + glow on the active stage. Wheel
 * scroll converts vertical → horizontal so a desktop trackpad still
 * works.
 *
 * Click/drag disambiguation: if the pointer travelled > 4px between
 * down/up we treat the gesture as a drag and suppress the underlying
 * button click. Pure clicks select the stage.
 *
 * Active stage auto-scrolls to the centre.
 */

import { useEffect, useRef } from 'react';
import { ArrowLeft } from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import {
  getStageMetaByOrder,
  getCategoryColor,
} from '@/components/session-env/stageMetadata';

export interface StageProgressBarProps {
  selectedOrder: number;
  onSelect: (order: number) => void;
  onBack: () => void;
  dirtyOrders: ReadonlySet<number>;
  activeOrders: ReadonlySet<number>;
}

const ALL_ORDERS = Array.from({ length: 21 }, (_, i) => i + 1);

const DRAG_THRESHOLD_PX = 4;
const FRICTION = 0.92;
const MIN_VELOCITY = 0.4;

export default function StageProgressBar({
  selectedOrder,
  onSelect,
  onBack,
  dirtyOrders,
  activeOrders,
}: StageProgressBarProps) {
  const { t } = useI18n();
  const locale = useI18n((s) => s.locale);
  const scrollRef = useRef<HTMLDivElement | null>(null);
  const itemRefs = useRef<Map<number, HTMLButtonElement>>(new Map());
  const rafRef = useRef<number | null>(null);
  const wasDraggingRef = useRef(false);

  // Auto-centre selected stage when it changes.
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

  // Cancel momentum on unmount
  useEffect(() => {
    return () => {
      if (rafRef.current != null) cancelAnimationFrame(rafRef.current);
    };
  }, []);

  // Wheel: vertical → horizontal
  const onWheel = (e: React.WheelEvent<HTMLDivElement>) => {
    if (!scrollRef.current) return;
    if (Math.abs(e.deltaY) > Math.abs(e.deltaX)) {
      scrollRef.current.scrollLeft += e.deltaY;
    }
  };

  // Pointer drag with momentum
  const dragState = useRef<{
    active: boolean;
    startX: number;
    startScroll: number;
    lastX: number;
    lastT: number;
    velocity: number; // px / ms (positive = content scrolling right→left)
    moved: boolean;
  }>({
    active: false,
    startX: 0,
    startScroll: 0,
    lastX: 0,
    lastT: 0,
    velocity: 0,
    moved: false,
  });

  const stopMomentum = () => {
    if (rafRef.current != null) {
      cancelAnimationFrame(rafRef.current);
      rafRef.current = null;
    }
  };

  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!scrollRef.current) return;
    if ((e.target as HTMLElement).closest('button[data-stage-button]')) {
      // Let the click fire normally — but cancel any in-flight momentum
      // so the page feels responsive.
      stopMomentum();
      // Still capture so a slow drag started from a button gets the
      // momentum behaviour. We just don't pre-flag wasDragging.
    }
    stopMomentum();
    dragState.current = {
      active: true,
      startX: e.clientX,
      startScroll: scrollRef.current.scrollLeft,
      lastX: e.clientX,
      lastT: e.timeStamp,
      velocity: 0,
      moved: false,
    };
    scrollRef.current.setPointerCapture(e.pointerId);
  };

  const onPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    const s = dragState.current;
    if (!s.active || !scrollRef.current) return;
    const dx = e.clientX - s.startX;
    if (Math.abs(dx) > DRAG_THRESHOLD_PX) {
      s.moved = true;
      wasDraggingRef.current = true;
    }
    scrollRef.current.scrollLeft = s.startScroll - dx;
    const dt = e.timeStamp - s.lastT;
    if (dt > 0) {
      s.velocity = -(e.clientX - s.lastX) / dt;
      s.lastX = e.clientX;
      s.lastT = e.timeStamp;
    }
  };

  const onPointerUp = (e: React.PointerEvent<HTMLDivElement>) => {
    const s = dragState.current;
    if (!s.active || !scrollRef.current) return;
    s.active = false;
    try {
      scrollRef.current.releasePointerCapture(e.pointerId);
    } catch {
      /* ignore */
    }

    // Spawn a momentum-decay loop. velocity is in px/ms; scale to
    // per-frame at ~60fps (16.67ms) for the initial step then decay.
    if (s.moved && Math.abs(s.velocity) > MIN_VELOCITY / 16) {
      let v = s.velocity * 16; // px per frame
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

    // Click-after-drag suppression: keep the flag true for one tick
    // so the button onClick can read it and bail.
    if (s.moved) {
      setTimeout(() => {
        wasDraggingRef.current = false;
      }, 0);
    } else {
      wasDraggingRef.current = false;
    }
  };

  const handleStageClick = (order: number) => {
    if (wasDraggingRef.current) return;
    onSelect(order);
  };

  return (
    <div className="relative flex items-center gap-3 h-[104px] pl-3 pr-3 border-b border-[hsl(var(--border))] bg-[hsl(var(--card))] shrink-0 overflow-hidden">
      {/* Background subtle gradient texture */}
      <div
        className="pointer-events-none absolute inset-0 opacity-[0.4]"
        style={{
          background:
            'radial-gradient(ellipse 60% 100% at 50% 50%, hsl(var(--primary) / 0.06) 0%, transparent 70%)',
        }}
      />

      {/* Back button — always-visible, sticky on the left */}
      <button
        type="button"
        onClick={onBack}
        className="relative z-10 inline-flex items-center gap-1.5 h-11 px-3 rounded-lg border border-[hsl(var(--border))] bg-[hsl(var(--background))] text-[0.8125rem] font-medium text-[hsl(var(--foreground))] hover:border-[hsl(var(--primary)/0.4)] hover:bg-[hsl(var(--accent))] hover:text-[hsl(var(--primary))] transition-all shrink-0 shadow-sm"
        title={t('envManagement.progress.backTip')}
      >
        <ArrowLeft className="w-4 h-4" />
        {t('envManagement.progress.back')}
      </button>

      {/* Vertical separator */}
      <div className="relative z-10 w-px h-12 bg-gradient-to-b from-transparent via-[hsl(var(--border))] to-transparent shrink-0" />

      {/* Scroll container — masked at the left/right edges so stages
          appear to "rotate around" an invisible cylinder. */}
      <div
        ref={scrollRef}
        onWheel={onWheel}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerLeave={onPointerUp}
        onPointerCancel={onPointerUp}
        className="relative z-10 flex items-center flex-1 min-w-0 overflow-x-auto overflow-y-hidden scrollbar-hide cursor-grab active:cursor-grabbing select-none"
        style={{
          maskImage:
            'linear-gradient(to right, transparent 0px, black 36px, black calc(100% - 36px), transparent 100%)',
          WebkitMaskImage:
            'linear-gradient(to right, transparent 0px, black 36px, black calc(100% - 36px), transparent 100%)',
          touchAction: 'pan-x',
        }}
      >
        {/* Centre line — connecting "rail" behind the stage circles */}
        <div
          aria-hidden
          className="absolute left-0 right-0 top-1/2 h-px -translate-y-px"
          style={{
            background:
              'linear-gradient(to right, transparent 0%, hsl(var(--border)) 8%, hsl(var(--border)) 92%, transparent 100%)',
          }}
        />

        <div className="flex items-center px-4">
          {ALL_ORDERS.map((order, idx) => {
            const meta = getStageMetaByOrder(order, locale);
            const color = meta ? getCategoryColor(meta.category) : null;
            const isSelected = order === selectedOrder;
            const isStageActive = activeOrders.has(order);
            const isDirty = dirtyOrders.has(order);
            const label = meta?.displayName ?? `Stage ${order}`;
            const isLast = idx === ALL_ORDERS.length - 1;
            const nextActive = activeOrders.has(order + 1);

            return (
              <div key={order} className="flex items-center shrink-0">
                <button
                  ref={(el) => {
                    if (el) itemRefs.current.set(order, el);
                    else itemRefs.current.delete(order);
                  }}
                  data-stage-button
                  type="button"
                  onClick={() => handleStageClick(order)}
                  className="group relative flex flex-col items-center gap-1 px-1.5 py-1 min-w-[80px] transition-transform"
                  title={label}
                >
                  {/* Glow halo (selected only) */}
                  {isSelected && (
                    <span
                      aria-hidden
                      className="absolute top-1/2 left-1/2 -translate-x-1/2 -translate-y-1/2 pointer-events-none"
                      style={{
                        width: 86,
                        height: 86,
                        marginTop: -22,
                        borderRadius: '50%',
                        background: `radial-gradient(closest-side, ${
                          color?.accent ?? 'hsl(var(--primary))'
                        }, transparent 70%)`,
                        opacity: 0.35,
                        filter: 'blur(6px)',
                      }}
                    />
                  )}

                  {/* Stage circle */}
                  <div
                    className={`relative flex items-center justify-center rounded-full font-bold tabular-nums transition-all duration-200 ${
                      isSelected
                        ? 'w-[58px] h-[58px] text-[1.0625rem] shadow-lg'
                        : 'w-[48px] h-[48px] text-[0.9375rem] group-hover:scale-105 group-hover:shadow-md'
                    }`}
                    style={{
                      background: isSelected
                        ? `linear-gradient(135deg, ${
                            color?.bg ?? 'hsl(var(--primary)/0.15)'
                          } 0%, ${color?.accent ?? 'hsl(var(--primary))'} 130%)`
                        : isStageActive
                          ? color?.bg ?? 'hsl(var(--accent))'
                          : 'hsl(var(--background))',
                      color: isSelected
                        ? '#ffffff'
                        : isStageActive
                          ? color?.accent ?? 'hsl(var(--primary))'
                          : 'hsl(var(--muted-foreground))',
                      border: `2px solid ${
                        isSelected
                          ? color?.accent ?? 'hsl(var(--primary))'
                          : isStageActive
                            ? color?.border ?? 'hsl(var(--border))'
                            : 'hsl(var(--border))'
                      }`,
                      boxShadow: isSelected
                        ? `0 8px 22px -8px ${
                            color?.accent ?? 'hsl(var(--primary))'
                          }, 0 0 0 4px hsl(var(--card)), 0 0 0 5.5px ${
                            color?.accent ?? 'hsl(var(--primary))'
                          }`
                        : undefined,
                    }}
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
                  </div>

                  {/* Label */}
                  <span
                    className={`text-[0.75rem] tracking-tight truncate max-w-[88px] leading-tight transition-colors ${
                      isSelected
                        ? 'text-[hsl(var(--foreground))] font-semibold'
                        : isStageActive
                          ? 'text-[hsl(var(--foreground))] font-medium'
                          : 'text-[hsl(var(--muted-foreground))] group-hover:text-[hsl(var(--foreground))]'
                    }`}
                    style={{
                      color:
                        isSelected && color
                          ? color.accent
                          : undefined,
                    }}
                  >
                    {label}
                  </span>
                </button>

                {/* Connector between adjacent stages */}
                {!isLast && (
                  <span
                    aria-hidden
                    className="block h-[3px] mx-0.5 rounded-full shrink-0 transition-all"
                    style={{
                      width: 18,
                      background:
                        isStageActive && nextActive
                          ? `linear-gradient(to right, ${
                              color?.accent ?? 'hsl(var(--primary))'
                            }/60, ${
                              getCategoryColor(
                                getStageMetaByOrder(order + 1, locale)
                                  ?.category ?? 'ingress',
                              ).accent
                            }/60)`
                          : 'hsl(var(--border))',
                      opacity: isStageActive && nextActive ? 0.55 : 0.4,
                    }}
                  />
                )}
              </div>
            );
          })}
        </div>
      </div>
    </div>
  );
}
