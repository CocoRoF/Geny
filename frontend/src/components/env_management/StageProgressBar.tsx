'use client';

/**
 * StageProgressBar — horizontal scrollable navigator for the 21
 * pipeline stages, used inside the Stage detail view (cycle 20260427_2
 * PR-2).
 *
 * NOT a progress indicator — purely navigation. Each stage is a pill
 * with its number + display name; clicking jumps to that stage.
 * Active stage is highlighted; dirty stages show an accent dot.
 *
 * The bar scrolls horizontally with mouse wheel + drag, like a tab
 * strip. The active stage auto-scrolls into view on selection.
 *
 * Layout:
 *   [← back] | ◯─◯─●─◯─◯─◯─...─◯ | (overflow scrolls)
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
  /** Stages currently active in the manifest (controls the
   *  filled-vs-outline visual). */
  activeOrders: ReadonlySet<number>;
}

const ALL_ORDERS = Array.from({ length: 21 }, (_, i) => i + 1);

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

  // Auto-scroll the selected stage into view when it changes.
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

  // Mouse-wheel → horizontal scroll
  const onWheel = (e: React.WheelEvent<HTMLDivElement>) => {
    if (!scrollRef.current) return;
    if (Math.abs(e.deltaY) > Math.abs(e.deltaX)) {
      scrollRef.current.scrollLeft += e.deltaY;
    }
  };

  // Drag-to-scroll
  const dragState = useRef<{ active: boolean; startX: number; startScroll: number }>({
    active: false,
    startX: 0,
    startScroll: 0,
  });
  const onPointerDown = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!scrollRef.current) return;
    // Don't start drag if pointer started on a button (let click work)
    if ((e.target as HTMLElement).closest('button')) return;
    dragState.current = {
      active: true,
      startX: e.clientX,
      startScroll: scrollRef.current.scrollLeft,
    };
    scrollRef.current.setPointerCapture(e.pointerId);
  };
  const onPointerMove = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!dragState.current.active || !scrollRef.current) return;
    const dx = e.clientX - dragState.current.startX;
    scrollRef.current.scrollLeft = dragState.current.startScroll - dx;
  };
  const onPointerUp = (e: React.PointerEvent<HTMLDivElement>) => {
    if (!dragState.current.active || !scrollRef.current) return;
    dragState.current.active = false;
    try {
      scrollRef.current.releasePointerCapture(e.pointerId);
    } catch {
      /* ignore */
    }
  };

  return (
    <div className="flex items-center gap-2 h-[68px] px-3 border-b border-[hsl(var(--border))] bg-[hsl(var(--card))] shrink-0">
      <button
        type="button"
        onClick={onBack}
        className="inline-flex items-center gap-1 h-9 px-2.5 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] text-[0.75rem] font-medium text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))] hover:bg-[hsl(var(--accent))] transition-colors shrink-0"
        title={t('envManagement.progress.backTip')}
      >
        <ArrowLeft className="w-3.5 h-3.5" />
        {t('envManagement.progress.back')}
      </button>
      <div className="w-px h-8 bg-[hsl(var(--border))] shrink-0" />

      <div
        ref={scrollRef}
        onWheel={onWheel}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerLeave={onPointerUp}
        className="flex items-center gap-0 flex-1 min-w-0 overflow-x-auto scrollbar-hide cursor-grab active:cursor-grabbing"
      >
        {ALL_ORDERS.map((order, idx) => {
          const meta = getStageMetaByOrder(order, locale);
          const color = meta ? getCategoryColor(meta.category) : null;
          const isActive = order === selectedOrder;
          const isStageActive = activeOrders.has(order);
          const isDirty = dirtyOrders.has(order);
          const label = meta?.displayName ?? `Stage ${order}`;
          const isLast = idx === ALL_ORDERS.length - 1;

          return (
            <div key={order} className="flex items-center shrink-0">
              <button
                ref={(el) => {
                  if (el) itemRefs.current.set(order, el);
                  else itemRefs.current.delete(order);
                }}
                type="button"
                onClick={() => onSelect(order)}
                className={`group relative flex flex-col items-center gap-0.5 px-2 py-1 rounded-md transition-colors min-w-[64px] ${
                  isActive
                    ? 'bg-[hsl(var(--primary)/0.12)]'
                    : 'hover:bg-[hsl(var(--accent))]'
                }`}
                title={label}
              >
                <div
                  className={`relative flex items-center justify-center rounded-full text-[0.6875rem] font-bold tabular-nums transition-all ${
                    isActive ? 'w-9 h-9 ring-2 ring-[hsl(var(--primary))] ring-offset-1 ring-offset-[hsl(var(--card))]' : 'w-7 h-7'
                  }`}
                  style={{
                    background: isActive
                      ? color?.bg ?? 'hsl(var(--primary)/0.15)'
                      : isStageActive
                        ? color?.bg ?? 'hsl(var(--accent))'
                        : 'hsl(var(--background))',
                    color: isStageActive || isActive
                      ? color?.accent ?? 'hsl(var(--primary))'
                      : 'hsl(var(--muted-foreground))',
                    border: `1.5px solid ${
                      isActive
                        ? color?.accent ?? 'hsl(var(--primary))'
                        : isStageActive
                          ? color?.border ?? 'hsl(var(--border))'
                          : 'hsl(var(--border))'
                    }`,
                  }}
                >
                  {order}
                  {isDirty && (
                    <span
                      aria-label="edited"
                      className="absolute -top-0.5 -right-0.5 w-2 h-2 rounded-full bg-[hsl(var(--primary))]"
                      style={{
                        boxShadow: '0 0 0 1.5px hsl(var(--card))',
                      }}
                    />
                  )}
                </div>
                <span
                  className={`text-[0.625rem] tracking-tight truncate max-w-[68px] leading-tight ${
                    isActive
                      ? 'text-[hsl(var(--foreground))] font-semibold'
                      : isStageActive
                        ? 'text-[hsl(var(--foreground))]'
                        : 'text-[hsl(var(--muted-foreground))]'
                  }`}
                >
                  {label}
                </span>
              </button>
              {!isLast && (
                <span
                  aria-hidden
                  className="block w-3 h-0.5 mx-0.5 shrink-0"
                  style={{
                    background:
                      activeOrders.has(order) && activeOrders.has(order + 1)
                        ? 'hsl(var(--primary)/0.4)'
                        : 'hsl(var(--border))',
                  }}
                />
              )}
            </div>
          );
        })}
      </div>
    </div>
  );
}
