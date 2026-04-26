'use client';

/**
 * ReloadRuntimeButton — E.1 (cycle 20260426_1).
 *
 * Pushes a between-turn refresh of permissions / hooks (or both) into
 * every active AgentSession. Backend queues the refresh on each
 * session; the next ``invoke`` / ``astream`` drains the queue and
 * swaps slot strategies via the executor's stage-slot setters.
 *
 * Visible only in the global Library tab — operator-scoped action.
 * Sessions currently executing finish on the pre-refresh runtime;
 * the next turn picks up the new state.
 */

import { useState } from 'react';
import { RefreshCw, ChevronDown, Check } from 'lucide-react';
import { toast } from 'sonner';
import { adminTelemetryApi } from '@/lib/api';

const SCOPES: Array<{ value: 'permissions' | 'hooks' | 'all'; label: string }> = [
  { value: 'all', label: 'All (permissions + hooks)' },
  { value: 'permissions', label: 'Permissions only' },
  { value: 'hooks', label: 'Hooks only' },
];

export function ReloadRuntimeButton() {
  const [busy, setBusy] = useState(false);
  const [open, setOpen] = useState(false);

  const send = async (scope: 'permissions' | 'hooks' | 'all') => {
    setBusy(true);
    setOpen(false);
    try {
      const res = await adminTelemetryApi.reloadRuntime(scope);
      if (res.queued_count === 0) {
        toast.info('No active sessions to refresh.', {
          description: res.skipped_session_ids.length
            ? `${res.skipped_session_ids.length} session(s) were not initialized yet.`
            : undefined,
        });
        return;
      }
      toast.success(
        `Queued runtime refresh on ${res.queued_count} session(s).`,
        {
          description:
            'Applies at each session\'s next turn. Currently-executing turns finish on the pre-refresh runtime.',
          duration: 6000,
        },
      );
    } catch (e) {
      const msg = e instanceof Error ? e.message : String(e);
      toast.error('Reload failed', { description: msg });
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="relative inline-flex">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        disabled={busy}
        className="inline-flex items-center gap-1.5 px-2.5 py-1 text-[0.6875rem] font-medium rounded-md border border-[var(--border-color)] bg-[hsl(var(--card))] text-[hsl(var(--foreground))] hover:bg-[hsl(var(--accent))] disabled:opacity-50 transition-colors"
        title="Push permission / hook changes into active sessions (between-turn)"
      >
        <RefreshCw size={11} className={busy ? 'animate-spin' : ''} />
        <span>Reload runtime</span>
        <ChevronDown size={11} />
      </button>
      {open && !busy && (
        <div
          role="menu"
          className="absolute right-0 top-[calc(100%+4px)] z-50 min-w-[180px] rounded-md border border-[var(--border-color)] bg-[hsl(var(--popover))] shadow-md py-1"
        >
          {SCOPES.map((s) => (
            <button
              key={s.value}
              type="button"
              role="menuitem"
              onClick={() => send(s.value)}
              className="w-full text-left px-2.5 py-1.5 text-[0.75rem] hover:bg-[hsl(var(--accent))] flex items-center gap-1.5"
            >
              <Check size={10} className="opacity-0" />
              {s.label}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}

export default ReloadRuntimeButton;
