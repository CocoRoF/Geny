'use client';

/**
 * EnvManagementShell — visual 21-stage environment builder body.
 *
 * Hosted by /app/environments/page.tsx (cycle 20260427_2). The page
 * wrapper owns the route-level chrome (back link, page header, save
 * navigation); this shell owns the editor body itself.
 *
 * Cycle 20260427_1 PR-A scaffold (composition unchanged in 20260427_2):
 *
 *   ┌─ TabShell ─────────────────────────────────────────┐
 *   │ TopBar (name/desc/tags/Save/Discard)               │
 *   │ GlobalSection (model + pipeline + tools + ext.)    │
 *   │ ┌───────────────────┬─ StageEditorPanel ─────────┐ │
 *   │ │ PipelineCanvas     │ (slide-in side panel)     │ │
 *   │ │ (21-stage view)    │  - generic editor (PR-A)  │ │
 *   │ │                    │  - curated (PR-B…E)       │ │
 *   │ └────────────────────┴───────────────────────────┘ │
 *   └────────────────────────────────────────────────────┘
 *
 * The draft lives in useEnvironmentDraftStore — discarded when the
 * user navigates away (with confirm if dirty). Save posts the full
 * manifest in one call via mode=blank + manifest_override (cycle
 * 20260427_1 backend patch).
 *
 * UX redesign (canvas-first layout) lands in cycle 20260427_2 PR-2.
 */

import { useEffect, useState } from 'react';
import { Sparkles } from 'lucide-react';
import { TabShell } from '@/components/layout';
import { useI18n } from '@/lib/i18n';
import { useEnvironmentDraftStore } from '@/store/useEnvironmentDraftStore';
import PipelineCanvas from '@/components/session-env/PipelineCanvas';
import TopBar from './TopBar';
import GlobalSection from './GlobalSection';
import StageEditorPanel from './StageEditorPanel';

export interface EnvManagementShellProps {
  /** Called after a successful Save with the new env id. The page
   *  wrapper decides where to send the user (back to /, into a
   *  detail drawer, etc.). */
  onSaved?: (newEnvId: string) => void;
}

export default function EnvManagementShell({
  onSaved,
}: EnvManagementShellProps = {}) {
  const { t } = useI18n();
  const draft = useEnvironmentDraftStore((s) => s.draft);
  const stageDirty = useEnvironmentDraftStore((s) => s.stageDirty);
  const isDirty = useEnvironmentDraftStore((s) => s.isDirty);
  const resetDraft = useEnvironmentDraftStore((s) => s.resetDraft);

  const [selectedOrder, setSelectedOrder] = useState<number | null>(null);

  // Beforeunload guard (browser tab close while dirty).
  useEffect(() => {
    const handler = (e: BeforeUnloadEvent) => {
      if (isDirty()) {
        e.preventDefault();
        // Browsers ignore the message string but still show the prompt.
        e.returnValue = '';
      }
    };
    window.addEventListener('beforeunload', handler);
    return () => window.removeEventListener('beforeunload', handler);
  }, [isDirty]);

  // Component-unmount discard: clear the draft when the user navigates
  // away from the tab. The TopBar already gates the Discard button on a
  // confirm prompt; the parent activeTab change is gated by
  // useAppStore.setActiveTab + this hook.
  useEffect(() => {
    return () => {
      // Only auto-clear if we got here without a save (saveDraft already
      // resets). isDirty() being true here means "navigating away with
      // unsaved edits" — the beforeunload guard catches browser close,
      // but in-app navigation falls through. Keep the draft so the user
      // returning to the tab still sees their work; clear only on
      // explicit Discard via TopBar.
    };
  }, []);

  // Selecting a stage that no longer exists (e.g. after Save reset)
  // should drop the selection.
  useEffect(() => {
    if (!draft && selectedOrder != null) {
      setSelectedOrder(null);
    }
  }, [draft, selectedOrder]);

  const handleSaved = (newEnvId: string) => {
    setSelectedOrder(null);
    resetDraft();
    onSaved?.(newEnvId);
  };

  return (
    <TabShell
      title={t('envManagement.title')}
      subtitle={t('envManagement.subtitle')}
      icon={Sparkles}
      bodyPadding="none"
      bodyScroll="none"
    >
      <div className="flex flex-col h-full min-h-0">
        <TopBar onSaved={handleSaved} />

        {draft && <GlobalSection />}

        {/* Canvas + side panel */}
        <div className="flex-1 min-h-0 flex">
          <div className="flex-1 min-w-0 flex flex-col">
            {!draft ? (
              <div className="flex-1 flex items-center justify-center text-[0.875rem] text-[hsl(var(--muted-foreground))]">
                <div className="text-center max-w-[420px] p-8">
                  <Sparkles className="w-10 h-10 mx-auto mb-3 opacity-40 text-[hsl(var(--primary))]" />
                  <p className="font-medium mb-2 text-[hsl(var(--foreground))]">
                    {t('envManagement.canvasPlaceholderTitle')}
                  </p>
                  <p className="text-[0.8125rem] leading-relaxed">
                    {t('envManagement.canvasPlaceholderHint')}
                  </p>
                </div>
              </div>
            ) : (
              <PipelineCanvas
                stages={draft.stages}
                selectedOrder={selectedOrder}
                onSelectStage={setSelectedOrder}
                dirtyOrders={stageDirty}
              />
            )}
          </div>

          {selectedOrder != null && draft && (
            <StageEditorPanel
              order={selectedOrder}
              onClose={() => setSelectedOrder(null)}
            />
          )}
        </div>
      </div>
    </TabShell>
  );
}
