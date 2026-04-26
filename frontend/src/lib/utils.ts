/**
 * shadcn-style utility helper. Re-exports the same `cn()` the layout
 * primitives already use so component files copied from shadcn's
 * registry don't need their import path rewritten.
 */
import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
