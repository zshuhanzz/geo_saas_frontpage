import type { ReactNode } from 'react';
import { Building2, Loader2, LockKeyhole, ShieldCheck } from 'lucide-react';
import { useTranslation } from 'react-i18next';
import { useLocation } from 'react-router-dom';

import { useSaaS } from '@/contexts/SaaSContext';
import { resolveFeatureForPath } from '@/lib/featureAccess';

function FeatureAccessLoading() {
    const { t } = useTranslation('common');
    return (
        <div className="flex min-h-[calc(100vh-3rem)] items-center justify-center rounded-2xl border bg-background">
            <div className="flex items-center gap-3 text-sm text-muted-foreground">
                <Loader2 className="h-5 w-5 animate-spin" />
                <span>{t('access.loading')}</span>
            </div>
        </div>
    );
}

function NoActiveWorkspace() {
    const { t } = useTranslation('common');
    return (
        <div className="flex min-h-[calc(100vh-3rem)] items-center justify-center rounded-2xl border bg-background">
            <section className="w-full max-w-md rounded-2xl border bg-card p-8 text-center shadow-sm">
                <Building2 className="mx-auto h-8 w-8 text-muted-foreground" />
                <h1 className="mt-5 text-xl font-semibold">{t('access.noWorkspaceTitle')}</h1>
                <p className="mt-2 text-sm leading-6 text-muted-foreground">
                    {t('access.noWorkspaceDescription')}
                </p>
            </section>
        </div>
    );
}

function LockedFeature({
    title,
    description,
    reason,
}: {
    title: string;
    description: string;
    reason: 'workspace' | 'role';
}) {
    const { t } = useTranslation('common');
    return (
        <div className="relative flex min-h-[calc(100vh-3rem)] items-center justify-center overflow-hidden rounded-2xl border bg-background">
            <div
                aria-hidden
                className="absolute inset-0 opacity-60 blur-md"
                style={{
                    background: 'radial-gradient(circle at 20% 20%, hsl(var(--primary) / 0.16), transparent 34%), radial-gradient(circle at 80% 70%, hsl(var(--muted-foreground) / 0.12), transparent 30%)',
                }}
            />
            <section className="relative z-10 w-full max-w-lg rounded-2xl border bg-card/95 p-8 shadow-xl backdrop-blur">
                <div className="mb-12 inline-flex items-center gap-2 rounded-full border bg-muted/40 px-3 py-1.5 text-xs font-medium text-muted-foreground">
                    <LockKeyhole className="h-3.5 w-3.5" />
                    {t('access.lockedBadge')}
                </div>
                <h1 className="text-2xl font-semibold tracking-tight">{title}</h1>
                <p className="mt-3 text-sm leading-6 text-muted-foreground">{description}</p>
                <div className="mt-12 flex items-start gap-3 rounded-xl border bg-muted/35 p-4">
                    <ShieldCheck className="mt-0.5 h-4 w-4 shrink-0 text-muted-foreground" />
                    <div>
                        <p className="text-sm font-medium">
                            {reason === 'workspace'
                                ? t('access.workspaceLockedTitle')
                                : t('access.roleLockedTitle')}
                        </p>
                        <p className="mt-1 text-xs leading-5 text-muted-foreground">
                            {reason === 'workspace'
                                ? t('access.workspaceLockedDescription')
                                : t('access.roleLockedDescription')}
                        </p>
                    </div>
                </div>
            </section>
        </div>
    );
}

export function FeatureAccessBoundary({ children }: { children: ReactNode }) {
    const { i18n, t } = useTranslation('common');
    const location = useLocation();
    const {
        activeClient,
        can,
        featureCatalog,
        isEntitled,
        loadingClients,
        loadingWorkspaceContext,
    } = useSaaS();
    const feature = resolveFeatureForPath(location.pathname);

    // DEV BYPASS: skip all access checks in dev auth mode
    if (import.meta.env.VITE_DEV_AUTH_USER_EMAIL) return <>{children}</>;

    if (!feature) return <>{children}</>;
    if (loadingClients) return <FeatureAccessLoading />;
    if (loadingWorkspaceContext) return <FeatureAccessLoading />;
    if (!activeClient) return <NoActiveWorkspace />;

    const managedFeature = featureCatalog[feature.key];
    const title = i18n.language.startsWith('zh')
        ? managedFeature?.display_name_zh || feature.label_zh
        : managedFeature?.display_name_en || feature.label_en;
    const description = i18n.language.startsWith('zh')
        ? managedFeature?.description_zh || feature.description_zh
        : managedFeature?.description_en || feature.description_en;

    if (!isEntitled(feature.key)) {
        return (
            <LockedFeature
                title={title}
                description={description}
                reason="workspace"
            />
        );
    }

    if (!can(feature.key, 'view')) {
        return (
            <LockedFeature
                title={title}
                description={description}
                reason="role"
            />
        );
    }

    const readOnly = !can(feature.key, 'execute') && !can(feature.key, 'manage');
    return (
        <>
            {readOnly && (
                <div className="mb-4 flex items-center gap-2 rounded-lg border bg-muted/35 px-4 py-2.5 text-sm text-muted-foreground">
                    <ShieldCheck className="h-4 w-4 shrink-0" />
                    <span>{t('access.readOnly')}</span>
                </div>
            )}
            {children}
        </>
    );
}
