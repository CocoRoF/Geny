'use client';

/**
 * PipelineCanvas — SVG+HTML hybrid canvas that visualises the 21-stage
 * pipeline shape of an EnvironmentManifest. Read-only: Geny's session
 * view is purely "which environment is applied", not "is it running
 * right now".
 *
 * G1.2: layout widened from 16 to 21 stages (Sub-phase 9a renumber).
 * Phase B grew from 12 to 15 stages — laid out as three 5-wide rows
 * with serpentine flow (left → right → right → left → left → right).
 * Phase C grew from 3 to 5 stages and is centred under Phase B.
 */

import { useEffect, useRef } from 'react';
import { useI18n } from '@/lib/i18n';
import type { StageManifestEntry } from '@/types/environment';
import { getStageMetaByOrder } from './stageMetadata';
import { useZoomPan } from './useZoomPan';

/* ═══ Layout constants — sized for the 21-stage layout ═══ */
const GAP = 110;
const LM = 120;
const ROW_A = 55;
const ROW_B1 = 175;
const ROW_B2 = 295;
const ROW_B3 = 415;
const ROW_C = 535;
const R = 27;
const CANVAS_W = 770;
const CANVAS_H = 600;

interface Pos {
  x: number;
  y: number;
}

function buildPositions(): Map<number, Pos> {
  const m = new Map<number, Pos>();
  const midX = LM + 2 * GAP; // centre of a 5-wide row (i = 0..4)

  // Phase A — stage 1 centred
  m.set(1, { x: midX, y: ROW_A });

  // Phase B row 1 — stages 2-6 left → right
  for (let i = 0; i < 5; i++) m.set(2 + i, { x: LM + i * GAP, y: ROW_B1 });

  // Phase B row 2 — stages 7-11 reversed (11 at left, 7 at right)
  for (let i = 0; i < 5; i++) m.set(11 - i, { x: LM + i * GAP, y: ROW_B2 });

  // Phase B row 3 — stages 12-16 left → right
  for (let i = 0; i < 5; i++) m.set(12 + i, { x: LM + i * GAP, y: ROW_B3 });

  // Phase C — stages 17-21 centred
  for (let i = 0; i < 5; i++) m.set(17 + i, { x: LM + i * GAP, y: ROW_C });

  return m;
}

const positions = buildPositions();

interface StageNodeProps {
  order: number;
  entry: StageManifestEntry | undefined;
  isSelected: boolean;
  onSelect: (order: number | null) => void;
  /** Cycle 20260427_1 — pulse + accent ring when the stage has unsaved
   *  edits in the Library (NEW) draft store. Optional so the read-only
   *  SessionEnvironmentTab call site stays unchanged. */
  isDirty?: boolean;
}

function StageNode({ order, entry, isSelected, onSelect, isDirty = false }: StageNodeProps) {
  const locale = useI18n((s) => s.locale);
  const meta = getStageMetaByOrder(order, locale);
  const displayName = meta?.displayName ?? entry?.name ?? `Stage ${order}`;

  const isActive = !!entry?.active;
  const isPresent = !!entry;

  let cls = 'stage-circle';
  if (!isPresent || !isActive) cls += ' inactive';
  else cls += ' active';
  if (isSelected) cls += ' selected';

  return (
    <div
      className="flex flex-col items-center relative"
      style={{ width: R * 2 + 20 }}
      onClick={(e) => {
        e.stopPropagation();
        onSelect(isSelected ? null : order);
      }}
      onPointerDown={(e) => e.stopPropagation()}
    >
      <div className={cls} style={{ position: 'relative' }}>
        {order}
        {isDirty && (
          <span
            aria-label="edited"
            title="Edited (unsaved)"
            style={{
              position: 'absolute',
              top: -4,
              right: -4,
              width: 10,
              height: 10,
              borderRadius: '50%',
              background: 'var(--pipe-accent)',
              boxShadow: '0 0 0 2px var(--pipe-bg-primary), 0 0 10px var(--pipe-accent-glow, rgba(59,130,246,0.5))',
            }}
          />
        )}
      </div>
      <span
        className="mt-1.5 text-[10px] font-medium tracking-wide text-center leading-tight"
        style={{
          color: isSelected
            ? 'var(--pipe-accent)'
            : isActive || isDirty
              ? 'var(--pipe-accent)'
              : 'var(--pipe-text-secondary)',
          maxWidth: 88,
          overflow: 'hidden',
          textOverflow: 'ellipsis',
          whiteSpace: 'nowrap',
        }}
      >
        {displayName}
      </span>
    </div>
  );
}

/* ═══ SVG Connections ═══ */
function Connections() {
  const baseColor = 'var(--pipe-border-hover)';
  const baseOpacity = 0.35;

  const hLine = (from: number, to: number) => {
    const a = positions.get(from)!;
    const b = positions.get(to)!;
    const x1 = a.x < b.x ? a.x + R : a.x - R;
    const x2 = a.x < b.x ? b.x - R : b.x + R;
    return (
      <line
        key={`h-${from}-${to}`}
        x1={x1}
        y1={a.y}
        x2={x2}
        y2={b.y}
        stroke={baseColor}
        strokeWidth={1.5}
        strokeLinecap="round"
        opacity={baseOpacity}
      />
    );
  };

  const curve = (
    from: number,
    to: number,
    key: string,
    opts?: {
      bulgeX?: number;
      dashed?: boolean;
      color?: string;
      opacity?: number;
      className?: string;
    },
  ) => {
    const a = positions.get(from)!;
    const b = positions.get(to)!;
    const goDown = b.y > a.y;
    const y1 = goDown ? a.y + R : a.y - R;
    const y2 = goDown ? b.y - R : b.y + R;

    let d: string;
    if (opts?.bulgeX !== undefined) {
      d = `M ${a.x} ${y1} C ${opts.bulgeX} ${y1}, ${opts.bulgeX} ${y2}, ${b.x} ${y2}`;
    } else {
      const my = (y1 + y2) / 2;
      d = `M ${a.x} ${y1} C ${a.x} ${my}, ${b.x} ${my}, ${b.x} ${y2}`;
    }

    return (
      <path
        key={key}
        d={d}
        stroke={opts?.color ?? baseColor}
        strokeWidth={1.5}
        strokeLinecap="round"
        strokeDasharray={opts?.dashed ? '5 4' : undefined}
        fill="none"
        opacity={opts?.opacity ?? baseOpacity}
        className={opts?.className}
      />
    );
  };

  return (
    <g>
      {/* Phase A → B */}
      {curve(1, 2, 'a-b')}

      {/* Phase B row 1: 2→3→4→5→6 */}
      {[2, 3, 4, 5].map((n) => hLine(n, n + 1))}

      {/* U-turn right: 6 → 7 */}
      {curve(6, 7, 'uturn-r-1', { bulgeX: positions.get(6)!.x + 55 })}

      {/* Phase B row 2: 7→8→9→10→11 (rendered right-to-left visually
          because positions for 7..11 are reversed in buildPositions) */}
      {[7, 8, 9, 10].map((n) => hLine(n, n + 1))}

      {/* U-turn left: 11 → 12 */}
      {curve(11, 12, 'uturn-l-1', { bulgeX: positions.get(11)!.x - 55 })}

      {/* Phase B row 3: 12→13→14→15→16 */}
      {[12, 13, 14, 15].map((n) => hLine(n, n + 1))}

      {/* Loop-back: 16 → 2 (left side, dashed) */}
      {curve(16, 2, 'loop', {
        bulgeX: positions.get(16)!.x - 55,
        dashed: true,
        color: 'var(--pipe-accent)',
        opacity: 0.3,
        className: 'pipe-dash-flow',
      })}

      {/* Phase B → C: 16 → 17 */}
      {curve(16, 17, 'b-c')}

      {/* Phase C: 17→18→19→20→21 */}
      {[17, 18, 19, 20].map((n) => hLine(n, n + 1))}
    </g>
  );
}

/* ═══ SVG Decorations (grid, labels, bounding box) ═══ */
function Decorations() {
  const locale = useI18n((s) => s.locale);
  const isKo = locale === 'ko';
  // Centre of Phase B's three rows is the middle row (B2).
  const midY_B = ROW_B2;

  return (
    <g>
      {/* Dot grid */}
      <defs>
        <pattern id="pipe-dot-grid" width="30" height="30" patternUnits="userSpaceOnUse">
          <circle cx="1" cy="1" r="0.4" fill="var(--pipe-text-muted)" opacity="0.12" />
        </pattern>
      </defs>
      <rect width={CANVAS_W} height={CANVAS_H} fill="url(#pipe-dot-grid)" />

      {/* Phase labels */}
      {[
        { label: 'A', sub: isKo ? '초기화' : 'init', y: ROW_A },
        { label: 'B', sub: isKo ? '에이전트 루프' : 'agent loop', y: midY_B },
        { label: 'C', sub: isKo ? '최종' : 'final', y: ROW_C },
      ].map((p) => (
        <g key={p.label}>
          <text
            x={28}
            y={p.y - 5}
            fill="var(--pipe-accent)"
            fontSize={10}
            fontWeight={700}
            letterSpacing="0.18em"
            fontFamily="var(--font-inter, 'Inter'), sans-serif"
            opacity={0.7}
          >
            {p.label}
          </text>
          <text
            x={28}
            y={p.y + 9}
            fill="var(--pipe-text-muted)"
            fontSize={8}
            fontFamily="var(--font-inter, 'Inter'), sans-serif"
            opacity={0.5}
          >
            {p.sub}
          </text>
        </g>
      ))}

      {/* Phase B bounding box — spans all 3 serpentine rows */}
      <rect
        x={LM - 50}
        y={ROW_B1 - 46}
        width={5 * GAP + 100 + 55}
        height={ROW_B3 - ROW_B1 + 92}
        rx={16}
        fill="none"
        stroke="var(--pipe-border)"
        strokeWidth={1}
        strokeDasharray="6 4"
        opacity={0.18}
      />

      {/* (Loop label removed — was overlapping with the section B
          "에이전트 루프" label rendered above. The looping arrow itself
          already communicates the loop-back semantics.) */}
    </g>
  );
}

/* ═══ Public component ═══ */
interface PipelineCanvasProps {
  stages: StageManifestEntry[];
  selectedOrder: number | null;
  onSelectStage: (order: number | null) => void;
  onResetView?: (resetFn: () => void) => void;
  /** Cycle 20260427_1 — Library (NEW) edit-mode highlight. Stage orders
   *  in this set get an accent badge to signal "edited but not saved".
   *  Read-only callers (SessionEnvironmentTab) omit it. */
  dirtyOrders?: ReadonlySet<number>;
}

export default function PipelineCanvas({
  stages,
  selectedOrder,
  onSelectStage,
  onResetView,
  dirtyOrders,
}: PipelineCanvasProps) {
  const {
    containerRef,
    transform,
    onPointerDown,
    onPointerMove,
    onPointerUp,
    resetView,
    fitToView,
  } = useZoomPan(0.4, 3);

  const hasFit = useRef(false);
  const stageByOrder = new Map<number, StageManifestEntry>();
  for (const s of stages) stageByOrder.set(s.order, s);

  // Auto-fit content on first mount
  useEffect(() => {
    if (hasFit.current) return;
    const t = setTimeout(() => {
      fitToView(CANVAS_W, CANVAS_H, 30);
      hasFit.current = true;
    }, 60);
    return () => clearTimeout(t);
  }, [fitToView]);

  // Expose reset to parent (used by the "Reset" header button)
  useEffect(() => {
    if (!onResetView) return;
    onResetView(() => {
      hasFit.current = false;
      resetView();
      // Then re-fit after state settles
      setTimeout(() => {
        fitToView(CANVAS_W, CANVAS_H, 30);
        hasFit.current = true;
      }, 60);
    });
  }, [onResetView, resetView, fitToView]);

  // Render 21 slots so layout stays stable even if the manifest
  // doesn't list every stage (missing stages show as .inactive).
  const slots: number[] = [];
  for (let i = 1; i <= 21; i++) slots.push(i);

  return (
    <div
      ref={containerRef}
      className="flex-1 overflow-hidden cursor-grab active:cursor-grabbing select-none relative"
      style={{ background: 'var(--pipe-bg-primary)' }}
      onPointerDown={onPointerDown}
      onPointerMove={onPointerMove}
      onPointerUp={onPointerUp}
      onPointerLeave={onPointerUp}
    >
      <div
        style={{
          transform: `translate(${transform.x}px, ${transform.y}px) scale(${transform.scale})`,
          transformOrigin: '0 0',
          width: CANVAS_W,
          height: CANVAS_H,
          position: 'relative',
        }}
      >
        <svg
          width={CANVAS_W}
          height={CANVAS_H}
          style={{ position: 'absolute', inset: 0, pointerEvents: 'none' }}
        >
          <Decorations />
          <Connections />
        </svg>

        {slots.map((order) => {
          const pos = positions.get(order);
          if (!pos) return null;
          const halfW = R + 10;
          return (
            <div
              key={order}
              style={{
                position: 'absolute',
                left: pos.x - halfW,
                top: pos.y - R,
                width: halfW * 2,
                display: 'flex',
                justifyContent: 'center',
              }}
            >
              <StageNode
                order={order}
                entry={stageByOrder.get(order)}
                isSelected={selectedOrder === order}
                onSelect={onSelectStage}
                isDirty={dirtyOrders?.has(order) ?? false}
              />
            </div>
          );
        })}
      </div>
    </div>
  );
}

export { CANVAS_W, CANVAS_H };
