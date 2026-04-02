'use client';

import { useState, useCallback, useRef } from 'react';
import { useObsidianStore } from '@/store/useObsidianStore';
import { memoryApi } from '@/lib/api';
import {
  Search,
  File,
  Tag,
  Loader2,
  AlertCircle,
  X,
} from 'lucide-react';

const IMPORTANCE_COLORS: Record<string, string> = {
  critical: '#ef4444',
  high: '#f59e0b',
  medium: '#3b82f6',
  low: '#64748b',
};

export default function SearchPanel() {
  const {
    searchQuery,
    searchResults,
    searching,
    selectedSessionId,
    files,
    setSearchQuery,
    setSearchResults,
    setSearching,
    openFile,
    setFileDetail,
    setViewMode,
  } = useObsidianStore();

  const [localQuery, setLocalQuery] = useState(searchQuery);
  const inputRef = useRef<HTMLInputElement>(null);

  const doSearch = useCallback(async () => {
    if (!localQuery.trim() || !selectedSessionId) return;
    setSearchQuery(localQuery);
    setSearching(true);
    try {
      const res = await memoryApi.search(selectedSessionId, localQuery, { max_results: 20 });
      setSearchResults(res.results);
    } catch (err) {
      console.error('Search failed:', err);
      setSearchResults([]);
    } finally {
      setSearching(false);
    }
  }, [localQuery, selectedSessionId, setSearchQuery, setSearching, setSearchResults]);

  const handleKeyDown = (e: React.KeyboardEvent) => {
    if (e.key === 'Enter') doSearch();
  };

  const handleResultClick = async (filename: string) => {
    openFile(filename);
    setViewMode('editor');
    if (selectedSessionId) {
      try {
        const detail = await memoryApi.readFile(selectedSessionId, filename);
        setFileDetail(detail);
      } catch (e) {
        console.error('Failed to read:', e);
      }
    }
  };

  return (
    <div className="obs-search">
      {/* Search bar */}
      <div className="obs-search-bar">
        <Search size={16} className="obs-search-icon" />
        <input
          ref={inputRef}
          type="text"
          placeholder="Search memory notes… (text + semantic)"
          value={localQuery}
          onChange={(e) => setLocalQuery(e.target.value)}
          onKeyDown={handleKeyDown}
          className="obs-search-input"
          autoFocus
        />
        {localQuery && (
          <button
            className="obs-search-clear"
            onClick={() => {
              setLocalQuery('');
              setSearchResults([]);
              inputRef.current?.focus();
            }}
          >
            <X size={14} />
          </button>
        )}
        <button className="obs-search-btn" onClick={doSearch} disabled={searching}>
          {searching ? <Loader2 size={14} className="spin" /> : 'Search'}
        </button>
      </div>

      {/* Results */}
      <div className="obs-search-results">
        {searching ? (
          <div className="obs-search-status">
            <Loader2 size={16} className="spin" />
            Searching across memory…
          </div>
        ) : searchResults.length === 0 && searchQuery ? (
          <div className="obs-search-status">
            No results found for &ldquo;{searchQuery}&rdquo;
          </div>
        ) : searchResults.length > 0 ? (
          <>
            <div className="obs-search-count">
              {searchResults.length} result{searchResults.length > 1 ? 's' : ''} for &ldquo;{searchQuery}&rdquo;
            </div>
            {searchResults.map((r, idx) => {
              const entry = r.entry;
              const impColor = IMPORTANCE_COLORS[entry.importance] || IMPORTANCE_COLORS.medium;
              const fileInfo = entry.filename ? files[entry.filename] : null;

              return (
                <button
                  key={idx}
                  className="obs-search-result"
                  onClick={() => entry.filename && handleResultClick(entry.filename)}
                >
                  <div className="obs-sr-header">
                    <File size={13} />
                    <span className="obs-sr-title">
                      {entry.title || entry.filename || 'Untitled'}
                    </span>
                    <span className="obs-sr-score">{(r.score * 100).toFixed(0)}%</span>
                  </div>

                  <div className="obs-sr-snippet">{r.snippet.slice(0, 200)}</div>

                  <div className="obs-sr-meta">
                    <span
                      className="obs-sr-importance"
                      style={{ color: impColor, borderColor: impColor }}
                    >
                      <AlertCircle size={10} />
                      {entry.importance}
                    </span>
                    {entry.category && (
                      <span className="obs-sr-badge">{entry.category}</span>
                    )}
                    {r.match_type && (
                      <span className="obs-sr-badge obs-sr-match">{r.match_type}</span>
                    )}
                    {entry.tags?.slice(0, 3).map((tag) => (
                      <span key={tag} className="obs-sr-tag">
                        <Tag size={9} />
                        {tag}
                      </span>
                    ))}
                    {fileInfo && (
                      <span className="obs-sr-chars">
                        {fileInfo.char_count.toLocaleString()} chars
                      </span>
                    )}
                  </div>
                </button>
              );
            })}
          </>
        ) : (
          <div className="obs-search-empty">
            <Search size={40} strokeWidth={1} />
            <p>Search across all memory notes</p>
            <p className="obs-search-hint">
              Uses both text matching and semantic vector search
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
