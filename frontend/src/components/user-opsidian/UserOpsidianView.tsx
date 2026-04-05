'use client';

import { useEffect, useCallback, useState, useMemo } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useUserOpsidianStore } from '@/store/useUserOpsidianStore';
import { useAuthStore } from '@/store/useAuthStore';
import { userOpsidianApi } from '@/lib/api';
import { useI18n } from '@/lib/i18n';
import { useHubMode } from '@/components/OpsidianHubContext';
import RightPanel from '../obsidian/RightPanel';
import Link from 'next/link';
import {
  Brain,
  FolderOpen,
  File,
  Tag,
  Link2,
  ChevronRight,
  ChevronDown,
  Search,
  GitGraph,
  FileText,
  Calendar,
  Lightbulb,
  Users,
  FolderKanban,
  Bookmark,
  PanelLeftClose,
  PanelLeftOpen,
  Plus,
  Trash2,
  RefreshCw,
  Save,
  X,
  ArrowLeft,
  Home,
  Edit3,
  Loader2,
} from 'lucide-react';
import '../obsidian/obsidian.css';

// ─── Constants ────────────────────────────────────────────────
const CATEGORY_ICONS: Record<string, typeof File> = {
  daily: Calendar,
  topics: Bookmark,
  entities: Users,
  projects: FolderKanban,
  insights: Lightbulb,
  root: FileText,
};

const CATEGORY_COLORS: Record<string, string> = {
  daily: '#f59e0b',
  topics: '#3b82f6',
  entities: '#10b981',
  projects: '#8b5cf6',
  insights: '#ec4899',
  root: '#64748b',
};

const IMPORTANCE_DOT: Record<string, string> = {
  critical: '#ef4444',
  high: '#f59e0b',
  medium: '#3b82f6',
  low: '#64748b',
};

const IMPORTANCE_STYLES: Record<string, { bg: string; color: string; label: string }> = {
  critical: { bg: 'rgba(239,68,68,0.15)', color: '#ef4444', label: 'Critical' },
  high: { bg: 'rgba(245,158,11,0.15)', color: '#f59e0b', label: 'High' },
  medium: { bg: 'rgba(59,130,246,0.1)', color: '#3b82f6', label: 'Medium' },
  low: { bg: 'rgba(100,116,139,0.1)', color: '#64748b', label: 'Low' },
};

// ─── Main View ────────────────────────────────────────────────
export default function UserOpsidianView() {
  const { isAuthenticated } = useAuthStore();
  const { t } = useI18n();
  const hub = useHubMode();
  const {
    files,
    selectedFile,
    fileDetail,
    openFiles,
    viewMode,
    sidebarCollapsed,
    rightPanelOpen,
    memoryIndex,
    sidebarPanel,
    graphNodes,
    graphEdges,
    searchQuery,
    searchResults,
    searching,
    setLoading,
    setMemoryIndex,
    setStats,
    setFiles,
    setGraphData,
    setViewMode,
    setSidebarCollapsed,
    setFileDetail,
    openFile,
    closeFile,
    setSidebarPanel,
    setSearchQuery,
    setSearchResults,
    setSearching,
    setUsername,
  } = useUserOpsidianStore();

  // ─── Load data on mount ──
  const loadData = useCallback(async () => {
    setLoading(true);
    try {
      const [indexRes, graphRes] = await Promise.all([
        userOpsidianApi.getIndex(),
        userOpsidianApi.getGraph(),
      ]);
      setMemoryIndex(indexRes.index);
      setStats({
        total_files: indexRes.stats.total_files ?? 0,
        total_chars: indexRes.stats.long_term_chars ?? 0,
        categories: indexRes.stats.categories ?? {},
        total_tags: indexRes.stats.total_tags ?? 0,
      });
      setFiles(indexRes.index.files);
      setGraphData(graphRes.nodes, graphRes.edges);
      setUsername(indexRes.username);
    } catch (err) {
      console.error('Failed to load user opsidian data:', err);
    } finally {
      setLoading(false);
    }
  }, [setLoading, setMemoryIndex, setStats, setFiles, setGraphData, setUsername]);

  useEffect(() => {
    if (isAuthenticated) {
      loadData();
    }
  }, [isAuthenticated, loadData]);

  // Register refresh callback for hub StatusBar
  useEffect(() => {
    if (hub) {
      hub.refreshRef.current = loadData;
    }
  }, [hub, loadData]);

  // ─── Draft note for inline creation ──
  const [draftNote, setDraftNote] = useState<{
    title: string; content: string; category: string;
    importance: string; tags: string;
  } | null>(null);

  // ─── File selection handler ──
  const handleSelectFile = useCallback(
    async (filename: string) => {
      openFile(filename);
      setDraftNote(null);
      try {
        const detail = await userOpsidianApi.readFile(filename);
        setFileDetail(detail);
      } catch (e) {
        console.error('Failed to read file:', e);
      }
    },
    [openFile, setFileDetail],
  );

  const handleNewNote = useCallback(() => {
    setDraftNote({ title: '', content: '', category: 'topics', importance: 'medium', tags: '' });
    useUserOpsidianStore.getState().setSelectedFile(null);
    useUserOpsidianStore.getState().setFileDetail(null);
    setViewMode('editor');
  }, [setViewMode]);

  const handleSaveDraft = useCallback(async (draft: {
    title: string; content: string; category: string;
    importance: string; tags: string;
  }) => {
    const tags = draft.tags.split(',').map((s) => s.trim()).filter(Boolean);
    try {
      const res = await userOpsidianApi.createFile({
        title: draft.title || t('opsidian.untitled'),
        content: draft.content || '',
        category: draft.category,
        tags,
        importance: draft.importance,
      });
      setDraftNote(null);
      await loadData();
      await handleSelectFile(res.filename);
    } catch (e) {
      console.error('Create failed:', e);
    }
  }, [loadData, handleSelectFile, t]);

  // ─── Auth guard ──
  if (!isAuthenticated) {
    return (
      <div className="obsidian-root" style={{ alignItems: 'center', justifyContent: 'center' }}>
        <div style={{ textAlign: 'center', color: 'var(--obs-text-muted)' }}>
          <Brain size={48} strokeWidth={1.2} style={{ marginBottom: 16, color: 'var(--obs-purple)' }} />
          <h2 style={{ margin: '0 0 8px', color: 'var(--obs-text)', fontSize: 20 }}>{t('opsidian.title')}</h2>
          <p style={{ fontSize: 14 }}>{t('opsidian.loginRequired')}</p>
          <Link
            href="/"
            style={{
              display: 'inline-flex', alignItems: 'center', gap: 6, marginTop: 16,
              padding: '8px 20px', borderRadius: 8, background: 'var(--obs-purple)',
              color: '#fff', textDecoration: 'none', fontSize: 13, fontWeight: 600,
            }}
          >
            <Home size={14} /> {t('opsidian.goHome')}
          </Link>
        </div>
      </div>
    );
  }

  return (
    <div className="obsidian-root">
      {/* Left sidebar */}
      <Sidebar
        files={files}
        selectedFile={selectedFile}
        sidebarCollapsed={sidebarCollapsed}
        sidebarPanel={sidebarPanel}
        viewMode={viewMode}
        memoryIndex={memoryIndex}
        onSelectFile={handleSelectFile}
        onSetSidebarCollapsed={setSidebarCollapsed}
        onSetSidebarPanel={setSidebarPanel}
        onSetViewMode={setViewMode}
        onRefresh={loadData}
        onNewNote={handleNewNote}
      />

      {/* Main content */}
      <div
        className="obsidian-main"
        style={{
          marginLeft: sidebarCollapsed ? 40 : 260,
          marginRight: rightPanelOpen ? 280 : 0,
        }}
      >
        {/* Tabs */}
        <Tabs
          openFiles={openFiles}
          selectedFile={selectedFile}
          files={files}
          onSelectFile={handleSelectFile}
          onCloseFile={closeFile}
        />

        {/* Content */}
        <div className="obsidian-content">
          {viewMode === 'editor' && (
            draftNote
              ? <DraftEditor
                  draft={draftNote}
                  onUpdate={setDraftNote}
                  onSave={handleSaveDraft}
                  onDiscard={() => setDraftNote(null)}
                />
              : <NoteEditor
                  fileDetail={fileDetail}
                  selectedFile={selectedFile}
                  onSelectFile={handleSelectFile}
                  onRefresh={loadData}
                />
          )}
          {viewMode === 'graph' && (
            <GraphViewer nodes={graphNodes} edges={graphEdges} onSelectFile={handleSelectFile} />
          )}
          {viewMode === 'search' && (
            <SearchView
              query={searchQuery}
              results={searchResults}
              searching={searching}
              onSetQuery={setSearchQuery}
              onSetResults={setSearchResults}
              onSetSearching={setSearching}
              onSelectFile={handleSelectFile}
            />
          )}
        </div>
      </div>

      {/* Right panel */}
      {rightPanelOpen && <RightPanel />}
    </div>
  );
}

// ═══════════════════════════════════════════════════════════════
// SUB-COMPONENTS
// ═══════════════════════════════════════════════════════════════

// ─── Sidebar ──────────────────────────────────────────────────
function Sidebar({
  files, selectedFile, sidebarCollapsed, sidebarPanel, viewMode, memoryIndex,
  onSelectFile, onSetSidebarCollapsed, onSetSidebarPanel, onSetViewMode, onRefresh, onNewNote,
}: {
  files: Record<string, import('@/types').MemoryFileInfo>;
  selectedFile: string | null;
  sidebarCollapsed: boolean;
  sidebarPanel: string;
  viewMode: string;
  memoryIndex: import('@/types').MemoryIndex | null;
  onSelectFile: (fn: string) => void;
  onSetSidebarCollapsed: (v: boolean) => void;
  onSetSidebarPanel: (p: 'files' | 'tags' | 'backlinks') => void;
  onSetViewMode: (v: 'editor' | 'graph' | 'search') => void;
  onRefresh: () => void;
  onNewNote: () => void;
}) {
  const { t } = useI18n();
  const [expandedCategories, setExpandedCategories] = useState<Set<string>>(
    new Set(['daily', 'topics', 'entities', 'projects', 'insights', 'root']),
  );
  const [filterText, setFilterText] = useState('');

  const toggleCategory = (cat: string) => {
    setExpandedCategories((prev) => {
      const next = new Set(prev);
      if (next.has(cat)) next.delete(cat);
      else next.add(cat);
      return next;
    });
  };

  const grouped = useMemo(() => {
    const groups: Record<string, (typeof files)[string][]> = {};
    Object.values(files).forEach((f) => {
      const cat = f.category || 'root';
      if (!groups[cat]) groups[cat] = [];
      if (filterText) {
        const q = filterText.toLowerCase();
        if (
          f.title.toLowerCase().includes(q) ||
          f.filename.toLowerCase().includes(q) ||
          f.tags.some((tg) => tg.includes(q))
        ) {
          groups[cat].push(f);
        }
      } else {
        groups[cat].push(f);
      }
    });
    return groups;
  }, [files, filterText]);

  const tagMap = memoryIndex?.tag_map ?? {};

  if (sidebarCollapsed) {
    return (
      <div className="obs-sidebar obs-sidebar-collapsed">
        <button className="obs-sb-toggle" onClick={() => onSetSidebarCollapsed(false)}>
          <PanelLeftOpen size={16} />
        </button>
        <div className="obs-sb-collapsed-icons">
          <button className={`obs-sb-icon-btn ${viewMode === 'editor' ? 'active' : ''}`} onClick={() => onSetViewMode('editor')} title={t('opsidian.editor')}>
            <FileText size={16} />
          </button>
          <button className={`obs-sb-icon-btn ${viewMode === 'graph' ? 'active' : ''}`} onClick={() => onSetViewMode('graph')} title={t('opsidian.graph')}>
            <GitGraph size={16} />
          </button>
          <button className={`obs-sb-icon-btn ${viewMode === 'search' ? 'active' : ''}`} onClick={() => onSetViewMode('search')} title={t('opsidian.search')}>
            <Search size={16} />
          </button>
        </div>
        <div className="obs-sb-collapsed-bottom">
          <button className="obs-sb-icon-btn" onClick={onRefresh} title={t('opsidian.refresh')}>
            <RefreshCw size={14} />
          </button>
        </div>
      </div>
    );
  }

  return (
    <div className="obs-sidebar">
      {/* Header */}
      <div className="obs-sb-header">
        <Link href="/" className="obs-sb-back" title={t('opsidian.goHome')}>
          <ArrowLeft size={14} />
        </Link>
        <span className="obs-sb-brand">{t('opsidian.title')}</span>
        <div className="obs-sb-header-actions">
          <button className="obs-sb-toggle" onClick={onNewNote} title={t('opsidian.createNote')}>
            <Plus size={13} />
          </button>
          <button className="obs-sb-toggle" onClick={onRefresh} title={t('opsidian.refresh')}>
            <RefreshCw size={13} />
          </button>
          <button className="obs-sb-toggle" onClick={() => onSetSidebarCollapsed(true)}>
            <PanelLeftClose size={14} />
          </button>
        </div>
      </div>

      {/* Panel tabs */}
      <div className="obs-sb-tabs">
        <button className={`obs-sb-tab ${sidebarPanel === 'files' ? 'active' : ''}`} onClick={() => onSetSidebarPanel('files')}>
          <FolderOpen size={12} /> {t('opsidian.files')}
        </button>
        <button className={`obs-sb-tab ${sidebarPanel === 'tags' ? 'active' : ''}`} onClick={() => onSetSidebarPanel('tags')}>
          <Tag size={12} /> {t('opsidian.tags')}
        </button>
        <button className={`obs-sb-tab ${sidebarPanel === 'backlinks' ? 'active' : ''}`} onClick={() => onSetSidebarPanel('backlinks')}>
          <Link2 size={12} /> {t('opsidian.links')}
        </button>
      </div>

      {/* View mode switcher */}
      <div className="obs-sb-view-modes">
        <button className={`obs-sb-view-btn ${viewMode === 'editor' ? 'active' : ''}`} onClick={() => onSetViewMode('editor')}>
          <FileText size={12} /> {t('opsidian.editor')}
        </button>
        <button className={`obs-sb-view-btn ${viewMode === 'graph' ? 'active' : ''}`} onClick={() => onSetViewMode('graph')}>
          <GitGraph size={12} /> {t('opsidian.graph')}
        </button>
        <button className={`obs-sb-view-btn ${viewMode === 'search' ? 'active' : ''}`} onClick={() => onSetViewMode('search')}>
          <Search size={12} /> {t('opsidian.search')}
        </button>
      </div>

      {/* Body */}
      <div className="obs-sb-body">
        {sidebarPanel === 'files' && (
          <>
            <div className="obs-sb-filter">
              <Search size={12} className="obs-sb-filter-icon" />
              <input
                className="obs-sb-filter-input"
                placeholder={t('opsidian.filterPlaceholder')}
                value={filterText}
                onChange={(e) => setFilterText(e.target.value)}
              />
            </div>
            <div className="obs-sb-tree">
              {Object.entries(grouped).map(([cat, catFiles]) => {
                if (catFiles.length === 0) return null;
                const Icon = CATEGORY_ICONS[cat] || FileText;
                const expanded = expandedCategories.has(cat);
                return (
                  <div key={cat} className="obs-sb-category">
                    <button className="obs-sb-cat-header" onClick={() => toggleCategory(cat)}>
                      {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                      <Icon size={12} style={{ color: CATEGORY_COLORS[cat] || '#64748b' }} />
                      <span className="obs-sb-cat-name">{cat}</span>
                      <span className="obs-sb-cat-count">{catFiles.length}</span>
                    </button>
                    {expanded && (
                      <div className="obs-sb-cat-files">
                        {catFiles.map((f) => (
                          <button
                            key={f.filename}
                            className={`obs-sb-file ${selectedFile === f.filename ? 'active' : ''}`}
                            onClick={() => onSelectFile(f.filename)}
                          >
                            <span
                              className="obs-sb-imp-dot"
                              style={{ color: IMPORTANCE_DOT[f.importance] || '#64748b' }}
                            />
                            <span className="obs-sb-file-title">{f.title || f.filename}</span>
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}
              {Object.values(files).length === 0 && !filterText && (
                <div style={{ padding: '24px 16px', textAlign: 'center', color: 'var(--obs-text-muted)', fontSize: 12 }}>
                  {t('opsidian.emptyVault')}
                </div>
              )}
            </div>
          </>
        )}

        {sidebarPanel === 'tags' && (
          <div className="obs-sb-tags">
            {Object.entries(tagMap).map(([tag, fns]) => (
              <button key={tag} className="obs-sb-tag-item" onClick={() => { /* filter by tag */ }}>
                <Tag size={12} style={{ color: 'var(--obs-purple-bright)' }} />
                <span className="obs-sb-tag-name">{tag}</span>
                <span className="obs-sb-tag-count">{Array.isArray(fns) ? fns.length : 0}</span>
              </button>
            ))}
            {Object.keys(tagMap).length === 0 && (
              <div style={{ padding: '24px 16px', textAlign: 'center', color: 'var(--obs-text-muted)', fontSize: 12 }}>
                {t('opsidian.noTags')}
              </div>
            )}
          </div>
        )}

        {sidebarPanel === 'backlinks' && selectedFile && (
          <div className="obs-sb-backlinks" style={{ padding: '8px' }}>
            {(() => {
              const info = files[selectedFile];
              if (!info) return <div style={{ padding: 16, color: 'var(--obs-text-muted)', fontSize: 12 }}>{t('opsidian.selectNote')}</div>;
              const backlinks = info.linked_from || [];
              const outlinks = info.links_to || [];
              return (
                <>
                  <div style={{ padding: '8px 4px', fontSize: 11, fontWeight: 600, color: 'var(--obs-text-dim)', textTransform: 'uppercase', letterSpacing: '0.05em' }}>
                    {t('opsidian.backlinksLabel')} ({backlinks.length})
                  </div>
                  {backlinks.map((bl) => (
                    <button key={bl} className="obs-sb-tag-item" onClick={() => onSelectFile(bl)}>
                      <Link2 size={12} /> <span className="obs-sb-tag-name">{files[bl]?.title || bl}</span>
                    </button>
                  ))}
                  <div style={{ padding: '8px 4px', fontSize: 11, fontWeight: 600, color: 'var(--obs-text-dim)', textTransform: 'uppercase', letterSpacing: '0.05em', marginTop: 12 }}>
                    {t('opsidian.outlinksLabel')} ({outlinks.length})
                  </div>
                  {outlinks.map((ol) => (
                    <button key={ol} className="obs-sb-tag-item" onClick={() => onSelectFile(ol)}>
                      <Link2 size={12} /> <span className="obs-sb-tag-name">{files[ol]?.title || ol}</span>
                    </button>
                  ))}
                </>
              );
            })()}
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Tabs ───────────────────────────────────────────────────────
function Tabs({
  openFiles, selectedFile, files, onSelectFile, onCloseFile,
}: {
  openFiles: string[];
  selectedFile: string | null;
  files: Record<string, import('@/types').MemoryFileInfo>;
  onSelectFile: (fn: string) => void;
  onCloseFile: (fn: string) => void;
}) {
  if (openFiles.length === 0) return null;
  return (
    <div style={{
      display: 'flex', gap: 0, borderBottom: '1px solid var(--obs-border-subtle)',
      background: 'var(--obs-bg-panel)', overflowX: 'auto', minHeight: 36,
    }}>
      {openFiles.map((fn) => {
        const isActive = fn === selectedFile;
        const info = files[fn];
        return (
          <div
            key={fn}
            style={{
              display: 'flex', alignItems: 'center', gap: 6,
              padding: '0 12px', fontSize: 12, cursor: 'pointer',
              borderBottom: isActive ? '2px solid var(--obs-purple)' : '2px solid transparent',
              background: isActive ? 'var(--obs-bg-surface)' : 'transparent',
              color: isActive ? 'var(--obs-text)' : 'var(--obs-text-muted)',
              transition: 'all 150ms ease', whiteSpace: 'nowrap',
            }}
            onClick={() => onSelectFile(fn)}
          >
            <span>{info?.title || fn}</span>
            <button
              onClick={(e) => { e.stopPropagation(); onCloseFile(fn); }}
              style={{
                display: 'flex', alignItems: 'center', justifyContent: 'center',
                width: 16, height: 16, background: 'none', border: 'none',
                color: 'var(--obs-text-muted)', cursor: 'pointer', borderRadius: 3,
                padding: 0,
              }}
              onMouseEnter={(e) => { (e.target as HTMLElement).style.background = 'var(--obs-bg-hover)'; }}
              onMouseLeave={(e) => { (e.target as HTMLElement).style.background = 'none'; }}
            >
              <X size={10} />
            </button>
          </div>
        );
      })}
    </div>
  );
}

// ─── Note Editor ──────────────────────────────────────────────
function NoteEditor({
  fileDetail, selectedFile, onSelectFile, onRefresh,
}: {
  fileDetail: import('@/types').MemoryFileDetail | null;
  selectedFile: string | null;
  onSelectFile: (fn: string) => void;
  onRefresh: () => void;
}) {
  const { t } = useI18n();
  const [editing, setEditing] = useState(false);
  const [editContent, setEditContent] = useState('');
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (fileDetail?.body) {
      setEditContent(fileDetail.body);
    }
    setEditing(false);
  }, [fileDetail]);

  const handleSave = async () => {
    if (!selectedFile || !editContent) return;
    setSaving(true);
    try {
      await userOpsidianApi.updateFile(selectedFile, { content: editContent });
      setEditing(false);
      await onRefresh();
      await onSelectFile(selectedFile);
    } catch (e) {
      console.error('Save failed:', e);
    } finally {
      setSaving(false);
    }
  };

  const handleDelete = async () => {
    if (!selectedFile) return;
    if (!confirm(t('opsidian.confirmDelete'))) return;
    try {
      await userOpsidianApi.deleteFile(selectedFile);
      onRefresh();
    } catch (e) {
      console.error('Delete failed:', e);
    }
  };

  if (!selectedFile || !fileDetail) {
    return (
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        height: '100%', color: 'var(--obs-text-muted)', fontSize: 14,
        flexDirection: 'column', gap: 12,
      }}>
        <Brain size={40} strokeWidth={1.2} style={{ color: 'var(--obs-purple)', opacity: 0.5 }} />
        <span>{t('opsidian.selectOrCreate')}</span>
      </div>
    );
  }

  const meta = fileDetail.metadata || {};
  const body = fileDetail.body ?? '';

  // Process wikilinks for markdown rendering
  const processedBody = body.replace(
    /\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g,
    (_match: string, target: string, alias: string) => {
      const display = alias || target;
      return `[🔗 ${display}](wikilink://${encodeURIComponent(target)})`;
    },
  );

  if (editing) {
    return (
      <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
        {/* Toolbar — matches DraftEditor */}
        <div style={{
          display: 'flex', alignItems: 'center', gap: 8, padding: '8px 16px',
          borderBottom: '1px solid var(--obs-border-subtle)',
          background: 'var(--obs-bg-panel)',
        }}>
          {!!meta.category && (
            <span style={{
              padding: '4px 10px', fontSize: 11, borderRadius: 4,
              background: `${CATEGORY_COLORS[String(meta.category)] || '#64748b'}20`,
              color: CATEGORY_COLORS[String(meta.category)] || '#64748b',
            }}>{String(meta.category)}</span>
          )}
          {!!meta.importance && (
            <span style={{
              padding: '4px 10px', fontSize: 11, borderRadius: 4,
              background: IMPORTANCE_STYLES[String(meta.importance)]?.bg || 'transparent',
              color: IMPORTANCE_STYLES[String(meta.importance)]?.color || 'var(--obs-text-dim)',
            }}>{String(meta.importance)}</span>
          )}
          {Array.isArray(meta.tags) && meta.tags.length > 0 && (
            <span style={{
              flex: 1, padding: '4px 8px', fontSize: 11,
              color: 'var(--obs-text-dim)', overflow: 'hidden', textOverflow: 'ellipsis',
              whiteSpace: 'nowrap',
            }}>{meta.tags.map(String).join(', ')}</span>
          )}
          <div style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
            <button
              onClick={() => { setEditing(false); setEditContent(body); }}
              style={{
                display: 'flex', alignItems: 'center', gap: 4, padding: '5px 12px',
                fontSize: 12, background: 'var(--obs-bg-hover)', color: 'var(--obs-text-dim)',
                border: '1px solid var(--obs-border)', borderRadius: 5, cursor: 'pointer',
              }}
            >
              <X size={12} /> {t('opsidian.cancel')}
            </button>
            <button
              onClick={handleSave}
              disabled={saving}
              style={{
                display: 'flex', alignItems: 'center', gap: 4, padding: '5px 14px',
                fontSize: 12, fontWeight: 600, background: 'var(--obs-purple)',
                color: '#fff', border: 'none', borderRadius: 5, cursor: 'pointer',
              }}
            >
              {saving ? <Loader2 size={12} className="spin" /> : <Save size={12} />}
              {t('opsidian.save')}
            </button>
            <button
              onClick={handleDelete}
              style={{
                display: 'flex', alignItems: 'center', padding: '5px 8px',
                fontSize: 12, background: 'rgba(239,68,68,0.1)', color: '#ef4444',
                border: '1px solid rgba(239,68,68,0.2)', borderRadius: 5, cursor: 'pointer',
              }}
            >
              <Trash2 size={12} />
            </button>
          </div>
        </div>

        {/* Title (read-only) */}
        <div style={{ padding: '16px 32px 0', maxWidth: 900, margin: '0 auto', width: '100%' }}>
          <h1 style={{
            fontSize: 24, fontWeight: 700, margin: 0, paddingBottom: 8,
            borderBottom: '1px solid var(--obs-border-subtle)',
            color: 'var(--obs-text)', marginBottom: 16,
          }}>
            {String(meta.title || selectedFile)}
          </h1>
        </div>

        {/* Content textarea — matches DraftEditor */}
        <div style={{ flex: 1, padding: '0 32px 16px', maxWidth: 900, margin: '0 auto', width: '100%' }}>
          <textarea
            value={editContent}
            onChange={(e) => setEditContent(e.target.value)}
            autoFocus
            style={{
              width: '100%', height: '100%', minHeight: 300, padding: 0,
              background: 'transparent', color: 'var(--obs-text)',
              border: 'none', fontFamily: 'var(--obs-font-mono)', fontSize: 14,
              lineHeight: 1.8, resize: 'none', outline: 'none',
            }}
          />
        </div>
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* Toolbar — view mode */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8, padding: '8px 16px',
        borderBottom: '1px solid var(--obs-border-subtle)',
        background: 'var(--obs-bg-panel)',
      }}>
        {!!meta.category && (
          <span style={{
            display: 'inline-flex', alignItems: 'center', gap: 4, padding: '4px 10px',
            fontSize: 11, borderRadius: 4,
            background: `${CATEGORY_COLORS[String(meta.category)] || '#64748b'}20`,
            color: CATEGORY_COLORS[String(meta.category)] || '#64748b',
          }}>
            {(() => { const I = CATEGORY_ICONS[String(meta.category)] || FileText; return <I size={10} />; })()}
            {String(meta.category)}
          </span>
        )}
        {!!meta.importance && (() => {
          const s = IMPORTANCE_STYLES[String(meta.importance)];
          return s ? (
            <span style={{
              display: 'inline-flex', alignItems: 'center', gap: 4, padding: '4px 10px',
              fontSize: 11, borderRadius: 4, background: s.bg, color: s.color,
            }}>{s.label}</span>
          ) : null;
        })()}
        {Array.isArray(meta.tags) && meta.tags.map((tag) => (
          <span key={String(tag)} style={{
            display: 'inline-flex', alignItems: 'center', gap: 3, padding: '4px 8px',
            fontSize: 11, borderRadius: 4, background: 'var(--obs-purple-dim)',
            color: 'var(--obs-purple-bright)',
          }}>
            <Tag size={9} /> {String(tag)}
          </span>
        ))}
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
          <button
            onClick={() => setEditing(true)}
            style={{
              display: 'flex', alignItems: 'center', gap: 4, padding: '5px 12px',
              fontSize: 12, fontWeight: 500, background: 'var(--obs-purple-dim)',
              color: 'var(--obs-purple-bright)', border: '1px solid rgba(139,92,246,0.3)',
              borderRadius: 5, cursor: 'pointer',
            }}
          >
            <Edit3 size={12} /> {t('opsidian.edit')}
          </button>
          <button
            onClick={handleDelete}
            style={{
              display: 'flex', alignItems: 'center', padding: '5px 8px',
              fontSize: 12, background: 'rgba(239,68,68,0.1)', color: '#ef4444',
              border: '1px solid rgba(239,68,68,0.2)', borderRadius: 5, cursor: 'pointer',
            }}
          >
            <Trash2 size={12} />
          </button>
        </div>
      </div>

      {/* Title + Body */}
      <div style={{ flex: 1, overflow: 'auto', padding: '16px 32px', maxWidth: 900, margin: '0 auto', width: '100%' }}>
        <h1 style={{ fontSize: 24, fontWeight: 700, margin: '0 0 16px', color: 'var(--obs-text)' }}>
          {String(meta.title || selectedFile)}
        </h1>
        <div style={{ fontSize: 14, lineHeight: 1.8, color: 'var(--obs-text)' }}>
          <ReactMarkdown
            remarkPlugins={[remarkGfm]}
            components={{
              a: ({ href, children, ...props }) => {
                if (href?.startsWith('wikilink://')) {
                  const target = decodeURIComponent(href.replace('wikilink://', ''));
                  return (
                    <a
                      {...props}
                      href="#"
                      style={{ color: 'var(--obs-purple-bright)', textDecoration: 'none', cursor: 'pointer' }}
                      onClick={(e) => { e.preventDefault(); onSelectFile(target); }}
                    >
                      {children}
                    </a>
                  );
                }
                return <a {...props} href={href} target="_blank" rel="noopener noreferrer">{children}</a>;
              },
            }}
          >
            {processedBody}
          </ReactMarkdown>
        </div>
      </div>
    </div>
  );
}

// ─── Graph Viewer ─────────────────────────────────────────────
function GraphViewer({
  nodes, edges, onSelectFile,
}: {
  nodes: import('@/types').MemoryGraphNode[];
  edges: import('@/types').MemoryGraphEdge[];
  onSelectFile: (fn: string) => void;
}) {
  const { t } = useI18n();

  // Simple force-based layout using a canvas-like SVG approach
  const width = 800;
  const height = 600;
  const nodePositions = useMemo(() => {
    const positions: Record<string, { x: number; y: number }> = {};
    const catGroups: Record<string, string[]> = {};
    nodes.forEach((n) => {
      if (!catGroups[n.category]) catGroups[n.category] = [];
      catGroups[n.category].push(n.id);
    });
    const cats = Object.keys(catGroups);
    cats.forEach((cat, ci) => {
      const angle = (ci / cats.length) * 2 * Math.PI;
      const cx = width / 2 + Math.cos(angle) * 200;
      const cy = height / 2 + Math.sin(angle) * 180;
      catGroups[cat].forEach((id, ni) => {
        const subAngle = (ni / catGroups[cat].length) * 2 * Math.PI;
        positions[id] = {
          x: cx + Math.cos(subAngle) * (40 + catGroups[cat].length * 8),
          y: cy + Math.sin(subAngle) * (40 + catGroups[cat].length * 8),
        };
      });
    });
    return positions;
  }, [nodes]);

  if (nodes.length === 0) {
    return (
      <div style={{
        display: 'flex', alignItems: 'center', justifyContent: 'center',
        height: '100%', color: 'var(--obs-text-muted)', fontSize: 14,
        flexDirection: 'column', gap: 12,
      }}>
        <GitGraph size={40} strokeWidth={1.2} style={{ opacity: 0.5 }} />
        <span>{t('opsidian.emptyGraph')}</span>
      </div>
    );
  }

  return (
    <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'center', height: '100%', overflow: 'auto' }}>
      <svg width={width} height={height} style={{ background: 'var(--obs-bg-deep)' }}>
        {/* Edges */}
        {edges.map((e, i) => {
          const from = nodePositions[e.source];
          const to = nodePositions[e.target];
          if (!from || !to) return null;
          return (
            <line key={i} x1={from.x} y1={from.y} x2={to.x} y2={to.y}
              stroke="var(--obs-purple)" strokeWidth={1} opacity={0.3} />
          );
        })}
        {/* Nodes */}
        {nodes.map((n) => {
          const pos = nodePositions[n.id];
          if (!pos) return null;
          const color = CATEGORY_COLORS[n.category] || '#64748b';
          return (
            <g key={n.id} style={{ cursor: 'pointer' }} onClick={() => onSelectFile(n.id)}>
              <circle cx={pos.x} cy={pos.y} r={8} fill={color} opacity={0.8} />
              <circle cx={pos.x} cy={pos.y} r={8} fill="none" stroke={color} strokeWidth={1} opacity={0.4} />
              <text x={pos.x} y={pos.y + 20} textAnchor="middle" fill="var(--obs-text-dim)" fontSize={10}>
                {n.label.length > 20 ? n.label.slice(0, 20) + '…' : n.label}
              </text>
            </g>
          );
        })}
      </svg>
    </div>
  );
}

// ─── Search View ──────────────────────────────────────────────
function SearchView({
  query, results, searching, onSetQuery, onSetResults, onSetSearching, onSelectFile,
}: {
  query: string;
  results: Array<Record<string, unknown>>;
  searching: boolean;
  onSetQuery: (q: string) => void;
  onSetResults: (r: Array<Record<string, unknown>>) => void;
  onSetSearching: (v: boolean) => void;
  onSelectFile: (fn: string) => void;
}) {
  const { t } = useI18n();

  const handleSearch = async () => {
    if (!query.trim()) return;
    onSetSearching(true);
    try {
      const res = await userOpsidianApi.search(query.trim());
      onSetResults(res.results);
    } catch (e) {
      console.error('Search failed:', e);
    } finally {
      onSetSearching(false);
    }
  };

  return (
    <div style={{ padding: '24px 32px', maxWidth: 800, margin: '0 auto' }}>
      <h2 style={{ fontSize: 18, fontWeight: 700, color: 'var(--obs-text)', margin: '0 0 16px' }}>
        {t('opsidian.search')}
      </h2>
      <div style={{
        display: 'flex', gap: 8, marginBottom: 24,
      }}>
        <input
          value={query}
          onChange={(e) => onSetQuery(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && handleSearch()}
          placeholder={t('opsidian.searchPlaceholder')}
          style={{
            flex: 1, padding: '10px 14px', background: 'var(--obs-bg-surface)',
            border: '1px solid var(--obs-border)', borderRadius: 8,
            color: 'var(--obs-text)', fontSize: 13, outline: 'none',
          }}
        />
        <button
          onClick={handleSearch}
          disabled={searching}
          style={{
            padding: '10px 20px', background: 'var(--obs-purple)', color: '#fff',
            border: 'none', borderRadius: 8, fontSize: 13, fontWeight: 600, cursor: 'pointer',
          }}
        >
          {searching ? <Loader2 size={14} className="spin" /> : <Search size={14} />}
        </button>
      </div>

      {/* Results */}
      <div style={{ display: 'flex', flexDirection: 'column', gap: 8 }}>
        {results.map((r, i) => (
          <button
            key={i}
            onClick={() => r.filename && onSelectFile(String(r.filename))}
            style={{
              display: 'block', width: '100%', textAlign: 'left', padding: '14px 16px',
              background: 'var(--obs-bg-panel)', border: '1px solid var(--obs-border-subtle)',
              borderRadius: 8, cursor: 'pointer', color: 'var(--obs-text)',
              transition: 'all 150ms ease',
            }}
            onMouseEnter={(e) => { (e.currentTarget as HTMLElement).style.borderColor = 'var(--obs-purple)'; }}
            onMouseLeave={(e) => { (e.currentTarget as HTMLElement).style.borderColor = 'var(--obs-border-subtle)'; }}
          >
            <div style={{ fontWeight: 600, fontSize: 14, marginBottom: 4 }}>
              {String(r.title || r.filename || 'Untitled')}
            </div>
            {!!r.snippet && (
              <div style={{ fontSize: 12, color: 'var(--obs-text-dim)', lineHeight: 1.5 }}>
                {String(r.snippet).slice(0, 200)}
              </div>
            )}
            <div style={{ display: 'flex', gap: 8, marginTop: 6, fontSize: 11, color: 'var(--obs-text-muted)' }}>
              {!!r.category && <span>{String(r.category)}</span>}
              {!!r.score && <span>score: {(Number(r.score)).toFixed(1)}</span>}
            </div>
          </button>
        ))}
        {results.length === 0 && query && !searching && (
          <div style={{ textAlign: 'center', padding: 24, color: 'var(--obs-text-muted)', fontSize: 13 }}>
            {t('opsidian.noResults')}
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Draft Editor (IDE-style inline creation) ────────────────
function DraftEditor({
  draft, onUpdate, onSave, onDiscard,
}: {
  draft: { title: string; content: string; category: string; importance: string; tags: string };
  onUpdate: (d: typeof draft) => void;
  onSave: (d: typeof draft) => void;
  onDiscard: () => void;
}) {
  const { t } = useI18n();
  const [saving, setSaving] = useState(false);

  const handleSave = async () => {
    setSaving(true);
    try {
      await onSave(draft);
    } finally {
      setSaving(false);
    }
  };

  return (
    <div style={{ display: 'flex', flexDirection: 'column', height: '100%' }}>
      {/* Toolbar */}
      <div style={{
        display: 'flex', alignItems: 'center', gap: 8, padding: '8px 16px',
        borderBottom: '1px solid var(--obs-border-subtle)',
        background: 'var(--obs-bg-panel)',
      }}>
        <select
          value={draft.category}
          onChange={(e) => onUpdate({ ...draft, category: e.target.value })}
          style={{
            padding: '4px 8px', fontSize: 11, background: 'var(--obs-bg-surface)',
            border: '1px solid var(--obs-border)', borderRadius: 4,
            color: 'var(--obs-text)', outline: 'none',
          }}
        >
          <option value="topics">Topics</option>
          <option value="daily">Daily</option>
          <option value="entities">Entities</option>
          <option value="projects">Projects</option>
          <option value="insights">Insights</option>
        </select>
        <select
          value={draft.importance}
          onChange={(e) => onUpdate({ ...draft, importance: e.target.value })}
          style={{
            padding: '4px 8px', fontSize: 11, background: 'var(--obs-bg-surface)',
            border: '1px solid var(--obs-border)', borderRadius: 4,
            color: 'var(--obs-text)', outline: 'none',
          }}
        >
          <option value="critical">Critical</option>
          <option value="high">High</option>
          <option value="medium">Medium</option>
          <option value="low">Low</option>
        </select>
        <input
          value={draft.tags}
          onChange={(e) => onUpdate({ ...draft, tags: e.target.value })}
          placeholder={t('opsidian.tagsPlaceholder')}
          style={{
            flex: 1, padding: '4px 8px', fontSize: 11, background: 'var(--obs-bg-surface)',
            border: '1px solid var(--obs-border)', borderRadius: 4,
            color: 'var(--obs-text)', outline: 'none', minWidth: 100,
          }}
        />
        <div style={{ marginLeft: 'auto', display: 'flex', gap: 6 }}>
          <button
            onClick={onDiscard}
            style={{
              display: 'flex', alignItems: 'center', gap: 4, padding: '5px 12px',
              fontSize: 12, background: 'var(--obs-bg-hover)', color: 'var(--obs-text-dim)',
              border: '1px solid var(--obs-border)', borderRadius: 5, cursor: 'pointer',
            }}
          >
            <X size={12} /> {t('opsidian.cancel')}
          </button>
          <button
            onClick={handleSave}
            disabled={saving}
            style={{
              display: 'flex', alignItems: 'center', gap: 4, padding: '5px 14px',
              fontSize: 12, fontWeight: 600, background: 'var(--obs-purple)',
              color: '#fff', border: 'none', borderRadius: 5, cursor: 'pointer',
            }}
          >
            {saving ? <Loader2 size={12} className="spin" /> : <Save size={12} />}
            {t('opsidian.save')}
          </button>
        </div>
      </div>

      {/* Title */}
      <div style={{ padding: '16px 32px 0', maxWidth: 900, margin: '0 auto', width: '100%' }}>
        <input
          value={draft.title}
          onChange={(e) => onUpdate({ ...draft, title: e.target.value })}
          placeholder={t('opsidian.noteTitlePlaceholder')}
          autoFocus
          style={{
            width: '100%', padding: '8px 0', fontSize: 24, fontWeight: 700,
            background: 'transparent', border: 'none', borderBottom: '1px solid var(--obs-border-subtle)',
            color: 'var(--obs-text)', outline: 'none', marginBottom: 16,
          }}
        />
      </div>

      {/* Content textarea */}
      <div style={{ flex: 1, padding: '0 32px 16px', maxWidth: 900, margin: '0 auto', width: '100%' }}>
        <textarea
          value={draft.content}
          onChange={(e) => onUpdate({ ...draft, content: e.target.value })}
          placeholder={t('opsidian.contentPlaceholder')}
          style={{
            width: '100%', height: '100%', minHeight: 300, padding: 0,
            background: 'transparent', color: 'var(--obs-text)',
            border: 'none', fontFamily: 'var(--obs-font-mono)', fontSize: 14,
            lineHeight: 1.8, resize: 'none', outline: 'none',
          }}
        />
      </div>
    </div>
  );
}
