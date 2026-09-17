/**
 * Geny Mobile — the conversation, and what it takes to have one.
 *
 * Two screens on purpose. The avatar, the workspace, the voice stack and the
 * model-account plumbing all live where they belong (the web UI and the
 * desktop connector); a phone is for asking the agent something and reading
 * the answer, including the answer to something asked an hour ago from a
 * different device.
 *
 * The launch sequence is the interesting part: restore, then REFRESH the
 * token before anything else. The token lasts thirty days and the phone may
 * have been closed for twenty-nine; refreshing on every launch means a phone
 * that is opened even occasionally never meets a login screen.
 */
import { useCallback, useEffect, useState } from 'react';
import { ActivityIndicator, SafeAreaView, StatusBar, View } from 'react-native';

import {
  auth as authApi, agents as agentsApi, setUnauthorizedHandler,
  normalizeBaseUrl, type AgentSummary, type Credentials,
} from './lib/server';
import {
  loadBaseUrl, loadLastSession, loadToken, saveBaseUrl, saveLastSession, saveToken,
} from './lib/store';
import { ChatScreen } from './screens/Chat';
import { SettingsScreen } from './screens/Settings';
import { T } from './theme';

export default function App() {
  const [ready, setReady] = useState(false);
  const [baseUrl, setBaseUrl] = useState('');
  const [token, setToken] = useState<string | null>(null);
  const [displayName, setDisplayName] = useState('');
  const [sessionId, setSessionId] = useState<string | null>(null);
  const [sessionName, setSessionName] = useState('');
  const [showSettings, setShowSettings] = useState(false);

  const creds: Credentials = { baseUrl, token };

  // One place decides the session is over, so a 401 from any call lands the
  // user on the sign-in form instead of on an empty screen.
  useEffect(() => {
    setUnauthorizedHandler(() => {
      setToken(null);
      void saveToken(null);
      setShowSettings(true);
    });
  }, []);

  useEffect(() => {
    (async () => {
      const [savedUrl, savedToken, savedSession] = await Promise.all([
        loadBaseUrl(), loadToken(), loadLastSession(),
      ]);
      setBaseUrl(savedUrl);
      setSessionId(savedSession);

      if (savedUrl && savedToken) {
        try {
          // Extend before doing anything else. A phone opened once a week
          // should never be asked to sign in again.
          const refreshed = await authApi.refresh({ baseUrl: savedUrl, token: savedToken });
          setToken(refreshed.access_token);
          setDisplayName(refreshed.display_name);
          await saveToken(refreshed.access_token);
        } catch {
          // The refresh itself failing is not proof the token is dead — the
          // server may simply be unreachable right now. Keep it and let the
          // first real call decide.
          setToken(savedToken);
        }
      }
      setShowSettings(!savedUrl || !savedToken || !savedSession);
      setReady(true);
    })().catch(() => setReady(true));
  }, []);

  // Name the session for the chat header, without making the header fetch.
  useEffect(() => {
    if (!token || !sessionId || !baseUrl) return;
    agentsApi.list(creds)
      .then((list) => {
        const found = list.find((s) => s.session_id === sessionId);
        if (found) setSessionName(found.session_name || found.session_id.slice(0, 8));
      })
      .catch(() => undefined);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [token, sessionId, baseUrl]);

  const signIn = useCallback(async (username: string, password: string) => {
    const result = await authApi.login({ baseUrl, token: null }, username, password);
    setToken(result.access_token);
    setDisplayName(result.display_name);
    await saveToken(result.access_token);
  }, [baseUrl]);

  const signOut = useCallback(() => {
    setToken(null);
    setDisplayName('');
    void saveToken(null);
  }, []);

  const applyBaseUrl = useCallback((raw: string) => {
    const normalized = normalizeBaseUrl(raw);
    setBaseUrl(normalized);
    void saveBaseUrl(normalized);
  }, []);

  const pickSession = useCallback((session: AgentSummary) => {
    setSessionId(session.session_id);
    setSessionName(session.session_name || session.session_id.slice(0, 8));
    void saveLastSession(session.session_id);
    setShowSettings(false);
  }, []);

  if (!ready) {
    return (
      <View style={{ flex: 1, backgroundColor: T.bg, alignItems: 'center', justifyContent: 'center' }}>
        <ActivityIndicator color={T.accent} />
      </View>
    );
  }

  return (
    <SafeAreaView style={{ flex: 1, backgroundColor: T.bg }}>
      <StatusBar barStyle="light-content" backgroundColor={T.bg} />
      {showSettings ? (
        <SettingsScreen
          creds={creds}
          signedIn={Boolean(token)}
          displayName={displayName}
          sessionId={sessionId}
          onBaseUrl={applyBaseUrl}
          onSignIn={signIn}
          onSignOut={signOut}
          onPickSession={pickSession}
          onClose={() => setShowSettings(false)}
        />
      ) : (
        <ChatScreen
          baseUrl={baseUrl}
          sessionId={sessionId}
          sessionName={sessionName}
          token={token}
          onOpenSettings={() => setShowSettings(true)}
        />
      )}
    </SafeAreaView>
  );
}
