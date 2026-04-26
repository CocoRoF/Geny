'use client';

/**
 * FrameworkSettingsPanel (PR-F.1.6).
 *
 * Lists every section registered with the executor's section_registry
 * and lets the operator edit each as JSON. Server validates against
 * the registered Pydantic schema before persisting; invalid payloads
 * surface as a toast + textarea stays open for fixup.
 *
 * The form is intentionally minimal — JSON in, JSON out. Per-field
 * widgets per section are a follow-up; this PR is about closing the
 * "operator can't see/touch framework knobs at all" gap from the
 * gap-analysis.
 */

import { useEffect, useState } from 'react';
import {
  frameworkSettingsApi,
  FrameworkSectionResponse,
  FrameworkSectionSummary,
} from '@/lib/api';
import { RefreshCw, Save, AlertCircle } from 'lucide-react';
import { Textarea } from '@/components/ui/textarea';

interface SchemaProperty {
  type?: string;
  description?: string;
  default?: unknown;
}

function fieldHints(schema: Record<string, unknown> | null): Record<string, string> {
  if (!schema || typeof schema !== 'object') return {};
  const props = (schema as { properties?: Record<string, SchemaProperty> }).properties;
  if (!props) return {};
  const out: Record<string, string> = {};
  for (const [name, prop] of Object.entries(props)) {
    const t = prop?.type;
    const desc = prop?.description ?? '';
    out[name] = `${t ?? 'any'}${desc ? ` — ${desc}` : ''}`;
  }
  return out;
}

export function FrameworkSettingsPanel() {
  const [sections, setSections] = useState<FrameworkSectionSummary[]>([]);
  const [active, setActive] = useState<string | null>(null);
  const [detail, setDetail] = useState<FrameworkSectionResponse | null>(null);
  const [draft, setDraft] = useState('');
  const [loading, setLoading] = useState(false);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [hint, setHint] = useState<string | null>(null);

  const refresh = async () => {
    setLoading(true);
    setError(null);
    try {
      const res = await frameworkSettingsApi.list();
      setSections(res.sections);
      if (!active && res.sections.length > 0) {
        setActive(res.sections[0].name);
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    refresh();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  useEffect(() => {
    if (!active) {
      setDetail(null);
      return;
    }
    let cancelled = false;
    (async () => {
      setLoading(true);
      setError(null);
      try {
        const res = await frameworkSettingsApi.get(active);
        if (cancelled) return;
        setDetail(res);
        setDraft(JSON.stringify(res.values, null, 2));
      } catch (e) {
        if (!cancelled) setError(e instanceof Error ? e.message : String(e));
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [active]);

  const onSave = async () => {
    if (!active) return;
    let parsed: Record<string, unknown>;
    try {
      parsed = JSON.parse(draft);
      if (typeof parsed !== 'object' || parsed === null || Array.isArray(parsed)) {
        throw new Error('expected a JSON object at the top level');
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
      return;
    }
    setSaving(true);
    setError(null);
    setHint(null);
    try {
      const res = await frameworkSettingsApi.patch(active, parsed);
      setDetail(res);
      setDraft(JSON.stringify(res.values, null, 2));
      setHint('Saved.');
      // Optimistically refresh the list to flip has_data flags.
      refresh().catch(() => {});
    } catch (e) {
      setError(e instanceof Error ? e.message : String(e));
    } finally {
      setSaving(false);
    }
  };

  const hints = fieldHints(detail?.schema ?? null);

  return (
    <div className="flex h-full min-h-0 border border-[var(--border-color)] rounded">
      {/* Sidebar */}
      <aside className="w-44 shrink-0 border-r border-[var(--border-color)] overflow-y-auto p-2">
        <div className="text-[0.625rem] uppercase tracking-wider text-[var(--text-muted)] font-semibold px-2 py-1 flex items-center justify-between">
          Sections
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
        {sections.length === 0 ? (
          <div className="px-2 py-1 text-[0.6875rem] text-[var(--text-muted)] italic">
            {loading ? 'Loading…' : 'No sections registered.'}
          </div>
        ) : (
          sections.map((s) => {
            const hasReaders = s.readers && s.readers.length > 0;
            const readerSummary = hasReaders
              ? `Read by: ${s.readers.join(', ')}`
              : 'No registered reader — this section may be unread at runtime.';
            return (
              <button
                key={s.name}
                type="button"
                onClick={() => setActive(s.name)}
                className={`w-full text-left px-2 py-1.5 rounded text-[0.8125rem] hover:bg-[var(--bg-tertiary)] flex flex-col gap-0.5 ${
                  active === s.name ? 'bg-[var(--bg-tertiary)] font-semibold' : ''
                }`}
                title={readerSummary}
              >
                <span className="flex items-center justify-between">
                  <span className="font-mono truncate">{s.name}</span>
                  {s.has_data && (
                    <span className="w-1.5 h-1.5 rounded-full bg-[var(--success-color)]" title="has data" />
                  )}
                </span>
                <span
                  className={`text-[0.625rem] truncate ${
                    hasReaders ? 'text-[var(--text-muted)]' : 'text-[var(--warning-color)]'
                  }`}
                >
                  {hasReaders ? s.readers.join(', ') : 'no reader'}
                </span>
              </button>
            );
          })
        )}
      </aside>

      {/* Editor */}
      <div className="flex-1 min-w-0 p-3 flex flex-col">
        {!active ? (
          <div className="text-sm text-[var(--text-muted)] m-auto">Pick a section.</div>
        ) : (
          <>
            <header className="flex items-center justify-between mb-2">
              <div>
                <h3 className="text-sm font-semibold font-mono">{active}</h3>
                {detail && (
                  <p className="text-[0.6875rem] text-[var(--text-muted)]">
                    {detail.settings_path}
                  </p>
                )}
              </div>
              <button
                type="button"
                onClick={onSave}
                disabled={saving || loading || !detail}
                className="flex items-center gap-1 text-xs bg-[var(--primary-color)] text-white rounded px-2 py-1 disabled:opacity-50"
              >
                <Save className="w-3 h-3" />
                {saving ? 'Saving…' : 'Save'}
              </button>
            </header>

            {error && (
              <div className="text-xs text-red-700 bg-red-50 border border-red-200 rounded p-2 mb-2 flex items-start gap-1.5">
                <AlertCircle className="w-3 h-3 mt-0.5" />
                <span>{error}</span>
              </div>
            )}
            {hint && !error && (
              <div className="text-xs text-green-700 bg-green-50 border border-green-200 rounded p-2 mb-2">
                {hint}
              </div>
            )}

            <Textarea
              value={draft}
              onChange={(e) => {
                setDraft(e.target.value);
                setHint(null);
              }}
              spellCheck={false}
              className="flex-1 min-h-0 font-mono text-xs resize-none"
            />

            {Object.keys(hints).length > 0 && (
              <details className="mt-2 text-[0.6875rem]">
                <summary className="cursor-pointer text-[var(--text-muted)]">
                  Field hints ({Object.keys(hints).length})
                </summary>
                <ul className="mt-1 ml-3 space-y-0.5">
                  {Object.entries(hints).map(([k, v]) => (
                    <li key={k}>
                      <span className="font-mono">{k}</span>: <span className="text-[var(--text-muted)]">{v}</span>
                    </li>
                  ))}
                </ul>
              </details>
            )}
          </>
        )}
      </div>
    </div>
  );
}

export default FrameworkSettingsPanel;
