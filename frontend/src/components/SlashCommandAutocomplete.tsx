'use client';

/**
 * SlashCommandAutocomplete (PR-A.6.2 frontend).
 *
 * Reusable dropdown that fetches /api/slash-commands once on mount,
 * filters by current input prefix, and emits a selection. Designed to
 * be mounted alongside any chat textarea — caller decides where to
 * position it (typically just above the input).
 */

import { useEffect, useMemo, useState } from 'react';
import { slashCommandApi, SlashCommandSummary } from '@/lib/api';

interface Props {
  /** Current textarea value. The component activates when it starts with '/'. */
  inputValue: string;
  /** Called when the user picks a command. Replaces the leading slash token. */
  onSelect: (commandName: string) => void;
}

export function SlashCommandAutocomplete({ inputValue, onSelect }: Props) {
  const [commands, setCommands] = useState<SlashCommandSummary[]>([]);
  const [loadError, setLoadError] = useState<string | null>(null);

  useEffect(() => {
    let cancelled = false;
    slashCommandApi
      .list()
      .then((resp) => {
        if (!cancelled) setCommands(resp.commands);
      })
      .catch((e) => {
        if (!cancelled) setLoadError(e instanceof Error ? e.message : String(e));
      });
    return () => {
      cancelled = true;
    };
  }, []);

  const matches = useMemo<SlashCommandSummary[]>(() => {
    const trimmed = inputValue.trimStart();
    if (!trimmed.startsWith('/')) return [];
    // The leading slash + first whitespace-delimited token is the prefix
    // we filter on. Everything past the first space is args, not a name.
    const firstLine = trimmed.split(/\r?\n/, 1)[0];
    const head = firstLine.slice(1).split(/\s+/, 1)[0]?.toLowerCase() || '';
    if (head === '') return commands.slice(0, 10);
    return commands
      .filter(
        (c) =>
          c.name.toLowerCase().startsWith(head) ||
          c.aliases.some((a) => a.toLowerCase().startsWith(head)),
      )
      .slice(0, 10);
  }, [inputValue, commands]);

  if (loadError) {
    return (
      <div className="text-xs text-red-600 px-2 py-1 border-t bg-red-50">
        slash commands unavailable: {loadError}
      </div>
    );
  }

  if (matches.length === 0) return null;

  return (
    <div className="border rounded shadow-sm bg-white max-h-60 overflow-y-auto">
      <ul className="text-sm divide-y">
        {matches.map((cmd) => (
          <li key={cmd.name}>
            <button
              type="button"
              onClick={() => onSelect(cmd.name)}
              className="w-full text-left px-3 py-2 hover:bg-blue-50"
            >
              <div className="flex items-center justify-between gap-2">
                <span className="font-mono font-medium">/{cmd.name}</span>
                <span className="text-xs text-slate-500 uppercase">{cmd.category}</span>
              </div>
              <div className="text-xs text-slate-600">{cmd.description}</div>
              {cmd.aliases.length > 0 && (
                <div className="text-xs text-slate-400 mt-1">
                  aliases: {cmd.aliases.map((a) => `/${a}`).join(', ')}
                </div>
              )}
            </button>
          </li>
        ))}
      </ul>
    </div>
  );
}

export default SlashCommandAutocomplete;
