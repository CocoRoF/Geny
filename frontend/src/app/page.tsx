'use client';

import { useEffect } from 'react';
import { useAppStore } from '@/store/useAppStore';
import Header from '@/components/Header';
import Sidebar from '@/components/Sidebar';
import TabNavigation from '@/components/TabNavigation';
import TabContent from '@/components/TabContent';

export default function Home() {
  const { loadSessions, loadDeletedSessions, checkHealth, loadPrompts } = useAppStore();

  useEffect(() => {
    loadSessions();
    loadDeletedSessions();
    checkHealth();
    loadPrompts();

    const healthInterval = setInterval(checkHealth, 15000);
    const sessionInterval = setInterval(loadSessions, 10000);

    return () => {
      clearInterval(healthInterval);
      clearInterval(sessionInterval);
    };
  }, [loadSessions, loadDeletedSessions, checkHealth, loadPrompts]);

  return (
    <div className="flex flex-col h-screen overflow-hidden">
      <Header />
      <div className="flex flex-1 overflow-hidden">
        <Sidebar />
        <div className="flex-1 flex flex-col overflow-hidden bg-[var(--bg-primary)]">
          <TabNavigation />
          <TabContent />
        </div>
      </div>
    </div>
  );
}
