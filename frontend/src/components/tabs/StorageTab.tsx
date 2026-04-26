'use client';

import { useState, useEffect, useCallback } from 'react';
import { useAppStore } from '@/store/useAppStore';
import { agentApi } from '@/lib/api';
import { twMerge } from 'tailwind-merge';
import { useI18n } from '@/lib/i18n';
import { ChevronDown, ChevronRight, FolderOpen, Download, RefreshCw, FileJson, FileText, FileCode, Globe, Palette, ScrollText, Settings, File, HardDrive } from 'lucide-react';
import type { StorageFile } from '@/types';
import { FileViewer } from '@/components/file-viewer';
import { TabShell, ActionButton, EmptyState } from '@/components/layout';

function cn(...classes: (string | boolean | undefined | null)[]) {
  return twMerge(classes.filter(Boolean).join(' '));
}

interface TreeNode {
  children: Record<string, TreeNode>;
  files: { name: string; path: string; size: number }[];
}

function buildFileTree(files: StorageFile[]): TreeNode {
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

function FolderNode({ name, node, onSelect, activePath }: {
  name: string; node: TreeNode; onSelect: (path: string) => void; activePath: string;
}) {
  const [open, setOpen] = useState(true);
  return (
    <div className="mb-1">
      <div className="flex items-center gap-1.5 py-1.5 px-2 cursor-pointer text-[13px] font-medium text-[var(--text-primary)] rounded hover:bg-[var(--bg-hover)]"
           onClick={() => setOpen(!open)}>
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

function TreeView({ node, onSelect, activePath }: { node: TreeNode; onSelect: (path: string) => void; activePath: string }) {
  return (
    <div>
      {Object.entries(node.children).map(([name, child]) => (
        <FolderNode key={name} name={name} node={child} onSelect={onSelect} activePath={activePath} />
      ))}
      {node.files.map(f => (
        <div key={f.path}
            className={`flex items-center gap-2 py-1.5 px-2.5 cursor-pointer rounded text-[13px] transition-colors hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)] ${activePath === f.path ? 'bg-[rgba(59,130,246,0.1)] text-[var(--primary-color)]' : 'text-[var(--text-secondary)]'}`}
            onClick={() => onSelect(f.path)}>
          <span className="text-[14px] flex items-center">{getFileIcon(f.name)}</span>
          <span className="flex-1 truncate">{f.name}</span>
          <span className="text-[var(--text-muted)] text-[11px]">{formatFileSize(f.size)}</span>
        </div>
      ))}
    </div>
  );
}

export default function StorageTab() {
  const { selectedSessionId } = useAppStore();
  const { t } = useI18n();
  const [files, setFiles] = useState<StorageFile[]>([]);
  const [activePath, setActivePath] = useState('');
  const [previewContent, setPreviewContent] = useState('');
  const [loading, setLoading] = useState(false);

  const fetchFiles = useCallback(async () => {
    if (!selectedSessionId) return;
    try {
      const res = await agentApi.listStorage(selectedSessionId);
      setFiles(res.files || []);
    } catch { setFiles([]); }
  }, [selectedSessionId]);

  const [downloading, setDownloading] = useState(false);

  const handleDownloadFolder = async () => {
    if (!selectedSessionId) return;
    setDownloading(true);
    try {
      await agentApi.downloadFolder(selectedSessionId);
    } catch {
      alert(t('storageTab.downloadFolderError'));
    } finally {
      setDownloading(false);
    }
  };

  useEffect(() => {
    fetchFiles();
    setActivePath('');
    setPreviewContent('');
  }, [fetchFiles]);

  const loadFile = async (path: string) => {
    if (!selectedSessionId) return;
    setActivePath(path);
    setLoading(true);
    try {
      const cleanPath = path.startsWith('/') ? path.substring(1) : path;
      const res = await agentApi.getStorageFile(selectedSessionId, cleanPath);
      setPreviewContent(res.content || t('storageTab.emptyFile'));
    } catch (e: any) {
      setPreviewContent(t('storageTab.loadError', { message: e.message }));
    } finally {
      setLoading(false);
    }
  };

  if (!selectedSessionId) {
    return (
      <TabShell title={t('storageTab.title')} icon={HardDrive}>
        <EmptyState
          title={t('storageTab.selectSession')}
          description={t('storageTab.selectSessionDesc')}
        />
      </TabShell>
    );
  }

  const tree = buildFileTree(files);

  return (
    <TabShell
      title={t('storageTab.title')}
      icon={HardDrive}
      actions={
        <>
          <ActionButton icon={Download} onClick={handleDownloadFolder} disabled={downloading}>
            {downloading ? t('common.loading') : t('storageTab.downloadFolder')}
          </ActionButton>
          <ActionButton icon={RefreshCw} onClick={fetchFiles}>
            {t('common.refresh')}
          </ActionButton>
        </>
      }
    >
      <div className="h-full p-3 md:p-6">
      <div className="flex flex-col md:flex-row gap-3 md:gap-4 h-full min-h-0">
        {/* File Tree */}
        <div className="md:w-[280px] shrink-0 bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-[var(--border-radius)] p-3 overflow-y-auto max-h-[200px] md:max-h-none">
          {files.length === 0 ? (
            <p className="text-[var(--text-muted)] text-[13px] text-center py-6 px-3">{t('storageTab.empty')}</p>
          ) : (
            <TreeView node={tree} onSelect={loadFile} activePath={activePath} />
          )}
        </div>

        {/* Preview */}
        {activePath && !loading && previewContent ? (
          <FileViewer
            content={previewContent}
            fileName={activePath}
            className="flex-1 min-w-0"
          />
        ) : (
          <div className="flex-1 bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-[var(--border-radius)] flex flex-col min-w-0">
            <div className="py-2.5 px-3.5 bg-[var(--bg-tertiary)] border-b border-[var(--border-color)]" style={{ borderRadius: 'var(--border-radius) var(--border-radius) 0 0' }}>
              <span className="text-[13px] font-medium text-[var(--text-secondary)]">{activePath || t('storageTab.noFile')}</span>
            </div>
            <div className="flex-1 flex items-center justify-center text-[var(--text-muted)] text-[13px] py-12">
              {loading ? (
                <div className="flex items-center gap-2">
                  <div className="w-4 h-4 border-2 border-[var(--primary-color)] border-t-transparent rounded-full animate-spin" />
                  {t('common.loading')}
                </div>
              ) : (
                t('storageTab.selectFile')
              )}
            </div>
          </div>
        )}
      </div>
      </div>
    </TabShell>
  );
}
