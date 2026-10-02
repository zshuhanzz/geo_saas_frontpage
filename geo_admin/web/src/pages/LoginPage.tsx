import { GoogleLogin, type CredentialResponse } from '@react-oauth/google';
import { useAuth } from '../contexts/AuthContext';
import { useState } from 'react';

export default function LoginPage() {
    const { login, restoreError, retrySession } = useAuth();
    const [error, setError] = useState<string | null>(null);

    async function handleSuccess(response: CredentialResponse) {
        if (!response.credential) {
            setError('Google 登录失败：无 credential 返回');
            return;
        }
        const result = await login(response.credential);
        if (!result.success) {
            setError(result.error || '登录失败');
        }
    }

    function handleError() {
        setError('Google 登录失败，请重试');
    }

    return (
        <div className="min-h-screen bg-background flex items-center justify-center">
            <div className="bg-card text-card-foreground border rounded-xl shadow-md p-8 max-w-md w-full mx-4">
                <div className="text-center mb-8">
                    {/* Logo */}
                    <div className="flex justify-center mb-4">
                        <img src="/logo.png" alt="AnswerX Logo" className="h-16 w-auto" />
                    </div>
                    <h1 className="text-2xl font-bold text-foreground">AnswerX GEO Admin</h1>
                    <p className="text-muted-foreground mt-2">内部管理后台</p>
                </div>

                {error && (
                    <div className="mb-6 p-4 bg-red-500/20 border border-red-500/30 rounded-lg text-red-400 text-sm text-center">
                        {error}
                    </div>
                )}
                {restoreError && (
                    <div className="mb-6 p-4 bg-red-500/20 border border-red-500/30 rounded-lg text-red-400 text-sm text-center">
                        <p>暂时无法恢复登录状态，请检查网络后重试。</p>
                        <button
                            type="button"
                            className="mt-3 underline underline-offset-4"
                            onClick={() => void retrySession()}
                        >
                            重试
                        </button>
                    </div>
                )}

                <div className="flex justify-center">
                    <GoogleLogin
                        onSuccess={handleSuccess}
                        onError={handleError}
                        theme="filled_black"
                        size="large"
                        text="signin_with"
                        shape="rectangular"
                        width="280"
                    />
                </div>

                <p className="text-muted-foreground text-xs text-center mt-6">
                    仅限授权用户访问
                </p>
            </div>
        </div>
    );
}
