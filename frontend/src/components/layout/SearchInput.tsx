'use client';

/**
 * SearchInput — debounced search box with clear button + optional count.
 *
 * Caller owns the committed `value`; intermediate keystrokes are held
 * locally and flushed via `onChange` after `debounceMs`. Pressing Enter
 * flushes immediately; pressing Esc clears.
 */

import { useEffect, useRef, useState } from 'react';
import { Search, X } from 'lucide-react';
import { Input } from '@/components/ui/input';
import { cn } from './cn';

export interface SearchInputProps {
  value: string;
  onChange: (next: string) => void;
  placeholder?: string;
  debounceMs?: number;
  count?: number;
  className?: string;
  autoFocus?: boolean;
}

export function SearchInput({
  value,
  onChange,
  placeholder = '검색...',
  debounceMs = 200,
  count,
  className,
  autoFocus = false,
}: SearchInputProps) {
  const [draft, setDraft] = useState(value);
  const timer = useRef<ReturnType<typeof setTimeout> | null>(null);

  useEffect(() => {
    setDraft(value);
  }, [value]);

  const flush = (next: string) => {
    if (timer.current) clearTimeout(timer.current);
    onChange(next);
  };

  const schedule = (next: string) => {
    setDraft(next);
    if (timer.current) clearTimeout(timer.current);
    timer.current = setTimeout(() => onChange(next), debounceMs);
  };

  return (
    <div className={cn('relative flex items-center', className)}>
      <Search
        className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-[hsl(var(--muted-foreground))] pointer-events-none"
        aria-hidden
      />
      <Input
        value={draft}
        onChange={(e) => schedule(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter') flush(draft);
          else if (e.key === 'Escape') flush('');
        }}
        placeholder={placeholder}
        autoFocus={autoFocus}
        className="pl-8 pr-14 h-8"
        aria-label={placeholder}
      />
      {draft && (
        <button
          type="button"
          onClick={() => flush('')}
          className="absolute right-2 top-1/2 -translate-y-1/2 text-[hsl(var(--muted-foreground))] hover:text-[hsl(var(--foreground))] transition-colors"
          aria-label="Clear search"
          tabIndex={-1}
        >
          <X className="w-3.5 h-3.5" />
        </button>
      )}
      {count !== undefined && !draft && (
        <span className="absolute right-2.5 top-1/2 -translate-y-1/2 text-[0.6875rem] text-[hsl(var(--muted-foreground))] tabular-nums pointer-events-none">
          {count}
        </span>
      )}
    </div>
  );
}

export default SearchInput;
