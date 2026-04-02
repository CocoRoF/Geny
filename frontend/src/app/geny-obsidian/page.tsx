'use client';

import dynamic from 'next/dynamic';

const ObsidianView = dynamic(() => import('@/components/obsidian/ObsidianView'), {
  ssr: false,
  loading: () => (
    <div
      style={{
        width: '100vw',
        height: '100vh',
        display: 'flex',
        alignItems: 'center',
        justifyContent: 'center',
        background: 'var(--bg-primary)',
        color: 'var(--text-muted)',
        fontSize: 14,
      }}
    >
      Loading Obsidian View…
    </div>
  ),
});

export default function GenyObsidianPage() {
  return <ObsidianView />;
}
