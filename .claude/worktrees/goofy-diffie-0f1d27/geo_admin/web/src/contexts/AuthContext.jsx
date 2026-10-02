import { createContext, useContext, useState, useEffect } from 'react';
import { jwtDecode } from 'jwt-decode';

const AuthContext = createContext(null);

// 允许访问的邮箱列表 (可以是特定邮箱或域名)
const ALLOWED_EMAILS = [
    // 添加你的邮箱
];

const ALLOWED_DOMAINS = [
    // 添加允许的域名，例如 '@yourcompany.com'
];

function isEmailAllowed(email) {
    // 如果没有配置限制，允许所有 Google 用户
    if (ALLOWED_EMAILS.length === 0 && ALLOWED_DOMAINS.length === 0) {
        return true;
    }

    // 检查邮箱白名单
    if (ALLOWED_EMAILS.includes(email)) {
        return true;
    }

    // 检查域名白名单
    for (const domain of ALLOWED_DOMAINS) {
        if (email.endsWith(domain)) {
            return true;
        }
    }

    return false;
}

export function AuthProvider({ children }) {
    const [user, setUser] = useState(null);
    const [loading, setLoading] = useState(true);

    useEffect(() => {
        // 检查本地存储的 token
        const token = localStorage.getItem('geo_admin_token');
        if (token) {
            try {
                const decoded = jwtDecode(token);
                // 检查 token 是否过期
                if (decoded.exp * 1000 > Date.now()) {
                    setUser({
                        email: decoded.email,
                        name: decoded.name,
                        picture: decoded.picture,
                    });
                } else {
                    localStorage.removeItem('geo_admin_token');
                }
            } catch (err) {
                console.error('Invalid token:', err);
                localStorage.removeItem('geo_admin_token');
            }
        }
        setLoading(false);
    }, []);

    function login(credential) {
        try {
            const decoded = jwtDecode(credential);

            // 检查邮箱是否允许访问
            if (!isEmailAllowed(decoded.email)) {
                return { success: false, error: `邮箱 ${decoded.email} 没有访问权限` };
            }

            localStorage.setItem('geo_admin_token', credential);
            setUser({
                email: decoded.email,
                name: decoded.name,
                picture: decoded.picture,
            });
            return { success: true };
        } catch (err) {
            return { success: false, error: '登录失败' };
        }
    }

    function logout() {
        localStorage.removeItem('geo_admin_token');
        setUser(null);
    }

    return (
        <AuthContext.Provider value={{ user, loading, login, logout }}>
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
