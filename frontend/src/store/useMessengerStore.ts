import { create } from 'zustand';
import { chatApi } from '@/lib/api';
import type { ChatRoom, ChatRoomMessage } from '@/types';

interface TypingAgent {
  session_id: string;
  session_name: string;
  role: string;
}

interface MessengerState {
  // Rooms
  rooms: ChatRoom[];
  activeRoomId: string | null;
  loadingRooms: boolean;
  searchQuery: string;

  // Messages
  messages: ChatRoomMessage[];
  loadingMessages: boolean;
  isSending: boolean;
  typingAgents: TypingAgent[];

  // UI
  createModalOpen: boolean;
  inviteModalOpen: boolean;
  mobileSidebarOpen: boolean;
  sidebarCollapsed: boolean;
  memberPanelOpen: boolean;
  selectedMemberId: string | null;

  // Actions - Rooms
  fetchRooms: () => Promise<void>;
  setActiveRoom: (roomId: string | null) => Promise<void>;
  deleteRoom: (roomId: string) => Promise<void>;
  addMembersToRoom: (sessionIds: string[]) => Promise<void>;
  setSearchQuery: (q: string) => void;

  // Actions - Messages
  sendMessage: (
    content: string,
    sessions: Array<{ session_id: string; session_name: string; role: string }>,
  ) => Promise<void>;

  // Actions - UI
  setCreateModalOpen: (open: boolean) => void;
  setInviteModalOpen: (open: boolean) => void;
  setMobileSidebarOpen: (open: boolean) => void;
  toggleSidebarCollapsed: () => void;
  setMemberPanelOpen: (open: boolean) => void;
  setSelectedMemberId: (id: string | null) => void;

  // Derived
  getActiveRoom: () => ChatRoom | undefined;
  getFilteredRooms: () => ChatRoom[];
}

export const useMessengerStore = create<MessengerState>((set, get) => ({
  rooms: [],
  activeRoomId: null,
  loadingRooms: false,
  searchQuery: '',
  messages: [],
  loadingMessages: false,
  isSending: false,
  typingAgents: [],
  createModalOpen: false,
  inviteModalOpen: false,
  mobileSidebarOpen: false,
  sidebarCollapsed: false,
  memberPanelOpen: false,
  selectedMemberId: null,

  fetchRooms: async () => {
    set({ loadingRooms: true });
    try {
      const res = await chatApi.listRooms();
      set({ rooms: res.rooms });
    } catch {
      /* ignore */
    } finally {
      set({ loadingRooms: false });
    }
  },

  setActiveRoom: async (roomId) => {
    if (!roomId) {
      set({ activeRoomId: null, messages: [], mobileSidebarOpen: false });
      return;
    }
    set({ activeRoomId: roomId, loadingMessages: true, mobileSidebarOpen: false });
    try {
      const msgsRes = await chatApi.getRoomMessages(roomId);
      set({ messages: msgsRes.messages });
    } catch {
      /* ignore */
    } finally {
      set({ loadingMessages: false });
    }
  },

  deleteRoom: async (roomId) => {
    try {
      await chatApi.deleteRoom(roomId);
      const { activeRoomId } = get();
      set(s => ({
        rooms: s.rooms.filter(r => r.id !== roomId),
        ...(activeRoomId === roomId ? { activeRoomId: null, messages: [] } : {}),
      }));
    } catch {
      /* ignore */
    }
  },

  setSearchQuery: (q) => set({ searchQuery: q }),

  addMembersToRoom: async (sessionIds) => {
    const { activeRoomId, fetchRooms } = get();
    if (!activeRoomId || sessionIds.length === 0) return;
    const room = get().getActiveRoom();
    if (!room) return;
    const merged = [...new Set([...room.session_ids, ...sessionIds])];
    try {
      await chatApi.updateRoom(activeRoomId, { session_ids: merged });
      await fetchRooms();
    } catch {
      /* ignore */
    }
  },

  sendMessage: async (content, sessions) => {
    const { activeRoomId } = get();
    if (!activeRoomId || !content.trim()) return;

    set({ isSending: true });

    const optimisticId = `opt-${Date.now()}`;
    const optimistic: ChatRoomMessage = {
      id: optimisticId,
      type: 'user',
      content: content.trim(),
      timestamp: new Date().toISOString(),
    };

    set(s => ({
      messages: [...s.messages, optimistic],
      typingAgents: sessions,
    }));

    try {
      await chatApi.broadcastToRoom(
        activeRoomId,
        { message: content.trim() },
        (eventType, eventData) => {
          const msg = eventData as ChatRoomMessage;
          switch (eventType) {
            case 'user_saved':
              set(s => ({
                messages: s.messages.map(m => m.id === optimisticId ? msg : m),
              }));
              break;
            case 'agent_response':
              set(s => ({
                messages: [...s.messages, msg],
                typingAgents: s.typingAgents.filter(
                  a => a.session_id !== (msg as ChatRoomMessage & { session_id?: string }).session_id,
                ),
              }));
              break;
            case 'agent_skip':
              set(s => ({
                typingAgents: s.typingAgents.filter(
                  a => a.session_id !== (eventData as Record<string, unknown>).session_id,
                ),
              }));
              break;
            case 'agent_error': {
              const errData = eventData as Record<string, unknown>;
              set(s => ({
                messages: [...s.messages, {
                  id: `err-${Date.now()}-${errData.session_id || ''}`,
                  type: 'system' as const,
                  content: `${errData.session_name || 'Agent'}: ${errData.error || 'Error'}`,
                  timestamp: new Date().toISOString(),
                }],
                typingAgents: s.typingAgents.filter(a => a.session_id !== errData.session_id),
              }));
              break;
            }
            case 'summary':
              set(s => ({ messages: [...s.messages, msg] }));
              break;
            case 'done':
              set({ typingAgents: [] });
              break;
            case 'error': {
              const errData2 = eventData as Record<string, unknown>;
              set(s => ({
                messages: [...s.messages, {
                  id: `sys-err-${Date.now()}`,
                  type: 'system' as const,
                  content: String(errData2.error || 'Unknown error'),
                  timestamp: new Date().toISOString(),
                }],
              }));
              break;
            }
          }
        },
      );
      // Refresh room list to update message counts
      get().fetchRooms();
    } catch (e: unknown) {
      set(s => ({
        messages: [...s.messages, {
          id: `err-${Date.now()}`,
          type: 'system' as const,
          content: e instanceof Error ? e.message : 'Failed to send message',
          timestamp: new Date().toISOString(),
        }],
      }));
    } finally {
      set({ isSending: false, typingAgents: [] });
    }
  },

  setCreateModalOpen: (open) => set({ createModalOpen: open }),
  setInviteModalOpen: (open) => set({ inviteModalOpen: open }),
  setMobileSidebarOpen: (open) => set({ mobileSidebarOpen: open }),
  toggleSidebarCollapsed: () => set(s => ({ sidebarCollapsed: !s.sidebarCollapsed })),
  setMemberPanelOpen: (open) => set({ memberPanelOpen: open, ...(!open ? { selectedMemberId: null } : {}) }),
  setSelectedMemberId: (id) => set({ selectedMemberId: id, memberPanelOpen: !!id }),

  getActiveRoom: () => {
    const { rooms, activeRoomId } = get();
    return rooms.find(r => r.id === activeRoomId);
  },

  getFilteredRooms: () => {
    const { rooms, searchQuery } = get();
    if (!searchQuery.trim()) return rooms;
    const q = searchQuery.toLowerCase();
    return rooms.filter(r => r.name.toLowerCase().includes(q));
  },
}));
