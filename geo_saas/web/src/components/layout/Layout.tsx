import { Outlet } from "react-router-dom";
import { Sidebar } from "./Sidebar";
import { CursorGlow } from "@/components/ui/cursor-glow";
import { FeatureAccessBoundary } from "@/components/permissions/FeatureAccessBoundary";

export function Layout() {
    return (
        <div className="flex h-screen w-full bg-background overflow-hidden relative noise-overlay">
            {/* Grid background with radial mask */}
            <div className="fixed inset-0 pointer-events-none z-0 dark-grid dark:block hidden" />
            {/* Cursor glow follows mouse */}
            <CursorGlow />
            <Sidebar />
            <div className="flex flex-col flex-1 h-full overflow-hidden">
                <main className="flex-1 overflow-auto bg-muted/10 p-6 relative z-[2]">
                    <div className="animate-fade-in h-full">
                        <FeatureAccessBoundary>
                            <Outlet />
                        </FeatureAccessBoundary>
                    </div>
                </main>
            </div>
        </div>
    );
}
