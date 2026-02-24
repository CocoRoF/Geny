'use client';

import { useState } from 'react';
import { useAppStore } from '@/store/useAppStore';
import type { SessionInfo } from '@/types';

interface Props { session: SessionInfo; onClose: () => void; }

export default function DeleteSessionModal({ session, onClose }: Props) {
  const { deleteSession } = useAppStore();
  const [deleting, setDeleting] = useState(false);

  const handleDelete = async () => {
    setDeleting(true);
    try {
      await deleteSession(session.session_id);
      onClose();
    } catch {
      setDeleting(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <div className="bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-lg w-full max-w-[400px] max-h-[85vh] flex flex-col shadow-[var(--shadow-lg)]" onClick={e => e.stopPropagation()}>
        <div className="flex justify-between items-center py-4 px-6 border-b border-[var(--border-color)]">
          <h3 className="text-[1rem] font-semibold text-[var(--text-primary)]">Delete Session</h3>
          <button className="flex items-center justify-center w-8 h-8 rounded-[var(--border-radius)] bg-transparent border-none text-[var(--text-muted)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)] cursor-pointer text-lg" onClick={onClose}>×</button>
        </div>
        <div className="flex-1 overflow-y-auto px-6 py-5 flex flex-col gap-4">
          <p className="text-[0.8125rem] text-[var(--text-secondary)]">
            Are you sure you want to delete <strong className="text-[var(--text-primary)]">{session.session_name || session.session_id.substring(0, 12)}</strong>?
          </p>
          <p className="text-[0.75rem] text-[var(--text-muted)] mt-3">This will soft-delete the session. You can restore it from the deleted sessions section.</p>
        </div>
        <div className="flex justify-end items-center gap-3 py-4 px-6 border-t border-[var(--border-color)]">
          <button className="py-2 px-4 bg-transparent hover:bg-[var(--bg-hover)] text-[var(--text-secondary)] text-[0.8125rem] font-medium rounded-[var(--border-radius)] cursor-pointer transition-all duration-150 border border-[var(--border-color)]" onClick={onClose}>Cancel</button>
          <button className="py-2 px-4 bg-[var(--danger-color)] hover:brightness-110 text-white text-[0.8125rem] font-medium rounded-[var(--border-radius)] cursor-pointer transition-all duration-150 border-none disabled:opacity-50 disabled:cursor-not-allowed" onClick={handleDelete} disabled={deleting}>
            {deleting ? 'Deleting...' : 'Delete'}
          </button>
        </div>
      </div>
    </div>
  );
}
