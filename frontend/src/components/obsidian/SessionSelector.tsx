'use client';

import { useObsidianStore } from '@/store/useObsidianStore';
import {
  Brain,
  Clock,
  ArrowRight,
  Loader2,
} from 'lucide-react';

export default function SessionSelector() {
  const { sessions, loadingSessions, setSelectedSessionId } = useObsidianStore();

  const activeSessions = sessions.filter((s) => !s.is_deleted);

  return (
    <div className="session-selector">
      <div className="session-selector-inner">
        {/* Header */}
        <div className="ss-header">
          <div className="ss-logo">
            <Brain size={32} strokeWidth={1.5} />
          </div>
          <h1 className="ss-title">GenY Obsidian</h1>
          <p className="ss-subtitle">
            Select a session to explore its memory vault
          </p>
        </div>

        {/* Session list */}
        {loadingSessions ? (
          <div className="ss-loading">
            <Loader2 size={20} className="spin" />
            <span>Loading sessions…</span>
          </div>
        ) : activeSessions.length === 0 ? (
          <div className="ss-empty">
            No active sessions found. Create one from the main dashboard.
          </div>
        ) : (
          <div className="ss-list">
            {activeSessions.map((s) => (
              <button
                key={s.session_id}
                className="ss-card"
                onClick={() => setSelectedSessionId(s.session_id)}
              >
                <div className="ss-card-top">
                  <span className="ss-card-name">
                    {s.session_name || s.session_id.slice(0, 8)}
                  </span>
                  <span className={`ss-card-role ss-role-${s.role || 'cli'}`}>
                    {s.role || 'cli'}
                  </span>
                </div>
                <div className="ss-card-meta">
                  <span className="ss-card-id">{s.session_id.slice(0, 12)}…</span>
                  {s.created_at && (
                    <span className="ss-card-time">
                      <Clock size={11} />
                      {new Date(s.created_at).toLocaleDateString()}
                    </span>
                  )}
                </div>
                {s.model && (
                  <div className="ss-card-model">{s.model}</div>
                )}
                <ArrowRight size={16} className="ss-card-arrow" />
              </button>
            ))}
          </div>
        )}
      </div>
    </div>
  );
}
