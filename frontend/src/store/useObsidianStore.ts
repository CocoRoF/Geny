import { create } from 'zustand';
import type {
  MemoryFileInfo,
  MemoryFileDetail,
  MemoryIndex,
  MemoryStats,
  MemoryGraphNode,
  MemoryGraphEdge,
  MemorySearchResult,
  SessionInfo,
} from '@/types';

export type ViewMode = 'editor' | 'graph' | 'search';
export type SidebarPanel = 'files' | 'tags' | 'backlinks';

export interface ObsidianState {
  // Sessions
  sessions: SessionInfo[];
  selectedSessionId: string | null;
  loadingSessions: boolean;

  // Memory Index
  memoryIndex: MemoryIndex | null;
  memoryStats: MemoryStats | null;
  loading: boolean;

  // Files
  files: Record<string, MemoryFileInfo>;
  selectedFile: string | null;
  fileDetail: MemoryFileDetail | null;
  openFiles: string[]; // tabs

  // Graph
  graphNodes: MemoryGraphNode[];
  graphEdges: MemoryGraphEdge[];

  // Search
  searchQuery: string;
  searchResults: MemorySearchResult[];
  searching: boolean;

  // UI
  viewMode: ViewMode;
  sidebarPanel: SidebarPanel;
  sidebarCollapsed: boolean;
  rightPanelOpen: boolean;

  // Actions
  setSessions: (s: SessionInfo[]) => void;
  setSelectedSessionId: (id: string | null) => void;
  setLoadingSessions: (v: boolean) => void;
  setMemoryIndex: (idx: MemoryIndex | null) => void;
  setMemoryStats: (s: MemoryStats | null) => void;
  setLoading: (v: boolean) => void;
  setFiles: (f: Record<string, MemoryFileInfo>) => void;
  setSelectedFile: (fn: string | null) => void;
  setFileDetail: (d: MemoryFileDetail | null) => void;
  openFile: (fn: string) => void;
  closeFile: (fn: string) => void;
  setGraphData: (nodes: MemoryGraphNode[], edges: MemoryGraphEdge[]) => void;
  setSearchQuery: (q: string) => void;
  setSearchResults: (r: MemorySearchResult[]) => void;
  setSearching: (v: boolean) => void;
  setViewMode: (m: ViewMode) => void;
  setSidebarPanel: (p: SidebarPanel) => void;
  setSidebarCollapsed: (v: boolean) => void;
  setRightPanelOpen: (v: boolean) => void;
  reset: () => void;
}

const initialState = {
  sessions: [] as SessionInfo[],
  selectedSessionId: null as string | null,
  loadingSessions: false,
  memoryIndex: null as MemoryIndex | null,
  memoryStats: null as MemoryStats | null,
  loading: false,
  files: {} as Record<string, MemoryFileInfo>,
  selectedFile: null as string | null,
  fileDetail: null as MemoryFileDetail | null,
  openFiles: [] as string[],
  graphNodes: [] as MemoryGraphNode[],
  graphEdges: [] as MemoryGraphEdge[],
  searchQuery: '',
  searchResults: [] as MemorySearchResult[],
  searching: false,
  viewMode: 'editor' as ViewMode,
  sidebarPanel: 'files' as SidebarPanel,
  sidebarCollapsed: false,
  rightPanelOpen: true,
};

export const useObsidianStore = create<ObsidianState>((set) => ({
  ...initialState,

  setSessions: (sessions) => set({ sessions }),
  setSelectedSessionId: (id) => set({ selectedSessionId: id }),
  setLoadingSessions: (v) => set({ loadingSessions: v }),
  setMemoryIndex: (idx) => set({ memoryIndex: idx }),
  setMemoryStats: (s) => set({ memoryStats: s }),
  setLoading: (v) => set({ loading: v }),
  setFiles: (f) => set({ files: f }),
  setSelectedFile: (fn) => set({ selectedFile: fn }),
  setFileDetail: (d) => set({ fileDetail: d }),
  openFile: (fn) =>
    set((s) => ({
      selectedFile: fn,
      openFiles: s.openFiles.includes(fn) ? s.openFiles : [...s.openFiles, fn],
    })),
  closeFile: (fn) =>
    set((s) => {
      const next = s.openFiles.filter((f) => f !== fn);
      return {
        openFiles: next,
        selectedFile:
          s.selectedFile === fn ? next[next.length - 1] ?? null : s.selectedFile,
        fileDetail: s.selectedFile === fn ? null : s.fileDetail,
      };
    }),
  setGraphData: (nodes, edges) => set({ graphNodes: nodes, graphEdges: edges }),
  setSearchQuery: (q) => set({ searchQuery: q }),
  setSearchResults: (r) => set({ searchResults: r }),
  setSearching: (v) => set({ searching: v }),
  setViewMode: (m) => set({ viewMode: m }),
  setSidebarPanel: (p) => set({ sidebarPanel: p }),
  setSidebarCollapsed: (v) => set({ sidebarCollapsed: v }),
  setRightPanelOpen: (v) => set({ rightPanelOpen: v }),
  reset: () => set(initialState),
}));
