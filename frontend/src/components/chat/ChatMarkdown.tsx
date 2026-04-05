'use client';

import { memo } from 'react';
import ReactMarkdown from 'react-markdown';
import remarkGfm from 'remark-gfm';
import type { Components } from 'react-markdown';

/**
 * Lightweight Markdown renderer for chat messages.
 *
 * Unlike the full-page MarkdownRenderer in file-viewer/,
 * this is styled for inline chat bubbles — compact spacing,
 * code blocks with copy button, and GFM support.
 */

// ── Copy button for code blocks ──
function CopyBtn({ text }: { text: string }) {
  const handleCopy = async () => {
    try {
      await navigator.clipboard.writeText(text);
    } catch { /* ignore */ }
  };
  return (
    <button
      onClick={handleCopy}
      className="absolute top-1.5 right-1.5 px-1.5 py-0.5 rounded text-[0.5625rem] text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] transition-all cursor-pointer border-none bg-transparent opacity-0 group-hover/codeblock:opacity-100"
      title="Copy"
    >
      Copy
    </button>
  );
}

// ── Custom components for react-markdown ──
const mdComponents: Components = {
  // Fenced code blocks
  pre({ children }) {
    return (
      <div className="relative group/codeblock my-1.5">
        {children}
      </div>
    );
  },
  code({ className, children }) {
    const match = /language-(\w+)/.exec(className || '');
    const content = String(children).replace(/\n$/, '');
    if (match) {
      return (
        <>
          <div className="flex items-center justify-between px-3 py-1 bg-[var(--bg-secondary)] border-b border-[var(--border-color)] rounded-t-lg">
            <span className="text-[0.5625rem] text-[var(--text-muted)] uppercase tracking-wider">{match[1]}</span>
          </div>
          <pre className="overflow-x-auto px-3 py-2 bg-[var(--bg-primary)] border border-t-0 border-[var(--border-color)] rounded-b-lg text-[0.8125rem] leading-relaxed">
            <code className={className}>{content}</code>
          </pre>
          <CopyBtn text={content} />
        </>
      );
    }
    // Inline code
    return (
      <code className="px-1 py-0.5 rounded bg-[var(--bg-tertiary)] text-[0.8125rem] font-mono text-[var(--text-primary)]">
        {children}
      </code>
    );
  },
  // Tables
  table({ children }) {
    return (
      <div className="overflow-x-auto my-1.5">
        <table className="min-w-full text-[0.8125rem] border-collapse border border-[var(--border-color)]">
          {children}
        </table>
      </div>
    );
  },
  th({ children }) {
    return (
      <th className="px-2 py-1 text-left border border-[var(--border-color)] bg-[var(--bg-secondary)] font-semibold text-[0.75rem]">
        {children}
      </th>
    );
  },
  td({ children }) {
    return (
      <td className="px-2 py-1 border border-[var(--border-color)] text-[0.8125rem]">
        {children}
      </td>
    );
  },
  // Links
  a({ href, children }) {
    return (
      <a
        href={href}
        target="_blank"
        rel="noopener noreferrer"
        className="text-[var(--primary-color)] hover:underline"
      >
        {children}
      </a>
    );
  },
  // Blockquotes
  blockquote({ children }) {
    return (
      <blockquote className="border-l-2 border-[var(--border-color)] pl-3 my-1.5 text-[var(--text-secondary)] italic">
        {children}
      </blockquote>
    );
  },
  // Lists
  ul({ children }) {
    return <ul className="list-disc list-inside my-1 space-y-0.5">{children}</ul>;
  },
  ol({ children }) {
    return <ol className="list-decimal list-inside my-1 space-y-0.5">{children}</ol>;
  },
  // Horizontal rule
  hr() {
    return <hr className="my-2 border-[var(--border-color)]" />;
  },
  // Paragraphs — minimal spacing for chat
  p({ children }) {
    return <p className="my-1 leading-relaxed">{children}</p>;
  },
  // Headings — smaller in chat context
  h1({ children }) {
    return <h1 className="text-base font-bold mt-2 mb-1">{children}</h1>;
  },
  h2({ children }) {
    return <h2 className="text-[0.9375rem] font-bold mt-2 mb-1">{children}</h2>;
  },
  h3({ children }) {
    return <h3 className="text-[0.875rem] font-semibold mt-1.5 mb-0.5">{children}</h3>;
  },
};

export interface ChatMarkdownProps {
  content: string;
  className?: string;
}

function ChatMarkdownInner({ content, className }: ChatMarkdownProps) {
  return (
    <div className={`chat-markdown text-[0.8125rem] text-[var(--text-primary)] leading-relaxed break-words ${className || ''}`}>
      <ReactMarkdown remarkPlugins={[remarkGfm]} components={mdComponents}>
        {content}
      </ReactMarkdown>
    </div>
  );
}

const ChatMarkdown = memo(ChatMarkdownInner);
export default ChatMarkdown;
