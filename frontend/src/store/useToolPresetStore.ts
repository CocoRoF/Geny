/**
 * Tool Preset Store — Zustand state management for tool presets and catalog.
 */

import { create } from 'zustand';
import { toolPresetApi, toolCatalogApi } from '@/lib/toolApi';
import type {
  ToolPresetDefinition,
  ToolCatalogResponse,
} from '@/types';

interface ToolPresetState {
  // Data
  presets: ToolPresetDefinition[];
  catalog: ToolCatalogResponse | null;
  isLoading: boolean;
  error: string | null;

  // Actions
  loadPresets: () => Promise<void>;
  loadCatalog: () => Promise<void>;
  createPreset: (data: { name: string; description?: string; custom_tools?: string[]; mcp_servers?: string[] }) => Promise<ToolPresetDefinition>;
  updatePreset: (id: string, data: Partial<Pick<ToolPresetDefinition,
    'name' | 'description' | 'icon' | 'custom_tools' | 'mcp_servers'
    | 'built_in_mode' | 'built_in_tools' | 'built_in_deny'
  >>) => Promise<void>;
  deletePreset: (id: string) => Promise<void>;
  clonePreset: (id: string, newName: string) => Promise<ToolPresetDefinition>;
}

export const useToolPresetStore = create<ToolPresetState>((set, get) => ({
  presets: [],
  catalog: null,
  isLoading: false,
  error: null,

  loadPresets: async () => {
    set({ isLoading: true, error: null });
    try {
      const res = await toolPresetApi.list();
      set({ presets: res.presets, isLoading: false });
    } catch (e) {
      set({ error: e instanceof Error ? e.message : 'Failed to load presets', isLoading: false });
    }
  },

  loadCatalog: async () => {
    try {
      const catalog = await toolCatalogApi.catalog();
      set({ catalog });
    } catch (e) {
      set({ error: e instanceof Error ? e.message : 'Failed to load catalog' });
    }
  },

  createPreset: async (data) => {
    const preset = await toolPresetApi.create(data);
    await get().loadPresets();
    return preset;
  },

  updatePreset: async (id, data) => {
    await toolPresetApi.update(id, data);
    await get().loadPresets();
  },

  deletePreset: async (id) => {
    await toolPresetApi.delete(id);
    await get().loadPresets();
  },

  clonePreset: async (id, newName) => {
    const cloned = await toolPresetApi.clone(id, newName);
    await get().loadPresets();
    return cloned;
  },
}));
