'use client';

import { useState, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { useAppStore } from '@/store/useAppStore';
import { ttsApi, type VoiceProfile } from '@/lib/api';
import InfoTooltip from '@/components/ui/InfoTooltip';
import Selector from '@/components/ui/Selector';
import { X } from 'lucide-react';
import { useI18n } from '@/lib/i18n';
import { useVTuberStore } from '@/store/useVTuberStore';
import type { CreateAgentRequest } from '@/types';

interface Props { onClose: () => void; }

// This used to ask which ENVIRONMENT to build the agent from, and derived
// the role from whichever one you picked. There is one environment now — the
// pipeline every agent runs — so it asks the thing it was really asking:
// what KIND of agent this is. A persona gets its character, its companion
// sub-agent and (below) an avatar and a voice; a worker gets none of that and
// every tool. Everything else is attached to the session afterwards, and can
// be changed without rebuilding anything.


export default function CreateSessionModal({ onClose }: Props) {
  const { createSession } = useAppStore();
  const { t } = useI18n();

  const [sessionName, setSessionName] = useState('');
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState('');
  const [role, setRole] = useState<'developer' | 'vtuber'>('developer');
  const [selectedAvatar, setSelectedAvatar] = useState('');
  const [selectedTtsProfile, setSelectedTtsProfile] = useState('');
  const [ttsProfiles, setTtsProfiles] = useState<VoiceProfile[]>([]);
  const [ttsProfilesLoaded, setTtsProfilesLoaded] = useState(false);
  const [ttsEnabled, setTtsEnabled] = useState(false);
  const { models: avatarModels, modelsLoaded: avatarsLoaded, fetchModels: fetchAvatarModels, assignModel: assignAvatar } = useVTuberStore();

  const isPersona = role === 'vtuber';

  // Lazy-load avatar models + TTS profiles only when a VTuber env is
  // selected (they drive the VTuber-only quick-assign selectors).
  useEffect(() => {
    if (!isPersona) return;
    if (!avatarsLoaded) fetchAvatarModels();
    if (!ttsProfilesLoaded) {
      Promise.all([
        ttsApi.engines().catch((): { engines: string[]; default: string } => ({ engines: [], default: '' })),
        ttsApi.listProfiles().catch((): { profiles: VoiceProfile[] } => ({ profiles: [] })),
      ]).then(([enginesRes, profilesRes]) => {
        const hasTtsEngine = (enginesRes.engines?.length ?? 0) > 0;
        setTtsEnabled(hasTtsEngine);
        setTtsProfiles(profilesRes.profiles || []);
        setTtsProfilesLoaded(true);
      });
    }
  }, [isPersona, avatarsLoaded, fetchAvatarModels, ttsProfilesLoaded]);

  const handleSubmit = async () => {

    setSubmitting(true);
    setError('');
    try {
      // The role is the whole choice. The server attaches what follows from
      // it — a persona and a companion for a VTuber, every tool for a worker
      // — and fills in every default we no longer send.
      const payload: CreateAgentRequest = {
        session_name: sessionName,
        role,
      };
      const session = await createSession(payload);
      // Post-create VTuber quick-assign — avatar + TTS profile. Both
      // are best-effort: the session is already created, so failures
      // just defer assignment to the session UI.
      if (isPersona && session?.session_id) {
        if (selectedAvatar) {
          try {
            await assignAvatar(session.session_id, selectedAvatar);
          } catch {
            console.warn('Avatar assignment failed, can be assigned manually later');
          }
        }
        if (selectedTtsProfile) {
          try {
            await ttsApi.assignSessionProfile(session.session_id, selectedTtsProfile);
          } catch {
            console.warn('TTS profile assignment failed, can be assigned manually later');
          }
        }
      }
      onClose();
    } catch (e: unknown) {
      setError(e instanceof Error ? e.message : t('createSession.failedToCreate'));
    } finally {
      setSubmitting(false);
    }
  };

  return createPortal(
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/60 backdrop-blur-sm" onClick={onClose}>
      <div className="bg-[var(--bg-secondary)] border border-[var(--border-color)] rounded-lg w-full max-w-[480px] mx-4 max-h-[85vh] flex flex-col shadow-[var(--shadow-lg)]" onClick={e => e.stopPropagation()}>
        {/* Header */}
        <div className="flex justify-between items-center py-3 md:py-4 px-4 md:px-6 border-b border-[var(--border-color)]">
          <h3 className="text-[1rem] font-semibold text-[var(--text-primary)]">{t('createSession.title')}</h3>
          <button className="flex items-center justify-center w-8 h-8 rounded-[var(--border-radius)] bg-transparent border-none text-[var(--text-muted)] hover:bg-[var(--bg-hover)] hover:text-[var(--text-primary)] cursor-pointer" onClick={onClose}><X size={16} /></button>
        </div>

        {/* Body */}
        <div className="flex-1 overflow-y-auto px-4 md:px-6 py-4 md:py-5 flex flex-col gap-4">
          {error && <div className="text-[0.8125rem] text-[var(--danger-color)] bg-[rgba(239,68,68,0.1)] p-2.5 rounded-[6px] mb-2">{error}</div>}

          {/* Session Name */}
          <div className="flex flex-col gap-1.5">
            <label className="text-[0.8125rem] font-medium text-[var(--text-secondary)]">{t('createSession.sessionName')}</label>
            <input
              className="w-full py-2.5 px-3 bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-[var(--border-radius)] text-[0.875rem] text-[var(--text-primary)] placeholder:text-[var(--text-muted)] transition-[border-color] focus:outline-none focus:border-[var(--primary-color)] focus:shadow-[0_0_0_3px_rgba(59,130,246,0.15)]"
              placeholder={t('createSession.sessionNamePlaceholder')}
              value={sessionName} onChange={e => setSessionName(e.target.value)} />
          </div>

          {/* What kind of agent. The only choice that has to be made now —
              everything else attaches to the session afterwards. */}
          <div className="flex flex-col gap-1.5">
            <label className="text-[0.8125rem] font-medium text-[var(--text-secondary)] inline-flex items-center gap-1.5">
              {t('createSession.kind')}
              <InfoTooltip text={t('createSession.kindHelp')} />
            </label>
            <Selector
              variant="field"
              ariaLabel={t('createSession.kind')}
              value={role}
              onChange={(next) => setRole(next as 'developer' | 'vtuber')}
              items={[
                { id: 'developer', label: t('createSession.kindWorker') },
                { id: 'vtuber', label: t('createSession.kindPersona') },
              ]}
            />
            <small className="text-[0.75rem] text-[var(--text-muted)] mt-0.5">
              {t('createSession.kindHelp')}
            </small>
          </div>

          {/* Avatar (VTuber env only) */}
          {isPersona && (
            <div className="flex flex-col gap-1.5">
              <label className="text-[0.8125rem] font-medium text-[var(--text-secondary)] inline-flex items-center gap-1.5">{t('createSession.avatar')} <InfoTooltip text={t('createSession.avatarHelp')} /></label>
              <Selector
                variant="field"
                ariaLabel={t('createSession.avatar')}
                value={selectedAvatar}
                onChange={setSelectedAvatar}
                items={[
                  { id: '', label: avatarsLoaded ? t('createSession.avatarNone') : t('createSession.avatarLoading') },
                  ...avatarModels.map(m => ({ id: m.name, label: m.display_name || m.name })),
                ]}
              />
            </div>
          )}

          {/* TTS Voice Profile (VTuber env only) */}
          {isPersona && (
            <div className="flex flex-col gap-1.5">
              <label className="text-[0.8125rem] font-medium text-[var(--text-secondary)] inline-flex items-center gap-1.5">{t('createSession.ttsProfile')} <InfoTooltip text={t('createSession.ttsProfileHelp')} /></label>
              {ttsProfilesLoaded && !ttsEnabled ? (
                <div className="w-full py-2.5 px-3 bg-[var(--bg-primary)] border border-[var(--border-color)] rounded-[var(--border-radius)] text-[0.8125rem] text-[var(--text-muted)] opacity-60">
                  {t('createSession.ttsDisabled')}
                </div>
              ) : (
                <Selector
                  variant="field"
                  ariaLabel={t('createSession.ttsProfile')}
                  value={selectedTtsProfile}
                  onChange={setSelectedTtsProfile}
                  items={[
                    { id: '', label: ttsProfilesLoaded ? t('createSession.ttsProfileNone') : t('createSession.ttsProfileLoading') },
                    ...ttsProfiles.map(p => ({ id: p.name, label: p.display_name || p.name })),
                  ]}
                />
              )}
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="flex justify-end items-center gap-3 py-3 md:py-4 px-4 md:px-6 border-t border-[var(--border-color)]">
          <button className="py-2 px-4 bg-transparent hover:bg-[var(--bg-hover)] text-[var(--text-secondary)] text-[0.8125rem] font-medium rounded-[var(--border-radius)] cursor-pointer transition-all duration-150 border border-[var(--border-color)]" onClick={onClose}>{t('common.cancel')}</button>
          <button className="py-2 px-4 bg-[var(--primary-color)] hover:bg-[var(--primary-hover)] text-white text-[0.8125rem] font-medium rounded-[var(--border-radius)] cursor-pointer transition-all duration-150 border-none disabled:opacity-50 disabled:cursor-not-allowed" onClick={handleSubmit} disabled={submitting}>
            {submitting ? t('createSession.creating') : t('createSession.createSession')}
          </button>
        </div>
      </div>
    </div>,
    document.body,
  );
}
