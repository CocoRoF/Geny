'use client';

/**
 * Read-only admin viewer (G13).
 *
 * Three sections — permissions, hooks, skills — each pulling from
 * its respective endpoint. Pure read; operators still hand-edit
 * YAML files. The viewers are here so the operator can answer
 * "what's loaded?" without tailing logs.
 */

import { useEffect, useState } from 'react';
import {
  agentApi,
  adminTelemetryApi,
  subagentTypeApi,
  notificationsApi,
  RecentToolEvent,
  RecentPermissionDecision,
  SubagentTypeRow,
  SystemStatusResponse,
  ToolUsageRow,
  InProcessHookHandlerRow,
  SettingsMigrationStatusResponse,
  NotificationEndpointRow,
  SendMessageChannelRow,
} from '@/lib/api';
import { Shield, Plug, Sparkles, AlertCircle, RefreshCw, FileText, Activity, Lock, Users, Server, BarChart3, Cog, GitMerge, Bell, MessageSquare } from 'lucide-react';
import { TabShell, ActionButton } from '@/components/layout';

interface PermissionRow {
  tool_name: string;
  pattern: string | null;
  behavior: string;
  source: string;
  reason: string | null;
}

interface HookRow {
  event: string;
  command: string[];
  timeout_ms: number | null;
  tool_filter: string[];
}

interface SkillRow {
  id: string | null;
  name: string | null;
  description: string | null;
  allowed_tools: string[];
}

const BEHAVIOR_COLOR: Record<string, string> = {
  allow: 'var(--success-color)',
  deny: 'var(--danger-color)',
  ask: 'var(--warning-color)',
};

function Section({
  title,
  Icon,
  count,
  children,
  onReload,
}: {
  title: string;
  Icon: typeof Shield;
  count: number;
  children: React.ReactNode;
  onReload: () => void;
}) {
  return (
    <section className="border-b border-[var(--border-color)] py-3">
      <div className="px-3 flex items-center justify-between gap-2 mb-2">
        <h3 className="text-[0.6875rem] uppercase tracking-wider font-semibold text-[var(--text-muted)] flex items-center gap-1.5">
          <Icon size={11} className="text-[var(--primary-color)]" />
          {title}
          <span className="font-normal opacity-70">({count})</span>
        </h3>
        <button
          className="h-5 w-5 rounded text-[var(--text-muted)] hover:text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary)] flex items-center justify-center"
          onClick={onReload}
          title="Reload"
        >
          <RefreshCw size={10} />
        </button>
      </div>
      {children}
    </section>
  );
}

function formatTime(ts: number): string {
  try {
    return new Date(ts * 1000).toLocaleTimeString('en-GB', {
      hour: '2-digit',
      minute: '2-digit',
      second: '2-digit',
    });
  } catch {
    return String(ts);
  }
}

export default function AdminPanel() {
  const [perms, setPerms] = useState<{ mode: string; rules: PermissionRow[]; sources: string[] } | null>(null);
  const [hooks, setHooks] = useState<{ enabled: boolean; env: boolean; path: string; entries: HookRow[] } | null>(null);
  const [skills, setSkills] = useState<SkillRow[]>([]);
  // PR-E.4.4 — recent activity rings.
  const [recentTools, setRecentTools] = useState<RecentToolEvent[]>([]);
  const [recentPerms, setRecentPerms] = useState<RecentPermissionDecision[]>([]);
  // PR-F.3.4 — Subagent types panel.
  const [subagentTypes, setSubagentTypes] = useState<SubagentTypeRow[]>([]);
  // PR-F.6.2 — System status snapshot.
  const [systemStatus, setSystemStatus] = useState<SystemStatusResponse | null>(null);
  // Cycle G — usage / handlers / migration.
  const [toolUsage, setToolUsage] = useState<ToolUsageRow[]>([]);
  const [inProcHandlers, setInProcHandlers] = useState<InProcessHookHandlerRow[]>([]);
  const [migration, setMigration] = useState<SettingsMigrationStatusResponse | null>(null);
  // Cycle G — notifications.
  const [endpoints, setEndpoints] = useState<NotificationEndpointRow[]>([]);
  const [channels, setChannels] = useState<SendMessageChannelRow[]>([]);
  const [error, setError] = useState<string | null>(null);

  const loadAll = () => {
    setError(null);
    agentApi.permissionsList()
      .then((r) => setPerms({ mode: r.mode, rules: r.rules, sources: r.sources_consulted }))
      .catch((e) => setError((p) => p ?? `permissions: ${e.message}`));
    agentApi.hooksList()
      .then((r) => setHooks({ enabled: r.enabled, env: r.env_opt_in, path: r.config_path, entries: r.entries }))
      .catch((e) => setError((p) => p ?? `hooks: ${e.message}`));
    agentApi.skillsList()
      .then((r) => setSkills(r.skills))
      .catch((e) => setError((p) => p ?? `skills: ${e.message}`));
    adminTelemetryApi.recentToolEvents(50)
      .then((r) => setRecentTools(r.events))
      .catch((e) => setError((p) => p ?? `recent tool events: ${e.message}`));
    adminTelemetryApi.recentPermissions(50)
      .then((r) => setRecentPerms(r.decisions))
      .catch((e) => setError((p) => p ?? `recent permissions: ${e.message}`));
    subagentTypeApi.list()
      .then((r) => setSubagentTypes(r.types))
      .catch((e) => setError((p) => p ?? `subagent types: ${e.message}`));
    adminTelemetryApi.systemStatus()
      .then(setSystemStatus)
      .catch((e) => setError((p) => p ?? `system status: ${e.message}`));
    adminTelemetryApi.toolUsage()
      .then((r) => setToolUsage(r.counts))
      .catch((e) => setError((p) => p ?? `tool usage: ${e.message}`));
    adminTelemetryApi.hookInProcessHandlers()
      .then((r) => setInProcHandlers(r.handlers))
      .catch((e) => setError((p) => p ?? `in-process handlers: ${e.message}`));
    adminTelemetryApi.settingsMigrationStatus()
      .then(setMigration)
      .catch((e) => setError((p) => p ?? `migration status: ${e.message}`));
    notificationsApi.listEndpoints()
      .then((r) => setEndpoints(r.endpoints))
      .catch((e) => setError((p) => p ?? `notification endpoints: ${e.message}`));
    notificationsApi.listChannels()
      .then((r) => setChannels(r.channels))
      .catch((e) => setError((p) => p ?? `send-message channels: ${e.message}`));
  };

  useEffect(() => {
    loadAll();
    // PR-E.4.4 — auto-refresh activity rings every 5s.
    const id = window.setInterval(() => {
      adminTelemetryApi.recentToolEvents(50).then((r) => setRecentTools(r.events)).catch(() => {});
      adminTelemetryApi.recentPermissions(50).then((r) => setRecentPerms(r.decisions)).catch(() => {});
    }, 5000);
    return () => window.clearInterval(id);
  }, []);

  return (
    <TabShell
      title="Admin"
      icon={Server}
      subtitle="Read-only viewer for permissions / hooks / skills / runtime telemetry."
      actions={
        <ActionButton icon={RefreshCw} onClick={loadAll}>Refresh all</ActionButton>
      }
      error={error}
      onDismissError={() => setError(null)}
    >
      <div className="h-full overflow-auto">

      {/* ── System Status (PR-F.6.2) ── */}
      <Section
        title="System status"
        Icon={Server}
        count={systemStatus?.subsystems.filter((s) => s.present).length ?? 0}
        onReload={loadAll}
      >
        <div className="px-3 text-[0.6875rem]">
          {!systemStatus ? (
            <div className="text-[var(--text-muted)] py-2">Loading…</div>
          ) : (
            <>
              <div className="grid grid-cols-2 gap-1 mb-2">
                {systemStatus.subsystems.map((s) => (
                  <div
                    key={s.name}
                    className="flex items-center gap-1.5 truncate"
                    title={s.detail ?? ''}
                  >
                    <span
                      className={`w-1.5 h-1.5 rounded-full shrink-0 ${
                        s.present ? 'bg-[var(--success-color)]' : 'bg-[var(--text-muted)]'
                      }`}
                    />
                    <span className={s.present ? '' : 'text-[var(--text-muted)]'}>{s.name}</span>
                  </div>
                ))}
              </div>
              {systemStatus.cron && (
                <div className="text-[var(--text-muted)] mb-1">
                  cron: {systemStatus.cron.running ? 'running' : 'stopped'}
                  {systemStatus.cron.cycle_seconds != null && (
                    <> · cycle {systemStatus.cron.cycle_seconds}s</>
                  )}
                  {systemStatus.cron.jobs != null && <> · {systemStatus.cron.jobs} jobs</>}
                </div>
              )}
              {systemStatus.task_runner && (
                <div className="text-[var(--text-muted)]">
                  task_runner: {systemStatus.task_runner.running ? 'running' : 'stopped'}
                  {systemStatus.task_runner.in_flight != null && (
                    <> · in-flight {systemStatus.task_runner.in_flight}</>
                  )}
                  {systemStatus.task_runner.max_concurrency != null && (
                    <> / max {systemStatus.task_runner.max_concurrency}</>
                  )}
                </div>
              )}
            </>
          )}
        </div>
      </Section>

      {/* ── Tool usage counts (Cycle G) ── */}
      <Section
        title="Tool usage"
        Icon={BarChart3}
        count={toolUsage.length}
        onReload={loadAll}
      >
        <div className="px-3">
          {toolUsage.length === 0 ? (
            <div className="text-[0.6875rem] text-[var(--text-muted)] italic py-2">
              No tool calls in the recent ring.
            </div>
          ) : (
            <table className="w-full text-[0.6875rem]">
              <thead>
                <tr className="text-[var(--text-muted)] border-b border-[var(--border-color)]">
                  <th className="text-left py-1">Tool</th>
                  <th className="text-right py-1 px-2">Calls</th>
                  <th className="text-right py-1 px-2">Errors</th>
                  <th className="text-right py-1 px-2">Total ms</th>
                </tr>
              </thead>
              <tbody>
                {toolUsage.map((row) => (
                  <tr key={row.tool_name} className="border-b border-[var(--border-color)]">
                    <td className="py-1 font-mono">{row.tool_name}</td>
                    <td className="py-1 px-2 text-right font-mono">{row.calls}</td>
                    <td className="py-1 px-2 text-right font-mono">{row.errors}</td>
                    <td className="py-1 px-2 text-right font-mono">{row.total_duration_ms}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </div>
      </Section>

      {/* ── In-process hook handlers (Cycle G) ── */}
      <Section
        title="In-process hook handlers"
        Icon={Cog}
        count={inProcHandlers.length}
        onReload={loadAll}
      >
        <div className="px-3 text-[0.6875rem]">
          {inProcHandlers.length === 0 ? (
            <div className="text-[var(--text-muted)] italic py-2">
              No in-process handlers registered.
            </div>
          ) : (
            <ul className="space-y-0.5">
              {inProcHandlers.map((h) => (
                <li key={h.event} className="flex items-center justify-between">
                  <span className="font-mono">{h.event}</span>
                  <span className="text-[var(--text-muted)]">{h.handler_count}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </Section>

      {/* ── Settings migration status (Cycle G) ── */}
      <Section
        title="Settings migration"
        Icon={GitMerge}
        count={(migration?.legacy_files_present.length ?? 0)}
        onReload={loadAll}
      >
        <div className="px-3 text-[0.6875rem] space-y-1">
          {!migration ? (
            <div className="text-[var(--text-muted)]">Loading…</div>
          ) : (
            <>
              <div>
                settings.json:{' '}
                <span className="font-mono">{migration.settings_json_path}</span>{' '}
                {migration.settings_json_exists ? (
                  <span className="text-[var(--success-color)]">exists</span>
                ) : (
                  <span className="text-[var(--text-muted)]">missing</span>
                )}
              </div>
              {migration.settings_json_sections.length > 0 && (
                <div>
                  sections:{' '}
                  <span className="font-mono">{migration.settings_json_sections.join(', ')}</span>
                </div>
              )}
              {migration.legacy_files_present.length > 0 && (
                <div className="text-[var(--warning-color)]">
                  Legacy YAML still present:
                  <ul className="ml-3 mt-0.5 list-disc font-mono">
                    {migration.legacy_files_present.map((p) => <li key={p}>{p}</li>)}
                  </ul>
                </div>
              )}
              {migration.notes.map((n, i) => (
                <div key={i} className="italic text-[var(--text-muted)]">{n}</div>
              ))}
            </>
          )}
        </div>
      </Section>

      {/* ── Recent Activity (PR-E.4.4) ── */}
      <Section title="Recent activity" Icon={Activity} count={recentTools.length} onReload={loadAll}>
        <div className="px-3">
          {recentTools.length === 0 ? (
            <div className="text-[0.6875rem] text-[var(--text-muted)] italic py-2">
              No tool calls yet — start a session and run a tool.
            </div>
          ) : (
            <ul className="flex flex-col gap-0.5 max-h-48 overflow-y-auto">
              {recentTools.slice().reverse().map((ev, i) => (
                <li
                  key={i}
                  className="px-2 py-1 rounded text-[0.6875rem] flex items-center gap-2 hover:bg-[var(--bg-tertiary)]"
                >
                  <span className="text-[0.5625rem] text-[var(--text-muted)] font-mono shrink-0 w-16">
                    {formatTime(ev.ts)}
                  </span>
                  <span
                    className="text-[0.5625rem] uppercase tracking-wider px-1 rounded shrink-0"
                    style={{
                      background: ev.kind === 'start'
                        ? 'rgba(59,130,246,0.10)'
                        : ev.is_error
                          ? 'rgba(239,68,68,0.10)'
                          : 'rgba(16,185,129,0.10)',
                      color: ev.kind === 'start'
                        ? 'var(--primary-color)'
                        : ev.is_error ? 'var(--danger-color)' : 'var(--success-color)',
                    }}
                  >
                    {ev.kind}
                  </span>
                  <span className="font-mono truncate flex-1">{ev.tool_name}</span>
                  {ev.duration_ms != null && (
                    <span className="text-[0.5625rem] text-[var(--text-muted)] shrink-0">
                      {ev.duration_ms}ms
                    </span>
                  )}
                  {ev.session_id && (
                    <span
                      className="text-[0.5625rem] text-[var(--text-muted)] font-mono shrink-0 truncate max-w-[80px]"
                      title={ev.session_id}
                    >
                      {ev.session_id.slice(0, 8)}
                    </span>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      </Section>

      {/* ── Permission Activity (PR-E.4.4) ── */}
      <Section title="Permission activity" Icon={Lock} count={recentPerms.length} onReload={loadAll}>
        <div className="px-3">
          {recentPerms.length === 0 ? (
            <div className="text-[0.6875rem] text-[var(--text-muted)] italic py-2">
              No permission decisions captured yet.
            </div>
          ) : (
            <ul className="flex flex-col gap-0.5 max-h-48 overflow-y-auto">
              {recentPerms.slice().reverse().map((d, i) => {
                const color = d.decision === 'allow'
                  ? 'var(--success-color)'
                  : 'var(--danger-color)';
                return (
                  <li
                    key={i}
                    className="px-2 py-1 rounded text-[0.6875rem] hover:bg-[var(--bg-tertiary)]"
                  >
                    <div className="flex items-center gap-2">
                      <span className="text-[0.5625rem] text-[var(--text-muted)] font-mono shrink-0 w-16">
                        {formatTime(d.ts)}
                      </span>
                      <span
                        className="text-[0.5625rem] uppercase tracking-wider px-1 rounded shrink-0"
                        style={{ background: 'rgba(239,68,68,0.10)', color }}
                      >
                        {d.decision}
                      </span>
                      <span className="font-mono truncate flex-1">{d.tool_name ?? '*'}</span>
                    </div>
                    {d.message && (
                      <div className="text-[var(--text-muted)] mt-0.5 pl-[72px] truncate">
                        {d.message}
                      </div>
                    )}
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </Section>

      {/* ── Subagent Types (PR-F.3.4) ── */}
      <Section title="Subagent types" Icon={Users} count={subagentTypes.length} onReload={loadAll}>
        <div className="px-3">
          {subagentTypes.length === 0 ? (
            <div className="text-[0.6875rem] text-[var(--text-muted)] italic py-2">
              No subagent types registered.
            </div>
          ) : (
            <ul className="flex flex-col gap-1">
              {subagentTypes.map((t) => (
                <li
                  key={t.agent_type}
                  className="px-2 py-1.5 rounded border border-[var(--border-color)] bg-[var(--bg-secondary)] text-[0.6875rem]"
                >
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-[var(--primary-color)]">{t.agent_type}</span>
                    {t.allowed_tools.length > 0 && (
                      <span className="text-[var(--text-muted)] opacity-70">
                        {t.allowed_tools.length} tool{t.allowed_tools.length === 1 ? '' : 's'}
                      </span>
                    )}
                  </div>
                  {t.description && (
                    <div className="text-[var(--text-secondary)] mt-0.5">{t.description}</div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      </Section>

      {/* ── Notification endpoints (Cycle G) ── */}
      <Section title="Notification endpoints" Icon={Bell} count={endpoints.length} onReload={loadAll}>
        <div className="px-3 text-[0.6875rem]">
          {endpoints.length === 0 ? (
            <div className="text-[var(--text-muted)] italic py-2">
              None registered. Drop entries in <span className="font-mono">~/.geny/notifications.json</span> or set <span className="font-mono">NOTIFICATION_ENDPOINTS</span>.
            </div>
          ) : (
            <ul className="space-y-1">
              {endpoints.map((e) => (
                <li key={e.name} className="px-2 py-1.5 rounded border border-[var(--border-color)] bg-[var(--bg-secondary)]">
                  <div className="flex items-center gap-2">
                    <span className="font-mono">{e.name}</span>
                    {e.type && <span className="text-[var(--text-muted)] text-[0.5625rem] uppercase">{e.type}</span>}
                    {!e.enabled && <span className="text-[var(--warning-color)]">disabled</span>}
                  </div>
                  {e.target && <div className="text-[var(--text-secondary)] truncate">{e.target}</div>}
                </li>
              ))}
            </ul>
          )}
        </div>
      </Section>

      {/* ── SendMessage channels (Cycle G) ── */}
      <Section title="SendMessage channels" Icon={MessageSquare} count={channels.length} onReload={loadAll}>
        <div className="px-3 text-[0.6875rem]">
          {channels.length === 0 ? (
            <div className="text-[var(--text-muted)] italic py-2">
              None registered.
            </div>
          ) : (
            <ul className="space-y-0.5">
              {channels.map((c) => (
                <li key={c.name} className="flex items-center justify-between">
                  <span className="font-mono">{c.name}</span>
                  <span className="text-[var(--text-muted)] text-[0.6875rem]">{c.impl ?? '?'}</span>
                </li>
              ))}
            </ul>
          )}
        </div>
      </Section>

      {/* ── Permissions ── */}
      <Section title="Permission rules" Icon={Shield} count={perms?.rules.length ?? 0} onReload={loadAll}>
        <div className="px-3">
          {perms ? (
            <>
              <div className="text-[0.625rem] text-[var(--text-muted)] mb-2">
                mode: <span style={{ color: 'var(--text-secondary)' }}>{perms.mode}</span>
                {perms.sources.length > 0 && (
                  <> · sources: {perms.sources.length} candidate path(s)</>
                )}
              </div>
              {perms.rules.length === 0 ? (
                <div className="text-[0.6875rem] text-[var(--text-muted)] italic py-2">
                  No permission rules loaded. Drop YAML at one of the candidate paths.
                </div>
              ) : (
                <ul className="flex flex-col gap-1">
                  {perms.rules.map((r, i) => (
                    <li
                      key={i}
                      className="px-2 py-1.5 rounded border border-[var(--border-color)] bg-[var(--bg-secondary)] flex items-start gap-2 text-[0.6875rem]"
                    >
                      <span
                        className="px-1.5 py-[1px] rounded text-[0.5625rem] font-bold uppercase tracking-wider shrink-0"
                        style={{ color: BEHAVIOR_COLOR[r.behavior.toLowerCase()] ?? 'var(--text-secondary)' }}
                      >
                        {r.behavior}
                      </span>
                      <div className="min-w-0 flex-1">
                        <div className="font-mono text-[var(--text-primary)] truncate">
                          {r.tool_name}{r.pattern ? `(${r.pattern})` : ''}
                        </div>
                        {r.reason && (
                          <div className="text-[var(--text-muted)] mt-0.5">{r.reason}</div>
                        )}
                      </div>
                      <span className="text-[0.5625rem] uppercase tracking-wider text-[var(--text-muted)] opacity-70 shrink-0">
                        {r.source}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
              {perms.sources.length > 0 && (
                <details className="mt-2 text-[0.625rem] text-[var(--text-muted)]">
                  <summary className="cursor-pointer hover:text-[var(--text-secondary)]">
                    Sources consulted
                  </summary>
                  <ul className="mt-1 pl-3 flex flex-col gap-0.5 font-mono">
                    {perms.sources.map((p) => <li key={p}>{p}</li>)}
                  </ul>
                </details>
              )}
            </>
          ) : (
            <div className="text-[0.6875rem] text-[var(--text-muted)] py-2">Loading…</div>
          )}
        </div>
      </Section>

      {/* ── Hooks ── */}
      <Section title="Hooks" Icon={Plug} count={hooks?.entries.length ?? 0} onReload={loadAll}>
        <div className="px-3">
          {hooks ? (
            <>
              <div className="text-[0.625rem] text-[var(--text-muted)] mb-2 flex flex-wrap items-center gap-2">
                <span>
                  active:{' '}
                  <span style={{ color: hooks.enabled && hooks.env ? 'var(--success-color)' : 'var(--text-muted)' }}>
                    {hooks.enabled && hooks.env ? 'YES' : 'no'}
                  </span>
                </span>
                <span>· env GENY_ALLOW_HOOKS: <span>{hooks.env ? '1' : 'unset'}</span></span>
                <span>· yaml enabled: <span>{hooks.enabled ? 'true' : 'false'}</span></span>
              </div>
              <div className="text-[0.5625rem] font-mono text-[var(--text-muted)] mb-2 flex items-center gap-1">
                <FileText size={9} /> {hooks.path}
              </div>
              {hooks.entries.length === 0 ? (
                <div className="text-[0.6875rem] text-[var(--text-muted)] italic py-2">
                  No hook entries configured.
                </div>
              ) : (
                <ul className="flex flex-col gap-1">
                  {hooks.entries.map((h, i) => (
                    <li
                      key={i}
                      className="px-2 py-1.5 rounded border border-[var(--border-color)] bg-[var(--bg-secondary)] text-[0.6875rem]"
                    >
                      <div className="flex items-center gap-2">
                        <span className="font-mono text-[var(--primary-color)] uppercase tracking-wider text-[0.5625rem]">
                          {h.event}
                        </span>
                        {h.timeout_ms != null && (
                          <span className="text-[var(--text-muted)] opacity-70">
                            timeout {h.timeout_ms}ms
                          </span>
                        )}
                        {h.tool_filter.length > 0 && (
                          <span className="text-[var(--text-muted)] opacity-70">
                            tools: {h.tool_filter.join(',')}
                          </span>
                        )}
                      </div>
                      <div className="font-mono text-[var(--text-secondary)] mt-0.5 truncate">
                        $ {h.command.join(' ')}
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </>
          ) : (
            <div className="text-[0.6875rem] text-[var(--text-muted)] py-2">Loading…</div>
          )}
        </div>
      </Section>

      {/* ── Skills ── */}
      <Section title="Skills" Icon={Sparkles} count={skills.length} onReload={loadAll}>
        <div className="px-3">
          {skills.length === 0 ? (
            <div className="text-[0.6875rem] text-[var(--text-muted)] italic py-2">
              No skills loaded.
            </div>
          ) : (
            <ul className="flex flex-col gap-1">
              {skills.map((s, idx) => (
                <li
                  key={s.id ?? `admin-skill-${idx}`}
                  className="px-2 py-1.5 rounded border border-[var(--border-color)] bg-[var(--bg-secondary)] text-[0.6875rem]"
                >
                  <div className="flex items-center gap-2">
                    <span className="font-mono text-[var(--primary-color)]">/{s.id}</span>
                    {s.allowed_tools.length > 0 && (
                      <span className="text-[var(--text-muted)] opacity-70">
                        {s.allowed_tools.length} tool{s.allowed_tools.length === 1 ? '' : 's'}
                      </span>
                    )}
                  </div>
                  {s.description && (
                    <div className="text-[var(--text-secondary)] mt-0.5">{s.description}</div>
                  )}
                </li>
              ))}
            </ul>
          )}
        </div>
      </Section>
      </div>
    </TabShell>
  );
}
