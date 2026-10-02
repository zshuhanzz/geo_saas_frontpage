import { useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { ModeToggle } from "@/components/mode-toggle";

/**
 * Route-to-title mapping for top Header.
 * `titleKey` is resolved against `sidebar:pageTitles.*` at render time.
 * `null` means this route manages its own full-bleed header (chat page).
 */
type PageTitleKey =
    | "answerEngineInsights"
    | "trackingStrategy"
    | "agents"
    | "trainAgent";

const AGENT_ROUTE_TITLES: { prefix: string; titleKey: PageTitleKey | null }[] = [
    { prefix: "/agents/tracking", titleKey: "trackingStrategy" },
    { prefix: "/agents/analysis", titleKey: "agents" },
    { prefix: "/agents/content", titleKey: "agents" },
    { prefix: "/agents/training", titleKey: "trainAgent" },
    { prefix: "/agents/chat", titleKey: null },
];

export function Header() {
    const { pathname } = useLocation();
    const { t } = useTranslation("sidebar");

    const match = AGENT_ROUTE_TITLES.find(({ prefix }) => pathname.startsWith(prefix));

    // Chat page: hide the header entirely
    if (match?.titleKey === null) return null;

    const titleKey: PageTitleKey = match?.titleKey ?? "answerEngineInsights";
    const title = t(`pageTitles.${titleKey}`);

    return (
        <header className="h-14 border-b border-border/50 bg-card/70 backdrop-blur-2xl flex items-center px-6 justify-between shrink-0 relative">
            <div className="flex items-center gap-4">
                <h1 className="text-lg font-semibold tracking-tight">{title}</h1>
            </div>
            <div className="flex items-center gap-4">
                <ModeToggle />
            </div>
            <div className="absolute bottom-0 left-0 right-0 h-px bg-gradient-to-r from-transparent via-primary/20 to-transparent" />
        </header>
    );
}
