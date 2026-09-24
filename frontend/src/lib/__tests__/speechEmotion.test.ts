/**
 * The avatar's voice across a streamed reply.
 *
 * 2026-09-24: a reply with a mood change in the middle ("[calm] … [curious]
 * …") was spoken twice. The live stream was the reader's text (cues
 * stripped), the end of the turn was the voice's text (cues kept), so the
 * finished text stopped matching what had already been said at the first
 * mid-reply cue and the extractor started over from the top. Live and final
 * now come from the same cued text; the cues are taken out per sentence.
 *
 * 실행:  cd Geny/frontend && npx vitest run src/lib/__tests__/speechEmotion.test.ts
 */
import { describe, it, expect } from 'vitest';

import { parseEmotion } from '../../components/chat/chat-utils';
import { SentenceStreamExtractor } from '../sentenceBoundaryDetector';
import { opensWithCue, voiceSentence } from '../speechEmotion';

// A real reply (room ed3efe84, message 9248).
const SPOKEN =
  '[calm:0.3] 어, 타이틀 화면 떴네 — 발더스 게이트 3 로고에 캐릭터들 쫙 나와있고, 뒤에 미치광이 문어… ' +
  '아니 촉수 괴물이랑 용까지 떠다니는 그림이야. [curious:0.4] 오른쪽 아래엔 내 창이 그대로 걸려있고. ' +
  '이제 뭐 누를 거야, 새 게임?';

/** Stream `text` in small steps, then finish the turn, as the panel does. */
function speakStreamed(text: string): { text: string; emotion: string }[] {
  const ex = new SentenceStreamExtractor({ minChars: 20, breakBefore: opensWithCue });
  const out: { text: string; emotion: string }[] = [];
  let carry: string | null = null;
  const say = (sentences: string[], emotion: string) => {
    for (const s of sentences) {
      const v = voiceSentence(s, carry ?? emotion);
      carry = v.carry;
      if (v.text) out.push({ text: v.text, emotion: v.emotion });
    }
  };
  for (let i = 5; i < text.length + 5; i += 5) {
    const [emotion, clean] = parseEmotion(text.slice(0, i));
    say(ex.push('turn', clean), emotion);
  }
  const [emotion, clean] = parseEmotion(text);
  say(ex.flush('turn', clean), emotion);
  return out;
}

describe('voiceSentence', () => {
  it('speaks a sentence in the cue it opens with, without the cue', () => {
    expect(voiceSentence('[curious:0.4] 오른쪽 아래엔 내 창이 그대로.', 'calm'))
      .toEqual({ text: '오른쪽 아래엔 내 창이 그대로.', emotion: 'curious', carry: 'curious' });
  });

  it('keeps the running emotion when a sentence has no cue', () => {
    expect(voiceSentence('그대로 걸려있고.', 'calm')).toEqual({ text: '그대로 걸려있고.', emotion: 'calm', carry: 'calm' });
  });

  it('a cue late in a sentence changes the NEXT sentence, not this one', () => {
    const v = voiceSentence('좋아 [joy] 가자!', 'calm');
    expect(v.emotion).toBe('calm');
    expect(v.carry).toBe('joy');
    expect(v.text).toBe('좋아 가자!');
  });

  it('drops unknown cues from speech without switching to them', () => {
    expect(voiceSentence('[smug] 역시 그렇지.', 'calm'))
      .toEqual({ text: '역시 그렇지.', emotion: 'calm', carry: 'calm' });
  });
});

describe('a streamed reply with a mood change', () => {
  const said = speakStreamed(SPOKEN);
  const joined = said.map((s) => s.text).join(' ');

  it('is spoken once — every sentence exactly one time', () => {
    const reply = parseEmotion(SPOKEN)[1].replace(/\[[a-z_]+(:[0-9.]+)?\]\s*/g, '');
    expect(joined.replace(/\s+/g, '')).toBe(reply.replace(/\s+/g, ''));
  });

  it('never speaks a cue', () => {
    expect(joined).not.toMatch(/\[/);
  });

  it('follows the mood: calm first, curious after the cue', () => {
    expect(said[0].emotion).toBe('calm');
    expect(said[said.length - 1].emotion).toBe('curious');
    expect(said.find((s) => s.text.startsWith('오른쪽'))?.emotion).toBe('curious');
  });
});

describe('a short sentence before a mood change', () => {
  // Room ed3efe84, message 9283: the first sentence is under the 20-char
  // clip minimum, so it used to be merged with the next — and the one clip
  // was voiced calm, losing the excitement.
  const said = speakStreamed('[calm:0.3] 응, 목소리 잘 들려. [excitement:0.6] 이번엔 끊기는 것도 없고 딱 깔끔하네!');

  it('is its own clip, so each keeps its voice', () => {
    expect(said).toEqual([
      { text: '응, 목소리 잘 들려.', emotion: 'calm' },
      { text: '이번엔 끊기는 것도 없고 딱 깔끔하네!', emotion: 'excitement' },
    ]);
  });

  it('short sentences without a mood change are still merged', () => {
    const merged = speakStreamed('[calm] 응. 그래. 좋아. 알겠어.');
    expect(merged).toEqual([{ text: '응. 그래. 좋아. 알겠어.', emotion: 'calm' }]);
  });
});

