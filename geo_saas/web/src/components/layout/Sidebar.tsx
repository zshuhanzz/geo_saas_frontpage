import { useState } from "react";
import { Link, useLocation } from "react-router-dom";
import { useTranslation } from "react-i18next";
import {
    BarChart,
    Lightbulb,
    Settings,
    LogOut,
    Building,
    ChevronDown,
    Check,
    PanelLeftClose,
    PanelLeft,
    Target,
    LineChart,
    PenTool,
    GraduationCap,
    MessageSquare,
    Link2,
    SmilePlus,
    Sun,
    Moon,
    Globe,
    FileText,
    MessageSquareText,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import { cn } from "@/lib/utils";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/contexts/AuthContext";
import { useSaaS } from "@/contexts/SaaSContext";
import { useTheme } from "@/components/theme-provider";
import {
    DropdownMenu,
    DropdownMenuContent,
    DropdownMenuItem,
    DropdownMenuLabel,
    DropdownMenuSeparator,
    DropdownMenuTrigger,
} from "@/components/ui/dropdown-menu";
import {
    Tooltip,
    TooltipContent,
    TooltipProvider,
    TooltipTrigger,
} from "@/components/ui/tooltip";
import {
    SIDEBAR_NAV_GROUPS,
    isSidebarNavItemActive,
    type SidebarNavItemId,
} from "@/components/layout/sidebarNavigation";

// Labels live in `sidebar.json`, route order/matching lives in
// `sidebarNavigation.ts`, and this component only binds icons to semantic IDs.
const NAV_ITEM_ICONS: Record<SidebarNavItemId, LucideIcon> = {
    overview: BarChart,
    visibility: Lightbulb,
    citation: Link2,
    sentiment: SmilePlus,
    prompts: MessageSquareText,
    reports: FileText,
    tracking: Target,
    analysis: LineChart,
    content: PenTool,
    chat: MessageSquare,
    training: GraduationCap,
};

export function Sidebar() {
    const location = useLocation();
    const { user, logout } = useAuth();
    const { clients, clientId, setClientId, activeClientName, loadingClients } = useSaaS();
    const [collapsed, setCollapsed] = useState(false);
    const { theme, setTheme } = useTheme();
    const { t, i18n } = useTranslation(["sidebar", "common"]);
    const isZh = i18n.language.startsWith("zh");
    const nextLang = isZh ? "en-US" : "zh-CN";
    const toggleLanguage = () => {
        void i18n.changeLanguage(nextLang);
    };
    const langButtonLabel = isZh ? "中 / EN" : "EN / 中";

    return (
        <TooltipProvider delayDuration={0}>
            <div className={cn(
                "border-r border-border/50 bg-card/70 backdrop-blur-2xl h-full flex flex-col transition-all duration-300 ease-in-out relative z-10",
                collapsed ? "w-16" : "w-64"
            )}>
                {/* Aurora blob in logo area */}
                <div className="absolute -top-20 -left-20 w-48 h-48 bg-primary/10 blur-[80px] rounded-full pointer-events-none" />

                {/* Workspace Selector */}
                <div className="p-3 border-b border-border/50">
                    {collapsed ? (
                        <Tooltip>
                            <TooltipTrigger asChild>
                                <Button variant="ghost" className="w-full h-10 p-0 flex items-center justify-center">
                                    <Building className="h-5 w-5 text-muted-foreground" />
                                </Button>
                            </TooltipTrigger>
                            <TooltipContent side="right">
                                <p>{activeClientName || t("workspace.placeholder")}</p>
                            </TooltipContent>
                        </Tooltip>
                    ) : (
                        <DropdownMenu>
                            <DropdownMenuTrigger asChild>
                                <Button variant="ghost" className="w-full flex items-center justify-between h-10 px-3 hover:bg-primary/[0.04] data-[state=open]:bg-primary/[0.06] rounded-md">
                                    <div className="flex items-center gap-2 overflow-hidden">
                                        <Building className="h-4 w-4 shrink-0 text-primary/70" />
                                        <span className="font-semibold text-sm truncate">
                                            {loadingClients ? t("workspace.loading") : activeClientName || t("workspace.placeholder")}
                                        </span>
                                    </div>
                                    <ChevronDown className="h-3 w-3 shrink-0 text-muted-foreground" />
                                </Button>
                            </DropdownMenuTrigger>
                            <DropdownMenuContent align="start" className="w-[230px]">
                                <DropdownMenuLabel className="text-[10px] uppercase tracking-[0.15em] text-muted-foreground/60">
                                    {t("workspace.placeholder")}
                                </DropdownMenuLabel>
                                <DropdownMenuSeparator />
                                {clients.map(client => (
                                    <DropdownMenuItem
                                        key={client.id}
                                        onClick={() => setClientId(client.id)}
                                        className="flex items-center justify-between cursor-pointer"
                                    >
                                        <span className="truncate">{client.name}</span>
                                        {client.id === clientId && <Check className="h-4 w-4 shrink-0 text-primary ml-2" />}
                                    </DropdownMenuItem>
                                ))}
                                {clients.length === 0 && !loadingClients && (
                                    <div className="p-2 text-sm text-muted-foreground text-center">{t("workspace.empty")}</div>
                                )}
                            </DropdownMenuContent>
                        </DropdownMenu>
                    )}
                </div>

                {/* Navigation Items */}
                <div className="flex-1 overflow-auto py-3">
                    {SIDEBAR_NAV_GROUPS.map((group) => (
                        <div key={group.id} className={cn("mb-6", collapsed ? "px-2" : "px-3")}>
                            {!collapsed && (
                                <h4 className="mb-2 px-3 text-[10px] font-semibold tracking-[0.15em] text-muted-foreground/60 uppercase">
                                    {t(`groups.${group.id}`)}
                                </h4>
                            )}
                            <div className="space-y-0.5">
                                {group.items.map((item) => {
                                    const isActive = isSidebarNavItemActive(item.id, location.pathname);
                                    const label = t(`nav.${item.id}`);
                                    const ItemIcon = NAV_ITEM_ICONS[item.id];
                                    if (collapsed) {
                                        return (
                                            <Tooltip key={item.path}>
                                                <TooltipTrigger asChild>
                                                    <Button
                                                        variant="ghost"
                                                        className={cn(
                                                            "w-full h-10 p-0 flex items-center justify-center relative",
                                                            isActive
                                                                ? "text-primary bg-primary/[0.08]"
                                                                : "text-muted-foreground hover:text-foreground hover:bg-primary/[0.04]"
                                                        )}
                                                        asChild
                                                    >
                                                        <Link to={item.path}>
                                                            {isActive && (
                                                                <div className="absolute left-0 top-1/2 -translate-y-1/2 w-[3px] h-5 bg-primary rounded-r-full" />
                                                            )}
                                                            <ItemIcon className="h-4 w-4" />
                                                        </Link>
                                                    </Button>
                                                </TooltipTrigger>
                                                <TooltipContent side="right">
                                                    <p>{label}</p>
                                                </TooltipContent>
                                            </Tooltip>
                                        );
                                    }
                                    return (
                                        <Button
                                            key={item.path}
                                            variant="ghost"
                                            className={cn(
                                                "w-full justify-start relative",
                                                isActive
                                                    ? "text-primary bg-primary/[0.08] font-semibold hover:bg-primary/[0.1]"
                                                    : "text-muted-foreground hover:text-foreground hover:bg-primary/[0.04]"
                                            )}
                                            asChild
                                        >
                                            <Link to={item.path}>
                                                {isActive && (
                                                    <div className="absolute left-0 top-1/2 -translate-y-1/2 w-[3px] h-5 bg-primary rounded-r-full" />
                                                )}
                                                <ItemIcon className={cn("mr-2 h-4 w-4", isActive ? "text-primary" : "")} />
                                                {label}
                                            </Link>
                                        </Button>
                                    );
                                })}
                            </div>
                        </div>
                    ))}
                </div>

                {/* Bottom Section */}
                <div className={cn("border-t border-border/50 mt-auto space-y-1", collapsed ? "p-2" : "p-3")}>
                    {/* Language Toggle */}
                    <Tooltip>
                        <TooltipTrigger asChild>
                            <Button
                                variant="ghost"
                                size={collapsed ? "icon" : "default"}
                                className={cn(
                                    "text-muted-foreground hover:text-foreground hover:bg-primary/[0.04]",
                                    collapsed ? "w-full h-10 p-0 flex items-center justify-center" : "w-full justify-start"
                                )}
                                onClick={toggleLanguage}
                                aria-label={t("common:language.toggleTooltip")}
                            >
                                {collapsed ? <Globe className="h-4 w-4" /> : (
                                    <>
                                        <Globe className="mr-2 h-4 w-4" />
                                        {langButtonLabel}
                                    </>
                                )}
                            </Button>
                        </TooltipTrigger>
                        {collapsed && (
                            <TooltipContent side="right">
                                <p>{t("common:language.toggleTooltip")}</p>
                            </TooltipContent>
                        )}
                    </Tooltip>

                    {/* Theme Toggle */}
                    <Tooltip>
                        <TooltipTrigger asChild>
                            <Button
                                variant="ghost"
                                size={collapsed ? "icon" : "default"}
                                className={cn(
                                    "text-muted-foreground hover:text-foreground hover:bg-primary/[0.04]",
                                    collapsed ? "w-full h-10 p-0 flex items-center justify-center" : "w-full justify-start"
                                )}
                                onClick={() => setTheme(theme === "light" ? "dark" : "light")}
                            >
                                {theme === "dark" ? (
                                    collapsed ? <Sun className="h-4 w-4" /> : (
                                        <>
                                            <Sun className="mr-2 h-4 w-4" />
                                            {t("common:theme.light")}
                                        </>
                                    )
                                ) : (
                                    collapsed ? <Moon className="h-4 w-4" /> : (
                                        <>
                                            <Moon className="mr-2 h-4 w-4" />
                                            {t("common:theme.dark")}
                                        </>
                                    )
                                )}
                            </Button>
                        </TooltipTrigger>
                        {collapsed && (
                            <TooltipContent side="right">
                                <p>{theme === "dark" ? t("common:theme.toLight") : t("common:theme.toDark")}</p>
                            </TooltipContent>
                        )}
                    </Tooltip>

                    {/* Collapse Toggle */}
                    <Tooltip>
                        <TooltipTrigger asChild>
                            <Button
                                variant="ghost"
                                size={collapsed ? "icon" : "default"}
                                className={cn(
                                    "text-muted-foreground hover:text-foreground hover:bg-primary/[0.04]",
                                    collapsed ? "w-full h-10 p-0 flex items-center justify-center" : "w-full justify-start"
                                )}
                                onClick={() => setCollapsed(!collapsed)}
                            >
                                {collapsed ? <PanelLeft className="h-4 w-4" /> : (
                                    <>
                                        <PanelLeftClose className="mr-2 h-4 w-4" />
                                        {t("controls.collapse")}
                                    </>
                                )}
                            </Button>
                        </TooltipTrigger>
                        {collapsed && (
                            <TooltipContent side="right">
                                <p>{t("controls.expand")}</p>
                            </TooltipContent>
                        )}
                    </Tooltip>

                    {/* Settings */}
                    {collapsed ? (
                        <Tooltip>
                            <TooltipTrigger asChild>
                                <Button variant="ghost" className="w-full h-10 p-0 flex items-center justify-center text-muted-foreground hover:bg-primary/[0.04]" asChild>
                                    <Link to="/settings">
                                        <Settings className="h-4 w-4" />
                                    </Link>
                                </Button>
                            </TooltipTrigger>
                            <TooltipContent side="right">
                                <p>{t("nav.settings")}</p>
                            </TooltipContent>
                        </Tooltip>
                    ) : (
                        <Button variant="ghost" className="w-full justify-start text-muted-foreground hover:bg-primary/[0.04]" asChild>
                            <Link to="/settings">
                                <Settings className="mr-2 h-4 w-4" />
                                {t("nav.settings")}
                            </Link>
                        </Button>
                    )}

                    {/* User Profile Area */}
                    {user && (
                        <div className={cn("flex items-center pt-2 border-t border-border/50", collapsed ? "justify-center" : "space-x-3 px-2")}>
                            {collapsed ? (
                                <Tooltip>
                                    <TooltipTrigger asChild>
                                        <Button variant="ghost" size="icon" onClick={logout} className="h-8 w-8 text-muted-foreground hover:text-foreground">
                                            <LogOut className="h-4 w-4" />
                                        </Button>
                                    </TooltipTrigger>
                                    <TooltipContent side="right">
                                        <p>{t("user.signOutTooltip", { name: user.name })}</p>
                                    </TooltipContent>
                                </Tooltip>
                            ) : (
                                <>
                                    <img src={user.picture} alt="Avatar" className="h-8 w-8 rounded-full ring-2 ring-primary/20 shrink-0" />
                                    <div className="flex flex-col flex-1 overflow-hidden">
                                        <span className="text-sm font-medium truncate">{user.name}</span>
                                        <span className="text-xs text-muted-foreground truncate">{user.email}</span>
                                    </div>
                                    <Button
                                        variant="ghost"
                                        size="icon"
                                        onClick={logout}
                                        className="h-8 w-8 shrink-0 text-muted-foreground hover:text-foreground"
                                        aria-label={t("common:states.signOut")}
                                    >
                                        <LogOut className="h-4 w-4" />
                                    </Button>
                                </>
                            )}
                        </div>
                    )}

                    {/* Logo */}
                    {!collapsed && (
                        <div className="flex items-center justify-center pt-3">
                            <img src="/logo.png" alt="AnswerX Logo" className="h-4 w-auto mr-2" />
                            <span className="text-xs font-bold tracking-wider gradient-text-static">AnswerX</span>
                        </div>
                    )}
                </div>
            </div>
        </TooltipProvider>
    );
}
