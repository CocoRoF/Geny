'use client';

/**
 * EditorModal — Add/Edit modal scaffold (shadcn-backed).
 *
 * Wraps shadcn's Dialog with the same prop API the existing tabs use.
 * `width` maps to a max-w preset; `saving` disables the close behavior;
 * `error` renders inline above the body.
 */

import { ReactNode } from 'react';
import { AlertCircle } from 'lucide-react';
import {
  Dialog,
  DialogContent,
  DialogHeader,
  DialogTitle,
  DialogFooter,
  DialogCloseButton,
} from '@/components/ui/dialog';
import { cn } from './cn';

export interface EditorModalProps {
  open: boolean;
  onClose: () => void;
  title: ReactNode;
  saving?: boolean;
  footer?: ReactNode;
  width?: 'sm' | 'md' | 'lg' | 'xl';
  error?: string | null;
  children: ReactNode;
}

const WIDTH: Record<NonNullable<EditorModalProps['width']>, string> = {
  sm: 'max-w-sm',
  md: 'max-w-md',
  lg: 'max-w-lg',
  xl: 'max-w-2xl',
};

export function EditorModal({
  open,
  onClose,
  title,
  saving = false,
  footer,
  width = 'md',
  error,
  children,
}: EditorModalProps) {
  return (
    <Dialog
      open={open}
      onOpenChange={(next) => {
        if (!next && !saving) onClose();
      }}
    >
      <DialogContent
        className={cn(WIDTH[width], 'p-0 max-h-[85vh] flex flex-col gap-0')}
        onPointerDownOutside={(e) => {
          if (saving) e.preventDefault();
        }}
        onEscapeKeyDown={(e) => {
          if (saving) e.preventDefault();
        }}
      >
        <DialogHeader>
          <DialogTitle className="flex-1 truncate">{title}</DialogTitle>
          <DialogCloseButton />
        </DialogHeader>
        <div className="overflow-y-auto p-4 flex-1 min-h-0">
          {error && (
            <div
              className="mb-3 text-xs text-red-700 dark:text-red-300 bg-red-500/10 border border-red-500/30 rounded-md px-2.5 py-2 flex items-start gap-1.5"
              role="alert"
            >
              <AlertCircle className="w-3 h-3 mt-0.5 shrink-0" />
              <span>{error}</span>
            </div>
          )}
          {children}
        </div>
        {footer && <DialogFooter>{footer}</DialogFooter>}
      </DialogContent>
    </Dialog>
  );
}

export default EditorModal;
