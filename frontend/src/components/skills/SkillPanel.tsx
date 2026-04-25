'use client';

/**
 * Skill chip panel — shows the available SKILL.md slash commands and
 * inserts the matching ``/<id>`` prefix into the command input on
 * click. Pure UI; no execution path of its own. The actual SkillTool
 * dispatch happens inside the executor when the prompt arrives with
 * a ``/<id>`` prefix the slash-command detector recognises.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { agentApi } from '@/lib/api';
import { Sparkles, RefreshCw } from 'lucide-react';

interface Props {
  /** Called when the operator clicks a skill chip. The handler
   * decides where to put the slash command (typically prepend it to
   * the current command input). */
  onPickSkill: (slashCommand: string) => void;
}

interface SkillRow {
  id: string | null;
  name: string | null;
  description: string | null;
  allowed_tools: string[];
}

export default function SkillPanel({ onPickSkill }: Props) {
  const [skills, setSkills] = useState<SkillRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  // R9 (audit 20260425_3 §1.3): cancel in-flight reload when a new
  // one starts (rapid clicks) or the component unmounts. Without
  // this a slow first response could clobber a fast second one.
  const fetchIdRef = useRef(0);

  const reload = useCallback(() => {
    setLoading(true);
    setError(null);
    const id = ++fetchIdRef.current;
    agentApi
      .skillsList()
      .then((resp) => {
        if (id !== fetchIdRef.current) return;  // stale
        setSkills(resp.skills);
      })
      .catch((err) => {
        if (id !== fetchIdRef.current) return;
        setError(err instanceof Error ? err.message : String(err));
      })
      .finally(() => {
        if (id !== fetchIdRef.current) return;
        setLoading(false);
      });
  }, []);

  useEffect(() => {
    reload();
    return () => {
      // Bump the id so any in-flight callback short-circuits.
      fetchIdRef.current += 1;
    };
  }, [reload]);

  if (loading && skills.length === 0) {
    return (
      <div className="px-3 py-2 text-[0.6875rem] text-[var(--text-muted)]">Loading skills…</div>
    );
  }
  if (error) {
    return (
      <div className="px-3 py-2 text-[0.6875rem] text-[var(--danger-color)]">{error}</div>
    );
  }
  if (skills.length === 0) {
    return (
      <div className="px-3 py-2 text-[0.6875rem] text-[var(--text-muted)] flex items-center gap-1.5">
        <Sparkles size={11} className="opacity-60" />
        No skills registered. Drop a <code className="font-mono">SKILL.md</code> under
        <code className="font-mono"> ~/.geny/skills/&lt;id&gt;/</code> and set
        <code className="font-mono"> GENY_ALLOW_USER_SKILLS=1</code>.
      </div>
    );
  }

  return (
    <div className="px-3 py-2 flex flex-wrap items-center gap-1.5">
      <Sparkles size={11} className="text-[var(--primary-color)] opacity-70" />
      <span className="text-[0.625rem] text-[var(--text-muted)] uppercase tracking-wider font-semibold mr-1">
        Skills
      </span>
      {skills.map((skill, idx) => (
        <button
          key={skill.id ?? `skill-${idx}`}
          className="inline-flex items-center gap-1 px-2 py-[2px] rounded-full bg-[var(--bg-tertiary)] hover:bg-[var(--bg-hover)] text-[0.6875rem] text-[var(--text-secondary)] border border-[var(--border-color)] transition-colors"
          onClick={() => onPickSkill(`/${skill.id ?? ''}`)}
          title={skill.description ?? skill.name ?? ''}
        >
          <span className="font-mono">/{skill.id}</span>
          {skill.allowed_tools.length > 0 && (
            <span className="text-[0.5625rem] text-[var(--text-muted)] opacity-70">
              · {skill.allowed_tools.length} tool{skill.allowed_tools.length === 1 ? '' : 's'}
            </span>
          )}
        </button>
      ))}
      <button
        className="ml-auto h-5 w-5 rounded text-[var(--text-muted)] hover:text-[var(--text-secondary)] flex items-center justify-center"
        onClick={reload}
        title="Reload skills"
      >
        <RefreshCw size={10} />
      </button>
    </div>
  );
}
