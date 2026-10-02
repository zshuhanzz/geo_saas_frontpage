import { createContext, useContext, useEffect, useState, type ReactNode } from 'react';
import { AUTH_EXPIRED_EVENT } from '../api/client';

export interface AuthUser {
    email: string;
    name: string;
    picture: string;
}

export interface LoginResult {
    success: boolean;
    error?: string;
}

interface SessionUser {
    id: string;
    email: string;
    google_sub?: string | null;
    name?: string | null;
    avatar_url?: string | null;
    is_active: boolean;
}

interface SessionLoginResponse {
    user: SessionUser;
    expires_at: string;
}

interface AccessControlMeResponse {
    user: SessionUser;
}

interface AuthContextValue {
    user: AuthUser | null;
    loading: boolean;
    restoreError: string | null;
    login: (credential: string) => Promise<LoginResult>;
    logout: () => Promise<void>;
    retrySession: () => Promise<void>;
}

const AuthContext = createContext<AuthContextValue | null>(null);

function toAuthUser(user: SessionUser): AuthUser {
    return {
        email: user.email,
        name: user.name || user.email,
        picture: user.avatar_url || '',
    };
}

async function parseErrorMessage(response: Response, fallback: string): Promise<string> {
    const body = await response.json().catch(() => null) as {
        detail?: string | { message?: string };
        message?: string;
    } | null;
    if (typeof body?.detail === 'string') return body.detail;
    if (body?.detail && typeof body.detail === 'object' && body.detail.message) {
        return body.detail.message;
    }
    if (typeof body?.message === 'string') return body.message;
    return fallback;
}

export function AuthProvider({ children }: { children: ReactNode }) {
    const [user, setUser] = useState<AuthUser | null>(null);
    const [loading, setLoading] = useState(true);
    const [restoreError, setRestoreError] = useState<string | null>(null);

    function clearAuthState() {
        // Remove credentials written by releases before server Sessions.
        localStorage.removeItem('geo_admin_token');
        setUser(null);
    }

    async function retrySession() {
        setLoading(true);
        setRestoreError(null);
        try {
            const response = await fetch('/api/access-control/me', {
                credentials: 'same-origin',
                headers: {
                    ...(import.meta.env.VITE_DEV_AUTH_USER_EMAIL
                        ? { 'X-Dev-User-Email': import.meta.env.VITE_DEV_AUTH_USER_EMAIL as string }
                        : {}),
                },
            });
            if (response.status === 401 || response.status === 403) {
                clearAuthState();
                return;
            }
            if (!response.ok) {
                throw new Error(await parseErrorMessage(response, '无法恢复登录状态'));
            }
            const result = await response.json() as AccessControlMeResponse;
            setUser(toAuthUser(result.user));
        } catch (error) {
            setRestoreError(error instanceof Error ? error.message : '无法恢复登录状态');
        } finally {
            setLoading(false);
        }
    }

    useEffect(() => {
        function handleAuthExpired() {
            clearAuthState();
        }
        window.addEventListener(AUTH_EXPIRED_EVENT, handleAuthExpired);

        const devEmail = import.meta.env.VITE_DEV_AUTH_USER_EMAIL as string | undefined;
        if (devEmail) {
            console.warn('[AuthContext] Dev-mode auth bypass active. DO NOT use in production.');
            setUser({
                email: devEmail,
                name: import.meta.env.VITE_DEV_AUTH_USER_NAME || 'Dev User',
                picture: '',
            });
            setLoading(false);
        } else {
            localStorage.removeItem('geo_admin_token');
            void retrySession();
        }

        return () => window.removeEventListener(AUTH_EXPIRED_EVENT, handleAuthExpired);
    }, []);

    async function login(credential: string): Promise<LoginResult> {
        setRestoreError(null);
        try {
            const response = await fetch('/api/auth/session', {
                method: 'POST',
                credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ credential }),
            });
            if (!response.ok) {
                return {
                    success: false,
                    error: await parseErrorMessage(response, '登录失败'),
                };
            }
            const result = await response.json() as SessionLoginResponse;
            setUser(toAuthUser(result.user));
            return { success: true };
        } catch (error) {
            return {
                success: false,
                error: error instanceof Error ? error.message : '登录失败',
            };
        }
    }

    async function logout() {
        try {
            await fetch('/api/auth/logout', {
                method: 'POST',
                credentials: 'same-origin',
            });
        } finally {
            clearAuthState();
        }
    }

    return (
        <AuthContext.Provider
            value={{ user, loading, restoreError, login, logout, retrySession }}
        >
            {children}
        </AuthContext.Provider>
    );
}

export function useAuth(): AuthContextValue {
    const context = useContext(AuthContext);
    if (!context) {
        throw new Error('useAuth must be used within AuthProvider');
    }
    return context;
}
