'use client';

/**
 * StageActiveCard — the single, canonical "이 단계 실행" toggle that
 * appears as the first card under every stage's header (curated or
 * generic). Title text is fixed (`runThisStage`); per-stage desc text
 * comes from `envManagement.stage{NN}.activeDesc` so each stage can
 * still explain what disabling it actually does.
 */

import { useI18n } from '@/lib/i18n';
import { Switch } from '@/components/ui/switch';
import { useEnvironmentDraftStore } from '@/store/useEnvironmentDraftStore';
import type { StageManifestEntry } from '@/types/environment';

interface Props {
  order: number;
  entry: StageManifestEntry;
}

export default function StageActiveCard({ order, entry }: Props) {
  const { t } = useI18n();
  const patchStage = useEnvironmentDraftStore((s) => s.patchStage);

  const descKey = `envManagement.stage${String(order).padStart(2, '0')}.activeDesc`;
  const desc = t(descKey);
  const fallbackDesc =
    desc === descKey ? t('envManagement.stageActiveDesc') : desc;

  return (
    <section className="flex items-center justify-between gap-3 p-3 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--card))]">
      <div className="min-w-0">
        <div className="text-[0.8125rem] font-semibold text-[hsl(var(--foreground))]">
          {t('envManagement.runThisStage')}
        </div>
        <div className="text-[0.6875rem] text-[hsl(var(--muted-foreground))] mt-0.5">
          {fallbackDesc}
        </div>
      </div>
      <Switch
        checked={!!entry.active}
        onCheckedChange={(checked) => patchStage(order, { active: checked })}
      />
    </section>
  );
}
