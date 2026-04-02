'use client';

import { useMemo, useCallback } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import { useObsidianStore } from '@/store/useObsidianStore';
import { memoryApi } from '@/lib/api';
import {
  Tag,
  Link2,
  Clock,
  AlertCircle,
  Calendar,
  Bookmark,
  Users,
  FolderKanban,
  Lightbulb,
  FileText,
  ExternalLink,
} from 'lucide-react';

const IMPORTANCE_STYLES: Record<string, { bg: string; color: string; label: string }> = {
  critical: { bg: 'rgba(239,68,68,0.15)', color: '#ef4444', label: 'Critical' },
  high: { bg: 'rgba(245,158,11,0.15)', color: '#f59e0b', label: 'High' },
  medium: { bg: 'rgba(59,130,246,0.1)', color: '#3b82f6', label: 'Medium' },
  low: { bg: 'rgba(100,116,139,0.1)', color: '#64748b', label: 'Low' },
};

const CATEGORY_ICONS: Record<string, typeof FileText> = {
  daily: Calendar,
  topics: Bookmark,
  entities: Users,
  projects: FolderKanban,
  insights: Lightbulb,
};

export default function NoteViewer() {
  const {
    selectedFile,
    fileDetail,
    files,
    selectedSessionId,
    openFile,
    setFileDetail,
  } = useObsidianStore();

  // Navigate to a file via wikilink
  const navigateToFile = useCallback(
    async (target: string) => {
      const targetLower = target.toLowerCase();
      const match = Object.values(files).find(
        (f) =>
          f.filename.toLowerCase().includes(targetLower) ||
          f.title.toLowerCase() === targetLower
      );
      if (match && selectedSessionId) {
        openFile(match.filename);
        try {
          const detail = await memoryApi.readFile(selectedSessionId, match.filename);
          setFileDetail(detail);
        } catch (e) {
          console.error('Failed to read:', e);
        }
      }
    },
    [files, selectedSessionId, openFile, setFileDetail]
  );

  // Process markdown body to render wikilinks
  const body = fileDetail?.body ?? '';
  const processedBody = useMemo(() => {
    if (!body) return '';
    // Replace [[link|alias]] and [[link]] with markdown links
    return body.replace(
      /\[\[([^\]|]+)(?:\|([^\]]+))?\]\]/g,
      (_match, target, alias) => {
        const display = alias || target;
        return `[🔗 ${display}](wikilink://${encodeURIComponent(target)})`;
      }
    );
  }, [body]);

  if (!selectedFile) {
    return (
      <div className="obs-note-empty">
        <div className="obs-note-empty-inner">
          <FileText size={48} strokeWidth={1} />
          <p>Select a note from the sidebar to view it</p>
          <p className="obs-note-hint">
            Or press <kbd>Ctrl+G</kbd> to open the Graph View
          </p>
        </div>
      </div>
    );
  }

  if (!fileDetail) {
    return (
      <div className="obs-note-empty">
        <div className="obs-note-loading">Loading note…</div>
      </div>
    );
  }

  const meta = fileDetail.metadata || {};
  const importance = IMPORTANCE_STYLES[(meta.importance as string) || 'medium'] || IMPORTANCE_STYLES.medium;
  const CatIcon = CATEGORY_ICONS[(meta.category as string) || 'topics'] || FileText;
  const tags = Array.isArray(meta.tags) ? meta.tags : [];
  const linksTo = Array.isArray(meta.links_to) ? meta.links_to : [];
  const linkedFrom = Array.isArray(meta.linked_from) ? meta.linked_from : [];
  const fileInfo = files[selectedFile];

  return (
    <div className="obs-note">
      {/* Frontmatter header */}
      <div className="obs-note-header">
        <div className="obs-note-title-row">
          <CatIcon size={18} style={{ color: 'var(--primary-color)' }} />
          <h1 className="obs-note-title">{(meta.title as string) || selectedFile}</h1>
        </div>

        <div className="obs-note-meta-row">
          <span className="obs-note-badge" style={{ background: importance.bg, color: importance.color }}>
            <AlertCircle size={11} />
            {importance.label}
          </span>
          <span className="obs-note-badge obs-note-badge-cat">
            <CatIcon size={11} />
            {(meta.category as string) || 'topics'}
          </span>
          {meta.source ? (
            <span className="obs-note-badge obs-note-badge-source">
              {String(meta.source)}
            </span>
          ) : null}
          {meta.created ? (
            <span className="obs-note-meta-item">
              <Clock size={11} />
              {new Date(String(meta.created)).toLocaleDateString('ko-KR')}
            </span>
          ) : null}
          {fileInfo && (
            <span className="obs-note-meta-item">
              {fileInfo.char_count.toLocaleString()} chars
            </span>
          )}
        </div>

        {/* Tags */}
        {tags.length > 0 && (
          <div className="obs-note-tags">
            {tags.map((tag) => (
              <span key={String(tag)} className="obs-note-tag">
                <Tag size={10} />
                {String(tag)}
              </span>
            ))}
          </div>
        )}

        {/* Links */}
        {(linksTo.length > 0 || linkedFrom.length > 0) && (
          <div className="obs-note-links">
            {linksTo.length > 0 && (
              <div className="obs-note-link-group">
                <ExternalLink size={11} />
                <span className="obs-note-link-label">Links to:</span>
                {linksTo.map((l) => (
                  <button
                    key={String(l)}
                    className="obs-note-link"
                    onClick={() => navigateToFile(String(l))}
                  >
                    {String(l)}
                  </button>
                ))}
              </div>
            )}
            {linkedFrom.length > 0 && (
              <div className="obs-note-link-group">
                <Link2 size={11} />
                <span className="obs-note-link-label">Linked from:</span>
                {linkedFrom.map((l) => (
                  <button
                    key={String(l)}
                    className="obs-note-link"
                    onClick={() => navigateToFile(String(l))}
                  >
                    {String(l)}
                  </button>
                ))}
              </div>
            )}
          </div>
        )}
      </div>

      {/* Markdown body */}
      <div className="obs-note-body">
        <ReactMarkdown
          remarkPlugins={[remarkGfm]}
          components={{
            a: ({ href, children }) => {
              if (href?.startsWith('wikilink://')) {
                const target = decodeURIComponent(href.replace('wikilink://', ''));
                return (
                  <button
                    className="obs-wikilink"
                    onClick={() => navigateToFile(target)}
                  >
                    {children}
                  </button>
                );
              }
              return (
                <a href={href} target="_blank" rel="noopener noreferrer">
                  {children}
                </a>
              );
            },
            code: ({ className, children, ...props }) => {
              const isInline = !className;
              if (isInline) {
                return <code className="obs-inline-code" {...props}>{children}</code>;
              }
              return (
                <pre className="obs-code-block">
                  <code className={className} {...props}>{children}</code>
                </pre>
              );
            },
          }}
        >
          {processedBody}
        </ReactMarkdown>
      </div>
    </div>
  );
}
