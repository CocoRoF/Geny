'use client';

/**
 * Stage01InputEditor — curated editor for s01_input.
 *
 * Stage 1 owns input VALIDATION and NORMALIZATION — not system prompt
 * (that belongs to Stage 3, see Stage03SystemEditor). The earlier
 * version of this editor mis-placed a system prompt textarea here;
 * removed in cycle 20260427_3 once the contract was double-checked
 * against geny-executor's stages/s01_input/strategy.py.
 *
 * Stage 1 strategy slots:
 *   - Validator (DefaultValidator / PassthroughValidator /
 *     StrictValidator / SchemaValidator)
 *   - Normalizer (DefaultNormalizer / MultimodalNormalizer)
 *
 * Both pickers are presented as friendly tile choices; everything
 * else (artifact / chains / raw config) lives under Advanced.
 */

import { useEffect, useState } from 'react';
import {
  CheckCircle,
  ChevronDown,
  ChevronRight,
  ImagePlus,
} from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import { catalogApi } from '@/lib/environmentApi';
import { localizeIntrospection } from '../stage_locale';
import { useEnvironmentDraftStore } from '@/store/useEnvironmentDraftStore';
import type {
  StageIntrospection,
  StageManifestEntry,
} from '@/types/environment';
import { Switch } from '@/components/ui/switch';
import StageGenericEditor from '../StageGenericEditor';

// Friendly choice tiles for the two main slot picks. The catalog is
// the source of truth for "is this option available in the current
// build" — anything not in catalog.available_impls is greyed out.
const VALIDATOR_OPTIONS = [
  {
    id: 'DefaultValidator',
    titleKey: 'envManagement.stage01.validator.default.title',
    descKey: 'envManagement.stage01.validator.default.desc',
  },
  {
    id: 'PassthroughValidator',
    titleKey: 'envManagement.stage01.validator.passthrough.title',
    descKey: 'envManagement.stage01.validator.passthrough.desc',
  },
  {
    id: 'StrictValidator',
    titleKey: 'envManagement.stage01.validator.strict.title',
    descKey: 'envManagement.stage01.validator.strict.desc',
  },
  {
    id: 'SchemaValidator',
    titleKey: 'envManagement.stage01.validator.schema.title',
    descKey: 'envManagement.stage01.validator.schema.desc',
  },
];

const NORMALIZER_OPTIONS = [
  {
    id: 'DefaultNormalizer',
    titleKey: 'envManagement.stage01.normalizer.default.title',
    descKey: 'envManagement.stage01.normalizer.default.desc',
  },
  {
    id: 'MultimodalNormalizer',
    titleKey: 'envManagement.stage01.normalizer.multimodal.title',
    descKey: 'envManagement.stage01.normalizer.multimodal.desc',
  },
];

interface Props {
  order: number;
  entry: StageManifestEntry;
}

export default function Stage01InputEditor({ order, entry }: Props) {
  const { t } = useI18n();
  const locale = useI18n((s) => s.locale);
  const patchStage = useEnvironmentDraftStore((s) => s.patchStage);

  const [intro, setIntro] = useState<StageIntrospection | null>(null);
  const [advancedOpen, setAdvancedOpen] = useState(false);

  useEffect(() => {
    let cancelled = false;
    catalogApi
      .stage(order)
      .then((res) => {
        if (!cancelled) setIntro(localizeIntrospection(res, locale));
      })
      .catch(() => {
        /* falls back gracefully — every option just shows enabled */
      });
    return () => {
      cancelled = true;
    };
  }, [order, locale]);

  const availableValidator = new Set(
    intro?.strategy_slots?.['validator']?.available_impls ??
      VALIDATOR_OPTIONS.map((o) => o.id),
  );
  const availableNormalizer = new Set(
    intro?.strategy_slots?.['normalizer']?.available_impls ??
      NORMALIZER_OPTIONS.map((o) => o.id),
  );

  const currentValidator =
    entry.strategies?.['validator'] ??
    intro?.strategy_slots?.['validator']?.current_impl ??
    'DefaultValidator';
  const currentNormalizer =
    entry.strategies?.['normalizer'] ??
    intro?.strategy_slots?.['normalizer']?.current_impl ??
    'DefaultNormalizer';

  const setValidator = (id: string) =>
    patchStage(order, {
      strategies: { ...(entry.strategies ?? {}), validator: id },
    });
  const setNormalizer = (id: string) =>
    patchStage(order, {
      strategies: { ...(entry.strategies ?? {}), normalizer: id },
    });

  return (
    <div className="flex flex-col gap-4">
      {/* ── Active ── */}
      <section className="flex items-center justify-between gap-3 p-3 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--card))]">
        <div>
          <div className="text-[0.8125rem] font-semibold text-[hsl(var(--foreground))]">
            {t('envManagement.stage01.activeTitle')}
          </div>
          <div className="text-[0.6875rem] text-[hsl(var(--muted-foreground))]">
            {t('envManagement.stage01.activeDesc')}
          </div>
        </div>
        <Switch
          checked={!!entry.active}
          onCheckedChange={(checked) => patchStage(order, { active: checked })}
        />
      </section>

      {/* ── Validator ── */}
      <section className="flex flex-col gap-2 p-3 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--card))]">
        <header className="flex items-center gap-2">
          <CheckCircle className="w-4 h-4 text-[hsl(var(--primary))]" />
          <h4 className="text-[0.8125rem] font-semibold text-[hsl(var(--foreground))]">
            {t('envManagement.stage01.validatorTitle')}
          </h4>
        </header>
        <p className="text-[0.7rem] text-[hsl(var(--muted-foreground))] leading-relaxed">
          {t('envManagement.stage01.validatorHint')}
        </p>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
          {VALIDATOR_OPTIONS.map((opt) => {
            const available = availableValidator.has(opt.id);
            const active = currentValidator === opt.id;
            return (
              <button
                key={opt.id}
                type="button"
                disabled={!available}
                onClick={() => setValidator(opt.id)}
                className={`flex items-start gap-2 p-2.5 rounded-md border text-left transition-colors ${
                  active
                    ? 'border-[hsl(var(--primary))] bg-[hsl(var(--primary)/0.08)]'
                    : 'border-[hsl(var(--border))] bg-[hsl(var(--background))] hover:bg-[hsl(var(--accent))]'
                } ${!available ? 'opacity-40 cursor-not-allowed' : ''}`}
                title={!available ? t('envManagement.stage01.unavailable') : undefined}
              >
                <div className="min-w-0">
                  <div className="text-[0.8125rem] font-medium text-[hsl(var(--foreground))]">
                    {t(opt.titleKey)}
                  </div>
                  <div className="text-[0.6875rem] text-[hsl(var(--muted-foreground))] mt-0.5">
                    {t(opt.descKey)}
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      </section>

      {/* ── Normalizer ── */}
      <section className="flex flex-col gap-2 p-3 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--card))]">
        <header className="flex items-center gap-2">
          <ImagePlus className="w-4 h-4 text-[hsl(var(--primary))]" />
          <h4 className="text-[0.8125rem] font-semibold text-[hsl(var(--foreground))]">
            {t('envManagement.stage01.normalizerTitle')}
          </h4>
        </header>
        <p className="text-[0.7rem] text-[hsl(var(--muted-foreground))] leading-relaxed">
          {t('envManagement.stage01.normalizerHint')}
        </p>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-2">
          {NORMALIZER_OPTIONS.map((opt) => {
            const available = availableNormalizer.has(opt.id);
            const active = currentNormalizer === opt.id;
            return (
              <button
                key={opt.id}
                type="button"
                disabled={!available}
                onClick={() => setNormalizer(opt.id)}
                className={`flex items-start gap-2 p-2.5 rounded-md border text-left transition-colors ${
                  active
                    ? 'border-[hsl(var(--primary))] bg-[hsl(var(--primary)/0.08)]'
                    : 'border-[hsl(var(--border))] bg-[hsl(var(--background))] hover:bg-[hsl(var(--accent))]'
                } ${!available ? 'opacity-40 cursor-not-allowed' : ''}`}
                title={!available ? t('envManagement.stage01.unavailable') : undefined}
              >
                <div className="min-w-0">
                  <div className="text-[0.8125rem] font-medium text-[hsl(var(--foreground))]">
                    {t(opt.titleKey)}
                  </div>
                  <div className="text-[0.6875rem] text-[hsl(var(--muted-foreground))] mt-0.5">
                    {t(opt.descKey)}
                  </div>
                </div>
              </button>
            );
          })}
        </div>
      </section>

      {/* ── Advanced ── */}
      <section className="rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--card))]">
        <button
          type="button"
          onClick={() => setAdvancedOpen((v) => !v)}
          className="w-full flex items-center gap-2 px-3 py-2 text-[0.8125rem] font-semibold text-[hsl(var(--foreground))] hover:bg-[hsl(var(--accent))] transition-colors text-left"
        >
          {advancedOpen ? (
            <ChevronDown className="w-3.5 h-3.5" />
          ) : (
            <ChevronRight className="w-3.5 h-3.5" />
          )}
          {t('envManagement.stage01.advancedTitle')}
          <span className="text-[0.6875rem] font-normal text-[hsl(var(--muted-foreground))]">
            {t('envManagement.stage01.advancedHint')}
          </span>
        </button>
        {advancedOpen && (
          <div className="px-3 pb-3 border-t border-[hsl(var(--border))] pt-3">
            <StageGenericEditor order={order} entry={entry} />
          </div>
        )}
      </section>
    </div>
  );
}
