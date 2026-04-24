'use client';

import { useState, useRef, useEffect, useCallback } from 'react';
import { useMessengerStore } from '@/store/useMessengerStore';
import { useI18n } from '@/lib/i18n';
import { chatApi } from '@/lib/api';
import { resizeImageIfNeeded, isImageFile } from '@/lib/imageAttachments';
import type { ChatAttachment } from '@/types';
import { Send, Loader2, Paperclip, X as XIcon } from 'lucide-react';

const MAX_ATTACHMENTS = 8;
const MAX_FILE_BYTES = 10 * 1024 * 1024;

export default function MessageInput() {
  const { isSending, sendMessage, getActiveRoom } = useMessengerStore();
  const { t } = useI18n();
  const [input, setInput] = useState('');
  const [pendingAttachments, setPendingAttachments] = useState<ChatAttachment[]>([]);
  const [uploadingCount, setUploadingCount] = useState(0);
  const [attachmentError, setAttachmentError] = useState<string | null>(null);
  const [dragActive, setDragActive] = useState(false);
  const textareaRef = useRef<HTMLTextAreaElement>(null);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const room = getActiveRoom();

  // Auto-focus on mount / room switch
  useEffect(() => {
    textareaRef.current?.focus();
  }, [room?.id]);

  // Auto-resize textarea
  useEffect(() => {
    const el = textareaRef.current;
    if (!el) return;
    el.style.height = 'auto';
    el.style.height = `${Math.min(el.scrollHeight, 160)}px`;
  }, [input]);

  // ── Attachment helpers (ported from VTuberChatPanel) ─────────────
  const addFiles = useCallback(async (files: File[]) => {
    if (!files.length) return;
    setAttachmentError(null);

    const remaining = MAX_ATTACHMENTS - pendingAttachments.length;
    const accepted = files.slice(0, Math.max(0, remaining));
    if (accepted.length < files.length) {
      setAttachmentError(
        t('messenger.attachmentLimit')
        ?? `Up to ${MAX_ATTACHMENTS} attachments per message.`
      );
    }
    if (accepted.length === 0) return;

    setUploadingCount((c) => c + accepted.length);
    try {
      const prepared = await Promise.all(
        accepted.map(async (f) => {
          if (f.size > MAX_FILE_BYTES && !isImageFile(f)) {
            throw new Error(`${f.name}: file too large (>10 MiB)`);
          }
          return isImageFile(f) ? resizeImageIfNeeded(f) : f;
        })
      );
      for (const f of prepared) {
        if (f.size > MAX_FILE_BYTES) {
          throw new Error(`${f.name}: still too large after resize`);
        }
      }
      const uploaded = await chatApi.uploadAttachments(prepared);
      setPendingAttachments((prev) => [...prev, ...uploaded].slice(0, MAX_ATTACHMENTS));
    } catch (e) {
      setAttachmentError(e instanceof Error ? e.message : String(e));
    } finally {
      setUploadingCount((c) => Math.max(0, c - accepted.length));
    }
  }, [pendingAttachments.length, t]);

  const removeAttachment = useCallback((idx: number) => {
    setPendingAttachments((prev) => prev.filter((_, i) => i !== idx));
  }, []);

  const handleFileInputChange = useCallback((e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files ?? []);
    if (files.length) void addFiles(files);
    if (e.target) e.target.value = '';
  }, [addFiles]);

  const handlePaste = useCallback((e: React.ClipboardEvent<HTMLTextAreaElement>) => {
    const items = e.clipboardData?.items;
    if (!items) return;
    const files: File[] = [];
    for (let i = 0; i < items.length; i++) {
      const it = items[i];
      if (it.kind === 'file') {
        const f = it.getAsFile();
        if (f) files.push(f);
      }
    }
    if (files.length) {
      e.preventDefault();
      void addFiles(files);
    }
  }, [addFiles]);

  const handleDragOver = useCallback((e: React.DragEvent) => {
    if (!e.dataTransfer.types.includes('Files')) return;
    e.preventDefault();
    setDragActive(true);
  }, []);
  const handleDragLeave = useCallback((e: React.DragEvent) => {
    if (e.currentTarget.contains(e.relatedTarget as Node)) return;
    setDragActive(false);
  }, []);
  const handleDrop = useCallback((e: React.DragEvent) => {
    e.preventDefault();
    setDragActive(false);
    const files = Array.from(e.dataTransfer?.files ?? []);
    if (files.length) void addFiles(files);
  }, [addFiles]);

  const handleSend = useCallback(() => {
    if (isSending || !room || uploadingCount > 0) return;
    const text = input.trim();
    if (!text && pendingAttachments.length === 0) return;

    sendMessage(text, pendingAttachments.length > 0 ? pendingAttachments : undefined);
    setInput('');
    setPendingAttachments([]);
    setAttachmentError(null);

    if (textareaRef.current) {
      textareaRef.current.style.height = 'auto';
    }
  }, [input, isSending, room, uploadingCount, pendingAttachments, sendMessage]);

  const canSend = (input.trim().length > 0 || pendingAttachments.length > 0) && !isSending && uploadingCount === 0;

  return (
    <div
      className="shrink-0 bg-[var(--bg-secondary)] relative"
      onDragOver={handleDragOver}
      onDragLeave={handleDragLeave}
      onDrop={handleDrop}
    >
      {dragActive && (
        <div className="absolute inset-0 z-10 flex items-center justify-center rounded-md bg-[var(--primary-color)]/10 border-2 border-dashed border-[var(--primary-color)] pointer-events-none">
          <span className="text-[0.8125rem] text-[var(--primary-color)] font-medium">
            {t('messenger.dropHere') ?? 'Drop files here'}
          </span>
        </div>
      )}

      <div className="h-px bg-[var(--border-color)]" />

      {/* Pending attachment chips */}
      {(pendingAttachments.length > 0 || uploadingCount > 0 || attachmentError) && (
        <div className="px-5 md:px-6 pt-2 flex flex-wrap gap-1.5">
          {pendingAttachments.map((att, idx) => (
            <div
              key={`${att.attachment_id ?? att.url ?? idx}`}
              className="relative group flex items-center gap-1.5 px-1.5 py-1 bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-md max-w-[160px]"
            >
              {att.kind === 'image' && att.url ? (
                // eslint-disable-next-line @next/next/no-img-element
                <img
                  src={att.url}
                  alt={att.name ?? 'image'}
                  className="w-8 h-8 object-cover rounded"
                />
              ) : (
                <div className="w-8 h-8 flex items-center justify-center rounded bg-[var(--bg-primary)]">
                  <Paperclip size={14} className="text-[var(--text-muted)]" />
                </div>
              )}
              <span className="text-[0.6875rem] text-[var(--text-secondary)] truncate">
                {att.name ?? att.kind}
              </span>
              <button
                type="button"
                className="ml-0.5 text-[var(--text-muted)] hover:text-red-400 cursor-pointer bg-transparent border-none p-0"
                onClick={() => removeAttachment(idx)}
                aria-label="Remove attachment"
              >
                <XIcon size={12} />
              </button>
            </div>
          ))}
          {uploadingCount > 0 && (
            <div className="flex items-center gap-1.5 px-2 py-1 bg-[var(--bg-tertiary)] border border-[var(--border-color)] rounded-md text-[0.6875rem] text-[var(--text-muted)]">
              <span className="animate-pulse">{t('messenger.uploading') ?? 'Uploading…'}</span>
            </div>
          )}
          {attachmentError && (
            <div className="text-[0.6875rem] text-red-400 self-center">{attachmentError}</div>
          )}
        </div>
      )}

      <div className="flex items-center gap-3 px-5 md:px-6 py-3">
        <input
          ref={fileInputRef}
          type="file"
          accept="image/*"
          multiple
          className="hidden"
          onChange={handleFileInputChange}
        />
        <button
          type="button"
          className="messenger-input shrink-0 w-8 h-8 rounded-lg flex items-center justify-center cursor-pointer transition-all duration-150 border-none bg-transparent text-[var(--text-muted)] hover:text-[var(--text-primary)] disabled:opacity-30 disabled:cursor-not-allowed"
          onClick={() => fileInputRef.current?.click()}
          disabled={isSending || pendingAttachments.length >= MAX_ATTACHMENTS}
          title={t('messenger.attachFile') ?? 'Attach image'}
          aria-label="Attach image"
        >
          <Paperclip size={16} />
        </button>
        <textarea
          ref={textareaRef}
          className="messenger-input flex-1 bg-transparent text-[var(--text-primary)] text-[0.8125rem] font-[inherit] resize-none min-h-[24px] max-h-[160px] leading-relaxed placeholder:text-[var(--text-muted)] border-none py-0.5"
          placeholder={t('messenger.inputPlaceholder')}
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => {
            if (e.key === 'Enter' && !e.shiftKey) {
              e.preventDefault();
              handleSend();
            }
          }}
          onPaste={handlePaste}
          rows={1}
          disabled={isSending}
        />
        <button
          className={`messenger-input shrink-0 w-8 h-8 rounded-lg flex items-center justify-center cursor-pointer transition-all duration-150 border-none disabled:cursor-not-allowed ${
            canSend
              ? 'bg-[var(--primary-color)] hover:bg-[var(--primary-hover)] text-white shadow-sm'
              : 'bg-transparent text-[var(--text-muted)] opacity-30'
          }`}
          disabled={!canSend}
          onClick={handleSend}
        >
          {isSending ? (
            <Loader2 size={15} className="animate-spin" />
          ) : (
            <Send size={15} />
          )}
        </button>
      </div>
      <div className="px-5 md:px-6 pb-2 -mt-1">
        <span className="text-[0.6125rem] text-[var(--text-muted)] opacity-40">
          Enter {t('messenger.sendHint')} · Shift+Enter {t('messenger.newlineHint')}
        </span>
      </div>
    </div>
  );
}
