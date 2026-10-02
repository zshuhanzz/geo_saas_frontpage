import React from 'react'
import ReactDOM from 'react-dom/client'
import { GoogleOAuthProvider } from '@react-oauth/google'
import { AuthProvider } from './contexts/AuthContext'
import { ThemeProvider } from './components/theme-provider'
import { ToastProvider, ConfirmProvider } from './components/Toast'
import App from './App'
import './index.css'

// TODO: 替换为你的 Google OAuth Client ID
const GOOGLE_CLIENT_ID = (import.meta.env.VITE_GOOGLE_CLIENT_ID as string | undefined) || 'YOUR_GOOGLE_CLIENT_ID';

const rootElement = document.getElementById('root');
if (!rootElement) {
    throw new Error('Root element #root not found');
}

ReactDOM.createRoot(rootElement).render(
    <React.StrictMode>
        <GoogleOAuthProvider clientId={GOOGLE_CLIENT_ID}>
            <ThemeProvider defaultTheme="system" storageKey="geo-admin-theme">
                <AuthProvider>
                    <ToastProvider>
                        <ConfirmProvider>
                            <App />
                        </ConfirmProvider>
                    </ToastProvider>
                </AuthProvider>
            </ThemeProvider>
        </GoogleOAuthProvider>
    </React.StrictMode>,
)
