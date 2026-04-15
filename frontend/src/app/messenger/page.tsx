'use client';

import { useEffect } from 'react';
import { useMessengerStore } from '@/store/useMessengerStore';
import { useAppStore } from '@/store/useAppStore';
import RoomSidebar from '@/components/messenger/RoomSidebar';
import RoomHeader from '@/components/messenger/RoomHeader';
import MessageList from '@/components/messenger/MessageList';
import MessageInput from '@/components/messenger/MessageInput';
import CreateRoomModal from '@/components/messenger/CreateRoomModal';
import InviteMemberModal from '@/components/messenger/InviteMemberModal';
import MemberPanel from '@/components/messenger/MemberPanel';
import FileChangeDetailPanel from '@/components/messenger/FileChangeDetailPanel';
import { MessageCircle } from 'lucide-react';
import { useI18n } from '@/lib/i18n';

export default function MessengerPage() {
  const { fetchRooms, activeRoomId, createModalOpen, inviteModalOpen, memberPanelOpen, fileChangeDetail } = useMessengerStore();
  const { loadSessions, checkHealth, loadUserName } = useAppStore();
  const { t } = useI18n();

  useEffect(() => {
    fetchRooms();
    loadSessions();
    checkHealth();
    loadUserName();

    // Re-establish WebSocket if we already have an active room (e.g. after
    // navigating away and back — WS was closed on unmount).
    useMessengerStore.getState()._ensureWS();

    const interval = setInterval(fetchRooms, 30000);
    return () => {
      clearInterval(interval);
      // Close SSE event stream on unmount (backend continues processing)
      useMessengerStore.getState()._unsubscribeEvents();
    };
  }, [fetchRooms, loadSessions, checkHealth, loadUserName]);

  return (
    <div className="flex h-screen h-[100dvh] overflow-hidden bg-[var(--bg-primary)]">
      {/* Room Sidebar */}
      <RoomSidebar />

      {/* Main Chat Area */}
      <div className="flex-1 flex flex-col min-w-0">
        {activeRoomId ? (
          <>
            <RoomHeader />
            <MessageList />
            <MessageInput />
          </>
        ) : (
          <div className="flex-1 flex flex-col items-center justify-center text-center px-6">
            <div className="w-20 h-20 rounded-2xl bg-gradient-to-br from-[var(--primary-color)] to-blue-600 flex items-center justify-center mb-6 shadow-lg">
              <MessageCircle size={36} className="text-white" />
            </div>
            <h2 className="text-xl font-bold text-[var(--text-primary)] mb-2">
              {t('messenger.welcomeTitle')}
            </h2>
            <p className="text-[0.875rem] text-[var(--text-muted)] max-w-md leading-relaxed">
              {t('messenger.welcomeDesc')}
            </p>
          </div>
        )}
      </div>

      {/* Member Info Panel */}
      {activeRoomId && memberPanelOpen && <MemberPanel />}

      {/* File Change Detail Panel */}
      {activeRoomId && fileChangeDetail && <FileChangeDetailPanel />}

      {/* Create Room Modal */}
      {createModalOpen && <CreateRoomModal />}

      {/* Invite Member Modal */}
      {inviteModalOpen && <InviteMemberModal />}
    </div>
  );
}
