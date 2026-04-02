'use client';

import { useMemo } from 'react';
import { useObsidianStore } from '@/store/useObsidianStore';
import { memoryApi } from '@/lib/api';
import {
  Tag,
  Link2,
  AlertCircle,
  FileText,
  Hash,
  BoxSelect,
  ChevronRight,
} from 'lucide-react';

const IMPORTANCE_COLORS: Record<string, string> = {
  critical: '#ef4444',
  high: '#f59e0b',
  medium: '#3b82f6',
  low: '#64748b',
};

export default function RightPanel() {
  const {
    selectedFile,
    fileDetail,
    files,
    memoryStats,
    memoryIndex,
    selectedSessionId,
    openFile,
    setFileDetail,
    setViewMode,
  } = useObsidianStore();

  const fileInfo = selectedFile ? files[selectedFile] : null;
  // metadata accessed via fileInfo

  // Build outline from body headings
  const fileBody = fileDetail?.body ?? '';
  const headings = useMemo(() => {
    if (!fileBody) return [];
    const lines = fileBody.split('\n');
    const result: { level: number; text: string }[] = [];
    for (const line of lines) {
      const match = line.match(/^(#{1,6})\s+(.+)$/);
      if (match) {
        result.push({ level: match[1].length, text: match[2] });
      }
    }
    return result;
  }, [fileBody]);

  const handleFileNavigate = async (filename: string) => {
    openFile(filename);
    if (selectedSessionId) {
      try {
        const detail = await memoryApi.readFile(selectedSessionId, filename);
        setFileDetail(detail);
        setViewMode('editor');
      } catch (e) {
        console.error(e);
      }
    }
  };

  // Stats overview when no file is selected
  const stats = memoryStats;
  const categories = stats?.categories || {};

  return (
    <div className="obs-rpanel">
      {/* When file is selected: show metadata */}
      {fileInfo ? (
        <>
          {/* Properties section */}
          <div className="obs-rp-section">
            <div className="obs-rp-section-title">
              <BoxSelect size={12} /> Properties
            </div>
            <div className="obs-rp-props">
              <div className="obs-rp-prop">
                <span className="obs-rp-prop-key">Category</span>
                <span className="obs-rp-prop-val obs-rp-capitalize">{fileInfo.category}</span>
              </div>
              <div className="obs-rp-prop">
                <span className="obs-rp-prop-key">Importance</span>
                <span className="obs-rp-prop-val" style={{ color: IMPORTANCE_COLORS[fileInfo.importance] }}>
                  <AlertCircle size={10} />
                  {fileInfo.importance}
                </span>
              </div>
              <div className="obs-rp-prop">
                <span className="obs-rp-prop-key">Source</span>
                <span className="obs-rp-prop-val">{fileInfo.source}</span>
              </div>
              <div className="obs-rp-prop">
                <span className="obs-rp-prop-key">Size</span>
                <span className="obs-rp-prop-val">{fileInfo.char_count.toLocaleString()} chars</span>
              </div>
              <div className="obs-rp-prop">
                <span className="obs-rp-prop-key">Created</span>
                <span className="obs-rp-prop-val">
                  {fileInfo.created ? new Date(fileInfo.created).toLocaleString('ko-KR') : '—'}
                </span>
              </div>
              <div className="obs-rp-prop">
                <span className="obs-rp-prop-key">Modified</span>
                <span className="obs-rp-prop-val">
                  {fileInfo.modified ? new Date(fileInfo.modified).toLocaleString('ko-KR') : '—'}
                </span>
              </div>
            </div>
          </div>

          {/* Tags */}
          {fileInfo.tags.length > 0 && (
            <div className="obs-rp-section">
              <div className="obs-rp-section-title">
                <Tag size={12} /> Tags
              </div>
              <div className="obs-rp-tags">
                {fileInfo.tags.map((tag) => (
                  <span key={tag} className="obs-rp-tag">#{tag}</span>
                ))}
              </div>
            </div>
          )}

          {/* Outgoing links */}
          {fileInfo.links_to.length > 0 && (
            <div className="obs-rp-section">
              <div className="obs-rp-section-title">
                <ChevronRight size={12} /> Outgoing Links ({fileInfo.links_to.length})
              </div>
              <div className="obs-rp-links">
                {fileInfo.links_to.map((target) => {
                  const targetFile = Object.values(files).find(
                    (f) => f.filename.toLowerCase().includes(target.toLowerCase())
                  );
                  return (
                    <button
                      key={target}
                      className="obs-rp-link"
                      onClick={() => targetFile && handleFileNavigate(targetFile.filename)}
                    >
                      <FileText size={11} />
                      {target}
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {/* Backlinks */}
          {fileInfo.linked_from.length > 0 && (
            <div className="obs-rp-section">
              <div className="obs-rp-section-title">
                <Link2 size={12} /> Backlinks ({fileInfo.linked_from.length})
              </div>
              <div className="obs-rp-links">
                {fileInfo.linked_from.map((fn) => {
                  const info = files[fn];
                  return (
                    <button
                      key={fn}
                      className="obs-rp-link"
                      onClick={() => handleFileNavigate(fn)}
                    >
                      <Link2 size={11} />
                      {info?.title || fn}
                    </button>
                  );
                })}
              </div>
            </div>
          )}

          {/* Outline */}
          {headings.length > 0 && (
            <div className="obs-rp-section">
              <div className="obs-rp-section-title">
                <Hash size={12} /> Outline
              </div>
              <div className="obs-rp-outline">
                {headings.map((h, i) => (
                  <div
                    key={i}
                    className="obs-rp-outline-item"
                    style={{ paddingLeft: (h.level - 1) * 12 + 8 }}
                  >
                    {h.text}
                  </div>
                ))}
              </div>
            </div>
          )}
        </>
      ) : (
        /* Vault stats when no file selected */
        <div className="obs-rp-section">
          <div className="obs-rp-section-title">
            <BoxSelect size={12} /> Vault Stats
          </div>
          <div className="obs-rp-props">
            <div className="obs-rp-prop">
              <span className="obs-rp-prop-key">Total Files</span>
              <span className="obs-rp-prop-val">{stats?.total_files ?? 0}</span>
            </div>
            <div className="obs-rp-prop">
              <span className="obs-rp-prop-key">Total Characters</span>
              <span className="obs-rp-prop-val">{(memoryIndex?.total_chars ?? 0).toLocaleString()}</span>
            </div>
            <div className="obs-rp-prop">
              <span className="obs-rp-prop-key">LTM Entries</span>
              <span className="obs-rp-prop-val">{stats?.long_term_entries ?? 0}</span>
            </div>
            <div className="obs-rp-prop">
              <span className="obs-rp-prop-key">STM Entries</span>
              <span className="obs-rp-prop-val">{stats?.short_term_entries ?? 0}</span>
            </div>
            <div className="obs-rp-prop">
              <span className="obs-rp-prop-key">Total Tags</span>
              <span className="obs-rp-prop-val">{stats?.total_tags ?? 0}</span>
            </div>
            <div className="obs-rp-prop">
              <span className="obs-rp-prop-key">Total Links</span>
              <span className="obs-rp-prop-val">{stats?.total_links ?? 0}</span>
            </div>
            {stats?.last_write && (
              <div className="obs-rp-prop">
                <span className="obs-rp-prop-key">Last Write</span>
                <span className="obs-rp-prop-val">
                  {new Date(stats.last_write).toLocaleString('ko-KR')}
                </span>
              </div>
            )}
          </div>

          {/* Categories breakdown */}
          {Object.keys(categories).length > 0 && (
            <div className="obs-rp-cats">
              <div className="obs-rp-section-title" style={{ marginTop: 16 }}>
                Categories
              </div>
              {Object.entries(categories)
                .sort((a, b) => b[1] - a[1])
                .map(([cat, count]) => (
                  <div key={cat} className="obs-rp-cat-row">
                    <span className="obs-rp-capitalize">{cat}</span>
                    <div className="obs-rp-cat-bar-bg">
                      <div
                        className="obs-rp-cat-bar"
                        style={{
                          width: `${Math.min(100, (count / Math.max(...Object.values(categories))) * 100)}%`,
                        }}
                      />
                    </div>
                    <span className="obs-rp-cat-count">{count}</span>
                  </div>
                ))}
            </div>
          )}
        </div>
      )}
    </div>
  );
}
