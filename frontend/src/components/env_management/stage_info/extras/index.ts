/**
 * Stage extras registry — maps a stage order to its extras factory.
 *
 * Stages without an entry here render base metadata only (which is
 * already substantial — description + detailedDescription + technical
 * behaviour + strategies + architecture notes from stageMetadata.ts).
 *
 * Future PRs add factories for the remaining 18 stages.
 */

import type { StageInfoExtrasFactory } from '../types';
import { stage01Extras } from './Stage01InputExtras';
import { stage06Extras } from './Stage06ApiExtras';
import { stage18Extras } from './Stage18MemoryExtras';

export const STAGE_EXTRAS: Record<number, StageInfoExtrasFactory> = {
  1: stage01Extras,
  6: stage06Extras,
  18: stage18Extras,
};
