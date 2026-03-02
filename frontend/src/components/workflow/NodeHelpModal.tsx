'use client';

/**
 * NodeHelpModal — displays detailed usage instructions for a workflow node.
 *
 * Shown when the user clicks the "?" button in the PropertyPanel header.
 * Renders multi-section help content from the backend i18n data with
 * light markdown-like formatting.
 */

import React, { useCallback, useEffect, useRef } from 'react';
import type { WfNodeHelp } from '@/types/workflow';
import { NodeIcon } from './icons';

/* ---------- Lightweight Markdown Renderer ---------- */

function renderContent(text: string): React.ReactElement[] {
  const elements: React.ReactElement[] = [];
  const lines = text.split('\n');
  let inCodeBlock = false;
  let codeLines: string[] = [];
  let key = 0;

  const flush = () => {
    if (codeLines.length > 0) {
      elements.push(
        <pre
          key={key++}
          className="
            my-2 px-3 py-2 text-[11px] leading-relaxed
            bg-[#0d0d0f] border border-[var(--border-color)]
            rounded-md font-mono text-[#a5d6ff] overflow-x-auto
          "
        >
          {codeLines.join('\n')}
        </pre>,
      );
      codeLines = [];
    }
  };

  for (const line of lines) {
    if (line.trim().startsWith('```')) {
      if (inCodeBlock) {
        flush();
        inCodeBlock = false;
      } else {
        inCodeBlock = true;
      }
      continue;
    }

    if (inCodeBlock) {
      codeLines.push(line);
      continue;
    }

    // Empty line → spacer
    if (line.trim() === '') {
      elements.push(<div key={key++} className="h-2" />);
      continue;
    }

    // Bullet list item
    if (/^\s*[-•]\s/.test(line)) {
      const content = line.replace(/^\s*[-•]\s/, '');
      elements.push(
        <div key={key++} className="flex gap-1.5 text-[11px] leading-relaxed pl-1">
          <span className="text-[var(--text-muted)] shrink-0">•</span>
          <span>{renderInline(content)}</span>
        </div>,
      );
      continue;
    }

    // Numbered list item
    if (/^\s*\d+\.\s/.test(line)) {
      const match = line.match(/^\s*(\d+)\.\s(.*)$/);
      if (match) {
        elements.push(
          <div key={key++} className="flex gap-1.5 text-[11px] leading-relaxed pl-1">
            <span className="text-[var(--primary-color)] font-medium shrink-0 w-4 text-right">{match[1]}.</span>
            <span>{renderInline(match[2])}</span>
          </div>,
        );
        continue;
      }
    }

    // Regular paragraph
    elements.push(
      <p key={key++} className="text-[11px] leading-relaxed">
        {renderInline(line)}
      </p>,
    );
  }

  flush();
  return elements;
}

/** Render inline formatting: **bold**, `code` */
function renderInline(text: string): (string | React.ReactElement)[] {
  const parts: (string | React.ReactElement)[] = [];
  // Match **bold** and `code` inline
  const regex = /(\*\*(.+?)\*\*|`([^`]+)`)/g;
  let lastIndex = 0;
  let match: RegExpExecArray | null;
  let key = 0;

  while ((match = regex.exec(text)) !== null) {
    if (match.index > lastIndex) {
      parts.push(text.slice(lastIndex, match.index));
    }
    if (match[2]) {
      // Bold
      parts.push(
        <strong key={key++} className="font-semibold text-[var(--text-primary)]">
          {match[2]}
        </strong>,
      );
    } else if (match[3]) {
      // Inline code
      parts.push(
        <code
          key={key++}
          className="px-1 py-0.5 text-[10px] bg-[#0d0d0f] border border-[var(--border-color)] rounded text-[#c3e88d] font-mono"
        >
          {match[3]}
        </code>,
      );
    }
    lastIndex = match.index + match[0].length;
  }

  if (lastIndex < text.length) {
    parts.push(text.slice(lastIndex));
  }

  return parts.length > 0 ? parts : [text];
}

/* ---------- Modal Component ---------- */

interface NodeHelpModalProps {
  help: WfNodeHelp;
  icon?: string;
  color?: string;
  onClose: () => void;
}

export default function NodeHelpModal({ help, icon, color, onClose }: NodeHelpModalProps) {
  const backdropRef = useRef<HTMLDivElement>(null);

  // Close on Escape
  useEffect(() => {
    const handler = (e: KeyboardEvent) => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', handler);
    return () => window.removeEventListener('keydown', handler);
  }, [onClose]);

  // Close on backdrop click
  const handleBackdropClick = useCallback(
    (e: React.MouseEvent) => {
      if (e.target === backdropRef.current) onClose();
    },
    [onClose],
  );

  return (
    <div
      ref={backdropRef}
      onClick={handleBackdropClick}
      className="
        fixed inset-0 z-[9999] flex items-center justify-center
        bg-black/60 backdrop-blur-sm
        animate-in fade-in duration-150
      "
    >
      <div
        className="
          relative w-full max-w-[560px] max-h-[80vh]
          bg-[var(--bg-secondary)] border border-[var(--border-color)]
          rounded-xl shadow-2xl flex flex-col overflow-hidden
        "
        onClick={(e) => e.stopPropagation()}
      >
        {/* ── Header ── */}
        <div className="flex items-center gap-2.5 px-5 py-3.5 border-b border-[var(--border-color)] bg-[var(--bg-primary)]">
          {icon && (
            <span
              className="flex items-center justify-center w-8 h-8 rounded-lg"
              style={{ background: `${color || '#3b82f6'}20` }}
            >
              <NodeIcon name={icon} size={16} style={{ color: color || '#3b82f6' }} />
            </span>
          )}
          <div className="flex-1 min-w-0">
            <h2 className="text-[14px] font-bold text-[var(--text-primary)] truncate">
              {help.title}
            </h2>
            <p className="text-[11px] text-[var(--text-muted)] mt-0.5 line-clamp-2">
              {help.summary}
            </p>
          </div>
          <button
            onClick={onClose}
            className="
              flex items-center justify-center w-7 h-7 rounded-md
              text-[var(--text-muted)] hover:text-[var(--text-primary)]
              hover:bg-[var(--bg-tertiary)] transition-colors shrink-0
            "
            aria-label="Close"
          >
            <svg className="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke="currentColor" strokeWidth={2}>
              <path strokeLinecap="round" strokeLinejoin="round" d="M6 18L18 6M6 6l12 12" />
            </svg>
          </button>
        </div>

        {/* ── Content ── */}
        <div className="flex-1 overflow-y-auto px-5 py-4 space-y-5">
          {help.sections.map((section, idx) => (
            <div key={idx}>
              <h3
                className="
                  text-[12px] font-bold text-[var(--text-primary)]
                  mb-2 pb-1.5 border-b border-[var(--border-color)]
                  flex items-center gap-1.5
                "
              >
                <span
                  className="w-1.5 h-1.5 rounded-full shrink-0"
                  style={{ background: color || '#3b82f6' }}
                />
                {section.title}
              </h3>
              <div className="text-[var(--text-secondary)] space-y-0.5">
                {renderContent(section.content)}
              </div>
            </div>
          ))}
        </div>

        {/* ── Footer ── */}
        <div className="px-5 py-3 border-t border-[var(--border-color)] flex justify-end">
          <button
            onClick={onClose}
            className="
              px-4 py-1.5 text-[11px] font-medium rounded-md
              bg-[var(--primary-color)] text-white
              hover:opacity-90 transition-opacity
            "
          >
            OK
          </button>
        </div>
      </div>
    </div>
  );
}
