'use client';

/**
 * RegistryPageShell — common chrome for the four host-registry tabs
 * (MCP / SKILLS / HOOK / 권한). Visual treatment mirrors the env
 * welcome card's hero pattern: large rounded icon-tile, generous
 * title, muted description, action cluster on the right.
 *
 *   ┌─ hero (gradient subtle, breathing room) ──────────────────────┐
 *   │ [icon-tile]  Title · {count}                  [Add] [Refresh] │
 *   │              {subtitle / description}                          │
 *   ├─ compact info banner ──────────────────────────────────────────┤
 *   │ ⓘ 호스트 공용 — {note}                                         │
 *   ├─ body (max-width container, padded) ───────────────────────────┤
 *   │ {children}                                                     │
 *   └────────────────────────────────────────────────────────────────┘
 *
 * Cycle 20260429 Phase 8.1 — replaced the slim TabShell-style header
 * with the hero treatment so registry tabs read at the same polish
 * level as `OverviewView`'s welcome card. Operator's previous
 * complaint: "옛날 쓰레기 같은 레이아웃". The fix consolidates the
 * page chrome into a single coherent surface instead of two thin
 * strips stacked on top of a centered card.
 */

import type { ReactNode } from 'react';
import { Info, Plus, RefreshCw, X, AlertCircle, type LucideIcon } from 'lucide-react';
import { IconButton } from '@/components/common/layout';

export interface RegistryPageShellProps {
  /** Page title, e.g. "MCP 서버". */
  title: string;
  /** Description / subtitle below the title. */
  subtitle?: ReactNode;
  /** Page-level icon — rendered in a tinted rounded tile. */
  icon: LucideIcon;
  /** Count chip beside the title (e.g. "3개 서버"). */
  countLabel?: string;
  /** Banner note — slim info chip. */
  bannerNote?: string;
  /** Primary "Add" button label. */
  addLabel?: string;
  onAdd?: () => void;
  onRefresh?: () => void;
  loading?: boolean;
  error?: string | null;
  onDismissError?: () => void;
  /** Right-of-actions slot for tab-specific controls (e.g. mode
   *  selectors, enabled toggle). Rendered before the Refresh
   *  button so the visual weight reads left → right as
   *  "context → actions". */
  headerExtras?: ReactNode;
  /** Body content — sections / grids / empty state. */
  children: ReactNode;
}

export default function RegistryPageShell({
  title,
  subtitle,
  icon: Icon,
  countLabel,
  bannerNote,
  addLabel,
  onAdd,
  onRefresh,
  loading = false,
  error = null,
  onDismissError,
  headerExtras,
  children,
}: RegistryPageShellProps) {
  return (
    <div className="flex flex-col h-full min-h-0 bg-[hsl(var(--background))] text-[hsl(var(--foreground))]">
      {/* Indeterminate loading strip (above hero so it doesn't push layout). */}
      {loading && (
        <div className="relative h-0.5 bg-[hsl(var(--border))] overflow-hidden shrink-0">
          <div className="absolute inset-y-0 w-1/3 bg-[hsl(var(--primary))] animate-loading-strip" />
        </div>
      )}

      <div className="flex-1 min-h-0 overflow-y-auto">
        <div className="max-w-[1200px] mx-auto px-6 py-8 flex flex-col gap-6">
          {/* ── Hero ── */}
          <header className="flex items-start gap-4">
            <div className="inline-flex items-center justify-center w-12 h-12 rounded-2xl bg-[hsl(var(--primary)/0.1)] shrink-0 mt-0.5">
              <Icon className="w-6 h-6 text-[hsl(var(--primary))]" strokeWidth={2} />
            </div>
            <div className="flex-1 min-w-0">
              <div className="flex items-baseline gap-2 flex-wrap">
                <h2 className="text-[1.25rem] font-semibold tracking-tight text-[hsl(var(--foreground))] truncate">
                  {title}
                </h2>
                {countLabel && (
                  <span className="text-[0.75rem] text-[hsl(var(--muted-foreground))] tabular-nums">
                    {countLabel}
                  </span>
                )}
              </div>
              {subtitle && (
                <p className="text-[0.8125rem] text-[hsl(var(--muted-foreground))] mt-1 leading-relaxed">
                  {subtitle}
                </p>
              )}
            </div>
            <div className="flex items-center gap-1.5 shrink-0 mt-1">
              {headerExtras}
              {onRefresh && (
                <IconButton
                  icon={RefreshCw}
                  title="Refresh"
                  spin={loading}
                  disabled={loading}
                  onClick={onRefresh}
                />
              )}
              {onAdd && addLabel && (
                <IconButton icon={Plus} variant="primary" title={addLabel} onClick={onAdd} />
              )}
            </div>
          </header>

          {/* ── Info banner (compact) ── */}
          {bannerNote && (
            <div className="flex items-start gap-2 px-3 py-2 rounded-lg border border-amber-500/25 bg-amber-500/5 text-[0.7rem] text-amber-800 dark:text-amber-300 leading-relaxed">
              <Info className="w-3.5 h-3.5 mt-0.5 shrink-0" />
              <div className="flex-1 min-w-0">
                <span className="font-semibold uppercase tracking-wider mr-1.5">
                  호스트 공용
                </span>
                {bannerNote}
              </div>
            </div>
          )}

          {/* ── Error chip ── */}
          {error && (
            <div className="flex items-start gap-2 px-3 py-2 rounded-lg border border-red-500/30 bg-red-500/10">
              <AlertCircle className="w-3.5 h-3.5 mt-0.5 text-red-700 dark:text-red-300 shrink-0" />
              <div className="flex-1 text-[0.75rem] text-red-700 dark:text-red-300">
                {error}
              </div>
              {onDismissError && (
                <button
                  type="button"
                  onClick={onDismissError}
                  className="text-red-700 dark:text-red-300 hover:opacity-70 shrink-0"
                  aria-label="dismiss"
                >
                  <X className="w-3.5 h-3.5" />
                </button>
              )}
            </div>
          )}

          {/* ── Body ── */}
          <div className="flex flex-col gap-5">{children}</div>
        </div>
      </div>
    </div>
  );
}
