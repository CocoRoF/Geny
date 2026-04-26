'use client';

import { Toaster as Sonner } from 'sonner';
import { useEffect, useState } from 'react';

type ToasterProps = React.ComponentProps<typeof Sonner>;

/**
 * Sonner toast surface — themed via Geny's html.dark/light class.
 * Mounted once at the root layout.
 */
export function Toaster({ ...props }: ToasterProps) {
  const [theme, setTheme] = useState<'light' | 'dark'>('dark');

  useEffect(() => {
    const root = document.documentElement;
    const sync = () =>
      setTheme(root.classList.contains('dark') ? 'dark' : 'light');
    sync();
    const obs = new MutationObserver(sync);
    obs.observe(root, { attributes: true, attributeFilter: ['class'] });
    return () => obs.disconnect();
  }, []);

  return (
    <Sonner
      theme={theme}
      className="toaster group"
      toastOptions={{
        classNames: {
          toast:
            'group toast group-[.toaster]:bg-[hsl(var(--card))] group-[.toaster]:text-[hsl(var(--card-foreground))] group-[.toaster]:border-[hsl(var(--border))] group-[.toaster]:shadow-lg',
          description: 'group-[.toast]:text-[hsl(var(--muted-foreground))]',
          actionButton:
            'group-[.toast]:bg-[hsl(var(--primary))] group-[.toast]:text-[hsl(var(--primary-foreground))]',
          cancelButton:
            'group-[.toast]:bg-[hsl(var(--muted))] group-[.toast]:text-[hsl(var(--muted-foreground))]',
        },
      }}
      {...props}
    />
  );
}
