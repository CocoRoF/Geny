'use client';

/**
 * Skill chip panel — shows the available SKILL.md slash commands and
 * inserts the matching ``/<id>`` prefix into the command input on
 * click. Pure UI; no execution path of its own. The actual SkillTool
 * dispatch happens inside the executor when the prompt arrives with
 * a ``/<id>`` prefix the slash-command detector recognises.
 */

import { useCallback, useEffect, useRef, useState } from 'react';
import { agentApi, skillsApi, SkillDetail } from '@/lib/api';
import { Sparkles, RefreshCw, Info, X } from 'lucide-react';

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
  // PR-D.3.3 — richer SKILL.md fields exposed after executor 1.2.0.
  // Optional / default-empty so older payloads still render.
  category?: string | null;
  effort?: string | null;
  examples?: string[];
}

// Effort indicator: low ●○○ / medium ●●○ / high ●●●. Returns null
// for unknown / missing so the badge is skipped.
function effortDots(effort?: string | null): string | null {
  switch ((effort || '').toLowerCase()) {
    case 'low': return '●○○';
    case 'medium': return '●●○';
    case 'high': return '●●●';
    default: return null;
  }
}

export default function SkillPanel({ onPickSkill }: Props) {
  const [skills, setSkills] = useState<SkillRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  // PR-F.2.2 — chip detail modal state.
  const [detail, setDetail] = useState<SkillDetail | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);

  const openDetail = (skillId: string | null) => {
    if (!skillId) return;
    setDetailLoading(true);
    skillsApi.get(skillId)
      .then(setDetail)
      .catch((e) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setDetailLoading(false));
  };

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
      {skills.map((skill, idx) => {
        const dots = effortDots(skill.effort);
        // Tooltip aggregates the new metadata so a hover surfaces
        // category/effort/examples without dedicating screen space.
        const tooltipParts = [
          skill.description ?? skill.name ?? '',
          skill.category ? `[${skill.category}]` : '',
          skill.effort ? `effort: ${skill.effort}` : '',
          (skill.examples?.length ?? 0) > 0
            ? `examples:\n  - ${skill.examples!.join('\n  - ')}`
            : '',
        ].filter(Boolean).join('\n');

        return (
          <span
            key={skill.id ?? `skill-${idx}`}
            className="inline-flex items-center rounded-full bg-[var(--bg-tertiary)] border border-[var(--border-color)] hover:bg-[var(--bg-hover)] transition-colors overflow-hidden"
          >
            <button
              className="inline-flex items-center gap-1 pl-2 pr-1 py-[2px] text-[0.6875rem] text-[var(--text-secondary)]"
              onClick={() => onPickSkill(`/${skill.id ?? ''}`)}
              title={tooltipParts}
            >
              <span className="font-mono">/{skill.id}</span>
              {skill.category && (
                <span className="text-[0.5625rem] uppercase tracking-wide text-[var(--primary-color)] opacity-80">
                  {skill.category}
                </span>
              )}
              {dots && (
                <span className="text-[0.5625rem] text-[var(--text-muted)] opacity-70 font-mono">
                  {dots}
                </span>
              )}
              {skill.allowed_tools.length > 0 && (
                <span className="text-[0.5625rem] text-[var(--text-muted)] opacity-70">
                  · {skill.allowed_tools.length} tool{skill.allowed_tools.length === 1 ? '' : 's'}
                </span>
              )}
            </button>
            {/* PR-F.2.2 — chip detail launcher */}
            <button
              type="button"
              onClick={() => openDetail(skill.id)}
              title="Show skill detail"
              className="px-1.5 py-[2px] border-l border-[var(--border-color)] text-[var(--text-muted)] hover:text-[var(--primary-color)]"
            >
              <Info size={10} />
            </button>
          </span>
        );
      })}
      <button
        className="ml-auto h-5 w-5 rounded text-[var(--text-muted)] hover:text-[var(--text-secondary)] flex items-center justify-center"
        onClick={reload}
        title="Reload skills"
      >
        <RefreshCw size={10} />
      </button>

      {/* PR-F.2.2 — chip detail modal */}
      {detail && (
        <div
          className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center p-4"
          onClick={() => setDetail(null)}
        >
          <div
            className="bg-[var(--bg-primary)] rounded-lg border border-[var(--border-color)] w-full max-w-2xl max-h-[80vh] overflow-hidden flex flex-col"
            onClick={(e) => e.stopPropagation()}
          >
            <header className="px-4 py-2 border-b border-[var(--border-color)] flex items-center justify-between">
              <div>
                <h3 className="text-sm font-semibold font-mono">/{detail.id}</h3>
                <p className="text-[0.6875rem] text-[var(--text-muted)]">{detail.name ?? ''}</p>
              </div>
              <button
                type="button"
                onClick={() => setDetail(null)}
                className="text-[var(--text-muted)] hover:text-[var(--text-primary)]"
              >
                <X size={14} />
              </button>
            </header>
            <div className="overflow-y-auto p-4 text-[0.8125rem] space-y-3">
              <p>{detail.description}</p>
              <div className="grid grid-cols-2 gap-2 text-[0.75rem]">
                {detail.category && <div><span className="text-[var(--text-muted)]">category:</span> {detail.category}</div>}
                {detail.effort && <div><span className="text-[var(--text-muted)]">effort:</span> {detail.effort}</div>}
                {detail.model && <div><span className="text-[var(--text-muted)]">model:</span> <span className="font-mono">{detail.model}</span></div>}
                <div><span className="text-[var(--text-muted)]">user_skill:</span> {detail.is_user_skill ? 'yes' : 'no'}</div>
                {detail.source && <div className="col-span-2 truncate" title={detail.source}><span className="text-[var(--text-muted)]">source:</span> <span className="font-mono">{detail.source}</span></div>}
              </div>
              {detail.allowed_tools.length > 0 && (
                <div>
                  <div className="text-[0.6875rem] uppercase tracking-wider text-[var(--text-muted)] mb-1">Allowed tools</div>
                  <div className="flex flex-wrap gap-1">
                    {detail.allowed_tools.map((tool) => (
                      <span key={tool} className="text-[0.6875rem] font-mono px-1.5 py-0.5 rounded bg-[var(--bg-tertiary)]">{tool}</span>
                    ))}
                  </div>
                </div>
              )}
              {detail.examples.length > 0 && (
                <div>
                  <div className="text-[0.6875rem] uppercase tracking-wider text-[var(--text-muted)] mb-1">Examples</div>
                  <ul className="list-disc ml-5 text-[0.75rem]">
                    {detail.examples.map((ex, i) => <li key={i}>{ex}</li>)}
                  </ul>
                </div>
              )}
              <div>
                <div className="text-[0.6875rem] uppercase tracking-wider text-[var(--text-muted)] mb-1">Body</div>
                <pre className="text-[0.6875rem] font-mono whitespace-pre-wrap bg-[var(--bg-tertiary)] rounded p-2">
                  {detail.body || '—'}
                </pre>
              </div>
            </div>
          </div>
        </div>
      )}
      {detailLoading && !detail && (
        <div className="fixed inset-0 z-50 bg-black/40 flex items-center justify-center pointer-events-none">
          <div className="text-white text-sm">Loading skill…</div>
        </div>
      )}
    </div>
  );
}
