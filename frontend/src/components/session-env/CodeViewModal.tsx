'use client';

/**
 * CodeViewModal — full-screen modal that shows the raw manifest JSON
 * for the environment the session is bound to. Read-only: users can
 * copy but not edit here (the Environment Builder owns edits).
 */

import { useEffect, useState } from 'react';
import { Check, Copy, X } from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import type { EnvironmentManifest } from '@/types/environment';

interface CodeViewModalProps {
  manifest: EnvironmentManifest | null;
  envName?: string;
  onClose: () => void;
}

export default function CodeViewModal({
  manifest,
  envName,
  onClose,
}: CodeViewModalProps) {
  const { t } = useI18n();
  const [copied, setCopied] = useState(false);

  const json = (() => {
    try {
      return JSON.stringify(manifest ?? {}, null, 2);
    } catch {
      return String(manifest);
    }
  })();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [onClose]);

  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(json);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // ignore — permissions may block clipboard in some contexts
    }
  };

  return (
    <div
      className="fixed inset-0 z-[60] flex items-center justify-center p-6"
      style={{ background: 'rgba(0,0,0,0.55)' }}
      onClick={onClose}
    >
      <div
        className="pipe-slide-in flex flex-col w-full max-w-[960px] h-[80vh] rounded-xl overflow-hidden"
        style={{
          background: 'var(--pipe-bg-secondary)',
          border: '1px solid var(--pipe-border)',
          boxShadow: '0 20px 80px rgba(0,0,0,0.6)',
        }}
        onClick={(e) => e.stopPropagation()}
      >
        {/* Header */}
        <div
          className="flex items-center justify-between px-5 py-3 shrink-0"
          style={{ borderBottom: '1px solid var(--pipe-border)' }}
        >
          <div className="flex flex-col min-w-0">
            <span
              className="text-[10px] uppercase tracking-[0.2em] font-semibold"
              style={{ color: 'var(--pipe-accent)' }}
            >
              {t('sessionEnvironmentTab.pipeline.code')}
            </span>
            <span
              className="pipe-mono text-[12px] truncate"
              style={{ color: 'var(--pipe-text-secondary)' }}
            >
              {envName ?? 'manifest.json'}
            </span>
          </div>
          <div className="flex items-center gap-2">
            <button
              onClick={handleCopy}
              className="flex items-center gap-1.5 text-[11px] px-3 py-1.5 rounded-md cursor-pointer transition-colors"
              style={{
                background: 'var(--pipe-bg-tertiary)',
                color: copied ? 'var(--pipe-green)' : 'var(--pipe-text-secondary)',
                border: `1px solid ${copied ? 'var(--pipe-green)' : 'var(--pipe-border)'}`,
              }}
            >
              {copied ? <Check size={12} /> : <Copy size={12} />}
              {copied
                ? t('sessionEnvironmentTab.pipeline.copied')
                : t('sessionEnvironmentTab.pipeline.copy')}
            </button>
            <button
              onClick={onClose}
              aria-label={t('common.close')}
              className="w-8 h-8 rounded-md flex items-center justify-center shrink-0 cursor-pointer transition-colors"
              style={{
                color: 'var(--pipe-text-muted)',
                background: 'var(--pipe-bg-tertiary)',
                border: '1px solid var(--pipe-border)',
              }}
            >
              <X size={14} />
            </button>
          </div>
        </div>

        {/* Body */}
        <div
          className="flex-1 min-h-0 overflow-auto"
          style={{ background: 'var(--pipe-bg-primary)' }}
        >
          <pre
            className="pipe-mono text-[12px] leading-[1.55] p-5 whitespace-pre"
            style={{ color: 'var(--pipe-text-primary)' }}
          >
            {json}
          </pre>
        </div>
      </div>
    </div>
  );
}
