'use client';

/**
 * Where the model comes from, said once, wherever someone looks for it.
 *
 * An environment used to name a provider and a model. It does not any more:
 * Stage 6 runs the router, and the router asks the session's account route.
 * Leaving the old pickers in place would have been worse than removing them —
 * the router replaces the model on every call, so a value set here would look
 * saved and change nothing.
 *
 * The environment still decides everything it should: which tools the agent
 * has, its persona, its permissions, its memory. Just not who answers.
 */

import { ArrowUpRight, Route } from 'lucide-react';

import { useI18n } from '@/lib/i18n';

export function RouteNotice({ compact = false }: { compact?: boolean }) {
  const { t } = useI18n();
  return (
    <div className={`flex gap-3 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--muted))]/30 ${compact ? 'p-3' : 'p-4'}`}>
      <Route className="w-4 h-4 mt-0.5 shrink-0 text-[hsl(var(--muted-foreground))]" />
      <div className="flex flex-col gap-1.5 min-w-0">
        <span className="text-[0.8125rem] font-medium">
          {t('envManagement.route.title')}
        </span>
        <p className="text-[0.75rem] leading-relaxed text-[hsl(var(--muted-foreground))]">
          {t('envManagement.route.body')}
        </p>
        <a
          href="/?tab=settings&section=models"
          className="inline-flex items-center gap-1 text-[0.75rem] text-[hsl(var(--primary))] hover:underline"
        >
          {t('envManagement.route.link')}
          <ArrowUpRight className="w-3 h-3" />
        </a>
      </div>
    </div>
  );
}

export default RouteNotice;
