/**
 * The conversation.
 *
 * The same room the desktop app and the web page show — so a question asked
 * here an hour ago is on the laptop now, and an answer the agent gave to the
 * web is here. What the phone draws differently is only how much fits: the
 * live tool calls are one line each instead of an expandable timeline.
 *
 * The connection banner is the screen's most load-bearing piece of honesty. A
 * phone loses its socket constantly, and the turn keeps running on the server
 * regardless — so the banner says which of those two is true, separately:
 * "생각 중" is about the agent, "다시 연결하는 중" is about this phone. Merging
 * them into one spinner is how a user learns to distrust the screen.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import {
  ActivityIndicator, FlatList, KeyboardAvoidingView, Platform, Pressable, Text, View,
} from 'react-native';

import type { ConnState, ToolCall } from '../../../shared/chat/room';
import { describeTool } from '../../../shared/chat/tool-view';
import type { Message } from '../../../shared/chat/transcript';
import { useLiveTurn } from '../lib/useLiveTurn';
import { Button, Input, Notice, Pill } from '../ui';
import { T } from '../theme';

const CONNECTION_TEXT: Record<ConnState, string> = {
  connecting: '연결하는 중',
  connected: '연결됨',
  reconnecting: '다시 연결하는 중',
  offline: '연결이 끊겼습니다',
  unauthorized: '로그인이 만료됐습니다',
  closed: '연결 종료',
};

const MONO = Platform.OS === 'ios' ? 'Menlo' : 'monospace';

function Bubble({ message }: { message: Message }) {
  // A buffer, not a message. The turn's answer arrives separately.
  if (message.role === 'draft') return null;

  if (message.role === 'activity') {
    const tone = message.ok === false ? T.bad : message.ok === true ? T.muted : T.warn;
    return (
      <View style={{ paddingHorizontal: 14, paddingVertical: 4 }}>
        <Text style={{ color: tone, fontSize: 12, fontFamily: MONO }}>
          {message.ok === false ? '✗ ' : '· '}{message.text}
        </Text>
      </View>
    );
  }
  if (message.role === 'notice' || message.role === 'system') {
    return (
      <View style={{
        marginHorizontal: 12, marginVertical: 4, padding: 10, borderRadius: 10,
        backgroundColor: '#3A1D22',
      }}>
        <Text style={{ color: T.bad, fontSize: 13 }}>{message.text}</Text>
      </View>
    );
  }
  const mine = message.role === 'user';
  return (
    <View style={{
      alignSelf: mine ? 'flex-end' : 'flex-start',
      maxWidth: '86%', marginHorizontal: 12, marginVertical: 4,
      backgroundColor: mine ? T.accent : T.surface,
      borderRadius: 14, borderWidth: mine ? 0 : 1, borderColor: T.border,
      paddingHorizontal: 13, paddingVertical: 10,
      opacity: message.pending ? 0.65 : 1,
    }}>
      <Text style={{ color: mine ? '#FFFFFF' : T.text, fontSize: 15, lineHeight: 21 }}>
        {message.text}
      </Text>
    </View>
  );
}

/** What it is doing, while it does it. One line per call, newest last. */
function Steps({ calls }: { calls: ToolCall[] }) {
  if (calls.length === 0) return null;
  return (
    <View style={{
      marginHorizontal: 12, marginBottom: 6, padding: 10, gap: 6,
      borderRadius: 12, borderWidth: 1, borderColor: T.border, backgroundColor: T.surface,
    }}>
      {calls.slice(-4).map((call) => {
        const { text } = describeTool(call.name, call.input);
        const mark = call.ok === null || call.ok === undefined ? '›' : call.ok ? '✓' : '✗';
        const color = call.ok === false ? T.bad : call.ok ? T.muted : T.warn;
        return (
          <View key={call.key} style={{ flexDirection: 'row', gap: 8, alignItems: 'flex-start' }}>
            <Text style={{ color, fontSize: 12, fontFamily: MONO, width: 12 }}>{mark}</Text>
            <Text numberOfLines={2} style={{ color: T.text, fontSize: 12.5, flex: 1, lineHeight: 17 }}>
              {text}
            </Text>
            {call.durationMs ? (
              <Text style={{ color: T.muted, fontSize: 11, fontFamily: MONO }}>
                {(call.durationMs / 1000).toFixed(1)}s
              </Text>
            ) : null}
          </View>
        );
      })}
    </View>
  );
}

export function ChatScreen({
  baseUrl, sessionId, sessionName, token, onOpenSettings,
}: {
  baseUrl: string;
  sessionId: string | null;
  sessionName: string;
  token: string | null;
  onOpenSettings: () => void;
}) {
  const turn = useLiveTurn(baseUrl, sessionId, token);
  const [draft, setDraft] = useState('');
  const listRef = useRef<FlatList<Message>>(null);

  useEffect(() => {
    const timer = setTimeout(() => listRef.current?.scrollToEnd({ animated: true }), 60);
    return () => clearTimeout(timer);
  }, [turn.messages.length]);

  const send = useCallback(() => {
    const text = draft.trim();
    if (!text) return;
    turn.send(text);
    setDraft('');
  }, [draft, turn]);

  const connection = useMemo(() => {
    if (turn.state === 'connected') return null;
    const tone = turn.state === 'unauthorized' || turn.state === 'offline' ? 'bad' : 'warn';
    return { text: CONNECTION_TEXT[turn.state], tone } as const;
  }, [turn.state]);

  if (!sessionId) {
    return (
      <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center', gap: 12, padding: 24 }}>
        <Text style={{ color: T.text, fontSize: 16 }}>대화할 에이전트를 고르세요</Text>
        <Button label="설정 열기" onPress={onOpenSettings} />
      </View>
    );
  }

  return (
    <KeyboardAvoidingView
      style={{ flex: 1 }}
      behavior={Platform.OS === 'ios' ? 'padding' : undefined}
      keyboardVerticalOffset={Platform.OS === 'ios' ? 88 : 0}
    >
      <View style={{
        paddingHorizontal: 14, paddingVertical: 10, borderBottomWidth: 1, borderColor: T.border,
        flexDirection: 'row', alignItems: 'center', justifyContent: 'space-between', gap: 10,
      }}>
        <View style={{ flex: 1, gap: 4 }}>
          <Text numberOfLines={1} style={{ color: T.text, fontSize: 15, fontWeight: '600' }}>
            {sessionName || sessionId.slice(0, 8)}
          </Text>
          <View style={{ flexDirection: 'row', gap: 6 }}>
            {/* Two separate facts. The agent working and this phone being
                connected are different things, and a phone is disconnected far
                more often than an agent is stuck. */}
            {turn.running ? <Pill text="생각 중" tone="ok" /> : null}
            {connection ? <Pill text={connection.text} tone={connection.tone} /> : null}
          </View>
        </View>
        <Pressable onPress={onOpenSettings} hitSlop={10}>
          <Text style={{ color: T.muted, fontSize: 20 }}>⋯</Text>
        </Pressable>
      </View>

      <FlatList
        ref={listRef}
        data={turn.messages}
        keyExtractor={(m) => m.key}
        renderItem={({ item }) => <Bubble message={item} />}
        contentContainerStyle={{ paddingVertical: 12, flexGrow: 1 }}
        onContentSizeChange={() => listRef.current?.scrollToEnd({ animated: false })}
        ListEmptyComponent={
          turn.loading ? (
            <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center' }}>
              <ActivityIndicator color={T.accent} />
            </View>
          ) : (
            <View style={{ flex: 1, alignItems: 'center', justifyContent: 'center', padding: 24 }}>
              <Text style={{ color: T.muted, fontSize: 14, textAlign: 'center' }}>
                무엇이든 시켜 보세요. 화면을 꺼도 서버에서 계속 돌아갑니다.
              </Text>
            </View>
          )
        }
      />

      <Steps calls={turn.calls} />

      {turn.error ? (
        <Pressable onPress={turn.clearError} style={{ paddingHorizontal: 14, paddingBottom: 6 }}>
          <Notice text={turn.error} />
        </Pressable>
      ) : null}

      <View style={{
        flexDirection: 'row', gap: 8, padding: 10, borderTopWidth: 1, borderColor: T.border,
        alignItems: 'flex-end',
      }}>
        <Input
          value={draft}
          onChangeText={setDraft}
          placeholder="메시지를 입력하세요"
          multiline
          style={{ flex: 1, maxHeight: 120 }}
          onSubmitEditing={send}
        />
        {turn.running ? (
          <Button label="중지" tone="danger" onPress={turn.stop} />
        ) : (
          <Button label="보내기" tone="primary" onPress={send} disabled={!draft.trim()} />
        )}
      </View>
    </KeyboardAvoidingView>
  );
}
