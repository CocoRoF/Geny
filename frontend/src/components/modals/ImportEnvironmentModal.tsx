'use client';

/**
 * ImportEnvironmentModal — create a brand-new environment by importing a
 * previously exported blob (full env record with manifest/snapshot, not
 * just a manifest).
 *
 * The paired overwrite flow lives in ImportManifestModal (for replacing
 * the manifest on an existing env). This modal wires up the orphan
 * `importEnvironment` store action to the Environments tab toolbar so
 * users can drop a backup JSON and get a fresh env created from it.
 *
 * Backend endpoint: `POST /api/environments/import` → returns `{id}`.
 */

import { useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { AlertTriangle, Check, FileUp, Upload, X } from 'lucide-react';

import { useEnvironmentStore } from '@/store/useEnvironmentStore';
import { useI18n } from '@/lib/i18n';
import { environmentApi } from '@/lib/environmentApi';

interface Props {
  onClose: () => void;
  onImported?: (id: string) => void;
}

type SingleMeta = { name?: string; stageCount?: number; version?: string; mode: 'manifest' | 'snapshot' };
type BundleEntry = { env_id?: string; data: Record<string, unknown>; meta: SingleMeta };
type ParseResult =
  | { ok: true; kind: 'single'; data: Record<string, unknown>; meta: SingleMeta }
  | { ok: true; kind: 'bundle'; entries: BundleEntry[]; bundleVersion: string }
  | { ok: false; error: string };

function classifySingleEnv(
  c: Record<string, unknown>,
): { data: Record<string, unknown>; meta: SingleMeta } | null {
  const manifest = c.manifest as Record<string, unknown> | undefined;
  const snapshot = c.snapshot as Record<string, unknown> | undefined;
  if (manifest && typeof manifest === 'object' && !Array.isArray(manifest)) {
    const stages = Array.isArray(manifest.stages) ? manifest.stages.length : undefined;
    return {
      data: c,
      meta: {
        name: typeof c.name === 'string' ? c.name : undefined,
        stageCount: stages,
        version: typeof manifest.version === 'string' ? manifest.version : undefined,
        mode: 'manifest',
      },
    };
  }
  if (snapshot && typeof snapshot === 'object' && !Array.isArray(snapshot)) {
    return {
      data: c,
      meta: {
        name: typeof c.name === 'string' ? c.name : undefined,
        mode: 'snapshot',
      },
    };
  }
  return null;
}

function extractEnvPayload(parsed: unknown): ParseResult {
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    return { ok: false, error: 'Root must be a JSON object' };
  }
  const obj = parsed as Record<string, unknown>;

  // Bundle format produced by the Environments tab bulk export:
  //   { version: "1", generated_at, exports: [{env_id, data}] }
  if (
    Array.isArray(obj.exports) &&
    (typeof obj.version === 'string' || obj.version === undefined)
  ) {
    const exports = obj.exports as unknown[];
    const entries: BundleEntry[] = [];
    for (let i = 0; i < exports.length; i += 1) {
      const item = exports[i];
      if (!item || typeof item !== 'object' || Array.isArray(item)) {
        return {
          ok: false,
          error: `Bundle entry #${i + 1} is not an object`,
        };
      }
      const rec = item as Record<string, unknown>;
      const rawData = rec.data && typeof rec.data === 'object' && !Array.isArray(rec.data)
        ? (rec.data as Record<string, unknown>)
        : null;
      if (!rawData) {
        return {
          ok: false,
          error: `Bundle entry #${i + 1} is missing a \`data\` object`,
        };
      }
      const classified = classifySingleEnv(rawData);
      if (!classified) {
        return {
          ok: false,
          error: `Bundle entry #${i + 1} missing \`manifest\` or \`snapshot\``,
        };
      }
      entries.push({
        env_id: typeof rec.env_id === 'string' ? rec.env_id : undefined,
        data: classified.data,
        meta: classified.meta,
      });
    }
    if (entries.length === 0) {
      return { ok: false, error: 'Bundle contains 0 entries' };
    }
    return {
      ok: true,
      kind: 'bundle',
      entries,
      bundleVersion: typeof obj.version === 'string' ? obj.version : '1',
    };
  }

  // Accept: raw env object OR { data: {...} } export envelope.
  const candidates: Record<string, unknown>[] = [obj];
  if ('data' in obj && obj.data && typeof obj.data === 'object' && !Array.isArray(obj.data)) {
    candidates.push(obj.data as Record<string, unknown>);
  }

  for (const c of candidates) {
    const classified = classifySingleEnv(c);
    if (classified) {
      return { ok: true, kind: 'single', ...classified };
    }
  }

  return {
    ok: false,
    error: 'Missing environment body (expected `manifest` or `snapshot`)',
  };
}

type BundleResult = {
  successes: { env_id?: string; new_id: string; name: string }[];
  failures: { env_id?: string; name: string; error: string }[];
};

export default function ImportEnvironmentModal({ onClose, onImported }: Props) {
  const { importEnvironment, loadEnvironments, refreshSessionCounts } = useEnvironmentStore();
  const { t } = useI18n();

  const [rawText, setRawText] = useState('');
  const [fileName, setFileName] = useState<string | null>(null);
  const [nameOverride, setNameOverride] = useState('');
  const [regenerateId, setRegenerateId] = useState(true);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState('');
  const [isDragOver, setIsDragOver] = useState(false);
  const [bundleResult, setBundleResult] = useState<BundleResult | null>(null);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  const parsed = (() => {
    const trimmed = rawText.trim();
    if (!trimmed) return null;
    try {
      return extractEnvPayload(JSON.parse(trimmed));
    } catch (e) {
      return { ok: false as const, error: e instanceof Error ? e.message : 'Invalid JSON' };
    }
  })();

  const parseError = parsed && !parsed.ok ? parsed.error : null;
  const ready = parsed && parsed.ok;

  const handleFile = async (file: File) => {
    setFileName(file.name);
    try {
      setRawText(await file.text());
    } catch (e) {
      setSubmitError(e instanceof Error ? e.message : 'Failed to read file');
    }
  };

  const handleFileInput = (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (file) void handleFile(file);
  };

  const handleDrop = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    setIsDragOver(false);
    const file = e.dataTransfer.files?.[0];
    if (file) void handleFile(file);
  };

  const handleDragOver = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    if (!isDragOver) setIsDragOver(true);
  };

  const handleDragLeave = (e: React.DragEvent<HTMLDivElement>) => {
    if (e.currentTarget === e.target || !e.currentTarget.contains(e.relatedTarget as Node | null)) {
      setIsDragOver(false);
    }
  };

  const handleConfirm = async () => {
    if (!parsed || !parsed.ok || submitting) return;
    setSubmitting(true);
    setSubmitError('');
    try {
      if (parsed.kind === 'single') {
        const payload = { ...parsed.data };
        if (regenerateId) delete payload.id;
        const trimmed = nameOverride.trim();
        if (trimmed) payload.name = trimmed;
        const result = await importEnvironment(payload);
        onImported?.(result.id);
        onClose();
        return;
      }
      // Bundle path — one round-trip to the new bulk endpoint.
      const cleanedEntries = parsed.entries.map(entry => {
        const payload = { ...entry.data };
        if (regenerateId) delete payload.id;
        return { env_id: entry.env_id, data: payload };
      });
      const response = await environmentApi.importEnvBulk({
        version: parsed.bundleVersion,
        entries: cleanedEntries,
      });
      const successes: BundleResult['successes'] = [];
      const failures: BundleResult['failures'] = [];
      for (let i = 0; i < response.results.length; i += 1) {
        const r = response.results[i];
        const originMeta = parsed.entries[i]?.meta;
        const displayName = originMeta?.name || r.env_id || '—';
        if (r.ok && r.new_id) {
          successes.push({ env_id: r.env_id, new_id: r.new_id, name: displayName });
        } else {
          failures.push({
            env_id: r.env_id,
            name: displayName,
            error: r.error ?? 'import failed',
          });
        }
      }
      setBundleResult({ successes, failures });
      if (successes.length > 0) {
        await loadEnvironments();
        void refreshSessionCounts();
      }
      if (failures.length === 0 && successes.length > 0) {
        onImported?.(successes[0].new_id);
      }
    } catch (e: unknown) {
      setSubmitError(e instanceof Error ? e.message : t('importEnvironment.failed'));
    } finally {
      setSubmitting(false);
    }
  };

  if (typeof document === 'undefined') return null;

  return createPortal(
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-black/50 backdrop-blur-sm px-4"
      onClick={onClose}
    >
      <div
        className="w-full max-w-[640px] max-h-[90vh] bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-lg shadow-[var(--shadow-lg)] flex flex-col"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start justify-between gap-3 py-3 px-5 border-b border-[var(--border-color)] shrink-0">
          <div className="flex flex-col gap-0.5">
            <h3 className="text-[1rem] font-semibold text-[var(--text-primary)]">
              {t('importEnvironment.title')}
            </h3>
            <span className="text-[0.75rem] text-[var(--text-muted)]">
              {t('importEnvironment.subtitle')}
            </span>
          </div>
          <button
            className="flex items-center justify-center w-8 h-8 rounded-md bg-transparent border-none text-[var(--text-muted)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)] cursor-pointer shrink-0"
            onClick={onClose}
          >
            <X size={16} />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 min-h-0 overflow-y-auto px-5 py-4 flex flex-col gap-4">
          {/* Drop zone */}
          <div
            onDrop={handleDrop}
            onDragOver={handleDragOver}
            onDragLeave={handleDragLeave}
            className={`flex flex-col items-center justify-center gap-1.5 p-4 rounded-md border border-dashed transition-colors ${
              isDragOver
                ? 'border-[var(--primary-color)] bg-[rgba(99,102,241,0.08)]'
                : 'border-[var(--border-color)] bg-[var(--bg-primary)]'
            }`}
          >
            <FileUp size={20} className="text-[var(--text-muted)] opacity-70" />
            <p className="text-[0.75rem] text-[var(--text-secondary)]">
              {t('importEnvironment.dropHint')}
            </p>
            <button
              onClick={() => fileInputRef.current?.click()}
              className="mt-1 flex items-center gap-1.5 py-1 px-2.5 rounded-md bg-[var(--bg-secondary)] border border-[var(--border-color)] text-[0.6875rem] font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] cursor-pointer transition-colors"
            >
              <Upload size={11} />
              {t('importEnvironment.chooseFile')}
            </button>
            <input
              ref={fileInputRef}
              type="file"
              accept="application/json,.json"
              onChange={handleFileInput}
              className="hidden"
            />
            {fileName && (
              <p className="text-[0.6875rem] text-[var(--text-muted)]">
                {t('importEnvironment.loadedFile', { name: fileName })}
              </p>
            )}
          </div>

          {/* Paste area */}
          <div className="flex flex-col gap-1">
            <label className="text-[0.75rem] font-medium text-[var(--text-secondary)]">
              {t('importEnvironment.jsonLabel')}
            </label>
            <textarea
              value={rawText}
              onChange={e => setRawText(e.target.value)}
              placeholder={t('importEnvironment.jsonPlaceholder')}
              className="w-full min-h-[140px] max-h-[260px] py-2 px-2.5 bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-md text-[0.75rem] font-mono text-[var(--text-primary)] focus:outline-none focus:border-[var(--primary-color)]"
            />
            <p className="text-[0.6875rem] text-[var(--text-muted)]">
              {t('importEnvironment.jsonHint')}
            </p>
          </div>

          {/* Parse feedback */}
          {parseError && (
            <div className="flex items-start gap-2 px-3 py-2 rounded-md bg-[rgba(239,68,68,0.1)] border border-[rgba(239,68,68,0.3)]">
              <AlertTriangle size={14} className="text-[var(--danger-color)] mt-0.5 shrink-0" />
              <div className="text-[0.75rem] text-[var(--danger-color)]">{parseError}</div>
            </div>
          )}

          {parsed && parsed.ok && parsed.kind === 'single' && (
            <div className="px-3 py-2 rounded-md bg-[rgba(34,197,94,0.1)] border border-[rgba(34,197,94,0.25)] text-[0.75rem] text-[#4ade80]">
              {t('importEnvironment.parsedOk', {
                mode: parsed.meta.mode,
                version: parsed.meta.version ?? '—',
                count: parsed.meta.stageCount ?? 0,
                name: parsed.meta.name ?? '—',
              })}
            </div>
          )}

          {parsed && parsed.ok && parsed.kind === 'bundle' && !bundleResult && (
            <div className="flex flex-col gap-1.5 px-3 py-2 rounded-md bg-[rgba(34,197,94,0.1)] border border-[rgba(34,197,94,0.25)]">
              <div className="text-[0.75rem] text-[#4ade80] font-medium">
                {t('importEnvironment.bundleDetected', {
                  n: String(parsed.entries.length),
                  version: parsed.bundleVersion,
                })}
              </div>
              <ul className="flex flex-col gap-0.5 text-[0.6875rem] text-[var(--text-secondary)] max-h-[160px] overflow-y-auto pl-3">
                {parsed.entries.map((e, i) => (
                  <li key={e.env_id ?? i} className="flex items-center gap-2 truncate">
                    <span className="shrink-0 text-[var(--text-muted)] font-mono">
                      {String(i + 1).padStart(2, '0')}.
                    </span>
                    <span className="truncate">{e.meta.name || e.env_id || '—'}</span>
                    <span className="ml-auto shrink-0 text-[0.625rem] text-[var(--text-muted)]">
                      {e.meta.mode}
                      {typeof e.meta.stageCount === 'number' && ` · ${e.meta.stageCount} stage(s)`}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          )}

          {bundleResult && (
            <div className="flex flex-col gap-1.5 px-3 py-2 rounded-md border border-[var(--border-color)] bg-[var(--bg-primary)]">
              <div className="text-[0.75rem] font-medium text-[var(--text-primary)]">
                {t('importEnvironment.bundleReport', {
                  ok: String(bundleResult.successes.length),
                  fail: String(bundleResult.failures.length),
                })}
              </div>
              {bundleResult.successes.length > 0 && (
                <ul className="flex flex-col gap-0.5 text-[0.6875rem] max-h-[120px] overflow-y-auto">
                  {bundleResult.successes.map(s => (
                    <li key={s.new_id} className="flex items-center gap-2 text-[#4ade80]">
                      <Check size={10} />
                      <span className="truncate">{s.name}</span>
                      <span className="ml-auto shrink-0 font-mono text-[0.625rem] text-[var(--text-muted)]">
                        {s.new_id}
                      </span>
                    </li>
                  ))}
                </ul>
              )}
              {bundleResult.failures.length > 0 && (
                <ul className="flex flex-col gap-0.5 text-[0.6875rem] max-h-[120px] overflow-y-auto">
                  {bundleResult.failures.map((f, i) => (
                    <li key={i} className="flex items-start gap-2 text-[var(--danger-color)]">
                      <AlertTriangle size={10} className="mt-0.5 shrink-0" />
                      <div className="flex flex-col min-w-0">
                        <span className="truncate">{f.name}</span>
                        <span className="text-[var(--text-muted)] truncate">{f.error}</span>
                      </div>
                    </li>
                  ))}
                </ul>
              )}
            </div>
          )}

          {/* Name override (single-env only) */}
          {(!parsed || !parsed.ok || parsed.kind === 'single') && (
            <div className="flex flex-col gap-1">
              <label className="text-[0.75rem] font-medium text-[var(--text-secondary)]">
                {t('importEnvironment.nameOverrideLabel')}
              </label>
              <input
                type="text"
                value={nameOverride}
                onChange={e => setNameOverride(e.target.value)}
                placeholder={parsed?.ok && parsed.kind === 'single' && parsed.meta.name ? parsed.meta.name : t('importEnvironment.nameOverridePlaceholder')}
                className="w-full py-2 px-2.5 bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-md text-[0.8125rem] text-[var(--text-primary)] focus:outline-none focus:border-[var(--primary-color)]"
              />
              <p className="text-[0.6875rem] text-[var(--text-muted)]">
                {t('importEnvironment.nameOverrideHint')}
              </p>
            </div>
          )}

          {/* Regenerate id toggle */}
          <label className="flex items-start gap-2 cursor-pointer">
            <input
              type="checkbox"
              checked={regenerateId}
              onChange={e => setRegenerateId(e.target.checked)}
              className="mt-0.5"
            />
            <div className="flex flex-col gap-0.5">
              <span className="text-[0.75rem] font-medium text-[var(--text-secondary)]">
                {t('importEnvironment.regenerateIdLabel')}
              </span>
              <span className="text-[0.6875rem] text-[var(--text-muted)]">
                {t('importEnvironment.regenerateIdHint')}
              </span>
            </div>
          </label>

          {/* Submit feedback */}
          {submitError && (
            <div className="flex items-start gap-2 px-3 py-2 rounded-md bg-[rgba(239,68,68,0.1)] border border-[rgba(239,68,68,0.3)]">
              <AlertTriangle size={14} className="text-[var(--danger-color)] mt-0.5 shrink-0" />
              <div className="text-[0.75rem] text-[var(--danger-color)]">{submitError}</div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 py-3 px-5 border-t border-[var(--border-color)] shrink-0">
          <button
            onClick={onClose}
            className="py-1.5 px-3 rounded-md bg-transparent border border-[var(--border-color)] text-[0.75rem] font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] cursor-pointer transition-colors"
          >
            {t('common.cancel')}
          </button>
          {bundleResult ? (
            <button
              onClick={onClose}
              className="py-1.5 px-3 rounded-md bg-[var(--primary-color)] hover:bg-[var(--primary-hover)] text-white text-[0.75rem] font-semibold cursor-pointer border-none transition-colors"
            >
              {t('common.done')}
            </button>
          ) : (
            <button
              onClick={handleConfirm}
              disabled={!ready || submitting}
              className="py-1.5 px-3 rounded-md bg-[var(--primary-color)] hover:bg-[var(--primary-hover)] text-white text-[0.75rem] font-semibold cursor-pointer border-none transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
            >
              {submitting
                ? parsed && parsed.ok && parsed.kind === 'bundle'
                  ? t('importEnvironment.importingBundle', { n: String(parsed.entries.length) })
                  : t('importEnvironment.importing')
                : parsed && parsed.ok && parsed.kind === 'bundle'
                  ? t('importEnvironment.importBundleButton', { n: String(parsed.entries.length) })
                  : t('importEnvironment.importButton')}
            </button>
          )}
        </div>
      </div>
    </div>,
    document.body,
  );
}
