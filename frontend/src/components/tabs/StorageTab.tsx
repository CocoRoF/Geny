'use client';

import { useState, useEffect, useCallback } from 'react';
import { useAppStore } from '@/store/useAppStore';
import { agentApi } from '@/lib/api';
import { twMerge } from 'tailwind-merge';
import type { StorageFile } from '@/types';

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

function getFileIcon(name: string): string {
  const ext = name.split('.').pop()?.toLowerCase();
  const map: Record<string, string> = {
    json: '📄', md: '📝', txt: '📄', py: '🐍', js: '📜', ts: '📜',
    html: '🌐', css: '🎨', log: '📋', yaml: '⚙️', yml: '⚙️',
  };
  return map[ext || ''] || '📄';
}

function FolderNode({ name, node, onSelect, activePath }: {
  name: string; node: TreeNode; onSelect: (path: string) => void; activePath: string;
}) {
  const [open, setOpen] = useState(true);
  return (
    <div className="mb-1">
      <div className="flex items-center gap-1.5 py-1.5 px-2 cursor-pointer text-[13px] font-medium text-[var(--text-primary)] rounded hover:bg-[var(--bg-hover)]"
           onClick={() => setOpen(!open)}>
        <span className={`text-[10px] transition-transform ${open ? '' : '-rotate-90'}`}>▼</span>
        <span>📁</span>
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
          <span className="text-[14px]">{getFileIcon(f.name)}</span>
          <span className="flex-1 truncate">{f.name}</span>
          <span className="text-[var(--text-muted)] text-[11px]">{formatFileSize(f.size)}</span>
        </div>
      ))}
    </div>
  );
}

export default function StorageTab() {
  const { selectedSessionId } = useAppStore();
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
      setPreviewContent(res.content || '(empty file)');
    } catch (e: any) {
      setPreviewContent(`Error loading file: ${e.message}`);
    } finally {
      setLoading(false);
    }
  };

  if (!selectedSessionId) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="flex flex-col items-center justify-center py-12 px-4">
          <h3 className="text-[1rem] font-medium text-[var(--text-secondary)] mb-2">Select a Session</h3>
          <p className="text-[0.8125rem] text-[var(--text-muted)]">Choose a session from the list to view its storage</p>
        </div>
      </div>
    );
  }

  const tree = buildFileTree(files);

  return (
    <div className="flex flex-col flex-1 p-6 gap-5 min-h-0 overflow-hidden">
      {/* Header */}
      <div className="flex justify-between items-center pb-3 border-b border-[var(--border-color)] shrink-0">
        <h3 className="text-[16px] font-semibold text-[var(--text-primary)]">Session Storage</h3>
        <button className={cn("py-2 px-4 bg-transparent hover:bg-[var(--bg-hover)] text-[var(--text-secondary)] text-[0.8125rem] font-medium rounded-[var(--border-radius)] cursor-pointer transition-all duration-150 border border-[var(--border-color)]", "!py-1.5 !px-3 text-[0.75rem]")} onClick={fetchFiles}>↻ Refresh</button>
      </div>

      {/* Content */}
      <div className="flex gap-4 flex-1 min-h-0">
        {/* File Tree */}
        <div className="w-[280px] shrink-0 bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-[var(--border-radius)] p-3 overflow-y-auto">
          {files.length === 0 ? (
            <p className="text-[var(--text-muted)] text-[13px] text-center py-6 px-3">Storage is empty</p>
          ) : (
            <TreeView node={tree} onSelect={loadFile} activePath={activePath} />
          )}
        </div>

        {/* Preview */}
        <div className="flex-1 bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-[var(--border-radius)] flex flex-col min-w-0">
          <div className="py-2.5 px-3.5 bg-[var(--bg-tertiary)] border-b border-[var(--border-color)]" style={{ borderRadius: 'var(--border-radius) var(--border-radius) 0 0' }}>
            <span className="text-[13px] font-medium text-[var(--text-secondary)]">{activePath || 'No file selected'}</span>
          </div>
          <pre className="flex-1 p-3.5 m-0 overflow-auto text-[12px] leading-[1.6] text-[var(--text-primary)] whitespace-pre-wrap break-words"
               style={{ fontFamily: "'JetBrains Mono', 'Fira Code', monospace" }}>
            {loading ? 'Loading...' : previewContent || 'Select a file to preview'}
          </pre>
        </div>
      </div>
    </div>
  );
}
