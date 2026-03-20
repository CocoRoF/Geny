'use client';

import { useMessengerStore } from '@/store/useMessengerStore';
import { useI18n } from '@/lib/i18n';
import { useTheme } from '@/lib/theme';
import {
  Hash, Plus, Search, X, Trash2, MessageCircle,
  ArrowLeft, Sun, Moon, Users, PanelLeftClose, PanelLeftOpen,
} from 'lucide-react';
import Link from 'next/link';
import { useCallback, useState } from 'react';

const formatRelative = (ts: string) => {
  const diff = Date.now() - new Date(ts).getTime();
  const mins = Math.floor(diff / 60000);
  if (mins < 1) return 'now';
  if (mins < 60) return `${mins}m`;
  const hrs = Math.floor(mins / 60);
  if (hrs < 24) return `${hrs}h`;
  return `${Math.floor(hrs / 24)}d`;
};

export default function RoomSidebar() {
  const {
    activeRoomId, setActiveRoom, deleteRoom,
    searchQuery, setSearchQuery, getFilteredRooms,
    setCreateModalOpen, mobileSidebarOpen, setMobileSidebarOpen,
    sidebarCollapsed, toggleSidebarCollapsed,
  } = useMessengerStore();
  const { t } = useI18n();
  const { theme, setTheme } = useTheme();
  const [confirmDeleteId, setConfirmDeleteId] = useState<string | null>(null);

  const rooms = getFilteredRooms();

  const handleDelete = useCallback(async (e: React.MouseEvent, roomId: string) => {
    e.stopPropagation();
    if (confirmDeleteId === roomId) {
      await deleteRoom(roomId);
      setConfirmDeleteId(null);
    } else {
      setConfirmDeleteId(roomId);
      setTimeout(() => setConfirmDeleteId(null), 3000);
    }
  }, [confirmDeleteId, deleteRoom]);

  const toggleTheme = useCallback(() => {
    document.documentElement.classList.add('theme-transition');
    setTimeout(() => document.documentElement.classList.remove('theme-transition'), 400);
    setTheme(theme === 'dark' ? 'light' : 'dark');
  }, [theme, setTheme]);

  const sidebarContent = (
    <div className="flex flex-col w-full h-full bg-[var(--bg-secondary)]">
      {/* Sidebar Header */}
      <div className="shrink-0 p-4 border-b border-[var(--border-color)]">
        <div className="flex items-center justify-between mb-3">
          <div className="flex items-center gap-2.5">
            <div className="w-8 h-8 rounded-lg bg-gradient-to-br from-[var(--primary-color)] to-blue-600 flex items-center justify-center shadow-sm">
              <MessageCircle size={14} className="text-white" />
            </div>
            <div>
              <h1 className="text-[0.875rem] font-bold text-[var(--text-primary)] leading-tight">
                Geny Chat
              </h1>
              <span className="text-[0.625rem] text-[var(--text-muted)]">
                {t('messenger.subtitle')}
              </span>
            </div>
          </div>
          <div className="flex items-center gap-1">
            <button
              onClick={toggleSidebarCollapsed}
              className="hidden md:flex w-7 h-7 rounded-md items-center justify-center text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] transition-all border-none bg-transparent cursor-pointer"
              title="Collapse sidebar"
            >
              <PanelLeftClose size={13} />
            </button>
            <button
              onClick={toggleTheme}
              className="w-7 h-7 rounded-md flex items-center justify-center text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] transition-all border-none bg-transparent cursor-pointer"
              title={theme === 'dark' ? 'Light mode' : 'Dark mode'}
            >
              {theme === 'dark' ? <Sun size={13} /> : <Moon size={13} />}
            </button>
            {/* Close sidebar on mobile */}
            <button
              className="w-7 h-7 rounded-md flex md:hidden items-center justify-center text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] transition-all border-none bg-transparent cursor-pointer"
              onClick={() => setMobileSidebarOpen(false)}
            >
              <X size={14} />
            </button>
          </div>
        </div>

        {/* Search */}
        <div className="relative">
          <Search size={13} className="absolute left-2.5 top-1/2 -translate-y-1/2 text-[var(--text-muted)]" />
          <input
            type="text"
            className="w-full pl-8 pr-3 py-1.5 rounded-lg bg-[var(--bg-primary)] border border-[var(--border-color)] text-[var(--text-primary)] text-[0.75rem] placeholder:text-[var(--text-muted)] focus:outline-none focus:border-[var(--primary-color)] transition-all"
            placeholder={t('messenger.searchRooms')}
            value={searchQuery}
            onChange={e => setSearchQuery(e.target.value)}
          />
          {searchQuery && (
            <button
              className="absolute right-2 top-1/2 -translate-y-1/2 text-[var(--text-muted)] hover:text-[var(--text-primary)] border-none bg-transparent cursor-pointer"
              onClick={() => setSearchQuery('')}
            >
              <X size={12} />
            </button>
          )}
        </div>
      </div>

      {/* New Room Button */}
      <div className="shrink-0 px-3 pt-3 pb-1">
        <button
          className="w-full flex items-center justify-center gap-1.5 py-2 rounded-lg bg-[var(--primary-color)] hover:bg-[var(--primary-hover)] text-white text-[0.75rem] font-medium cursor-pointer border-none transition-all shadow-sm"
          onClick={() => setCreateModalOpen(true)}
        >
          <Plus size={14} />
          {t('messenger.newRoom')}
        </button>
      </div>

      {/* Room List */}
      <div className="flex-1 min-h-0 overflow-y-auto px-2 py-2 space-y-0.5">
        {rooms.length === 0 && (
          <div className="flex flex-col items-center justify-center py-12 text-center px-4">
            <Hash size={28} className="text-[var(--text-muted)] opacity-30 mb-3" />
            <p className="text-[0.75rem] text-[var(--text-muted)]">
              {searchQuery ? t('messenger.noSearchResults') : t('messenger.noRooms')}
            </p>
          </div>
        )}

        {rooms.map(room => {
          const isActive = room.id === activeRoomId;
          const isDeleting = confirmDeleteId === room.id;
          return (
            <div
              key={room.id}
              className={`group flex items-center gap-2.5 px-2.5 py-2 rounded-lg cursor-pointer transition-all duration-150 ${
                isActive
                  ? 'bg-[var(--primary-subtle)] text-[var(--text-primary)]'
                  : 'text-[var(--text-secondary)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]'
              }`}
              onClick={() => setActiveRoom(room.id)}
            >
              <div className={`w-8 h-8 rounded-lg flex items-center justify-center shrink-0 ${
                isActive
                  ? 'bg-[var(--primary-color)] text-white'
                  : 'bg-[var(--bg-tertiary)] text-[var(--text-muted)]'
              }`}>
                <Hash size={14} />
              </div>
              <div className="flex-1 min-w-0">
                <div className="flex items-center justify-between">
                  <span className={`text-[0.8125rem] truncate ${isActive ? 'font-semibold' : 'font-medium'}`}>
                    {room.name}
                  </span>
                  <span className="text-[0.625rem] text-[var(--text-muted)] shrink-0 ml-1">
                    {formatRelative(room.updated_at)}
                  </span>
                </div>
                <div className="flex items-center gap-2 mt-0.5">
                  <span className="flex items-center gap-0.5 text-[0.625rem] text-[var(--text-muted)]">
                    <Users size={9} />
                    {room.session_ids.length}
                  </span>
                  <span className="flex items-center gap-0.5 text-[0.625rem] text-[var(--text-muted)]">
                    <MessageCircle size={9} />
                    {room.message_count}
                  </span>
                </div>
              </div>
              <button
                className={`shrink-0 w-6 h-6 rounded-md flex items-center justify-center border-none cursor-pointer transition-all opacity-0 group-hover:opacity-100 ${
                  isDeleting
                    ? 'bg-red-500 text-white opacity-100'
                    : 'bg-transparent text-[var(--text-muted)] hover:text-red-500 hover:bg-[rgba(239,68,68,0.1)]'
                }`}
                onClick={e => handleDelete(e, room.id)}
                title={isDeleting ? t('messenger.confirmDelete') : t('messenger.deleteRoom')}
              >
                <Trash2 size={12} />
              </button>
            </div>
          );
        })}
      </div>

      {/* Back to Dashboard */}
      <div className="shrink-0 p-3 border-t border-[var(--border-color)]">
        <Link
          href="/"
          className="flex items-center gap-2 px-3 py-2 rounded-lg text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] transition-all text-[0.75rem] font-medium no-underline"
        >
          <ArrowLeft size={14} />
          {t('messenger.backToDashboard')}
        </Link>
      </div>
    </div>
  );

  // ── Collapsed sidebar (icons only) ──
  const collapsedContent = (
    <div className="flex flex-col items-center w-full h-full bg-[var(--bg-secondary)] py-3 gap-1">
      {/* Expand button */}
      <button
        onClick={toggleSidebarCollapsed}
        className="w-9 h-9 rounded-lg flex items-center justify-center text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] transition-all border-none bg-transparent cursor-pointer mb-2"
        title="Expand sidebar"
      >
        <PanelLeftOpen size={16} />
      </button>

      {/* New room */}
      <button
        onClick={() => setCreateModalOpen(true)}
        className="w-9 h-9 rounded-lg bg-[var(--primary-color)] hover:bg-[var(--primary-hover)] flex items-center justify-center text-white border-none cursor-pointer transition-all shadow-sm mb-2"
        title={t('messenger.newRoom')}
      >
        <Plus size={16} />
      </button>

      {/* Room icons */}
      <div className="flex-1 min-h-0 overflow-y-auto flex flex-col items-center gap-1 w-full px-1.5">
        {rooms.map(room => {
          const isActive = room.id === activeRoomId;
          return (
            <button
              key={room.id}
              onClick={() => setActiveRoom(room.id)}
              className={`w-9 h-9 rounded-lg flex items-center justify-center shrink-0 border-none cursor-pointer transition-all ${
                isActive
                  ? 'bg-[var(--primary-color)] text-white'
                  : 'bg-[var(--bg-tertiary)] text-[var(--text-muted)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)]'
              }`}
              title={room.name}
            >
              <Hash size={14} />
            </button>
          );
        })}
      </div>

      {/* Theme toggle */}
      <button
        onClick={toggleTheme}
        className="w-9 h-9 rounded-lg flex items-center justify-center text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] transition-all border-none bg-transparent cursor-pointer mt-1"
        title={theme === 'dark' ? 'Light mode' : 'Dark mode'}
      >
        {theme === 'dark' ? <Sun size={14} /> : <Moon size={14} />}
      </button>

      {/* Back to dashboard */}
      <Link
        href="/"
        className="w-9 h-9 rounded-lg flex items-center justify-center text-[var(--text-muted)] hover:text-[var(--text-primary)] hover:bg-[var(--bg-hover)] transition-all no-underline"
        title={t('messenger.backToDashboard')}
      >
        <ArrowLeft size={14} />
      </Link>
    </div>
  );

  return (
    <>
      {/* Desktop sidebar */}
      <div
        className={`hidden md:flex shrink-0 overflow-hidden transition-[width] duration-200 ease-in-out bg-[var(--bg-secondary)] border-r border-[var(--border-color)] ${
          sidebarCollapsed ? 'w-[48px]' : 'w-[280px]'
        }`}
      >
        {sidebarCollapsed ? collapsedContent : sidebarContent}
      </div>

      {/* Mobile sidebar overlay */}
      {mobileSidebarOpen && (
        <div className="fixed inset-0 z-50 flex md:hidden">
          <div
            className="absolute inset-0 bg-black/50"
            onClick={() => setMobileSidebarOpen(false)}
          />
          <div className="relative w-[300px] max-w-[85vw] h-full shadow-2xl animate-[slideInLeft_200ms_ease-out]">
            {sidebarContent}
          </div>
        </div>
      )}
    </>
  );
}
