'use client';

/**
 * Stage10ToolsEditor — curated editor for s10_tools (the tool
 * execution stage).
 *
 * The user wants a single screen that answers: "어떤 도구를 사용 가능
 * 하게 할까?" Instead of two slightly-different layers (manifest tools
 * registry + per-stage tool_binding) we surface them as:
 *
 *   1. "도구 사용 가능 목록" — checkbox grid for manifest.tools.built_in
 *      (the global registry every stage inherits from).
 *   2. "MCP 서버" — checkbox toggles for each entry in
 *      manifest.tools.mcp_servers (currently registered MCP servers;
 *      add/edit happens in the existing MCP Servers tab).
 *   3. "이 단계만 따로 제한" — collapsed disclosure for
 *      stage.tool_binding (allowed/blocked sets). Most users never
 *      open this; it's a power-user filter.
 *
 * Active toggle stays in its own card.
 */

import { useState } from 'react';
import {
  ChevronDown,
  ChevronRight,
  ExternalLink,
  Server,
  Wrench,
  Filter,
} from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import { useAppStore } from '@/store/useAppStore';
import { useEnvironmentDraftStore } from '@/store/useEnvironmentDraftStore';
import type {
  StageManifestEntry,
  StageToolBinding,
} from '@/types/environment';
import { Switch } from '@/components/ui/switch';
import ToolCheckboxGrid from '../ToolCheckboxGrid';
import StageGenericEditor from '../StageGenericEditor';

interface Props {
  order: number;
  entry: StageManifestEntry;
}

export default function Stage10ToolsEditor({ order, entry }: Props) {
  const { t } = useI18n();
  const draft = useEnvironmentDraftStore((s) => s.draft);
  const patchStage = useEnvironmentDraftStore((s) => s.patchStage);
  const patchTools = useEnvironmentDraftStore((s) => s.patchTools);
  const setActiveTab = useAppStore((s) => s.setActiveTab);
  const setEnvSubTab = useAppStore((s) => s.setEnvSubTab);

  const [bindingOpen, setBindingOpen] = useState(false);
  const [advancedOpen, setAdvancedOpen] = useState(false);

  const builtInList = (draft?.tools?.built_in ?? []) as string[];
  const mcpServers = (draft?.tools?.mcp_servers ?? []) as Array<
    Record<string, unknown>
  >;

  const binding = (entry.tool_binding ?? {}) as StageToolBinding;
  const filterMode: 'inherit' | 'allowlist' | 'blocklist' = (() => {
    if (binding.allowed && binding.allowed.length > 0) return 'allowlist';
    if (binding.blocked && binding.blocked.length > 0) return 'blocklist';
    return 'inherit';
  })();

  const setFilterMode = (next: 'inherit' | 'allowlist' | 'blocklist') => {
    if (next === 'inherit') {
      patchStage(order, { tool_binding: null });
      return;
    }
    const seed: StageToolBinding =
      next === 'allowlist'
        ? { stage_order: order, allowed: [], blocked: null }
        : { stage_order: order, allowed: null, blocked: [] };
    patchStage(order, { tool_binding: seed });
  };

  const setAllowed = (names: string[]) => {
    patchStage(order, {
      tool_binding: {
        ...binding,
        stage_order: binding.stage_order ?? order,
        allowed: names,
        blocked: null,
      },
    });
  };
  const setBlocked = (names: string[]) => {
    patchStage(order, {
      tool_binding: {
        ...binding,
        stage_order: binding.stage_order ?? order,
        blocked: names,
        allowed: null,
      },
    });
  };

  // Mcp helpers
  const mcpIncluded = (name: string) => {
    // We treat mcp_servers as "if the server is in the snapshot, the
    // stage uses it". There's no per-server include flag in the
    // manifest yet; surfacing the list here is a step toward that.
    return mcpServers.some((s) => s.name === name);
  };
  // Toggling MCP servers is currently a global-snapshot concern (add /
  // remove via the MCP Servers tab). We surface them here read-only
  // with a cross-link.

  return (
    <div className="flex flex-col gap-4">
      {/* ── Active ── */}
      <section className="flex items-center justify-between gap-3 p-3 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--card))]">
        <div>
          <div className="text-[0.8125rem] font-semibold text-[hsl(var(--foreground))]">
            {t('libraryNewTab.stage10.activeTitle')}
          </div>
          <div className="text-[0.6875rem] text-[hsl(var(--muted-foreground))]">
            {t('libraryNewTab.stage10.activeDesc')}
          </div>
        </div>
        <Switch
          checked={!!entry.active}
          onCheckedChange={(checked) => patchStage(order, { active: checked })}
        />
      </section>

      {/* ── Tools registry (manifest.tools.built_in) ── */}
      <section className="flex flex-col gap-2 p-3 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--card))]">
        <header className="flex items-center gap-2">
          <Wrench className="w-4 h-4 text-[hsl(var(--primary))]" />
          <h4 className="text-[0.8125rem] font-semibold text-[hsl(var(--foreground))]">
            {t('libraryNewTab.stage10.builtInTitle')}
          </h4>
        </header>
        <ToolCheckboxGrid
          value={builtInList}
          onChange={(names) => patchTools({ built_in: names })}
          mode="allowlist"
          hint={t('libraryNewTab.stage10.builtInHint')}
        />
      </section>

      {/* ── MCP servers ── */}
      <section className="flex flex-col gap-2 p-3 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--card))]">
        <header className="flex items-center justify-between gap-2">
          <div className="flex items-center gap-2">
            <Server className="w-4 h-4 text-[hsl(var(--primary))]" />
            <h4 className="text-[0.8125rem] font-semibold text-[hsl(var(--foreground))]">
              {t('libraryNewTab.stage10.mcpTitle')}
            </h4>
            <span className="text-[0.6875rem] text-[hsl(var(--muted-foreground))] tabular-nums">
              ({mcpServers.length})
            </span>
          </div>
          <button
            type="button"
            onClick={() => {
              setActiveTab('library');
              setEnvSubTab('mcpServers');
            }}
            className="inline-flex items-center gap-1 text-[0.7rem] text-[hsl(var(--primary))] hover:underline"
          >
            {t('libraryNewTab.stage10.mcpManage')}
            <ExternalLink className="w-3 h-3" />
          </button>
        </header>
        {mcpServers.length === 0 ? (
          <p className="text-[0.75rem] text-[hsl(var(--muted-foreground))] italic py-2">
            {t('libraryNewTab.stage10.mcpEmpty')}
          </p>
        ) : (
          <ul className="flex flex-col gap-0.5 max-h-[160px] overflow-y-auto">
            {mcpServers.map((server, i) => {
              const name = (server.name as string) ?? `server_${i}`;
              const transport = (server.transport as string) ?? 'stdio';
              return (
                <li
                  key={`${name}_${i}`}
                  className="flex items-center gap-2 py-1 px-1.5 rounded text-[0.75rem]"
                >
                  <input
                    type="checkbox"
                    checked={mcpIncluded(name)}
                    readOnly
                    disabled
                    className="w-3 h-3 accent-[hsl(var(--primary))] opacity-60"
                  />
                  <code className="text-[hsl(var(--foreground))] font-mono text-[0.7rem] flex-1">
                    {name}
                  </code>
                  <span className="text-[0.625rem] uppercase tracking-wider text-[hsl(var(--muted-foreground))]">
                    {transport}
                  </span>
                </li>
              );
            })}
          </ul>
        )}
        <p className="text-[0.6875rem] text-[hsl(var(--muted-foreground))] italic">
          {t('libraryNewTab.stage10.mcpHint')}
        </p>
      </section>

      {/* ── Stage-specific binding (allowed / blocked) ── */}
      <section className="rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--card))]">
        <button
          type="button"
          onClick={() => setBindingOpen((v) => !v)}
          className="w-full flex items-center gap-2 px-3 py-2 text-[0.8125rem] font-semibold text-[hsl(var(--foreground))] hover:bg-[hsl(var(--accent))] transition-colors text-left"
        >
          {bindingOpen ? (
            <ChevronDown className="w-3.5 h-3.5" />
          ) : (
            <ChevronRight className="w-3.5 h-3.5" />
          )}
          <Filter className="w-3.5 h-3.5 text-[hsl(var(--primary))]" />
          {t('libraryNewTab.stage10.bindingTitle')}
          <span className="text-[0.6875rem] font-normal text-[hsl(var(--muted-foreground))]">
            {t(`libraryNewTab.stage10.bindingMode.${filterMode}`)}
          </span>
        </button>
        {bindingOpen && (
          <div className="px-3 pb-3 border-t border-[hsl(var(--border))] pt-3 flex flex-col gap-3">
            <p className="text-[0.7rem] text-[hsl(var(--muted-foreground))] leading-relaxed">
              {t('libraryNewTab.stage10.bindingHint')}
            </p>
            <div className="flex items-center gap-2 flex-wrap">
              {(['inherit', 'allowlist', 'blocklist'] as const).map((m) => (
                <button
                  key={m}
                  type="button"
                  onClick={() => setFilterMode(m)}
                  className={`px-2.5 py-1 rounded-full border text-[0.7rem] font-medium transition-colors ${
                    filterMode === m
                      ? 'border-[hsl(var(--primary))] bg-[hsl(var(--primary)/0.12)] text-[hsl(var(--primary))]'
                      : 'border-[hsl(var(--border))] text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))]'
                  }`}
                >
                  {t(`libraryNewTab.stage10.bindingMode.${m}`)}
                </button>
              ))}
            </div>

            {filterMode === 'allowlist' && (
              <ToolCheckboxGrid
                value={binding.allowed ?? []}
                onChange={setAllowed}
                mode="allowlist"
                hint={t('libraryNewTab.stage10.allowedHint')}
                hideBulkControls
              />
            )}
            {filterMode === 'blocklist' && (
              <ToolCheckboxGrid
                value={binding.blocked ?? []}
                onChange={setBlocked}
                mode="blocklist"
                hint={t('libraryNewTab.stage10.blockedHint')}
                hideBulkControls
              />
            )}
            {filterMode === 'inherit' && (
              <p className="text-[0.7rem] text-[hsl(var(--muted-foreground))] italic">
                {t('libraryNewTab.stage10.inheritHint')}
              </p>
            )}
          </div>
        )}
      </section>

      {/* ── Advanced ── */}
      <section className="rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--card))]">
        <button
          type="button"
          onClick={() => setAdvancedOpen((v) => !v)}
          className="w-full flex items-center gap-2 px-3 py-2 text-[0.8125rem] font-semibold text-[hsl(var(--foreground))] hover:bg-[hsl(var(--accent))] transition-colors text-left"
        >
          {advancedOpen ? (
            <ChevronDown className="w-3.5 h-3.5" />
          ) : (
            <ChevronRight className="w-3.5 h-3.5" />
          )}
          {t('libraryNewTab.stage10.advancedTitle')}
          <span className="text-[0.6875rem] font-normal text-[hsl(var(--muted-foreground))]">
            {t('libraryNewTab.stage10.advancedHint')}
          </span>
        </button>
        {advancedOpen && (
          <div className="px-3 pb-3 border-t border-[hsl(var(--border))] pt-3">
            <StageGenericEditor order={order} entry={entry} />
          </div>
        )}
      </section>
    </div>
  );
}
