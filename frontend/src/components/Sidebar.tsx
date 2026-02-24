'use client';

import { useState, useCallback } from 'react';
import { useAppStore } from '@/store/useAppStore';
import { twMerge } from 'tailwind-merge';
import type { SessionInfo } from '@/types';

function cn(...classes: (string | boolean | undefined | null)[]) {
  return twMerge(classes.filter(Boolean).join(' '));
}
import CreateSessionModal from '@/components/modals/CreateSessionModal';
import DeleteSessionModal from '@/components/modals/DeleteSessionModal';

function SessionItem({ session, isSelected, onSelect }: {
  session: SessionInfo; isSelected: boolean; onSelect: () => void;
}) {
  const dotClass = session.status === 'running' ? 'bg-[var(--success-color)]'
    : session.status === 'error' ? 'bg-[var(--danger-color)]'
    : session.status === 'starting' ? 'bg-[var(--warning-color)]'
    : 'bg-[var(--text-muted)]';

  const dotShadow = session.status === 'running'
    ? { boxShadow: '0 0 6px var(--success-color)' }
    : undefined;

  const isManager = session.role === 'manager';

  return (
    <div
      className={`flex items-center py-3 px-3.5 mb-1 rounded-[var(--border-radius)] cursor-pointer transition-all duration-150 border
        ${isSelected
          ? 'bg-[var(--primary-subtle)] border-[var(--primary-color)]'
          : 'bg-transparent border-transparent hover:bg-[var(--bg-hover)]'
        }`}
      onClick={onSelect}
    >
      {/* Status dot */}
      <span className={`w-2 h-2 rounded-full mr-3 shrink-0 ${dotClass}`} style={dotShadow} />

      {/* Role badge */}
      <span
        className="inline-flex items-center justify-center w-[18px] h-[18px] rounded text-[10px] font-semibold mr-1.5 text-white shrink-0"
        style={{
          background: isManager
            ? 'linear-gradient(135deg, #8b5cf6, #6366f1)'
            : 'linear-gradient(135deg, #10b981, #059669)',
        }}
      >
        {isManager ? 'M' : 'W'}
      </span>

      {/* Session info */}
      <div className="flex-1 min-w-0">
        <div className="font-medium text-[0.875rem] whitespace-nowrap overflow-hidden text-ellipsis">
          {session.session_name || `Session ${session.session_id.substring(0, 8)}`}
        </div>
        <div className="text-[0.75rem] text-[var(--text-muted)] font-mono mt-0.5">
          {session.session_id.substring(0, 12)}...
        </div>
      </div>
    </div>
  );
}

export default function Sidebar() {
  const {
    sessions, deletedSessions, selectedSessionId, selectSession,
    sidebarCollapsed, deletedSectionOpen, toggleDeletedSection,
    permanentDeleteSession, restoreSession,
  } = useAppStore();

  const [showCreateModal, setShowCreateModal] = useState(false);
  const [deleteTarget, setDeleteTarget] = useState<SessionInfo | null>(null);

  const running = sessions.filter(s => s.status === 'running').length;
  const errors = sessions.filter(s => s.status === 'error').length;

  const handleDeleteClick = useCallback((e: React.MouseEvent, session: SessionInfo) => {
    e.stopPropagation();
    setDeleteTarget(session);
  }, []);

  if (sidebarCollapsed) return null;

  return (
    <>
      <aside className="w-[280px] bg-[var(--bg-secondary)] border-r border-[var(--border-color)] flex flex-col overflow-hidden">
        {/* Sidebar Header */}
        <div className="flex justify-between items-center h-11 px-5 border-b border-[var(--border-color)]">
          <h2 className="text-[0.8125rem] font-medium text-[var(--text-secondary)] uppercase tracking-[0.05em]">
            Sessions
          </h2>
          <div className="flex items-center gap-2">
            <button className="py-1.5 px-3 bg-[var(--primary-color)] hover:bg-[var(--primary-hover)] text-white text-[0.75rem] font-medium rounded-[var(--border-radius)] cursor-pointer transition-all duration-150 border-none disabled:opacity-50 disabled:cursor-not-allowed" onClick={() => setShowCreateModal(true)}>
              New Session
            </button>
          </div>
        </div>

        {/* Session Stats */}
        <div className="grid grid-cols-3 gap-3 px-5 py-4 bg-[var(--bg-primary)] border-b border-[var(--border-color)]">
          <div className="text-center">
            <span className="block text-[1.5rem] font-semibold text-[var(--text-primary)] leading-tight">
              {sessions.length}
            </span>
            <span className="text-[0.6875rem] text-[var(--text-muted)] uppercase tracking-[0.05em] mt-0.5">
              Total
            </span>
          </div>
          <div className="text-center">
            <span className="block text-[1.5rem] font-semibold text-[var(--success-color)] leading-tight">
              {running}
            </span>
            <span className="text-[0.6875rem] text-[var(--text-muted)] uppercase tracking-[0.05em] mt-0.5">
              Running
            </span>
          </div>
          <div className="text-center">
            <span className="block text-[1.5rem] font-semibold text-[var(--danger-color)] leading-tight">
              {errors}
            </span>
            <span className="text-[0.6875rem] text-[var(--text-muted)] uppercase tracking-[0.05em] mt-0.5">
              Errors
            </span>
          </div>
        </div>

        {/* Session List */}
        <div className="flex-1 min-h-0 overflow-y-auto p-3">
          {sessions.length === 0 ? (
            <div className="flex flex-col items-center justify-center py-12 px-4">
              <p className="text-[0.8125rem] text-[var(--text-muted)]">No sessions yet</p>
            </div>
          ) : (
            sessions.map(session => (
              <div key={session.session_id} className="relative group">
                <SessionItem
                  session={session}
                  isSelected={selectedSessionId === session.session_id}
                  onSelect={() => selectSession(session.session_id)}
                />
                <div className="absolute right-2 top-1/2 -translate-y-1/2 flex gap-1 opacity-0 group-hover:opacity-100 transition-opacity duration-150">
                  <button
                    className="flex items-center justify-center w-7 h-7 rounded bg-transparent border-none text-[var(--text-muted)] hover:text-[var(--danger-color)] cursor-pointer transition-colors duration-150"
                    onClick={(e) => handleDeleteClick(e, session)}
                    title="Delete session"
                  >
                    ✕
                  </button>
                </div>
              </div>
            ))
          )}
        </div>

        {/* Deleted Sessions */}
        {deletedSessions.length > 0 && (
          <div className="border-t border-[var(--border-color)]">
            <div
              className="flex items-center gap-2 cursor-pointer select-none hover:text-[var(--text-secondary)] transition-colors duration-150"
              style={{ padding: '10px 16px', fontSize: '12px', fontWeight: 600, textTransform: 'uppercase' as const, letterSpacing: '0.5px', color: 'var(--text-muted)' }}
              onClick={toggleDeletedSection}
            >
              <span style={{ fontSize: '9px', transition: 'transform 0.15s' }}>{deletedSectionOpen ? '▼' : '▶'}</span>
              <span>Deleted Sessions</span>
              <span className="ml-auto text-center" style={{ fontSize: '10px', fontWeight: 600, background: 'rgba(107, 114, 128, 0.2)', color: 'var(--text-muted)', padding: '1px 7px', borderRadius: '10px', minWidth: '18px' }}>
                {deletedSessions.length}
              </span>
            </div>
            {deletedSectionOpen && (
              <div className="max-h-[240px] overflow-y-auto">
                {deletedSessions.map(session => (
                  <div key={session.session_id} className="flex items-center gap-2 px-4 py-1.5 text-[0.8125rem] opacity-70 hover:opacity-100 transition-opacity">
                    <span className="truncate flex-1">
                      {session.session_name || session.session_id.substring(0, 12)}
                    </span>
                    <button
                      className="flex items-center justify-center w-7 h-7 rounded bg-transparent border-none text-[var(--text-muted)] hover:text-[var(--text-primary)] cursor-pointer transition-colors duration-150"
                      onClick={() => restoreSession(session.session_id)}
                      title="Restore"
                    >
                      ↩
                    </button>
                    <button
                      className="flex items-center justify-center w-7 h-7 rounded bg-transparent border-none text-[var(--text-muted)] hover:!text-[var(--danger-color)] cursor-pointer transition-colors duration-150"
                      onClick={() => permanentDeleteSession(session.session_id)}
                      title="Permanently delete"
                    >
                      ✕
                    </button>
                  </div>
                ))}
              </div>
            )}
          </div>
        )}
      </aside>

      {showCreateModal && <CreateSessionModal onClose={() => setShowCreateModal(false)} />}
      {deleteTarget && (
        <DeleteSessionModal session={deleteTarget} onClose={() => setDeleteTarget(null)} />
      )}
    </>
  );
}
