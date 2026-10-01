'use client';

/**
 * CanvasTab — the session files-workspace browser + live document preview.
 *
 * workspace-canvas P4 (docs/workspace-canvas-plan/01_PLAN.md). Shows the
 * session's `workspace/` tree (uploads / drafts / outputs convention) on the
 * left and a type-aware preview on the right:
 *   - images        → inline <img> (storage-raw, cookie-auth'd)
 *   - pdf           → <iframe>
 *   - office drafts → the drafts/<job>/preview/page-N.png pager the editing
 *                     tools (doc_edit / doc_generate / doc_convert) regenerate
 *   - text/code/md  → FileViewer (existing renderer)
 * Work-in-progress drafts surface as a band up top. Polls every 5s so an
 * in-flight edit's preview refreshes while the agent works.
 */

import { useState, useEffect, useCallback, useMemo, useRef } from 'react';
import { useAppStore } from '@/store/useAppStore';
import { agentApi } from '@/lib/api';
import { getToken } from '@/lib/authApi';
import { useI18n } from '@/lib/i18n';
import {
  RefreshCw, Download, FileText, Image as ImageIcon, Presentation,
  FileSpreadsheet, File as FileIcon, ChevronLeft, ChevronRight, Palette,
} from 'lucide-react';
import { TabShell, IconButton, EmptyState } from '@/components/common/layout';
import { FileViewer } from '@/components/file-viewer';
import type { StorageFile } from '@/types';

const POLL_MS = 5_000;
const TEXT_MAX_BYTES = 2 * 1024 * 1024;
const IMAGE_EXTS = new Set(['png', 'jpg', 'jpeg', 'gif', 'webp', 'svg']);
const OFFICE_EXTS = new Set(['pptx', 'docx', 'xlsx', 'xlsm', 'ppt', 'doc', 'xls', 'odt', 'odp', 'ods']);
const BINARY_EXTS = new Set(['zip', 'gz', 'tar', 'exe', 'bin', 'mp3', 'mp4', 'wav', 'ogg', 'woff', 'woff2']);

function ext(path: string): string {
  const i = path.lastIndexOf('.');
  return i >= 0 ? path.slice(i + 1).toLowerCase() : '';
}

function fileIcon(path: string) {
  const e = ext(path);
  if (IMAGE_EXTS.has(e)) return ImageIcon;
  if (e === 'pptx' || e === 'ppt' || e === 'odp') return Presentation;
  if (e === 'xlsx' || e === 'xls' || e === 'csv' || e === 'ods') return FileSpreadsheet;
  if (e === 'md' || e === 'txt' || e === 'docx' || e === 'doc') return FileText;
  return FileIcon;
}

function fmtSize(n?: number | null): string {
  if (n == null) return '';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(1)} MB`;
}

/**
 * Fetch a (gated) asset with the Bearer token → blob URL. A bare `<img src>` /
 * `<a href>` / `<iframe src>` can only carry the same-origin cookie, which the
 * desktop connector doesn't have (it boots from a URL token into localStorage).
 * That is why previews / downloads 401'd there. Authenticated fetch → blob
 * works in the web app AND the connector. Revokes the object URL on cleanup.
 */
function useAuthedBlob(url: string | null): { blobUrl: string | null; error: boolean } {
  const [blobUrl, setBlobUrl] = useState<string | null>(null);
  const [error, setError] = useState(false);
  useEffect(() => {
    if (!url) { setBlobUrl(null); setError(false); return; }
    let cancelled = false;
    let obj: string | null = null;
    setBlobUrl(null);
    setError(false);
    const token = getToken();
    fetch(url, { headers: token ? { Authorization: `Bearer ${token}` } : {} })
      .then((r) => { if (!r.ok) throw new Error(`HTTP ${r.status}`); return r.blob(); })
      .then((b) => { if (cancelled) return; obj = URL.createObjectURL(b); setBlobUrl(obj); })
      .catch(() => { if (!cancelled) setError(true); });
    return () => { cancelled = true; if (obj) URL.revokeObjectURL(obj); };
  }, [url]);
  return { blobUrl, error };
}

function AuthedImg({ url, alt, className }: { url: string; alt: string; className?: string }) {
  const { blobUrl, error } = useAuthedBlob(url);
  if (error) {
    return (
      <div className="text-[0.75rem] text-[var(--text-muted)] p-4">
        🖼️ 미리보기를 불러오지 못했습니다.
      </div>
    );
  }
  if (!blobUrl) {
    return <div className="w-40 h-56 rounded-md bg-[var(--bg-hover)] animate-pulse" />;
  }
  return <img src={blobUrl} alt={alt} className={className} />;
}

function PdfPreview({ url }: { url: string }) {
  const { blobUrl, error } = useAuthedBlob(url);
  if (error) {
    return (
      <div className="h-full flex items-center justify-center text-[0.8125rem] text-[var(--text-muted)]">
        PDF를 불러오지 못했습니다.
      </div>
    );
  }
  if (!blobUrl) {
    return <div className="w-full h-full rounded-md bg-[var(--bg-hover)] animate-pulse" />;
  }
  return (
    <iframe
      src={blobUrl}
      title="pdf"
      className="w-full h-full rounded-md border border-[var(--border-color)] bg-white"
    />
  );
}

/** Authenticated download → blob → save (Bearer, not the cookie). */
async function authedDownload(url: string, filename: string): Promise<void> {
  const token = getToken();
  const res = await fetch(url, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  if (!res.ok) throw new Error(`HTTP ${res.status}`);
  const blob = await res.blob();
  const obj = URL.createObjectURL(blob);
  const a = document.createElement('a');
  a.href = obj;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(obj);
}

function DownloadButton({ url, filename }: { url: string; filename: string }) {
  const { t } = useI18n();
  const [busy, setBusy] = useState(false);
  return (
    <IconButton
      icon={Download}
      title={t('canvasTab.download')}
      spin={busy}
      disabled={busy}
      onClick={async () => {
        setBusy(true);
        try { await authedDownload(url, filename); } catch { /* ignore */ }
        setBusy(false);
      }}
    />
  );
}

/** Slide/page pager over preview pages (draft PNGs or on-demand SVG/PNG). */
function PreviewPager({ pages, rawUrl }: { pages: string[]; rawUrl: (p: string) => string }) {
  const [idx, setIdx] = useState(0);
  useEffect(() => { setIdx(0); }, [pages.length, pages[0]]);
  if (!pages.length) return null;
  const clamped = Math.min(idx, pages.length - 1);
  return (
    <div className="flex flex-col items-center gap-2 h-full min-h-0">
      <div className="flex-1 min-h-0 flex items-center justify-center w-full">
        <AuthedImg
          url={rawUrl(pages[clamped])}
          alt={`page ${clamped + 1}`}
          className="max-w-full max-h-full object-contain rounded-md border border-[var(--border-color)] shadow-sm bg-white"
        />
      </div>
      <div className="flex items-center gap-2 shrink-0 pb-1">
        <button
          className="w-7 h-7 rounded-md border border-[var(--border-color)] flex items-center justify-center text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] disabled:opacity-30"
          disabled={clamped <= 0}
          onClick={() => setIdx(clamped - 1)}
        >
          <ChevronLeft size={14} />
        </button>
        <span className="text-[0.6875rem] text-[var(--text-muted)] font-mono">
          {clamped + 1} / {pages.length}
        </span>
        <button
          className="w-7 h-7 rounded-md border border-[var(--border-color)] flex items-center justify-center text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] disabled:opacity-30"
          disabled={clamped >= pages.length - 1}
          onClick={() => setIdx(clamped + 1)}
        >
          <ChevronRight size={14} />
        </button>
      </div>
    </div>
  );
}

export default function CanvasTab() {
  const { selectedSessionId, canvasFocus, clearCanvasFocus } = useAppStore();
  const { t } = useI18n();
  const [files, setFiles] = useState<StorageFile[]>([]);
  const [selected, setSelected] = useState<string | null>(null);
  const [textContent, setTextContent] = useState<string | null>(null);
  const [loadingText, setLoadingText] = useState(false);
  const [refreshing, setRefreshing] = useState(false);
  // On-demand server-rendered preview for an office file with no live draft
  // pages (e.g. a freshly uploaded deck). Keyed to the path it was rendered for.
  const [docPreview, setDocPreview] = useState<{ path: string; pages: string[] } | null>(null);
  const [docPreviewErr, setDocPreviewErr] = useState(false);

  // path → mtime: the cache-buster key. The doc tools overwrite
  // preview/page-N.png in place, so the URL must change when the bytes
  // do — otherwise the <img> keeps showing the pre-edit render.
  const mtimeByPath = useMemo(() => {
    const map: Record<string, string> = {};
    for (const f of files) {
      if (f.modified_at) map[f.path] = String(f.modified_at);
    }
    return map;
  }, [files]);

  const rawUrl = useCallback(
    (path: string) => {
      const base = `/api/agents/${selectedSessionId}/storage-raw/${path}`;
      const v = mtimeByPath[path];
      return v ? `${base}?v=${encodeURIComponent(v)}` : base;
    },
    [selectedSessionId, mtimeByPath],
  );

  const refresh = useCallback(async () => {
    if (!selectedSessionId) return;
    try {
      // The workspace scope, not 'all': `workspace/` is a link into the
      // user's cloud, and the whole-session listing does not follow it —
      // every agent's canvas read "the workspace is empty" while its files
      // sat right there. Paths here are relative to the workspace; the rest
      // of this tab (and storage-raw) speaks session-root paths.
      const res = await agentApi.listStorage(selectedSessionId, 'workspace');
      setFiles(
        (res.files || [])
          .filter((f) => !(f.is_dir ?? f.is_directory))
          .map((f) => ({ ...f, path: `workspace/${f.path}` })),
      );
    } catch { /* session may be dormant; keep last view */ }
  }, [selectedSessionId]);

  useEffect(() => {
    setSelected(null);
    setTextContent(null);
    refresh();
    const id = window.setInterval(refresh, POLL_MS);
    return () => window.clearInterval(id);
  }, [refresh]);

  // ── derived: sections + drafts ──────────────────────────────────
  const sections = useMemo(() => {
    const by: Record<string, StorageFile[]> = { uploads: [], drafts: [], outputs: [], other: [] };
    for (const f of files) {
      const seg = f.path.split('/')[1] ?? '';
      (by[seg] ?? by.other).push(f);
    }
    return by;
  }, [files]);

  // drafts/<job>/preview/page-N.png → pages per job dir
  const previewsByDir = useMemo(() => {
    const map: Record<string, string[]> = {};
    for (const f of files) {
      const m = f.path.match(/^(workspace\/drafts\/[^/]+)\/preview\/page-\d+\.png$/);
      if (m) (map[m[1]] ??= []).push(f.path);
    }
    for (const k of Object.keys(map)) {
      map[k].sort((a, b) => a.localeCompare(b, undefined, { numeric: true }));
    }
    return map;
  }, [files]);

  const draftJobs = useMemo(() => {
    const jobs = new Map<string, { doc: StorageFile | null; pages: string[] }>();
    for (const f of sections.drafts) {
      const m = f.path.match(/^workspace\/drafts\/([^/]+)\/([^/]+)$/);
      if (m && OFFICE_EXTS.has(ext(m[2]))) {
        jobs.set(m[1], {
          doc: f,
          pages: previewsByDir[`workspace/drafts/${m[1]}`] ?? [],
        });
      }
    }
    return jobs;
  }, [sections.drafts, previewsByDir]);

  // ── auto-select: follow the document being edited ────────────────
  // A manual click "pins" the user's choice; agent activity (a draft
  // doc whose mtime advances, or a brand-new draft) auto-selects only
  // when nothing is pinned. Chat's "open in canvas" affordance sets
  // canvasFocus, which wins once and pins.
  const pinnedRef = useRef(false);
  const lastDraftStampRef = useRef<string>('');

  const selectFile = useCallback((path: string, opts?: { pin?: boolean }) => {
    setSelected(path);
    if (opts?.pin) pinnedRef.current = true;
  }, []);

  useEffect(() => {
    pinnedRef.current = false;
    lastDraftStampRef.current = '';
  }, [selectedSessionId]);

  useEffect(() => {
    if (!canvasFocus) return;
    // Deferred so the store update never happens synchronously inside
    // the effect (react-hooks/set-state-in-effect).
    const t = window.setTimeout(() => {
      // uploads/x.docx → its draft copy when one exists (that's what
      // the agent actually edited and what carries the preview pages).
      let target = canvasFocus;
      const m = canvasFocus.match(/^workspace\/(?:uploads|outputs)\/([^/]+)$/);
      if (m) {
        const stem = m[1].replace(/\.[^.]+$/, '');
        const draft = `workspace/drafts/${stem}/${m[1]}`;
        if (files.some((f) => f.path === draft)) target = draft;
      }
      if (files.some((f) => f.path === target)) {
        selectFile(target, { pin: true });
        clearCanvasFocus();
      }
    }, 0);
    return () => window.clearTimeout(t);
  }, [canvasFocus, files, selectFile, clearCanvasFocus]);

  useEffect(() => {
    let latestPath = '';
    let latestStamp = '';
    for (const [, info] of draftJobs) {
      if (!info.doc) continue;
      const stamp = mtimeByPath[info.doc.path] ?? '';
      if (stamp > latestStamp) {
        latestStamp = stamp;
        latestPath = info.doc.path;
      }
    }
    if (!latestPath || latestStamp === lastDraftStampRef.current) return;
    const isFirstScan = lastDraftStampRef.current === '';
    lastDraftStampRef.current = latestStamp;
    // Skip on the very first scan (session open) unless nothing is
    // selected — only *new* agent activity should steal focus.
    if (pinnedRef.current) return;
    if (isFirstScan && selected) return;
    const t = window.setTimeout(() => setSelected(latestPath), 0);
    return () => window.clearTimeout(t);
  }, [draftJobs, mtimeByPath, selected]);

  // ── selection → load text when previewable as text ──────────────
  const selectedFile = useMemo(
    () => files.find((f) => f.path === selected) ?? null,
    [files, selected],
  );
  const selectedExt = selected ? ext(selected) : '';
  const selectedKind: 'image' | 'pdf' | 'office' | 'text' | 'binary' = !selected
    ? 'binary'
    : IMAGE_EXTS.has(selectedExt)
      ? 'image'
      : selectedExt === 'pdf'
        ? 'pdf'
        : OFFICE_EXTS.has(selectedExt)
          ? 'office'
          : BINARY_EXTS.has(selectedExt) || (selectedFile?.size ?? 0) > TEXT_MAX_BYTES
            ? 'binary'
            : 'text';

  useEffect(() => {
    setTextContent(null);
    if (!selected || !selectedSessionId || selectedKind !== 'text') return;
    let cancelled = false;
    setLoadingText(true);
    agentApi
      .getStorageFile(selectedSessionId, selected)
      .then((res) => { if (!cancelled) setTextContent(res.content ?? ''); })
      .catch(() => { if (!cancelled) setTextContent(null); })
      .finally(() => { if (!cancelled) setLoadingText(false); });
    return () => { cancelled = true; };
  }, [selected, selectedSessionId, selectedKind]);

  // office file selected → its draft preview pages (same dir), if any
  const officePages = useMemo(() => {
    if (!selected || selectedKind !== 'office') return [];
    const dir = selected.slice(0, selected.lastIndexOf('/'));
    return previewsByDir[dir] ?? [];
  }, [selected, selectedKind, previewsByDir]);

  // Office file with no live draft pages (uploads, outputs) → auto-render a
  // preview server-side (edit2docs, cached). Fires on selection; no agent turn.
  useEffect(() => {
    setDocPreview(null);
    setDocPreviewErr(false);
    if (!selected || !selectedSessionId || selectedKind !== 'office') return;
    if (officePages.length > 0) return; // live draft pages already cover it
    let cancelled = false;
    const target = selected;
    agentApi
      .docPreview(selectedSessionId, target)
      .then((res) => {
        if (cancelled) return;
        if (res.pages?.length) setDocPreview({ path: target, pages: res.pages });
        else setDocPreviewErr(true);
      })
      .catch(() => { if (!cancelled) setDocPreviewErr(true); });
    return () => { cancelled = true; };
  }, [selected, selectedSessionId, selectedKind, officePages.length]);

  // Pages to show for the office preview: live draft pages first, else on-demand.
  const officePreviewPages =
    officePages.length > 0
      ? officePages
      : docPreview && docPreview.path === selected
        ? docPreview.pages
        : [];

  if (!selectedSessionId) {
    return (
      <TabShell title={t('tabs.canvas')} icon={Palette}>
        <EmptyState icon={Palette} title={t('canvasTab.selectSession')} />
      </TabShell>
    );
  }

  const SECTION_LABELS: Record<string, string> = {
    uploads: t('canvasTab.uploads'),
    drafts: t('canvasTab.drafts'),
    outputs: t('canvasTab.outputs'),
    other: t('canvasTab.other'),
  };

  return (
    <TabShell
      title={t('tabs.canvas')}
      icon={Palette}
      actions={
        <IconButton
          icon={RefreshCw}
          title={t('common.refresh')}
          spin={refreshing}
          onClick={async () => { setRefreshing(true); await refresh(); setRefreshing(false); }}
        />
      }
    >
      <div className="flex h-full min-h-0">
        {/* ── left: workspace tree ── */}
        <div className="w-72 shrink-0 border-r border-[var(--border-color)] overflow-y-auto p-3 flex flex-col gap-3">
          {files.length === 0 && (
            <p className="text-[0.75rem] text-[var(--text-muted)] px-1 py-2">
              {t('canvasTab.empty')}
            </p>
          )}
          {(['drafts', 'uploads', 'outputs', 'other'] as const).map((sec) => {
            const list = sections[sec];
            if (!list?.length) return null;
            return (
              <div key={sec}>
                <div className="text-[0.625rem] font-semibold uppercase tracking-wider text-[var(--text-muted)] px-1 mb-1">
                  {SECTION_LABELS[sec]}
                </div>
                <div className="flex flex-col">
                  {list
                    .filter((f) => !/\/preview\/page-\d+\.png$/.test(f.path))
                    .map((f) => {
                      const Icon = fileIcon(f.path);
                      const label = f.path.split('/').slice(2).join('/') || f.path.split('/').pop() || f.path;
                      const active = selected === f.path;
                      return (
                        <button
                          key={f.path}
                          onClick={() => selectFile(f.path, { pin: true })}
                          className={`flex items-center gap-1.5 px-2 py-1.5 rounded-md text-left text-[0.75rem] transition-colors ${
                            active
                              ? 'bg-[hsl(var(--accent))] text-[var(--text-primary)]'
                              : 'text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]'
                          }`}
                        >
                          <Icon size={13} className="shrink-0 text-[var(--text-muted)]" />
                          <span className="truncate flex-1">{label}</span>
                          <span className="text-[0.625rem] text-[var(--text-muted)] shrink-0">
                            {fmtSize(f.size)}
                          </span>
                        </button>
                      );
                    })}
                </div>
              </div>
            );
          })}
        </div>

        {/* ── right: preview ── */}
        <div className="flex-1 min-w-0 min-h-0 flex flex-col">
          {/* working drafts band */}
          {draftJobs.size > 0 && (
            <div className="shrink-0 px-4 py-2 border-b border-[var(--border-color)] flex items-center gap-2 flex-wrap bg-[hsl(var(--card))]">
              <span className="text-[0.6875rem] font-semibold text-[var(--text-muted)] uppercase tracking-wider">
                {t('canvasTab.working')}
              </span>
              {[...draftJobs.entries()].map(([job, info]) => (
                <button
                  key={job}
                  onClick={() => info.doc && selectFile(info.doc.path, { pin: true })}
                  className="inline-flex items-center gap-1.5 px-2 py-1 rounded-md border border-[var(--border-color)] text-[0.6875rem] text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]"
                >
                  <Presentation size={11} className="text-[hsl(var(--primary))]" />
                  {job}
                  {info.pages.length > 0 && (
                    <span className="text-[var(--text-muted)]">({info.pages.length}p)</span>
                  )}
                </button>
              ))}
            </div>
          )}

          <div className="flex-1 min-h-0 p-4 overflow-auto">
            {!selected ? (
              <EmptyState icon={Palette} title={t('canvasTab.selectFile')} />
            ) : selectedKind === 'image' ? (
              <div className="h-full flex items-center justify-center">
                <AuthedImg
                  url={rawUrl(selected)}
                  alt={selected}
                  className="max-w-full max-h-full object-contain rounded-md border border-[var(--border-color)]"
                />
              </div>
            ) : selectedKind === 'pdf' ? (
              <PdfPreview url={rawUrl(selected)} />
            ) : selectedKind === 'office' ? (
              officePreviewPages.length > 0 ? (
                <PreviewPager pages={officePreviewPages} rawUrl={rawUrl} />
              ) : docPreviewErr ? (
                <div className="h-full flex flex-col items-center justify-center gap-3 text-center">
                  <Presentation size={32} className="text-[var(--text-muted)] opacity-40" />
                  <p className="text-[0.8125rem] text-[var(--text-muted)] max-w-[420px]">
                    {t('canvasTab.noPreview')}
                  </p>
                  <DownloadButton url={rawUrl(selected)} filename={selected.split('/').pop() || selected} />
                </div>
              ) : (
                <div className="h-full flex flex-col items-center justify-center gap-3">
                  <div className="w-8 h-8 rounded-full border-2 border-[var(--border-color)] border-t-[hsl(var(--primary))] animate-spin" />
                  <p className="text-[0.75rem] text-[var(--text-muted)]">미리보기 생성 중…</p>
                </div>
              )
            ) : selectedKind === 'text' ? (
              loadingText ? (
                <p className="text-[0.75rem] text-[var(--text-muted)]">…</p>
              ) : textContent != null ? (
                <FileViewer content={textContent} fileName={selected.split('/').pop() || selected} />
              ) : (
                <p className="text-[0.75rem] text-[var(--text-muted)]">{t('canvasTab.loadFailed')}</p>
              )
            ) : (
              <div className="h-full flex flex-col items-center justify-center gap-3">
                <FileIcon size={32} className="text-[var(--text-muted)] opacity-40" />
                <DownloadButton url={rawUrl(selected)} filename={selected.split('/').pop() || selected} />
              </div>
            )}
          </div>
        </div>
      </div>
    </TabShell>
  );
}
