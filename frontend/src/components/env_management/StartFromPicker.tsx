'use client';

/**
 * StartFromPicker — welcome-state picker that lets the user start a
 * draft from one of three places:
 *   - blank (existing newDraft())
 *   - an existing env in the library
 *   - a "preset" tagged env (filtered to those tagged with "preset")
 *
 * Renders inline below the welcome header in TopBar's empty state.
 */

import { useEffect, useMemo, useState } from 'react';
import { Boxes, Plus, Sparkles, Star } from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import { environmentApi } from '@/lib/environmentApi';
import { useEnvironmentDraftStore } from '@/store/useEnvironmentDraftStore';
import type { EnvironmentSummary } from '@/types/environment';
import { ActionButton } from '@/components/layout';

export default function StartFromPicker() {
  const { t } = useI18n();
  const newDraft = useEnvironmentDraftStore((s) => s.newDraft);
  const newDraftFromExisting = useEnvironmentDraftStore(
    (s) => s.newDraftFromExisting,
  );
  const seeding = useEnvironmentDraftStore((s) => s.seeding);

  const [envs, setEnvs] = useState<EnvironmentSummary[]>([]);
  const [loading, setLoading] = useState(false);
  const [showAll, setShowAll] = useState(false);

  useEffect(() => {
    let cancelled = false;
    setLoading(true);
    environmentApi
      .list()
      .then((res) => {
        if (!cancelled) setEnvs(res);
      })
      .catch(() => {
        /* picker silently degrades to "blank only" */
      })
      .finally(() => {
        if (!cancelled) setLoading(false);
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const presetEnvs = useMemo(
    () => envs.filter((e) => (e.tags || []).includes('preset')),
    [envs],
  );
  const nonPresetEnvs = useMemo(
    () => envs.filter((e) => !(e.tags || []).includes('preset')),
    [envs],
  );

  const visibleNonPresets = showAll ? nonPresetEnvs : nonPresetEnvs.slice(0, 6);

  const handleBlank = async () => {
    try {
      await newDraft();
    } catch {
      /* error surfaces via store */
    }
  };

  const handleFromExisting = async (id: string) => {
    try {
      await newDraftFromExisting(id);
    } catch {
      /* error surfaces via store */
    }
  };

  return (
    <div className="flex flex-col gap-4">
      {/* ── Blank ── */}
      <div className="flex items-center gap-3 p-3 rounded-md border border-[hsl(var(--border))] bg-[hsl(var(--card))]">
        <div className="w-10 h-10 rounded-md bg-gradient-to-br from-blue-500/15 to-purple-500/15 flex items-center justify-center shrink-0">
          <Plus className="w-5 h-5 text-[hsl(var(--primary))]" />
        </div>
        <div className="flex-1 min-w-0">
          <div className="text-[0.8125rem] font-semibold text-[hsl(var(--foreground))]">
            {t('envManagement.startFrom.blankTitle')}
          </div>
          <div className="text-[0.7rem] text-[hsl(var(--muted-foreground))] mt-0.5">
            {t('envManagement.startFrom.blankDesc')}
          </div>
        </div>
        <ActionButton
          variant="primary"
          icon={Plus}
          onClick={handleBlank}
          disabled={seeding}
          spinIcon={seeding}
        >
          {seeding ? t('envManagement.seeding') : t('envManagement.newDraft')}
        </ActionButton>
      </div>

      {/* ── Presets (tagged with "preset") ── */}
      {presetEnvs.length > 0 && (
        <div>
          <div className="flex items-center gap-1 text-[0.7rem] font-semibold uppercase tracking-wider text-[hsl(var(--muted-foreground))] mb-2">
            <Star className="w-3 h-3" />
            {t('envManagement.startFrom.presetsTitle')}
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2">
            {presetEnvs.map((env) => (
              <PresetCard
                key={env.id}
                env={env}
                onPick={() => handleFromExisting(env.id)}
                disabled={seeding}
                accent="violet"
              />
            ))}
          </div>
        </div>
      )}

      {/* ── Existing envs ── */}
      {nonPresetEnvs.length > 0 && (
        <div>
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-1 text-[0.7rem] font-semibold uppercase tracking-wider text-[hsl(var(--muted-foreground))]">
              <Boxes className="w-3 h-3" />
              {t('envManagement.startFrom.existingTitle', {
                n: String(nonPresetEnvs.length),
              })}
            </div>
            {nonPresetEnvs.length > 6 && (
              <button
                type="button"
                onClick={() => setShowAll((v) => !v)}
                className="text-[0.7rem] text-[hsl(var(--primary))] hover:underline"
              >
                {showAll
                  ? t('envManagement.startFrom.collapse')
                  : t('envManagement.startFrom.showAll', {
                      n: String(nonPresetEnvs.length),
                    })}
              </button>
            )}
          </div>
          <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-2">
            {visibleNonPresets.map((env) => (
              <PresetCard
                key={env.id}
                env={env}
                onPick={() => handleFromExisting(env.id)}
                disabled={seeding}
                accent="blue"
              />
            ))}
          </div>
        </div>
      )}

      {!loading && envs.length === 0 && (
        <p className="text-[0.7rem] text-[hsl(var(--muted-foreground))] italic">
          {t('envManagement.startFrom.empty')}
        </p>
      )}
    </div>
  );
}

function PresetCard({
  env,
  onPick,
  disabled,
  accent,
}: {
  env: EnvironmentSummary;
  onPick: () => void;
  disabled: boolean;
  accent: 'violet' | 'blue';
}) {
  const { t } = useI18n();
  const accentClass =
    accent === 'violet'
      ? 'border-violet-500/30 hover:border-violet-500'
      : 'border-[hsl(var(--border))] hover:border-[hsl(var(--primary))]';
  return (
    <button
      type="button"
      onClick={onPick}
      disabled={disabled}
      className={`group flex flex-col gap-1 p-3 rounded-md border bg-[hsl(var(--card))] hover:bg-[hsl(var(--accent))] transition-colors text-left disabled:opacity-50 disabled:cursor-not-allowed ${accentClass}`}
    >
      <div className="flex items-center gap-1.5">
        <Sparkles
          className={`w-3.5 h-3.5 shrink-0 ${
            accent === 'violet' ? 'text-violet-500' : 'text-[hsl(var(--primary))]'
          }`}
        />
        <span className="text-[0.8125rem] font-semibold text-[hsl(var(--foreground))] truncate">
          {env.name}
        </span>
      </div>
      <p className="text-[0.7rem] text-[hsl(var(--muted-foreground))] line-clamp-2 leading-relaxed">
        {env.description || t('envManagement.startFrom.noDescription')}
      </p>
      {env.tags && env.tags.length > 0 && (
        <div className="flex flex-wrap gap-1 mt-1">
          {env.tags.slice(0, 3).map((tag) => (
            <span
              key={tag}
              className="text-[0.625rem] px-1.5 py-0.5 rounded-full bg-[hsl(var(--accent))] text-[hsl(var(--muted-foreground))]"
            >
              {tag}
            </span>
          ))}
        </div>
      )}
      <div className="text-[0.625rem] text-[hsl(var(--primary))] mt-1 opacity-0 group-hover:opacity-100 transition-opacity">
        {t('envManagement.startFrom.useThis')} →
      </div>
    </button>
  );
}
