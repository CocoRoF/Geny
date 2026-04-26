'use client';

import { useState, useEffect, useCallback, useRef } from 'react';
import { sharedFolderApi, type SharedFileItem, type SharedFolderInfoResponse } from '@/lib/api';
import { twMerge } from 'tailwind-merge';
import { useI18n } from '@/lib/i18n';
import {
  ChevronDown,
  ChevronRight,
  FolderOpen,
  Download,
  RefreshCw,
  FileJson,
  FileText,
  FileCode,
  Globe,
  Palette,
  ScrollText,
  Settings,
  File,
  Upload,
  Plus,
  Trash2,
  FolderSync,
  Info,
} from 'lucide-react';
import { TabShell, ActionButton } from '@/components/layout';

function cn(...classes: (string | boolean | undefined | null)[]) {
  return twMerge(classes.filter(Boolean).join(' '));
}

/* ────────────────── File tree helpers ────────────────── */

interface TreeNode {
  children: Record<string, TreeNode>;
  files: { name: string; path: string; size: number }[];
}

function buildFileTree(files: SharedFileItem[]): TreeNode {
  const tree: TreeNode = { children: {}, files: [] };
  for (const file of files) {
    const parts = file.path.split('/').filter(Boolean);
    let current = tree;
    for (let i = 0; i < parts.length - 1; i++) {
      if (!current.children[parts[i]]) current.children[parts[i]] = { children: {}, files: [] };
      current = current.children[parts[i]];
    }
    current.files.push({ name: parts[parts.length - 1], path: file.path, size: file.size || 0 });
  }
  return tree;
}

function formatFileSize(bytes: number): string {
  if (bytes === 0) return '0 B';
  const k = 1024;
  const sizes = ['B', 'KB', 'MB', 'GB'];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + ' ' + sizes[i];
}

function getFileIcon(name: string): React.ReactNode {
  const ext = name.split('.').pop()?.toLowerCase();
  const map: Record<string, React.ReactNode> = {
    json: <FileJson size={14} className="text-[#f59e0b]" />,
    md: <FileText size={14} className="text-[#60a5fa]" />,
    txt: <FileText size={14} className="text-[var(--text-muted)]" />,
    py: <FileCode size={14} className="text-[#22c55e]" />,
    js: <FileCode size={14} className="text-[#facc15]" />,
    ts: <FileCode size={14} className="text-[#3b82f6]" />,
    html: <Globe size={14} className="text-[#f97316]" />,
    css: <Palette size={14} className="text-[#a855f7]" />,
    log: <ScrollText size={14} className="text-[var(--text-muted)]" />,
    yaml: <Settings size={14} className="text-[#6b7280]" />,
    yml: <Settings size={14} className="text-[#6b7280]" />,
  };
  return map[ext || ''] || <File size={14} className="text-[var(--text-muted)]" />;
}

/* ────────────────── Tree components ────────────────── */

function FolderNode({
  name,
  node,
  onSelect,
  activePath,
}: {
  name: string;
  node: TreeNode;
  onSelect: (path: string) => void;
  activePath: string;
}) {
  const [open, setOpen] = useState(true);
  return (
    <div className="mb-1">
      <div
        className="flex items-center gap-1.5 py-1.5 px-2 cursor-pointer text-[13px] font-medium text-[var(--text-primary)] rounded hover:bg-[var(--bg-hover)]"
        onClick={() => setOpen(!open)}
      >
        {open ? <ChevronDown size={12} /> : <ChevronRight size={12} />}
        <FolderOpen size={14} className="text-[#f59e0b]" />
        <span>{name}</span>
      </div>
      {open && (
        <div className="pl-4 ml-2.5" style={{ borderLeft: '1px solid var(--border-color)' }}>
          <TreeView node={node} onSelect={onSelect} activePath={activePath} />
        </div>
      )}
    </div>
  );
}

function TreeView({
  node,
  onSelect,
  activePath,
}: {
  node: TreeNode;
  onSelect: (path: string) => void;
  activePath: string;
}) {
  return (
    <div>
      {Object.entries(node.children).map(([name, child]) => (
        <FolderNode key={name} name={name} node={child} onSelect={onSelect} activePath={activePath} />
      ))}
      {node.files.map((f) => (
        <div
          key={f.path}
          className={cn(
            'flex items-center gap-2 py-1.5 px-2.5 cursor-pointer rounded text-[13px] transition-colors hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]',
            activePath === f.path
              ? 'bg-[rgba(59,130,246,0.1)] text-[var(--primary-color)]'
              : 'text-[var(--text-secondary)]',
          )}
          onClick={() => onSelect(f.path)}
        >
          <span className="text-[14px] flex items-center">{getFileIcon(f.name)}</span>
          <span className="flex-1 truncate">{f.name}</span>
          <span className="text-[var(--text-muted)] text-[11px]">{formatFileSize(f.size)}</span>
        </div>
      ))}
    </div>
  );
}

/* ────────────────── Create File Modal ────────────────── */

function CreateFileModal({
  onClose,
  onCreated,
}: {
  onClose: () => void;
  onCreated: () => void;
}) {
  const { t } = useI18n();
  const [filePath, setFilePath] = useState('');
  const [content, setContent] = useState('');
  const [saving, setSaving] = useState(false);

  const handleCreate = async () => {
    if (!filePath.trim()) return;
    setSaving(true);
    try {
      await sharedFolderApi.writeFile(filePath.trim(), content, false);
      onCreated();
      onClose();
    } catch (e: any) {
      alert(e.message || t('sharedFolderTab.writeError'));
    } finally {
      setSaving(false);
    }
  };

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40" onClick={onClose}>
      <div
        className="bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-xl shadow-xl w-[520px] max-w-[90vw] p-6"
        onClick={(e) => e.stopPropagation()}
      >
        <h3 className="text-[15px] font-semibold text-[var(--text-primary)] mb-4">
          {t('sharedFolderTab.createFileTitle')}
        </h3>
        <input
          className="w-full mb-3 px-3 py-2 text-[13px] bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-lg text-[var(--text-primary)] outline-none focus:border-[var(--primary-color)]"
          placeholder={t('sharedFolderTab.createFilePlaceholder')}
          value={filePath}
          onChange={(e) => setFilePath(e.target.value)}
          autoFocus
        />
        <textarea
          className="w-full mb-4 px-3 py-2 text-[13px] bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-lg text-[var(--text-primary)] outline-none focus:border-[var(--primary-color)] resize-y min-h-[120px]"
          placeholder={t('sharedFolderTab.createFileContent')}
          value={content}
          onChange={(e) => setContent(e.target.value)}
          rows={6}
        />
        <div className="flex justify-end gap-2">
          <button
            className="py-1.5 px-4 text-[13px] font-medium rounded-lg border border-[var(--border-color)] bg-transparent text-[var(--text-secondary)] hover:bg-[var(--bg-hover)]"
            onClick={onClose}
          >
            Cancel
          </button>
          <button
            className="py-1.5 px-4 text-[13px] font-medium rounded-lg bg-[var(--primary-color)] text-white hover:opacity-90 disabled:opacity-50"
            onClick={handleCreate}
            disabled={saving || !filePath.trim()}
          >
            {saving ? '...' : 'Create'}
          </button>
        </div>
      </div>
    </div>
  );
}

/* ────────────────── Main Component ────────────────── */

export default function SharedFolderTab() {
  const { t } = useI18n();
  const [files, setFiles] = useState<SharedFileItem[]>([]);
  const [info, setInfo] = useState<SharedFolderInfoResponse | null>(null);
  const [activePath, setActivePath] = useState('');
  const [previewContent, setPreviewContent] = useState('');
  const [loading, setLoading] = useState(false);
  const [downloading, setDownloading] = useState(false);
  const [showCreateModal, setShowCreateModal] = useState(false);
  const fileInputRef = useRef<HTMLInputElement>(null);

  const fetchFiles = useCallback(async () => {
    try {
      const [filesRes, infoRes] = await Promise.all([
        sharedFolderApi.listFiles(),
        sharedFolderApi.getInfo(),
      ]);
      setFiles(filesRes.files || []);
      setInfo(infoRes);
    } catch {
      setFiles([]);
    }
  }, []);

  useEffect(() => {
    fetchFiles();
  }, [fetchFiles]);

  const loadFile = async (path: string) => {
    setActivePath(path);
    setLoading(true);
    try {
      const cleanPath = path.startsWith('/') ? path.substring(1) : path;
      const res = await sharedFolderApi.getFile(cleanPath);
      setPreviewContent(res.content || t('sharedFolderTab.emptyFile'));
    } catch (e: any) {
      setPreviewContent(t('sharedFolderTab.loadError', { message: e.message }));
    } finally {
      setLoading(false);
    }
  };

  const handleDelete = async () => {
    if (!activePath) return;
    const name = activePath.split('/').pop() || activePath;
    if (!confirm(t('sharedFolderTab.deleteConfirm', { name }))) return;
    try {
      await sharedFolderApi.deleteFile(activePath);
      setActivePath('');
      setPreviewContent('');
      fetchFiles();
    } catch {
      alert(t('sharedFolderTab.deleteError'));
    }
  };

  const handleDownload = async () => {
    setDownloading(true);
    try {
      await sharedFolderApi.download();
    } catch {
      alert(t('sharedFolderTab.downloadFolderError'));
    } finally {
      setDownloading(false);
    }
  };

  const handleUpload = async (e: React.ChangeEvent<HTMLInputElement>) => {
    const file = e.target.files?.[0];
    if (!file) return;
    try {
      await sharedFolderApi.uploadFile(file);
      fetchFiles();
    } catch {
      alert(t('sharedFolderTab.uploadError'));
    }
    // Reset to allow re-uploading same file
    if (fileInputRef.current) fileInputRef.current.value = '';
  };

  const tree = buildFileTree(files);

  return (
    <TabShell
      title={t('sharedFolderTab.title')}
      icon={FolderSync}
      subtitle={t('sharedFolderTab.description')}
      actions={
        <>
          <input ref={fileInputRef} type="file" className="hidden" onChange={handleUpload} />
          <ActionButton icon={Upload} onClick={() => fileInputRef.current?.click()}>
            <span className="hidden sm:inline">{t('sharedFolderTab.uploadFile')}</span>
          </ActionButton>
          <ActionButton icon={Plus} onClick={() => setShowCreateModal(true)}>
            <span className="hidden sm:inline">{t('sharedFolderTab.createFile')}</span>
          </ActionButton>
          <ActionButton icon={Download} onClick={handleDownload} disabled={downloading}>
            <span className="hidden sm:inline">{downloading ? t('common.loading') : t('sharedFolderTab.downloadFolder')}</span>
          </ActionButton>
          <ActionButton icon={RefreshCw} onClick={fetchFiles}>
            <span className="hidden sm:inline">{t('sharedFolderTab.refresh')}</span>
          </ActionButton>
        </>
      }
    >
      <div className="flex flex-col h-full p-3 md:p-6 gap-3 md:gap-5 min-h-0 overflow-y-auto md:overflow-hidden">
      {/* Info banner */}
      {info && (
        <div className="flex flex-wrap items-center gap-3 md:gap-6 py-2 px-3 md:px-4 bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-lg text-[11px] md:text-[12px] text-[var(--text-muted)] shrink-0">
          <span className="flex items-center gap-1.5 min-w-0">
            <Info size={12} /> {t('sharedFolderTab.path')}: <code className="text-[var(--text-secondary)] truncate max-w-[150px] md:max-w-none">{info.path}</code>
          </span>
          <span>
            {t('sharedFolderTab.totalFiles')}: <strong className="text-[var(--text-secondary)]">{info.total_files}</strong>
          </span>
          <span>
            {t('sharedFolderTab.totalSize')}: <strong className="text-[var(--text-secondary)]">{formatFileSize(info.total_size)}</strong>
          </span>
        </div>
      )}

      {/* Content */}
      <div className="flex flex-col md:flex-row gap-3 md:gap-4 flex-1 min-h-0">
        {/* File Tree */}
        <div className="md:w-[280px] shrink-0 bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-[var(--border-radius)] p-3 overflow-y-auto max-h-[300px] md:max-h-none">
          {files.length === 0 ? (
            <p className="text-[var(--text-muted)] text-[13px] text-center py-6 px-3">
              {t('sharedFolderTab.empty')}
            </p>
          ) : (
            <TreeView node={tree} onSelect={loadFile} activePath={activePath} />
          )}
        </div>

        {/* Preview */}
        <div className="flex-1 min-h-[300px] md:min-h-0 bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-[var(--border-radius)] flex flex-col min-w-0">
          <div
            className="flex items-center justify-between py-2.5 px-3.5 bg-[var(--bg-tertiary)] border-b border-[var(--border-color)]"
            style={{ borderRadius: 'var(--border-radius) var(--border-radius) 0 0' }}
          >
            <span className="text-[13px] font-medium text-[var(--text-secondary)]">
              {activePath || t('sharedFolderTab.noFile')}
            </span>
            {activePath && (
              <button
                className="text-[12px] text-red-400 hover:text-red-300 flex items-center gap-1 cursor-pointer"
                onClick={handleDelete}
              >
                <Trash2 size={12} /> {t('sharedFolderTab.deleteFile')}
              </button>
            )}
          </div>
          <pre
            className="flex-1 p-3.5 m-0 overflow-auto text-[12px] leading-[1.6] text-[var(--text-primary)] whitespace-pre-wrap break-words"
            style={{ fontFamily: "'JetBrains Mono', 'Fira Code', monospace" }}
          >
            {loading ? t('common.loading') : previewContent || t('sharedFolderTab.selectFile')}
          </pre>
        </div>
      </div>

      {/* Create File Modal */}
      {showCreateModal && (
        <CreateFileModal
          onClose={() => setShowCreateModal(false)}
          onCreated={fetchFiles}
        />
      )}
      </div>
    </TabShell>
  );
}
