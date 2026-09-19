/**
 * The harness of one agent, as the server reports it.
 *
 * Read from the session's live pipeline — not from the environment it was
 * built from, because Geny declares placeholders there and installs the real
 * implementations at build time. `source` is what makes the difference
 * legible: a value labelled `runtime` is one Geny sets for every session, and
 * changing it needs the owner's own overlay to beat it.
 */

/** Where a live value came from. */
export type HarnessSource = 'default' | 'manifest' | 'runtime' | 'session';

/** Which screen a control belongs on. A claim about the reader, not the code. */
export type HarnessTier = 'basic' | 'advanced' | 'locked';

export interface HarnessOption {
  name: string;
  description: string;
  schema?: { fields: HarnessField[] } | null;
  /** This is the instance Geny installed, not a name the stage's registry
   *  knows. Present so the dropdown can render its own current value —
   *  without it the control falls back to the first option and the page
   *  reports something other than what runs. */
  installed?: boolean;
}

export interface HarnessField {
  name: string;
  type: string;
  label: string;
  description: string;
  default: unknown;
  required: boolean;
  minValue: number | null;
  maxValue: number | null;
  options: { value: string; label: string }[] | null;
  itemType: string | null;
}

export interface HarnessSlot {
  slot: string;
  /** One implementation name, or a chain's members in order. */
  value: string | string[];
  isChain: boolean;
  options: HarnessOption[];
  config: Record<string, unknown>;
  description: string;
  tier: HarnessTier;
  /** i18n key for the question a basic slot answers. */
  question: string | null;
  /** i18n key for why a locked slot takes no input. */
  lockedBecause: string | null;
  /** i18n key naming what Geny installs here for every session. */
  installedBy: string | null;
  source: HarnessSource;
}

export interface HarnessStage {
  order: number;
  name: string;
  category: string;
  group: string;
  active: boolean;
  slots: HarnessSlot[];
}

export interface HarnessBudgets {
  maxIterations?: { value: number | null; source: string };
  contextWindow?: {
    value: number | null;
    source: string;
    /** What each hop in the route can hold. The smallest one binds. */
    perHop?: { label: string; model: string; window: number | null }[];
  };
  costCeiling?: { value: number | null; source: string; countsOnly?: string };
}

export interface HarnessView {
  stages: HarnessStage[];
  budgets: HarnessBudgets;
}
