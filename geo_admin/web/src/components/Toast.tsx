import { useState, useCallback, createContext, useContext, useEffect, type ReactNode } from 'react';
import { AUTH_EXPIRED_EVENT, SESSION_EXPIRED_MESSAGE } from '../api/client';

// ============================================================================
// Toast Context & Provider
// ============================================================================
type ToastType = 'success' | 'error' | 'info' | 'warning';

interface ToastItemModel {
    id: number;
    message: string;
    type: ToastType;
}

interface ToastApi {
    success: (msg: string) => void;
    error: (msg: string) => void;
    info: (msg: string) => void;
    warning: (msg: string) => void;
}

const ToastContext = createContext<ToastApi | null>(null);

interface ToastProviderProps {
    children: ReactNode;
}

export function ToastProvider({ children }: ToastProviderProps) {
    const [toasts, setToasts] = useState<ToastItemModel[]>([]);

    const addToast = useCallback((message: string, type: ToastType = 'info', duration: number = 4000) => {
        const id = Date.now() + Math.random();
        setToasts((prev) => [...prev, { id, message, type }]);
        setTimeout(() => {
            setToasts((prev) => prev.filter((t) => t.id !== id));
        }, duration);
    }, []);

    useEffect(() => {
        function handleAuthExpired(event: Event) {
            const message = (event as CustomEvent<string>).detail || SESSION_EXPIRED_MESSAGE;
            addToast(message, 'error', 6000);
        }

        window.addEventListener(AUTH_EXPIRED_EVENT, handleAuthExpired);
        return () => window.removeEventListener(AUTH_EXPIRED_EVENT, handleAuthExpired);
    }, [addToast]);

    // NOTE: original .jsx passed an object literal (not a function) into useCallback.
    // This is functionally a no-op — useCallback expects a function — but preserved
    // here verbatim to avoid behavioral drift during the migration. The toast object
    // actually consumed by context is `toastApi` below.
    // Cast to `any` so TS does not block the (legacy) misuse.
    // eslint-disable-next-line @typescript-eslint/no-explicit-any
    const toast = useCallback(({
        success: (msg: string) => addToast(msg, 'success'),
        error: (msg: string) => addToast(msg, 'error', 6000),
        info: (msg: string) => addToast(msg, 'info'),
        warning: (msg: string) => addToast(msg, 'warning', 5000),
    } as any), [addToast]);
    void toast;

    // Re-create toast object on each render so it has the latest addToast
    const toastApi: ToastApi = {
        success: (msg: string) => addToast(msg, 'success'),
        error: (msg: string) => addToast(msg, 'error', 6000),
        info: (msg: string) => addToast(msg, 'info'),
        warning: (msg: string) => addToast(msg, 'warning', 5000),
    };

    return (
        <ToastContext.Provider value={toastApi}>
            {children}
            <ToastContainer toasts={toasts} onDismiss={(id) => setToasts((prev) => prev.filter((t) => t.id !== id))} />
        </ToastContext.Provider>
    );
}

export function useToast(): ToastApi {
    const ctx = useContext(ToastContext);
    if (!ctx) throw new Error('useToast must be used within ToastProvider');
    return ctx;
}

// ============================================================================
// Toast Container & Toast Item
// ============================================================================
interface TypeStyle {
    bg: string;
    icon: string;
    iconBg: string;
    text: string;
}

const typeStyles: Record<ToastType, TypeStyle> = {
    success: {
        bg: 'bg-emerald-50 border-emerald-200 dark:bg-emerald-950/50 dark:border-emerald-800',
        icon: '✓',
        iconBg: 'bg-emerald-500',
        text: 'text-emerald-800 dark:text-emerald-200',
    },
    error: {
        bg: 'bg-red-50 border-red-200 dark:bg-red-950/50 dark:border-red-800',
        icon: '✕',
        iconBg: 'bg-red-500',
        text: 'text-red-800 dark:text-red-200',
    },
    info: {
        bg: 'bg-blue-50 border-blue-200 dark:bg-blue-950/50 dark:border-blue-800',
        icon: 'ℹ',
        iconBg: 'bg-blue-500',
        text: 'text-blue-800 dark:text-blue-200',
    },
    warning: {
        bg: 'bg-amber-50 border-amber-200 dark:bg-amber-950/50 dark:border-amber-800',
        icon: '⚠',
        iconBg: 'bg-amber-500',
        text: 'text-amber-800 dark:text-amber-200',
    },
};

interface ToastContainerProps {
    toasts: ToastItemModel[];
    onDismiss: (id: number) => void;
}

function ToastContainer({ toasts, onDismiss }: ToastContainerProps) {
    return (
        <div className="fixed top-4 right-4 z-[9999] flex flex-col gap-3 max-w-sm w-full pointer-events-none">
            {toasts.map((t) => (
                <ToastItem key={t.id} toast={t} onDismiss={() => onDismiss(t.id)} />
            ))}
        </div>
    );
}

interface ToastItemProps {
    toast: ToastItemModel;
    onDismiss: () => void;
}

function ToastItem({ toast, onDismiss }: ToastItemProps) {
    const style = typeStyles[toast.type] || typeStyles.info;
    return (
        <div
            className={`pointer-events-auto flex items-start gap-3 p-4 rounded-lg border shadow-lg backdrop-blur-sm animate-slide-in ${style.bg}`}
        >
            <span className={`flex-shrink-0 w-6 h-6 rounded-full ${style.iconBg} text-white flex items-center justify-center text-xs font-bold`}>
                {style.icon}
            </span>
            <p className={`flex-1 text-sm font-medium leading-5 ${style.text}`}>{toast.message}</p>
            <button
                onClick={onDismiss}
                className={`flex-shrink-0 p-0.5 rounded hover:bg-black/10 dark:hover:bg-white/10 transition-colors ${style.text}`}
            >
                <svg width="14" height="14" viewBox="0 0 14 14" fill="currentColor">
                    <path d="M4.646 4.646a.5.5 0 0 1 .708 0L7 6.293l1.646-1.647a.5.5 0 0 1 .708.708L7.707 7l1.647 1.646a.5.5 0 0 1-.708.708L7 7.707l-1.646 1.647a.5.5 0 0 1-.708-.708L6.293 7 4.646 5.354a.5.5 0 0 1 0-.708z" />
                </svg>
            </button>
        </div>
    );
}

// ============================================================================
// Confirm Dialog (replaces window.confirm)
// ============================================================================
type ConfirmFn = (message: string, title?: string) => Promise<boolean>;

interface ConfirmState {
    open: boolean;
    title: string;
    message: string;
    resolve: ((value: boolean) => void) | null;
}

const ConfirmContext = createContext<ConfirmFn | null>(null);

interface ConfirmProviderProps {
    children: ReactNode;
}

export function ConfirmProvider({ children }: ConfirmProviderProps) {
    const [state, setState] = useState<ConfirmState>({ open: false, title: '', message: '', resolve: null });

    const confirm: ConfirmFn = useCallback((message: string, title: string = 'Confirm') => {
        return new Promise<boolean>((resolve) => {
            setState({ open: true, title, message, resolve });
        });
    }, []);

    const handleConfirm = () => {
        state.resolve?.(true);
        setState({ open: false, title: '', message: '', resolve: null });
    };

    const handleCancel = () => {
        state.resolve?.(false);
        setState({ open: false, title: '', message: '', resolve: null });
    };

    return (
        <ConfirmContext.Provider value={confirm}>
            {children}
            {state.open && (
                <div className="fixed inset-0 z-[10000] flex items-center justify-center">
                    <div className="absolute inset-0 bg-black/60 backdrop-blur-sm" onClick={handleCancel} />
                    <div className="relative bg-card rounded-xl shadow-2xl border border-border max-w-sm w-full mx-4 p-6 animate-scale-in">
                        <h3 className="text-lg font-semibold text-foreground mb-2">{state.title}</h3>
                        <p className="text-sm text-muted-foreground mb-6">{state.message}</p>
                        <div className="flex justify-end gap-3">
                            <button
                                onClick={handleCancel}
                                className="px-4 py-2 text-sm font-medium bg-secondary text-secondary-foreground hover:bg-secondary/80 rounded-lg transition-colors"
                            >
                                Cancel
                            </button>
                            <button
                                onClick={handleConfirm}
                                className="px-4 py-2 text-sm font-medium bg-destructive text-destructive-foreground hover:bg-destructive/90 rounded-lg transition-colors"
                            >
                                Confirm
                            </button>
                        </div>
                    </div>
                </div>
            )}
        </ConfirmContext.Provider>
    );
}

export function useConfirm(): ConfirmFn {
    const ctx = useContext(ConfirmContext);
    if (!ctx) throw new Error('useConfirm must be used within ConfirmProvider');
    return ctx;
}
