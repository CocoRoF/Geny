/** The handful of pieces every screen here is made of. */
import type { ReactNode } from 'react';
import { ActivityIndicator, Pressable, Text, TextInput, View } from 'react-native';

import { T } from './theme';

export function Card({ title, children }: { title?: string; children: ReactNode }) {
  return (
    <View style={{
      backgroundColor: T.surface, borderRadius: T.radius, borderWidth: 1,
      borderColor: T.border, padding: 14, gap: 10,
    }}>
      {title ? <Text style={{ color: T.text, fontSize: 15, fontWeight: '600' }}>{title}</Text> : null}
      {children}
    </View>
  );
}

export function Field({ label, children }: { label: string; children: ReactNode }) {
  return (
    <View style={{ gap: 6 }}>
      <Text style={{ color: T.muted, fontSize: 12 }}>{label}</Text>
      {children}
    </View>
  );
}

export function Input(props: React.ComponentProps<typeof TextInput>) {
  return (
    <TextInput
      placeholderTextColor={T.muted}
      {...props}
      style={[{
        backgroundColor: T.surfaceAlt, borderRadius: 10, borderWidth: 1, borderColor: T.border,
        color: T.text, paddingHorizontal: 12, paddingVertical: 10, fontSize: 15,
      }, props.style]}
    />
  );
}

export function Button({
  label, onPress, tone = 'default', disabled, busy,
}: {
  label: string;
  onPress: () => void;
  tone?: 'default' | 'primary' | 'danger';
  disabled?: boolean;
  busy?: boolean;
}) {
  const bg = tone === 'primary' ? T.accent : tone === 'danger' ? '#3A1D22' : T.surfaceAlt;
  const fg = tone === 'primary' ? '#FFFFFF' : tone === 'danger' ? T.bad : T.text;
  return (
    <Pressable
      onPress={onPress}
      disabled={disabled || busy}
      style={{
        backgroundColor: bg, borderRadius: 10, borderWidth: tone === 'primary' ? 0 : 1,
        borderColor: T.border, paddingHorizontal: 14, paddingVertical: 11,
        opacity: disabled || busy ? 0.5 : 1, flexDirection: 'row',
        alignItems: 'center', justifyContent: 'center', gap: 8,
      }}
    >
      {busy ? <ActivityIndicator size="small" color={fg} /> : null}
      <Text style={{ color: fg, fontSize: 14, fontWeight: '600' }}>{label}</Text>
    </Pressable>
  );
}

export function Pill({ text, tone = 'muted' }: { text: string; tone?: 'muted' | 'ok' | 'warn' | 'bad' }) {
  const color = tone === 'ok' ? T.ok : tone === 'warn' ? T.warn : tone === 'bad' ? T.bad : T.muted;
  return (
    <View style={{
      flexDirection: 'row', alignItems: 'center', gap: 6, alignSelf: 'flex-start',
      backgroundColor: T.surfaceAlt, borderRadius: 999, paddingHorizontal: 10, paddingVertical: 5,
    }}>
      <View style={{ width: 7, height: 7, borderRadius: 4, backgroundColor: color }} />
      <Text style={{ color: T.muted, fontSize: 12 }}>{text}</Text>
    </View>
  );
}

export function Notice({ text, tone = 'bad' }: { text: string; tone?: 'bad' | 'muted' }) {
  return (
    <Text style={{ color: tone === 'bad' ? T.bad : T.muted, fontSize: 12.5, lineHeight: 18 }}>
      {text}
    </Text>
  );
}
