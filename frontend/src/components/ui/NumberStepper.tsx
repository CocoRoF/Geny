'use client';

import { useCallback, useRef, useEffect } from 'react';
import { twMerge } from 'tailwind-merge';

function cn(...classes: (string | boolean | undefined | null)[]) {
  return twMerge(classes.filter(Boolean).join(' '));
}

interface Props {
  value: number;
  onChange: (v: number) => void;
  min?: number;
  max?: number;
  step?: number;
}

/* ── Shared Tailwind strings ── */
const WRAP =
  'flex flex-row items-stretch h-[42px] border border-[var(--border-subtle)] rounded-[6px] overflow-hidden bg-[var(--bg-secondary)] transition-all duration-150 focus-within:border-[var(--primary-color)] focus-within:shadow-[0_0_0_3px_rgba(59,130,246,0.15)]';

const BTN =
  'flex items-center justify-center w-[38px] min-w-[38px] h-full border-none bg-transparent text-[var(--text-muted)] cursor-pointer transition-all duration-[120ms] p-0 m-0 shrink-0 leading-none hover:bg-[var(--bg-tertiary)] hover:text-[var(--text-primary)] active:bg-[var(--primary-color)] active:text-white';

const BTN_DISABLED = 'opacity-25 !cursor-not-allowed';

const VALUE =
  'flex-1 min-w-0 w-auto border-none bg-transparent text-center text-[0.875rem] font-semibold tabular-nums text-[var(--text-primary)] p-0 px-1 m-0 rounded-none shadow-none outline-none [appearance:textfield] [&::-webkit-outer-spin-button]:appearance-none [&::-webkit-inner-spin-button]:appearance-none';

export default function NumberStepper({ value, onChange, min = 1, max = 9999, step = 1 }: Props) {
  const intervalRef = useRef<ReturnType<typeof setInterval> | null>(null);
  const timeoutRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const valueRef = useRef(value);
  valueRef.current = value;

  const clamp = useCallback((v: number) => Math.min(max, Math.max(min, v)), [min, max]);

  const stopRepeat = useCallback(() => {
    if (timeoutRef.current) { clearTimeout(timeoutRef.current); timeoutRef.current = null; }
    if (intervalRef.current) { clearInterval(intervalRef.current); intervalRef.current = null; }
  }, []);

  useEffect(() => stopRepeat, [stopRepeat]);

  const startRepeat = (delta: number) => {
    onChange(clamp(value + delta));
    timeoutRef.current = setTimeout(() => {
      intervalRef.current = setInterval(() => {
        valueRef.current = clamp(valueRef.current + delta);
        onChange(valueRef.current);
      }, 75);
    }, 400);
  };

  const atMin = value <= min;
  const atMax = value >= max;

  return (
    <div className={WRAP}>
      <button
        type="button"
        className={cn(BTN, 'border-r border-r-[var(--border-subtle)] rounded-l-[6px]', atMin && BTN_DISABLED)}
        disabled={atMin}
        onMouseDown={() => startRepeat(-step)}
        onMouseUp={stopRepeat}
        onMouseLeave={stopRepeat}
        tabIndex={-1}
        aria-label="Decrease"
      >
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
          <path d="M2.5 6h7" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
        </svg>
      </button>

      <input
        type="text"
        inputMode="numeric"
        className={VALUE}
        value={value}
        onChange={e => {
          const raw = e.target.value.replace(/[^0-9]/g, '');
          if (raw === '') return;
          onChange(clamp(parseInt(raw)));
        }}
        onBlur={() => onChange(clamp(value))}
      />

      <button
        type="button"
        className={cn(BTN, 'border-l border-l-[var(--border-subtle)] rounded-r-[6px]', atMax && BTN_DISABLED)}
        disabled={atMax}
        onMouseDown={() => startRepeat(step)}
        onMouseUp={stopRepeat}
        onMouseLeave={stopRepeat}
        tabIndex={-1}
        aria-label="Increase"
      >
        <svg width="12" height="12" viewBox="0 0 12 12" fill="none">
          <path d="M6 2.5v7M2.5 6h7" stroke="currentColor" strokeWidth="1.6" strokeLinecap="round" />
        </svg>
      </button>
    </div>
  );
}
