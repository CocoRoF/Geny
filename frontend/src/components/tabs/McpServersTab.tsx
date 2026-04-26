'use client';

/**
 * McpServersTab — manage custom MCP server JSON files (Cycle G).
 *
 * Reads from /api/mcp/custom (PR-G-MCP-1). The JSON config is edited
 * in a textarea; on save the backend writes the file and reloads the
 * MCPLoader so live sessions pick the server up on next reconnect.
 *
 * Per-session OAuth flow lives inside MCPAdminPanel (PR-G-MCP-OAuth).
 * This tab is for the catalog ("which servers are even available
 * to enable per preset"), not the live-session attach surface.
 */

import { useEffect, useMemo, useState } from 'react';
import { customMcpApi, CustomMcpServerSummary, CustomMcpServerDetail } from '@/lib/api';
import { Plus, RefreshCw, Save, Trash2, X, AlertCircle } from 'lucide-react';

const NAME_RE = /^[a-z0-9][a-z0-9_-]{1,63}$/;

interface FormState {
  name: string;
  configJson: string;
  description: string;
}

const EMPTY_FORM: FormState = {
  name: '',
  configJson: '{\n  "command": "uvx",\n  "args": ["mcp-server-fetch"]\n}',
  description: '',
};

export function McpServersTab() {
  const [servers, setServers] = useState<CustomMcpServerSummary[]>([]);
  const [customDir, setCustomDir] = useState<string>('');
  const [active, setActive] = useState<string | null>(null);
  const [detail, setDetail] = useState<CustomMcpServerDetail | null>(null);
  const [editorOpen, setEditorOpen] = useState(false);
  const [form, setForm] = useState<FormState>(EMPTY_FORM);
  const [editingExisting, setEditingExisting] = useState(false);
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const refresh = async () => {
    setLoading(true);
    setError(null);
    try {
      const r = await customMcpApi.list();
      setServers(r.servers);
      setCustomDir(r.custom_dir);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
  }, []);

  useEffect(() => {
    if (!active) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    customMcpApi.get(active)
      .then((r) => { if (!cancelled) setDetail(r); })
      .catch((e) => { if (!cancelled) setError(e instanceof Error ? e.message : String(e)); });
    return () => { cancelled = true; };
  }, [active]);

  const openCreate = () => {
    setEditingExisting(false);
    setForm(EMPTY_FORM);
    setEditorOpen(true);
  };

  const openEdit = async (name: string) => {
    setEditingExisting(true);
    setError(null);
    try {
      const d = await customMcpApi.get(name);
      setForm({
        name: d.name,
        configJson: JSON.stringify(d.config, null, 2),
        description: typeof d.config.description === 'string' ? d.config.description : '',
      });
      setEditorOpen(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const submitForm = async () => {
    if (!NAME_RE.test(form.name)) {
      setError('name must be lower-case alnum / dash / underscore (2-64 chars)');
      return;
    }
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(form.configJson);
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
        throw new Error('config must be a JSON object');
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return;
    }
    setSaving(true);
    setError(null);
    try {
      if (editingExisting) {
        await customMcpApi.replace(form.name, parsed, form.description || undefined);
      } else {
        await customMcpApi.create(form.name, parsed, form.description || undefined);
      }
      setEditorOpen(false);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const onDelete = async (name: string) => {
    if (!window.confirm(`Delete custom MCP server "${name}"?`)) return;
    try {
      await customMcpApi.remove(name);
      if (active === name) setActive(null);
      await refresh();
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  const detailJson = useMemo(
    () => (detail ? JSON.stringify(detail.config, null, 2) : ''),
    [detail],
  );

  return (
    <div className="flex h-full min-h-0">
      <aside className="w-60 shrink-0 border-r border-[var(--border-color)] overflow-y-auto p-2">
        <div className="text-[0.625rem] uppercase tracking-wider text-[var(--text-muted)] font-semibold px-2 py-1 flex items-center justify-between">
          Custom MCP servers
          <button
            type="button"
            onClick={refresh}
            disabled={loading}
            className="text-[var(--text-muted)] hover:text-[var(--primary-color)]"
            title="Refresh"
          >
            <RefreshCw size={10} className={loading ? 'animate-spin' : ''} />
          </button>
        </div>
        <button
          type="button"
          onClick={openCreate}
          className="w-full flex items-center justify-center gap-1 text-xs bg-[var(--primary-color)] text-white rounded px-2 py-1 mb-2"
        >
          <Plus className="w-3 h-3" />
          Add server
        </button>
        {servers.length === 0 ? (
          <div className="px-2 py-1 text-[0.6875rem] text-[var(--text-muted)] italic">
            {loading ? 'Loading…' : 'None.'}
          </div>
        ) : (
          servers.map((s) => (
            <button
              key={s.name}
              type="button"
              onClick={() => setActive(s.name)}
              className={`w-full text-left px-2 py-1.5 rounded text-[0.8125rem] hover:bg-[var(--bg-tertiary)] ${
                active === s.name ? 'bg-[var(--bg-tertiary)] font-semibold' : ''
              }`}
            >
              <span className="font-mono">{s.name}</span>
              {s.type && (
                <span className="text-[0.5625rem] uppercase text-[var(--text-muted)] ml-1">{s.type}</span>
              )}
              {s.description && (
                <div className="text-[0.6875rem] text-[var(--text-secondary)] line-clamp-1">
                  {s.description}
                </div>
              )}
            </button>
          ))
        )}
      </aside>

      <main className="flex-1 min-w-0 overflow-y-auto p-4">
        <header className="mb-3">
          <h2 className="text-base font-semibold">MCP Servers</h2>
          <p className="text-[0.75rem] text-[var(--text-muted)]">
            Custom servers persist as JSON files under{' '}
            <span className="font-mono">{customDir}</span>. Live-session OAuth and per-server
            controls live in the per-session tools panel.
          </p>
        </header>
        {error && (
          <div className="text-sm text-red-700 bg-red-50 border border-red-200 rounded p-2 mb-2 flex items-start gap-1.5">
            <AlertCircle className="w-3 h-3 mt-0.5" />
            <span>{error}</span>
          </div>
        )}
        {!active ? (
          <div className="text-sm text-[var(--text-muted)] py-12 text-center">
            Pick a server on the left, or click <span className="font-mono">Add server</span>.
          </div>
        ) : detail ? (
          <div>
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-sm font-semibold font-mono">{detail.name}</h3>
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  onClick={() => openEdit(detail.name)}
                  className="text-xs border rounded px-2 py-1"
                >
                  Edit
                </button>
                <button
                  type="button"
                  onClick={() => onDelete(detail.name)}
                  className="text-xs border rounded px-2 py-1 text-red-600 hover:bg-red-50"
                >
                  <Trash2 className="w-3 h-3 inline mr-1" /> Delete
                </button>
              </div>
            </div>
            <p className="text-[0.6875rem] text-[var(--text-muted)] mb-2 font-mono">
              {detail.path}
            </p>
            <pre className="text-[0.75rem] font-mono bg-[var(--bg-tertiary)] rounded p-3 overflow-x-auto">
              {detailJson}
            </pre>
          </div>
        ) : (
          <div className="text-sm text-[var(--text-muted)]">Loading…</div>
        )}
      </main>

      {editorOpen && (
        <div
          className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4"
          onClick={() => !saving && setEditorOpen(false)}
        >
          <div
            className="bg-[var(--bg-primary)] rounded-lg border border-[var(--border-color)] w-full max-w-2xl max-h-[80vh] overflow-hidden flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            <header className="px-4 py-2 border-b border-[var(--border-color)] flex items-center justify-between">
              <h3 className="text-sm font-semibold">
                {editingExisting ? `Edit ${form.name}` : 'New custom MCP server'}
              </h3>
              <button
                type="button"
                onClick={() => setEditorOpen(false)}
                disabled={saving}
                className="text-[var(--text-muted)] hover:text-[var(--text-primary)]"
              >
                <X size={14} />
              </button>
            </header>
            <div className="overflow-y-auto p-4 grid gap-2 text-[0.75rem]">
              <label>
                <div className="text-[var(--text-muted)] mb-0.5">Name *</div>
                <input
                  value={form.name}
                  onChange={(e) => setForm({ ...form, name: e.target.value })}
                  disabled={editingExisting}
                  placeholder="e.g. github"
                  className="w-full border rounded px-2 py-1 text-[0.8125rem] font-mono disabled:opacity-50"
                />
              </label>
              <label>
                <div className="text-[var(--text-muted)] mb-0.5">Description (optional)</div>
                <input
                  value={form.description}
                  onChange={(e) => setForm({ ...form, description: e.target.value })}
                  className="w-full border rounded px-2 py-1 text-[0.8125rem]"
                />
              </label>
              <label>
                <div className="text-[var(--text-muted)] mb-0.5">Config (JSON object)</div>
                <textarea
                  value={form.configJson}
                  onChange={(e) => setForm({ ...form, configJson: e.target.value })}
                  rows={14}
                  spellCheck={false}
                  className="w-full border rounded px-2 py-1 text-[0.75rem] font-mono"
                />
              </label>
            </div>
            <footer className="px-4 py-2 border-t border-[var(--border-color)] flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setEditorOpen(false)}
                disabled={saving}
                className="text-xs border rounded px-3 py-1"
              >
                Cancel
              </button>
              <button
                type="button"
                onClick={submitForm}
                disabled={saving}
                className="text-xs bg-[var(--primary-color)] text-white rounded px-3 py-1 disabled:opacity-50 inline-flex items-center gap-1"
              >
                <Save className="w-3 h-3" />
                {saving ? 'Saving…' : editingExisting ? 'Save' : 'Create'}
              </button>
            </footer>
          </div>
        </div>
      )}
    </div>
  );
}

export default McpServersTab;
