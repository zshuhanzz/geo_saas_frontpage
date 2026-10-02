import { Outlet } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { useAuth } from "../../contexts/AuthContext";
import { ModeToggle } from "../mode-toggle";

export function AppLayout() {
    const { user, logout } = useAuth();

    return (
        <div className="flex h-screen bg-background overflow-hidden noise-overlay">
            {/* Grid background */}
            <div className="fixed inset-0 pointer-events-none z-0 dark-grid dark:block hidden" />

            {/* Sidebar Navigation */}
            <Sidebar />

            {/* Main Content Area */}
            <div className="flex flex-1 flex-col overflow-hidden relative z-10">
                {/* Top Header */}
                <header className="flex h-14 shrink-0 items-center justify-end border-b border-border/50 bg-card/70 backdrop-blur-2xl px-6 sticky top-0 z-50">
                    <div className="flex items-center gap-4">
                        {user && (
                            <>
                                <img
                                    src={user.picture}
                                    alt={user.name}
                                    className="h-8 w-8 rounded-full ring-2 ring-primary/20"
                                />
                                <span className="text-sm text-muted-foreground hidden md:inline-block font-medium">
                                    {user.email}
                                </span>
                                <button
                                    onClick={logout}
                                    className="text-sm px-3 py-1.5 rounded-lg text-muted-foreground hover:text-foreground hover:bg-primary/[0.04] transition-all duration-200"
                                >
                                    Logout
                                </button>
                            </>
                        )}
                        <ModeToggle />
                    </div>
                    {/* Gradient line at bottom of header */}
                    <div className="absolute bottom-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-primary/20 to-transparent" />
                </header>

                {/* Page Content */}
                <main className="flex-1 overflow-y-auto p-6 md:p-8 relative z-0">
                    <div className="mx-auto max-w-7xl animate-fade-in">
                        <Outlet />
                    </div>
                </main>
            </div>
        </div>
    );
}
