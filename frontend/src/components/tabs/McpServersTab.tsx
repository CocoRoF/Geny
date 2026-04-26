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
import { Plus, RefreshCw, Save, Trash2, Plug } from 'lucide-react';
import {
  TabShell,
  TwoPaneBody,
  EditorModal,
  EmptyState,
  ActionButton,
} from '@/components/layout';

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

  const sidebar = (
    <>
      <ActionButton
        variant="primary"
        icon={Plus}
        onClick={openCreate}
        className="w-full justify-center mb-2"
      >
        Add server
      </ActionButton>
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
    </>
  );

  return (
    <TabShell
      title="MCP Servers"
      icon={Plug}
      subtitle={
        <>
          Custom servers persist as JSON files under{' '}
          <span className="font-mono">{customDir}</span>. Live-session OAuth lives in the per-session tools panel.
        </>
      }
      actions={
        <ActionButton icon={RefreshCw} spinIcon={loading} onClick={refresh} disabled={loading}>
          Refresh
        </ActionButton>
      }
      error={error}
      onDismissError={() => setError(null)}
    >
      <TwoPaneBody
        sidebar={sidebar}
        sidebarTitle="Custom MCP servers"
        sidebarWidth="wide"
        mainPadding="lg"
      >
        {!active ? (
          <EmptyState
            icon={Plug}
            title="Pick a server on the left"
            description={<>or click <span className="font-mono">Add server</span> to create one.</>}
          />
        ) : detail ? (
          <div>
            <div className="flex items-center justify-between mb-2">
              <h3 className="text-sm font-semibold font-mono">{detail.name}</h3>
              <div className="flex items-center gap-1">
                <ActionButton onClick={() => openEdit(detail.name)}>Edit</ActionButton>
                <ActionButton
                  variant="danger"
                  icon={Trash2}
                  onClick={() => onDelete(detail.name)}
                >
                  Delete
                </ActionButton>
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
      </TwoPaneBody>

      <EditorModal
        open={editorOpen}
        onClose={() => setEditorOpen(false)}
        title={editingExisting ? `Edit ${form.name}` : 'New custom MCP server'}
        saving={saving}
        width="xl"
        footer={
          <>
            <ActionButton onClick={() => setEditorOpen(false)} disabled={saving}>
              Cancel
            </ActionButton>
            <ActionButton variant="primary" icon={Save} onClick={submitForm} disabled={saving}>
              {saving ? 'Saving…' : editingExisting ? 'Save' : 'Create'}
            </ActionButton>
          </>
        }
      >
            <div className="grid gap-2 text-[0.75rem]">
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
      </EditorModal>
    </TabShell>
  );
}

export default McpServersTab;
