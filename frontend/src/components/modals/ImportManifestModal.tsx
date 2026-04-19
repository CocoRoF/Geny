'use client';

/**
 * ImportManifestModal — overwrite an existing environment's manifest
 * from a JSON file or pasted text.
 *
 * The backend already exposes two entry points:
 *   - `POST /api/environments/import` creates a *new* env from an
 *     exported blob (already wired via CreateEnvironmentModal).
 *   - `PUT /api/environments/{id}/manifest` replaces the manifest in
 *     place (reused here via `replaceManifest`).
 *
 * This modal targets the second: it parses a user-provided JSON blob
 * into `EnvironmentManifest`, validates the shape, and — after an
 * explicit "this will overwrite N stages" confirmation row — calls
 * `replaceManifest(envId, parsed)`.
 */

import { useEffect, useMemo, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { AlertTriangle, ChevronDown, ChevronRight, FileUp, Minus, Pencil, Plus, Upload, X } from 'lucide-react';

import { useEnvironmentStore } from '@/store/useEnvironmentStore';
import { useI18n } from '@/lib/i18n';
import { diffManifests } from '@/lib/environmentDiff';
import type { EnvironmentManifest } from '@/types/environment';

interface Props {
  envId: string;
  envName: string;
  onClose: () => void;
  onImported?: () => void;
}

type ParseResult =
  | { ok: true; manifest: EnvironmentManifest }
  | { ok: false; error: string };

function extractManifest(parsed: unknown): ParseResult {
  if (!parsed || typeof parsed !== 'object' || Array.isArray(parsed)) {
    return { ok: false, error: 'Root must be a JSON object' };
  }
  const obj = parsed as Record<string, unknown>;

  // Support both raw manifest objects and exported-env envelopes like
  // `{manifest: {...}}` or `{data: {manifest: {...}}}` — whichever the
  // user pasted. Pick the first shape that has a `version` + `stages`.
  const candidates: unknown[] = [obj];
  if ('manifest' in obj) candidates.push(obj.manifest);
  if ('data' in obj && obj.data && typeof obj.data === 'object') {
    candidates.push((obj.data as Record<string, unknown>).manifest);
    candidates.push(obj.data);
  }

  for (const c of candidates) {
    if (!c || typeof c !== 'object' || Array.isArray(c)) continue;
    const cand = c as Record<string, unknown>;
    if (typeof cand.version !== 'string') continue;
    if (!Array.isArray(cand.stages)) continue;
    return { ok: true, manifest: cand as unknown as EnvironmentManifest };
  }

  return {
    ok: false,
    error: 'Missing required fields (version, stages) — not an EnvironmentManifest',
  };
}

export default function ImportManifestModal({ envId, envName, onClose, onImported }: Props) {
  const { replaceManifest, selectedEnvironment, loadEnvironment } = useEnvironmentStore();
  const { t } = useI18n();

  const [rawText, setRawText] = useState('');
  const [fileName, setFileName] = useState<string | null>(null);
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState('');
  const [showDiff, setShowDiff] = useState(false);
  const fileInputRef = useRef<HTMLInputElement | null>(null);

  // Ensure the current manifest is loaded so we can diff against it.
  // The drawer that opens us usually has it cached already, but preview
  // should work even if invoked standalone later.
  useEffect(() => {
    if (!selectedEnvironment || selectedEnvironment.id !== envId) {
      loadEnvironment(envId).catch(() => {});
    }
  }, [envId, selectedEnvironment, loadEnvironment]);

  const currentManifest =
    selectedEnvironment && selectedEnvironment.id === envId
      ? selectedEnvironment.manifest ?? null
      : null;

  const parsed = useMemo<ParseResult | null>(() => {
    const trimmed = rawText.trim();
    if (!trimmed) return null;
    try {
      const json = JSON.parse(trimmed);
      return extractManifest(json);
    } catch (e) {
      return {
        ok: false,
        error: e instanceof Error ? e.message : 'Invalid JSON',
      };
    }
  }, [rawText]);

  const manifest = parsed && parsed.ok ? parsed.manifest : null;
  const parseError = parsed && !parsed.ok ? parsed.error : null;

  const stageCount = manifest?.stages.length ?? 0;

  const diff = useMemo(() => {
    if (!manifest || !currentManifest) return null;
    return diffManifests(currentManifest, manifest);
  }, [manifest, currentManifest]);

  const diffTotal = diff
    ? diff.added.length + diff.removed.length + diff.changed.length
    : 0;

  const handleFile = async (file: File) => {
    setFileName(file.name);
    try {
      const text = await file.text();
      setRawText(text);
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
    const file = e.dataTransfer.files?.[0];
    if (file) void handleFile(file);
  };

  const handleConfirm = async () => {
    if (!manifest || submitting) return;
    setSubmitting(true);
    setSubmitError('');
    try {
      await replaceManifest(envId, manifest);
      onImported?.();
      onClose();
    } catch (e: unknown) {
      setSubmitError(e instanceof Error ? e.message : t('importManifest.failed'));
    } finally {
      setSubmitting(false);
    }
  };

  if (typeof document === 'undefined') return null;

  return createPortal(
    <div
      className="fixed inset-0 z-50 bg-black/50 backdrop-blur-sm flex items-center justify-center p-4"
      onClick={onClose}
    >
      <div
        className="bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-xl shadow-[var(--shadow-lg)] w-full max-w-[680px] max-h-[88vh] flex flex-col"
        onClick={e => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex items-start justify-between gap-3 py-3 px-5 border-b border-[var(--border-color)] shrink-0">
          <div className="flex flex-col gap-0.5 min-w-0">
            <h3 className="text-[1rem] font-semibold text-[var(--text-primary)] truncate">
              {t('importManifest.title')}
            </h3>
            <p className="text-[0.75rem] text-[var(--text-muted)] truncate">
              {t('importManifest.subtitle', { name: envName })}
            </p>
          </div>
          <button
            onClick={onClose}
            className="w-8 h-8 flex items-center justify-center rounded-md bg-transparent border-none text-[var(--text-muted)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)] cursor-pointer shrink-0"
          >
            <X size={16} />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 min-h-0 overflow-y-auto px-5 py-4 flex flex-col gap-4">
          {/* Warning */}
          <div className="flex items-start gap-2 px-3 py-2.5 rounded-md bg-[rgba(245,158,11,0.1)] border border-[rgba(245,158,11,0.3)]">
            <AlertTriangle size={14} className="text-[#f59e0b] mt-0.5 shrink-0" />
            <div className="text-[0.75rem] text-[var(--text-secondary)]">
              {t('importManifest.warning')}
            </div>
          </div>

          {/* Upload / paste row */}
          <div
            onDrop={handleDrop}
            onDragOver={e => e.preventDefault()}
            className="flex flex-col items-center justify-center gap-1.5 p-4 rounded-md border border-dashed border-[var(--border-color)] bg-[var(--bg-primary)]"
          >
            <FileUp size={20} className="text-[var(--text-muted)] opacity-70" />
            <p className="text-[0.75rem] text-[var(--text-secondary)]">
              {t('importManifest.dropHint')}
            </p>
            <button
              onClick={() => fileInputRef.current?.click()}
              className="mt-1 flex items-center gap-1.5 py-1 px-2.5 rounded-md bg-[var(--bg-secondary)] border border-[var(--border-color)] text-[0.6875rem] font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] cursor-pointer transition-colors"
            >
              <Upload size={11} />
              {t('importManifest.chooseFile')}
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
                {t('importManifest.loadedFile', { name: fileName })}
              </p>
            )}
          </div>

          {/* Paste textarea */}
          <div className="flex flex-col gap-1.5">
            <label className="text-[0.6875rem] font-semibold text-[var(--text-muted)] uppercase tracking-wide">
              {t('importManifest.jsonLabel')}
            </label>
            <textarea
              value={rawText}
              onChange={e => {
                setRawText(e.target.value);
                setFileName(null);
              }}
              rows={10}
              spellCheck={false}
              placeholder={t('importManifest.jsonPlaceholder')}
              className={`py-2 px-3 rounded-md bg-[var(--bg-primary)] border font-mono text-[0.6875rem] leading-[1.5] text-[var(--text-primary)] focus:outline-none focus:shadow-[0_0_0_3px_rgba(59,130,246,0.1)] resize-y ${
                parseError
                  ? 'border-[var(--danger-color)] focus:border-[var(--danger-color)]'
                  : 'border-[var(--border-color)] focus:border-[var(--primary-color)]'
              }`}
            />
            {parseError ? (
              <small className="text-[0.6875rem] text-[var(--danger-color)]">
                {parseError}
              </small>
            ) : manifest ? (
              <small className="text-[0.6875rem] text-[var(--success-color)]">
                {t('importManifest.parsedOk', {
                  version: manifest.version,
                  count: String(stageCount),
                })}
              </small>
            ) : (
              <small className="text-[0.6875rem] text-[var(--text-muted)]">
                {t('importManifest.jsonHint')}
              </small>
            )}
          </div>

          {/* Diff preview — current vs incoming */}
          {manifest && diff && (
            <div className="flex flex-col gap-2 px-3 py-2.5 rounded-md bg-[var(--bg-primary)] border border-[var(--border-color)]">
              <button
                type="button"
                onClick={() => setShowDiff(v => !v)}
                className="flex items-center justify-between gap-2 bg-transparent border-none p-0 cursor-pointer text-left"
              >
                <span className="flex items-center gap-1.5 text-[0.75rem] font-semibold text-[var(--text-secondary)]">
                  {showDiff ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                  {t('importManifest.diffTitle')}
                </span>
                <span className="flex items-center gap-2 text-[0.6875rem] font-mono">
                  <span className="text-[var(--success-color)]">+{diff.added.length}</span>
                  <span className="text-[var(--danger-color)]">−{diff.removed.length}</span>
                  <span className="text-[var(--text-muted)]">~{diff.changed.length}</span>
                </span>
              </button>
              {diffTotal === 0 && (
                <p className="text-[0.6875rem] text-[var(--success-color)]">
                  {t('importManifest.diffIdentical')}
                </p>
              )}
              {showDiff && diffTotal > 0 && (
                <div className="flex flex-col gap-2 mt-1 pt-2 border-t border-[var(--border-color)]">
                  {diff.added.length > 0 && (
                    <section className="flex flex-col gap-1">
                      <h5 className="flex items-center gap-1 text-[0.6875rem] font-semibold text-[var(--success-color)] uppercase tracking-wide">
                        <Plus size={10} /> {t('importManifest.diffAdded')} ({diff.added.length})
                      </h5>
                      <ul className="flex flex-col gap-0.5">
                        {diff.added.slice(0, 20).map(p => (
                          <li key={p} className="px-2 py-0.5 rounded bg-[rgba(34,197,94,0.08)] text-[0.6875rem] font-mono text-[var(--text-primary)] break-all">
                            {p}
                          </li>
                        ))}
                        {diff.added.length > 20 && (
                          <li className="text-[0.625rem] text-[var(--text-muted)] italic">
                            {t('importManifest.diffMore', { n: String(diff.added.length - 20) })}
                          </li>
                        )}
                      </ul>
                    </section>
                  )}
                  {diff.removed.length > 0 && (
                    <section className="flex flex-col gap-1">
                      <h5 className="flex items-center gap-1 text-[0.6875rem] font-semibold text-[var(--danger-color)] uppercase tracking-wide">
                        <Minus size={10} /> {t('importManifest.diffRemoved')} ({diff.removed.length})
                      </h5>
                      <ul className="flex flex-col gap-0.5">
                        {diff.removed.slice(0, 20).map(p => (
                          <li key={p} className="px-2 py-0.5 rounded bg-[rgba(239,68,68,0.08)] text-[0.6875rem] font-mono text-[var(--text-primary)] break-all">
                            {p}
                          </li>
                        ))}
                        {diff.removed.length > 20 && (
                          <li className="text-[0.625rem] text-[var(--text-muted)] italic">
                            {t('importManifest.diffMore', { n: String(diff.removed.length - 20) })}
                          </li>
                        )}
                      </ul>
                    </section>
                  )}
                  {diff.changed.length > 0 && (
                    <section className="flex flex-col gap-1">
                      <h5 className="flex items-center gap-1 text-[0.6875rem] font-semibold text-[var(--text-muted)] uppercase tracking-wide">
                        <Pencil size={10} /> {t('importManifest.diffChanged')} ({diff.changed.length})
                      </h5>
                      <ul className="flex flex-col gap-0.5">
                        {diff.changed.slice(0, 20).map(c => (
                          <li key={c.path} className="px-2 py-0.5 rounded bg-[var(--bg-secondary)] text-[0.6875rem] font-mono text-[var(--text-primary)] break-all">
                            {c.path}
                          </li>
                        ))}
                        {diff.changed.length > 20 && (
                          <li className="text-[0.625rem] text-[var(--text-muted)] italic">
                            {t('importManifest.diffMore', { n: String(diff.changed.length - 20) })}
                          </li>
                        )}
                      </ul>
                    </section>
                  )}
                </div>
              )}
            </div>
          )}

          {manifest && !currentManifest && (
            <p className="text-[0.6875rem] text-[var(--text-muted)] italic">
              {t('importManifest.diffUnavailable')}
            </p>
          )}

          {submitError && (
            <div className="px-3 py-2 rounded-md bg-[rgba(239,68,68,0.1)] border border-[rgba(239,68,68,0.3)] text-[0.75rem] text-[var(--danger-color)]">
              {submitError}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex items-center justify-end gap-2 py-3 px-5 border-t border-[var(--border-color)] shrink-0">
          <button
            onClick={onClose}
            disabled={submitting}
            className="py-1.5 px-3 rounded-md bg-transparent border border-[var(--border-color)] text-[0.75rem] font-medium text-[var(--text-secondary)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-tertiary)] cursor-pointer transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            {t('common.cancel')}
          </button>
          <button
            onClick={handleConfirm}
            disabled={!manifest || submitting}
            className="flex items-center gap-1.5 py-1.5 px-3 rounded-md bg-[var(--primary-color)] hover:bg-[var(--primary-hover)] text-white text-[0.75rem] font-semibold cursor-pointer border-none transition-colors disabled:opacity-50 disabled:cursor-not-allowed"
          >
            <Upload size={12} />
            {submitting ? t('importManifest.importing') : t('importManifest.overwriteButton')}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
