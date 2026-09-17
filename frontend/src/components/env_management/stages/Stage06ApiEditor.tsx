'use client';

/**
 * Stage06ApiEditor — the LLM call.
 *
 * This used to be where you picked a provider and a model. It is not any
 * more. Stage 6 runs `geny_router`, which resolves the session's account
 * route per call and replaces the model with the one that route names — so a
 * provider or model chosen here would be written to the manifest, look saved,
 * and be overwritten on every single call. A control that lies is worse than
 * no control.
 *
 * What is left is the one thing this stage still decides: whether it runs at
 * all. Off means no model call — used by headless preview pipelines and
 * almost nothing else.
 */

import { useI18n } from '@/lib/i18n';
import { useEnvironmentDraftStore } from '@/store/useEnvironmentDraftStore';
import type { StageManifestEntry } from '@/types/environment';
import { Switch } from '@/components/ui/switch';
import SectionHelpButton from '../section_help/SectionHelpButton';
import RouteNotice from '../RouteNotice';

interface Props {
  order: number;
  entry: StageManifestEntry;
}

export default function Stage06ApiEditor({ order, entry }: Props) {
  const { t } = useI18n();
  const patchStage = useEnvironmentDraftStore((s) => s.patchStage);

  return (
    <div className="flex flex-col gap-4">
      <section className="relative flex flex-col gap-3 p-4 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--card))]">
        <div className="absolute right-3 top-3 z-10">
          <SectionHelpButton helpId="stage06" />
        </div>

        <div className="flex items-start justify-between gap-4 pr-8">
          <div className="flex flex-col gap-1 min-w-0">
            <span className="text-[0.8125rem] font-medium">{t('envManagement.stage06.activeTitle')}</span>
            <p className="text-[0.75rem] leading-relaxed text-[hsl(var(--muted-foreground))]">
              {t('envManagement.stage06.activeDesc')}
            </p>
          </div>
          <Switch
            checked={entry.active !== false}
            onCheckedChange={(next) => patchStage(order, { active: next })}
          />
        </div>
      </section>

      <RouteNotice />
    </div>
  );
}
