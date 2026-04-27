/**
 * Shared layout primitives — see each module for usage.
 *
 * Convention: every tab (excluding Playground / Playground2D /
 * VTuber / Command / Chat) wraps its body in TabShell. Two-pane
 * tabs nest TwoPaneBody inside; CRUD tabs use EditorModal for
 * Add/Edit. EmptyState + StatusBadge + ActionButton replace
 * scattered ad-hoc inline styles.
 *
 * Toolbar primitives (TabToolbar / SearchInput / FilterPills /
 * SortMenu / BulkActionBar / ResultsGrid / TabFooter) keep search,
 * filter, sort, and selection chrome OUT of each tab's body so
 * the body owns only the result view itself.
 */

export { TabShell, type TabShellProps } from './TabShell';
export { TwoPaneBody, type TwoPaneBodyProps } from './TwoPaneBody';
export { DetailDrawer, type DetailDrawerProps } from './DetailDrawer';
export { EditorModal, type EditorModalProps } from './EditorModal';
export { EmptyState, type EmptyStateProps } from './EmptyState';
export { StatusBadge, type StatusBadgeProps, type BadgeTone } from './StatusBadge';
export { ActionButton, type ActionButtonProps } from './ActionButton';
export { SubTabNav, type SubTabNavProps, type SubTabDef } from './SubTabNav';
export { NextSessionBanner, type NextSessionBannerProps } from './NextSessionBanner';

export { TabToolbar, type TabToolbarProps } from './TabToolbar';
export { SearchInput, type SearchInputProps } from './SearchInput';
export {
  FilterPills,
  type FilterPillsProps,
  type FilterPillsSingleProps,
  type FilterPillsMultiProps,
  type FilterPillDef,
} from './FilterPills';
export {
  SortMenu,
  type SortMenuProps,
  type SortOptionDef,
  type SortDirection,
} from './SortMenu';
export { BulkActionBar, type BulkActionBarProps } from './BulkActionBar';
export { ResultsGrid, type ResultsGridProps } from './ResultsGrid';
export { TabFooter, CountSummary, type TabFooterProps, type CountSummaryProps } from './TabFooter';

export { cn } from './cn';
