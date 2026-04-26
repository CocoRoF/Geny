'use client';

/**
 * ToolsEditor — edits the four `manifest.tools` snapshot fields:
 * `global_allowlist`, `global_blocklist` (pattern arrays) and
 * `adhoc`, `mcp_servers` (opaque object arrays).
 *
 * Pattern arrays are edited as one pattern per line — empty lines
 * are stripped on save. The object arrays are edited as pretty-
 * printed JSON; if the user pastes a non-array / invalid JSON we
 * surface the error inline so they can fix it before the parent
 * enables Save.
 */

import { useMemo } from 'react';

import type { ToolsSnapshot } from '@/types/environment';

export interface ToolsDraft {
  adhocText: string;
  mcpServersText: string;
  allowlistText: string;
  blocklistText: string;
  // T.1 (cycle 20260426_2) — checkbox grid driven by the external catalog
  // endpoint. Selected names map directly to manifest.tools.external.
  external: string[];
  // T.2 (placeholder; sprint adds the editor) — kept here so the
  // snapshot round-trip preserves the field.
  scopeText: string;
}

export function toolsDraftFromSnapshot(tools: ToolsSnapshot | undefined): ToolsDraft {
  const t = tools ?? emptyTools();
  return {
    adhocText: JSON.stringify(t.adhoc ?? [], null, 2),
    mcpServersText: JSON.stringify(t.mcp_servers ?? [], null, 2),
    allowlistText: (t.global_allowlist ?? []).join('\n'),
    blocklistText: (t.global_blocklist ?? []).join('\n'),
    external: [...(t.external ?? [])],
    scopeText: t.scope ? JSON.stringify(t.scope, null, 2) : '',
  };
}

export function emptyTools(): ToolsSnapshot {
  return {
    adhoc: [],
    mcp_servers: [],
    global_allowlist: [],
    global_blocklist: [],
    external: [],
    scope: undefined,
  };
}

function parseJsonArray(
  text: string,
): { ok: true; value: Array<Record<string, unknown>> } | { ok: false; error: string } {
  const trimmed = text.trim();
  if (!trimmed) return { ok: true, value: [] };
  try {
    const parsed = JSON.parse(trimmed);
    if (!Array.isArray(parsed)) {
      return { ok: false, error: 'Must be a JSON array' };
    }
    for (const item of parsed) {
      if (item === null || typeof item !== 'object' || Array.isArray(item)) {
        return { ok: false, error: 'Each entry must be a JSON object' };
      }
    }
    return { ok: true, value: parsed as Array<Record<string, unknown>> };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : 'Invalid JSON' };
  }
}

function parsePatternList(text: string): string[] {
  return text
    .split(/\r?\n/)
    .map(line => line.trim())
    .filter(line => line.length > 0);
}

function parseJsonObjectOrEmpty(
  text: string,
): { ok: true; value: Record<string, unknown> | undefined } | { ok: false; error: string } {
  const trimmed = text.trim();
  if (!trimmed) return { ok: true, value: undefined };
  try {
    const parsed = JSON.parse(trimmed);
    if (parsed === null || typeof parsed !== 'object' || Array.isArray(parsed)) {
      return { ok: false, error: 'Must be a JSON object (or empty for none)' };
    }
    return { ok: true, value: parsed as Record<string, unknown> };
  } catch (e) {
    return { ok: false, error: e instanceof Error ? e.message : 'Invalid JSON' };
  }
}

export interface ToolsValidation {
  adhocError: string | null;
  mcpServersError: string | null;
  scopeError: string | null;
  hasErrors: boolean;
  snapshot: ToolsSnapshot | null;
}

export function validateToolsDraft(draft: ToolsDraft): ToolsValidation {
  const adhoc = parseJsonArray(draft.adhocText);
  const mcp = parseJsonArray(draft.mcpServersText);
  const scope = parseJsonObjectOrEmpty(draft.scopeText);
  const adhocError = adhoc.ok ? null : adhoc.error;
  const mcpError = mcp.ok ? null : mcp.error;
  const scopeError = scope.ok ? null : scope.error;
  const hasErrors = !!adhocError || !!mcpError || !!scopeError;
  const snapshot: ToolsSnapshot | null = hasErrors
    ? null
    : {
        adhoc: adhoc.ok ? adhoc.value : [],
        mcp_servers: mcp.ok ? mcp.value : [],
        global_allowlist: parsePatternList(draft.allowlistText),
        global_blocklist: parsePatternList(draft.blocklistText),
        external: [...draft.external],
        scope: scope.ok ? scope.value : undefined,
      };
  return {
    adhocError,
    mcpServersError: mcpError,
    scopeError,
    hasErrors,
    snapshot,
  };
}

export function toolsSnapshotsEqual(a: ToolsSnapshot, b: ToolsSnapshot): boolean {
  return (
    JSON.stringify(a.adhoc ?? []) === JSON.stringify(b.adhoc ?? []) &&
    JSON.stringify(a.mcp_servers ?? []) === JSON.stringify(b.mcp_servers ?? []) &&
    JSON.stringify(a.global_allowlist ?? []) === JSON.stringify(b.global_allowlist ?? []) &&
    JSON.stringify(a.global_blocklist ?? []) === JSON.stringify(b.global_blocklist ?? []) &&
    JSON.stringify((a.external ?? []).slice().sort()) ===
      JSON.stringify((b.external ?? []).slice().sort()) &&
    JSON.stringify(a.scope ?? null) === JSON.stringify(b.scope ?? null)
  );
}

/** T.1 (cycle 20260426_2) — one row in the external tool picker. */
export interface ExternalToolOption {
  name: string;
  category: string;
  description: string;
}

interface Props {
  draft: ToolsDraft;
  onChange: (next: ToolsDraft) => void;
  /** Optional — when supplied, renders the external-tool checkbox grid.
   *  Pass empty array to show "no candidates discovered". */
  externalCatalog?: ExternalToolOption[] | null;
  labels: {
    allowlist: string;
    allowlistHint: string;
    blocklist: string;
    blocklistHint: string;
    adhocTools: string;
    adhocToolsHint: string;
    mcpServers: string;
    mcpServersHint: string;
    patternsPlaceholder: string;
    jsonArrayPlaceholder: string;
    entriesCount: string;
  };
}

function PatternField({
  value,
  onChange,
  placeholder,
}: {
  value: string;
  onChange: (next: string) => void;
  placeholder: string;
}) {
  return (
    <textarea
      value={value}
      onChange={e => onChange(e.target.value)}
      rows={5}
      spellCheck={false}
      placeholder={placeholder}
      className="py-2 px-3 rounded-md bg-[var(--bg-primary)] border border-[var(--border-color)] text-[0.8125rem] leading-[1.5] text-[var(--text-primary)] font-mono focus:outline-none focus:border-[var(--primary-color)] focus:shadow-[0_0_0_3px_rgba(59,130,246,0.1)] resize-y"
    />
  );
}

function JsonArrayField({
  value,
  onChange,
  placeholder,
  error,
}: {
  value: string;
  onChange: (next: string) => void;
  placeholder: string;
  error: string | null;
}) {
  return (
    <textarea
      value={value}
      onChange={e => onChange(e.target.value)}
      rows={8}
      spellCheck={false}
      placeholder={placeholder}
      className={`py-2 px-3 rounded-md bg-[var(--bg-primary)] border font-mono text-[0.75rem] leading-[1.5] text-[var(--text-primary)] focus:outline-none focus:shadow-[0_0_0_3px_rgba(59,130,246,0.1)] resize-y ${
        error
          ? 'border-[var(--danger-color)] focus:border-[var(--danger-color)]'
          : 'border-[var(--border-color)] focus:border-[var(--primary-color)]'
      }`}
    />
  );
}

export default function ToolsEditor({ draft, onChange, labels, externalCatalog }: Props) {
  const validation = useMemo(() => validateToolsDraft(draft), [draft]);
  const allowlistCount = useMemo(
    () => parsePatternList(draft.allowlistText).length,
    [draft.allowlistText],
  );
  const blocklistCount = useMemo(
    () => parsePatternList(draft.blocklistText).length,
    [draft.blocklistText],
  );

  return (
    <div className="flex flex-col gap-5">
      <div className="flex flex-col gap-1.5">
        <div className="flex items-center justify-between gap-2">
          <label className="text-[0.6875rem] font-semibold text-[var(--text-muted)] uppercase tracking-wide">
            {labels.allowlist}
          </label>
          <span className="text-[0.625rem] text-[var(--text-muted)]">
            {labels.entriesCount.replace('{count}', String(allowlistCount))}
          </span>
        </div>
        <PatternField
          value={draft.allowlistText}
          onChange={next => onChange({ ...draft, allowlistText: next })}
          placeholder={labels.patternsPlaceholder}
        />
        <small className="text-[0.6875rem] text-[var(--text-muted)]">{labels.allowlistHint}</small>
      </div>

      <div className="flex flex-col gap-1.5">
        <div className="flex items-center justify-between gap-2">
          <label className="text-[0.6875rem] font-semibold text-[var(--text-muted)] uppercase tracking-wide">
            {labels.blocklist}
          </label>
          <span className="text-[0.625rem] text-[var(--text-muted)]">
            {labels.entriesCount.replace('{count}', String(blocklistCount))}
          </span>
        </div>
        <PatternField
          value={draft.blocklistText}
          onChange={next => onChange({ ...draft, blocklistText: next })}
          placeholder={labels.patternsPlaceholder}
        />
        <small className="text-[0.6875rem] text-[var(--text-muted)]">{labels.blocklistHint}</small>
      </div>

      <div className="flex flex-col gap-1.5">
        <label className="text-[0.6875rem] font-semibold text-[var(--text-muted)] uppercase tracking-wide">
          {labels.adhocTools}
        </label>
        <JsonArrayField
          value={draft.adhocText}
          onChange={next => onChange({ ...draft, adhocText: next })}
          placeholder={labels.jsonArrayPlaceholder}
          error={validation.adhocError}
        />
        {validation.adhocError ? (
          <small className="text-[0.6875rem] text-[var(--danger-color)]">
            {validation.adhocError}
          </small>
        ) : (
          <small className="text-[0.6875rem] text-[var(--text-muted)]">{labels.adhocToolsHint}</small>
        )}
      </div>

      <div className="flex flex-col gap-1.5">
        <label className="text-[0.6875rem] font-semibold text-[var(--text-muted)] uppercase tracking-wide">
          {labels.mcpServers}
        </label>
        <JsonArrayField
          value={draft.mcpServersText}
          onChange={next => onChange({ ...draft, mcpServersText: next })}
          placeholder={labels.jsonArrayPlaceholder}
          error={validation.mcpServersError}
        />
        {validation.mcpServersError ? (
          <small className="text-[0.6875rem] text-[var(--danger-color)]">
            {validation.mcpServersError}
          </small>
        ) : (
          <small className="text-[0.6875rem] text-[var(--text-muted)]">{labels.mcpServersHint}</small>
        )}
      </div>

      {/* T.1 (cycle 20260426_2) — external tools picker. Renders only
          when the parent passes a catalog; otherwise the section is
          hidden so older callers keep working. */}
      {externalCatalog !== undefined && (
        <div className="flex flex-col gap-1.5">
          <div className="flex items-center justify-between gap-2">
            <label className="text-[0.6875rem] font-semibold text-[var(--text-muted)] uppercase tracking-wide">
              External tools <span className="opacity-60 normal-case">(GenyToolProvider)</span>
            </label>
            <span className="text-[0.625rem] text-[var(--text-muted)]">
              {draft.external.length} selected
            </span>
          </div>
          {externalCatalog === null ? (
            <div className="text-[0.75rem] text-[var(--text-muted)] italic py-2">
              Loading external tool catalog…
            </div>
          ) : externalCatalog.length === 0 ? (
            <div className="text-[0.75rem] text-[var(--text-muted)] italic py-2">
              No external tools discovered. Drop a tool into ``backend/tools/custom`` and reload.
            </div>
          ) : (
            <div className="max-h-[260px] overflow-y-auto rounded-md border border-[var(--border-color)] bg-[var(--bg-primary)]">
              {externalCatalog.map((opt) => {
                const checked = draft.external.includes(opt.name);
                return (
                  <label
                    key={opt.name}
                    className={`flex items-center gap-2 px-2 py-1 cursor-pointer hover:bg-[var(--bg-tertiary)] border-b border-[var(--border-color)] last:border-b-0 ${
                      checked ? 'bg-[rgba(59,130,246,0.05)]' : ''
                    }`}
                  >
                    <input
                      type="checkbox"
                      checked={checked}
                      onChange={(e) => {
                        const next = e.target.checked
                          ? [...draft.external, opt.name]
                          : draft.external.filter((n) => n !== opt.name);
                        onChange({ ...draft, external: next });
                      }}
                      className="cursor-pointer"
                    />
                    <span className="font-mono text-[0.75rem] text-[var(--text-primary)] flex-1 truncate">
                      {opt.name}
                    </span>
                    <span className="text-[0.625rem] text-[var(--text-muted)] uppercase tracking-wider shrink-0">
                      {opt.category}
                    </span>
                  </label>
                );
              })}
            </div>
          )}
          <small className="text-[0.6875rem] text-[var(--text-muted)]">
            Selected names land in <code className="font-mono">manifest.tools.external</code> —
            ``GenyToolProvider`` advertises every entry; the manifest decides which actually attach.
          </small>
        </div>
      )}

      {/* T.2 (cycle 20260426_2) — tools.scope editor. Free-form JSON
          object since the executor accepts any shape host plugins
          declare. Empty = no scope. */}
      <div className="flex flex-col gap-1.5">
        <label className="text-[0.6875rem] font-semibold text-[var(--text-muted)] uppercase tracking-wide">
          Tool scope <span className="opacity-60 normal-case">(JSON object, optional)</span>
        </label>
        <JsonArrayField
          value={draft.scopeText}
          onChange={next => onChange({ ...draft, scopeText: next })}
          placeholder={'(empty = no scope)\n{"workspace_root": "/repo"}'}
          error={validation.scopeError}
        />
        {validation.scopeError ? (
          <small className="text-[0.6875rem] text-[var(--danger-color)]">
            {validation.scopeError}
          </small>
        ) : (
          <small className="text-[0.6875rem] text-[var(--text-muted)]">
            Free-form scope dict consumed by host plugins. Leave empty for the executor default.
          </small>
        )}
      </div>
    </div>
  );
}
