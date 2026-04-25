'use client';

/**
 * HITL approval modal — surfaces a pending Stage 15 approval
 * request and posts the operator's decision back to the backend.
 *
 * Wired to `agentApi.hitlResume` (POST /api/agents/{id}/hitl/resume).
 * The pending request lives on `SessionData.pendingHitl`; the parent
 * (CommandTab) injects it from WS `hitl_request` events and clears
 * it on `hitl_decision` / `hitl_timeout` events. Approving here only
 * dispatches the REST call — clearing happens once the executor
 * echoes the decision back.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { agentApi } from '@/lib/api';
import { useI18n } from '@/lib/i18n';
import type { PendingHitlRequest } from '@/store/useAppStore';
import { AlertTriangle, ShieldAlert, ShieldCheck, X } from 'lucide-react';

interface HITLApprovalModalProps {
  sessionId: string;
  request: PendingHitlRequest;
  onClose: () => void;
}

type Decision = 'approve' | 'reject' | 'cancel';

function severityStyle(severity: string): { color: string; bg: string; Icon: typeof ShieldAlert } {
  const s = severity.toLowerCase();
  if (s === 'critical' || s === 'block' || s === 'error') {
    return { color: 'var(--danger-color)', bg: 'rgba(239,68,68,0.10)', Icon: ShieldAlert };
  }
  if (s === 'warn' || s === 'warning') {
    return { color: 'var(--warning-color)', bg: 'rgba(245,158,11,0.10)', Icon: AlertTriangle };
  }
  return { color: 'var(--success-color)', bg: 'rgba(16,185,129,0.10)', Icon: ShieldCheck };
}

export default function HITLApprovalModal({ sessionId, request, onClose }: HITLApprovalModalProps) {
  const { t } = useI18n();
  const [pending, setPending] = useState<Decision | null>(null);
  const [error, setError] = useState<string | null>(null);
  const approveBtnRef = useRef<HTMLButtonElement>(null);

  const sty = severityStyle(request.severity);
  const Icon = sty.Icon;

  const handleDecision = useCallback(
    async (decision: Decision) => {
      if (pending) return;
      setPending(decision);
      setError(null);
      try {
        await agentApi.hitlResume(sessionId, { token: request.token, decision });
        // Don't close immediately — wait for the WS `hitl_decision`
        // event to clear the pending request. But if the executor is
        // slow, give the modal an escape hatch by closing after the
        // call returns. The next pendingHitl change in the parent
        // will replace this anyway.
        onClose();
      } catch (err: unknown) {
        const msg = err instanceof Error ? err.message : String(err);
        setError(msg);
        setPending(null);
      }
    },
    [pending, sessionId, request.token, onClose],
  );

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape' && !pending) onClose();
    };
    document.addEventListener('keydown', onKey);
    return () => document.removeEventListener('keydown', onKey);
  }, [onClose, pending]);

  useEffect(() => {
    approveBtnRef.current?.focus();
  }, []);

  // Render the executor-supplied data payload as a JSON block so the
  // operator can see exactly what triggered the request (tool name,
  // args, guard chain hits, …). Keep it small — anything large should
  // already have been summarised by the reviewer.
  const dataJson = (() => {
    try {
      return JSON.stringify(request.data, null, 2);
    } catch {
      return String(request.data);
    }
  })();

  // Quick label hints from the data payload — these are best-effort.
  // The reviewer is free to put whatever it wants on `data`, so we
  // only display fields we know about.
  const toolName = typeof request.data.tool_name === 'string' ? request.data.tool_name : null;
  const reviewer = typeof request.data.reviewer === 'string' ? request.data.reviewer : null;

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center bg-black/60 backdrop-blur-sm"
      onClick={pending ? undefined : onClose}
    >
      <div
        className="bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-lg w-full max-w-[520px] max-h-[85vh] flex flex-col shadow-[var(--shadow-lg)]"
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div className="flex justify-between items-center py-4 px-6 border-b border-[var(--border-color)]">
          <div className="flex items-center gap-2 min-w-0">
            <span
              className="inline-flex items-center justify-center w-7 h-7 rounded-md"
              style={{ background: sty.bg, color: sty.color }}
            >
              <Icon size={15} />
            </span>
            <h3 className="text-[1rem] font-semibold text-[var(--text-primary)] truncate">
              {t('hitl.modalTitle')}
            </h3>
            <span
              className="ml-1 px-1.5 py-[1px] rounded text-[0.5625rem] font-bold uppercase tracking-wider"
              style={{ color: sty.color, background: sty.bg }}
            >
              {request.severity}
            </span>
          </div>
          <button
            disabled={pending !== null}
            className="flex items-center justify-center w-8 h-8 rounded-[var(--border-radius)] bg-transparent border-none text-[var(--text-muted)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)] cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed"
            onClick={onClose}
            title="Close"
          >
            <X size={16} />
          </button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-6 py-5 flex flex-col gap-4">
          {/* Reason */}
          <div>
            <div className="text-[0.6875rem] font-semibold text-[var(--text-muted)] uppercase tracking-wider mb-1">
              {t('hitl.reasonLabel')}
            </div>
            <div className="text-[0.8125rem] text-[var(--text-secondary)] whitespace-pre-wrap break-words">
              {request.reason || '(no reason provided)'}
            </div>
          </div>

          {/* Quick chips */}
          {(toolName || reviewer) && (
            <div className="flex items-center gap-2 flex-wrap">
              {toolName && (
                <span className="inline-flex items-center gap-1 px-2 py-[2px] rounded-full bg-[var(--bg-tertiary)] text-[0.6875rem] text-[var(--text-secondary)] border border-[var(--border-color)]">
                  tool: <span className="font-mono">{toolName}</span>
                </span>
              )}
              {reviewer && (
                <span className="inline-flex items-center gap-1 px-2 py-[2px] rounded-full bg-[var(--bg-tertiary)] text-[0.6875rem] text-[var(--text-secondary)] border border-[var(--border-color)]">
                  reviewer: <span className="font-mono">{reviewer}</span>
                </span>
              )}
              <span className="inline-flex items-center gap-1 px-2 py-[2px] rounded-full bg-[var(--bg-tertiary)] text-[0.6875rem] text-[var(--text-muted)] border border-[var(--border-color)]">
                token: <span className="font-mono">{request.token.slice(0, 8)}…</span>
              </span>
            </div>
          )}

          {/* Raw payload */}
          <div>
            <div className="text-[0.6875rem] font-semibold text-[var(--text-muted)] uppercase tracking-wider mb-1">
              {t('hitl.payloadLabel')}
            </div>
            <pre className="text-[0.6875rem] text-[var(--text-primary)] bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-md px-3 py-2 max-h-[220px] overflow-auto leading-relaxed font-mono whitespace-pre-wrap break-words m-0">
              {dataJson}
            </pre>
          </div>

          {error && (
            <div className="text-[0.75rem] text-[var(--danger-color)] bg-[rgba(239,68,68,0.08)] border border-[rgba(239,68,68,0.2)] rounded-md px-3 py-2">
              {error}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex justify-between items-center gap-3 py-4 px-6 border-t border-[var(--border-color)]">
          <button
            disabled={pending !== null}
            className="py-2 px-3 bg-transparent hover:bg-[var(--bg-hover)] text-[var(--text-muted)] text-[0.75rem] font-medium rounded-[var(--border-radius)] cursor-pointer transition-all duration-150 border border-[var(--border-color)] disabled:opacity-50 disabled:cursor-not-allowed"
            onClick={() => handleDecision('cancel')}
          >
            {pending === 'cancel' ? t('hitl.cancellingBtn') : t('hitl.cancelBtn')}
          </button>
          <div className="flex gap-2">
            <button
              disabled={pending !== null}
              className="py-2 px-4 bg-transparent hover:bg-[rgba(239,68,68,0.10)] text-[var(--danger-color)] text-[0.8125rem] font-medium rounded-[var(--border-radius)] cursor-pointer transition-all duration-150 border border-[rgba(239,68,68,0.35)] disabled:opacity-50 disabled:cursor-not-allowed"
              onClick={() => handleDecision('reject')}
            >
              {pending === 'reject' ? t('hitl.rejectingBtn') : t('hitl.rejectBtn')}
            </button>
            <button
              ref={approveBtnRef}
              disabled={pending !== null}
              className="py-2 px-4 bg-[var(--success-color)] hover:brightness-110 text-white text-[0.8125rem] font-medium rounded-[var(--border-radius)] cursor-pointer transition-all duration-150 border-none disabled:opacity-50 disabled:cursor-not-allowed"
              onClick={() => handleDecision('approve')}
            >
              {pending === 'approve' ? t('hitl.approvingBtn') : t('hitl.approveBtn')}
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}
