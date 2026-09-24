/**
 * Which voice a sentence is spoken in, and what is left to speak.
 *
 * A reply can change mood as it goes — "[calm:0.3] 타이틀 화면 떴네. …
 * [curious:0.4] 이제 뭐 누를 거야?" — and the voice should follow: a
 * sentence that opens with a cue is spoken in that cue, and the cue carries
 * on to the sentences after it until another one comes. The cues themselves
 * are never spoken.
 *
 * The same text feeds the live stream and the end of the turn, cues and all
 * (see ``streaming_spoken`` on the server), so what was already said is
 * always a prefix of the finished reply; this is where the cues are taken
 * back out, one sentence at a time, just before the voice.
 */
import { EMOTIONS } from '../components/chat/chat-utils';

const KNOWN = new Set<string>(EMOTIONS);

/** Any cue the model writes — known or not, with or without a strength. The
 *  unknown ones are dropped from speech too; they are not words. */
const CUE = /\[\s*([a-z][a-z_]{2,19})(?:\s*:\s*-?\d+(?:\.\d+)?)?\s*\][^\S\n]*/gi;
const LEADING_CUE = /^\s*\[\s*([a-z][a-z_]{2,19})(?:\s*:\s*-?\d+(?:\.\d+)?)?\s*\]/i;

export interface VoicedSentence {
  /** What the voice says: the sentence without cues. */
  text: string;
  /** The emotion it is said in. */
  emotion: string;
  /** The emotion the next sentence inherits. */
  carry: string;
}

export function voiceSentence(sentence: string, carry: string): VoicedSentence {
  const leading = LEADING_CUE.exec(sentence)?.[1]?.toLowerCase();
  const emotion = leading && KNOWN.has(leading) ? leading : carry;
  let next = carry;
  for (const m of sentence.matchAll(CUE)) {
    const name = m[1].toLowerCase();
    if (KNOWN.has(name)) next = name;
  }
  const text = sentence.replace(CUE, '').replace(/[^\S\n]{2,}/g, ' ').trim();
  return { text, emotion, carry: next };
}

/** Whether a sentence opens with a known cue — a mood change, which must not
 *  be merged into the previous sentence's clip (one clip, one voice). */
export function opensWithCue(sentence: string): boolean {
  const leading = LEADING_CUE.exec(sentence)?.[1]?.toLowerCase();
  return !!leading && KNOWN.has(leading);
}
