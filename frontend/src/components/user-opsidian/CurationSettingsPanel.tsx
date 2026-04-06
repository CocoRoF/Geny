'use client';

import { useEffect, useState, useCallback } from 'react';
import { configApi, curatedKnowledgeApi } from '@/lib/api';
import { useUserOpsidianStore } from '@/store/useUserOpsidianStore';
import { useI18n } from '@/lib/i18n';
import {
  X,
  Sparkles,
  Clock,
  Play,
  Loader2,
  CheckCircle,
  AlertCircle,
  Save,
  ToggleLeft,
  ToggleRight,
  Zap,
  Brain,
  Timer,
  Hash,
} from 'lucide-react';

interface CurationScheduleConfig {
  auto_curation_enabled: boolean;
  auto_curation_use_llm: boolean;
  auto_curation_quality_threshold: number;
  auto_curation_schedule_enabled: boolean;
  auto_curation_interval_hours: number;
  auto_curation_max_notes_per_run: number;
  auto_curation_last_run: string;
}

const DEFAULT_CONFIG: CurationScheduleConfig = {
  auto_curation_enabled: false,
  auto_curation_use_llm: true,
  auto_curation_quality_threshold: 0.6,
  auto_curation_schedule_enabled: false,
  auto_curation_interval_hours: 24,
  auto_curation_max_notes_per_run: 20,
  auto_curation_last_run: '',
};

export default function CurationSettingsPanel({ onClose }: { onClose: () => void }) {
  const { t } = useI18n();
  const { files } = useUserOpsidianStore();

  const [config, setConfig] = useState<CurationScheduleConfig>(DEFAULT_CONFIG);
  const [loading, setLoading] = useState(true);
  const [saving, setSaving] = useState(false);
  const [saveMsg, setSaveMsg] = useState<{ type: 'success' | 'error'; text: string } | null>(null);

  const [batchRunning, setBatchRunning] = useState(false);
  const [batchResult, setBatchResult] = useState<{
    total: number; success_count: number;
  } | null>(null);

  // Load config on mount
  const loadConfig = useCallback(async () => {
    setLoading(true);
    try {
      const res = await configApi.get('ltm');
      const v = res.values || {};
      setConfig({
        auto_curation_enabled: (v.auto_curation_enabled as boolean) ?? false,
        auto_curation_use_llm: (v.auto_curation_use_llm as boolean) ?? true,
        auto_curation_quality_threshold: (v.auto_curation_quality_threshold as number) ?? 0.6,
        auto_curation_schedule_enabled: (v.auto_curation_schedule_enabled as boolean) ?? false,
        auto_curation_interval_hours: (v.auto_curation_interval_hours as number) ?? 24,
        auto_curation_max_notes_per_run: (v.auto_curation_max_notes_per_run as number) ?? 20,
        auto_curation_last_run: (v.auto_curation_last_run as string) ?? '',
      });
    } catch (e) {
      console.error('Failed to load LTM config:', e);
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { loadConfig(); }, [loadConfig]);

  // Auto-dismiss save message
  useEffect(() => {
    if (saveMsg) {
      const timer = setTimeout(() => setSaveMsg(null), 4000);
      return () => clearTimeout(timer);
    }
  }, [saveMsg]);

  const handleSave = async () => {
    setSaving(true);
    try {
      await configApi.update('ltm', {
        auto_curation_enabled: config.auto_curation_enabled,
        auto_curation_use_llm: config.auto_curation_use_llm,
        auto_curation_quality_threshold: config.auto_curation_quality_threshold,
        auto_curation_schedule_enabled: config.auto_curation_schedule_enabled,
        auto_curation_interval_hours: config.auto_curation_interval_hours,
        auto_curation_max_notes_per_run: config.auto_curation_max_notes_per_run,
      });
      setSaveMsg({ type: 'success', text: t('opsidian.curationSettingsSaved') });
    } catch (e: any) {
      setSaveMsg({ type: 'error', text: e.message || t('opsidian.curateFailed') });
    } finally {
      setSaving(false);
    }
  };

  const handleRunNow = async () => {
    setBatchRunning(true);
    setBatchResult(null);
    try {
      const res = await curatedKnowledgeApi.curateAll(config.auto_curation_use_llm);
      setBatchResult({ total: res.total, success_count: res.success_count });
    } catch (e) {
      console.error('Batch curation failed:', e);
      setBatchResult({ total: 0, success_count: 0 });
    } finally {
      setBatchRunning(false);
    }
  };

  const totalNotes = Object.keys(files).length;

  const Toggle = ({ value, onChange }: { value: boolean; onChange: (v: boolean) => void }) => (
    <button
      onClick={() => onChange(!value)}
      style={{
        display: 'flex', alignItems: 'center', background: 'none', border: 'none',
        cursor: 'pointer', color: value ? '#10b981' : 'var(--obs-text-muted)',
        padding: 0,
      }}
    >
      {value ? <ToggleRight size={22} /> : <ToggleLeft size={22} />}
    </button>
  );

  return (
    <div style={{
      position: 'fixed', inset: 0, zIndex: 9999,
      display: 'flex', alignItems: 'center', justifyContent: 'center',
      background: 'rgba(0,0,0,0.5)', backdropFilter: 'blur(4px)',
    }} onClick={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div style={{
        width: 480, maxHeight: '80vh', overflow: 'auto',
        background: 'var(--obs-bg-surface)', borderRadius: 12,
        border: '1px solid var(--obs-border)',
        boxShadow: '0 20px 60px rgba(0,0,0,0.3)',
      }}>
        {/* Header */}
        <div style={{
          display: 'flex', alignItems: 'center', gap: 10, padding: '16px 20px',
          borderBottom: '1px solid var(--obs-border-subtle)',
        }}>
          <Sparkles size={18} style={{ color: '#f59e0b' }} />
          <span style={{ flex: 1, fontSize: 15, fontWeight: 600, color: 'var(--obs-text)' }}>
            {t('opsidian.curationSettings')}
          </span>
          <button onClick={onClose} style={{
            display: 'flex', alignItems: 'center', justifyContent: 'center',
            width: 28, height: 28, background: 'var(--obs-bg-hover)',
            border: '1px solid var(--obs-border)', borderRadius: 6, cursor: 'pointer',
            color: 'var(--obs-text-muted)',
          }}>
            <X size={14} />
          </button>
        </div>

        {loading ? (
          <div style={{ padding: 40, textAlign: 'center', color: 'var(--obs-text-muted)' }}>
            <Loader2 size={20} className="spin" />
          </div>
        ) : (
          <div style={{ padding: '16px 20px', display: 'flex', flexDirection: 'column', gap: 20 }}>

            {/* ── Section 1: Manual Curation ── */}
            <div>
              <div style={{
                fontSize: 11, fontWeight: 600, color: 'var(--obs-text-dim)',
                textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 10,
              }}>
                {t('opsidian.manualCuration')}
              </div>
              <div style={{
                display: 'flex', alignItems: 'center', gap: 10, padding: '12px 14px',
                background: 'var(--obs-bg-panel)', borderRadius: 8,
                border: '1px solid var(--obs-border-subtle)',
              }}>
                <div style={{ flex: 1 }}>
                  <div style={{ fontSize: 13, fontWeight: 500, color: 'var(--obs-text)' }}>
                    {t('opsidian.curateAllNotes')}
                  </div>
                  <div style={{ fontSize: 11, color: 'var(--obs-text-muted)', marginTop: 2 }}>
                    {totalNotes} {t('opsidian.notes')} {t('opsidian.inUserVault')}
                  </div>
                </div>
                <button
                  onClick={handleRunNow}
                  disabled={batchRunning || totalNotes === 0}
                  style={{
                    display: 'flex', alignItems: 'center', gap: 6, padding: '8px 16px',
                    fontSize: 12, fontWeight: 600,
                    background: batchRunning ? 'rgba(245,158,11,0.05)' : 'rgba(245,158,11,0.15)',
                    color: '#f59e0b',
                    border: '1px solid rgba(245,158,11,0.3)',
                    borderRadius: 6, cursor: batchRunning ? 'not-allowed' : 'pointer',
                    opacity: batchRunning ? 0.7 : 1,
                  }}
                >
                  {batchRunning ? <Loader2 size={13} className="spin" /> : <Play size={13} />}
                  {batchRunning ? t('opsidian.curationRunning') : t('opsidian.runNow')}
                </button>
              </div>
              {batchResult && (
                <div style={{
                  marginTop: 8, padding: '8px 14px', borderRadius: 6, fontSize: 12,
                  background: batchResult.success_count > 0 ? 'rgba(16,185,129,0.1)' : 'rgba(100,116,139,0.1)',
                  color: batchResult.success_count > 0 ? '#10b981' : 'var(--obs-text-muted)',
                  display: 'flex', alignItems: 'center', gap: 6,
                }}>
                  <CheckCircle size={12} />
                  {batchResult.success_count}/{batchResult.total} {t('opsidian.notesCurated')}
                </div>
              )}
            </div>

            {/* ── Section 2: Pipeline Settings ── */}
            <div>
              <div style={{
                fontSize: 11, fontWeight: 600, color: 'var(--obs-text-dim)',
                textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 10,
              }}>
                {t('opsidian.pipelineSettings')}
              </div>
              <div style={{
                display: 'flex', flexDirection: 'column', gap: 0,
                background: 'var(--obs-bg-panel)', borderRadius: 8,
                border: '1px solid var(--obs-border-subtle)', overflow: 'hidden',
              }}>
                {/* Enable Auto-Curation */}
                <SettingRow
                  icon={<Zap size={13} style={{ color: '#f59e0b' }} />}
                  label={t('opsidian.enableAutoCuration')}
                  description={t('opsidian.enableAutoCurationDesc')}
                >
                  <Toggle value={config.auto_curation_enabled} onChange={(v) => setConfig(c => ({ ...c, auto_curation_enabled: v }))} />
                </SettingRow>

                {/* Use LLM */}
                <SettingRow
                  icon={<Brain size={13} style={{ color: '#8b5cf6' }} />}
                  label={t('opsidian.useLlm')}
                  description={t('opsidian.useLlmDesc')}
                >
                  <Toggle value={config.auto_curation_use_llm} onChange={(v) => setConfig(c => ({ ...c, auto_curation_use_llm: v }))} />
                </SettingRow>

                {/* Quality Threshold */}
                <SettingRow
                  icon={<Sparkles size={13} style={{ color: '#10b981' }} />}
                  label={t('opsidian.qualityThreshold')}
                  description={t('opsidian.qualityThresholdDesc')}
                >
                  <input
                    type="number"
                    value={config.auto_curation_quality_threshold}
                    onChange={(e) => setConfig(c => ({ ...c, auto_curation_quality_threshold: Math.max(0, Math.min(1, parseFloat(e.target.value) || 0)) }))}
                    step={0.1}
                    min={0}
                    max={1}
                    style={{
                      width: 60, padding: '4px 8px', fontSize: 12, textAlign: 'center',
                      background: 'var(--obs-bg-surface)', border: '1px solid var(--obs-border)',
                      borderRadius: 4, color: 'var(--obs-text)', outline: 'none',
                    }}
                  />
                </SettingRow>
              </div>
            </div>

            {/* ── Section 3: Schedule Settings ── */}
            <div>
              <div style={{
                fontSize: 11, fontWeight: 600, color: 'var(--obs-text-dim)',
                textTransform: 'uppercase', letterSpacing: '0.05em', marginBottom: 10,
              }}>
                {t('opsidian.scheduledCuration')}
              </div>
              <div style={{
                display: 'flex', flexDirection: 'column', gap: 0,
                background: 'var(--obs-bg-panel)', borderRadius: 8,
                border: '1px solid var(--obs-border-subtle)', overflow: 'hidden',
              }}>
                {/* Enable Schedule */}
                <SettingRow
                  icon={<Clock size={13} style={{ color: '#3b82f6' }} />}
                  label={t('opsidian.enableSchedule')}
                  description={t('opsidian.enableScheduleDesc')}
                >
                  <Toggle value={config.auto_curation_schedule_enabled} onChange={(v) => setConfig(c => ({ ...c, auto_curation_schedule_enabled: v }))} />
                </SettingRow>

                {/* Interval Hours */}
                <SettingRow
                  icon={<Timer size={13} style={{ color: '#6366f1' }} />}
                  label={t('opsidian.intervalHours')}
                  description={t('opsidian.intervalHoursDesc')}
                >
                  <input
                    type="number"
                    value={config.auto_curation_interval_hours}
                    onChange={(e) => setConfig(c => ({ ...c, auto_curation_interval_hours: Math.max(1, Math.min(168, parseInt(e.target.value) || 24)) }))}
                    min={1}
                    max={168}
                    style={{
                      width: 60, padding: '4px 8px', fontSize: 12, textAlign: 'center',
                      background: 'var(--obs-bg-surface)', border: '1px solid var(--obs-border)',
                      borderRadius: 4, color: 'var(--obs-text)', outline: 'none',
                    }}
                  />
                </SettingRow>

                {/* Max Notes Per Run */}
                <SettingRow
                  icon={<Hash size={13} style={{ color: '#ec4899' }} />}
                  label={t('opsidian.maxNotesPerRun')}
                  description={t('opsidian.maxNotesPerRunDesc')}
                >
                  <input
                    type="number"
                    value={config.auto_curation_max_notes_per_run}
                    onChange={(e) => setConfig(c => ({ ...c, auto_curation_max_notes_per_run: Math.max(1, Math.min(100, parseInt(e.target.value) || 20)) }))}
                    min={1}
                    max={100}
                    style={{
                      width: 60, padding: '4px 8px', fontSize: 12, textAlign: 'center',
                      background: 'var(--obs-bg-surface)', border: '1px solid var(--obs-border)',
                      borderRadius: 4, color: 'var(--obs-text)', outline: 'none',
                    }}
                  />
                </SettingRow>

                {/* Last Run */}
                {config.auto_curation_last_run && (
                  <SettingRow
                    icon={<CheckCircle size={13} style={{ color: '#10b981' }} />}
                    label={t('opsidian.lastRun')}
                  >
                    <span style={{ fontSize: 11, color: 'var(--obs-text-muted)' }}>
                      {new Date(config.auto_curation_last_run).toLocaleString()}
                    </span>
                  </SettingRow>
                )}
              </div>
            </div>

            {/* ── Save Button ── */}
            <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
              {saveMsg && (
                <span style={{
                  display: 'inline-flex', alignItems: 'center', gap: 4, fontSize: 12,
                  color: saveMsg.type === 'success' ? '#10b981' : '#ef4444',
                }}>
                  {saveMsg.type === 'success' ? <CheckCircle size={12} /> : <AlertCircle size={12} />}
                  {saveMsg.text}
                </span>
              )}
              <button
                onClick={handleSave}
                disabled={saving}
                style={{
                  marginLeft: 'auto', display: 'flex', alignItems: 'center', gap: 6,
                  padding: '8px 20px', fontSize: 13, fontWeight: 600,
                  background: 'var(--obs-purple)', color: '#fff',
                  border: 'none', borderRadius: 6, cursor: saving ? 'not-allowed' : 'pointer',
                  opacity: saving ? 0.7 : 1,
                }}
              >
                {saving ? <Loader2 size={13} className="spin" /> : <Save size={13} />}
                {t('opsidian.saveCurationSettings')}
              </button>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

/* ─── Setting Row sub-component ─── */
function SettingRow({
  icon, label, description, children,
}: {
  icon: React.ReactNode;
  label: string;
  description?: string;
  children: React.ReactNode;
}) {
  return (
    <div style={{
      display: 'flex', alignItems: 'center', gap: 10, padding: '10px 14px',
      borderBottom: '1px solid var(--obs-border-subtle)',
    }}>
      {icon}
      <div style={{ flex: 1 }}>
        <div style={{ fontSize: 12, fontWeight: 500, color: 'var(--obs-text)' }}>{label}</div>
        {description && (
          <div style={{ fontSize: 10, color: 'var(--obs-text-muted)', marginTop: 1 }}>{description}</div>
        )}
      </div>
      {children}
    </div>
  );
}
