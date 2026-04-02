'use client';

import { useObsidianStore } from '@/store/useObsidianStore';
import { memoryApi } from '@/lib/api';
import { X, FileText } from 'lucide-react';

export default function ObsidianTabs() {
  const {
    openFiles,
    selectedFile,
    selectedSessionId,
    files,
    openFile,
    closeFile,
    setFileDetail,
    setViewMode,
  } = useObsidianStore();

  const handleTabClick = async (fn: string) => {
    openFile(fn);
    setViewMode('editor');
    if (selectedSessionId) {
      try {
        const detail = await memoryApi.readFile(selectedSessionId, fn);
        setFileDetail(detail);
      } catch (e) {
        console.error('Failed to read file:', e);
      }
    }
  };

  if (openFiles.length === 0) return null;

  return (
    <div className="obs-tabs-bar">
      {openFiles.map((fn) => {
        const info = files[fn];
        const isActive = fn === selectedFile;
        return (
          <div
            key={fn}
            className={`obs-tab ${isActive ? 'active' : ''}`}
            onClick={() => handleTabClick(fn)}
          >
            <FileText size={12} />
            <span className="obs-tab-name">{info?.title || fn}</span>
            <button
              className="obs-tab-close"
              onClick={(e) => {
                e.stopPropagation();
                closeFile(fn);
              }}
            >
              <X size={11} />
            </button>
          </div>
        );
      })}
    </div>
  );
}
