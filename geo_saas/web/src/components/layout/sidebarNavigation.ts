export type SidebarNavGroupId = "dashboards" | "agents";

export type SidebarNavItemId =
    | "overview"
    | "visibility"
    | "citation"
    | "sentiment"
    | "prompts"
    | "reports"
    | "tracking"
    | "analysis"
    | "content"
    | "chat"
    | "training";

export interface SidebarNavigationItem {
    id: SidebarNavItemId;
    path: string;
}

export interface SidebarNavigationGroup {
    id: SidebarNavGroupId;
    items: readonly SidebarNavigationItem[];
}

export const PROMPT_ROUTE_CONTRACT = {
    canonicalPath: "/insights/prompts",
    childSegment: "prompts",
    legacyPath: "/prompts",
    redirectTarget: "/insights/prompts",
    replace: true,
} as const;

export const PROMPTS_PATH = PROMPT_ROUTE_CONTRACT.canonicalPath;
export const LEGACY_PROMPTS_PATH = PROMPT_ROUTE_CONTRACT.legacyPath;
export const LEGACY_PROMPTS_REDIRECT_TARGET = PROMPT_ROUTE_CONTRACT.redirectTarget;

export type InsightsTabKey = "prompts" | "fanouts";

export interface InsightsNavigationTab {
    key: InsightsTabKey;
    path: string;
}

export function buildPromptTabs(): InsightsNavigationTab[] {
    return [
        { key: "prompts", path: PROMPTS_PATH },
        { key: "fanouts", path: "/insights/fanouts" },
    ];
}

export const SIDEBAR_NAV_GROUPS: readonly SidebarNavigationGroup[] = [
    {
        id: "dashboards",
        items: [
            { id: "overview", path: "/overview" },
            { id: "visibility", path: "/insights" },
            { id: "citation", path: "/citation" },
            { id: "sentiment", path: "/sentiment" },
            { id: "prompts", path: PROMPTS_PATH },
            { id: "reports", path: "/reports" },
        ],
    },
    {
        id: "agents",
        items: [
            { id: "tracking", path: "/agents/tracking" },
            { id: "analysis", path: "/agents/analysis" },
            { id: "content", path: "/agents/content" },
            { id: "chat", path: "/agents/chat" },
            { id: "training", path: "/agents/training" },
        ],
    },
];

function matchesPathPrefix(pathname: string, prefix: string) {
    return pathname === prefix || pathname.startsWith(`${prefix}/`);
}

export function isSidebarNavItemActive(itemId: SidebarNavItemId, pathname: string) {
    if (itemId === "prompts") {
        return matchesPathPrefix(pathname, PROMPTS_PATH)
            || matchesPathPrefix(pathname, LEGACY_PROMPTS_PATH)
            || matchesPathPrefix(pathname, "/insights/fanouts");
    }

    if (itemId === "visibility") {
        return pathname === "/insights"
            || [
                "/insights/visibility",
                "/insights/citations",
                "/insights/channel-analysis",
            ].some((path) => matchesPathPrefix(pathname, path));
    }

    const item = SIDEBAR_NAV_GROUPS
        .flatMap((group) => group.items)
        .find((candidate) => candidate.id === itemId);
    return item ? matchesPathPrefix(pathname, item.path) : false;
}
