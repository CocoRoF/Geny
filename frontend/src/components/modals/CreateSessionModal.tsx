'use client';

import { useState, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { useAppStore } from '@/store/useAppStore';
import { useEnvironmentStore } from '@/store/useEnvironmentStore';
import { agentApi, ttsApi, type VoiceProfile } from '@/lib/api';
// workflowApi removed — pipeline presets replace workflow selection
import { toolPresetApi } from '@/lib/toolApi';
import NumberStepper from '@/components/ui/NumberStepper';
import InfoTooltip from '@/components/ui/InfoTooltip';
import { X } from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import { useVTuberStore } from '@/store/useVTuberStore';
import type { CreateAgentRequest, SessionInfo, ToolPresetDefinition } from '@/types';
// WorkflowDefinition type removed — using preset strings instead

const selectArrow: React.CSSProperties = {
  backgroundImage: "url(\"data:image/svg+xml,%3Csvg xmlns='http://www.w3.org/2000/svg' width='12' height='12' viewBox='0 0 24 24' fill='none' stroke='%239ca3af' stroke-width='2'%3E%3Cpath d='M6 9l6 6 6-6'/%3E%3C/svg%3E\")",
  backgroundRepeat: 'no-repeat',
  backgroundPosition: 'right 12px center',
};

interface Props { onClose: () => void; }

const MODEL_OPTIONS_BASE = [
  { value: '', labelKey: 'createSession.modelDefault' },
  { value: 'claude-opus-4-6', label: 'Claude Opus 4.6' },
  { value: 'claude-sonnet-4-6', label: 'Claude Sonnet 4.6' },
  { value: 'claude-opus-4-5-20251101', label: 'Claude Opus 4.5' },
  { value: 'claude-sonnet-4-5-20250929', label: 'Claude Sonnet 4.5' },
  { value: 'claude-haiku-4-5-20251001', label: 'Claude Haiku 4.5' },
  { value: 'claude-opus-4-20250514', label: 'Claude Opus 4' },
  { value: 'claude-sonnet-4-20250514', label: 'Claude Sonnet 4' },
  { value: 'claude-haiku-4-20250414', label: 'Claude Haiku 4' },
];

export default function CreateSessionModal({ onClose }: Props) {
  const { createSession, prompts, loadPrompts, loadPromptContent } = useAppStore();
  const { t } = useI18n();

  const [formState, setFormState] = useState<CreateAgentRequest>({
    session_name: '',
    role: 'developer',
    model: '',
    max_turns: 50,
    timeout: 21600,
    max_iterations: 50,
    system_prompt: '',
  });
  const [selectedPrompt, setSelectedPrompt] = useState('geny-default');
  const [selectedCliPrompt, setSelectedCliPrompt] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [toolPresets, setToolPresets] = useState<ToolPresetDefinition[]>([]);
  const [selectedPreset, setSelectedPreset] = useState('');
  const [selectedCliPreset, setSelectedCliPreset] = useState('');
  const [selectedEnvId, setSelectedEnvId] = useState('');
  const [memoryProvider, setMemoryProvider] = useState<'' | 'disabled' | 'ephemeral' | 'file' | 'sql'>('');
  const [memoryRoot, setMemoryRoot] = useState('');
  const [memoryDsn, setMemoryDsn] = useState('');
  const [memoryDialect, setMemoryDialect] = useState<'' | 'sqlite' | 'postgres'>('');
  const [memoryScope, setMemoryScope] = useState('');
  const [memoryTimezone, setMemoryTimezone] = useState('');
  const [showMemoryAdvanced, setShowMemoryAdvanced] = useState(false);
  const {
    environments,
    isLoading: environmentsLoading,
    loadEnvironments,
  } = useEnvironmentStore();
  const [selectedAvatar, setSelectedAvatar] = useState('');
  const [selectedTtsProfile, setSelectedTtsProfile] = useState('');
  const [ttsProfiles, setTtsProfiles] = useState<VoiceProfile[]>([]);
  const [ttsProfilesLoaded, setTtsProfilesLoaded] = useState(false);
  const [ttsEnabled, setTtsEnabled] = useState(false);
  const { models: avatarModels, modelsLoaded: avatarsLoaded, fetchModels: fetchAvatarModels, assignModel: assignAvatar } = useVTuberStore();

  useEffect(() => { loadPrompts(); }, [loadPrompts]);

  // Load avatar models + TTS profiles when VTuber role is selected
  useEffect(() => {
    if (formState.role === 'vtuber' && !avatarsLoaded) {
      fetchAvatarModels();
    }
    if (formState.role === 'vtuber' && !ttsProfilesLoaded) {
      Promise.all([
        ttsApi.engines().catch((): { engines: string[]; default: string } => ({ engines: [], default: '' })),
        ttsApi.listProfiles().catch((): { profiles: VoiceProfile[] } => ({ profiles: [] })),
      ]).then(([enginesRes, profilesRes]) => {
        const hasGptSovits = enginesRes.engines.includes('gpt_sovits');
        setTtsEnabled(hasGptSovits);
        setTtsProfiles(profilesRes.profiles || []);
        setTtsProfilesLoaded(true);
      });
    }
  }, [formState.role, avatarsLoaded, fetchAvatarModels, ttsProfilesLoaded]);

  // Load default prompt template content on mount
  useEffect(() => {
    if (selectedPrompt && !formState.system_prompt) {
      loadPromptContent(selectedPrompt).then(content => {
        if (content) setFormState(f => ({ ...f, system_prompt: content }));
      });
    }
  }, [selectedPrompt, loadPromptContent]);

  // Load available workflows
  useEffect(() => {
    // Workflow list removed — presets are determined by role
    toolPresetApi.list().catch(() => ({ presets: [] })).then((presetRes) => {
      setToolPresets(presetRes.presets || []);
    });
  }, []);

  // Load environments for the Phase 6e env_id selector
  useEffect(() => {
    loadEnvironments();
  }, [loadEnvironments]);

  const handlePromptChange = async (name: string) => {
    setSelectedPrompt(name);
    if (name) {
      const content = await loadPromptContent(name);
      if (content) setFormState(f => ({ ...f, system_prompt: content }));
    } else {
      // "None" selected — clear template content
      setFormState(f => ({ ...f, system_prompt: '' }));
    }
  };

  const handleCliPromptChange = async (name: string) => {
    setSelectedCliPrompt(name);
    if (name) {
      const content = await loadPromptContent(name);
      if (content) setFormState(f => ({ ...f, bound_worker_system_prompt: content }));
    } else {
      setFormState(f => ({ ...f, bound_worker_system_prompt: '' }));
    }
  };

  const handleRoleChange = (role: string) => {
    setFormState(f => ({ ...f, role }));
    if (role === 'vtuber') {
      handlePromptChange('vtuber-default');
      handleCliPromptChange('cli-default');
      if (!avatarsLoaded) fetchAvatarModels();
    } else {
      setSelectedAvatar('');
      setSelectedTtsProfile('');
      setSelectedCliPrompt('');
      setSelectedCliPreset('');
    }
  };

  // Filtered prompt lists
  const vtuberPrompts = prompts.filter(p => p.name.startsWith('vtuber-'));
  const cliPrompts = prompts.filter(p => p.name.startsWith('cli-'));
  const generalPrompts = prompts.filter(p => !p.name.startsWith('vtuber-') && !p.name.startsWith('cli-'));

  const handleSubmit = async () => {
    setSubmitting(true);
    setError('');
    try {
      const payload: CreateAgentRequest = { ...formState };
      // Preset is determined by role on backend — send workflow_id for compat
      payload.workflow_id = formState.role === 'vtuber' ? 'template-vtuber' : 'template-optimized-autonomous';
      // Send tool preset if explicitly selected
      if (selectedPreset) {
        payload.tool_preset_id = selectedPreset;
      }
      // Phase 6e — attach EnvironmentManifest if selected. Backend
      // falls back to the role-based preset pipeline when env_id is
      // absent, so empty string = legacy path (unchanged behavior).
      if (selectedEnvId) {
        payload.env_id = selectedEnvId;
      }
      // Phase 7-3 — per-session MemoryProvider override. Only send
      // when the user picked a provider; leaving it blank = process
      // default (MEMORY_PROVIDER env).
      if (memoryProvider) {
        const memCfg: Record<string, unknown> = { provider: memoryProvider };
        if (memoryProvider === 'file') {
          if (memoryRoot.trim()) memCfg.root = memoryRoot.trim();
        }
        if (memoryProvider === 'sql') {
          if (memoryDsn.trim()) memCfg.dsn = memoryDsn.trim();
          if (memoryDialect) memCfg.dialect = memoryDialect;
        }
        if (memoryScope.trim()) memCfg.scope = memoryScope.trim();
        if (memoryTimezone.trim()) memCfg.timezone = memoryTimezone.trim();
        payload.memory_config = memCfg;
      }
      // Bound-Worker tool-preset override currently has no backend
      // field (manifest-backed tool list now; see plan/02). The
      // selector remains as a UI placeholder for PR 20's auto-pair
      // reshape. Intentionally no-op here.
      const session = await createSession(payload);
      // Auto-assign avatar if selected for VTuber sessions
      if (selectedAvatar && session?.session_id && formState.role === 'vtuber') {
        try {
          await assignAvatar(session.session_id, selectedAvatar);
        } catch {
          // Non-blocking: session created successfully, avatar assignment can be done later
          console.warn('Avatar assignment failed, can be assigned manually later');
        }
      }
      // Auto-assign TTS voice profile if selected for VTuber sessions
      if (selectedTtsProfile && session?.session_id && formState.role === 'vtuber') {
        try {
          await ttsApi.assignSessionProfile(session.session_id, selectedTtsProfile);
        } catch {
          console.warn('TTS profile assignment failed, can be assigned manually later');
        }
      }
      onClose();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : t('createSession.failedToCreate'));
    } finally {
      setSubmitting(false);
    }
  };

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <div className="bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-lg w-full max-w-[480px] mx-4 max-h-[85vh] flex flex-col shadow-[var(--shadow-lg)]" onClick={e => e.stopPropagation()}>
        {/* Header */}
        <div className="flex justify-between items-center py-3 md:py-4 px-4 md:px-6 border-b border-[var(--border-color)]">
          <h3 className="text-[1rem] font-semibold text-[var(--text-primary)]">{t('createSession.title')}</h3>
          <button className="flex items-center justify-center w-8 h-8 rounded-[var(--border-radius)] bg-transparent border-none text-[var(--text-muted)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)] cursor-pointer" onClick={onClose}><X size={16} /></button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-4 md:px-6 py-4 md:py-5 flex flex-col gap-4">
          {error && <div className="text-[0.8125rem] text-[var(--danger-color)] bg-[rgba(239,68,68,0.1)] p-2.5 rounded-[6px] mb-2">{error}</div>}

          {/* Session Name */}
          <div className="flex flex-col gap-1.5">
            <label className="text-[0.8125rem] font-medium text-[var(--text-secondary)]">{t('createSession.sessionName')}</label>
            <input
              className="w-full py-2.5 px-3 bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-[var(--border-radius)] text-[0.875rem] text-[var(--text-primary)] placeholder:text-[var(--text-muted)] transition-[border-color] focus:outline-none focus:border-[var(--primary-color)] focus:shadow-[0_0_0_3px_rgba(59,130,246,0.15)]"
              placeholder={t('createSession.sessionNamePlaceholder')}
              value={formState.session_name || ''} onChange={e => setFormState(f => ({ ...f, session_name: e.target.value }))} />
          </div>

          {/* Role + Model */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="flex flex-col gap-1.5">
              <label className="text-[0.8125rem] font-medium text-[var(--text-secondary)]">{t('createSession.role')}</label>
              <select className="w-full py-2.5 px-3 bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-[var(--border-radius)] text-[0.875rem] text-[var(--text-primary)] appearance-none cursor-pointer transition-[border-color] focus:outline-none focus:border-[var(--primary-color)] focus:shadow-[0_0_0_3px_rgba(59,130,246,0.15)] pr-8" style={selectArrow} value={formState.role} onChange={e => handleRoleChange(e.target.value)}>
                <option value="developer">{t('createSession.roleDeveloper')}</option>
                <option value="worker">{t('createSession.roleWorker')}</option>
                <option value="researcher">{t('createSession.roleResearcher')}</option>
                <option value="planner">{t('createSession.rolePlanner')}</option>
                <option value="vtuber">{t('createSession.roleVTuber')}</option>
              </select>
            </div>
            <div className="flex flex-col gap-1.5">
              <label className="text-[0.8125rem] font-medium text-[var(--text-secondary)]">{t('createSession.model')}</label>
              <select className="w-full py-2.5 px-3 bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-[var(--border-radius)] text-[0.875rem] text-[var(--text-primary)] appearance-none cursor-pointer transition-[border-color] focus:outline-none focus:border-[var(--primary-color)] focus:shadow-[0_0_0_3px_rgba(59,130,246,0.15)] pr-8" style={selectArrow} value={formState.model || ''} onChange={e => setFormState(f => ({ ...f, model: e.target.value }))}>
                {MODEL_OPTIONS_BASE.map(opt => (
                  <option key={opt.value} value={opt.value}>{'labelKey' in opt ? t(opt.labelKey as string) : opt.label}</option>
                ))}
              </select>
            </div>
          </div>

          {/* Avatar (VTuber only) */}
          {formState.role === 'vtuber' && (
            <div className="flex flex-col gap-1.5">
              <label className="text-[0.8125rem] font-medium text-[var(--text-secondary)] inline-flex items-center gap-1.5">{t('createSession.avatar')} <InfoTooltip text={t('createSession.avatarHelp')} /></label>
              <select className="w-full py-2.5 px-3 bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-[var(--border-radius)] text-[0.875rem] text-[var(--text-primary)] appearance-none cursor-pointer transition-[border-color] focus:outline-none focus:border-[var(--primary-color)] focus:shadow-[0_0_0_3px_rgba(59,130,246,0.15)] pr-8" style={selectArrow} value={selectedAvatar} onChange={e => setSelectedAvatar(e.target.value)}>
                <option value="">{avatarsLoaded ? t('createSession.avatarNone') : t('createSession.avatarLoading')}</option>
                {avatarModels.map(m => (
                  <option key={m.name} value={m.name}>{m.display_name || m.name}</option>
                ))}
              </select>
            </div>
          )}

          {/* TTS Voice Profile (VTuber only) */}
          {formState.role === 'vtuber' && (
            <div className="flex flex-col gap-1.5">
              <label className="text-[0.8125rem] font-medium text-[var(--text-secondary)] inline-flex items-center gap-1.5">{t('createSession.ttsProfile')} <InfoTooltip text={t('createSession.ttsProfileHelp')} /></label>
              {ttsProfilesLoaded && !ttsEnabled ? (
                <div className="w-full py-2.5 px-3 bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-[var(--border-radius)] text-[0.8125rem] text-[var(--text-muted)] opacity-60">
                  {t('createSession.ttsDisabled')}
                </div>
              ) : (
                <select className="w-full py-2.5 px-3 bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-[var(--border-radius)] text-[0.875rem] text-[var(--text-primary)] appearance-none cursor-pointer transition-[border-color] focus:outline-none focus:border-[var(--primary-color)] focus:shadow-[0_0_0_3px_rgba(59,130,246,0.15)] pr-8" style={selectArrow} value={selectedTtsProfile} onChange={e => setSelectedTtsProfile(e.target.value)}>
                  <option value="">{ttsProfilesLoaded ? t('createSession.ttsProfileNone') : t('createSession.ttsProfileLoading')}</option>
                  {ttsProfiles.map(p => (
                    <option key={p.name} value={p.name}>{p.display_name || p.name}</option>
                  ))}
                </select>
              )}
            </div>
          )}

          {/* Prompt Template — hidden for VTuber (moved into VTuber sections) */}
          {formState.role !== 'vtuber' && (
            <div className="flex flex-col gap-1.5">
              <label className="text-[0.8125rem] font-medium text-[var(--text-secondary)] inline-flex items-center gap-1.5">{t('createSession.promptTemplate')} <InfoTooltip text={t('createSession.promptTemplateHelp')} /></label>
              <select className="w-full py-2.5 px-3 bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-[var(--border-radius)] text-[0.875rem] text-[var(--text-primary)] appearance-none cursor-pointer transition-[border-color] focus:outline-none focus:border-[var(--primary-color)] focus:shadow-[0_0_0_3px_rgba(59,130,246,0.15)] pr-8" style={selectArrow} value={selectedPrompt} onChange={e => handlePromptChange(e.target.value)}>
                <option value="">{t('createSession.templateNone')}</option>
                {generalPrompts.map(p => (
                  <option key={p.name} value={p.name}>{p.name}</option>
                ))}
              </select>
            </div>
          )}

          {/* Max Turns + Timeout */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="flex flex-col gap-1.5">
              <label className="text-[0.8125rem] font-medium text-[var(--text-secondary)] inline-flex items-center gap-1.5">{t('createSession.maxTurns')} <InfoTooltip text={t('createSession.maxTurnsHelp')} /></label>
              <NumberStepper value={formState.max_turns ?? 50} onChange={v => setFormState(f => ({ ...f, max_turns: v }))} min={1} max={500} step={5} />
            </div>
            <div className="flex flex-col gap-1.5">
              <label className="text-[0.8125rem] font-medium text-[var(--text-secondary)] inline-flex items-center gap-1.5">{t('createSession.timeout')} <InfoTooltip text={t('createSession.timeoutHelp')} /></label>
              <NumberStepper value={formState.timeout ?? 21600} onChange={v => setFormState(f => ({ ...f, timeout: v }))} min={10} max={86400} step={60} />
            </div>
          </div>

          {/* Max Iterations */}
          <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
            <div className="flex flex-col gap-1.5">
              <label className="text-[0.8125rem] font-medium text-[var(--text-secondary)] inline-flex items-center gap-1.5">{t('createSession.maxIterations')} <InfoTooltip text={t('createSession.maxIterationsHelp')} /></label>
              <NumberStepper value={formState.max_iterations ?? 30} onChange={v => setFormState(f => ({ ...f, max_iterations: v }))} min={1} max={500} step={5} />
            </div>
          </div>

          {/* Tool Preset */}
          <div className="flex flex-col gap-1.5">
            <label className="text-[0.8125rem] font-medium text-[var(--text-secondary)] inline-flex items-center gap-1.5">
              Tool Preset <InfoTooltip text="Select which Python tools and MCP servers are available to the agent. Default is determined by the role." />
            </label>
            <select className="w-full py-2.5 px-3 bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-[var(--border-radius)] text-[0.875rem] text-[var(--text-primary)] appearance-none cursor-pointer transition-[border-color] focus:outline-none focus:border-[var(--primary-color)] focus:shadow-[0_0_0_3px_rgba(59,130,246,0.15)] pr-8" style={selectArrow} value={selectedPreset} onChange={e => setSelectedPreset(e.target.value)}>
              <option value="">Default (based on role)</option>
              {toolPresets.filter(p => p.is_template).length > 0 && (
                <optgroup label="Templates">
                  {toolPresets.filter(p => p.is_template).map(p => (
                    <option key={p.id} value={p.id}>{p.icon || '🔧'} {p.name}</option>
                  ))}
                </optgroup>
              )}
              {toolPresets.filter(p => !p.is_template).length > 0 && (
                <optgroup label="Custom">
                  {toolPresets.filter(p => !p.is_template).map(p => (
                    <option key={p.id} value={p.id}>{p.icon || '🔧'} {p.name}</option>
                  ))}
                </optgroup>
              )}
            </select>
            <small className="text-[0.75rem] text-[var(--text-muted)] mt-0.5">
              {(() => {
                if (!selectedPreset) return 'Automatically selects the best preset for the chosen role.';
                const p = toolPresets.find(tp => tp.id === selectedPreset);
                return p?.description || '';
              })()}
            </small>
          </div>

          {/* Environment (v2 EnvironmentManifest) — optional. When set,
              backend swaps the legacy preset pipeline for the manifest's
              Pipeline + tools snapshot. */}
          <div className="flex flex-col gap-1.5">
            <label className="text-[0.8125rem] font-medium text-[var(--text-secondary)] inline-flex items-center gap-1.5">
              {t('createSession.environment')}
              <InfoTooltip text={t('createSession.environmentHelp')} />
            </label>
            <select
              className="w-full py-2.5 px-3 bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-[var(--border-radius)] text-[0.875rem] text-[var(--text-primary)] appearance-none cursor-pointer transition-[border-color] focus:outline-none focus:border-[var(--primary-color)] focus:shadow-[0_0_0_3px_rgba(59,130,246,0.15)] pr-8"
              style={selectArrow}
              value={selectedEnvId}
              onChange={e => setSelectedEnvId(e.target.value)}
            >
              <option value="">
                {environmentsLoading && environments.length === 0
                  ? t('createSession.environmentLoading')
                  : t('createSession.environmentNone')}
              </option>
              {environments.map(env => (
                <option key={env.id} value={env.id}>
                  {env.name}
                </option>
              ))}
            </select>
            <small className="text-[0.75rem] text-[var(--text-muted)] mt-0.5">
              {(() => {
                if (!selectedEnvId) return t('createSession.environmentLegacy');
                const env = environments.find(e => e.id === selectedEnvId);
                return env?.description || t('createSession.environmentSelected');
              })()}
            </small>
          </div>

          {/* Memory provider override (advanced, collapsible) */}
          <div className="flex flex-col gap-1.5">
            <button
              type="button"
              onClick={() => setShowMemoryAdvanced(v => !v)}
              className="flex items-center justify-between gap-2 py-1 text-left bg-transparent border-none text-[0.8125rem] font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)] cursor-pointer"
            >
              <span className="inline-flex items-center gap-1.5">
                {t('createSession.memoryOverride')}
                <InfoTooltip text={t('createSession.memoryOverrideHelp')} />
              </span>
              <span className="text-[0.75rem] text-[var(--text-muted)]">
                {showMemoryAdvanced ? t('createSession.memoryHide') : t('createSession.memoryShow')}
              </span>
            </button>
            {showMemoryAdvanced && (
              <div className="flex flex-col gap-3 p-3 rounded-md bg-[var(--bg-primary)] border border-[var(--border-color)]">
                <div className="flex flex-col gap-1.5">
                  <label className="text-[0.75rem] font-medium text-[var(--text-secondary)]">
                    {t('createSession.memoryProvider')}
                  </label>
                  <select
                    className="w-full py-2 px-3 bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-[var(--border-radius)] text-[0.8125rem] text-[var(--text-primary)] appearance-none cursor-pointer focus:outline-none focus:border-[var(--primary-color)] pr-8"
                    style={selectArrow}
                    value={memoryProvider}
                    onChange={e => setMemoryProvider(e.target.value as typeof memoryProvider)}
                  >
                    <option value="">{t('createSession.memoryProviderDefault')}</option>
                    <option value="disabled">{t('createSession.memoryProviderDisabled')}</option>
                    <option value="ephemeral">{t('createSession.memoryProviderEphemeral')}</option>
                    <option value="file">{t('createSession.memoryProviderFile')}</option>
                    <option value="sql">{t('createSession.memoryProviderSql')}</option>
                  </select>
                </div>

                {memoryProvider === 'file' && (
                  <div className="flex flex-col gap-1.5">
                    <label className="text-[0.75rem] font-medium text-[var(--text-secondary)]">
                      {t('createSession.memoryRoot')}
                    </label>
                    <input
                      className="w-full py-2 px-3 bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-[var(--border-radius)] text-[0.8125rem] text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--primary-color)]"
                      placeholder="/var/lib/geny/memory"
                      value={memoryRoot}
                      onChange={e => setMemoryRoot(e.target.value)}
                    />
                    <small className="text-[0.6875rem] text-[var(--text-muted)]">
                      {t('createSession.memoryRootHelp')}
                    </small>
                  </div>
                )}

                {memoryProvider === 'sql' && (
                  <>
                    <div className="flex flex-col gap-1.5">
                      <label className="text-[0.75rem] font-medium text-[var(--text-secondary)]">
                        {t('createSession.memoryDsn')}
                      </label>
                      <input
                        className="w-full py-2 px-3 bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-[var(--border-radius)] text-[0.8125rem] font-mono text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--primary-color)]"
                        placeholder="sqlite:///./data/memory.db"
                        value={memoryDsn}
                        onChange={e => setMemoryDsn(e.target.value)}
                      />
                      <small className="text-[0.6875rem] text-[var(--text-muted)]">
                        {t('createSession.memoryDsnHelp')}
                      </small>
                    </div>
                    <div className="flex flex-col gap-1.5">
                      <label className="text-[0.75rem] font-medium text-[var(--text-secondary)]">
                        {t('createSession.memoryDialect')}
                      </label>
                      <select
                        className="w-full py-2 px-3 bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-[var(--border-radius)] text-[0.8125rem] text-[var(--text-primary)] appearance-none cursor-pointer focus:outline-none focus:border-[var(--primary-color)] pr-8"
                        style={selectArrow}
                        value={memoryDialect}
                        onChange={e => setMemoryDialect(e.target.value as typeof memoryDialect)}
                      >
                        <option value="">{t('createSession.memoryDialectAuto')}</option>
                        <option value="sqlite">sqlite</option>
                        <option value="postgres">postgres</option>
                      </select>
                    </div>
                  </>
                )}

                {memoryProvider && memoryProvider !== 'disabled' && (
                  <div className="grid grid-cols-1 sm:grid-cols-2 gap-3">
                    <div className="flex flex-col gap-1.5">
                      <label className="text-[0.75rem] font-medium text-[var(--text-secondary)]">
                        {t('createSession.memoryScope')}
                      </label>
                      <input
                        className="w-full py-2 px-3 bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-[var(--border-radius)] text-[0.8125rem] text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--primary-color)]"
                        placeholder="session"
                        value={memoryScope}
                        onChange={e => setMemoryScope(e.target.value)}
                      />
                    </div>
                    <div className="flex flex-col gap-1.5">
                      <label className="text-[0.75rem] font-medium text-[var(--text-secondary)]">
                        {t('createSession.memoryTimezone')}
                      </label>
                      <input
                        className="w-full py-2 px-3 bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-[var(--border-radius)] text-[0.8125rem] text-[var(--text-primary)] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--primary-color)]"
                        placeholder="Asia/Seoul"
                        value={memoryTimezone}
                        onChange={e => setMemoryTimezone(e.target.value)}
                      />
                    </div>
                  </div>
                )}
              </div>
            )}
          </div>

          {/* System Prompt — VTuber mode shows dual prompts with template selectors */}
          {formState.role === 'vtuber' ? (
            <>
              {/* VTuber Persona Prompt */}
              <div className="flex flex-col gap-1.5">
                <label className="text-[0.8125rem] font-medium text-[var(--text-secondary)] inline-flex items-center gap-1.5">{t('createSession.vtuberPromptLabel')} <InfoTooltip text={t('createSession.vtuberPromptHelp')} /></label>
                <select className="w-full py-2.5 px-3 bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-[var(--border-radius)] text-[0.875rem] text-[var(--text-primary)] appearance-none cursor-pointer transition-[border-color] focus:outline-none focus:border-[var(--primary-color)] focus:shadow-[0_0_0_3px_rgba(59,130,246,0.15)] pr-8" style={selectArrow} value={selectedPrompt} onChange={e => handlePromptChange(e.target.value)}>
                  <option value="">{t('createSession.templateNone')}</option>
                  {vtuberPrompts.map(p => (
                    <option key={p.name} value={p.name}>{p.name}</option>
                  ))}
                </select>
                <textarea className="w-full py-2.5 px-3 bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-[var(--border-radius)] text-[0.875rem] text-[var(--text-primary)] placeholder:text-[var(--text-muted)] transition-[border-color] focus:outline-none focus:border-[var(--primary-color)] focus:shadow-[0_0_0_3px_rgba(59,130,246,0.15)] resize-y" rows={4} placeholder={t('createSession.systemPromptPlaceholder')}
                  value={formState.system_prompt || ''} onChange={e => setFormState(f => ({ ...f, system_prompt: e.target.value }))} />
              </div>
              {/* CLI Agent Prompt */}
              <div className="flex flex-col gap-1.5">
                <label className="text-[0.8125rem] font-medium text-[var(--text-secondary)] inline-flex items-center gap-1.5">{t('createSession.cliPromptLabel')} <InfoTooltip text={t('createSession.cliPromptHelp')} /></label>
                <select className="w-full py-2.5 px-3 bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-[var(--border-radius)] text-[0.875rem] text-[var(--text-primary)] appearance-none cursor-pointer transition-[border-color] focus:outline-none focus:border-[var(--primary-color)] focus:shadow-[0_0_0_3px_rgba(59,130,246,0.15)] pr-8" style={selectArrow} value={selectedCliPrompt} onChange={e => handleCliPromptChange(e.target.value)}>
                  <option value="">{t('createSession.templateNone')}</option>
                  {cliPrompts.map(p => (
                    <option key={p.name} value={p.name}>{p.name}</option>
                  ))}
                </select>
                <textarea className="w-full py-2.5 px-3 bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-[var(--border-radius)] text-[0.875rem] text-[var(--text-primary)] placeholder:text-[var(--text-muted)] transition-[border-color] focus:outline-none focus:border-[var(--primary-color)] focus:shadow-[0_0_0_3px_rgba(59,130,246,0.15)] resize-y" rows={3} placeholder={t('createSession.cliPromptPlaceholder')}
                  value={formState.bound_worker_system_prompt || ''} onChange={e => setFormState(f => ({ ...f, bound_worker_system_prompt: e.target.value }))} />
              </div>
              {/* CLI Agent Model */}
              <div className="flex flex-col gap-1.5">
                <label className="text-[0.8125rem] font-medium text-[var(--text-secondary)] inline-flex items-center gap-1.5">{t('createSession.cliModel')} <InfoTooltip text={t('createSession.cliModelHelp')} /></label>
                <select className="w-full py-2.5 px-3 bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-[var(--border-radius)] text-[0.875rem] text-[var(--text-primary)] appearance-none cursor-pointer transition-[border-color] focus:outline-none focus:border-[var(--primary-color)] focus:shadow-[0_0_0_3px_rgba(59,130,246,0.15)] pr-8" style={selectArrow} value={formState.bound_worker_model || ''} onChange={e => setFormState(f => ({ ...f, bound_worker_model: e.target.value }))}>
                  <option value="">{t('createSession.cliModelSame')}</option>
                  {MODEL_OPTIONS_BASE.filter(o => o.value).map(opt => (
                    <option key={opt.value} value={opt.value}>{opt.label}</option>
                  ))}
                </select>
              </div>
              {/* CLI Agent Tool Preset */}
              <div className="flex flex-col gap-1.5">
                <label className="text-[0.8125rem] font-medium text-[var(--text-secondary)] inline-flex items-center gap-1.5">{t('createSession.cliToolPreset')} <InfoTooltip text={t('createSession.cliToolPresetHelp')} /></label>
                <select className="w-full py-2.5 px-3 bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-[var(--border-radius)] text-[0.875rem] text-[var(--text-primary)] appearance-none cursor-pointer transition-[border-color] focus:outline-none focus:border-[var(--primary-color)] focus:shadow-[0_0_0_3px_rgba(59,130,246,0.15)] pr-8" style={selectArrow} value={selectedCliPreset} onChange={e => setSelectedCliPreset(e.target.value)}>
                  <option value="">{t('createSession.cliToolPresetSame')}</option>
                  {toolPresets.filter(p => p.is_template).length > 0 && (
                    <optgroup label="Templates">
                      {toolPresets.filter(p => p.is_template).map(p => (
                        <option key={p.id} value={p.id}>{p.icon || '🔧'} {p.name}</option>
                      ))}
                    </optgroup>
                  )}
                  {toolPresets.filter(p => !p.is_template).length > 0 && (
                    <optgroup label="Custom">
                      {toolPresets.filter(p => !p.is_template).map(p => (
                        <option key={p.id} value={p.id}>{p.icon || '🔧'} {p.name}</option>
                      ))}
                    </optgroup>
                  )}
                </select>
                <small className="text-[0.75rem] text-[var(--text-muted)] mt-0.5">
                  {(() => {
                    if (!selectedCliPreset) return t('createSession.cliToolPresetDefault');
                    const p = toolPresets.find(tp => tp.id === selectedCliPreset);
                    return p?.description || '';
                  })()}
                </small>
              </div>
            </>
          ) : (
            <div className="flex flex-col gap-1.5">
              <label className="text-[0.8125rem] font-medium text-[var(--text-secondary)] inline-flex items-center gap-1.5">{t('createSession.systemPrompt')} <InfoTooltip text={t('createSession.systemPromptHelp')} /></label>
              <textarea className="w-full py-2.5 px-3 bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-[var(--border-radius)] text-[0.875rem] text-[var(--text-primary)] placeholder:text-[var(--text-muted)] transition-[border-color] focus:outline-none focus:border-[var(--primary-color)] focus:shadow-[0_0_0_3px_rgba(59,130,246,0.15)] resize-y" rows={4} placeholder={t('createSession.systemPromptPlaceholder')}
                value={formState.system_prompt || ''} onChange={e => setFormState(f => ({ ...f, system_prompt: e.target.value }))} />
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex justify-end items-center gap-3 py-3 md:py-4 px-4 md:px-6 border-t border-[var(--border-color)]">
          <button className="py-2 px-4 bg-transparent hover:bg-[var(--bg-hover)] text-[var(--text-secondary)] text-[0.8125rem] font-medium rounded-[var(--border-radius)] cursor-pointer transition-all duration-150 border border-[var(--border-color)]" onClick={onClose}>{t('common.cancel')}</button>
          <button className="py-2 px-4 bg-[var(--primary-color)] hover:bg-[var(--primary-hover)] text-white text-[0.8125rem] font-medium rounded-[var(--border-radius)] cursor-pointer transition-all duration-150 border-none disabled:opacity-50 disabled:cursor-not-allowed" onClick={handleSubmit} disabled={submitting}>
            {submitting ? t('createSession.creating') : t('createSession.createSession')}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
