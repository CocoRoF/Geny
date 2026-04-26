'use client';

/**
 * ToolCatalogTab — viewer for executor's BUILT_IN_TOOL_CLASSES (PR-E.1.2).
 *
 * Surfaces every framework tool (Read / Write / Bash / AgentTool /
 * TaskCreate / etc — 33 tools) so operators can browse what's
 * available before deciding which to enable per preset.
 *
 * Layout:
 *   [Sidebar: feature groups]  [Card grid: tools in active group]  [Detail panel: selected tool]
 */

import { useEffect, useMemo, useState } from 'react';
import { frameworkToolApi, FrameworkToolDetail } from '@/lib/api';
import { environmentApi } from '@/lib/environmentApi';
import type { EnvironmentSummary, EnvironmentDetail } from '@/types/environment';
import { RefreshCw, Check, Wrench } from 'lucide-react';
import {
  TabShell,
  TwoPaneBody,
  DetailDrawer,
  EmptyState,
  ActionButton,
  cn,
} from '@/components/layout';

const ALL = '__all__';

// Capability badges — short labels for the card view.
const CAPABILITY_BADGES: Array<[keyof FrameworkToolDetail['capabilities'], string, string]> = [
  ['read_only', 'read-only', 'bg-green-100 text-green-800'],
  ['destructive', 'destructive', 'bg-red-100 text-red-800'],
  ['concurrency_safe', 'parallel', 'bg-blue-100 text-blue-800'],
  ['idempotent', 'idempotent', 'bg-purple-100 text-purple-800'],
  ['network_egress', 'network', 'bg-amber-100 text-amber-800'],
];

export function ToolCatalogTab() {
  const [tools, setTools] = useState<FrameworkToolDetail[]>([]);
  const [groups, setGroups] = useState<string[]>([]);
  const [activeGroup, setActiveGroup] = useState<string>(ALL);
  const [selected, setSelected] = useState<FrameworkToolDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // ── PR-E.1.4 — Active-in-preset toggle state ─────────────
  // List of "preset" environments (tag === "preset") and the currently
  // selected one. When a preset is selected the card grid shows a per-
  // tool checkbox that mutates manifest.tools.built_in.
  const [presets, setPresets] = useState<EnvironmentSummary[]>([]);
  const [activePresetId, setActivePresetId] = useState<string | null>(null);
  const [activePresetDetail, setActivePresetDetail] = useState<EnvironmentDetail | null>(null);
  const [enabledNames, setEnabledNames] = useState<Set<string>>(new Set());
  const [presetLoading, setPresetLoading] = useState(false);
  const [savingTool, setSavingTool] = useState<string | null>(null);

  const refresh = async () => {
    setLoading(true);
    setError(null);
    try {
      const [catalog, envs] = await Promise.all([
        frameworkToolApi.list(),
        environmentApi.list(),
      ]);
      setTools(catalog.tools);
      setGroups(catalog.groups);
      setPresets(envs.filter((e) => (e.tags || []).includes('preset')));
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  // Load the selected preset's manifest + currently-enabled built-ins.
  useEffect(() => {
    if (!activePresetId) {
      setActivePresetDetail(null);
      setEnabledNames(new Set());
      return;
    }
    let cancelled = false;
    (async () => {
      setPresetLoading(true);
      try {
        const detail = await environmentApi.get(activePresetId);
        if (cancelled) return;
        setActivePresetDetail(detail);
        const names: string[] = detail.manifest?.tools?.built_in ?? [];
        setEnabledNames(new Set(names));
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      } finally {
        if (!cancelled) setPresetLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [activePresetId]);

  // Toggle one tool inside the active preset's manifest. Optimistic
  // update; reverts the local set on failure.
  const toggleTool = async (toolName: string) => {
    if (!activePresetDetail || !activePresetId) return;
    const next = new Set(enabledNames);
    const wasEnabled = next.has(toolName);
    if (wasEnabled) next.delete(toolName);
    else next.add(toolName);

    setEnabledNames(next);
    setSavingTool(toolName);
    try {
      const baseManifest = activePresetDetail.manifest ?? null;
      if (!baseManifest) {
        throw new Error('Preset has no manifest to update');
      }
      const nextTools = {
        ...(baseManifest.tools ?? { adhoc: [], mcp_servers: [] }),
        built_in: Array.from(next).sort(),
      };
      const nextManifest = { ...baseManifest, tools: nextTools };
      const updated = await environmentApi.replaceManifest(activePresetId, nextManifest);
      setActivePresetDetail(updated);
    } catch (e) {
      // Revert
      const reverted = new Set(enabledNames);
      if (wasEnabled) reverted.add(toolName);
      else reverted.delete(toolName);
      setEnabledNames(reverted);
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSavingTool(null);
    }
  };

  const visible = useMemo(() => {
    if (activeGroup === ALL) return tools;
    return tools.filter((tt) => tt.feature_group === activeGroup);
  }, [tools, activeGroup]);

  // Sidebar entries with per-group counts
  const groupCounts = useMemo(() => {
    const counts: Record<string, number> = {};
    for (const tt of tools) {
      counts[tt.feature_group] = (counts[tt.feature_group] || 0) + 1;
    }
    return counts;
  }, [tools]);

  const sidebar = (
    <>
      <button
        type="button"
        onClick={() => setActiveGroup(ALL)}
        className={cn(
          'w-full text-left px-2 py-1.5 rounded text-[0.8125rem] hover:bg-[var(--bg-tertiary)]',
          activeGroup === ALL && 'bg-[var(--bg-tertiary)] font-semibold',
        )}
      >
        All <span className="text-[var(--text-muted)] text-[0.6875rem]">({tools.length})</span>
      </button>
      {groups.map((g) => (
        <button
          key={g}
          type="button"
          onClick={() => setActiveGroup(g)}
          className={cn(
            'w-full text-left px-2 py-1.5 rounded text-[0.8125rem] hover:bg-[var(--bg-tertiary)]',
            activeGroup === g && 'bg-[var(--bg-tertiary)] font-semibold',
          )}
        >
          {g}{' '}
          <span className="text-[var(--text-muted)] text-[0.6875rem]">
            ({groupCounts[g] ?? 0})
          </span>
        </button>
      ))}
    </>
  );

  return (
    <TabShell
      title="Framework tools"
      icon={Wrench}
      subtitle={
        <>
          Built-in tools shipped with geny-executor.
          {activeGroup !== ALL && <> · filter: {activeGroup}</>}
          {activePresetId && (
            <>
              {' · editing '}
              <span className="font-mono">{activePresetDetail?.name ?? activePresetId}</span>
              {' · '}
              {enabledNames.size} / {tools.length} enabled
              {presetLoading && ' · loading…'}
            </>
          )}
        </>
      }
      actions={
        <>
          <select
            value={activePresetId ?? ''}
            onChange={(e) => setActivePresetId(e.target.value || null)}
            disabled={loading || presetLoading}
            className="text-xs border rounded px-2 py-1 bg-[var(--bg-primary)] disabled:opacity-50"
            title="Edit which built-ins are enabled in a preset environment"
          >
            <option value="">— No preset —</option>
            {presets.map((p) => (
              <option key={p.id} value={p.id}>
                {p.name}
              </option>
            ))}
          </select>
          <ActionButton icon={RefreshCw} spinIcon={loading} onClick={refresh} disabled={loading}>
            Refresh
          </ActionButton>
        </>
      }
      error={error}
      onDismissError={() => setError(null)}
    >
      <div className="flex h-full min-h-0">
        <TwoPaneBody
          sidebar={sidebar}
          sidebarTitle="Groups"
          sidebarWidth="narrow"
          mainPadding="lg"
        >
          {visible.length === 0 ? (
            <EmptyState
              icon={Wrench}
              title={loading ? 'Loading…' : 'No tools.'}
            />
          ) : (
          <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-3">
            {visible.map((tt) => {
              const isEnabled = enabledNames.has(tt.name);
              const isSaving = savingTool === tt.name;
              return (
                <div
                  key={tt.name}
                  className={cn(
                    'relative border border-[var(--border-color)] rounded-md p-3 transition-all',
                    'hover:border-[var(--primary-color)] hover:shadow-sm',
                    selected?.name === tt.name &&
                      'border-[var(--primary-color)] shadow-sm',
                    activePresetId && isEnabled &&
                      'bg-[rgba(59,130,246,0.04)]',
                  )}
                >
                  {/* PR-E.1.4 — Per-tool toggle. Hidden when no preset. */}
                  {activePresetId && (
                    <button
                      type="button"
                      onClick={(e) => {
                        e.stopPropagation();
                        toggleTool(tt.name);
                      }}
                      disabled={presetLoading || isSaving || !activePresetDetail?.manifest}
                      title={isEnabled ? 'Disable in preset' : 'Enable in preset'}
                      className={cn(
                        'absolute top-2 right-2 w-5 h-5 rounded border flex items-center justify-center transition-all',
                        isEnabled
                          ? 'bg-[var(--primary-color)] border-[var(--primary-color)] text-white'
                          : 'bg-[var(--bg-primary)] border-[var(--border-color)] hover:border-[var(--primary-color)]',
                        (isSaving || presetLoading) && 'opacity-50',
                      )}
                    >
                      {isEnabled && <Check className="w-3 h-3" />}
                    </button>
                  )}
                  <button
                    type="button"
                    onClick={() => setSelected(tt)}
                    className="text-left w-full"
                  >
                    <div className="flex items-center justify-between pr-7">
                      <span className="font-mono font-semibold text-[0.875rem]">
                        {tt.name}
                      </span>
                      <span className="text-[0.625rem] text-[var(--text-muted)] uppercase">
                        {tt.feature_group}
                      </span>
                    </div>
                    <div className="text-[0.75rem] text-[var(--text-secondary)] mt-1 line-clamp-2">
                      {tt.description || '—'}
                    </div>
                    <div className="flex flex-wrap gap-1 mt-2">
                      {CAPABILITY_BADGES.map(([key, label, cls]) =>
                        tt.capabilities[key] ? (
                          <span
                            key={String(key)}
                            className={cn(
                              'inline-block text-[0.5625rem] px-1.5 py-0.5 rounded',
                              cls,
                            )}
                          >
                            {label}
                          </span>
                        ) : null,
                      )}
                    </div>
                  </button>
                </div>
              );
            })}
          </div>
        )}
        </TwoPaneBody>

        <DetailDrawer
          open={!!selected}
          onClose={() => setSelected(null)}
          title={<span className="font-mono">{selected?.name}</span>}
        >
          {selected && (
            <>
              <div className="text-[0.6875rem] text-[var(--text-muted)] uppercase tracking-wider mb-1">
                Group
              </div>
              <div className="text-[0.8125rem] mb-3">{selected.feature_group}</div>

              <div className="text-[0.6875rem] text-[var(--text-muted)] uppercase tracking-wider mb-1">
                Description
              </div>
              <div className="text-[0.8125rem] mb-3 whitespace-pre-wrap">
                {selected.description || '—'}
              </div>

              <div className="text-[0.6875rem] text-[var(--text-muted)] uppercase tracking-wider mb-1">
                Capabilities
              </div>
              <div className="flex flex-wrap gap-1 mb-3">
                {Object.entries(selected.capabilities).map(([k, v]) => (
                  <span
                    key={k}
                    className="text-[0.625rem] px-1.5 py-0.5 rounded bg-[var(--bg-tertiary)] font-mono"
                  >
                    {k}: {String(v)}
                  </span>
                ))}
                {Object.keys(selected.capabilities).length === 0 && (
                  <span className="text-[var(--text-muted)] text-[0.75rem]">—</span>
                )}
              </div>

              <div className="text-[0.6875rem] text-[var(--text-muted)] uppercase tracking-wider mb-1">
                Input schema
              </div>
              <pre className="text-[0.625rem] font-mono bg-[var(--bg-tertiary)] rounded p-2 overflow-x-auto">
                {JSON.stringify(selected.input_schema, null, 2)}
              </pre>
            </>
          )}
        </DetailDrawer>
      </div>
    </TabShell>
  );
}

export default ToolCatalogTab;
