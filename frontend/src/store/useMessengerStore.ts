import { create } from 'zustand';
import { chatApi } from '@/lib/api';
import type { ChatRoom, ChatRoomMessage, BroadcastStatus, AgentProgressState, FileChanges } from '@/types';

interface MessengerState {
  // Rooms
  rooms: ChatRoom[];
  activeRoomId: string | null;
  loadingRooms: boolean;
  searchQuery: string;

  // Messages
  messages: ChatRoomMessage[];
  loadingMessages: boolean;
  loadingOlderMessages: boolean;
  hasMoreMessages: boolean;
  isSending: boolean;

  // Broadcast progress
  broadcastStatus: BroadcastStatus | null;
  agentProgress: AgentProgressState[] | null;  // NEW: per-agent progress

  // Event subscription (internal)
  _eventSub: { close: () => void } | null;
  _lastMsgId: string | null;

  // UI
  createModalOpen: boolean;
  inviteModalOpen: boolean;
  mobileSidebarOpen: boolean;
  sidebarCollapsed: boolean;
  memberPanelOpen: boolean;
  selectedMemberId: string | null;
  fileChangeDetail: FileChanges[] | null;

  // Actions - Rooms
  fetchRooms: () => Promise<void>;
  setActiveRoom: (roomId: string | null) => Promise<void>;
  deleteRoom: (roomId: string) => Promise<void>;
  addMembersToRoom: (sessionIds: string[]) => Promise<void>;
  setSearchQuery: (q: string) => void;

  // Actions - Messages
  sendMessage: (content: string) => Promise<void>;
  loadOlderMessages: () => Promise<void>;
  cancelBroadcast: () => Promise<void>;

  // Actions - Event stream
  _subscribeToEvents: (roomId: string) => void;
  _unsubscribeEvents: () => void;
  _ensureWS: () => void;

  // Actions - UI
  setCreateModalOpen: (open: boolean) => void;
  setInviteModalOpen: (open: boolean) => void;
  setMobileSidebarOpen: (open: boolean) => void;
  toggleSidebarCollapsed: () => void;
  setMemberPanelOpen: (open: boolean) => void;
  setSelectedMemberId: (id: string | null) => void;
  setFileChangeDetail: (fc: FileChanges[] | null) => void;

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
  loadingOlderMessages: false,
  hasMoreMessages: false,
  isSending: false,
  broadcastStatus: null,
  agentProgress: null,
  _eventSub: null,
  _lastMsgId: null,
  createModalOpen: false,
  inviteModalOpen: false,
  mobileSidebarOpen: false,
  sidebarCollapsed: false,
  memberPanelOpen: false,
  selectedMemberId: null,
  fileChangeDetail: null,

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
    const { _unsubscribeEvents } = get();
    _unsubscribeEvents();

    if (!roomId) {
      set({ activeRoomId: null, messages: [], mobileSidebarOpen: false, broadcastStatus: null, _lastMsgId: null, hasMoreMessages: false });
      return;
    }
    set({ activeRoomId: roomId, loadingMessages: true, mobileSidebarOpen: false, broadcastStatus: null });
    try {
      const PAGE_SIZE = 50;
      const msgsRes = await chatApi.getRoomMessages(roomId, { limit: PAGE_SIZE });
      const msgs = msgsRes.messages;
      const lastId = msgs.length > 0 ? msgs[msgs.length - 1].id : null;
      set({ messages: msgs, _lastMsgId: lastId, hasMoreMessages: msgsRes.has_more ?? false });

      // Subscribe to live events starting from the last known message
      get()._subscribeToEvents(roomId);
    } catch {
      /* ignore */
    } finally {
      set({ loadingMessages: false });
    }
  },

  deleteRoom: async (roomId) => {
    try {
      await chatApi.deleteRoom(roomId);
      const { activeRoomId, _unsubscribeEvents } = get();
      if (activeRoomId === roomId) {
        _unsubscribeEvents();
      }
      set(s => ({
        rooms: s.rooms.filter(r => r.id !== roomId),
        ...(activeRoomId === roomId ? { activeRoomId: null, messages: [], broadcastStatus: null, _lastMsgId: null } : {}),
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

  sendMessage: async (content) => {
    const { activeRoomId } = get();
    if (!activeRoomId || !content.trim()) return;

    set({ isSending: true });

    try {
      const res = await chatApi.broadcastToRoom(activeRoomId, { message: content.trim() });
      // Add user message immediately (optimistic)
      set(s => {
        const alreadyExists = s.messages.some(m => m.id === res.user_message.id);
        if (alreadyExists) return {};
        return {
          messages: [...s.messages, res.user_message],
          _lastMsgId: res.user_message.id,
        };
      });

      if (res.target_count > 0 && res.broadcast_id) {
        set({
          broadcastStatus: {
            broadcast_id: res.broadcast_id,
            total: res.target_count,
            completed: 0,
            responded: 0,
            finished: false,
          },
        });
        // Agent responses and broadcast completion arrive via WebSocket
        // (`message`, `broadcast_status`, `broadcast_done` events).
        // No polling needed.
      }

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
      set({ isSending: false });
    }
  },

  loadOlderMessages: async () => {
    const { activeRoomId, messages, loadingOlderMessages, hasMoreMessages } = get();
    if (!activeRoomId || loadingOlderMessages || !hasMoreMessages) return;

    const oldestId = messages.length > 0 ? messages[0].id : undefined;
    set({ loadingOlderMessages: true });
    try {
      const PAGE_SIZE = 50;
      const res = await chatApi.getRoomMessages(activeRoomId, {
        limit: PAGE_SIZE,
        before: oldestId,
      });
      set(s => ({
        messages: [...res.messages, ...s.messages],
        hasMoreMessages: res.has_more ?? false,
      }));
    } catch {
      /* ignore */
    } finally {
      set({ loadingOlderMessages: false });
    }
  },

  cancelBroadcast: async () => {
    const { activeRoomId, broadcastStatus } = get();
    if (!activeRoomId || !broadcastStatus || broadcastStatus.finished) return;
    try {
      await chatApi.cancelBroadcast(activeRoomId);
    } catch {
      /* ignore — broadcast may have already finished */
    }
  },

  _subscribeToEvents: (roomId: string) => {
    const { _lastMsgId, _unsubscribeEvents } = get();
    _unsubscribeEvents();

    const sub = chatApi.subscribeToRoom(
      roomId,
      _lastMsgId,
      (eventType, eventData) => {
        const state = get();
        if (state.activeRoomId !== roomId) return;

        switch (eventType) {
          case 'message': {
            const msg = eventData as unknown as ChatRoomMessage;
            set(s => {
              if (s.messages.some(m => m.id === msg.id)) return {};
              return {
                messages: [...s.messages, msg],
                _lastMsgId: msg.id,
              };
            });
            break;
          }
          case 'broadcast_status': {
            const status = eventData as unknown as BroadcastStatus;
            set({ broadcastStatus: status });
            break;
          }
          case 'agent_progress': {
            // Per-agent execution progress with thinking previews
            const progress = eventData as unknown as { broadcast_id: string; agents: AgentProgressState[] };
            set({ agentProgress: progress.agents });
            break;
          }
          case 'broadcast_done': {
            set({ broadcastStatus: null, agentProgress: null });
            get().fetchRooms();
            break;
          }
        }
      },
      () => get()._lastMsgId,
    );

    set({ _eventSub: sub });
  },

  _unsubscribeEvents: () => {
    const { _eventSub } = get();
    if (_eventSub) {
      _eventSub.close();
      set({ _eventSub: null });
    }
  },

  _ensureWS: () => {
    const { activeRoomId, _eventSub } = get();
    if (activeRoomId && !_eventSub) {
      get()._subscribeToEvents(activeRoomId);
    }
  },

  setCreateModalOpen: (open) => set({ createModalOpen: open }),
  setInviteModalOpen: (open) => set({ inviteModalOpen: open }),
  setMobileSidebarOpen: (open) => set({ mobileSidebarOpen: open }),
  toggleSidebarCollapsed: () => set(s => ({ sidebarCollapsed: !s.sidebarCollapsed })),
  setMemberPanelOpen: (open) => set({ memberPanelOpen: open, ...(!open ? { selectedMemberId: null } : {}) }),
  setSelectedMemberId: (id) => set({ selectedMemberId: id, memberPanelOpen: !!id }),
  setFileChangeDetail: (fc) => set({ fileChangeDetail: fc }),

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
