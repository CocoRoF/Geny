'use client';

/**
 * GlobalSection — collapsible "전역 설정" panel above the canvas.
 *
 * Hosts editors for things that aren't tied to a single stage:
 *   - top-level model config (defaults all stages without model_override)
 *   - pipeline-level config (max_iterations, budgets, streaming, ...)
 *   - tool snapshot summary + cross-link to ToolSetsTab (PR-C inlines a
 *     full editor here)
 *   - read-only links to global tabs that own scope outside the manifest:
 *     hooks (.geny/hooks.yaml), permissions (settings.json),
 *     skills (Geny global). These intentionally stay global until v4.0.
 *
 * Reuses ModelConfigEditor / PipelineConfigEditor verbatim — both are
 * shaped as snapshot → buildChanges → onSave(changes) and we route Save
 * straight into the draft store's patchModel/patchPipeline.
 */

import { useState } from 'react';
import {
  ChevronDown,
  ChevronRight,
  Cpu,
  ExternalLink,
  Layers,
  Plug,
  Shield,
  Sparkles,
  Wrench,
} from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import { useAppStore } from '@/store/useAppStore';
import { useEnvironmentDraftStore } from '@/store/useEnvironmentDraftStore';
import { ModelConfigEditor } from '@/components/builder/ModelConfigEditor';
import { PipelineConfigEditor } from '@/components/builder/PipelineConfigEditor';
import ToolCheckboxGrid from './ToolCheckboxGrid';

export default function GlobalSection() {
  const { t } = useI18n();
  const draft = useEnvironmentDraftStore((s) => s.draft);
  const patchModel = useEnvironmentDraftStore((s) => s.patchModel);
  const patchPipeline = useEnvironmentDraftStore((s) => s.patchPipeline);
  const patchTools = useEnvironmentDraftStore((s) => s.patchTools);
  const setActiveTab = useAppStore((s) => s.setActiveTab);
  const setEnvSubTab = useAppStore((s) => s.setEnvSubTab);

  const [open, setOpen] = useState(true);
  const [activePanel, setActivePanel] = useState<'model' | 'pipeline' | 'tools' | 'externals'>(
    'model',
  );

  if (!draft) return null;

  const goToLibrary = (sub: string) => {
    setActiveTab('library');
    setEnvSubTab(sub);
  };

  const builtInCount = (draft.tools?.built_in ?? []).length;
  const mcpCount = (draft.tools?.mcp_servers ?? []).length;
  const adhocCount = (draft.tools?.adhoc ?? []).length;

  return (
    <section className="border-b border-[hsl(var(--border))] bg-[hsl(var(--card))]">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        className="w-full flex items-center gap-2 px-5 py-2 text-[0.8125rem] font-semibold text-[hsl(var(--foreground))] hover:bg-[hsl(var(--accent))] transition-colors text-left"
      >
        {open ? (
          <ChevronDown className="w-3.5 h-3.5" />
        ) : (
          <ChevronRight className="w-3.5 h-3.5" />
        )}
        <Layers className="w-3.5 h-3.5 text-[hsl(var(--primary))]" />
        {t('envManagement.globalSectionTitle')}
        <span className="text-[0.6875rem] font-normal text-[hsl(var(--muted-foreground))]">
          {t('envManagement.globalSectionHint')}
        </span>
      </button>

      {open && (
        <div className="flex flex-col md:flex-row gap-0 border-t border-[hsl(var(--border))]">
          {/* ── Sub-tab strip ── */}
          <nav className="flex md:flex-col gap-0.5 p-2 md:w-48 shrink-0 md:border-r md:border-[hsl(var(--border))] bg-[hsl(var(--background))]">
            <SubTabButton
              icon={Cpu}
              label={t('envManagement.global.model')}
              active={activePanel === 'model'}
              onClick={() => setActivePanel('model')}
            />
            <SubTabButton
              icon={Layers}
              label={t('envManagement.global.pipeline')}
              active={activePanel === 'pipeline'}
              onClick={() => setActivePanel('pipeline')}
            />
            <SubTabButton
              icon={Wrench}
              label={t('envManagement.global.tools')}
              active={activePanel === 'tools'}
              onClick={() => setActivePanel('tools')}
              badge={`${builtInCount + mcpCount + adhocCount}`}
            />
            <SubTabButton
              icon={ExternalLink}
              label={t('envManagement.global.externals')}
              active={activePanel === 'externals'}
              onClick={() => setActivePanel('externals')}
            />
          </nav>

          {/* ── Panel body ── */}
          <div className="flex-1 min-w-0 p-4 max-h-[420px] overflow-y-auto">
            {activePanel === 'model' && (
              <ModelConfigEditor
                initial={draft.model ?? {}}
                saving={false}
                error={null}
                onSave={(changes) => patchModel(changes)}
                onClearError={() => {}}
              />
            )}

            {activePanel === 'pipeline' && (
              <PipelineConfigEditor
                initial={draft.pipeline ?? {}}
                saving={false}
                error={null}
                onSave={(changes) => patchPipeline(changes)}
                onClearError={() => {}}
              />
            )}

            {activePanel === 'tools' && (
              <div className="flex flex-col gap-3">
                <p className="text-[0.8125rem] text-[hsl(var(--muted-foreground))]">
                  {t('envManagement.global.toolsHint')}
                </p>
                <div className="grid grid-cols-3 gap-2">
                  <ToolStatCard
                    label={t('envManagement.global.builtInTools')}
                    count={builtInCount}
                  />
                  <ToolStatCard
                    label={t('envManagement.global.mcpServers')}
                    count={mcpCount}
                  />
                  <ToolStatCard
                    label={t('envManagement.global.customTools')}
                    count={adhocCount}
                  />
                </div>
                <ToolCheckboxGrid
                  value={(draft.tools?.built_in ?? []) as string[]}
                  onChange={(names) => patchTools({ built_in: names })}
                  mode="allowlist"
                  hint={t('envManagement.global.toolsPickerHint')}
                />
              </div>
            )}

            {activePanel === 'externals' && (
              <div className="flex flex-col gap-3">
                <p className="text-[0.8125rem] text-[hsl(var(--muted-foreground))]">
                  {t('envManagement.global.externalsHint')}
                </p>
                <div className="flex flex-col gap-2">
                  <ExternalLinkRow
                    icon={Plug}
                    label={t('tabs.hooks') ?? 'Hooks'}
                    description={t('envManagement.global.hooksDesc')}
                    onClick={() => goToLibrary('hooks')}
                  />
                  <ExternalLinkRow
                    icon={Shield}
                    label={t('tabs.permissions') ?? 'Permissions'}
                    description={t('envManagement.global.permissionsDesc')}
                    onClick={() => goToLibrary('permissions')}
                  />
                  <ExternalLinkRow
                    icon={Sparkles}
                    label={t('tabs.skills') ?? 'Skills'}
                    description={t('envManagement.global.skillsDesc')}
                    onClick={() => goToLibrary('skills')}
                  />
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </section>
  );
}

// ── Helpers ──

function SubTabButton({
  icon: Icon,
  label,
  active,
  onClick,
  badge,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  active: boolean;
  onClick: () => void;
  badge?: string;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className={`flex items-center gap-2 px-2.5 py-1.5 rounded-md text-[0.8125rem] text-left transition-colors ${
        active
          ? 'bg-[hsl(var(--accent))] text-[hsl(var(--foreground))] font-semibold'
          : 'text-[hsl(var(--muted-foreground))] hover:bg-[hsl(var(--accent))]/60 hover:text-[hsl(var(--foreground))]'
      }`}
    >
      <Icon className="w-3.5 h-3.5" />
      <span className="flex-1 truncate">{label}</span>
      {badge !== undefined && (
        <span className="text-[0.6875rem] tabular-nums text-[hsl(var(--muted-foreground))]">
          {badge}
        </span>
      )}
    </button>
  );
}

function ToolStatCard({ label, count }: { label: string; count: number }) {
  return (
    <div className="flex flex-col gap-0.5 p-3 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))]">
      <span className="text-[0.6875rem] uppercase tracking-wider text-[hsl(var(--muted-foreground))]">
        {label}
      </span>
      <span className="text-lg font-semibold tabular-nums text-[hsl(var(--foreground))]">
        {count}
      </span>
    </div>
  );
}

function ExternalLinkRow({
  icon: Icon,
  label,
  description,
  onClick,
}: {
  icon: React.ComponentType<{ className?: string }>;
  label: string;
  description: string;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      className="flex items-start gap-3 p-3 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] hover:bg-[hsl(var(--accent))] transition-colors text-left group"
    >
      <Icon className="w-4 h-4 text-[hsl(var(--primary))] mt-0.5 shrink-0" />
      <div className="flex-1 min-w-0">
        <div className="text-[0.8125rem] font-medium text-[hsl(var(--foreground))]">
          {label}
        </div>
        <div className="text-[0.7rem] text-[hsl(var(--muted-foreground))] mt-0.5">
          {description}
        </div>
      </div>
      <ExternalLink className="w-3.5 h-3.5 text-[hsl(var(--muted-foreground))] group-hover:text-[hsl(var(--primary))] mt-0.5 shrink-0" />
    </button>
  );
}
