'use client';

/**
 * ToolCheckboxGrid — reusable checkbox grid over the framework tool
 * catalog, grouped by feature_group.
 *
 * Two value modes:
 *   - "allowlist": value is the explicit list of selected tool names.
 *     `*` is treated as "all tools" — checking any individual tool
 *     replaces the wildcard with the explicit list.
 *   - "blocklist": value is the list of names to BLOCK; everything
 *     not listed is allowed. (Used by stage tool_binding.blocked.)
 *
 * The grid auto-fetches the framework catalog on mount; pass
 * `tools` to short-circuit (used when the parent already has the
 * list loaded — e.g. ToolSetsTab).
 */

import { useEffect, useMemo, useState } from 'react';
import { Search, ChevronDown, ChevronRight, Info } from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import {
  frameworkToolApi,
  type FrameworkToolDetail,
} from '@/lib/api';
import { Input } from '@/components/ui/input';

export interface ToolCheckboxGridProps {
  /** Currently-selected tool names. `["*"]` means "all tools" in
   *  allowlist mode and "block all" in blocklist mode. */
  value: string[];
  onChange: (next: string[]) => void;
  /** allowlist (default) or blocklist semantics. */
  mode?: 'allowlist' | 'blocklist';
  /** Hint shown above the grid. */
  hint?: string;
  /** Optional pre-loaded catalog (skips the network fetch). */
  tools?: FrameworkToolDetail[];
  /** Optional click handler for the per-tool info button (opens a
   *  drawer / modal showing description + capabilities + schema). */
  onShowToolInfo?: (tool: FrameworkToolDetail) => void;
  /** When true, hides the "Select all / Clear all" header bar. */
  hideBulkControls?: boolean;
}

export default function ToolCheckboxGrid({
  value,
  onChange,
  mode = 'allowlist',
  hint,
  tools: externalTools,
  onShowToolInfo,
  hideBulkControls = false,
}: ToolCheckboxGridProps) {
  const { t } = useI18n();

  const [tools, setTools] = useState<FrameworkToolDetail[]>(externalTools ?? []);
  const [loading, setLoading] = useState(!externalTools);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState('');
  const [collapsed, setCollapsed] = useState<Record<string, boolean>>({});

  useEffect(() => {
    if (externalTools) {
      setTools(externalTools);
      return;
    }
    let cancelled = false;
    setLoading(true);
    frameworkToolApi
      .list()
      .then((res) => {
        if (cancelled) return;
        setTools(res.tools);
      })
      .catch((e) => {
        if (cancelled) return;
        setError(e instanceof Error ? e.message : String(e));
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, [externalTools]);

  const isWildcard = value.includes('*');
  const selectedSet = useMemo(() => new Set(value), [value]);

  // Group by feature_group
  const grouped = useMemo(() => {
    const m = new Map<string, FrameworkToolDetail[]>();
    for (const tool of tools) {
      const g = tool.feature_group || 'other';
      if (!m.has(g)) m.set(g, []);
      m.get(g)!.push(tool);
    }
    return m;
  }, [tools]);

  // Apply search filter
  const filteredGroups = useMemo(() => {
    if (!search) return grouped;
    const q = search.toLowerCase();
    const out = new Map<string, FrameworkToolDetail[]>();
    for (const [group, ts] of grouped) {
      const hits = ts.filter(
        (t) =>
          t.name.toLowerCase().includes(q) ||
          (t.description || '').toLowerCase().includes(q),
      );
      if (hits.length > 0) out.set(group, hits);
    }
    return out;
  }, [grouped, search]);

  const toggleTool = (name: string) => {
    if (isWildcard) {
      // Replace wildcard with the full explicit list MINUS this tool
      // (allowlist) / PLUS this tool (blocklist), so the user keeps
      // working with explicit names from here.
      const all = tools.map((t) => t.name);
      if (mode === 'allowlist') {
        onChange(all.filter((n) => n !== name));
      } else {
        // blocklist + wildcard means "block all". Toggling one off
        // means "block all except this one" → next list is `all -
        // [name]` (everything else still blocked).
        onChange(all.filter((n) => n !== name));
      }
      return;
    }
    if (selectedSet.has(name)) {
      onChange(value.filter((n) => n !== name));
    } else {
      onChange([...value, name]);
    }
  };

  const toggleGroup = (group: string) => {
    const groupTools = grouped.get(group) ?? [];
    const groupNames = groupTools.map((t) => t.name);
    const allOn = groupNames.every((n) => selectedSet.has(n));
    if (allOn) {
      onChange(value.filter((n) => !groupNames.includes(n)));
    } else {
      const next = new Set(value.filter((n) => n !== '*'));
      groupNames.forEach((n) => next.add(n));
      onChange(Array.from(next));
    }
  };

  const handleSelectAll = () => onChange(['*']);
  const handleClearAll = () => onChange([]);

  // Status line
  const totalCount = tools.length;
  const effectiveCount = isWildcard ? totalCount : value.length;

  if (loading) {
    return (
      <div className="text-[0.75rem] text-[hsl(var(--muted-foreground))] py-3">
        {t('common.loading')}
      </div>
    );
  }

  if (error) {
    return (
      <div className="px-3 py-2 rounded-md bg-red-500/10 border border-red-500/30 text-[0.75rem] text-red-700 dark:text-red-300">
        {error}
      </div>
    );
  }

  return (
    <div className="flex flex-col gap-2">
      {hint && (
        <p className="text-[0.7rem] text-[hsl(var(--muted-foreground))] leading-relaxed">
          {hint}
        </p>
      )}

      {/* Header: search + select-all */}
      <div className="flex items-center gap-2 flex-wrap">
        <div className="relative flex-1 min-w-[180px] max-w-[260px]">
          <Search
            size={12}
            className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[hsl(var(--muted-foreground))] pointer-events-none"
          />
          <Input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder={t('envManagement.toolGrid.search')}
            className="pl-7 h-7 text-[0.75rem]"
          />
        </div>
        <span className="text-[0.6875rem] text-[hsl(var(--muted-foreground))] tabular-nums">
          {mode === 'allowlist'
            ? t('envManagement.toolGrid.allowedCount', {
                n: String(effectiveCount),
                total: String(totalCount),
              })
            : t('envManagement.toolGrid.blockedCount', {
                n: String(effectiveCount),
                total: String(totalCount),
              })}
        </span>
        {!hideBulkControls && (
          <div className="ml-auto flex items-center gap-1">
            <button
              type="button"
              onClick={handleSelectAll}
              className={`px-2 py-0.5 rounded text-[0.6875rem] font-medium border transition-colors ${
                isWildcard
                  ? 'border-[hsl(var(--primary))] bg-[hsl(var(--primary)/0.12)] text-[hsl(var(--primary))]'
                  : 'border-[hsl(var(--border))] text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))]'
              }`}
            >
              {t('envManagement.toolGrid.selectAll')}
            </button>
            <button
              type="button"
              onClick={handleClearAll}
              disabled={!isWildcard && value.length === 0}
              className="px-2 py-0.5 rounded text-[0.6875rem] font-medium border border-[hsl(var(--border))] text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))] disabled:opacity-40 disabled:cursor-not-allowed"
            >
              {t('envManagement.toolGrid.clearAll')}
            </button>
          </div>
        )}
      </div>

      {/* Wildcard hint */}
      {isWildcard && (
        <div className="px-3 py-2 rounded-md bg-[hsl(var(--primary)/0.06)] border border-[hsl(var(--primary)/0.2)] text-[0.7rem] text-[hsl(var(--foreground))]">
          {mode === 'allowlist'
            ? t('envManagement.toolGrid.wildcardAllowHint')
            : t('envManagement.toolGrid.wildcardBlockHint')}
        </div>
      )}

      {/* Groups */}
      <div className="flex flex-col gap-2 max-h-[420px] overflow-y-auto">
        {Array.from(filteredGroups.entries()).map(([group, ts]) => {
          const open = !collapsed[group];
          const groupNames = ts.map((t) => t.name);
          const allOn =
            isWildcard || groupNames.every((n) => selectedSet.has(n));
          const someOn =
            !allOn && groupNames.some((n) => selectedSet.has(n));
          return (
            <div
              key={group}
              className="rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))]"
            >
              <div className="flex items-center gap-2 px-2 py-1.5">
                <button
                  type="button"
                  onClick={() =>
                    setCollapsed((prev) => ({ ...prev, [group]: !prev[group] }))
                  }
                  className="text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]"
                >
                  {open ? (
                    <ChevronDown className="w-3.5 h-3.5" />
                  ) : (
                    <ChevronRight className="w-3.5 h-3.5" />
                  )}
                </button>
                <input
                  type="checkbox"
                  checked={allOn}
                  ref={(el) => {
                    if (el) el.indeterminate = someOn;
                  }}
                  onChange={() => toggleGroup(group)}
                  className="w-3.5 h-3.5 accent-[hsl(var(--primary))]"
                  aria-label={`Toggle ${group}`}
                />
                <span className="text-[0.75rem] font-semibold text-[hsl(var(--foreground))] flex-1">
                  {group}
                </span>
                <span className="text-[0.625rem] text-[hsl(var(--muted-foreground))] tabular-nums">
                  {isWildcard
                    ? `${ts.length}/${ts.length}`
                    : `${groupNames.filter((n) => selectedSet.has(n)).length}/${ts.length}`}
                </span>
              </div>
              {open && (
                <div className="px-2 pb-2 grid grid-cols-1 md:grid-cols-2 gap-y-0.5 gap-x-2">
                  {ts.map((tool) => {
                    const checked = isWildcard || selectedSet.has(tool.name);
                    return (
                      <label
                        key={tool.name}
                        className="flex items-center gap-2 py-0.5 px-1 rounded text-[0.75rem] hover:bg-[hsl(var(--accent))] cursor-pointer group"
                      >
                        <input
                          type="checkbox"
                          checked={checked}
                          onChange={() => toggleTool(tool.name)}
                          className="w-3 h-3 accent-[hsl(var(--primary))] shrink-0"
                        />
                        <code className="text-[hsl(var(--foreground))] font-mono text-[0.7rem] truncate flex-1">
                          {tool.name}
                        </code>
                        {onShowToolInfo && (
                          <button
                            type="button"
                            onClick={(e) => {
                              e.preventDefault();
                              onShowToolInfo(tool);
                            }}
                            className="opacity-0 group-hover:opacity-100 transition-opacity text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--primary))]"
                            aria-label="info"
                          >
                            <Info className="w-3 h-3" />
                          </button>
                        )}
                      </label>
                    );
                  })}
                </div>
              )}
            </div>
          );
        })}
        {filteredGroups.size === 0 && (
          <p className="text-[0.75rem] text-[hsl(var(--muted-foreground))] italic py-2 text-center">
            {t('envManagement.toolGrid.noMatch')}
          </p>
        )}
      </div>
    </div>
  );
}
