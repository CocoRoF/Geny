'use client';

import { useState, useEffect, useCallback } from 'react';
import { useOpsidianStore } from '@/store/useOpsidianStore';
import { useUserOpsidianStore } from '@/store/useUserOpsidianStore';
import { useCuratedKnowledgeStore } from '@/store/useCuratedKnowledgeStore';
import { useHubMode } from '@/components/OpsidianHubContext';
import { useI18n } from '@/lib/i18n';
import ShortcutHelp from './ShortcutHelp';
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
  ArrowLeftRight,
  Keyboard,
} from 'lucide-react';

export default function StatusBar({ onRefresh }: { onRefresh: () => void }) {
  const hub = useHubMode();
  const { t } = useI18n();
  const [showShortcuts, setShowShortcuts] = useState(false);

  // Global Ctrl+/ shortcut to open/close help modal
  useEffect(() => {
    const handleKey = (e: KeyboardEvent) => {
      if ((e.ctrlKey || e.metaKey) && e.key === '/') {
        e.preventDefault();
        setShowShortcuts(prev => !prev);
      }
    };
    window.addEventListener('keydown', handleKey);
    return () => window.removeEventListener('keydown', handleKey);
  }, []);

  // Always read all three stores — pick data based on hub mode
  const opsidian = useOpsidianStore();
  const userStore = useUserOpsidianStore();
  const curatedStore = useCuratedKnowledgeStore();

  const isUserMode = hub?.mode === 'user';
  const isCuratorMode = hub?.mode === 'curator';

  // Derived data — switch source based on mode
  const totalFiles = isCuratorMode
    ? (curatedStore.stats?.total_files ?? 0)
    : isUserMode
      ? (userStore.stats?.total_files ?? 0)
      : (opsidian.memoryStats?.total_files ?? opsidian.vaultTotals?.total_files ?? 0);
  const totalChars = isCuratorMode
    ? (curatedStore.stats?.total_chars ?? 0)
    : isUserMode
      ? (userStore.stats?.total_chars ?? 0)
      : (opsidian.memoryIndex?.total_chars ?? opsidian.vaultTotals?.total_chars ?? 0);
  const totalTags = isCuratorMode
    ? (curatedStore.stats?.total_tags ?? 0)
    : isUserMode
      ? (userStore.stats?.total_tags ?? 0)
      : (opsidian.memoryStats?.total_tags ?? '—');  // only the full index knows
  const totalLinks = isCuratorMode
    ? (curatedStore.stats?.total_links ?? 0)
    : isUserMode
      ? (userStore.stats?.total_links ?? 0)
      : (opsidian.memoryStats?.total_links ?? '—');  // only the full index knows
  const loading = isCuratorMode
    ? curatedStore.loading
    : isUserMode ? userStore.loading : opsidian.loading;
  const selectedFile = isCuratorMode
    ? curatedStore.selectedFile
    : isUserMode ? userStore.selectedFile : opsidian.selectedFile;
  const viewMode = isCuratorMode
    ? curatedStore.viewMode
    : isUserMode ? userStore.viewMode : opsidian.viewMode;
  const rightPanelOpen = isCuratorMode
    ? curatedStore.rightPanelOpen
    : isUserMode ? userStore.rightPanelOpen : opsidian.rightPanelOpen;
  const togglePanel = isCuratorMode
    ? () => curatedStore.setRightPanelOpen(!curatedStore.rightPanelOpen)
    : isUserMode
      ? () => userStore.setRightPanelOpen(!userStore.rightPanelOpen)
      : () => opsidian.setRightPanelOpen(!opsidian.rightPanelOpen);
  const showViewMode = isUserMode || isCuratorMode || !!opsidian.selectedSessionId;

  // Session info for sessions mode
  const selectedSession = !isUserMode && !isCuratorMode && opsidian.selectedSessionId
    ? opsidian.sessions.find(s => s.session_id === opsidian.selectedSessionId)
    : null;
  const sessionLabel = selectedSession
    ? (selectedSession.session_name || selectedSession.session_id.slice(0, 8))
    : null;

  // Without hub context (standalone session page), hide when no session
  if (!hub && !opsidian.selectedSessionId) return null;

  return (
    <div className="obs-statusbar">
      <div className="obs-sb-left">
        {/* Hub navigation buttons — 3 tabs */}
        {hub && (
          <div className="obs-hub-nav">
            <button
              className={`obs-hub-nav-btn ${hub.mode === 'user' ? 'obs-hub-nav-active' : ''}`}
              onClick={() => hub.setMode('user')}
            >
              {t('opsidian.userVault')}
            </button>
            <button
              className={`obs-hub-nav-btn ${hub.mode === 'curator' ? 'obs-hub-nav-active' : ''}`}
              onClick={() => hub.setMode('curator')}
            >
              {t('opsidian.curatedVault')}
            </button>
            <button
              className={`obs-hub-nav-btn ${hub.mode === 'sessions' ? 'obs-hub-nav-active' : ''}`}
              onClick={() => hub.setMode('sessions')}
            >
              {t('opsidian.sessionsVault')}
            </button>
            <span className="obs-hub-nav-sep" />
          </div>
        )}
        <span className="obs-sb-item obs-sb-brand-item">
          <Brain size={12} />
          GenY Opsidian
        </span>
        {/* Session indicator in sessions mode */}
        {!isUserMode && !isCuratorMode && sessionLabel && (
          <button
            className="obs-sb-item obs-sb-session-btn"
            onClick={() => opsidian.setSelectedSessionId(null)}
            title={t('opsidian.changeSession')}
          >
            <ArrowLeftRight size={11} />
            {sessionLabel}
          </button>
        )}
        <span className="obs-sb-item">
          <FileText size={11} />
          {totalFiles} files
        </span>
        <span className="obs-sb-item">
          <Database size={11} />
          {(totalChars / 1000).toFixed(1)}K chars
        </span>
        <span className="obs-sb-item">
          <Tag size={11} />
          {totalTags} tags
        </span>
        <span className="obs-sb-item">
          <Link2 size={11} />
          {totalLinks} links
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
        {showViewMode && <span className="obs-sb-item obs-sb-mode">{viewMode}</span>}
        <button className="obs-sb-btn" onClick={onRefresh} title="Refresh memory">
          <RefreshCw size={11} />
        </button>
        <button
          className="obs-sb-btn"
          onClick={togglePanel}
          title={rightPanelOpen ? 'Hide right panel' : 'Show right panel'}
        >
          {rightPanelOpen ? <PanelRightClose size={11} /> : <PanelRight size={11} />}
        </button>
        <button
          className="obs-sb-btn"
          onClick={() => setShowShortcuts(true)}
          title={`${t('opsidian.keyboardShortcuts')} (Ctrl+/)`}
        >
          <Keyboard size={11} />
        </button>
      </div>
      {showShortcuts && <ShortcutHelp onClose={() => setShowShortcuts(false)} />}
    </div>
  );
}
