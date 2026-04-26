'use client';

/**
 * Per-session MCP server admin panel (G8.3).
 *
 * Lists every server attached to the session's pipeline with its
 * current FSM state (PENDING / CONNECTED / FAILED / NEEDS_AUTH /
 * DISABLED). Buttons to disable / enable / test / disconnect each
 * server, plus an "Add server" form for runtime additions.
 *
 * Pulled into SessionToolsTab (or any container that knows the
 * session id) — this component is just the panel chrome.
 */

import { useCallback, useEffect, useState } from 'react';
import { agentApi } from '@/lib/api';
import {
  Plug, PlugZap, AlertTriangle, ShieldOff, Loader2, Plus, X, RefreshCw,
} from 'lucide-react';

interface ServerRow {
  name: string;
  state: string;
  last_error: string | null;
}

interface Props {
  sessionId: string;
}

const STATE_VISUAL: Record<string, { color: string; Icon: typeof Plug; label: string }> = {
  connected: { color: 'var(--success-color)', Icon: PlugZap, label: 'Connected' },
  pending: { color: 'var(--warning-color)', Icon: Loader2, label: 'Pending' },
  failed: { color: 'var(--danger-color)', Icon: AlertTriangle, label: 'Failed' },
  needs_auth: { color: 'var(--warning-color)', Icon: AlertTriangle, label: 'Needs auth' },
  disabled: { color: 'var(--text-muted)', Icon: ShieldOff, label: 'Disabled' },
};

function visualFor(state: string) {
  return STATE_VISUAL[state.toLowerCase()] ?? {
    color: 'var(--text-muted)', Icon: Plug, label: state || 'unknown',
  };
}

export default function MCPAdminPanel({ sessionId }: Props) {
  const [servers, setServers] = useState<ServerRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState<string | null>(null);
  const [showAdd, setShowAdd] = useState(false);
  const [addName, setAddName] = useState('');
  const [addConfig, setAddConfig] = useState('{\n  "command": "echo",\n  "args": []\n}');

  const reload = useCallback(async () => {
    setLoading(true);
    setError(null);
    try {
      const resp = await agentApi.mcpServersList(sessionId);
      setServers(resp.servers);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [sessionId]);

  useEffect(() => {
    reload();
  }, [reload]);

  const action = useCallback(
    async (op: 'disable' | 'enable' | 'test' | 'disconnect', name: string) => {
      setBusy(`${op}:${name}`);
      setError(null);
      try {
        if (op === 'disconnect') {
          await agentApi.mcpServerDisconnect(sessionId, name);
        } else {
          await agentApi.mcpServerControl(sessionId, name, op);
        }
        await reload();
      } catch (err) {
        setError(err instanceof Error ? err.message : String(err));
      } finally {
        setBusy(null);
      }
    },
    [sessionId, reload],
  );

  const handleAdd = useCallback(async () => {
    if (!addName.trim()) {
      setError('Name is required');
      return;
    }
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(addConfig);
    } catch (err) {
      setError(`Config JSON parse error: ${err instanceof Error ? err.message : String(err)}`);
      return;
    }
    setBusy(`add:${addName}`);
    setError(null);
    try {
      await agentApi.mcpServerAdd(sessionId, addName.trim(), parsed);
      setShowAdd(false);
      setAddName('');
      await reload();
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setBusy(null);
    }
  }, [sessionId, addName, addConfig, reload]);

  return (
    <div className="flex flex-col gap-2 p-3">
      <div className="flex items-center justify-between gap-2">
        <h3 className="text-[0.75rem] font-semibold text-[var(--text-secondary)] uppercase tracking-wider flex items-center gap-1.5">
          <Plug size={12} className="text-[var(--primary-color)]" />
          MCP servers
          <span className="text-[0.625rem] font-normal text-[var(--text-muted)]">
            ({servers.length})
          </span>
        </h3>
        <div className="flex items-center gap-1">
          <button
            className="h-6 w-6 rounded-md text-[var(--text-muted)] hover:text-[var(--text-secondary)] hover:bg-[var(--bg-tertiary)] flex items-center justify-center"
            onClick={reload}
            title="Reload"
            disabled={loading}
          >
            <RefreshCw size={11} className={loading ? 'animate-spin' : ''} />
          </button>
          <button
            className="h-6 px-2 rounded-md bg-[var(--primary-color)] hover:bg-[var(--primary-hover)] text-white text-[0.625rem] font-semibold flex items-center gap-1"
            onClick={() => setShowAdd((v) => !v)}
          >
            <Plus size={10} />
            Add
          </button>
        </div>
      </div>

      {error && (
        <div className="text-[0.6875rem] text-[var(--danger-color)] bg-[rgba(239,68,68,0.08)] border border-[rgba(239,68,68,0.2)] rounded-md px-2 py-1.5">
          {error}
        </div>
      )}

      {showAdd && (
        <div className="border border-[var(--border-color)] rounded-md p-2.5 bg-[var(--bg-tertiary)] flex flex-col gap-2">
          <input
            type="text"
            placeholder="server name"
            value={addName}
            onChange={(e) => setAddName(e.target.value)}
            className="bg-[var(--bg-primary)] border border-[var(--border-color)] rounded px-2 py-1 text-[0.75rem] text-[var(--text-primary)] outline-none focus:border-[var(--primary-color)]"
          />
          <textarea
            value={addConfig}
            onChange={(e) => setAddConfig(e.target.value)}
            rows={4}
            className="bg-[var(--bg-primary)] border border-[var(--border-color)] rounded px-2 py-1 text-[0.6875rem] font-mono text-[var(--text-primary)] outline-none focus:border-[var(--primary-color)] resize-none"
          />
          <div className="flex justify-end gap-2">
            <button
              className="px-3 py-1 text-[0.6875rem] text-[var(--text-muted)] hover:text-[var(--text-secondary)]"
              onClick={() => setShowAdd(false)}
            >
              Cancel
            </button>
            <button
              className="px-3 py-1 bg-[var(--primary-color)] hover:bg-[var(--primary-hover)] text-white text-[0.6875rem] rounded font-semibold disabled:opacity-50"
              onClick={handleAdd}
              disabled={busy !== null}
            >
              {busy?.startsWith('add:') ? 'Adding…' : 'Connect'}
            </button>
          </div>
        </div>
      )}

      {servers.length === 0 && !loading && !error && (
        <div className="text-[0.6875rem] text-[var(--text-muted)] py-3 text-center">
          No MCP servers attached to this session.
        </div>
      )}

      <ul className="flex flex-col gap-1">
        {servers.map((srv) => {
          const v = visualFor(srv.state);
          const Icon = v.Icon;
          const isBusy = busy?.endsWith(`:${srv.name}`);
          return (
            <li
              key={srv.name}
              className="flex items-center justify-between gap-2 px-2 py-1.5 rounded-md border border-[var(--border-color)] bg-[var(--bg-primary)]"
            >
              <div className="min-w-0 flex-1">
                <div className="flex items-center gap-1.5">
                  <Icon
                    size={11}
                    style={{ color: v.color }}
                    className={srv.state.toLowerCase() === 'pending' ? 'animate-spin' : ''}
                  />
                  <span className="text-[0.75rem] font-mono text-[var(--text-primary)] truncate">
                    {srv.name}
                  </span>
                  <span className="text-[0.5625rem] uppercase font-bold tracking-wider" style={{ color: v.color }}>
                    {v.label}
                  </span>
                </div>
                {srv.last_error && (
                  <div className="text-[0.625rem] text-[var(--danger-color)] mt-0.5 truncate">
                    {srv.last_error}
                  </div>
                )}
              </div>
              <div className="flex items-center gap-1 shrink-0">
                {/* Cycle G — MCP OAuth start. Show only when the
                    server is in NEEDS_AUTH (executor surfaces this
                    state when a server requires OAuth before its
                    next reconnect). */}
                {srv.state.toLowerCase() === 'needs_auth' && (
                  <button
                    className="px-2 py-[2px] text-[0.625rem] text-[var(--warning-color)] border border-[var(--warning-color)] rounded hover:bg-[var(--bg-tertiary)] disabled:opacity-50"
                    onClick={async () => {
                      setBusy(`oauth:${srv.name}`);
                      try {
                        const r = await agentApi.mcpAuthStart(sessionId, srv.name);
                        window.open(r.authorization_url, '_blank', 'noopener,noreferrer');
                      } catch (err) {
                        setError(err instanceof Error ? err.message : String(err));
                      } finally {
                        setBusy(null);
                        await reload();
                      }
                    }}
                    disabled={isBusy}
                    title="Start OAuth — opens consent in a new tab"
                  >
                    Authorize
                  </button>
                )}
                {srv.state.toLowerCase() === 'disabled' ? (
                  <button
                    className="px-2 py-[2px] text-[0.625rem] text-[var(--success-color)] border border-[var(--border-color)] rounded hover:bg-[var(--bg-tertiary)] disabled:opacity-50"
                    onClick={() => action('enable', srv.name)}
                    disabled={isBusy}
                  >
                    Enable
                  </button>
                ) : (
                  <button
                    className="px-2 py-[2px] text-[0.625rem] text-[var(--warning-color)] border border-[var(--border-color)] rounded hover:bg-[var(--bg-tertiary)] disabled:opacity-50"
                    onClick={() => action('disable', srv.name)}
                    disabled={isBusy}
                  >
                    Disable
                  </button>
                )}
                <button
                  className="px-2 py-[2px] text-[0.625rem] text-[var(--text-secondary)] border border-[var(--border-color)] rounded hover:bg-[var(--bg-tertiary)] disabled:opacity-50"
                  onClick={() => action('test', srv.name)}
                  disabled={isBusy}
                >
                  Test
                </button>
                <button
                  className="h-5 w-5 rounded text-[var(--danger-color)] hover:bg-[rgba(239,68,68,0.10)] flex items-center justify-center disabled:opacity-50"
                  onClick={() => action('disconnect', srv.name)}
                  disabled={isBusy}
                  title="Disconnect"
                >
                  <X size={10} />
                </button>
              </div>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
