'use client';

/**
 * /environments — dedicated page for the visual 21-stage environment
 * builder (cycle 20260427_2).
 *
 * Replaces the dev-mode "Library (NEW)" tab. The shell component
 * (EnvManagementShell) hosts the canvas + side panel + global section;
 * this page wrapper owns the route-level chrome (back link to /, page
 * header) and the post-save navigation.
 *
 * Note: PR-1 of cycle 20260427_2 just relocates the surface as-is.
 * PR-2 will redesign the layout so the 21-stage canvas is visually
 * primary and metadata / global settings get out of the way.
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
    // Hand off to the existing Library catalog so the user can see
    // their new env in context. requestOpenEnvDrawer queues the env
    // for the detail drawer; navigating back to / + activeTab='library'
    // pops it open.
    requestOpenEnvDrawer(newEnvId);
    router.push('/');
  };

  return (
    <div className="min-h-screen bg-[hsl(var(--background))] text-[hsl(var(--foreground))] flex flex-col">
      {/* ── Page header (own chrome — separate from app's TabNavigation) ── */}
      <header className="flex items-center h-14 px-4 md:px-6 border-b border-[hsl(var(--border))] bg-[hsl(var(--card))] shrink-0 gap-3">
        <Link
          href="/"
          className="inline-flex items-center gap-1.5 text-[0.8125rem] text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))] no-underline transition-colors px-2 py-1 rounded-md hover:bg-[hsl(var(--accent))]"
        >
          <ArrowLeft size={14} />
          {t('envManagement.backToHome')}
        </Link>
        <div className="w-px h-5 bg-[hsl(var(--border))]" />
        <Sparkles size={14} className="text-[hsl(var(--primary))]" />
        <div className="min-w-0">
          <h1 className="text-[0.9375rem] font-semibold text-[hsl(var(--foreground))] truncate leading-tight">
            {t('envManagement.pageTitle')}
          </h1>
          <p className="text-[0.6875rem] text-[hsl(var(--muted-foreground))] truncate leading-tight">
            {t('envManagement.pageSubtitle')}
          </p>
        </div>
      </header>

      {/* ── Body — the existing shell component ── */}
      <div className="flex-1 min-h-0 flex flex-col">
        <EnvManagementShell onSaved={handleSaved} />
      </div>
    </div>
  );
}
