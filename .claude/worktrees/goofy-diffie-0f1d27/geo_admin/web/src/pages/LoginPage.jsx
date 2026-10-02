import { GoogleLogin } from '@react-oauth/google';
import { useAuth } from '../contexts/AuthContext';
import { useState } from 'react';

export default function LoginPage() {
    const { login } = useAuth();
    const [error, setError] = useState(null);

    function handleSuccess(response) {
        const result = login(response.credential);
        if (!result.success) {
            setError(result.error);
        }
    }

    function handleError() {
        setError('Google 登录失败，请重试');
    }

    return (
        <div className="min-h-screen bg-dark-950 flex items-center justify-center">
            <div className="glass-card p-8 max-w-md w-full mx-4">
                <div className="text-center mb-8">
                    {/* Logo */}
                    <div className="flex justify-center mb-4">
                        <img src="/logo.png" alt="AnswerX Logo" className="h-16 w-auto" />
                    </div>
                    <h1 className="text-2xl font-bold text-white">AnswerX GEO Admin</h1>
                    <p className="text-dark-400 mt-2">内部管理后台</p>
                </div>

                {error && (
                    <div className="mb-6 p-4 bg-red-500/20 border border-red-500/30 rounded-lg text-red-400 text-sm text-center">
                        {error}
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

                <p className="text-dark-500 text-xs text-center mt-6">
                    仅限授权用户访问
                </p>
            </div>
        </div>
    );
}
