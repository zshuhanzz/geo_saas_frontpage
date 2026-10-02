import { NavLink } from "react-router-dom";
import {
    BarChart3,
    Settings,
    Users,
    ListTodo,
    Globe,
    MessageSquareText,
    Layout,
    Activity,
    Sparkles,
    FileText,
    PenTool,
    Brain,
    MessageSquare,
    Zap,
    UserCircle,
    Target,
    Crosshair,
    Lightbulb,
    FileBox,
    Ruler,
    ShieldCheck,
    PackageCheck,
    type LucideIcon,
} from "lucide-react";

// NOTE: BarChart3 and PenTool are imported but not used in current navigation;
// retained verbatim from the .jsx version (relaxed `noUnusedLocals` during migration).
void BarChart3;
void PenTool;

interface NavItem {
    name: string;
    href: string;
    icon: LucideIcon;
}

const navigation: NavItem[] = [
    { name: "Clients", href: "/clients", icon: Users },
    { name: "Access Control", href: "/access-control", icon: ShieldCheck },
    { name: "Feature Access", href: "/feature-access", icon: PackageCheck },
    { name: "Prompts", href: "/prompts", icon: MessageSquareText },
    { name: "Tasks & Results", href: "/tasks", icon: ListTodo },
    { name: "Languages", href: "/languages", icon: Globe },
    { name: "Brand Profiles", href: "/brand-profiles", icon: Sparkles },
    { name: "Global Config", href: "/global", icon: Settings },
];

const analysisNavigation: NavItem[] = [
    { name: "Analysis Metrics", href: "/analysis/metrics", icon: Ruler },
    { name: "Report Templates", href: "/analysis/templates", icon: Layout },
    { name: "GEO Analysis Tasks", href: "/analysis/tasks", icon: Activity },
    { name: "Static Reports", href: "/static-reports", icon: FileText },
];

const contentNavigation: NavItem[] = [
    { name: "Content Templates", href: "/content/templates", icon: FileText },
    { name: "GEO Content Tasks", href: "/content/tasks", icon: Activity },
];

const frameworkNavigation: NavItem[] = [
    { name: "Metrics", href: "/framework/metrics", icon: Target },
    { name: "Subgoals", href: "/framework/subgoals", icon: Crosshair },
    { name: "Strategies", href: "/framework/strategies", icon: Lightbulb },
    { name: "Content Assets", href: "/framework/assets", icon: FileBox },
];

const agentNavigation: NavItem[] = [
    { name: "Agent Memories", href: "/agent/memories", icon: Brain },
    { name: "Agent Sessions", href: "/agent/sessions", icon: MessageSquare },
    { name: "Token Usage", href: "/agent/token-usage", icon: Zap },
    { name: "User Profiles", href: "/agent/user-profiles", icon: UserCircle },
];

interface NavSectionProps {
    title: string;
    items: NavItem[];
}

function NavSection({ title, items }: NavSectionProps) {
    return (
        <>
            <div className="px-3 mt-6 first:mt-0 mb-2 text-[10px] font-semibold text-muted-foreground/60 uppercase tracking-[0.15em]">
                {title}
            </div>
            {items.map((item) => (
                <NavLink
                    key={item.name}
                    to={item.href}
                    className={({ isActive }) =>
                        `group flex items-center px-4 py-2.5 text-sm rounded-lg transition-all duration-200 relative ${isActive
                            ? "bg-primary/[0.08] text-primary font-semibold"
                            : "text-muted-foreground font-medium hover:bg-primary/[0.04] hover:text-foreground"
                        }`
                    }
                >
                    {({ isActive }) => (
                        <>
                            {isActive && (
                                <div className="absolute left-0 top-1/2 -translate-y-1/2 w-[3px] h-5 bg-primary rounded-r-full" />
                            )}
                            <item.icon
                                className={`mr-3 h-4 w-4 flex-shrink-0 transition-colors duration-200 ${isActive ? "text-primary" : "text-muted-foreground/70 group-hover:text-foreground"}`}
                                aria-hidden="true"
                            />
                            <span className="tracking-wide">{item.name}</span>
                        </>
                    )}
                </NavLink>
            ))}
        </>
    );
}

export function Sidebar() {
    return (
        <div className="flex z-20 h-full w-64 flex-col border-r border-border/50 bg-card/70 backdrop-blur-2xl relative">
            {/* Aurora blob */}
            <div className="absolute -top-20 -left-20 w-48 h-48 bg-primary/10 blur-[80px] rounded-full pointer-events-none" />

            <div className="flex h-16 shrink-0 items-center px-6 border-b border-border/50 relative overflow-hidden">
                <span className="text-xl font-bold flex items-center gap-3 relative z-10 w-full tracking-wide">
                    <img src="/logo.png" alt="AnswerX Logo" className="h-6 w-auto object-contain" />
                    <span className="gradient-text-static font-bold">
                        AnswerX
                    </span>
                </span>
            </div>
            <div className="flex flex-1 flex-col overflow-y-auto pt-4 pb-4">
                <nav className="flex-1 space-y-0.5 px-3">
                    <NavSection title="Menu" items={navigation} />
                    <NavSection title="Analysis" items={analysisNavigation} />
                    <NavSection title="Content" items={contentNavigation} />
                    <NavSection title="Optimization" items={frameworkNavigation} />
                    <NavSection title="Agent" items={agentNavigation} />
                </nav>
            </div>
        </div>
    );
}
