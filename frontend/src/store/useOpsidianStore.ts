import { create } from 'zustand';
import type {
  MemoryFileInfo,
  MemoryFileDetail,
  MemoryIndex,
  MemoryStats,
  MemoryGraphNode,
  MemoryGraphEdge,
  MemorySearchResult,
  MemoryOverview,
  SessionInfo,
} from '@/types';

// Memory v2 PR 5 — added 'conversation' so the Opsidian sessions
// scope can render the InteractionEvent stream + dms/ index next to
// the existing notes editor / graph / search views. The tab is
// session-only (irrelevant on user/curator scope).
export type ViewMode = 'editor' | 'graph' | 'search' | 'conversation' | 'digest';
export type SidebarPanel = 'files' | 'tags' | 'backlinks';

/** What `/memory/stats` answers: the vault's size, without the index. */
export interface VaultTotals {
  total_files: number;
  total_chars: number;
  categories: Record<string, number>;
}

export interface OpsidianState {
  // Sessions
  sessions: SessionInfo[];
  selectedSessionId: string | null;
  loadingSessions: boolean;

  // Memory Index
  memoryIndex: MemoryIndex | null;
  memoryStats: MemoryStats | null;
  loading: boolean;

  // Vault catalogue — the counts the sidebar opens with, before any
  // note has been fetched. `daysByCategory` is filled per category as
  // folders are expanded, `loadedDays` records which day pages have
  // already been pulled so re-expanding costs nothing.
  overview: MemoryOverview | null;
  /** The vault's size from the cheap stats endpoint — files, characters and
   *  categories — so the stats panels can say something true before (and
   *  without) the full index. Tags, links and STM/LTM need the index. */
  vaultTotals: VaultTotals | null;
  daysByCategory: Record<string, { day: string; count: number }[]>;
  loadedDays: Record<string, boolean>;
  /** The whole-vault index (tag map, backlinks) — expensive, so it is
   *  fetched only when a panel that genuinely needs it is opened. */
  fullIndexLoaded: boolean;

  // Files — a partial map by design: it holds the notes whose folder or
  // day has actually been opened, not the vault.
  files: Record<string, MemoryFileInfo>;
  // Every category folder (canonical + host-defined) with its file_count
  // and description. Drives the sidebar so empty folders also appear —
  // populated by `memoryApi.listCategories(...)`.
  categories: Array<{
    name: string;
    file_count: number;
    path: string;
    exists: boolean;
    description?: string;
  }>;
  selectedFile: string | null;
  fileDetail: MemoryFileDetail | null;
  openFiles: string[]; // tabs

  // Graph
  //
  // `graphStatus` exists because an empty node list means three different
  // things — not asked yet, asking now, asked and genuinely empty — and
  // the view rendered all three as "No knowledge graph data available".
  graphNodes: MemoryGraphNode[];
  graphEdges: MemoryGraphEdge[];
  graphStatus: 'idle' | 'loading' | 'ready' | 'error';
  graphTruncated: boolean;

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
  /** Fold a page of notes in without dropping what is already there —
   *  what every day / folder expansion uses. */
  mergeFiles: (f: Record<string, MemoryFileInfo>) => void;
  setOverview: (o: MemoryOverview | null) => void;
  setVaultTotals: (v: VaultTotals | null) => void;
  setCategoryDays: (category: string, days: { day: string; count: number }[]) => void;
  markDayLoaded: (key: string) => void;
  setFullIndexLoaded: (v: boolean) => void;
  setCategories: (
    c: Array<{
      name: string;
      file_count: number;
      path: string;
      exists: boolean;
      description?: string;
    }>,
  ) => void;
  setSelectedFile: (fn: string | null) => void;
  setFileDetail: (d: MemoryFileDetail | null) => void;
  openFile: (fn: string) => void;
  closeFile: (fn: string) => void;
  setGraphData: (nodes: MemoryGraphNode[], edges: MemoryGraphEdge[]) => void;
  setGraphStatus: (s: 'idle' | 'loading' | 'ready' | 'error') => void;
  setGraphTruncated: (v: boolean) => void;
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
  overview: null as MemoryOverview | null,
  vaultTotals: null as VaultTotals | null,
  daysByCategory: {} as Record<string, { day: string; count: number }[]>,
  loadedDays: {} as Record<string, boolean>,
  fullIndexLoaded: false,
  files: {} as Record<string, MemoryFileInfo>,
  categories: [] as Array<{
    name: string;
    file_count: number;
    path: string;
    exists: boolean;
    description?: string;
  }>,
  selectedFile: null as string | null,
  fileDetail: null as MemoryFileDetail | null,
  openFiles: [] as string[],
  graphNodes: [] as MemoryGraphNode[],
  graphEdges: [] as MemoryGraphEdge[],
  graphStatus: 'idle' as 'idle' | 'loading' | 'ready' | 'error',
  graphTruncated: false,
  searchQuery: '',
  searchResults: [] as MemorySearchResult[],
  searching: false,
  viewMode: 'editor' as ViewMode,
  sidebarPanel: 'files' as SidebarPanel,
  sidebarCollapsed: false,
  rightPanelOpen: true,
};

export const useOpsidianStore = create<OpsidianState>((set) => ({
  ...initialState,

  setSessions: (sessions) => set({ sessions }),
  setSelectedSessionId: (id) => set({ selectedSessionId: id }),
  setLoadingSessions: (v) => set({ loadingSessions: v }),
  setMemoryIndex: (idx) => set({ memoryIndex: idx }),
  setMemoryStats: (s) => set({ memoryStats: s }),
  setLoading: (v) => set({ loading: v }),
  setFiles: (f) => set({ files: f }),
  mergeFiles: (f) => set((s) => ({ files: { ...s.files, ...f } })),
  setOverview: (o) => set({ overview: o }),
  setVaultTotals: (v) => set({ vaultTotals: v }),
  setCategoryDays: (category, days) =>
    set((s) => ({ daysByCategory: { ...s.daysByCategory, [category]: days } })),
  markDayLoaded: (key) =>
    set((s) => ({ loadedDays: { ...s.loadedDays, [key]: true } })),
  setFullIndexLoaded: (v) => set({ fullIndexLoaded: v }),
  setCategories: (c) => set({ categories: c }),
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
  setGraphStatus: (graphStatus) => set({ graphStatus }),
  setGraphTruncated: (graphTruncated) => set({ graphTruncated }),
  setSearchQuery: (q) => set({ searchQuery: q }),
  setSearchResults: (r) => set({ searchResults: r }),
  setSearching: (v) => set({ searching: v }),
  setViewMode: (m) => set({ viewMode: m }),
  setSidebarPanel: (p) => set({ sidebarPanel: p }),
  setSidebarCollapsed: (v) => set({ sidebarCollapsed: v }),
  setRightPanelOpen: (v) => set({ rightPanelOpen: v }),
  reset: () => set(initialState),
}));
