'use client';

/**
 * IntegrationHealthCard — C.2 (cycle 20260426_1).
 *
 * Renders the wiring snapshot from `GET /api/admin/integration-health`
 * as a grid of pill badges. Each badge answers one independently
 * verifiable question that the post-D4 audit found invisible to
 * operators.
 *
 * The badges intentionally read like questions ("Settings.json found?",
 * "Hooks env gate open?") rather than sub-system names; the goal is
 * "did the bridge wire correctly?" not a generic system inventory
 * (that's what the existing System Status card is for).
 */

import { useEffect, useState } from 'react';
import { ShieldCheck, Activity, RefreshCw, AlertTriangle } from 'lucide-react';
import {
  adminTelemetryApi,
  type IntegrationHealthResponse,
  type RingFill,
} from '@/lib/api';
import { StatusBadge, type BadgeTone } from '@/components/layout';

/** Map a binary "is wired" check to a tone + label. */
function boolBadge(ok: boolean, label: string): { tone: BadgeTone; text: string } {
  return { tone: ok ? 'success' : 'danger', text: `${label}: ${ok ? 'yes' : 'no'}` };
}

/** Ring fill: green when non-empty, amber when 0 (likely "call site missing"
 * — but the operator hasn't done anything yet either, so amber not red). */
function ringBadge(name: string, ring: RingFill): { tone: BadgeTone; text: string } {
  const tone: BadgeTone = ring.filled > 0 ? 'success' : 'warning';
  return {
    tone,
    text: `${name}: ${ring.filled}/${ring.capacity}`,
  };
}

export function IntegrationHealthCard() {
  const [data, setData] = useState<IntegrationHealthResponse | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  const reload = () => {
    setLoading(true);
    setError(null);
    adminTelemetryApi
      .integrationHealth()
      .then(setData)
      .catch((e: Error) => setError(e.message))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    reload();
  }, []);

  return (
    <section className="border-b border-[hsl(var(--border))] py-3">
      <div className="px-3 flex items-center justify-between gap-2 mb-2">
        <h3 className="text-[0.6875rem] uppercase tracking-wider font-semibold text-[hsl(var(--muted-foreground))] flex items-center gap-1.5">
          <ShieldCheck size={11} className="text-[hsl(var(--primary))]" />
          Integration Health
          <span className="font-normal opacity-70">(wiring snapshot)</span>
        </h3>
        <button
          className="h-5 w-5 rounded text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))] hover:bg-[hsl(var(--accent))] flex items-center justify-center transition-colors"
          onClick={reload}
          title="Reload"
          disabled={loading}
        >
          <RefreshCw size={10} className={loading ? 'animate-spin' : ''} />
        </button>
      </div>

      {error && (
        <div className="px-3 text-[0.6875rem] text-[hsl(var(--danger))] flex items-center gap-1.5 py-1">
          <AlertTriangle size={11} />
          {error}
        </div>
      )}

      {!data && !error && (
        <div className="px-3 text-[0.6875rem] text-[hsl(var(--muted-foreground))] py-2">
          Loading…
        </div>
      )}

      {data && (
        <div className="px-3 flex flex-col gap-2">
          {/* Bool checks row */}
          <div className="flex flex-wrap gap-1.5">
            {[
              boolBadge(data.settings_exists, 'settings.json found'),
              boolBadge(data.hooks_env_gate, 'hooks env gate open'),
              boolBadge(data.task_runner_running, 'task_runner running'),
              {
                tone: data.hooks_yaml_legacy_present ? 'warning' : 'neutral',
                text: data.hooks_yaml_legacy_present
                  ? 'legacy hooks.yaml present'
                  : 'no legacy hooks.yaml',
              } as { tone: BadgeTone; text: string },
            ].map((b) => (
              <StatusBadge key={b.text} tone={b.tone} title={b.text}>
                {b.text}
              </StatusBadge>
            ))}
          </div>

          {/* Telemetry rings */}
          <div className="flex flex-wrap gap-1.5">
            <Activity size={11} className="text-[hsl(var(--muted-foreground))] mt-1" />
            {[
              ringBadge('tool events', data.tool_event_ring),
              ringBadge('permission decisions', data.permission_ring),
              ringBadge('cron fires', data.cron_history),
            ].map((b) => (
              <StatusBadge key={b.text} tone={b.tone} title={b.text}>
                {b.text}
              </StatusBadge>
            ))}
          </div>

          {/* Settings path */}
          <div className="text-[0.6875rem] text-[hsl(var(--muted-foreground))]">
            settings.json: <code>{data.settings_path}</code>
          </div>

          {/* Operator notes */}
          {data.notes.length > 0 && (
            <ul className="text-[0.6875rem] text-[hsl(var(--muted-foreground))] list-disc pl-4 space-y-0.5">
              {data.notes.map((note, idx) => (
                <li key={idx}>{note}</li>
              ))}
            </ul>
          )}
        </div>
      )}
    </section>
  );
}

export default IntegrationHealthCard;
