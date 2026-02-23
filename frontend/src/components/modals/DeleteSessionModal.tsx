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
    <div className="modal-overlay" onClick={onClose}>
      <div className="modal" style={{ maxWidth: '400px' }} onClick={e => e.stopPropagation()}>
        <div className="modal-header">
          <h3 className="modal-title">Delete Session</h3>
          <button className="btn-close" onClick={onClose}>×</button>
        </div>
        <div className="modal-body">
          <p className="text-[0.8125rem] text-[var(--text-secondary)]">
            Are you sure you want to delete <strong className="text-[var(--text-primary)]">{session.session_name || session.session_id.substring(0, 12)}</strong>?
          </p>
          <p className="text-[0.75rem] text-[var(--text-muted)] mt-3">This will soft-delete the session. You can restore it from the deleted sessions section.</p>
        </div>
        <div className="modal-footer">
          <button className="btn" onClick={onClose}>Cancel</button>
          <button className="btn btn-danger" onClick={handleDelete} disabled={deleting}>
            {deleting ? 'Deleting...' : 'Delete'}
          </button>
        </div>
      </div>
    </div>
  );
}
