import { StrictMode, Suspense } from 'react'
import { createRoot } from 'react-dom/client'
import { GoogleOAuthProvider } from '@react-oauth/google'
import { I18nextProvider } from 'react-i18next'
import { AuthProvider } from './contexts/AuthContext'
import { ThemeProvider } from './components/theme-provider'
import i18n from './i18n'
import './i18n/types'
import './index.css'
import App from './App.tsx'

const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID || 'YOUR_GOOGLE_CLIENT_ID';

function I18nSplash() {
  return (
    <div className="min-h-screen flex items-center justify-center bg-background">
      <div className="animate-spin rounded-full h-8 w-8 border-b-2 border-primary"></div>
    </div>
  );
}

createRoot(document.getElementById('root')!).render(
  <StrictMode>
    <I18nextProvider i18n={i18n}>
      <Suspense fallback={<I18nSplash />}>
        <GoogleOAuthProvider clientId={GOOGLE_CLIENT_ID}>
          <ThemeProvider defaultTheme="system" storageKey="geo-saas-theme">
            <AuthProvider>
              <App />
            </AuthProvider>
          </ThemeProvider>
        </GoogleOAuthProvider>
      </Suspense>
    </I18nextProvider>
  </StrictMode>,
)
