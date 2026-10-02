import { createContext, useContext, useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { API_BASE, AUTH_EXPIRED_EVENT } from '@/lib/api/_base';

interface User {
    sub: string;
    email: string;
    name: string;
    picture: string;
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

interface AuthContextType {
    user: User | null;
    loading: boolean;
    restoreError: string | null;
    login: (credential: string) => Promise<{ success: boolean; error?: string }>;
    logout: () => Promise<void>;
    retrySession: () => Promise<void>;
}

const AuthContext = createContext<AuthContextType | null>(null);

function toUser(profile: SessionUser): User {
    return {
        sub: profile.google_sub || profile.id,
        email: profile.email,
        name: profile.name || profile.email,
        picture: profile.avatar_url || '',
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
    const [user, setUser] = useState<User | null>(null);
    const [loading, setLoading] = useState(true);
    const [restoreError, setRestoreError] = useState<string | null>(null);

    function clearAuthState() {
        // Remove credentials written by releases before server Sessions.
        localStorage.removeItem('geo_saas_token');
        localStorage.removeItem('geo_saas_client_id');
        setUser(null);
    }

    async function retrySession() {
        setLoading(true);
        setRestoreError(null);
        try {
            const response = await fetch(`${API_BASE}/me`, {
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
                throw new Error(await parseErrorMessage(response, 'Unable to restore login'));
            }
            setUser(toUser(await response.json() as SessionUser));
        } catch (error) {
            setRestoreError(
                error instanceof Error
                    ? error.message
                    : 'Unable to restore login',
            );
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
                sub: import.meta.env.VITE_DEV_AUTH_USER_SUB || 'dev-sub',
                email: devEmail,
                name: import.meta.env.VITE_DEV_AUTH_USER_NAME || 'Dev User',
                picture: '',
            });
            setLoading(false);
        } else {
            localStorage.removeItem('geo_saas_token');
            void retrySession();
        }

        return () => window.removeEventListener(AUTH_EXPIRED_EVENT, handleAuthExpired);
    }, []);

    async function login(credential: string) {
        setRestoreError(null);
        try {
            const response = await fetch(`${API_BASE}/auth/session`, {
                method: 'POST',
                credentials: 'same-origin',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ credential }),
            });
            if (!response.ok) {
                return {
                    success: false,
                    error: await parseErrorMessage(response, 'Login failed'),
                };
            }
            const result = await response.json() as SessionLoginResponse;
            setUser(toUser(result.user));
            return { success: true };
        } catch (error) {
            return {
                success: false,
                error: error instanceof Error ? error.message : 'Login failed',
            };
        }
    }

    async function logout() {
        try {
            await fetch(`${API_BASE}/auth/logout`, {
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

export function useAuth() {
    const context = useContext(AuthContext);
    if (!context) {
        throw new Error('useAuth must be used within AuthProvider');
    }
    return context;
}
