import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/badge";
import { cn } from "@/lib/utils";
import { TopicQuadrantScatter, PlatformCitationBar } from "@/components/charts/OpportunityCharts";
import type { RunRecord } from "./types";

/** Opportunity Discovery structured output (Quadrants / Content Opps / Platform Recs).
 *  Returns null when no structured output is present, so caller can render
 *  conditionally without an extra check. */
export function OpportunityDiscoveryView({ run }: { run: RunRecord }) {
    const { t } = useTranslation("agents");
    const report = run.report_output;
    if (!report) return null;
    if (!(run.task_type === "opportunity_discovery" || run.inputs?.analysis_goal === "opportunity")) return null;

    // Canonical quadrant keys. Backend may return English ("Strong")
    // or Chinese ("强势") depending on pipeline version; normalize both.
    type QuadrantKey = "strong" | "weak" | "untapped" | "emerging";
    const QUADRANT_KEYS: QuadrantKey[] = ["strong", "weak", "untapped", "emerging"];
    const QUADRANT_FROM_SERVER: Record<string, QuadrantKey> = {
        "Strong": "strong", "Weak": "weak", "Untapped": "untapped", "Emerging": "emerging",
        "强势": "strong", "薄弱": "weak", "待挖掘": "untapped", "新兴": "emerging",
    };
    const QUADRANT_COLORS: Record<QuadrantKey, string> = {
        strong: "bg-green-100 text-green-800 dark:bg-green-900/40 dark:text-green-300",
        weak: "bg-red-100 text-red-800 dark:bg-red-900/40 dark:text-red-300",
        untapped: "bg-amber-100 text-amber-800 dark:bg-amber-900/40 dark:text-amber-300",
        emerging: "bg-blue-100 text-blue-800 dark:bg-blue-900/40 dark:text-blue-300",
    };
    const toQuadrantKey = (s: string | undefined | null): QuadrantKey | null =>
        s ? (QUADRANT_FROM_SERVER[s] ?? null) : null;

    const topicQuadrants: Array<{ topic: string; primary_quadrant: string; secondary_quadrant?: string | null; action?: string; metrics?: any }> = report.topic_quadrants || [];
    const contentOpps: Array<{ topic: string; angle: string; score: number; source_quadrant?: string; quadrant?: string; opportunity_score?: number; recommended_metrics?: string[]; related_prompts?: string[]; competitor_refs?: string[] }> = (report.content_opportunities || []).slice(0, 8);
    const platformRecs: Array<{ platform_type: string; engines: string[]; citation_share: number; priority: string; engine_breakdown?: Record<string, number> }> = report.platform_recommendations || [];

    if (topicQuadrants.length === 0 && contentOpps.length === 0 && platformRecs.length === 0) return null;

    // Count topics per quadrant (canonical keys)
    const quadrantCounts: Record<QuadrantKey, number> = { strong: 0, weak: 0, untapped: 0, emerging: 0 };
    topicQuadrants.forEach(tq => {
        const q = toQuadrantKey(tq.primary_quadrant);
        if (q) quadrantCounts[q] = quadrantCounts[q] + 1;
    });

    const priorityLabel = (p: string) =>
        p === "high" ? t("analysis.opportunity.priorityHigh")
            : p === "medium" ? t("analysis.opportunity.priorityMedium")
                : t("analysis.opportunity.priorityLow");

    return (
        <div className="space-y-4">
            {/* Quadrant Legend */}
            {topicQuadrants.length > 0 && (
                <div>
                    <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">
                        {t("analysis.opportunity.quadrantModel")}
                    </div>
                    <div className="grid grid-cols-2 gap-2 mb-4">
                        {QUADRANT_KEYS.map(q => {
                            const count = quadrantCounts[q] || 0;
                            return (
                                <div key={q} className={cn("rounded-lg border p-3", QUADRANT_COLORS[q])}>
                                    <div className="flex items-center justify-between mb-1">
                                        <span className="text-sm font-bold">{t(`analysis.opportunity.quadrantLabels.${q}`)}</span>
                                        <span className="text-xs font-medium opacity-70">
                                            {t("analysis.opportunity.strategyLabel", { action: t(`analysis.opportunity.quadrantActions.${q}`) })}
                                        </span>
                                    </div>
                                    <p className="text-[11px] opacity-70">{t(`analysis.opportunity.quadrantDescs.${q}`)}</p>
                                    <div className="text-xs font-semibold mt-1.5">{t("analysis.opportunity.topicsCount", { count })}</div>
                                </div>
                            );
                        })}
                    </div>

                    {/* Scatter Chart */}
                    <div className="rounded-xl border bg-card p-4 mb-4">
                        <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
                            {t("analysis.opportunity.matrixTitle")}
                        </div>
                        <TopicQuadrantScatter data={topicQuadrants} />
                    </div>

                    <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">
                        {t("analysis.opportunity.quadrantDistribution")}
                    </div>
                    <div className="rounded-xl border bg-card p-4">
                        <div className="space-y-2">
                            {topicQuadrants.map((tq, i) => {
                                const primaryKey = toQuadrantKey(tq.primary_quadrant);
                                const secondaryKey = toQuadrantKey(tq.secondary_quadrant);
                                return (
                                    <div key={i} className="flex items-center gap-2">
                                        <span className={cn(
                                            "inline-flex items-center gap-1.5 px-2.5 py-1 rounded-full text-xs font-medium shrink-0",
                                            primaryKey ? QUADRANT_COLORS[primaryKey] : "bg-gray-100 text-gray-700 dark:bg-gray-800 dark:text-gray-300"
                                        )}>
                                            {primaryKey ? t(`analysis.opportunity.quadrantLabels.${primaryKey}`) : tq.primary_quadrant}
                                        </span>
                                        {secondaryKey && (
                                            <span className={cn("inline-flex items-center px-2 py-0.5 rounded-full text-[10px] shrink-0", QUADRANT_COLORS[secondaryKey])}>
                                                {t(`analysis.opportunity.quadrantLabels.${secondaryKey}`)}
                                            </span>
                                        )}
                                        <span className="text-sm font-medium flex-1 min-w-0 truncate">{tq.topic}</span>
                                        <span className="text-[10px] text-muted-foreground shrink-0">
                                            {tq.action || (primaryKey ? t(`analysis.opportunity.quadrantActions.${primaryKey}`) : "")}
                                        </span>
                                        {tq.metrics?.visibility_score != null && (
                                            <span className="text-[10px] text-muted-foreground shrink-0">
                                                {t("analysis.opportunity.visibilityPct", { pct: Math.round(tq.metrics.visibility_score * 100) })}
                                            </span>
                                        )}
                                        {tq.metrics?.citation_rate != null && (
                                            <span className="text-[10px] text-muted-foreground shrink-0">
                                                {t("analysis.opportunity.citationPct", { pct: Math.round(tq.metrics.citation_rate * 100) })}
                                            </span>
                                        )}
                                    </div>
                                );
                            })}
                        </div>
                    </div>
                </div>
            )}

            {/* Top Content Opportunities */}
            {contentOpps.length > 0 && (
                <div>
                    <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">
                        {t("analysis.opportunity.contentOpps", { count: contentOpps.length })}
                    </div>
                    <div className="rounded-xl border bg-card divide-y">
                        {contentOpps.map((opp, i) => {
                            const rawScore = opp.opportunity_score ?? opp.score ?? 0;
                            // Score could be 1-10 scale (from LLM) or 0-100 — normalize to 0-100 for display
                            const score = rawScore <= 10 ? rawScore * 10 : rawScore;
                            const scoreColor = score >= 80 ? "bg-emerald-500" : score >= 60 ? "bg-amber-500" : "bg-red-400";
                            const badgeKey = toQuadrantKey(opp.source_quadrant || opp.quadrant || "");
                            return (
                                <div key={i} className="px-4 py-3">
                                    <div className="flex items-center gap-3">
                                        <div className="flex items-center justify-center w-6 h-6 rounded-full bg-primary/10 text-primary text-xs font-bold shrink-0">{i + 1}</div>
                                        <div className="flex-1 min-w-0">
                                            <div className="text-sm font-medium truncate">{opp.topic}</div>
                                            <div className="text-xs text-muted-foreground mt-0.5">{opp.angle}</div>
                                        </div>
                                        <Badge variant="outline" className={cn("text-[10px] shrink-0", badgeKey ? QUADRANT_COLORS[badgeKey] : "")}>
                                            {badgeKey ? t(`analysis.opportunity.quadrantLabels.${badgeKey}`) : (opp.source_quadrant || opp.quadrant || "—")}
                                        </Badge>
                                        <div className="text-xs font-bold text-primary shrink-0 w-10 text-right">{score}</div>
                                    </div>
                                    {/* Score bar (normalized to 0-100) */}
                                    <div className="mt-2 ml-9">
                                        <div className="h-1.5 w-full bg-muted rounded-full overflow-hidden">
                                            <div className={cn("h-full rounded-full transition-all", scoreColor)} style={{ width: `${Math.min(100, score)}%` }} />
                                        </div>
                                    </div>
                                    {/* Metric pills + prompt count */}
                                    {((opp.recommended_metrics && opp.recommended_metrics.length > 0) || (opp.related_prompts && opp.related_prompts.length > 0) || (opp.competitor_refs && opp.competitor_refs.length > 0)) && (
                                        <div className="mt-2 ml-9 flex flex-wrap items-center gap-1.5">
                                            {opp.recommended_metrics?.map((m, mi) => (
                                                <span key={mi} className="text-[10px] px-1.5 py-0.5 rounded bg-primary/10 text-primary font-medium">{m}</span>
                                            ))}
                                            {opp.related_prompts && opp.related_prompts.length > 0 && (
                                                <span className="text-[10px] px-1.5 py-0.5 rounded bg-blue-500/10 text-blue-400 font-medium">
                                                    {t("analysis.opportunity.relatedPrompts", { count: opp.related_prompts.length })}
                                                </span>
                                            )}
                                            {opp.competitor_refs && opp.competitor_refs.length > 0 && (
                                                <span className="text-[10px] px-1.5 py-0.5 rounded bg-red-500/10 text-red-400 font-medium">
                                                    {t("analysis.opportunity.competitorRefs", { count: opp.competitor_refs.length })}
                                                </span>
                                            )}
                                        </div>
                                    )}
                                </div>
                            );
                        })}
                    </div>
                </div>
            )}

            {/* Platform Recommendations */}
            {platformRecs.length > 0 && (
                <div>
                    <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-3">
                        {t("analysis.opportunity.platformMatrix")}
                    </div>
                    {/* Bar Chart */}
                    {platformRecs.some(r => r.engine_breakdown) && (
                        <div className="rounded-xl border bg-card p-4 mb-3">
                            <PlatformCitationBar data={platformRecs} />
                        </div>
                    )}
                    <div className="grid gap-2">
                        {platformRecs.map((rec, i) => {
                            const sharePercent = Math.round((rec.citation_share || 0) * 100);
                            return (
                                <div key={i} className="rounded-xl border bg-card px-4 py-3 space-y-2">
                                    <div className="flex items-center gap-3">
                                        <Badge variant="outline" className="text-[10px] shrink-0">{rec.platform_type}</Badge>
                                        <div className="flex-1 text-sm text-muted-foreground">
                                            {t("analysis.opportunity.aiEngines", { engines: rec.engines?.join(", ") || "—" })}
                                        </div>
                                        <span className={cn("text-[10px] font-semibold px-2 py-0.5 rounded-full shrink-0",
                                            rec.priority === "high" ? "bg-red-500/10 text-red-500" : rec.priority === "medium" ? "bg-amber-500/10 text-amber-500" : "bg-muted text-muted-foreground"
                                        )}>
                                            {priorityLabel(rec.priority)}
                                        </span>
                                    </div>
                                    {/* Citation share bar */}
                                    <div className="flex items-center gap-2">
                                        <span className="text-[10px] text-muted-foreground shrink-0 w-16">
                                            {t("analysis.opportunity.citationShare")}
                                        </span>
                                        <div className="flex-1 h-1.5 bg-muted rounded-full overflow-hidden">
                                            <div className="h-full bg-primary rounded-full" style={{ width: `${sharePercent}%` }} />
                                        </div>
                                        <span className="text-[10px] font-semibold text-primary shrink-0 w-8 text-right">{sharePercent}%</span>
                                    </div>
                                    {/* Engine breakdown inline bar */}
                                    {rec.engine_breakdown && (() => {
                                        // engine_breakdown values are raw counts — normalize to percentages
                                        const bdTotal = Object.values(rec.engine_breakdown!).reduce((a, b) => a + b, 0) || 1;
                                        return (
                                            <div className="flex items-center gap-2">
                                                <span className="text-[10px] text-muted-foreground shrink-0 w-16">
                                                    {t("analysis.opportunity.engineDistribution")}
                                                </span>
                                                <div className="flex-1 h-2 bg-muted rounded-full overflow-hidden flex">
                                                    {Object.entries(rec.engine_breakdown!).map(([engine, count], ei) => {
                                                        const pct = count / bdTotal;
                                                        const color = ({
                                                            chatgpt: "#10b981",
                                                            gemini: "#6366f1",
                                                            aimode: "#f59e0b",
                                                            ai_mode: "#f59e0b",
                                                            perplexity: "#8b5cf6",
                                                            aioverview: "#0ea5e9",
                                                            ai_overview: "#0ea5e9",
                                                            google_ai_overview: "#0ea5e9",
                                                        } as Record<string, string>)[engine.toLowerCase()] || "#8b5cf6";
                                                        return (
                                                            <div key={ei} className="h-full" style={{ width: `${Math.round(pct * 100)}%`, background: color }} title={`${engine}: ${Math.round(pct * 100)}%`} />
                                                        );
                                                    })}
                                                </div>
                                                <div className="flex items-center gap-1.5 shrink-0">
                                                    {Object.entries(rec.engine_breakdown!).map(([engine, count], ei) => {
                                                        const pct = count / bdTotal;
                                                        const color = ({
                                                            chatgpt: "#10b981",
                                                            gemini: "#6366f1",
                                                            aimode: "#f59e0b",
                                                            ai_mode: "#f59e0b",
                                                            perplexity: "#8b5cf6",
                                                            aioverview: "#0ea5e9",
                                                            ai_overview: "#0ea5e9",
                                                            google_ai_overview: "#0ea5e9",
                                                        } as Record<string, string>)[engine.toLowerCase()] || "#8b5cf6";
                                                        return (
                                                            <span key={ei} className="text-[9px] flex items-center gap-0.5">
                                                                <span className="w-1.5 h-1.5 rounded-full inline-block" style={{ background: color }} />
                                                                {Math.round(pct * 100)}%
                                                            </span>
                                                        );
                                                    })}
                                                </div>
                                            </div>
                                        );
                                    })()}
                                </div>
                            );
                        })}
                    </div>
                </div>
            )}
        </div>
    );
}
