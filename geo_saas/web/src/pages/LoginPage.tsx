import { GoogleLogin } from '@react-oauth/google';
import { useAuth } from '../contexts/AuthContext';
import { useState } from 'react';
import { useTranslation } from 'react-i18next';

export default function LoginPage() {
    const { login, restoreError, retrySession } = useAuth();
    const { t } = useTranslation('common');
    const [error, setError] = useState<string | null>(null);

    async function handleSuccess(response: any) {
        const result = await login(response.credential);
        if (!result.success) {
            setError(result.error || t('login.loginFailed'));
        }
    }

    function handleError() {
        setError(t('login.googleFailed'));
    }

    return (
        <div className="min-h-screen bg-background flex items-center justify-center">
            <div className="border bg-card text-card-foreground shadow-sm p-8 max-w-md w-full mx-4 rounded-xl">
                <div className="text-center mb-8">
                    {/* Logo */}
                    <div className="flex justify-center mb-4">
                        <img src="/logo.png" alt="AnswerX Logo" className="h-16 w-auto" />
                    </div>
                    <h1 className="text-2xl font-bold tracking-tight">{t('login.welcome')}</h1>
                    <p className="text-muted-foreground mt-2 text-sm">{t('login.subtitle')}</p>
                </div>

                {error && (
                    <div className="mb-6 p-4 bg-destructive/10 border border-destructive/20 rounded-lg text-destructive text-sm text-center">
                        {error}
                    </div>
                )}
                {restoreError && (
                    <div className="mb-6 p-4 bg-destructive/10 border border-destructive/20 rounded-lg text-destructive text-sm text-center">
                        <p>{t('login.restoreFailed')}</p>
                        <button
                            type="button"
                            className="mt-3 underline underline-offset-4"
                            onClick={() => void retrySession()}
                        >
                            {t('actions.retry')}
                        </button>
                    </div>
                )}

                <div className="flex justify-center">
                    <GoogleLogin
                        onSuccess={handleSuccess}
                        onError={handleError}
                        size="large"
                        text="signin_with"
                        shape="rectangular"
                        width="280"
                    />
                </div>
            </div>
        </div>
    );
}
