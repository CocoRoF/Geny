'use client';

import { useState, useRef, useCallback, useEffect } from 'react';
import { createPortal } from 'react-dom';
import { Info } from 'lucide-react';

interface Props {
  text: string;
  children?: React.ReactNode;
}

/**
 * Polished info-tooltip. Renders a small ⓘ icon that shows a floating
 * tooltip on hover with a smooth fade + slide animation.
 *
 * Uses a React Portal to render at document.body level so tooltips
 * are never clipped by parent overflow containers.
 */
export default function InfoTooltip({ text }: Props) {
  const [visible, setVisible] = useState(false);
  const [position, setPosition] = useState<'top' | 'bottom'>('top');
  const [coords, setCoords] = useState({ x: 0, y: 0 });
  const triggerRef = useRef<HTMLSpanElement>(null);
  const timerRef = useRef<ReturnType<typeof setTimeout> | null>(null);
  const [mounted, setMounted] = useState(false);

  useEffect(() => { setMounted(true); }, []);

  const updatePosition = useCallback(() => {
    if (!triggerRef.current) return;
    const rect = triggerRef.current.getBoundingClientRect();
    const centerX = rect.left + rect.width / 2;
    const above = rect.top > 80;
    setPosition(above ? 'top' : 'bottom');
    setCoords({
      x: centerX,
      y: above ? rect.top - 8 : rect.bottom + 8,
    });
  }, []);

  const show = useCallback(() => {
    if (timerRef.current) clearTimeout(timerRef.current);
    updatePosition();
    setVisible(true);
  }, [updatePosition]);

  const hide = useCallback(() => {
    timerRef.current = setTimeout(() => setVisible(false), 120);
  }, []);

  useEffect(() => () => { if (timerRef.current) clearTimeout(timerRef.current); }, []);

  const isTop = position === 'top';

  const tooltip = mounted && (visible || coords.x !== 0) ? createPortal(
    <div
      role="tooltip"
      style={{
        position: 'fixed',
        left: `${coords.x}px`,
        top: isTop ? undefined : `${coords.y}px`,
        bottom: isTop ? `${window.innerHeight - coords.y}px` : undefined,
        transform: 'translateX(-50%)',
        zIndex: 10000,
      }}
      className={[
        'pointer-events-none',
        'w-max max-w-[260px] px-3 py-2',
        'rounded-lg',
        'bg-[var(--bg-tertiary)] border border-[var(--border-color)]',
        'shadow-[0_4px_16px_rgba(0,0,0,0.25)]',
        'text-[0.75rem] leading-[1.45] text-[var(--text-secondary)] font-normal',
        'transition-all duration-200 ease-out',
        visible
          ? 'opacity-100 scale-100 translate-y-0'
          : isTop
            ? 'opacity-0 scale-95 translate-y-1'
            : 'opacity-0 scale-95 -translate-y-1',
      ].join(' ')}
    >
      {text}
      {/* Arrow */}
      <span
        className={[
          'absolute left-1/2 -translate-x-1/2 w-2 h-2 rotate-45',
          'bg-[var(--bg-tertiary)] border-[var(--border-color)]',
          isTop
            ? 'bottom-[-5px] border-r border-b'
            : 'top-[-5px] border-l border-t',
        ].join(' ')}
      />
    </div>,
    document.body,
  ) : null;

  return (
    <>
      <span
        ref={triggerRef}
        className="relative inline-flex items-center"
        onMouseEnter={show}
        onMouseLeave={hide}
        onFocus={show}
        onBlur={hide}
      >
        <Info
          size={14}
          strokeWidth={1.8}
          className="text-[var(--text-muted)] cursor-help hover:text-[var(--primary-color)] transition-colors duration-150"
        />
      </span>
      {tooltip}
    </>
  );
}
