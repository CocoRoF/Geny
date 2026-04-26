'use client';

/**
 * McpServersTab — manage custom MCP server JSON files.
 *
 * Reads from /api/mcp/custom. The config can be edited two ways:
 *   - Structured form (T.3 / cycle 20260426_2): per-transport fields
 *     (stdio: command + args + env; http/sse: url + headers + env).
 *   - Raw JSON textarea: free-form fallback for any field structured
 *     mode doesn't model yet.
 *
 * The two modes share state — switching between them serialises the
 * structured fields into JSON or parses JSON back into structured
 * fields (best-effort; unknown keys land in the raw JSON view).
 *
 * Per-session OAuth flow lives inside MCPAdminPanel.
 */

import { useEffect, useMemo, useState } from 'react';
import { toast } from 'sonner';
import { customMcpApi, CustomMcpServerSummary, CustomMcpServerDetail } from '@/lib/api';
import { Plus, RefreshCw, Save, Trash2, Plug, X } from 'lucide-react';
import {
  TabShell,
  TwoPaneBody,
  EditorModal,
  EmptyState,
  ActionButton,
} from '@/components/layout';
import { Input } from '@/components/ui/input';
import { Textarea } from '@/components/ui/textarea';
import { Label } from '@/components/ui/label';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';

const NAME_RE = /^[a-z0-9][a-z0-9_-]{1,63}$/;

const TRANSPORTS = ['stdio', 'http', 'sse'] as const;
type Transport = (typeof TRANSPORTS)[number];

interface KvRow {
  key: string;
  value: string;
}

interface FormState {
  name: string;
  description: string;
  mode: 'structured' | 'json';
  // Structured fields. ``configJson`` is the raw fallback / JSON-mode source.
  transport: Transport;
  command: string;        // stdio
  argsText: string;       // stdio (one per line)
  envRows: KvRow[];       // all transports
  url: string;            // http / sse
  headerRows: KvRow[];    // http / sse
  configJson: string;     // JSON-mode authoritative; structured-mode synced on switch
}

const EMPTY_FORM: FormState = {
  name: '',
  description: '',
  mode: 'structured',
  transport: 'stdio',
  command: 'uvx',
  argsText: 'mcp-server-fetch',
  envRows: [],
  url: '',
  headerRows: [],
  configJson: '{\n  "command": "uvx",\n  "args": ["mcp-server-fetch"]\n}',
};

function rowsToDict(rows: KvRow[]): Record<string, string> {
  const out: Record<string, string> = {};
  for (const r of rows) {
    const k = r.key.trim();
    if (!k) continue;
    out[k] = r.value;
  }
  return out;
}

function dictToRows(d: unknown): KvRow[] {
  if (!d || typeof d !== 'object' || Array.isArray(d)) return [];
  return Object.entries(d as Record<string, unknown>).map(([k, v]) => ({
    key: k,
    value: String(v ?? ''),
  }));
}

/** Serialise structured fields → executor-shape JSON. */
function structuredToJson(f: FormState): Record<string, unknown> {
  const out: Record<string, unknown> = { transport: f.transport };
  if (f.transport === 'stdio') {
    out.command = f.command.trim();
    const args = f.argsText
      .split(/\r?\n/)
      .map((s) => s.trim())
      .filter((s) => s.length > 0);
    if (args.length) out.args = args;
  } else {
    if (f.url.trim()) out.url = f.url.trim();
    const headers = rowsToDict(f.headerRows);
    if (Object.keys(headers).length) out.headers = headers;
  }
  const env = rowsToDict(f.envRows);
  if (Object.keys(env).length) out.env = env;
  if (f.description.trim()) out.description = f.description.trim();
  return out;
}

/** Parse executor-shape JSON → structured fields (best-effort). */
function jsonToStructured(raw: Record<string, unknown>): Partial<FormState> {
  const transportRaw = typeof raw.transport === 'string' ? raw.transport : 'stdio';
  const transport: Transport = TRANSPORTS.includes(transportRaw as Transport)
    ? (transportRaw as Transport)
    : 'stdio';
  const out: Partial<FormState> = {
    transport,
    command: typeof raw.command === 'string' ? raw.command : '',
    argsText: Array.isArray(raw.args) ? (raw.args as string[]).join('\n') : '',
    envRows: dictToRows(raw.env),
    url: typeof raw.url === 'string' ? raw.url : '',
    headerRows: dictToRows(raw.headers),
  };
  return out;
}

function KvEditor({
  rows,
  onChange,
  keyPlaceholder = 'key',
  valuePlaceholder = 'value',
}: {
  rows: KvRow[];
  onChange: (rows: KvRow[]) => void;
  keyPlaceholder?: string;
  valuePlaceholder?: string;
}) {
  return (
    <div className="grid gap-1.5">
      {rows.map((row, i) => (
        <div key={i} className="flex gap-1.5 items-center">
          <Input
            value={row.key}
            placeholder={keyPlaceholder}
            onChange={(e) => {
              const next = [...rows];
              next[i] = { ...next[i], key: e.target.value };
              onChange(next);
            }}
            className="font-mono text-[0.75rem] flex-1"
          />
          <Input
            value={row.value}
            placeholder={valuePlaceholder}
            onChange={(e) => {
              const next = [...rows];
              next[i] = { ...next[i], value: e.target.value };
              onChange(next);
            }}
            className="font-mono text-[0.75rem] flex-1"
          />
          <button
            type="button"
            onClick={() => onChange(rows.filter((_, j) => j !== i))}
            className="text-[var(--text-muted)] hover:text-red-600 p-1"
            title="Remove"
          >
            <X className="w-3.5 h-3.5" />
          </button>
        </div>
      ))}
      <button
        type="button"
        onClick={() => onChange([...rows, { key: '', value: '' }])}
        className="text-[0.75rem] text-[var(--primary-color)] hover:underline self-start"
      >
        + Add row
      </button>
    </div>
  );
}

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
      const cfg = d.config as Record<string, unknown>;
      const structured = jsonToStructured(cfg);
      setForm({
        ...EMPTY_FORM,
        name: d.name,
        description: typeof cfg.description === 'string' ? cfg.description : '',
        configJson: JSON.stringify(cfg, null, 2),
        ...structured,
      });
      setEditorOpen(true);
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    }
  };

  /** When the user toggles between structured and json modes, sync
   *  whichever one was just edited into the other so neither view
   *  goes stale. */
  const switchMode = (next: 'structured' | 'json') => {
    if (next === form.mode) return;
    if (next === 'json') {
      // Structured → JSON: serialise.
      const cfg = structuredToJson(form);
      setForm({ ...form, mode: 'json', configJson: JSON.stringify(cfg, null, 2) });
    } else {
      // JSON → Structured: parse (best-effort; unknown keys lost).
      try {
        const parsed = JSON.parse(form.configJson || '{}');
        if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
          throw new Error('config must be a JSON object');
        }
        const structured = jsonToStructured(parsed as Record<string, unknown>);
        setForm({ ...form, ...structured, mode: 'structured' });
      } catch (e) {
        setError(
          'Cannot switch to structured mode — JSON invalid (' +
            (e instanceof Error ? e.message : 'parse error') +
            '). Fix it first or stay in JSON mode.',
        );
      }
    }
  };

  const submitForm = async () => {
    if (!NAME_RE.test(form.name)) {
      setError('name must be lower-case alnum / dash / underscore (2-64 chars)');
      return;
    }
    let parsed: Record<string, unknown>;
    if (form.mode === 'structured') {
      parsed = structuredToJson(form);
    } else {
      try {
        const v = JSON.parse(form.configJson);
        if (typeof v !== 'object' || v === null || Array.isArray(v)) {
          throw new Error('config must be a JSON object');
        }
        parsed = v as Record<string, unknown>;
      } catch (e) {
        setError(e instanceof Error ? e.message : String(e));
        return;
      }
    }
    setSaving(true);
    setError(null);
    try {
      if (editingExisting) {
        await customMcpApi.replace(form.name, parsed, form.description || undefined);
      } else {
        await customMcpApi.create(form.name, parsed, form.description || undefined);
      }
      toast.success(editingExisting ? `Updated ${form.name}` : `Created ${form.name}`);
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
      toast.success(`Deleted ${name}`);
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
        <div className="grid gap-3">
          <div className="grid grid-cols-3 gap-3">
            <div className="grid gap-1.5 col-span-2">
              <Label htmlFor="mcp-name">Name *</Label>
              <Input
                id="mcp-name"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
                disabled={editingExisting}
                placeholder="e.g. github"
                className="font-mono"
              />
            </div>
            <div className="grid gap-1.5">
              <Label>Editor mode</Label>
              <div className="inline-flex rounded-md border border-[var(--border-color)] bg-[var(--bg-secondary)] p-0.5">
                {(['structured', 'json'] as const).map((m) => (
                  <button
                    key={m}
                    type="button"
                    onClick={() => switchMode(m)}
                    className={`flex-1 px-2 py-1 rounded text-[0.6875rem] font-medium cursor-pointer transition-colors ${
                      form.mode === m
                        ? 'bg-[var(--primary-color)] text-white'
                        : 'bg-transparent text-[var(--text-muted)] hover:text-[var(--text-primary)]'
                    }`}
                  >
                    {m}
                  </button>
                ))}
              </div>
            </div>
          </div>

          <div className="grid gap-1.5">
            <Label htmlFor="mcp-desc">Description <span className="opacity-60">(optional)</span></Label>
            <Input
              id="mcp-desc"
              value={form.description}
              onChange={(e) => setForm({ ...form, description: e.target.value })}
            />
          </div>

          {form.mode === 'structured' ? (
            <>
              <div className="grid gap-1.5">
                <Label>Transport</Label>
                <Select
                  value={form.transport}
                  onValueChange={(v) => setForm({ ...form, transport: v as Transport })}
                >
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {TRANSPORTS.map((tr) => (
                      <SelectItem key={tr} value={tr}>{tr}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>

              {form.transport === 'stdio' ? (
                <>
                  <div className="grid gap-1.5">
                    <Label htmlFor="mcp-command">Command <span className="opacity-60">(executable path)</span></Label>
                    <Input
                      id="mcp-command"
                      value={form.command}
                      onChange={(e) => setForm({ ...form, command: e.target.value })}
                      placeholder="uvx"
                      className="font-mono"
                    />
                  </div>
                  <div className="grid gap-1.5">
                    <Label htmlFor="mcp-args">Args <span className="opacity-60">(one per line)</span></Label>
                    <Textarea
                      id="mcp-args"
                      value={form.argsText}
                      onChange={(e) => setForm({ ...form, argsText: e.target.value })}
                      rows={4}
                      placeholder={'mcp-server-fetch'}
                      className="font-mono text-[0.75rem]"
                    />
                  </div>
                </>
              ) : (
                <>
                  <div className="grid gap-1.5">
                    <Label htmlFor="mcp-url">URL</Label>
                    <Input
                      id="mcp-url"
                      value={form.url}
                      onChange={(e) => setForm({ ...form, url: e.target.value })}
                      placeholder="https://mcp.example.com/sse"
                      className="font-mono text-[0.75rem]"
                    />
                  </div>
                  <div className="grid gap-1.5">
                    <Label>Headers</Label>
                    <KvEditor
                      rows={form.headerRows}
                      onChange={(rows) => setForm({ ...form, headerRows: rows })}
                      keyPlaceholder="Authorization"
                      valuePlaceholder="Bearer …"
                    />
                  </div>
                </>
              )}

              <div className="grid gap-1.5">
                <Label>Env <span className="opacity-60">(extra environment variables)</span></Label>
                <KvEditor
                  rows={form.envRows}
                  onChange={(rows) => setForm({ ...form, envRows: rows })}
                  keyPlaceholder="GITHUB_TOKEN"
                  valuePlaceholder="ghp_…"
                />
              </div>
            </>
          ) : (
            <div className="grid gap-1.5">
              <Label htmlFor="mcp-cfg">Config <span className="opacity-60">(JSON object)</span></Label>
              <Textarea
                id="mcp-cfg"
                value={form.configJson}
                onChange={(e) => setForm({ ...form, configJson: e.target.value })}
                rows={14}
                spellCheck={false}
                className="font-mono text-xs"
              />
            </div>
          )}
        </div>
      </EditorModal>
    </TabShell>
  );
}

export default McpServersTab;
