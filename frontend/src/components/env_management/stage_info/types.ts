/**
 * StageInfoExtras — optional supplementary content per stage that goes
 * beyond what stageMetadata.ts already provides.
 *
 * stageMetadata supplies the BASE content (description, detailedDescription,
 * technicalBehavior bullets, strategies, architectureNotes) — that's
 * already enough for a functioning detail modal across all 21 stages.
 *
 * Extras let curated stages add deeper sections without bloating the
 * shared metadata file:
 *   - useCases: "you would enable this stage if..."
 *   - configurations: example presets the operator can copy/borrow
 *   - codeReferences: executor / Geny source files for the curious
 *   - pitfalls: common mistakes / gotchas
 *   - relatedStages: stage orders that interact with this one
 *
 * Locales: each extras file exports a `getExtras(locale)` that picks the
 * right language pack. Both en and ko must be supplied in lockstep.
 */

import type { Locale } from '@/lib/i18n';

export interface StageUseCase {
  /** Short title — "When to disable" / "Heavy validation needed" / etc. */
  title: string;
  /** Body paragraph explaining the case + recommendation. */
  body: string;
}

export interface StageConfigExample {
  /** Display name — "Minimal echo agent", "Tool-using assistant", … */
  name: string;
  /** One-line summary. */
  summary: string;
  /** Optional list of bullet points describing what's set. */
  highlights?: string[];
}

export interface StageCodeRef {
  /** Display label, e.g. "geny-executor / s06_api/strategy.py". */
  label: string;
  /** Optional human description — what reading this file teaches you. */
  description?: string;
}

export interface StagePitfall {
  /** "Forgetting to set X", "Overlapping Y", … */
  title: string;
  body: string;
}

export interface StageRelatedStage {
  order: number;
  /** How / why this stage relates to the current one. */
  reason: string;
}

export interface StageInfoExtrasContent {
  useCases?: StageUseCase[];
  configurations?: StageConfigExample[];
  codeReferences?: StageCodeRef[];
  pitfalls?: StagePitfall[];
  relatedStages?: StageRelatedStage[];
}

/**
 * The shape every stage_info extras module exports. The function takes
 * the active locale and returns the localized content (or null if this
 * stage has no extras yet — the modal will render base metadata only).
 */
export type StageInfoExtrasFactory = (
  locale: Locale,
) => StageInfoExtrasContent | null;
