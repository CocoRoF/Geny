'use client';

/**
 * sessionEnvTarget — which session the tool roster should render.
 *
 * Defaults to the app's globally-selected session. The override exists for a
 * VTuber, whose linked Sub-Worker has its own tools: a caller can put the
 * pair's other side in the context so the roster shows it without disturbing
 * the app-wide selection (the sidebar and the chat stay on the VTuber).
 */

import { createContext, useContext } from 'react';
import { useAppStore } from '@/store/useAppStore';

/** Override session id, or null = use the globally-selected session. */
export const SessionEnvTargetContext = createContext<string | null>(null);

/** The session whose tools to show: the context override when present, else
 * the app's selected session. */
export function useSessionEnvTargetId(): string | null {
  const override = useContext(SessionEnvTargetContext);
  const selected = useAppStore((s) => s.selectedSessionId);
  return override ?? selected;
}
