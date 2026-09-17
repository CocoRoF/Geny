'use client';

/**
 * GlobalSettingsView — body view for "stage 0" (env-wide globals).
 *
 * Cycle 20260525_1 trim: tool selection (executor / geny / custom /
 * MCP) is owned by Stage 10 now. Stage 0 retains only the *truly
 * global* manifest concerns:
 *
 *     1. 기본 모델 설정       → ModelConfigEditor   (manifest.model)
 *     2. 스테이지 기본 설정   → PipelineConfigEditor (manifest.pipeline)
 *     3. 훅                   → HookEnvPicker        (manifest.host_selections.hooks)
 *     4. 권한                 → PermissionEnvPicker  (manifest.host_selections.permissions)
 *     5. 스킬                 → SkillEnvPicker       (manifest.host_selections.skills)
 *
 * The host-shared sections (hooks / skills / permissions) stay here
 * because they are not "tools" — they are pre/post hooks, prompt
 * bundles, and runtime gates that belong to the env, not to a stage.
 *
 * The new-draft seeder (`seedDefaultToolLists` in the draft store)
 * pre-populates `host_selections.{hooks,skills,permissions}` from
 * `/api/env-defaults` (Phase 1), so a fresh env opens with whatever
 * the operator has marked ★ on the host registry tabs.
 */

import { useState } from 'react';
import Link from 'next/link';
import {
  Cpu,
  ExternalLink,
  Layers,
  Settings2,
  Shield,
  Sparkles,
  Zap,
  Bot,
  Workflow,
  SlidersHorizontal,
  Boxes,
  MonitorCog,
} from 'lucide-react';
import { Switch } from '@/components/ui/switch';
import { useI18n } from '@/lib/i18n';
import { useTheme } from '@/lib/theme';
import { useEnvironmentDraftStore } from '@/store/useEnvironmentDraftStore';
import { ModelConfigEditor } from '@/components/builder/ModelConfigEditor';
import { PipelineConfigEditor } from '@/components/builder/PipelineConfigEditor';
import {
  MODEL_CATALOG,
  PROVIDER_DEFAULT_MODEL,
  PROVIDERS,
  inferProvider,
  type ProviderId,
} from '@/lib/modelCatalog';
import SectionHelpButton from './section_help/SectionHelpButton';
import RouteNotice from './RouteNotice';
import {
  PermissionEnvPicker,
  SkillEnvPicker,
  TriggerEnvPicker,
  OwnedSubagentPicker,
  SubworkerTypesPicker,
  SandboxToolPacksPicker,
  PersonaPresetPicker,
} from './HostSelectionPickers';
import ToolSettingsPicker from './ToolSettingsPicker';

const S06_API_ORDER = 6;

// Cycle 20260525_1 — tool selection (executor / geny / custom / MCP) was
// moved out of Stage 0 entirely into Stage 10 ("도구"). Stage 10 is the
// single source for "which tools does this env expose"; Stage 0 keeps
// only the truly *global* manifest concerns (default model, pipeline,
// host-selection of hooks/permissions/skills).
type Panel =
  | 'model'
  | 'pipeline'
  | 'permissions'
  | 'skills'
  | 'triggers'
  | 'subagent'
  | 'subworker'
  | 'tool_settings'
  | 'sandbox_tool_packs'
  | 'persona'
  | 'computer_use';

const PANEL_HELP_ID: Record<Panel, string> = {
  model: 'globals.model',
  pipeline: 'globals.pipeline',
  permissions: 'globals.permissions',
  skills: 'globals.skills',
  triggers: 'globals.triggers',
  subagent: 'globals.subagent',
  subworker: 'globals.subworker',
  tool_settings: 'globals.toolSettings',
  sandbox_tool_packs: 'globals.sandboxToolPacks',
  persona: 'globals.persona',
  computer_use: 'globals.computerUse',
};

const HEADER_PALETTE = {
  light: {
    bg: 'rgb(237 233 254)',
    fg: 'rgb(91 33 182)',
    border: 'rgb(139 92 246)',
  },
  dark: {
    bg: 'rgb(76 29 149 / 0.45)',
    fg: 'rgb(196 181 253)',
    border: 'rgb(167 139 250)',
  },
} as const;

export default function GlobalSettingsView() {
  const { t } = useI18n();
  const { theme } = useTheme();
  const palette = HEADER_PALETTE[theme === 'dark' ? 'dark' : 'light'];
  const draft = useEnvironmentDraftStore((s) => s.draft);
  const patchModel = useEnvironmentDraftStore((s) => s.patchModel);
  const patchPipeline = useEnvironmentDraftStore((s) => s.patchPipeline);
  const patchStage = useEnvironmentDraftStore((s) => s.patchStage);
  const setComputerUseEnabled = useEnvironmentDraftStore(
    (s) => s.setComputerUseEnabled,
  );

  const [panel, setPanel] = useState<Panel>('model');

  if (!draft) return null;

  // ── Sidebar badges ──
  // Wildcard `["*"]` reads as a single-element list to `.length`,
  // which would print "1" next to a panel — misleading when the
  // manifest actually means "every entry". Render ★ in that mode
  // and reserve the count for explicit lists.
  const selectionBadge = (sel: string[] | undefined): string => {
    if (!sel) return '0';
    if (sel.includes('*')) return '★';
    return `${sel.length}`;
  };
  // Pre-1.3.3 manifests have no host_selections object; treat that
  // as wildcard so the badge doesn't read "0" for a section that
  // historically applied in full.
  const skillSelection = draft.host_selections?.skills ?? ['*'];
  const permSelection = draft.host_selections?.permissions ?? ['*'];
  // Trigger mapping is a single optional id (not a list) — show ★ when
  // the env maps a preset, otherwise leave the badge off so the nav row
  // reads as "using the default" by absence.
  const triggerMapped =
    typeof draft.host_selections?.extras?.trigger_preset_id === 'string' &&
    draft.host_selections.extras.trigger_preset_id.length > 0;

  // ★ on the Sub-Agent nav row when the env declares an owned sub-agent.
  const ownedSubagentEnabled = !!draft.host_selections?.extras?.owned_subagent;
  const subworkerCustomized =
    Array.isArray(draft.host_selections?.extras?.subworker_types) &&
    (draft.host_selections?.extras?.subworker_types as unknown[]).length > 0;

  // ★ on the Tool Settings nav row when any per-env tool has stored values.
  const toolSettingsConfigured =
    Object.keys(
      (draft.host_selections?.extras?.tool_settings as
        | Record<string, unknown>
        | undefined) ?? {},
    ).length > 0;

  // ★ on the Tool Packs nav row when this env opted into any pack.
  const sandboxPacksSelected =
    Array.isArray(draft.host_selections?.extras?.sandbox_tool_packs) &&
    (draft.host_selections?.extras?.sandbox_tool_packs as unknown[]).length > 0;

  // ★ on the Persona nav row when this env has a persona preset attached.
  const personaSelected =
    typeof draft.host_selections?.extras?.persona_preset_id === 'string' &&
    draft.host_selections.extras.persona_preset_id.length > 0;

  // ★ on the Local Control nav row when this env opted into Computer Use.
  const computerUseEnabled =
    !!draft.host_selections?.extras?.computer_use_enabled;

  return (
    <div className="flex-1 min-h-0 overflow-y-auto bg-[hsl(var(--background))]">
      <div className="max-w-[1300px] mx-auto p-6 flex flex-col gap-6">
        {/* ── Header ── */}
        <header className="flex items-center gap-3">
          <span
            className="inline-flex items-center justify-center w-12 h-12 rounded-full text-[1rem] font-bold tabular-nums shrink-0"
            style={{
              background: palette.bg,
              color: palette.fg,
              border: `2px solid ${palette.border}`,
              boxShadow: '0 1px 4px -1px rgb(139 92 246 / 0.18)',
            }}
          >
            <Settings2 className="w-5 h-5" />
          </span>
          <div className="flex-1 min-w-0">
            <div className="flex items-center gap-2 flex-wrap">
              <h2 className="text-[1.125rem] font-semibold text-[hsl(var(--foreground))]">
                {t('envManagement.globalSectionTitle')}
              </h2>
              <span
                className="text-[0.625rem] uppercase tracking-wider px-1.5 py-0.5 rounded font-medium"
                style={{ background: palette.bg, color: palette.fg }}
              >
                {t('envManagement.compactBar.globalsLabel')}
              </span>
            </div>
            <p className="text-[0.8125rem] text-[hsl(var(--muted-foreground))] mt-1 leading-relaxed">
              {t('envManagement.globalSectionHint')}
            </p>
          </div>
        </header>

        {/* ── Sub-tab strip + body ── */}
        <div className="flex gap-4 min-h-0">
          <nav className="flex flex-col gap-0.5 w-52 shrink-0">
            <NavGroupLabel label={t('envManagement.globals.navGroupEnv')} />
            <SubTabButton
              icon={Cpu}
              label={t('envManagement.globals.navModel')}
              active={panel === 'model'}
              onClick={() => setPanel('model')}
            />
            <SubTabButton
              icon={Layers}
              label={t('envManagement.globals.navPipeline')}
              active={panel === 'pipeline'}
              onClick={() => setPanel('pipeline')}
            />
            <SubTabButton
              icon={Shield}
              label={t('envManagement.globals.navPermissions')}
              active={panel === 'permissions'}
              onClick={() => setPanel('permissions')}
              badge={selectionBadge(permSelection)}
            />
            <SubTabButton
              icon={Sparkles}
              label={t('envManagement.globals.navSkills')}
              active={panel === 'skills'}
              onClick={() => setPanel('skills')}
              badge={selectionBadge(skillSelection)}
            />
            <SubTabButton
              icon={Zap}
              label={t('envManagement.globals.navTriggers')}
              active={panel === 'triggers'}
              onClick={() => setPanel('triggers')}
              badge={triggerMapped ? '★' : undefined}
            />
            <SubTabButton
              icon={Bot}
              label={t('envManagement.globals.navSubagent')}
              active={panel === 'subagent'}
              onClick={() => setPanel('subagent')}
              badge={ownedSubagentEnabled ? '★' : undefined}
            />
            <SubTabButton
              icon={Workflow}
              label={t('envManagement.globals.navSubworker')}
              active={panel === 'subworker'}
              onClick={() => setPanel('subworker')}
              badge={subworkerCustomized ? '★' : undefined}
            />
            <SubTabButton
              icon={SlidersHorizontal}
              label={t('envManagement.globals.navToolSettings')}
              active={panel === 'tool_settings'}
              onClick={() => setPanel('tool_settings')}
              badge={toolSettingsConfigured ? '★' : undefined}
            />
            <SubTabButton
              icon={Boxes}
              label="Tool Packs"
              active={panel === 'sandbox_tool_packs'}
              onClick={() => setPanel('sandbox_tool_packs')}
              badge={sandboxPacksSelected ? '★' : undefined}
            />
            <SubTabButton
              icon={Sparkles}
              label={t('envManagement.globals.navPersona')}
              active={panel === 'persona'}
              onClick={() => setPanel('persona')}
              badge={personaSelected ? '★' : undefined}
            />
            <SubTabButton
              icon={MonitorCog}
              label="로컬 제어"
              active={panel === 'computer_use'}
              onClick={() => setPanel('computer_use')}
              badge={computerUseEnabled ? '★' : undefined}
            />
          </nav>

          <div className="relative flex-1 min-w-0 p-4 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--card))]">
            <div className="absolute right-3 top-3 z-10">
              <SectionHelpButton helpId={PANEL_HELP_ID[panel]} />
            </div>
            {/* The provider and model pickers that lived here are gone. Stage 6
                 runs the router, which replaces the model on every call with
                 the one the session's account route names — anything set here
                 would look saved and be overwritten immediately. */}
            {panel === 'model' && <RouteNotice />}

            {panel === 'pipeline' && (
              <PipelineConfigEditor
                initial={draft.pipeline ?? {}}
                saving={false}
                error={null}
                onSave={(changes) => patchPipeline(changes)}
                onClearError={() => {}}
              />
            )}


            {panel === 'permissions' && (
              <div className="flex flex-col gap-4">
                <PanelHeader
                  title={t('envManagement.globals.permissions.title')}
                  description={t(
                    'envManagement.globals.permissions.description',
                  )}
                />
                <PermissionEnvPicker />
                <RegistryEditorLink tab="permissions" />
              </div>
            )}

            {panel === 'skills' && (
              <div className="flex flex-col gap-4">
                <PanelHeader
                  title={t('envManagement.globals.skills.title')}
                  description={t('envManagement.globals.skills.description')}
                />
                <SkillEnvPicker />
                <RegistryEditorLink tab="skills" />
              </div>
            )}

            {panel === 'triggers' && (
              <div className="flex flex-col gap-4">
                <PanelHeader
                  title={t('envManagement.globals.triggers.title')}
                  description={t('envManagement.globals.triggers.description')}
                />
                <TriggerEnvPicker />
              </div>
            )}

            {panel === 'subagent' && (
              <div className="flex flex-col gap-4">
                <PanelHeader
                  title={t('envManagement.globals.subagent.title')}
                  description={t('envManagement.globals.subagent.description')}
                />
                <OwnedSubagentPicker />
              </div>
            )}

            {panel === 'subworker' && (
              <div className="flex flex-col gap-4">
                <PanelHeader
                  title={t('envManagement.globals.subworker.title')}
                  description={t('envManagement.globals.subworker.description')}
                />
                <SubworkerTypesPicker />
              </div>
            )}

            {panel === 'tool_settings' && (
              <div className="flex flex-col gap-4">
                <PanelHeader
                  title={t('envManagement.globals.toolSettings.title')}
                  description={t(
                    'envManagement.globals.toolSettings.description',
                  )}
                />
                <ToolSettingsPicker />
              </div>
            )}

            {panel === 'sandbox_tool_packs' && (
              <div className="flex flex-col gap-4">
                <PanelHeader
                  title="Sandbox Tool Packs"
                  description="Opt this environment into reusable Sandbox Tool Packs — each loads its tools + skills into every session, running in the pack's own snapshotted workspace."
                />
                <SandboxToolPacksPicker />
              </div>
            )}

            {panel === 'persona' && (
              <div className="flex flex-col gap-4">
                <PanelHeader
                  title={t('envManagement.globals.persona.title')}
                  description={t('envManagement.globals.persona.description')}
                />
                <PersonaPresetPicker />
              </div>
            )}

            {panel === 'computer_use' && (
              <div className="flex flex-col gap-4">
                <PanelHeader
                  title="로컬 컴퓨터 제어 (Computer Use)"
                  description="이 환경의 에이전트가 사용자의 데스크톱 접속기를 통해 로컬 컴퓨터를 보고 조작할 수 있게 합니다(화면 보기·타이핑·클릭·앱 열기 등). 켜면 접속기 capability 도구가 세션에 노출됩니다."
                />
                <label className="flex items-start gap-3 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--card))] p-4">
                  <Switch
                    checked={computerUseEnabled}
                    onCheckedChange={(v) => setComputerUseEnabled(!!v)}
                  />
                  <div className="min-w-0">
                    <div className="text-sm font-medium">
                      로컬 컴퓨터 제어 허용
                    </div>
                    <p className="mt-1 text-xs text-muted-foreground">
                      이것은 <b>서버측 정책 게이트</b>입니다. 실제 실행과 능력별
                      동의(항상 확인 등)는 사용자의 데스크톱 접속기에서 별도로
                      켜고 제어합니다(설정 → 제어). 두 곳이 모두 켜져 있어야 하며,
                      접속기가 연결돼 있지 않으면 도구는 안전하게 실패합니다.
                    </p>
                  </div>
                </label>
              </div>
            )}
          </div>
        </div>
      </div>
    </div>
  );
}

function NavGroupLabel({
  label,
  className = '',
}: {
  label: string;
  className?: string;
}) {
  return (
    <div
      className={`px-2 pt-1 pb-1 text-[0.625rem] uppercase tracking-wider font-semibold text-[hsl(var(--muted-foreground))] ${className}`}
    >
      {label}
    </div>
  );
}

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
      <Icon className="w-3.5 h-3.5 shrink-0" />
      <span className="flex-1 truncate">{label}</span>
      {badge !== undefined && (
        <span className="text-[0.6875rem] tabular-nums text-[hsl(var(--muted-foreground))] shrink-0">
          {badge}
        </span>
      )}
    </button>
  );
}

function PanelHeader({
  title,
  description,
}: {
  title: string;
  description: string;
}) {
  return (
    <div className="flex flex-col gap-0.5">
      <h3 className="text-[0.9375rem] font-semibold text-[hsl(var(--foreground))]">
        {title}
      </h3>
      <p className="text-[0.75rem] text-[hsl(var(--muted-foreground))] leading-relaxed">
        {description}
      </p>
    </div>
  );
}


/**
 * RegistryEditorLink — slim "go to host registry editor" link that
 * navigates to the corresponding top-level tab (cycle 20260429 PR
 * #553). Replaces the previous in-panel collapsible
 * `HostRegistryEditor` — the host CRUD now lives one click away in
 * the dedicated MCP / SKILLS / HOOK / 권한 tabs, so embedding it
 * inside the env picker doubled the surface area without adding
 * value.
 */
function RegistryEditorLink({
  tab,
}: {
  tab: 'skills' | 'permissions' | 'mcp';
}) {
  const labels: Record<typeof tab, { name: string; hint: string }> = {
    skills: {
      name: '스킬 등록소',
      hint: '스킬을 추가/수정하려면 호스트 등록소로 이동',
    },
    permissions: {
      name: '권한 등록소',
      hint: '권한 룰을 추가/수정하려면 호스트 등록소로 이동',
    },
    mcp: {
      name: 'MCP 등록소',
      hint: 'MCP 서버를 추가/수정하려면 호스트 등록소로 이동',
    },
  };
  const { name, hint } = labels[tab];
  return (
    <div className="border-t border-[hsl(var(--border))] pt-3 flex items-center gap-3">
      <span className="text-[0.625rem] uppercase tracking-wider px-1.5 py-0.5 rounded font-semibold bg-amber-500/15 text-amber-800 dark:text-amber-300 border border-amber-500/30 shrink-0">
        호스트 공용
      </span>
      <span className="text-[0.7rem] text-[hsl(var(--muted-foreground))] flex-1 leading-relaxed">
        {hint} (모든 환경에 영향).
      </span>
      <Link
        href={`/environments?tab=${tab}`}
        className="inline-flex items-center gap-1.5 h-7 px-2.5 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--background))] text-[0.7rem] font-medium text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))] hover:bg-[hsl(var(--accent))] transition-colors no-underline shrink-0"
      >
        <ExternalLink className="w-3 h-3" />
        {name} 열기
      </Link>
    </div>
  );
}

