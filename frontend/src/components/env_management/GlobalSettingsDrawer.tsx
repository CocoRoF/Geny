'use client';

/**
 * GlobalSettingsDrawer — right-side slide-in panel for env-wide
 * settings (model / pipeline / tools / externals).
 *
 * Replaces the old inline GlobalSection (cycle 20260427_2 PR-2). Sits
 * outside the canvas / stage editor so it doesn't compete for vertical
 * real estate. Toggled by the ⚙ button in CompactMetaBar.
 *
 * Closes on:
 *   - X button
 *   - Escape key
 *   - Click outside the drawer (overlay click)
 */

import { useEffect, useState } from 'react';
import {
  Cpu,
  ExternalLink,
  Layers,
  Plug,
  Shield,
  Sparkles,
  Wrench,
  X,
} from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import { useAppStore } from '@/store/useAppStore';
import { useEnvironmentDraftStore } from '@/store/useEnvironmentDraftStore';
import { ModelConfigEditor } from '@/components/builder/ModelConfigEditor';
import { PipelineConfigEditor } from '@/components/builder/PipelineConfigEditor';
import ToolCheckboxGrid from './ToolCheckboxGrid';

export interface GlobalSettingsDrawerProps {
  open: boolean;
  onClose: () => void;
}

type Panel = 'model' | 'pipeline' | 'tools' | 'externals';

export default function GlobalSettingsDrawer({
  open,
  onClose,
}: GlobalSettingsDrawerProps) {
  const { t } = useI18n();
  const draft = useEnvironmentDraftStore((s) => s.draft);
  const patchModel = useEnvironmentDraftStore((s) => s.patchModel);
  const patchPipeline = useEnvironmentDraftStore((s) => s.patchPipeline);
  const patchTools = useEnvironmentDraftStore((s) => s.patchTools);
  const setActiveTab = useAppStore((s) => s.setActiveTab);
  const setEnvSubTab = useAppStore((s) => s.setEnvSubTab);

  const [panel, setPanel] = useState<Panel>('model');

  // Esc to close
  useEffect(() => {
    if (!open) return;
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [open, onClose]);

  if (!open || !draft) return null;

  const goToLibrary = (sub: string) => {
    setActiveTab('library');
    setEnvSubTab(sub);
    onClose();
  };

  const builtInCount = (draft.tools?.built_in ?? []).length;
  const mcpCount = (draft.tools?.mcp_servers ?? []).length;
  const adhocCount = (draft.tools?.adhoc ?? []).length;

  return (
    <>
      {/* Overlay */}
      <div
        className="fixed inset-0 z-40 bg-black/30 backdrop-blur-[1px]"
        onClick={onClose}
        aria-hidden
      />
      {/* Drawer */}
      <aside
        className="fixed top-0 right-0 z-50 h-full w-full max-w-[640px] bg-[hsl(var(--background))] border-l border-[hsl(var(--border))] shadow-2xl flex flex-col"
        role="dialog"
        aria-label={t('envManagement.globalSectionTitle')}
      >
        {/* Header */}
        <header className="flex items-center justify-between gap-3 px-4 h-12 border-b border-[hsl(var(--border))] bg-[hsl(var(--card))] shrink-0">
          <div className="flex items-center gap-2 min-w-0">
            <Layers className="w-4 h-4 text-[hsl(var(--primary))] shrink-0" />
            <h3 className="text-[0.875rem] font-semibold truncate">
              {t('envManagement.globalSectionTitle')}
            </h3>
          </div>
          <button
            type="button"
            onClick={onClose}
            className="inline-flex items-center justify-center w-7 h-7 rounded-md text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))] hover:bg-[hsl(var(--accent))] transition-colors"
            aria-label="close"
          >
            <X className="w-4 h-4" />
          </button>
        </header>

        {/* Sub-tab strip + body */}
        <div className="flex flex-1 min-h-0">
          <nav className="flex flex-col gap-0.5 p-2 w-44 shrink-0 border-r border-[hsl(var(--border))] bg-[hsl(var(--card))] overflow-y-auto">
            <SubTabButton
              icon={Cpu}
              label={t('envManagement.global.model')}
              active={panel === 'model'}
              onClick={() => setPanel('model')}
            />
            <SubTabButton
              icon={Layers}
              label={t('envManagement.global.pipeline')}
              active={panel === 'pipeline'}
              onClick={() => setPanel('pipeline')}
            />
            <SubTabButton
              icon={Wrench}
              label={t('envManagement.global.tools')}
              active={panel === 'tools'}
              onClick={() => setPanel('tools')}
              badge={`${builtInCount + mcpCount + adhocCount}`}
            />
            <SubTabButton
              icon={ExternalLink}
              label={t('envManagement.global.externals')}
              active={panel === 'externals'}
              onClick={() => setPanel('externals')}
            />
          </nav>

          <div className="flex-1 min-w-0 p-4 overflow-y-auto">
            {panel === 'model' && (
              <ModelConfigEditor
                initial={draft.model ?? {}}
                saving={false}
                error={null}
                onSave={(changes) => patchModel(changes)}
                onClearError={() => {}}
              />
            )}
            {panel === 'pipeline' && (
              <PipelineConfigEditor
                initial={draft.pipeline ?? {}}
                saving={false}
                error={null}
                onSave={(changes) => patchPipeline(changes)}
                onClearError={() => {}}
              />
            )}
            {panel === 'tools' && (
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
            {panel === 'externals' && (
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
      </aside>
    </>
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
    <div className="flex flex-col gap-0.5 p-3 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--card))]">
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
      className="flex items-start gap-3 p-3 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--card))] hover:bg-[hsl(var(--accent))] transition-colors text-left group"
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
