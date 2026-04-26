'use client';

import { useState, useEffect, useCallback, useMemo } from 'react';
import { useAppStore } from '@/store/useAppStore';
import { memoryApi, globalMemoryApi } from '@/lib/api';
import { useI18n } from '@/lib/i18n';
import {
  Search, Plus, RefreshCw, X, ChevronDown, ChevronRight,
  Trash2, Edit3, Save, FolderOpen, FileText, Upload, ExternalLink,
  Database,
} from 'lucide-react';
import { TabShell, EmptyState } from '@/components/layout';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { twMerge } from 'tailwind-merge';
import type {
  MemoryFileInfo, MemoryFileDetail, MemoryStats,
  MemoryIndex, MemorySearchResult,
} from '@/types';

// ==================== Helpers ====================

function cn(...classes: (string | boolean | undefined | null)[]) {
  return twMerge(classes.filter(Boolean).join(' '));
}

function formatDate(isoStr: string | null): string {
  if (!isoStr) return '';
  try {
    return new Date(isoStr).toLocaleDateString('ko-KR', {
      year: 'numeric', month: '2-digit', day: '2-digit',
      hour: '2-digit', minute: '2-digit',
    });
  } catch { return isoStr; }
}

function formatChars(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

const IMPORTANCE_DOT: Record<string, string> = {
  critical: 'bg-red-400',
  high: 'bg-orange-400',
  medium: 'bg-blue-400',
  low: 'bg-gray-500',
};

const CATEGORIES = ['daily', 'topics', 'entities', 'projects', 'insights', 'root'] as const;

// ==================== Sub-components ====================

/** Category folder node in file tree */
function CategoryFolder({
  name,
  items,
  selectedFile,
  onSelect,
  defaultOpen = true,
}: {
  name: string;
  items: MemoryFileInfo[];
  selectedFile: string | null;
  onSelect: (filename: string) => void;
  defaultOpen?: boolean;
}) {
  const [open, setOpen] = useState(defaultOpen);

  return (
    <div className="mb-0.5">
      <div
        className="flex items-center gap-1.5 py-1.5 px-2 cursor-pointer text-[13px] font-medium text-[var(--text-primary)] rounded hover:bg-[var(--bg-hover)]"
        onClick={() => setOpen(!open)}
      >
        {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        <FolderOpen size={14} className="text-[#f59e0b]" />
        <span>{name}</span>
        <span className="ml-auto text-[11px] text-[var(--text-muted)]">{items.length}</span>
      </div>
      {open && (
        <div className="pl-4 ml-2.5" style={{ borderLeft: '1px solid var(--border-color)' }}>
          {items.map(info => (
            <div
              key={info.filename}
              className={cn(
                'flex items-center gap-2 py-1.5 px-2.5 cursor-pointer rounded text-[13px] transition-colors',
                'hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]',
                selectedFile === info.filename
                  ? 'bg-[rgba(59,130,246,0.1)] text-[var(--primary-color)]'
                  : 'text-[var(--text-secondary)]'
              )}
              onClick={() => onSelect(info.filename)}
            >
              <FileText size={14} className="text-[#60a5fa] shrink-0" />
              <span className="flex-1 truncate">{info.title || info.filename}</span>
              <span className={cn(
                'w-1.5 h-1.5 rounded-full shrink-0',
                IMPORTANCE_DOT[info.importance] || 'bg-gray-500',
              )} title={info.importance} />
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

/** File tree sidebar */
function MemoryFileTree({
  files,
  selectedFile,
  onSelect,
}: {
  files: Record<string, MemoryFileInfo>;
  selectedFile: string | null;
  onSelect: (filename: string) => void;
}) {
  const grouped = useMemo(() => {
    const groups: Record<string, MemoryFileInfo[]> = {};
    for (const info of Object.values(files)) {
      const cat = info.category || 'root';
      if (!groups[cat]) groups[cat] = [];
      groups[cat].push(info);
    }
    for (const arr of Object.values(groups)) {
      arr.sort((a, b) => (b.modified || '').localeCompare(a.modified || ''));
    }
    return groups;
  }, [files]);

  return (
    <div className="flex flex-col h-full">
      {/* File list */}
      <div className="flex-1 overflow-y-auto p-1">
        {CATEGORIES.map(cat => {
          const items = grouped[cat];
          if (!items || items.length === 0) return null;
          return (
            <CategoryFolder
              key={cat}
              name={cat}
              items={items}
              selectedFile={selectedFile}
              onSelect={onSelect}
            />
          );
        })}
        {Object.keys(grouped).length === 0 && (
          <div className="flex items-center justify-center py-12 text-[var(--text-muted)] text-[13px]">
            No memory files
          </div>
        )}
      </div>
    </div>
  );
}

/** Memory note viewer — uses wiki-markdown class like StorageTab */
function MemoryViewer({
  detail,
  onEdit,
  onDelete,
  onClose,
  onPromote,
  showPromote,
}: {
  detail: MemoryFileDetail | null;
  onEdit: () => void;
  onDelete: () => void;
  onClose: () => void;
  onPromote?: () => void;
  showPromote?: boolean;
}) {
  if (!detail) {
    return (
      <div className="flex-1 bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-[var(--border-radius)] flex flex-col min-w-0">
        <div
          className="py-2.5 px-3.5 bg-[var(--bg-tertiary)] border-b border-[var(--border-color)]"
          style={{ borderRadius: 'var(--border-radius) var(--border-radius) 0 0' }}
        >
          <span className="text-[13px] font-medium text-[var(--text-secondary)]">No file selected</span>
        </div>
        <div className="flex-1 flex items-center justify-center text-[var(--text-muted)] text-[13px] py-12">
          Select a memory file to view its contents
        </div>
      </div>
    );
  }

  const meta = detail.metadata || {};
  const tags = (meta.tags as string[]) || [];
  const importance = meta.importance as string;
  const linksTo = (meta.links_to as string[]) || [];
  const linkedFrom = (meta.linked_from as string[]) || [];
  const category = meta.category as string;
  const title = (meta.title as string) || detail.filename;

  return (
    <div className="flex-1 bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-[var(--border-radius)] flex flex-col min-w-0 overflow-hidden">
      {/* Header — matches FileViewerHeader style */}
      <div
        className="flex items-center justify-between px-3 py-2 bg-[var(--bg-tertiary)] border-b border-[var(--border-color)] shrink-0"
        style={{ borderRadius: 'var(--border-radius) var(--border-radius) 0 0' }}
      >
        <div className="flex items-center gap-2 min-w-0">
          <FileText size={14} className="text-[#60a5fa] shrink-0" />
          <span className="text-[13px] font-medium text-[var(--text-primary)] truncate">
            {title}
          </span>
          {category && (
            <span className="text-[10px] px-1.5 py-[2px] rounded bg-[rgba(100,116,139,0.15)] text-[var(--text-muted)] shrink-0 font-medium">
              {category}
            </span>
          )}
          {importance && (
            <span className={cn(
              'w-2 h-2 rounded-full shrink-0',
              IMPORTANCE_DOT[importance] || 'bg-gray-500',
            )} title={importance} />
          )}
        </div>
        <div className="flex items-center gap-1 shrink-0">
          {typeof meta.modified === 'string' && (
            <span className="text-[10px] text-[var(--text-muted)] mr-2 tabular-nums">
              {formatDate(meta.modified)}
            </span>
          )}
          {showPromote && onPromote && (
            <button
              onClick={onPromote}
              className="flex items-center gap-1 px-2 py-1 rounded text-[11px] transition-all cursor-pointer border-none bg-transparent text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)]"
              title="Promote to global"
            >
              <Upload size={12} />
            </button>
          )}
          <button
            onClick={onEdit}
            className="flex items-center gap-1 px-2 py-1 rounded text-[11px] transition-all cursor-pointer border-none bg-transparent text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)]"
            title="Edit"
          >
            <Edit3 size={12} />
          </button>
          <button
            onClick={onDelete}
            className="flex items-center gap-1 px-2 py-1 rounded text-[11px] transition-all cursor-pointer border-none bg-transparent text-[var(--text-muted)] hover:text-red-400 hover:bg-[var(--bg-hover)]"
            title="Delete"
          >
            <Trash2 size={12} />
          </button>
          <button
            onClick={onClose}
            className="flex items-center gap-1 px-2 py-1 rounded text-[11px] transition-all cursor-pointer border-none bg-transparent text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)]"
            title="Close"
          >
            <X size={12} />
          </button>
        </div>
      </div>

      {/* Tags bar — only if tags exist */}
      {tags.length > 0 && (
        <div className="flex items-center gap-1.5 px-4 py-1.5 border-b border-[var(--border-color)] bg-[var(--bg-secondary)]">
          {tags.map(t => (
            <span
              key={t}
              className="text-[10px] px-1.5 py-[1px] rounded bg-[rgba(100,116,139,0.12)] text-[var(--text-muted)] font-medium"
            >
              #{t}
            </span>
          ))}
        </div>
      )}

      {/* Body — wiki-markdown like StorageTab's FileViewer/MarkdownRenderer */}
      <div className="flex-1 overflow-y-auto">
        <article className="wiki-markdown max-w-none px-6 md:px-8 py-5">
          <ReactMarkdown remarkPlugins={[remarkGfm]}>{detail.body}</ReactMarkdown>
        </article>
      </div>

      {/* Links footer — only if links exist */}
      {(linksTo.length > 0 || linkedFrom.length > 0) && (
        <div className="px-4 py-2 border-t border-[var(--border-color)] text-[11px] text-[var(--text-muted)] flex items-center gap-3 flex-wrap">
          {linksTo.length > 0 && (
            <span>
              <span className="opacity-50 mr-1">Links →</span>
              {linksTo.map((l, i) => (
                <span key={l}>
                  {i > 0 && ', '}
                  <span className="text-[var(--primary-color)]">{l.replace('.md', '')}</span>
                </span>
              ))}
            </span>
          )}
          {linkedFrom.length > 0 && (
            <span>
              <span className="opacity-50 mr-1">← From</span>
              {linkedFrom.map((l, i) => (
                <span key={l}>
                  {i > 0 && ', '}
                  <span className="text-[var(--primary-color)]">{l.replace('.md', '')}</span>
                </span>
              ))}
            </span>
          )}
        </div>
      )}
    </div>
  );
}

/** Search results panel */
function MemorySearchResults({
  results,
  onSelect,
}: {
  results: MemorySearchResult[];
  onSelect: (filename: string) => void;
}) {
  if (results.length === 0) {
    return (
      <div className="flex-1 bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-[var(--border-radius)] flex items-center justify-center text-[var(--text-muted)] text-[13px]">
        No results found
      </div>
    );
  }

  return (
    <div className="flex-1 bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-[var(--border-radius)] overflow-hidden flex flex-col">
      <div
        className="py-2.5 px-3.5 bg-[var(--bg-tertiary)] border-b border-[var(--border-color)] shrink-0"
        style={{ borderRadius: 'var(--border-radius) var(--border-radius) 0 0' }}
      >
        <span className="text-[13px] font-medium text-[var(--text-secondary)]">
          {results.length} result{results.length !== 1 ? 's' : ''}
        </span>
      </div>
      <div className="flex-1 overflow-y-auto">
        {results.map((r, i) => (
          <div
            key={i}
            onClick={() => r.entry.filename && onSelect(r.entry.filename)}
            className="px-4 py-3 border-b border-[var(--border-color)] cursor-pointer hover:bg-[var(--bg-hover)] transition-colors"
          >
            <div className="flex items-center gap-2 mb-1">
              <span className="text-[13px] font-medium text-[var(--text-primary)]">
                {r.entry.title || r.entry.filename || 'Untitled'}
              </span>
              <span className="text-[10px] px-1.5 py-[1px] rounded bg-[rgba(100,116,139,0.15)] text-[var(--text-muted)]">
                {r.score.toFixed(1)}
              </span>
              {r.entry.category && (
                <span className="text-[10px] text-[var(--text-muted)]">{r.entry.category}</span>
              )}
            </div>
            {r.snippet && (
              <p className="text-[12px] text-[var(--text-muted)] line-clamp-2 leading-relaxed">{r.snippet}</p>
            )}
            {r.entry.tags && r.entry.tags.length > 0 && (
              <div className="flex gap-1 mt-1.5">
                {r.entry.tags.map(t => (
                  <span key={t} className="text-[10px] px-1.5 py-[1px] rounded bg-[rgba(100,116,139,0.1)] text-[var(--text-muted)]">
                    #{t}
                  </span>
                ))}
              </div>
            )}
          </div>
        ))}
      </div>
    </div>
  );
}

/** Create note modal */
function MemoryCreateModal({
  onClose,
  onCreate,
}: {
  onClose: () => void;
  onCreate: (data: { title: string; content: string; category: string; tags: string[]; importance: string }) => void;
}) {
  const [title, setTitle] = useState('');
  const [content, setContent] = useState('');
  const [category, setCategory] = useState('topics');
  const [tagsStr, setTagsStr] = useState('');
  const [importance, setImportance] = useState('medium');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    if (!title.trim()) return;
    const tags = tagsStr.split(',').map(t => t.trim()).filter(Boolean);
    onCreate({ title: title.trim(), content, category, tags, importance });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={onClose}>
      <form
        onSubmit={handleSubmit}
        onClick={e => e.stopPropagation()}
        className="bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-lg shadow-2xl w-full max-w-xl mx-4"
      >
        {/* Modal header */}
        <div className="flex items-center justify-between px-5 py-3 border-b border-[var(--border-color)]">
          <h3 className="text-[14px] font-semibold text-[var(--text-primary)]">New Memory Note</h3>
          <button type="button" onClick={onClose} className="text-[var(--text-muted)] hover:text-[var(--text-primary)]">
            <X size={16} />
          </button>
        </div>

        <div className="p-5 space-y-3">
          <input
            className="w-full bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-[var(--border-radius)] px-3 py-2
                       text-[13px] text-[var(--text-primary)] placeholder:text-[var(--text-muted)] outline-none
                       focus:border-[var(--primary-color)] transition-colors"
            placeholder="Title"
            value={title}
            onChange={e => setTitle(e.target.value)}
            autoFocus
          />

          <div className="flex gap-2">
            <select
              value={category}
              onChange={e => setCategory(e.target.value)}
              className="bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-[var(--border-radius)] px-2 py-1.5
                         text-[12px] text-[var(--text-secondary)] outline-none"
            >
              {CATEGORIES.filter(c => c !== 'root').map(c => (
                <option key={c} value={c}>{c}</option>
              ))}
            </select>
            <select
              value={importance}
              onChange={e => setImportance(e.target.value)}
              className="bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-[var(--border-radius)] px-2 py-1.5
                         text-[12px] text-[var(--text-secondary)] outline-none"
            >
              {['critical', 'high', 'medium', 'low'].map(i => (
                <option key={i} value={i}>{i}</option>
              ))}
            </select>
            <input
              className="flex-1 bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-[var(--border-radius)] px-3 py-1.5
                         text-[12px] text-[var(--text-secondary)] placeholder:text-[var(--text-muted)] outline-none"
              placeholder="Tags (comma separated)"
              value={tagsStr}
              onChange={e => setTagsStr(e.target.value)}
            />
          </div>

          <textarea
            className="w-full bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-[var(--border-radius)] px-3 py-2.5
                       text-[13px] text-[var(--text-primary)] placeholder:text-[var(--text-muted)] outline-none
                       focus:border-[var(--primary-color)] transition-colors min-h-[220px] resize-y leading-relaxed"
            style={{ fontFamily: "'JetBrains Mono', 'Fira Code', monospace", fontSize: '12px' }}
            placeholder="Content (Markdown supported, use [[wikilinks]] for links)"
            value={content}
            onChange={e => setContent(e.target.value)}
          />
        </div>

        <div className="flex justify-end gap-2 px-5 py-3 border-t border-[var(--border-color)]">
          <button
            type="button"
            onClick={onClose}
            className="px-4 py-1.5 text-[12px] font-medium text-[var(--text-muted)] hover:text-[var(--text-primary)] rounded-[var(--border-radius)] hover:bg-[var(--bg-hover)] transition-colors"
          >
            Cancel
          </button>
          <button
            type="submit"
            disabled={!title.trim()}
            className="px-4 py-1.5 text-[12px] font-medium rounded-[var(--border-radius)] bg-[var(--primary-color)] text-white disabled:opacity-40 transition-opacity"
          >
            Create
          </button>
        </div>
      </form>
    </div>
  );
}

/** Edit note modal */
function MemoryEditModal({
  detail,
  onClose,
  onSave,
}: {
  detail: MemoryFileDetail;
  onClose: () => void;
  onSave: (data: { content: string; tags: string[]; importance: string }) => void;
}) {
  const meta = detail.metadata || {};
  const [content, setContent] = useState(detail.body);
  const [tagsStr, setTagsStr] = useState(((meta.tags as string[]) || []).join(', '));
  const [importance, setImportance] = useState((meta.importance as string) || 'medium');

  const handleSubmit = (e: React.FormEvent) => {
    e.preventDefault();
    const tags = tagsStr.split(',').map(t => t.trim()).filter(Boolean);
    onSave({ content, tags, importance });
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60" onClick={onClose}>
      <form
        onSubmit={handleSubmit}
        onClick={e => e.stopPropagation()}
        className="bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-lg shadow-2xl w-full max-w-2xl mx-4"
      >
        <div className="flex items-center justify-between px-5 py-3 border-b border-[var(--border-color)]">
          <h3 className="text-[14px] font-semibold text-[var(--text-primary)] truncate">
            Edit: {(meta.title as string) || detail.filename}
          </h3>
          <button type="button" onClick={onClose} className="text-[var(--text-muted)] hover:text-[var(--text-primary)]">
            <X size={16} />
          </button>
        </div>

        <div className="p-5 space-y-3">
          <div className="flex gap-2">
            <select
              value={importance}
              onChange={e => setImportance(e.target.value)}
              className="bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-[var(--border-radius)] px-2 py-1.5
                         text-[12px] text-[var(--text-secondary)] outline-none"
            >
              {['critical', 'high', 'medium', 'low'].map(i => (
                <option key={i} value={i}>{i}</option>
              ))}
            </select>
            <input
              className="flex-1 bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-[var(--border-radius)] px-3 py-1.5
                         text-[12px] text-[var(--text-secondary)] placeholder:text-[var(--text-muted)] outline-none"
              placeholder="Tags (comma separated)"
              value={tagsStr}
              onChange={e => setTagsStr(e.target.value)}
            />
          </div>

          <textarea
            className="w-full bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-[var(--border-radius)] px-3 py-2.5
                       text-[13px] text-[var(--text-primary)] outline-none
                       focus:border-[var(--primary-color)] transition-colors min-h-[340px] resize-y leading-relaxed"
            style={{ fontFamily: "'JetBrains Mono', 'Fira Code', monospace", fontSize: '12px' }}
            value={content}
            onChange={e => setContent(e.target.value)}
          />
        </div>

        <div className="flex justify-end gap-2 px-5 py-3 border-t border-[var(--border-color)]">
          <button type="button" onClick={onClose}
            className="px-4 py-1.5 text-[12px] font-medium text-[var(--text-muted)] hover:text-[var(--text-primary)] rounded-[var(--border-radius)] hover:bg-[var(--bg-hover)] transition-colors">
            Cancel
          </button>
          <button type="submit"
            className="px-4 py-1.5 text-[12px] font-medium rounded-[var(--border-radius)] bg-[var(--primary-color)] text-white flex items-center gap-1.5">
            <Save size={12} /> Save
          </button>
        </div>
      </form>
    </div>
  );
}


// ==================== Main MemoryTab ====================

export default function MemoryTab() {
  const { selectedSessionId } = useAppStore();
  const { t } = useI18n();

  // State
  const [scope, setScope] = useState<'session' | 'global'>('session');
  const [loading, setLoading] = useState(false);
  const [index, setIndex] = useState<MemoryIndex | null>(null);
  const [stats, setStats] = useState<MemoryStats | null>(null);
  const [tags, setTags] = useState<Record<string, number>>({});
  const [selectedFile, setSelectedFile] = useState<string | null>(null);
  const [fileDetail, setFileDetail] = useState<MemoryFileDetail | null>(null);
  const [selectedTag, setSelectedTag] = useState<string | null>(null);
  const [searchQuery, setSearchQuery] = useState('');
  const [searchResults, setSearchResults] = useState<MemorySearchResult[] | null>(null);
  const [, setSearching] = useState(false);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [showEditModal, setShowEditModal] = useState(false);

  const sessionId = selectedSessionId;
  const isGlobal = scope === 'global';

  // Reset selection on scope change
  useEffect(() => {
    setSelectedFile(null);
    setFileDetail(null);
    setSearchResults(null);
    setSearchQuery('');
  }, [scope]);

  // Load index + stats + tags
  const loadData = useCallback(async () => {
    if (!isGlobal && !sessionId) return;
    setLoading(true);
    try {
      if (isGlobal) {
        const indexRes = await globalMemoryApi.getIndex();
        setIndex(indexRes.index);
        setStats(indexRes.stats);
        const tagMap: Record<string, number> = {};
        if (indexRes.index?.tag_map) {
          for (const [tag, files] of Object.entries(indexRes.index.tag_map)) {
            tagMap[tag] = Array.isArray(files) ? files.length : 0;
          }
        }
        setTags(tagMap);
      } else {
        const [indexRes, tagsRes] = await Promise.all([
          memoryApi.getIndex(sessionId!),
          memoryApi.getTags(sessionId!),
        ]);
        setIndex(indexRes.index);
        setStats(indexRes.stats);
        setTags(tagsRes.tags);
      }
    } catch (err) {
      console.error('Failed to load memory data:', err);
    } finally {
      setLoading(false);
    }
  }, [sessionId, isGlobal]);

  useEffect(() => { loadData(); }, [loadData]);

  // Load file detail
  const loadFile = useCallback(async (filename: string) => {
    if (!isGlobal && !sessionId) return;
    try {
      const detail = isGlobal
        ? await globalMemoryApi.readFile(filename)
        : await memoryApi.readFile(sessionId!, filename);
      setFileDetail(detail);
      setSelectedFile(filename);
      setSearchResults(null);
    } catch (err) {
      console.error('Failed to load file:', err);
    }
  }, [sessionId, isGlobal]);

  // Search
  const handleSearch = useCallback(async (query: string) => {
    if (!isGlobal && !sessionId) return;
    if (!query.trim()) { setSearchResults(null); return; }
    setSearching(true);
    try {
      if (isGlobal) {
        const res = await globalMemoryApi.search(query);
        setSearchResults(res.results);
      } else {
        const res = await memoryApi.search(sessionId!, query, {
          tag: selectedTag || undefined,
        });
        setSearchResults(res.results);
      }
      setFileDetail(null);
      setSelectedFile(null);
    } catch (err) {
      console.error('Search failed:', err);
    } finally {
      setSearching(false);
    }
  }, [sessionId, isGlobal, selectedTag]);

  // Create note
  const handleCreate = useCallback(async (data: {
    title: string; content: string; category: string; tags: string[]; importance: string;
  }) => {
    if (!isGlobal && !sessionId) return;
    try {
      if (isGlobal) {
        await globalMemoryApi.createFile(data);
      } else {
        await memoryApi.createFile(sessionId!, data);
      }
      setShowCreateModal(false);
      await loadData();
    } catch (err) {
      console.error('Failed to create note:', err);
    }
  }, [sessionId, isGlobal, loadData]);

  // Update note
  const handleUpdate = useCallback(async (data: {
    content: string; tags: string[]; importance: string;
  }) => {
    if (!selectedFile) return;
    if (!isGlobal && !sessionId) return;
    try {
      if (isGlobal) {
        await globalMemoryApi.updateFile(selectedFile, data);
      } else {
        await memoryApi.updateFile(sessionId!, selectedFile, data);
      }
      setShowEditModal(false);
      await loadFile(selectedFile);
      await loadData();
    } catch (err) {
      console.error('Failed to update note:', err);
    }
  }, [sessionId, isGlobal, selectedFile, loadFile, loadData]);

  // Delete note
  const handleDelete = useCallback(async () => {
    if (!selectedFile) return;
    if (!isGlobal && !sessionId) return;
    if (!confirm('Delete this memory note?')) return;
    try {
      if (isGlobal) {
        await globalMemoryApi.deleteFile(selectedFile);
      } else {
        await memoryApi.deleteFile(sessionId!, selectedFile);
      }
      setSelectedFile(null);
      setFileDetail(null);
      await loadData();
    } catch (err) {
      console.error('Failed to delete note:', err);
    }
  }, [sessionId, isGlobal, selectedFile, loadData]);

  // Reindex
  const handleReindex = useCallback(async () => {
    if (!sessionId || isGlobal) return;
    try {
      await memoryApi.reindex(sessionId);
      await loadData();
    } catch (err) {
      console.error('Failed to reindex:', err);
    }
  }, [sessionId, isGlobal, loadData]);

  // Promote to global
  const handlePromote = useCallback(async () => {
    if (!sessionId || !selectedFile || isGlobal) return;
    try {
      await memoryApi.promote(sessionId, selectedFile);
      await loadData();
    } catch (err) {
      console.error('Failed to promote:', err);
    }
  }, [sessionId, selectedFile, isGlobal, loadData]);

  // No session selected (and not global mode)
  if (!sessionId && !isGlobal) {
    return (
      <TabShell title={t('memory')} icon={Database}>
        <EmptyState
          title="Select a session"
          description="Choose a session to view and manage its memory"
        />
      </TabShell>
    );
  }

  // Filtered files by tag
  const displayFiles = (() => {
    if (!index?.files) return {};
    if (!selectedTag) return index.files;
    const filtered: Record<string, MemoryFileInfo> = {};
    for (const [k, v] of Object.entries(index.files)) {
      if (v.tags?.includes(selectedTag)) filtered[k] = v;
    }
    return filtered;
  })();

  // Tag entries sorted by count
  const sortedTags = Object.entries(tags).sort((a, b) => b[1] - a[1]);

  return (
    <TabShell title={t('memory')} icon={Database}>
    <div className="flex flex-col flex-1 p-3 md:p-6 gap-3 md:gap-5 min-h-0 overflow-hidden">
      {/* Header */}
      <div className="flex justify-between items-center pb-3 border-b border-[var(--border-color)] shrink-0">
        <div className="flex items-center gap-3">
          {/* Scope toggle */}
          <div className="flex items-center rounded-[var(--border-radius)] border border-[var(--border-color)] overflow-hidden">
            <button
              onClick={() => setScope('session')}
              className={cn(
                'px-3 py-1 text-[11px] font-medium transition-colors',
                scope === 'session'
                  ? 'bg-[var(--primary-color)] text-white'
                  : 'bg-transparent text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)]',
              )}
            >
              Session
            </button>
            <button
              onClick={() => setScope('global')}
              className={cn(
                'px-3 py-1 text-[11px] font-medium transition-colors border-l border-[var(--border-color)]',
                scope === 'global'
                  ? 'bg-[var(--primary-color)] text-white'
                  : 'bg-transparent text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)]',
              )}
            >
              Global
            </button>
          </div>
          {/* Stats inline */}
          {stats && (
            <div className="hidden md:flex items-center gap-3 text-[11px] text-[var(--text-muted)]">
              <span>{stats.total_files} files</span>
              <span>{formatChars(stats.long_term_chars)} chars</span>
              <span>{stats.total_tags} tags</span>
              <span>{stats.total_links} links</span>
            </div>
          )}
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => {
              const url = sessionId
                ? `/geny-obsidian?sessionId=${encodeURIComponent(sessionId)}`
                : '/geny-obsidian';
              window.open(url, '_blank');
            }}
            className="py-1.5 px-3 bg-transparent hover:bg-[rgba(139,92,246,0.1)] text-[#8b5cf6] text-[0.75rem] font-medium rounded-[var(--border-radius)] cursor-pointer transition-all border border-[rgba(139,92,246,0.3)] inline-flex items-center gap-1.5"
          >
            <ExternalLink size={12} /> Obsidian
          </button>
          <button
            onClick={() => setShowCreateModal(true)}
            className={cn(
              'py-1.5 px-3 text-[0.75rem] font-medium inline-flex items-center gap-1.5 rounded-[var(--border-radius)] transition-all cursor-pointer',
              'bg-[var(--primary-color)] text-white hover:opacity-90',
            )}
          >
            <Plus size={12} /> New
          </button>
          <button
            onClick={() => { handleReindex(); loadData(); }}
            className="py-1.5 px-3 bg-transparent hover:bg-[var(--bg-hover)] text-[var(--text-secondary)] text-[0.75rem] font-medium rounded-[var(--border-radius)] cursor-pointer transition-all border border-[var(--border-color)] inline-flex items-center gap-1.5"
          >
            <RefreshCw size={12} /> Refresh
          </button>
        </div>
      </div>

      {/* Search + tags row */}
      <div className="flex items-center gap-3 shrink-0">
        <form
          className="flex-1 flex items-center gap-2 bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-[var(--border-radius)] px-3 py-1.5"
          onSubmit={e => { e.preventDefault(); handleSearch(searchQuery); }}
        >
          <Search size={14} className="text-[var(--text-muted)] shrink-0" />
          <input
            className="flex-1 bg-transparent text-[13px] outline-none text-[var(--text-primary)] placeholder:text-[var(--text-muted)]"
            placeholder="Search memory..."
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
          />
          {searchQuery && (
            <button
              type="button"
              onClick={() => { setSearchQuery(''); setSearchResults(null); }}
              className="text-[var(--text-muted)] hover:text-[var(--text-primary)] shrink-0"
            >
              <X size={14} />
            </button>
          )}
        </form>
        {/* Tag pills removed — Obsidian page provides full tag interface */}
      </div>

      {/* Main content — matches StorageTab layout */}
      <div className="flex flex-col md:flex-row gap-3 md:gap-4 flex-1 min-h-0">
        {/* File tree — left panel */}
        <div className="md:w-[280px] shrink-0 bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-[var(--border-radius)] overflow-y-auto max-h-[200px] md:max-h-none">
          {loading ? (
            <div className="flex items-center justify-center py-12 text-[var(--text-muted)] text-[13px]">
              Loading...
            </div>
          ) : (
            <MemoryFileTree
              files={displayFiles}
              selectedFile={selectedFile}
              onSelect={loadFile}
            />
          )}
        </div>

        {/* Right — viewer or search results */}
        {searchResults ? (
          <MemorySearchResults results={searchResults} onSelect={loadFile} />
        ) : (
          <MemoryViewer
            detail={fileDetail}
            onEdit={() => setShowEditModal(true)}
            onDelete={handleDelete}
            onClose={() => { setSelectedFile(null); setFileDetail(null); }}
            onPromote={handlePromote}
            showPromote={!isGlobal && !!selectedFile}
          />
        )}
      </div>

      {/* Modals */}
      {showCreateModal && (
        <MemoryCreateModal onClose={() => setShowCreateModal(false)} onCreate={handleCreate} />
      )}
      {showEditModal && fileDetail && (
        <MemoryEditModal detail={fileDetail} onClose={() => setShowEditModal(false)} onSave={handleUpdate} />
      )}
    </div>
    </TabShell>
  );
}
