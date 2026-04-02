'use client';

import { useObsidianStore } from '@/store/useObsidianStore';
import {
  RefreshCw,
  FileText,
  Database,
  Tag,
  Link2,
  Brain,
  PanelRight,
  PanelRightClose,
  Loader2,
} from 'lucide-react';

export default function StatusBar({ onRefresh }: { onRefresh: () => void }) {
  const {
    selectedSessionId,
    memoryStats,
    memoryIndex,
    loading,
    selectedFile,
    viewMode,
    rightPanelOpen,
    setRightPanelOpen,
  } = useObsidianStore();

  if (!selectedSessionId) return null;

  const stats = memoryStats;

  return (
    <div className="obs-statusbar">
      <div className="obs-sb-left">
        <span className="obs-sb-item obs-sb-brand-item">
          <Brain size={12} />
          GenY Obsidian
        </span>
        <span className="obs-sb-item">
          <FileText size={11} />
          {stats?.total_files ?? 0} files
        </span>
        <span className="obs-sb-item">
          <Database size={11} />
          {((memoryIndex?.total_chars ?? 0) / 1000).toFixed(1)}K chars
        </span>
        <span className="obs-sb-item">
          <Tag size={11} />
          {stats?.total_tags ?? 0} tags
        </span>
        <span className="obs-sb-item">
          <Link2 size={11} />
          {stats?.total_links ?? 0} links
        </span>
      </div>
      <div className="obs-sb-right">
        {loading && (
          <span className="obs-sb-item">
            <Loader2 size={11} className="spin" />
            Loading…
          </span>
        )}
        {selectedFile && (
          <span className="obs-sb-item obs-sb-file">
            {selectedFile}
          </span>
        )}
        <span className="obs-sb-item obs-sb-mode">{viewMode}</span>
        <button className="obs-sb-btn" onClick={onRefresh} title="Refresh memory">
          <RefreshCw size={11} />
        </button>
        <button
          className="obs-sb-btn"
          onClick={() => setRightPanelOpen(!rightPanelOpen)}
          title={rightPanelOpen ? 'Hide right panel' : 'Show right panel'}
        >
          {rightPanelOpen ? <PanelRightClose size={11} /> : <PanelRight size={11} />}
        </button>
      </div>
    </div>
  );
}
