/**
 * Shared chat utilities — color mappings, time formatting, and role helpers
 * used by Messenger, VTuber, and other chat-related components.
 */

// ── Role color helpers ──

/** Tailwind gradient class for role-based avatar backgrounds. */
export const getRoleColor = (role: string): string => {
  switch (role) {
    case 'developer': return 'from-blue-500 to-cyan-500';
    case 'researcher': return 'from-amber-500 to-orange-500';
    case 'planner': return 'from-teal-500 to-emerald-500';
    default: return 'from-emerald-500 to-green-500';
  }
};

/** CSS gradient string for role badge backgrounds. */
export const getRoleBadgeBg = (role: string): string => {
  switch (role) {
    case 'developer': return 'linear-gradient(135deg, #3b82f6, #06b6d4)';
    case 'researcher': return 'linear-gradient(135deg, #f59e0b, #ea580c)';
    case 'planner': return 'linear-gradient(135deg, #14b8a6, #10b981)';
    default: return 'linear-gradient(135deg, #10b981, #059669)';
  }
};

// ── Time formatting ──

/** Format timestamp to HH:MM (locale). */
export const formatTime = (ts: string): string => {
  const d = new Date(ts);
  return d.toLocaleTimeString([], { hour: '2-digit', minute: '2-digit' });
};

/** Format timestamp to display-friendly date label. */
export const formatDate = (ts: string): string => {
  const d = new Date(ts);
  const today = new Date();
  const yesterday = new Date(today);
  yesterday.setDate(yesterday.getDate() - 1);

  if (d.toDateString() === today.toDateString()) return 'Today';
  if (d.toDateString() === yesterday.toDateString()) return 'Yesterday';
  return d.toLocaleDateString(undefined, { month: 'short', day: 'numeric', year: 'numeric' });
};

/** Format duration in milliseconds to human-readable string. */
export const formatDuration = (ms: number): string => {
  if (ms < 1000) return `${ms}ms`;
  return `${(ms / 1000).toFixed(1)}s`;
};

// ── Emotion parsing (VTuber) ──

/** The emotion vocabulary, mirroring ``service/affect/taxonomy.py``.
 *
 *  It must be the same list on both sides: the backend strips these tags from
 *  what a user reads, and anything it does not know it leaves on screen. Six
 *  were missing here (``wonder``, ``love``, ``excitement``, ``curiosity``,
 *  ``amazement``, ``satisfaction``) — including ``wonder``, which the
 *  emitter's own docstring uses as its worked example. A backend test
 *  compares the two lists so they cannot drift again. */
export const EMOTIONS = [
  'neutral', 'joy', 'anger', 'disgust', 'fear', 'smirk', 'sadness', 'surprise',
  'warmth', 'curious', 'calm', 'excited', 'shy', 'proud', 'grateful',
  'playful', 'confident', 'thoughtful', 'concerned', 'amused', 'tender',
  'wonder', 'love', 'excitement', 'curiosity', 'amazement', 'satisfaction',
] as const;

/** Emotion → subtle color for inline badges */
export const EMOTION_COLORS: Record<string, string> = {
  neutral: '#8b949e',
  joy: '#e3b341',
  anger: '#f47067',
  disgust: '#57ab5a',
  fear: '#b083f0',
  smirk: '#f0a8d0',
  sadness: '#6cb6ff',
  surprise: '#39d2c0',
  warmth: '#f0883e',
  curious: '#d2a8ff',
  calm: '#7ee787',
  excited: '#f8e3a1',
  shy: '#ffb3c6',
  proud: '#ffa657',
  grateful: '#a5d6ff',
  playful: '#ff9bce',
  confident: '#79c0ff',
  thoughtful: '#b7bfc7',
  concerned: '#d29922',
  amused: '#e3b341',
  tender: '#f0a8d0',
};

const EMOTION_SET = new Set<string>(EMOTIONS);

/** The optional ``:strength`` suffix, matching the grammar ``prompts/vtuber.md``
 *  offers the model ("[joy:0.7] light, [joy:1.5] intense") and the backend's
 *  own ``_STRENGTH_RE``. Without it every tag the model wrote with a strength —
 *  which is most of them — read as no tag at all. */
const STRENGTH = '(?:\\s*:\\s*-?\\d+(?:\\.\\d+)?)?';
const EMOTION_REGEX = new RegExp(`^\\[\\s*(${EMOTIONS.join('|')})${STRENGTH}\\s*\\]\\s*`);

/** Parse "[emotion] text" → [emotion, cleanText]. Returns ['neutral', text] if no tag. */
export const parseEmotion = (content: string): [string, string] => {
  const match = content.match(EMOTION_REGEX);
  if (match) {
    return [match[1], content.slice(match[0].length)];
  }
  return ['neutral', content];
};

export interface EmotionSegment {
  emotion: string | null;
  content: string;
}

/**
 * Split text by inline emotion tags into segments.
 * Each segment has an optional emotion and its following text content.
 * Tags must be from known EMOTIONS and appear at line start.
 */
export function splitEmotionSegments(text: string): EmotionSegment[] {
  // Match [emotion] or [emotion:strength] at start of string or after newline
  const re = new RegExp(
    `(?:^|\\n)\\[\\s*(${EMOTIONS.join('|')})${STRENGTH}\\s*\\][ ]*`,
    'g',
  );
  const segments: EmotionSegment[] = [];
  let lastIndex = 0;

  for (const m of text.matchAll(re)) {
    const matchStart = m.index!;
    // Text before this emotion tag
    const before = text.slice(lastIndex, matchStart);
    if (before.trim()) {
      if (segments.length > 0) {
        segments[segments.length - 1].content += before;
      } else {
        segments.push({ emotion: null, content: before });
      }
    }
    segments.push({ emotion: m[1], content: '' });
    lastIndex = matchStart + m[0].length;
  }

  // Remaining text after last match
  const remaining = text.slice(lastIndex);
  if (remaining) {
    if (segments.length > 0) {
      segments[segments.length - 1].content += remaining;
    } else {
      segments.push({ emotion: null, content: remaining });
    }
  }

  // Fallback if no segments
  if (segments.length === 0) {
    return [{ emotion: null, content: text }];
  }

  return segments;
}

/** Check if a string is a known emotion */
export function isKnownEmotion(tag: string): boolean {
  return EMOTION_SET.has(tag);
}

// ── File path helpers ──

/** Extract just the filename from a full path. */
export const shortFileName = (fp: string): string => {
  const parts = fp.replace(/\\/g, '/').split('/');
  return parts[parts.length - 1] || fp;
};

// ── Markdown normalization ──

/**
 * Agents habitually wrap their entire formatted answer in a ```` ```markdown ````
 * fence. A CommonMark renderer then treats it as a *literal* code block, so the
 * headings/tables inside show as raw source (the exact bug users hit). Unwrap
 * fences whose info string is `markdown`/`md` so their inner content renders as
 * real markdown.
 *
 * Everything else is left byte-for-byte intact: other languages (```python,
 * ```json) and plain ``` blocks stay literal, so genuine code — including lines
 * that merely *look* like tables — is never mangled. Fence length is respected
 * per CommonMark (a closer must be at least as long as its opener), so a
 * ```` ````markdown ```` wrapper can safely contain inner ``` code fences. An
 * unclosed markdown fence (still streaming) is unwrapped to the end, so partial
 * answers render live instead of flashing as a code block until the closer lands.
 */
export function normalizeChatMarkdown(src: string): string {
  if (!src) return src;
  // Fast path: no fences → nothing to unwrap.
  if (src.indexOf('```') === -1 && src.indexOf('~~~') === -1) return src;

  const parseFence = (line: string): { char: string; len: number; info: string } | null => {
    const m = /^([ \t]{0,3})(`{3,}|~{3,})[ \t]*(.*?)[ \t]*$/.exec(line);
    return m ? { char: m[2][0], len: m[2].length, info: m[3] } : null;
  };

  const lines = src.split('\n');
  const out: string[] = [];
  let i = 0;
  while (i < lines.length) {
    const open = parseFence(lines[i]);
    if (!open) { out.push(lines[i]); i++; continue; }

    // Locate the matching closer: same fence char, length ≥ opener, empty info.
    let close = -1;
    for (let j = i + 1; j < lines.length; j++) {
      const f = parseFence(lines[j]);
      if (f && f.char === open.char && f.len >= open.len && f.info === '') { close = j; break; }
    }

    const info = open.info.trim().toLowerCase();
    if (info === 'markdown' || info === 'md') {
      // Unwrap: emit only the inner lines, dropping both fence lines.
      const end = close === -1 ? lines.length : close;
      for (let k = i + 1; k < end; k++) out.push(lines[k]);
      i = close === -1 ? lines.length : close + 1;
    } else {
      // Preserve the whole fenced block verbatim (fences included).
      const last = close === -1 ? lines.length - 1 : close;
      for (let k = i; k <= last; k++) out.push(lines[k]);
      i = last + 1;
    }
  }
  return out.join('\n');
}
