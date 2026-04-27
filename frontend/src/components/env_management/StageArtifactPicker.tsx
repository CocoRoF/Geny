'use client';

/**
 * StageArtifactPicker — compact artifact dropdown that lives in the
 * stage header (left of the "자세히" button). Hydrates the available
 * artifact list via `catalogApi.listArtifacts(order)`; until the
 * response lands, falls back to the entry's current pick + 'default'
 * so the control is always interactive.
 */

import { useEffect, useState } from 'react';
import { catalogApi } from '@/lib/environmentApi';
import { useI18n } from '@/lib/i18n';
import { useEnvironmentDraftStore } from '@/store/useEnvironmentDraftStore';
import type {
  ArtifactInfo,
  StageManifestEntry,
} from '@/types/environment';
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from '@/components/ui/select';

interface Props {
  order: number;
  entry: StageManifestEntry;
}

export default function StageArtifactPicker({ order, entry }: Props) {
  const { t } = useI18n();
  const patchStage = useEnvironmentDraftStore((s) => s.patchStage);
  const [artifacts, setArtifacts] = useState<ArtifactInfo[] | null>(null);

  useEffect(() => {
    let cancelled = false;
    catalogApi
      .listArtifacts(order)
      .then((res) => {
        if (!cancelled) setArtifacts(res.artifacts);
      })
      .catch(() => {
        /* falls back to current + default below */
      });
    return () => {
      cancelled = true;
    };
  }, [order]);

  const current = entry.artifact || 'default';
  const options = (() => {
    if (artifacts && artifacts.length > 0) {
      const names = artifacts.map((a) => a.name);
      if (!names.includes(current)) names.unshift(current);
      return names;
    }
    return Array.from(new Set([current, 'default']));
  })();

  return (
    <div className="flex items-center gap-1.5 shrink-0">
      <span className="text-[0.6875rem] font-medium text-[hsl(var(--muted-foreground))] uppercase tracking-wider">
        {t('envManagement.stageArtifact')}
      </span>
      <Select
        value={current}
        onValueChange={(v) => patchStage(order, { artifact: v })}
      >
        <SelectTrigger className="h-8 min-w-[140px] text-[0.75rem]">
          <SelectValue />
        </SelectTrigger>
        <SelectContent>
          {options.map((name) => (
            <SelectItem key={name} value={name} className="text-[0.75rem]">
              {name}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
    </div>
  );
}
