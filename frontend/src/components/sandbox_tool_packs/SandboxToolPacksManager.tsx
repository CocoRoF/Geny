'use client';

/**
 * SandboxToolPacksManager — the reusable Sandbox Tool Packs manager.
 *
 * A pack = an independent GAPT environment (workspace restorable from a snapshot)
 * + the tools whose code runs inside it + the skills documenting them. It's a
 * first-class **Agent Environment component**, so this renders both as a standalone
 * page (/sandbox-tool-packs) and as the "Sandbox Tool Packs" section of the
 * environment editor (?tab=sandbox_packs).
 *
 * Uses the shared host-registry chrome (RegistryPageShell / RegistryGrid /
 * RegistryCard) so it reads identically to the MCP / Skills / Persona tabs; the
 * per-pack environment/tools/skills detail opens in a modal.
 */

import { useCallback, useEffect, useState } from 'react';
import { toast } from 'sonner';
import {
  Boxes, Trash2, Wrench, BookOpen, Camera, ScrollText, X, FolderGit2,
  TerminalSquare, Globe, Lock, Clock, Power,
} from 'lucide-react';
import {
  sandboxToolPacksApi,
  type SandboxToolPackSummary,
  type SandboxToolPackDetail,
} from '@/lib/api';
import { useI18n } from '@/lib/i18n';
import SnapshotLogView from '@/components/sandbox/SnapshotLogView';
import RegistryPageShell from '@/components/registry/RegistryPageShell';
import RegistryGrid from '@/components/registry/RegistryGrid';
import RegistryCard, {
  type RegistryCardBadge,
} from '@/components/registry/RegistryCard';
import RegistryActionButton from '@/components/registry/RegistryActionButton';
import RegistryEmptyState from '@/components/registry/RegistryEmptyState';

function Ref({ icon: Icon, label, value }: { icon: any; label: string; value?: string }) {
  return (
    <span className="inline-flex items-center gap-1 text-[0.6875rem] text-[hsl(var(--muted-foreground))]">
      <Icon size={11} /> {label} <span className="font-mono text-[hsl(var(--foreground))]">{value || '—'}</span>
    </span>
  );
}

export default function SandboxToolPacksManager() {
  const { t } = useI18n();
  const [packs, setPacks] = useState<SandboxToolPackSummary[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [detail, setDetail] = useState<Record<string, SandboxToolPackDetail>>({});
  const [busy, setBusy] = useState<string | null>(null);
  const [logPack, setLogPack] = useState<SandboxToolPackSummary | null>(null);
  const [detailPack, setDetailPack] = useState<SandboxToolPackSummary | null>(null);

  const refresh = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await sandboxToolPacksApi.list();
      setPacks(res.packs || []);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  }, []);

  useEffect(() => { void refresh(); }, [refresh]);

  const openDetail = async (p: SandboxToolPackSummary) => {
    setDetailPack(p);
    if (!detail[p.id]) {
      try {
        const d = await sandboxToolPacksApi.get(p.id);
        setDetail((prev) => ({ ...prev, [p.id]: d }));
      } catch (e) {
        toast.error(t('sandboxPacks.loadFailed', { error: e instanceof Error ? e.message : String(e) }));
      }
    }
  };

  const onToggleEnabled = async (p: SandboxToolPackSummary) => {
    setBusy(p.id);
    try {
      const updated = await sandboxToolPacksApi.setEnabled(p.id, !p.enabled);
      setPacks((prev) => prev.map((x) => (x.id === p.id ? { ...x, enabled: updated.enabled } : x)));
      toast.success(`${p.name} — ${updated.enabled ? t('sandboxPacks.enabled') : t('sandboxPacks.disabled')}`);
    } catch (e) {
      toast.error(t('sandboxPacks.failed', { error: e instanceof Error ? e.message : String(e) }));
    } finally {
      setBusy(null);
    }
  };

  const onDelete = async (p: SandboxToolPackSummary) => {
    if (!window.confirm(t('sandboxPacks.deleteConfirm', { name: p.name }))) return;
    setBusy(p.id);
    try {
      await sandboxToolPacksApi.remove(p.id);
      setPacks((prev) => prev.filter((x) => x.id !== p.id));
      toast.success(t('sandboxPacks.deleted', { name: p.name }));
    } catch (e) {
      toast.error(t('sandboxPacks.failed', { error: e instanceof Error ? e.message : String(e) }));
    } finally {
      setBusy(null);
    }
  };

  const d = detailPack ? detail[detailPack.id] : undefined;

  return (
    <RegistryPageShell
      title={t('sandboxPacks.title')}
      subtitle={t('sandboxPacks.subtitle')}
      icon={Boxes}
      countLabel={packs.length ? `${packs.length}개` : undefined}
      onRefresh={() => void refresh()}
      loading={loading}
      error={error}
      onDismissError={() => setError(null)}
    >
      {packs.length === 0 && !loading ? (
        <RegistryEmptyState
          icon={Boxes}
          title={t('sandboxPacks.empty.title')}
          hint={`${t('sandboxPacks.empty.desc')} · ${t('sandboxPacks.empty.warn')}`}
        />
      ) : (
        <RegistryGrid>
          {packs.map((p) => {
            const badges: RegistryCardBadge[] = [
              { label: p.enabled ? t('sandboxPacks.enabled') : t('sandboxPacks.disabled'), tone: p.enabled ? 'good' : 'neutral' },
              { label: `${p.tool_count}`, tone: 'neutral', icon: Wrench },
              { label: `${p.skill_count}`, tone: 'neutral', icon: BookOpen },
            ];
            return (
              <RegistryCard
                key={p.id}
                icon={Boxes}
                title={p.name}
                description={p.description}
                badges={badges}
                onClick={() => void openDetail(p)}
                actions={
                  <>
                    <RegistryActionButton
                      icon={Power}
                      title={p.enabled ? t('sandboxPacks.disableHint') : t('sandboxPacks.enableHint')}
                      variant={p.enabled ? 'primary' : 'default'}
                      alwaysVisible={p.enabled}
                      disabled={busy === p.id}
                      onClick={() => void onToggleEnabled(p)}
                    />
                    <RegistryActionButton icon={ScrollText} title={t('sandboxPacks.buildLog')} onClick={() => setLogPack(p)} />
                    <RegistryActionButton icon={Trash2} title={t('sandboxPacks.delete')} variant="danger" disabled={busy === p.id} onClick={() => void onDelete(p)} />
                  </>
                }
              />
            );
          })}
        </RegistryGrid>
      )}

      {/* Detail modal — environment refs + tools + skills */}
      {detailPack && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={() => setDetailPack(null)}>
          <div className="w-full max-w-2xl max-h-[85vh] overflow-hidden rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] flex flex-col" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between px-4 py-3 border-b border-[hsl(var(--border))]">
              <div className="flex items-center gap-2 min-w-0">
                <Boxes size={16} />
                <span className="font-semibold truncate">{detailPack.name}</span>
              </div>
              <button onClick={() => setDetailPack(null)} className="text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]"><X size={16} /></button>
            </div>
            <div className="p-4 overflow-y-auto text-[0.8125rem] space-y-3">
              <div>
                <div className="font-medium mb-1.5 flex items-center gap-1.5"><Camera size={12} /> {t('sandboxPacks.environment')}</div>
                <div className="flex flex-wrap items-center gap-x-4 gap-y-1 px-2.5 py-2 rounded-md bg-[hsl(var(--muted))]/50">
                  <Ref icon={FolderGit2} label={t('sandboxPacks.project')} value={detailPack.project_ref} />
                  <Ref icon={Boxes} label={t('sandboxPacks.workspace')} value={detailPack.workspace_ref} />
                  <Ref icon={Camera} label={t('sandboxPacks.snapshot')} value={detailPack.snapshot_ref} />
                </div>
              </div>
              {!d ? (
                <div className="text-[hsl(var(--muted-foreground))] animate-pulse">{t('sandboxPacks.loading')}</div>
              ) : (
                <>
                  {d.tools.length > 0 && (
                    <div>
                      <div className="font-medium mb-1 flex items-center gap-1.5"><Wrench size={12} /> {t('sandboxPacks.tools')}</div>
                      <div className="space-y-1.5">
                        {d.tools.map((tool) => (
                          <div key={tool.name} className="px-2.5 py-2 rounded-md bg-[hsl(var(--muted))]/50">
                            <div>
                              <span className="font-mono font-medium">{tool.name}</span>
                              <span className="text-[hsl(var(--muted-foreground))]"> — {tool.description || t('sandboxPacks.noDescription')}</span>
                            </div>
                            <div className="flex flex-wrap items-center gap-x-3 gap-y-0.5 mt-1 text-[0.6875rem] text-[hsl(var(--muted-foreground))]">
                              <span className="inline-flex items-center gap-1"><TerminalSquare size={11} /> {tool.runtime} <span className="font-mono">{tool.entrypoint}</span></span>
                              <span className="inline-flex items-center gap-1"><FolderGit2 size={11} /> {tool.workdir}</span>
                              <span className="inline-flex items-center gap-1"><Clock size={11} /> {tool.timeout_s}s</span>
                              <span className={`inline-flex items-center gap-1 ${tool.network_egress ? 'text-amber-500' : ''}`}><Globe size={11} /> {tool.network_egress ? t('sandboxPacks.egressOn') : t('sandboxPacks.egressOff')}</span>
                              {tool.read_only && <span className="inline-flex items-center gap-1"><Lock size={11} /> {t('sandboxPacks.readOnly')}</span>}
                            </div>
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                  {d.skills.length > 0 && (
                    <div>
                      <div className="font-medium mb-1 flex items-center gap-1.5"><BookOpen size={12} /> {t('sandboxPacks.skills')}</div>
                      <div className="space-y-1">
                        {d.skills.map((s) => (
                          <div key={s.id} className="px-2.5 py-1.5 rounded-md bg-[hsl(var(--muted))]/50">
                            <span className="font-mono font-medium">{s.id}</span>
                            <span className="text-[hsl(var(--muted-foreground))]"> — {s.description || t('sandboxPacks.noDescription')}</span>
                            {s.allowed_tools?.length > 0 && (
                              <div className="text-[0.6875rem] text-[hsl(var(--muted-foreground))] font-mono mt-0.5">→ {s.allowed_tools.join(', ')}</div>
                            )}
                          </div>
                        ))}
                      </div>
                    </div>
                  )}
                </>
              )}
            </div>
          </div>
        </div>
      )}

      {/* Build-log modal */}
      {logPack && (
        <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50 p-4" onClick={() => setLogPack(null)}>
          <div className="w-full max-w-3xl max-h-[85vh] overflow-hidden rounded-xl border border-[hsl(var(--border))] bg-[hsl(var(--card))] flex flex-col" onClick={(e) => e.stopPropagation()}>
            <div className="flex items-center justify-between px-4 py-3 border-b border-[hsl(var(--border))]">
              <div className="flex items-center gap-2 min-w-0">
                <ScrollText size={16} />
                <span className="font-medium truncate">{logPack.name} · {t('sandboxPacks.buildLogTitle')}</span>
              </div>
              <button onClick={() => setLogPack(null)} className="text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))]"><X size={16} /></button>
            </div>
            <div className="p-4 overflow-y-auto">
              <SnapshotLogView loadActivity={() => sandboxToolPacksApi.activity(logPack.id)} loadDiff={() => sandboxToolPacksApi.diff(logPack.id)} />
            </div>
          </div>
        </div>
      )}
    </RegistryPageShell>
  );
}
