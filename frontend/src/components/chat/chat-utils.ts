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

const EMOTIONS = ['neutral', 'joy', 'anger', 'disgust', 'fear', 'smirk', 'sadness', 'surprise'] as const;
const EMOTION_REGEX = new RegExp(`^\\[(${EMOTIONS.join('|')})\\]\\s*`);

/** Parse "[emotion] text" → [emotion, cleanText]. Returns ['neutral', text] if no tag. */
export const parseEmotion = (content: string): [string, string] => {
  const match = content.match(EMOTION_REGEX);
  if (match) {
    return [match[1], content.slice(match[0].length)];
  }
  return ['neutral', content];
};

// ── File path helpers ──

/** Extract just the filename from a full path. */
export const shortFileName = (fp: string): string => {
  const parts = fp.replace(/\\/g, '/').split('/');
  return parts[parts.length - 1] || fp;
};
