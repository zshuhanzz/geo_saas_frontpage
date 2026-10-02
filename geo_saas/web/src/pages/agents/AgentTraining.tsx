import { useState } from "react";
import { useTranslation } from "react-i18next";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import {
  Wrench,
  Brain,
  GitBranch,
  Users,
  Plus,
  Eye,
  ChevronRight,
} from "lucide-react";

const tiers = [
  {
    level: 4,
    title: "Multi-Role Coordination",
    subtitle: "Orchestration",
    desc: "Multi-agent role collaboration for automating complex decision workflows",
    icon: Users,
    color: "from-violet-500/15 to-purple-500/10",
    accent: "text-violet-600",
    border: "hover:border-violet-300",
    ring: "bg-violet-500",
    skills: ["Strategy Planner", "Intel Analyst", "Growth Hacker"],
  },
  {
    level: 3,
    title: "Workflow SOP",
    subtitle: "Workflow",
    desc: "Automated GEO optimization workflows and scheduled tasks",
    icon: GitBranch,
    color: "from-blue-500/15 to-cyan-500/10",
    accent: "text-blue-600",
    border: "hover:border-blue-300",
    ring: "bg-blue-500",
    skills: ["Weekly Report", "Alert Monitor", "Auto-Optimize"],
  },
  {
    level: 2,
    title: "Brand Understanding",
    subtitle: "Context-aware",
    desc: "Deep understanding of brand knowledge, competitor data, and industry insights",
    icon: Brain,
    color: "from-emerald-500/15 to-teal-500/10",
    accent: "text-emerald-600",
    border: "hover:border-emerald-300",
    ring: "bg-emerald-500",
    skills: ["Brand Knowledge", "Competitor Intel", "Industry Data"],
  },
  {
    level: 1,
    title: "Tool Library",
    subtitle: "Tool Skills",
    desc: "Core tool capabilities for GEO data retrieval, visualization, and analysis",
    icon: Wrench,
    color: "from-amber-500/15 to-orange-500/10",
    accent: "text-amber-600",
    border: "hover:border-amber-300",
    ring: "bg-amber-500",
    skills: ["Data Query", "Visualization", "Export"],
  },
];

export default function AgentTraining() {
  const { t } = useTranslation("agents");
  const [expandedTier, setExpandedTier] = useState<number | null>(null);

  return (
    <div className="h-full flex flex-col">
      {/* Fixed page title */}
      <div className="shrink-0 px-6 lg:px-10 pt-1 pb-4">
        <h1 className="text-2xl font-bold tracking-tight text-foreground">
          {t("training.pageTitle")}
        </h1>
        <p className="text-muted-foreground mt-1 text-sm">
          {t("training.subtitle")}
        </p>
      </div>

      {/* Scrollable content */}
      <div className="flex-1 overflow-auto">
        <div className="max-w-7xl mx-auto px-6 lg:px-10 pb-6">
          {/* Main layout: Anthony + Tier cards */}
        <div className="grid grid-cols-1 lg:grid-cols-[340px_1fr] gap-8 items-stretch">
          {/* Left: Anthony Image */}
          <div className="flex flex-col items-center lg:sticky lg:top-6">
            <div className="relative h-full">
              <div className="w-72 h-full min-h-[400px] rounded-3xl overflow-hidden bg-gradient-to-b from-muted/20 to-muted/40 border shadow-lg">
                <img
                  src="/Anthony.png"
                  alt="Anthony"
                  className="w-full h-full object-contain"
                />
              </div>
              {/* Connection dot */}
              <div className="hidden lg:flex absolute top-1/2 -right-5 -translate-y-1/2 items-center justify-center">
                <span className="relative flex h-4 w-4">
                  <span className="animate-ping absolute inline-flex h-full w-full rounded-full bg-emerald-400 opacity-60" />
                  <span className="relative inline-flex rounded-full h-4 w-4 bg-emerald-500 border-2 border-background shadow" />
                </span>
              </div>
            </div>
            <div className="mt-5 text-center">
              <p className="text-xs text-muted-foreground tracking-wider uppercase">
                {t("training.agentCaption")}
              </p>
              <p className="text-xl font-bold tracking-tight mt-0.5">Anthony</p>
            </div>
          </div>

          {/* Right: Tier cards */}
          <div className="relative flex flex-col gap-5">
            {/* Vertical connector line */}
            <div className="hidden lg:block absolute left-0 top-8 bottom-8 w-px bg-gradient-to-b from-violet-300 via-emerald-300 to-amber-300 -translate-x-6" />

            {tiers.map((tier) => {
              const Icon = tier.icon;
              const isExpanded = expandedTier === tier.level;

              return (
                <div key={tier.level} className="relative">
                  {/* Horizontal connector */}
                  <div className="hidden lg:block absolute left-0 top-1/2 w-5 h-px bg-border -translate-x-6 -translate-y-1/2" />
                  {/* Dot on line */}
                  <div className="hidden lg:block absolute -left-6 top-1/2 -translate-x-1/2 -translate-y-1/2">
                    <div className={`w-2.5 h-2.5 rounded-full ${tier.ring} shadow-sm`} />
                  </div>

                  <Card
                    className={`
                      group cursor-pointer transition-all duration-300 ease-out
                      hover:shadow-lg ${tier.border}
                      ${isExpanded ? "ring-1 ring-primary/20 shadow-md" : ""}
                    `}
                    onClick={() =>
                      setExpandedTier(isExpanded ? null : tier.level)
                    }
                  >
                    <CardContent className="p-6">
                      <div className="flex items-center gap-5">
                        {/* Level badge */}
                        <div
                          className={`
                            shrink-0 w-16 h-16 rounded-xl bg-gradient-to-br ${tier.color}
                            flex items-center justify-center
                            transition-transform duration-300 group-hover:scale-110
                          `}
                        >
                          <Icon className={`h-7 w-7 ${tier.accent}`} />
                        </div>

                        {/* Content */}
                        <div className="flex-1 min-w-0">
                          <div className="flex items-center gap-2">
                            <span className="text-xs font-bold tracking-wider text-muted-foreground/60 uppercase">
                              {t("training.tierLabel", { level: tier.level })}
                            </span>
                          </div>
                          <h3 className="text-lg font-semibold text-foreground mt-1 flex items-center gap-2">
                            {tier.title}
                            <span className="text-sm font-normal text-muted-foreground">
                              ({tier.subtitle})
                            </span>
                          </h3>
                          {isExpanded && (
                            <p className="text-sm text-muted-foreground mt-2 leading-relaxed">
                              {tier.desc}
                            </p>
                          )}
                        </div>

                        {/* Actions */}
                        <div className="flex items-center gap-3 shrink-0">
                          <Button
                            variant="outline"
                            size="default"
                            className="h-9 text-sm gap-2 opacity-80 group-hover:opacity-100 transition-opacity"
                            onClick={(e) => e.stopPropagation()}
                          >
                            <Eye className="h-4 w-4" />
                            {t("training.view")}
                          </Button>
                          <Button
                            variant="default"
                            size="default"
                            className="h-9 text-sm gap-2"
                            onClick={(e) => e.stopPropagation()}
                          >
                            <Plus className="h-4 w-4" />
                            {t("training.addCapability")}
                          </Button>
                          <ChevronRight
                            className={`h-5 w-5 text-muted-foreground/50 transition-transform duration-300 ${
                              isExpanded ? "rotate-90" : ""
                            }`}
                          />
                        </div>
                      </div>

                      {/* Expanded skills */}
                      {isExpanded && (
                        <div className="mt-4 pt-4 border-t flex flex-wrap gap-2.5">
                          {tier.skills.map((skill) => (
                            <span
                              key={skill}
                              className="inline-flex items-center px-4 py-1.5 rounded-full text-sm font-medium bg-muted text-muted-foreground"
                            >
                              {skill}
                            </span>
                          ))}
                          <button className="inline-flex items-center px-4 py-1.5 rounded-full text-sm font-medium border border-dashed text-muted-foreground hover:text-foreground hover:border-primary/40 transition-colors">
                            <Plus className="h-3.5 w-3.5 mr-1" />
                            {t("training.add")}
                          </button>
                        </div>
                      )}
                    </CardContent>
                  </Card>
                </div>
              );
            })}
          </div>
        </div>
        </div>
      </div>
    </div>
  );
}
