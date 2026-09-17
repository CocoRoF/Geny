/**
 * Everything that is not the conversation: the server, the account, which
 * agent this phone is talking to, and which model answers it.
 *
 * Model accounts are managed on the web or in the desktop connector — signing
 * a subscription in needs a browser sitting next to the server, and a phone is
 * the wrong place to do it. What a phone DOES need is to switch which account
 * answers, because that is a decision made mid-conversation.
 */
import { useCallback, useEffect, useState } from 'react';
import { ScrollView, Text, View } from 'react-native';

import {
  agents as agentsApi, auth as authApi, models as modelsApi,
  ServerError, type AgentRoute, type AgentSummary, type Credentials, type LlmAccount,
} from '../lib/server';
import { Button, Card, Field, Input, Notice, Pill } from '../ui';
import { T } from '../theme';

interface Props {
  creds: Credentials;
  signedIn: boolean;
  displayName: string;
  sessionId: string | null;
  onBaseUrl(url: string): void;
  onSignIn(username: string, password: string): Promise<void>;
  onSignOut(): void;
  onPickSession(session: AgentSummary): void;
  onClose(): void;
}

export function SettingsScreen({
  creds, signedIn, displayName, sessionId,
  onBaseUrl, onSignIn, onSignOut, onPickSession, onClose,
}: Props) {
  const [url, setUrl] = useState(creds.baseUrl);
  const [username, setUsername] = useState('admin');
  const [password, setPassword] = useState('');
  const [busy, setBusy] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [note, setNote] = useState<string | null>(null);

  const [sessions, setSessions] = useState<AgentSummary[]>([]);
  const [accounts, setAccounts] = useState<LlmAccount[]>([]);
  const [route, setRoute] = useState<AgentRoute | null>(null);
  const [lastRoute, setLastRoute] = useState<{ label?: string; model?: string; failedOver?: boolean } | null>(null);

  const [currentPw, setCurrentPw] = useState('');
  const [nextPw, setNextPw] = useState('');

  const run = useCallback(async (key: string, work: () => Promise<void>) => {
    setBusy(key);
    setError(null);
    setNote(null);
    try {
      await work();
    } catch (e) {
      setError(e instanceof ServerError ? e.message : String(e));
    } finally {
      setBusy(null);
    }
  }, []);

  const refresh = useCallback(async () => {
    if (!signedIn) return;
    const [list, catalogue] = await Promise.all([
      agentsApi.list(creds),
      modelsApi.list(creds).catch(() => ({ accounts: [], defaultRoute: { primary: null, fallbacks: [] } })),
    ]);
    setSessions(list);
    setAccounts(catalogue.accounts.filter((a) => a.enabled));
    if (sessionId) {
      const state = await modelsApi.route(creds, sessionId).catch(() => null);
      setRoute(state?.route ?? null);
      setLastRoute(state?.last_route ?? null);
    }
  }, [creds, signedIn, sessionId]);

  useEffect(() => { void refresh().catch(() => undefined); }, [refresh]);

  const switchModel = (accountId: string, model: string) => run('route', async () => {
    if (!sessionId) return;
    const next: AgentRoute = {
      primary: { accountId, model },
      fallbacks: accounts.filter((a) => a.id !== accountId).map((a) => ({
        accountId: a.id, model: a.modelChoices[0]?.id,
      })),
    };
    await modelsApi.setRoute(creds, sessionId, next);
    setRoute(next);
    setNote('모델을 바꿨습니다 — 대화는 그대로 이어집니다.');
  });

  const primary = route?.primary ?? null;

  return (
    <ScrollView contentContainerStyle={{ padding: 14, gap: 14, paddingBottom: 40 }}>
      <View style={{ flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between' }}>
        <Text style={{ color: T.text, fontSize: 18, fontWeight: '700' }}>설정</Text>
        <Button label="닫기" onPress={onClose} />
      </View>

      {error ? <Notice text={error} /> : null}
      {note ? <Notice text={note} tone="muted" /> : null}

      <Card title="서버">
        <Field label="주소">
          <Input
            value={url}
            onChangeText={setUrl}
            placeholder="geny.example.com"
            autoCapitalize="none"
            autoCorrect={false}
            keyboardType="url"
          />
        </Field>
        <Button label="저장" onPress={() => onBaseUrl(url)} />
      </Card>

      <Card title="계정">
        {signedIn ? (
          <>
            <Pill text={`${displayName || 'admin'} 로 로그인됨`} tone="ok" />
            <Button label="로그아웃" tone="danger" onPress={onSignOut} />
            <View style={{ height: 1, backgroundColor: T.border, marginVertical: 4 }} />
            <Field label="지금 비밀번호">
              <Input value={currentPw} onChangeText={setCurrentPw} secureTextEntry />
            </Field>
            <Field label="새 비밀번호">
              <Input value={nextPw} onChangeText={setNextPw} secureTextEntry />
            </Field>
            <Text style={{ color: T.muted, fontSize: 12 }}>
              바꾸면 다른 기기는 모두 로그아웃됩니다. 이 폰은 그대로 유지됩니다.
            </Text>
            <Button
              label="비밀번호 변경"
              busy={busy === 'password'}
              disabled={!currentPw || !nextPw}
              onPress={() => run('password', async () => {
                await authApi.changePassword(creds, currentPw, nextPw);
                setCurrentPw('');
                setNextPw('');
                setNote('비밀번호를 바꿨습니다. 다른 기기는 로그아웃됐습니다.');
              })}
            />
          </>
        ) : (
          <>
            <Field label="아이디">
              <Input value={username} onChangeText={setUsername} autoCapitalize="none" />
            </Field>
            <Field label="비밀번호">
              <Input value={password} onChangeText={setPassword} secureTextEntry />
            </Field>
            <Button
              label="로그인"
              tone="primary"
              busy={busy === 'login'}
              disabled={!username || !password || !url.trim()}
              onPress={() => run('login', async () => {
                onBaseUrl(url);
                await onSignIn(username, password);
                setPassword('');
              })}
            />
          </>
        )}
      </Card>

      {signedIn ? (
        <Card title="에이전트">
          {sessions.length === 0 ? (
            <Text style={{ color: T.muted, fontSize: 13 }}>
              아직 에이전트가 없습니다. 웹이나 데스크톱에서 하나 만들어 주세요.
            </Text>
          ) : (
            sessions.map((session) => (
              <View
                key={session.session_id}
                style={{
                  flexDirection: 'row', alignItems: 'center', gap: 10,
                  paddingVertical: 8, borderTopWidth: 1, borderColor: T.border,
                }}
              >
                <View style={{ flex: 1 }}>
                  <Text style={{ color: T.text, fontSize: 14 }} numberOfLines={1}>
                    {session.session_name || session.session_id.slice(0, 8)}
                  </Text>
                  <Text style={{ color: T.muted, fontSize: 12 }}>
                    {session.status}{session.env_name ? ` · ${session.env_name}` : ''}
                  </Text>
                </View>
                {session.session_id === sessionId
                  ? <Pill text="사용 중" tone="ok" />
                  : <Button label="열기" onPress={() => onPickSession(session)} />}
              </View>
            ))
          )}
          <Button label="새로고침" busy={busy === 'refresh'} onPress={() => run('refresh', refresh)} />
        </Card>
      ) : null}

      {signedIn && sessionId ? (
        <Card title="모델">
          {lastRoute?.label ? (
            <Text style={{ color: T.muted, fontSize: 12 }}>
              지난 턴은 {lastRoute.label}{lastRoute.model ? ` · ${lastRoute.model}` : ''} 가 답했습니다
              {lastRoute.failedOver ? ' (넘어감)' : ''}
            </Text>
          ) : null}
          {accounts.length === 0 ? (
            <Text style={{ color: T.muted, fontSize: 13 }}>
              쓸 수 있는 모델 계정이 없습니다. 웹 설정 › 모델에서 추가하세요.
            </Text>
          ) : (
            accounts.map((account) => (
              <View key={account.id} style={{ gap: 6, paddingTop: 8, borderTopWidth: 1, borderColor: T.border }}>
                <Text style={{ color: T.muted, fontSize: 12, fontWeight: '600' }}>{account.label}</Text>
                <View style={{ flexDirection: 'row', flexWrap: 'wrap', gap: 6 }}>
                  {account.modelChoices.slice(0, 6).map((choice) => {
                    const active = primary?.accountId === account.id && primary?.model === choice.id;
                    return (
                      <Button
                        key={choice.id}
                        label={choice.label}
                        tone={active ? 'primary' : 'default'}
                        busy={busy === 'route'}
                        onPress={() => switchModel(account.id, choice.id)}
                      />
                    );
                  })}
                </View>
              </View>
            ))
          )}
          <Text style={{ color: T.muted, fontSize: 12 }}>
            대화 중에 바꿔도 대화는 그대로 이어집니다 — 도구도, 기억도, 권한도 그대로입니다.
          </Text>
        </Card>
      ) : null}
    </ScrollView>
  );
}
