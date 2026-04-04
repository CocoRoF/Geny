'use client';

import { useEffect } from 'react';
import { useRouter } from 'next/navigation';
import { useAuthStore } from '@/store/useAuthStore';
import { useI18n } from '@/lib/i18n';

/**
 * AuthGuard — wraps pages/components that require authentication.
 *
 * Behaviour:
 *   - If no users exist yet → redirect to /setup
 *   - If users exist but not authenticated → show nothing (parent should show LoginModal)
 *   - If authenticated → render children
 *   - While loading → show spinner
 */
export default function AuthGuard({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const { t } = useI18n();
  const { initialized, isLoading, hasUsers, isAuthenticated, checkAuth } = useAuthStore();

  useEffect(() => {
    if (!initialized) checkAuth();
  }, [initialized, checkAuth]);

  // Redirect to setup if no admin exists
  useEffect(() => {
    if (initialized && !hasUsers) {
      router.replace('/setup');
    }
  }, [initialized, hasUsers, router]);

  if (isLoading || !initialized) {
    return (
      <div className="flex items-center justify-center h-full">
        <div className="text-[var(--text-muted)] text-sm">{t('common.loading')}</div>
      </div>
    );
  }

  if (!hasUsers) return null;
  if (!isAuthenticated) return null;

  return <>{children}</>;
}
