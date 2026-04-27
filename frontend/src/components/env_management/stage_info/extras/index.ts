/**
 * Stage extras registry — maps a stage order to its extras factory.
 *
 * As of cycle 20260427_3 PR-2 every one of the 21 stages has a
 * curated extras module. The base stageMetadata.ts content remains
 * the foundation; extras layer use cases / configurations / pitfalls /
 * code references / related stages on top.
 */

import type { StageInfoExtrasFactory } from '../types';
import { stage01Extras } from './Stage01InputExtras';
import { stage02Extras } from './Stage02ContextExtras';
import { stage03Extras } from './Stage03SystemExtras';
import { stage04Extras } from './Stage04GuardExtras';
import { stage05Extras } from './Stage05CacheExtras';
import { stage06Extras } from './Stage06ApiExtras';
import { stage07Extras } from './Stage07TokenExtras';
import { stage08Extras } from './Stage08ThinkExtras';
import { stage09Extras } from './Stage09ParseExtras';
import { stage10Extras } from './Stage10ToolsExtras';
import { stage11Extras } from './Stage11ToolReviewExtras';
import { stage12Extras } from './Stage12AgentExtras';
import { stage13Extras } from './Stage13TaskRegistryExtras';
import { stage14Extras } from './Stage14EvaluateExtras';
import { stage15Extras } from './Stage15HitlExtras';
import { stage16Extras } from './Stage16LoopExtras';
import { stage17Extras } from './Stage17EmitExtras';
import { stage18Extras } from './Stage18MemoryExtras';
import { stage19Extras } from './Stage19SummarizeExtras';
import { stage20Extras } from './Stage20PersistExtras';
import { stage21Extras } from './Stage21YieldExtras';

export const STAGE_EXTRAS: Record<number, StageInfoExtrasFactory> = {
  1: stage01Extras,
  2: stage02Extras,
  3: stage03Extras,
  4: stage04Extras,
  5: stage05Extras,
  6: stage06Extras,
  7: stage07Extras,
  8: stage08Extras,
  9: stage09Extras,
  10: stage10Extras,
  11: stage11Extras,
  12: stage12Extras,
  13: stage13Extras,
  14: stage14Extras,
  15: stage15Extras,
  16: stage16Extras,
  17: stage17Extras,
  18: stage18Extras,
  19: stage19Extras,
  20: stage20Extras,
  21: stage21Extras,
};
