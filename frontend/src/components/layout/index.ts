/**
 * Shared layout primitives — see each module for usage.
 *
 * Convention: every tab (excluding Playground / Playground2D /
 * VTuber / Command / Chat) wraps its body in TabShell. Two-pane
 * tabs nest TwoPaneBody inside; CRUD tabs use EditorModal for
 * Add/Edit. EmptyState + StatusBadge + ActionButton replace
 * scattered ad-hoc inline styles.
 */

export { TabShell, type TabShellProps } from './TabShell';
export { TwoPaneBody, type TwoPaneBodyProps } from './TwoPaneBody';
export { DetailDrawer, type DetailDrawerProps } from './DetailDrawer';
export { EditorModal, type EditorModalProps } from './EditorModal';
export { EmptyState, type EmptyStateProps } from './EmptyState';
export { StatusBadge, type StatusBadgeProps, type BadgeTone } from './StatusBadge';
export { ActionButton, type ActionButtonProps } from './ActionButton';
export { cn } from './cn';
