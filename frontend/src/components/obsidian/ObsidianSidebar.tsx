'use client';

import { useMemo, useState } from 'react';
import { useObsidianStore } from '@/store/useObsidianStore';
import { memoryApi } from '@/lib/api';
import {
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
  ArrowLeft,
  RefreshCw,
} from 'lucide-react';

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

export default function ObsidianSidebar() {
  const {
    files,
    selectedFile,
    selectedSessionId,
    sidebarCollapsed,
    sidebarPanel,
    viewMode,
    memoryIndex,
    setSidebarCollapsed,
    setSidebarPanel,
    setViewMode,
    openFile,
    setFileDetail,
    setSelectedSessionId,
    setFiles,
    setMemoryIndex,
    setMemoryStats,
    setGraphData,
    setLoading,
  } = useObsidianStore();

  const [expandedCategories, setExpandedCategories] = useState<Set<string>>(
    new Set(['daily', 'topics', 'entities', 'projects', 'insights', 'root'])
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

  // Group files by category
  const grouped = useMemo(() => {
    const groups: Record<string, typeof files[string][]> = {};
    Object.values(files).forEach((f) => {
      const cat = f.category || 'root';
      if (!groups[cat]) groups[cat] = [];
      if (filterText) {
        const q = filterText.toLowerCase();
        if (
          f.title.toLowerCase().includes(q) ||
          f.filename.toLowerCase().includes(q) ||
          f.tags.some((t) => t.includes(q))
        ) {
          groups[cat].push(f);
        }
      } else {
        groups[cat].push(f);
      }
    });
    // Sort files by modified desc
    for (const cat of Object.keys(groups)) {
      groups[cat].sort((a, b) => (b.modified || '').localeCompare(a.modified || ''));
    }
    return groups;
  }, [files, filterText]);

  // Tags from index
  const sortedTags = useMemo(
    () => Object.entries(memoryIndex?.tag_map || {}).sort((a, b) => b[1].length - a[1].length),
    [memoryIndex?.tag_map]
  );

  // Backlinks for selected file
  const backlinks = useMemo(() => {
    if (!selectedFile || !files[selectedFile]) return [];
    return files[selectedFile].linked_from || [];
  }, [selectedFile, files]);

  const handleFileClick = async (filename: string) => {
    openFile(filename);
    if (selectedSessionId) {
      try {
        const detail = await memoryApi.readFile(selectedSessionId, filename);
        setFileDetail(detail);
      } catch (e) {
        console.error('Failed to read file:', e);
      }
    }
  };

  const handleRefresh = async () => {
    if (!selectedSessionId) return;
    setLoading(true);
    try {
      const [indexRes, graphRes] = await Promise.all([
        memoryApi.getIndex(selectedSessionId),
        memoryApi.getGraph(selectedSessionId),
      ]);
      setMemoryIndex(indexRes.index);
      setMemoryStats(indexRes.stats);
      setFiles(indexRes.index.files);
      setGraphData(graphRes.nodes, graphRes.edges);
    } finally {
      setLoading(false);
    }
  };

  if (sidebarCollapsed) {
    return (
      <div className="obs-sidebar obs-sidebar-collapsed">
        <button className="obs-sb-toggle" onClick={() => setSidebarCollapsed(false)} title="Expand sidebar">
          <PanelLeftOpen size={16} />
        </button>
        <div className="obs-sb-collapsed-icons">
          <button
            className={`obs-sb-icon-btn ${sidebarPanel === 'files' ? 'active' : ''}`}
            onClick={() => { setSidebarPanel('files'); setSidebarCollapsed(false); }}
            title="Files"
          >
            <FolderOpen size={16} />
          </button>
          <button
            className={`obs-sb-icon-btn ${sidebarPanel === 'tags' ? 'active' : ''}`}
            onClick={() => { setSidebarPanel('tags'); setSidebarCollapsed(false); }}
            title="Tags"
          >
            <Tag size={16} />
          </button>
          <button
            className={`obs-sb-icon-btn ${sidebarPanel === 'backlinks' ? 'active' : ''}`}
            onClick={() => { setSidebarPanel('backlinks'); setSidebarCollapsed(false); }}
            title="Backlinks"
          >
            <Link2 size={16} />
          </button>
        </div>
        <div className="obs-sb-collapsed-bottom">
          <button
            className={`obs-sb-icon-btn ${viewMode === 'graph' ? 'active' : ''}`}
            onClick={() => setViewMode(viewMode === 'graph' ? 'editor' : 'graph')}
            title="Graph View"
          >
            <GitGraph size={16} />
          </button>
          <button
            className={`obs-sb-icon-btn ${viewMode === 'search' ? 'active' : ''}`}
            onClick={() => setViewMode(viewMode === 'search' ? 'editor' : 'search')}
            title="Search"
          >
            <Search size={16} />
          </button>
        </div>

      </div>
    );
  }

  return (
    <div className="obs-sidebar">
      {/* Header */}
      <div className="obs-sb-header">
        <button className="obs-sb-back" onClick={() => setSelectedSessionId(null)} title="Back to sessions">
          <ArrowLeft size={14} />
        </button>
        <span className="obs-sb-brand">GenY Vault</span>
        <div className="obs-sb-header-actions">
          <button className="obs-sb-icon-btn" onClick={handleRefresh} title="Refresh">
            <RefreshCw size={13} />
          </button>
          <button className="obs-sb-toggle" onClick={() => setSidebarCollapsed(true)}>
            <PanelLeftClose size={14} />
          </button>
        </div>
      </div>

      {/* Panel switcher */}
      <div className="obs-sb-tabs">
        {([
          ['files', FolderOpen, 'Files'],
          ['tags', Tag, 'Tags'],
          ['backlinks', Link2, 'Links'],
        ] as const).map(([key, Icon, label]) => (
          <button
            key={key}
            className={`obs-sb-tab ${sidebarPanel === key ? 'active' : ''}`}
            onClick={() => setSidebarPanel(key)}
          >
            <Icon size={13} />
            {label}
          </button>
        ))}
      </div>

      {/* View mode switcher */}
      <div className="obs-sb-view-modes">
        <button
          className={`obs-sb-view-btn ${viewMode === 'editor' ? 'active' : ''}`}
          onClick={() => setViewMode('editor')}
        >
          <FileText size={13} /> Editor
        </button>
        <button
          className={`obs-sb-view-btn ${viewMode === 'graph' ? 'active' : ''}`}
          onClick={() => setViewMode('graph')}
        >
          <GitGraph size={13} /> Graph
        </button>
        <button
          className={`obs-sb-view-btn ${viewMode === 'search' ? 'active' : ''}`}
          onClick={() => setViewMode('search')}
        >
          <Search size={13} /> Search
        </button>
      </div>

      {/* Content */}
      <div className="obs-sb-body">
        {/* FILES panel */}
        {sidebarPanel === 'files' && (
          <>
            <div className="obs-sb-filter">
              <Search size={12} className="obs-sb-filter-icon" />
              <input
                type="text"
                placeholder="Filter files…"
                value={filterText}
                onChange={(e) => setFilterText(e.target.value)}
                className="obs-sb-filter-input"
              />
            </div>
            <div className="obs-sb-tree">
              {Object.entries(grouped).map(([cat, catFiles]) => {
                if (catFiles.length === 0) return null;
                const CatIcon = CATEGORY_ICONS[cat] || File;
                const expanded = expandedCategories.has(cat);
                return (
                  <div key={cat} className="obs-sb-category">
                    <button
                      className="obs-sb-cat-header"
                      onClick={() => toggleCategory(cat)}
                    >
                      {expanded ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
                      <CatIcon size={13} style={{ color: CATEGORY_COLORS[cat] }} />
                      <span className="obs-sb-cat-name">{cat}</span>
                      <span className="obs-sb-cat-count">{catFiles.length}</span>
                    </button>
                    {expanded && (
                      <div className="obs-sb-cat-files">
                        {catFiles.map((f) => (
                          <button
                            key={f.filename}
                            className={`obs-sb-file ${selectedFile === f.filename ? 'active' : ''}`}
                            onClick={() => handleFileClick(f.filename)}
                            title={f.filename}
                          >
                            <span
                              className="obs-sb-imp-dot"
                              style={{ background: IMPORTANCE_DOT[f.importance] || IMPORTANCE_DOT.medium }}
                            />
                            <span className="obs-sb-file-title">{f.title || f.filename}</span>
                          </button>
                        ))}
                      </div>
                    )}
                  </div>
                );
              })}
            </div>
          </>
        )}

        {/* TAGS panel */}
        {sidebarPanel === 'tags' && (
          <div className="obs-sb-tags">
            {sortedTags.length === 0 ? (
              <p className="obs-sb-muted">No tags found</p>
            ) : (
              sortedTags.map(([tag, fns]) => (
                <button
                  key={tag}
                  className="obs-sb-tag-item"
                  onClick={() => {
                    if (fns.length > 0) handleFileClick(fns[0]);
                  }}
                >
                  <Tag size={12} />
                  <span className="obs-sb-tag-name">#{tag}</span>
                  <span className="obs-sb-tag-count">{fns.length}</span>
                </button>
              ))
            )}
          </div>
        )}

        {/* BACKLINKS panel */}
        {sidebarPanel === 'backlinks' && (
          <div className="obs-sb-backlinks">
            {!selectedFile ? (
              <p className="obs-sb-muted">Select a file to see backlinks</p>
            ) : backlinks.length === 0 ? (
              <p className="obs-sb-muted">No backlinks for this file</p>
            ) : (
              backlinks.map((fn) => {
                const info = files[fn];
                return (
                  <button
                    key={fn}
                    className="obs-sb-file"
                    onClick={() => handleFileClick(fn)}
                  >
                    <Link2 size={12} />
                    <span className="obs-sb-file-title">{info?.title || fn}</span>
                  </button>
                );
              })
            )}

            {/* Forward links */}
            {selectedFile && files[selectedFile]?.links_to?.length > 0 && (
              <>
                <div className="obs-sb-section-title">Outgoing Links</div>
                {files[selectedFile].links_to.map((target) => {
                  const targetFile = Object.values(files).find(
                    (f) => f.filename.toLowerCase().includes(target.toLowerCase())
                  );
                  return (
                    <button
                      key={target}
                      className="obs-sb-file"
                      onClick={() => targetFile && handleFileClick(targetFile.filename)}
                    >
                      <ChevronRight size={12} />
                      <span className="obs-sb-file-title">{target}</span>
                    </button>
                  );
                })}
              </>
            )}
          </div>
        )}
      </div>
    </div>
  );
}
