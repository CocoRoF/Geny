'use client';

/**
 * /environments — dedicated page for the visual 21-stage environment
 * builder.
 *
 * Cycle 20260427_2 PR-1 split the surface from the dev-mode tab system;
 * PR-2 redesigned the layout to be canvas-first. The page wrapper here
 * is intentionally minimal — its only chrome is the back link + page
 * title. The shell's CompactMetaBar handles the env metadata + actions
 * (Save / Discard / Globals drawer) directly above the canvas, so the
 * page header doesn't compete for vertical space.
 */

import { useRouter } from 'next/navigation';
import Link from 'next/link';
import { ArrowLeft, Sparkles } from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import { useEnvironmentStore } from '@/store/useEnvironmentStore';
import EnvManagementShell from '@/components/env_management/EnvManagementShell';

export default function EnvironmentManagementPage() {
  const { t } = useI18n();
  const router = useRouter();
  const requestOpenEnvDrawer = useEnvironmentStore(
    (s) => s.requestOpenEnvDrawer,
  );

  const handleSaved = (newEnvId: string) => {
    requestOpenEnvDrawer(newEnvId);
    router.push('/');
  };

  return (
    <div className="min-h-screen h-screen bg-[hsl(var(--background))] text-[hsl(var(--foreground))] flex flex-col overflow-hidden">
      {/* ── Slim page header (back link + page title) ── */}
      <header className="flex items-center h-11 px-4 md:px-6 border-b border-[hsl(var(--border))] bg-[hsl(var(--card))] shrink-0 gap-2">
        <Link
          href="/"
          className="inline-flex items-center gap-1 text-[0.75rem] text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))] no-underline transition-colors px-1.5 py-1 rounded hover:bg-[hsl(var(--accent))]"
        >
          <ArrowLeft size={13} />
          {t('envManagement.backToHome')}
        </Link>
        <div className="w-px h-4 bg-[hsl(var(--border))]" />
        <Sparkles size={13} className="text-[hsl(var(--primary))]" />
        <h1 className="text-[0.8125rem] font-semibold text-[hsl(var(--foreground))] truncate">
          {t('envManagement.pageTitle')}
        </h1>
      </header>

      {/* ── Body — shell with CompactMetaBar + canvas/stage view ── */}
      <div className="flex-1 min-h-0 flex flex-col">
        <EnvManagementShell onSaved={handleSaved} />
      </div>
    </div>
  );
}
