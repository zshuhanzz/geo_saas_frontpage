import React, { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import {
    getVisibilityRankingGroups,
    getVisibilityRankingPrompts,
    getStaticReportFrozenList,
    type VisibilityRankingGroup,
    type VisibilityRankingPrompt,
} from "@/lib/api";
import {
    LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
    PieChart, Pie, Cell, Legend, BarChart, Bar,
} from "recharts";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Button } from "@/components/ui/button";
import { Switch } from "@/components/ui/switch";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import {
    DropdownMenu, DropdownMenuTrigger, DropdownMenuContent,
    DropdownMenuRadioGroup, DropdownMenuRadioItem,
} from "@/components/ui/dropdown-menu";
import { TrendingUp, TrendingDown, Trophy, BarChart3, Expand, Settings2, Info, ChevronDown, ChevronRight, Hash, Package, Check, Loader2, Minus } from "lucide-react";
import { GlassTooltip } from "@/components/ui/chart-tooltip";
import {
    buildVisibilityRankingRequestKeys,
    isVisibilityRankingRequestCurrent,
} from "@/components/insights/visibilityRankingRequest";
import { SortableMetricHeader } from "@/components/ui/SortableMetricHeader";
import { type MetricSortState, withMetricSortParams } from "@/lib/metricSort";
import { sortVisibilityTimeSeries, toCanonicalBrandMetricRows, type CanonicalBrandMetricRow } from "@/components/insights/visibilityMetricSort";
import { comparisonIndicatorState, type ComparisonImprovement } from "@/lib/comparisonIndicator";
import { ScopedStaticListRequestManager } from "@/pages/reports/components/scopedStaticListRequest";

const COLORS = [
    "#10b981", "#3b82f6", "#f59e0b", "#ef4444", "#8b5cf6",
    "#ec4899", "#14b8a6", "#f97316", "#6366f1", "#84cc16",
];

const PRODUCT_COLORS = [
    "#3b82f6", "#8b5cf6", "#f59e0b", "#14b8a6", "#ec4899",
    "#6366f1", "#f97316", "#84cc16",
];

function fmtDate(v: any) {
    const s = String(v);
    // Append T00:00:00 to force local-time parsing ("2026-03-09" alone is UTC midnight)
    const d = s.includes("T") ? new Date(s) : new Date(s + "T00:00:00");
    return `${d.getMonth() + 1}/${d.getDate()}`;
}

function fmtPercentValue(val: any) {
    if (val == null || Number.isNaN(Number(val))) return "—";
    return `${Number(val).toFixed(1)}%`;
}

function brandFaviconUrl(name: string) {
    const domain = name.toLowerCase().replace(/\s+/g, "");
    return `https://www.google.com/s2/favicons?domain=${domain}.com&sz=32`;
}

function BrandRankCellContent({ brand }: { brand?: CanonicalBrandMetricRow }) {
    if (!brand) return <>—</>;
    return (
        <span className="flex min-w-0 items-center justify-center gap-1.5">
            <img
                src={brandFaviconUrl(brand.name)}
                alt=""
                className="h-4 w-4 shrink-0 rounded-sm"
                onError={(event) => { event.currentTarget.style.display = "none"; }}
            />
            <span className="truncate" title={brand.name}>{brand.name}</span>
        </span>
    );
}

// ============================================================================
// Props
// ============================================================================

interface VisibilityDashboardProps {
    data: any;
    /** If true, hides TopicRankingMatrix and some secondary elements */
    compact?: boolean;
    /**
     * v1.2 Spec §8.4 "View By" dimension. Brand is the original behaviour;
     * product / topic render the same chart layout against a different
     * entity universe (normalized upstream in Visibility.tsx).
     */
    dimension?: "brand" | "product" | "topic";
    staticMode?: boolean;
    exportMode?: boolean;
    rankingMatrixQuery?: {
        clientId: string;
        params: Record<string, string>;
    };
    staticReportId?: string;
    staticFrozenLists?: Record<string, { total: number; default_sort_by: string; default_sort_order: "asc" | "desc"; scopes?: Array<{ parent_key: string; prompt_key: string; total: number }> }>;
    loadingSections?: {
        score?: boolean;
        visibilityRanking?: boolean;
        sov?: boolean;
        sovRanking?: boolean;
        position?: boolean;
        positionRanking?: boolean;
    };
    rankingSorts?: VisibilityRankingSorts;
    onRankingSortChange?: (list: keyof VisibilityRankingSorts, next: MetricSortState) => void;
    /** Dynamic APIs return the complete date series; static/export callers must prove completeness explicitly. */
    timeSeriesComplete?: boolean;
    /** Shows an explicit neutral/placeholder comparison even when the frozen delta is zero or null. */
    comparisonEnabled?: boolean;
}

export interface VisibilityRankingSorts {
    visibility: MetricSortState;
    sov: MetricSortState;
    position: MetricSortState;
}

// ============================================================================
// Main Dashboard Component
// ============================================================================

export default function VisibilityDashboard({ data, compact = false, dimension = "brand", staticMode = false, exportMode = false, rankingMatrixQuery, staticReportId, staticFrozenLists, loadingSections, rankingSorts, onRankingSortChange, timeSeriesComplete = false, comparisonEnabled = false }: VisibilityDashboardProps) {
    const { t } = useTranslation("insights");
    const dimLabel = t(`dimensionLabel.${dimension}`);
    const [showCompetitive, setShowCompetitive] = useState(false);
    const [visChartMode, setVisChartMode] = useState<"line" | "bar" | "table">("line");
    const [expandRanking, setExpandRanking] = useState<string | null>(null);
    const [showPrevVis, setShowPrevVis] = useState(false);
    const [showPrevAvgPos, setShowPrevAvgPos] = useState(false);
    const [timeSeriesSort, setTimeSeriesSort] = useState<MetricSortState | null>(null);

    const summary = data?.summary || {};
    const rawTimeSeries = data?.time_series || [];
    const rawPrevTimeSeries = data?.prev_time_series || [];
    const sovRanking = data?.sov_ranking || [];
    const visibilityRankingData = data?.visibility_ranking || [];
    const positionRankingData = data?.position_ranking || [];
    const topicSovRanking = data?.topic_sov_ranking || [];
    const productSovRanking = data?.product_sov_ranking || [];
    const competitiveSeries = data?.competitive_series || {};
    const rawAvgPositionSeries = data?.avg_position_series || [];
    const rawPrevAvgPositionSeries = data?.prev_avg_position_series || [];
    const isStaticMultiDay = staticMode && Number(data?.filters?.window_days || 1) > 1;

    // Merge prev period data INTO the main arrays by index position.
    // This avoids Recharts XAxis distortion caused by separate Line `data` props
    // with different date values.
    const timeSeries = rawTimeSeries.map((pt: any, i: number) => ({
        ...pt,
        prev_score: rawPrevTimeSeries[i]?.score ?? null,
    }));
    const sortedTimeSeries = timeSeriesSort
        ? sortVisibilityTimeSeries(timeSeries, timeSeriesComplete, timeSeriesSort)
        : timeSeries;
    const prevHasData = rawPrevTimeSeries.length > 0;
    const avgPositionSeries = rawAvgPositionSeries.map((pt: any, i: number) => ({
        ...pt,
        prev_avg_position: rawPrevAvgPositionSeries[i]?.avg_position ?? null,
    }));
    const prevAvgHasData = rawPrevAvgPositionSeries.length > 0;
    const useStaticScoreMetrics = staticMode && !isStaticMultiDay && timeSeries.length <= 1;
    const useStaticPositionMetrics = staticMode && !isStaticMultiDay && avgPositionSeries.length <= 1;

    // Build competitive line data (as SOV % per date)
    const companyNames = Object.keys(competitiveSeries);
    const competitiveLineData = (() => {
        if (!showCompetitive || companyNames.length === 0) return [];
        const dateMap: Record<string, any> = {};
        // First pass: collect raw counts
        for (const name of companyNames) {
            for (const pt of competitiveSeries[name]) {
                if (!dateMap[pt.date]) dateMap[pt.date] = { date: pt.date, _total: 0 };
                dateMap[pt.date][`_raw_${name}`] = pt.count;
                dateMap[pt.date]._total += pt.count;
            }
        }
        // Second pass: convert to percentages
        for (const entry of Object.values(dateMap)) {
            const total = entry._total || 1;
            for (const name of companyNames) {
                const raw = entry[`_raw_${name}`] || 0;
                entry[name] = Math.round((raw / total) * 1000) / 10; // e.g. 45.2
            }
        }
        return Object.values(dateMap).sort((a: any, b: any) => a.date.localeCompare(b.date));
    })();

    // Donut data
    const donutData = sovRanking.slice(0, 8).map((r: any) => ({
        name: (r.brand_name ?? r.company_name),
        value: r.sov_pct,
        isOwn: r.is_own,
    }));
    const ownSovPct = summary.sov_pct ?? sovRanking.find((r: any) => r.is_own)?.sov_pct ?? null;
    const visibilityRanking = visibilityRankingData.length > 0
        ? visibilityRankingData
        : [...sovRanking].sort((a: any, b: any) => (b.visibility_pct ?? 0) - (a.visibility_pct ?? 0));
    const positionRanking = positionRankingData.length > 0
        ? positionRankingData
        : sovRanking
            .filter((r: any) => r.avg_position != null)
            .sort((a: any, b: any) => a.avg_position - b.avg_position);
    const showPositionSection = Boolean(
        loadingSections?.position ||
        loadingSections?.positionRanking ||
        sovRanking.length > 0 ||
        avgPositionSeries.length > 0 ||
        positionRanking.length > 0 ||
        summary.avg_position != null,
    );

    return (
        <div className="space-y-8">
            {/* ============== Section 1: Visibility Score ============== */}
            <section>
                <SectionHeader
                    icon={<TrendingUp className="h-5 w-5 text-primary" />}
                    title={`${t("visibility.sectionScore.title")} · ${dimLabel}`}
                    subtitle={
                        dimension === "brand"
                            ? t("visibility.sectionScore.subtitleBrand")
                            : dimension === "product"
                                ? t("visibility.sectionScore.subtitleProduct")
                                : t("visibility.sectionScore.subtitleTopic")
                    }
                    chartMode={staticMode ? undefined : visChartMode}
                    onChartModeChange={staticMode ? undefined : (v: string) => setVisChartMode(v as any)}
                />
                <div className="grid items-stretch gap-6 xl:grid-cols-[344px_minmax(0,1fr)]">
                    {/* LEFT: KPI + Ranking */}
                    <RankingCard
                        title={t("visibility.sectionScore.rankTitle", { dim: dimLabel })}
                        rank={summary.visibility_rank}
                        rankChange={summary.visibility_rank_change}
                        comparisonEnabled={comparisonEnabled}
                        items={visibilityRanking}
                        valueKey="visibility_pct"
                        valueLabel={t("visibility.sectionScore.rankHeader")}
                        changeKey="visibility_pct_change"
                        valueSuffix="%"
                        accentColor="emerald"
                        loading={loadingSections?.visibilityRanking}
                        onExpand={() => setExpandRanking("visibility")}
                        sort={rankingSorts?.visibility || null}
                        onSortChange={onRankingSortChange ? (next) => onRankingSortChange("visibility", next) : undefined}
                        sortableMetrics={dimension === "brand" ? [
                            { key: "visibility_pct", label: t("visibility.sectionScore.rankHeader") },
                            { key: "visibility_pct_change", label: t("citations.sectionDomains.columnChange") },
                        ] : [{
                            key: dimension === "product" ? "visibility_pct" : "own_sov_pct",
                            label: t("visibility.sectionScore.rankHeader"),
                        }]}
                        entityDimension={dimension}
                        entityLabel={dimLabel}
                        summaryValue={`${summary.visibility_score ?? "—"}%`}
                        summaryChange={<MetricChangeBadge value={summary.visibility_score_change} improvement="higher" enabled={comparisonEnabled} />}
                        summaryLabel={dimension === "product" ? t("visibility.sectionScore.scoreLabelProduct") : t("visibility.sectionScore.scoreLabel")}
                        summaryTooltip={dimension === "product" ? t("visibility.sectionScore.scoreTooltipProduct") : t("visibility.sectionScore.scoreTooltip")}
                    />
                    {/* RIGHT: Chart */}
                    <Card className="rounded-lg border-border/60 bg-background/85 shadow-sm">
                        <CardHeader className="pb-2">
                            <div className="flex items-center justify-between">
                                <div className="text-sm font-medium text-muted-foreground">
                                    {t("visibility.sectionScore.title")}
                                </div>
                                {!staticMode && dimension === "brand" && (
                                    <div className="flex items-center gap-2 text-sm">
                                        <span className="text-muted-foreground">{t("visibility.sectionScore.competitiveSwitch")}</span>
                                        <Switch checked={showCompetitive} onCheckedChange={setShowCompetitive} />
                                    </div>
                                )}
                                {!staticMode && (
                                    <DropdownMenu>
                                        <DropdownMenuTrigger asChild>
                                            <Button variant="outline" size="sm" className="h-8 gap-1.5 text-xs">
                                                <Settings2 className="h-3.5 w-3.5" />
                                                {t("visibility.chartMode.button")}
                                            </Button>
                                        </DropdownMenuTrigger>
                                        <DropdownMenuContent align="end">
                                            <DropdownMenuRadioGroup value={visChartMode} onValueChange={(v) => setVisChartMode(v as any)}>
                                                <DropdownMenuRadioItem value="line">{t("visibility.chartMode.line")}</DropdownMenuRadioItem>
                                                <DropdownMenuRadioItem value="bar">{t("visibility.chartMode.bar")}</DropdownMenuRadioItem>
                                                <DropdownMenuRadioItem value="table">{t("visibility.chartMode.table")}</DropdownMenuRadioItem>
                                            </DropdownMenuRadioGroup>
                                        </DropdownMenuContent>
                                    </DropdownMenu>
                                )}
                            </div>
                        </CardHeader>
                        <CardContent>
                            {loadingSections?.score ? (
                                <ChartLoadingBlock heightClassName="h-[260px]" />
                            ) : useStaticScoreMetrics ? (
                                <StaticMetricGrid
                                    metrics={[
                                        { label: t("visibility.sectionScore.rankHeader"), value: `${summary.visibility_score ?? "—"}%` },
                                    ]}
                                />
                            ) : timeSeries.length > 0 ? (
                                visChartMode === "table" ? (
                                    <div className="rounded-md border overflow-hidden max-h-[260px] overflow-y-auto">
                                        <Table data-sort-list="visibility-time-series">
                                            <TableHeader>
                                                <TableRow className="bg-muted/20">
                                                    <TableHead>{t("visibility.chartTable.date")}</TableHead>
                                                    <TableHead className="text-right"><SortableMetricHeader label={t("visibility.chartTable.score")} metricKey="score" sort={timeSeriesSort} onChange={setTimeSeriesSort} disabled={!timeSeriesComplete} /></TableHead>
                                                    <TableHead className="text-right"><SortableMetricHeader label={dimension === "product" ? t("visibility.chartTable.productMentionedResponses") : t("visibility.chartTable.ownMentions")} metricKey="own_count" sort={timeSeriesSort} onChange={setTimeSeriesSort} disabled={!timeSeriesComplete} /></TableHead>
                                                    <TableHead className="text-right"><SortableMetricHeader label={dimension === "product" ? t("visibility.chartTable.eligibleResponses") : t("visibility.chartTable.totalMentions")} metricKey="total" sort={timeSeriesSort} onChange={setTimeSeriesSort} disabled={!timeSeriesComplete} /></TableHead>
                                                </TableRow>
                                            </TableHeader>
                                            <TableBody>
                                                {sortedTimeSeries.map((r: any) => (
                                                    <TableRow key={r.date}>
                                                        <TableCell className="text-sm">{fmtDate(r.date)}</TableCell>
                                                        <TableCell className="text-right font-medium">{r.score == null ? "—" : `${r.score}%`}</TableCell>
                                                        <TableCell className="text-right">{r.own_count}</TableCell>
                                                        <TableCell className="text-right">{r.total}</TableCell>
                                                    </TableRow>
                                                ))}
                                            </TableBody>
                                        </Table>
                                    </div>
                                ) : (
                                    <>
                                        <ResponsiveContainer width="100%" height={260}>
                                            {visChartMode === "bar" ? (
                                                <BarChart data={timeSeries}>
                                                    <XAxis dataKey="date" stroke="#888" fontSize={11} tickLine={false} axisLine={false} tickFormatter={fmtDate} />
                                                    <YAxis stroke="#888" fontSize={11} tickLine={false} axisLine={false} unit="%" width={40} domain={[(dataMin: number) => Math.max(0, Math.floor(dataMin - 5)), (dataMax: number) => Math.ceil(dataMax + 5)]} />
                                                    <Tooltip content={<GlassTooltip />} formatter={(val: any) => fmtPercentValue(val)} labelFormatter={(v: any) => { const s = String(v); const d = s.includes("T") ? new Date(s) : new Date(s + "T00:00:00"); return d.toLocaleDateString(); }} />
                                                    <Bar dataKey="score" fill="#10b981" radius={[4, 4, 0, 0]} />
                                                </BarChart>
                                            ) : (
                                                <LineChart data={showCompetitive ? competitiveLineData : timeSeries}>
                                                    <XAxis dataKey="date" stroke="#888" fontSize={11} tickLine={false} axisLine={false} tickFormatter={fmtDate} />
                                                    <YAxis stroke="#888" fontSize={11} tickLine={false} axisLine={false} unit="%" width={40} domain={[(dataMin: number) => Math.max(0, Math.floor(dataMin - 5)), (dataMax: number) => Math.ceil(dataMax + 5)]} />
                                                    <Tooltip content={<GlassTooltip />} formatter={(val: any, name: any) => [fmtPercentValue(val), name]} labelFormatter={(v: any) => { const s = String(v); const d = s.includes("T") ? new Date(s) : new Date(s + "T00:00:00"); return d.toLocaleDateString(); }} />
                                                    {showCompetitive ? (
                                                        companyNames.map((name, i) => (
                                                            <Line key={name} type="monotone" dataKey={name} stroke={COLORS[i % COLORS.length]} strokeWidth={2} dot={{ r: 2 }} />
                                                        ))
                                                    ) : (
                                                        <>
                                                            <Line type="monotone" dataKey="score" stroke="#10b981" strokeWidth={2.5} dot={{ r: 3, fill: "#10b981" }} activeDot={{ r: 5 }} name={t("visibility.chartLegend.current")} connectNulls={false} />
                                                            {prevHasData && showPrevVis && (
                                                                <Line type="monotone" dataKey="prev_score" stroke="#10b981" strokeWidth={1.5} strokeDasharray="5 5" dot={false} opacity={0.35} name={t("visibility.chartLegend.previous")} connectNulls />
                                                            )}
                                                        </>
                                                    )}
                                                </LineChart>
                                            )}
                                        </ResponsiveContainer>
                                        {prevHasData && visChartMode === "line" && !showCompetitive && (
                                            <div className="flex items-center gap-4 mt-2 ml-10">
                                                <label className="flex items-center gap-1.5 cursor-default select-none text-xs text-muted-foreground px-2 py-1 rounded-md">
                                                    <span className="inline-flex items-center justify-center w-3.5 h-3.5 rounded-sm border border-emerald-500 bg-emerald-500"><Check className="w-2.5 h-2.5 text-white" /></span>
                                                    {t("filters.currentPeriod")}
                                                </label>
                                                <label className="flex items-center gap-1.5 cursor-pointer select-none text-xs text-muted-foreground hover:bg-muted/50 px-2 py-1 rounded-md transition-colors" onClick={() => setShowPrevVis(!showPrevVis)}>
                                                    <span className={"inline-flex items-center justify-center w-3.5 h-3.5 rounded-sm border transition-colors " + (showPrevVis ? "border-gray-400 bg-gray-400" : "border-gray-300")}>{showPrevVis && <Check className="w-2.5 h-2.5 text-white" />}</span>
                                                    {t("filters.previousPeriod")}
                                                </label>
                                            </div>
                                        )}
                                    </>
                                )
                            ) : (
                                <EmptyState message={t("visibility.sectionScore.emptyState")} />
                            )}
                        </CardContent>
                    </Card>
                </div>
            </section>

            {/* ============== Section 2: Share of Voice ============== */}
            <section>
                <SectionHeader
                    icon={<BarChart3 className="h-5 w-5 text-primary" />}
                    title={`${t("visibility.sectionSov.title")} · ${dimLabel}`}
                    subtitle={
                        dimension === "brand"
                            ? t("visibility.sectionSov.subtitleBrand")
                            : dimension === "product"
                                ? t("visibility.sectionSov.subtitleProduct")
                                : t("visibility.sectionSov.subtitleTopic")
                    }
                />
                <div className="grid items-stretch gap-6 xl:grid-cols-[344px_minmax(0,1fr)]">
                    {/* LEFT: KPI + Ranking */}
                    <RankingCard
                        title={t("visibility.sectionSov.rankTitle", { dim: dimLabel })}
                        rank={summary.sov_rank}
                        rankChange={summary.sov_rank_change}
                        comparisonEnabled={comparisonEnabled}
                        items={sovRanking}
                        valueKey="mention_count"
                        valueLabel={t("visibility.sectionSov.rankHeader")}
                        changeKey="sov_pct_change"
                        accentColor="emerald"
                        loading={loadingSections?.sovRanking}
                        onExpand={() => setExpandRanking("sov")}
                        sort={rankingSorts?.sov || null}
                        onSortChange={onRankingSortChange ? (next) => onRankingSortChange("sov", next) : undefined}
                        sortableMetrics={dimension === "brand" ? [
                            { key: "mention_count", label: t("visibility.sectionSov.rankHeader") },
                            { key: "sov_pct_change", label: t("citations.sectionDomains.columnChange") },
                        ] : [{ key: "mention_count", label: t("visibility.sectionSov.rankHeader") }]}
                        entityDimension={dimension}
                        entityLabel={dimLabel}
                        summaryValue={`${ownSovPct ?? "—"}%`}
                        summaryChange={<MetricChangeBadge value={summary.sov_pct_change} improvement="higher" enabled={comparisonEnabled} />}
                        summaryLabel={dimension === "product" ? t("visibility.sectionSov.leadingProductLabel") : t("visibility.sectionSov.sovLabel")}
                        summaryTooltip={dimension === "product" ? t("visibility.sectionSov.leadingProductTooltip") : t("visibility.sectionSov.sovTooltip")}
                    />
                    {/* RIGHT: Chart */}
                    <Card className="rounded-lg border-border/60 bg-background/85 shadow-sm">
                        <CardHeader className="pb-2">
                            <div className="text-sm font-medium text-muted-foreground">
                                {t("visibility.sectionSov.title")}
                            </div>
                        </CardHeader>
                        <CardContent>
                            {loadingSections?.sov ? (
                                <ChartLoadingBlock heightClassName="h-[280px]" />
                            ) : sovRanking.length > 0 ? (
                                <div className="flex flex-col gap-3 py-2">
                                    {sovRanking.slice(0, 10).map((r: any, i: number) => {
                                        const maxSov = Math.max(...sovRanking.map((x: any) => Number(x.sov_pct || 0)));
                                        const pct = maxSov > 0 ? (Number(r.sov_pct || 0) / maxSov) * 100 : 0;
                                        const name = r.brand_name ?? r.company_name ?? "";
                                        const sovPctDisplay = `${Number(r.sov_pct ?? 0).toFixed(2)}%`;
                                        // Own brand = green (#00E676), others get descending green-grey shades matching Figma
                                        const barColors = ["#688C7C", "#88A394", "#A4B7AA", "#7D9487", "#B9C7B9", "#94A699", "#8FA89A", "#9EB5A7"];
                                        const barColor = r.is_own ? "#00E676" : barColors[i % barColors.length];
                                        return (
                                            <div key={name} className="flex items-center gap-4" style={{ height: 40 }}>
                                                <span className="shrink-0 truncate text-sm text-foreground" style={{ width: 112 }} title={name}>{name}</span>
                                                <div className="flex-1 rounded-sm bg-black/[0.04] dark:bg-white/[0.06]" style={{ height: 12 }}>
                                                    <div
                                                        className="h-full rounded-sm transition-all duration-500"
                                                        style={{ width: `${pct}%`, backgroundColor: barColor }}
                                                    />
                                                </div>
                                                <span className="shrink-0 text-right text-sm text-foreground tabular-nums" style={{ width: 88 }}>{sovPctDisplay}</span>
                                            </div>
                                        );
                                    })}
                                </div>
                            ) : (
                                <EmptyState message={t("visibility.sectionSov.emptyState")} />
                            )}
                        </CardContent>
                    </Card>
                </div>
            </section>

            {/* ============== Section 3: Average Position ============== */}
            {showPositionSection && (
                <section>
                    <SectionHeader
                        icon={<TrendingUp className="h-5 w-5 text-primary" />}
                        title={t("visibility.sectionPosition.title")}
                        subtitle={t("visibility.sectionPosition.subtitle")}
                    />
                    <div className="grid items-stretch gap-6 xl:grid-cols-[344px_minmax(0,1fr)]">
                        {/* LEFT: KPI + Ranking */}
                        <RankingCard
                            title={t("visibility.sectionPosition.rankTitle")}
                            rank={summary.avg_position_rank}
                            rankChange={summary.avg_position_rank_change}
                            comparisonEnabled={comparisonEnabled}
                            items={positionRanking}
                            valueKey="avg_position"
                            valueLabel={t("visibility.sectionPosition.rankHeader")}
                            valuePrefix="#"
                            accentColor="emerald"
                            loading={loadingSections?.positionRanking}
                            onExpand={() => setExpandRanking("position")}
                            sort={rankingSorts?.position || null}
                            onSortChange={onRankingSortChange ? (next) => onRankingSortChange("position", next) : undefined}
                            sortableMetrics={dimension === "brand" ? [
                                { key: "avg_position", label: t("visibility.sectionPosition.rankHeader") },
                            ] : dimension === "product" ? [{ key: "avg_position", label: t("visibility.sectionPosition.rankHeader") }] : []}
                            entityDimension={dimension}
                            entityLabel={dimLabel}
                            summaryValue={summary.avg_position != null ? `#${summary.avg_position}` : "—"}
                            summaryChange={<MetricChangeBadge value={summary.avg_position_change} improvement="lower" enabled={comparisonEnabled} unit="" />}
                            summaryLabel={t("visibility.sectionPosition.positionLabel")}
                            summaryTooltip={t("visibility.sectionPosition.positionTooltip")}
                        />
                        {/* RIGHT: Chart */}
                        <Card className="rounded-lg border-border/60 bg-background/85 shadow-sm">
                            <CardHeader className="pb-2">
                                <div className="text-sm font-medium text-muted-foreground">
                                    {t("visibility.sectionPosition.title")}
                                </div>
                            </CardHeader>
                            <CardContent>
                                {loadingSections?.position ? (
                                    <ChartLoadingBlock heightClassName="h-[260px]" />
                                ) : useStaticPositionMetrics ? (
                                    <StaticMetricGrid
                                        metrics={[
                                            { label: t("visibility.sectionPosition.positionLabel"), value: summary.avg_position != null ? `#${summary.avg_position}` : "—" },
                                        ]}
                                    />
                                ) : avgPositionSeries.length > 0 ? (
                                    <>
                                        <ResponsiveContainer width="100%" height={260}>
                                            <LineChart data={avgPositionSeries}>
                                                <XAxis dataKey="date" stroke="#888" fontSize={11} tickLine={false} axisLine={false} tickFormatter={fmtDate} />
                                                <YAxis stroke="#888" fontSize={11} tickLine={false} axisLine={false} reversed domain={[1, (dataMax: number) => Math.ceil(dataMax + 1)]} width={30} />
                                                <Tooltip content={<GlassTooltip />} formatter={(val: any, name: any) => [`#${Number(val).toFixed(1)}`, name]} labelFormatter={(v: any) => { const s = String(v); const d = s.includes("T") ? new Date(s) : new Date(s + "T00:00:00"); return d.toLocaleDateString(); }} />
                                                <Line type="monotone" dataKey="avg_position" stroke="#10b981" strokeWidth={2.5} dot={{ r: 3, fill: "#10b981" }} activeDot={{ r: 5 }} name={t("visibility.chartLegend.current")} />
                                                {prevAvgHasData && showPrevAvgPos && (
                                                    <Line type="monotone" dataKey="prev_avg_position" stroke="#10b981" strokeWidth={1.5} strokeDasharray="5 5" dot={false} opacity={0.35} name={t("visibility.chartLegend.previous")} connectNulls />
                                                )}
                                            </LineChart>
                                        </ResponsiveContainer>
                                        {prevAvgHasData && (
                                            <div className="flex items-center gap-4 mt-2 ml-10">
                                                <label className="flex items-center gap-1.5 cursor-default select-none text-xs text-muted-foreground px-2 py-1 rounded-md">
                                                    <span className="inline-flex items-center justify-center w-3.5 h-3.5 rounded-sm border border-emerald-500 bg-emerald-500"><Check className="w-2.5 h-2.5 text-white" /></span>
                                                    {t("filters.currentPeriod")}
                                                </label>
                                                <label className="flex items-center gap-1.5 cursor-pointer select-none text-xs text-muted-foreground hover:bg-muted/50 px-2 py-1 rounded-md transition-colors" onClick={() => setShowPrevAvgPos(!showPrevAvgPos)}>
                                                    <span className={"inline-flex items-center justify-center w-3.5 h-3.5 rounded-sm border transition-colors " + (showPrevAvgPos ? "border-gray-400 bg-gray-400" : "border-gray-300")}>{showPrevAvgPos && <Check className="w-2.5 h-2.5 text-white" />}</span>
                                                    {t("filters.previousPeriod")}
                                                </label>
                                            </div>
                                        )}
                                    </>
                                ) : (
                                    <EmptyState message={t("visibility.sectionPosition.emptyState")} />
                                )}
                            </CardContent>
                        </Card>
                    </div>
                </section>
            )}

            {/* ============== Section 4: Ranking Table ============== */}
            {!compact && (topicSovRanking.length > 0 || productSovRanking.length > 0 || rankingMatrixQuery) && (
                <TopicRankingMatrix
                    topicSovRanking={topicSovRanking}
                    productSovRanking={productSovRanking}
                    exportMode={exportMode}
                    rankingMatrixQuery={rankingMatrixQuery}
                    staticReportId={staticReportId}
                    staticFrozenLists={staticFrozenLists}
                />
            )}

            {/* ============== Expand Dialog ============== */}
            <Dialog open={!!expandRanking} onOpenChange={() => setExpandRanking(null)}>
                <DialogContent className="max-w-lg max-h-[80vh] overflow-y-auto">
                    <DialogHeader>
                        <DialogTitle>{t("visibility.fullRankingDialog.title")}</DialogTitle>
                        <DialogDescription>{t("visibility.fullRankingDialog.description")}</DialogDescription>
                    </DialogHeader>
                    <div className="space-y-2 mt-2">
                        {(expandRanking === "visibility"
                            ? visibilityRanking
                            : expandRanking === "position"
                                ? positionRanking
                                : sovRanking
                        ).slice(0, 20).map((r: any, i: number) => (
                            <div key={(r.brand_name ?? r.company_name)} className="flex items-center gap-2 py-1">
                                <span className="text-xs text-muted-foreground w-6">{r.rank ?? i + 1}.</span>
                                <span className={`text-sm flex-1 ${r.is_own ? "font-semibold text-emerald-500" : ""}`}>
                                    {(r.brand_name ?? r.company_name)}
                                    {r.is_own && <span className="text-[9px] bg-emerald-500/10 text-emerald-500 px-1 ml-1 rounded">{t("visibility.sectionScore.rankOwnBadge")}</span>}
                                </span>
                                <span className="text-xs text-muted-foreground">
                                    {expandRanking === "position" ? (r.avg_position == null ? "—" : `#${r.avg_position}`) : expandRanking === "sov" ? `${r.mention_count}` : `${r.visibility_pct ?? 0}%`}
                                </span>
                            </div>
                        ))}
                    </div>
                </DialogContent>
            </Dialog>
        </div>
    );
}


// ============================================================================
// Sub-components
// ============================================================================

function SectionHeader({ icon, title, subtitle, chartMode, onChartModeChange }: {
    icon: React.ReactNode; title: string; subtitle: string;
    chartMode?: string; onChartModeChange?: (v: string) => void;
}) {
    const { t } = useTranslation("insights");
    return (
        <div className="mb-5">
            <div className="flex items-center justify-between">
            <div>
                <h2 className="text-lg font-semibold flex items-center gap-2">{icon}{title}</h2>
                <p className="text-sm text-muted-foreground mt-0.5">{subtitle}</p>
            </div>
            {chartMode && onChartModeChange && (
                <DropdownMenu>
                    <DropdownMenuTrigger asChild>
                        <Button variant="outline" size="sm" className="h-8 gap-1.5 text-xs">
                            <Settings2 className="h-3.5 w-3.5" />
                            {t("visibility.chartMode.button")}
                        </Button>
                    </DropdownMenuTrigger>
                    <DropdownMenuContent align="end">
                        <DropdownMenuRadioGroup value={chartMode} onValueChange={onChartModeChange}>
                            <DropdownMenuRadioItem value="line">{t("visibility.chartMode.line")}</DropdownMenuRadioItem>
                            <DropdownMenuRadioItem value="bar">{t("visibility.chartMode.bar")}</DropdownMenuRadioItem>
                            <DropdownMenuRadioItem value="table">{t("visibility.chartMode.table")}</DropdownMenuRadioItem>
                        </DropdownMenuRadioGroup>
                    </DropdownMenuContent>
                </DropdownMenu>
            )}
            </div>
            <div className="mt-3 h-px bg-gradient-to-r from-primary/20 via-primary/5 to-transparent" />
        </div>
    );
}

function RankingCard({
    title, rank, rankChange, items, valueKey, valueLabel, valueSuffix, valuePrefix, changeKey, accentColor, loading, onExpand,
    sort, onSortChange, sortableMetrics = [], comparisonEnabled = false, entityDimension = "brand", entityLabel,
    summaryValue, summaryChange, summaryLabel, summaryTooltip,
}: {
    title: string; rank: number | null; rankChange?: number | null; items: any[]; valueKey: string; valueLabel: string;
    valueSuffix?: string; valuePrefix?: string; changeKey?: string; accentColor: string; loading?: boolean; onExpand: () => void;
    sort?: MetricSortState | null;
    onSortChange?: (next: MetricSortState) => void;
    sortableMetrics?: Array<{ key: string; label: string }>;
    comparisonEnabled?: boolean;
    entityDimension?: "brand" | "product" | "topic";
    entityLabel?: string;
    summaryValue?: React.ReactNode;
    summaryChange?: React.ReactNode;
    summaryLabel?: string;
    summaryTooltip?: string;
}) {
    const { t } = useTranslation("insights");
    const accent = accentColor === "blue" ? "text-blue-500" : "text-emerald-500";
    const accentBadge = accentColor === "blue" ? "bg-blue-500/10 text-blue-500" : "bg-emerald-500/10 text-emerald-500";
    const visibleItems = items.slice(0, 5);

    return (
        <div className="flex flex-col gap-3">
            {/* KPI accent card — matches Figma #178:5 green accent header */}
            {summaryValue !== undefined && (
                <div className="rounded-xl border border-[#6CB991] bg-[#CDEEDD] px-6 py-5 shadow-sm dark:border-emerald-700 dark:bg-emerald-950/40">
                    <div className="text-3xl font-bold flex items-center gap-2 text-foreground">
                        {summaryValue}
                        {summaryChange}
                    </div>
                    {summaryLabel && (
                        <div className="text-xs text-muted-foreground mt-1 flex items-center gap-1">
                            {summaryLabel}
                            {summaryTooltip && (
                                <span className="relative group">
                                    <Info className="h-3 w-3 text-muted-foreground/50 cursor-help" />
                                    <span className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1.5 px-2.5 py-1.5 rounded-md bg-popover border text-popover-foreground text-[11px] leading-tight w-48 hidden group-hover:block shadow-md z-50">{summaryTooltip}</span>
                                </span>
                            )}
                        </div>
                    )}
                </div>
            )}
            {/* Ranking card */}
            <Card className="rounded-lg border-border/60 bg-background/85 shadow-sm flex-1">
                <CardHeader className="pb-2">
                    <CardTitle className="text-sm font-medium flex items-center gap-2">
                        <Trophy className="h-4 w-4 text-amber-500" />
                        {title}
                    </CardTitle>
                    <div className="text-2xl font-bold flex items-center gap-2">
                        <span>{rank ? `#${rank}` : "—"}</span>
                        <RankChangeBadge change={rankChange} enabled={comparisonEnabled} />
                    </div>
                </CardHeader>
                <CardContent className="space-y-1.5">
                    <div className="text-[10px] text-muted-foreground uppercase tracking-wider mb-2 flex justify-between">
                        <span>{entityLabel || t("visibility.sectionScore.rankBrandLabel")}</span>
                        {sort && onSortChange && sortableMetrics.length > 0 ? (
                            <div className="flex max-w-[70%] flex-wrap justify-end gap-1" data-sort-list="visibility-ranking">
                                {sortableMetrics.map((metric) => (
                                    <SortableMetricHeader key={metric.key} label={metric.label} metricKey={metric.key} sort={sort} onChange={onSortChange} />
                                ))}
                            </div>
                        ) : <span>{valueLabel}</span>}
                    </div>
                    {loading && visibleItems.length === 0 ? (
                        <ChartLoadingBlock heightClassName="h-40" />
                    ) : visibleItems.map((r: any, i: number) => (
                        <div key={(r.brand_name ?? r.company_name)} className="flex items-center gap-2">
                            <span className="text-xs text-muted-foreground w-5">{r.rank ?? i + 1}.</span>
                            {entityDimension === "product" ? (
                                <Package className="h-4 w-4 shrink-0 text-muted-foreground" />
                            ) : (
                                <img
                                    src={brandFaviconUrl((r.brand_name ?? r.company_name) || "")}
                                    alt="" className="w-4 h-4 rounded-sm flex-shrink-0"
                                    onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
                                />
                            )}
                            <div className="flex-1 min-w-0">
                                <div className="flex items-center gap-1.5">
                                    <span className={`text-sm truncate ${r.is_own && entityDimension !== "product" ? `font-semibold ${accent}` : ""}`}>{(r.brand_name ?? r.company_name)}</span>
                                    {r.is_own && entityDimension !== "product" && <span className={`text-[9px] ${accentBadge} px-1 rounded`}>{t("visibility.sectionScore.rankOwnBadge")}</span>}
                                </div>
                            </div>
                            <span className={`text-xs font-medium ${r.is_own && entityDimension !== "product" ? accent : "text-foreground"}`}>
                                {r[valueKey] == null ? "—" : `${valuePrefix || ""}${r[valueKey]}${valueSuffix || ""}`}
                            </span>
                            {changeKey && (
                                <MetricChangeBadge value={r[changeKey]} improvement="higher" enabled={comparisonEnabled} />
                            )}
                        </div>
                    ))}
                    {loading && visibleItems.length > 0 && (
                        <div className="flex items-center justify-center py-1 text-xs text-muted-foreground"><Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />{t("visibility.topicRanking.loading")}</div>
                    )}
                    {!loading && items.length === 0 && <EmptyState message={t("visibility.sectionScore.emptyRanking")} />}
                    {items.length > 5 && (
                        <Button variant="ghost" size="sm" className="w-full mt-2 text-xs" onClick={onExpand}>
                            <Expand className="h-3 w-3 mr-1" /> {t("visibility.sectionScore.expand")}
                        </Button>
                    )}
                </CardContent>
            </Card>
        </div>
    );
}

function ChartLoadingBlock({ heightClassName = "h-56" }: { heightClassName?: string }) {
    return (
        <div className={`flex items-center justify-center rounded-lg border border-dashed border-border/60 bg-muted/10 ${heightClassName}`}>
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
        </div>
    );
}

function MetricChangeBadge({ value, improvement, enabled, unit = "%" }: { value?: number | null; improvement: ComparisonImprovement; enabled: boolean; unit?: string }) {
    const state = comparisonIndicatorState(value, improvement, enabled, unit);
    if (!state.visible) return null;
    if (state.direction === "none") {
        return (
            <span className="text-sm font-medium flex items-center gap-0.5 text-muted-foreground">
                {state.display === "—" ? null : <Minus className="h-3.5 w-3.5" />}
                {state.display}
            </span>
        );
    }
    return (
        <span className={`text-sm font-medium flex items-center gap-0.5 ${state.tone === "positive" ? "text-emerald-500" : "text-red-400"}`}>
            {state.direction === "up" ? <TrendingUp className="h-3.5 w-3.5" /> : <TrendingDown className="h-3.5 w-3.5" />}
            {state.display}
        </span>
    );
}

function RankChangeBadge({ change, enabled = false }: { change?: number | null; enabled?: boolean }) {
    const state = comparisonIndicatorState(change, "lower", enabled, "");
    if (!state.visible) return null;
    if (state.direction === "none") {
        return (
            <span className="text-sm font-medium flex items-center gap-0.5 text-muted-foreground">
                {state.display === "—" ? null : <Minus className="h-3.5 w-3.5" />}
                {state.display}
            </span>
        );
    }
    return (
        <span className={`text-sm font-medium flex items-center gap-0.5 ${state.tone === "positive" ? "text-emerald-500" : "text-red-400"}`}>
            {state.direction === "up" ? <TrendingUp className="h-3.5 w-3.5" /> : <TrendingDown className="h-3.5 w-3.5" />}
            {state.direction === "up" ? "↑" : "↓"}{state.display}
        </span>
    );
}


function StaticMetricGrid({ metrics }: { metrics: Array<{ label: string; value: any }> }) {
    if (metrics.length === 1) {
        const metric = metrics[0];
        return (
            <div className="relative min-h-[260px] overflow-hidden rounded-lg border bg-muted/20 p-6">
                <div className="absolute right-6 top-6 h-24 w-24 rounded-full border border-primary/15" />
                <div className="absolute right-12 top-12 h-12 w-12 rounded-full bg-primary/10" />
                <div className="relative flex h-full min-h-[212px] flex-col justify-between">
                    <div>
                        <div className="text-sm font-medium text-muted-foreground">{metric.label}</div>
                        <div className="mt-4 text-5xl font-bold tracking-tight gradient-text-static">{metric.value}</div>
                    </div>
                    <div className="flex items-end gap-2">
                        {[36, 58, 44, 72, 52, 88].map((height, index) => (
                            <span
                                key={height + index}
                                className="w-8 rounded-t-md bg-primary/20"
                                style={{ height }}
                            />
                        ))}
                    </div>
                </div>
            </div>
        );
    }

    return (
        <div className="grid gap-3 sm:grid-cols-3">
            {metrics.map((metric) => (
                <div key={metric.label} className="rounded-lg border bg-muted/20 p-4">
                    <div className="text-xs text-muted-foreground">{metric.label}</div>
                    <div className="mt-2 text-2xl font-bold gradient-text-static">{metric.value}</div>
                </div>
            ))}
        </div>
    );
}

function TopicRankingMatrix({
    topicSovRanking,
    productSovRanking,
    exportMode = false,
    rankingMatrixQuery,
    staticReportId,
    staticFrozenLists,
}: {
    topicSovRanking: any[];
    productSovRanking: any[];
    exportMode?: boolean;
    rankingMatrixQuery?: { clientId: string; params: Record<string, string> };
    staticReportId?: string;
    staticFrozenLists?: Record<string, { total: number; default_sort_by: string; default_sort_order: "asc" | "desc"; scopes?: Array<{ parent_key: string; prompt_key: string; total: number }> }>;
}) {
    const { t } = useTranslation("insights");
    const { t: reportT } = useTranslation("reports");
    const { t: commonT } = useTranslation("common");
    const [groupBy, setGroupBy] = useState<"topic" | "product">("topic");
    const [expandedRows, setExpandedRows] = useState<Set<string>>(new Set());
    const [fullPrompt, setFullPrompt] = useState<string | null>(null);
    const [remoteGroups, setRemoteGroups] = useState<VisibilityRankingGroup[]>([]);
    const [remoteGroupsLoadedKey, setRemoteGroupsLoadedKey] = useState("");
    const [groupsLoading, setGroupsLoading] = useState(false);
    const [remoteGroupsVisible, setRemoteGroupsVisible] = useState(false);
    const [groupOffset, setGroupOffset] = useState(0);
    const [groupTotal, setGroupTotal] = useState(0);
    const [groupBrandPages, setGroupBrandPages] = useState<Record<string, { items: any[]; total: number; offset: number; loading: boolean }>>({});
    const [promptBrandPages, setPromptBrandPages] = useState<Record<string, { items: any[]; total: number; offset: number; loading: boolean }>>({});
    const [matrixError, setMatrixError] = useState(false);
    const [matrixRetryNonce, setMatrixRetryNonce] = useState(0);
    const [promptPages, setPromptPages] = useState<Record<string, { items: VisibilityRankingPrompt[]; total: number; offset: number; loading: boolean; queryKey: string }>>({});
    const groupRequestSeq = useRef(0);
    const promptRequestSeq = useRef<Record<string, number>>({});
    const promptRequestControllers = useRef<Record<string, AbortController>>({});
    const groupBrandRequestManager = useRef(new ScopedStaticListRequestManager());
    const promptBrandRequestManager = useRef(new ScopedStaticListRequestManager());
    const rankingMatrixQueryRef = useRef(rankingMatrixQuery);
    rankingMatrixQueryRef.current = rankingMatrixQuery;
    const sectionRef = useRef<HTMLElement | null>(null);
    const groupSort = useMemo<MetricSortState>(() => ({ metricKey: "total_mentions", direction: "desc" }), []);
    const promptSort = useMemo<MetricSortState>(() => ({ metricKey: "total_mentions", direction: "desc" }), []);
    const brandSort = useMemo<MetricSortState>(() => ({ metricKey: "rank", direction: "asc" }), []);

    const effectiveGroupBy = exportMode ? "topic" : groupBy;
    const staticRemoteMode = !!staticReportId && !exportMode;
    const staticDefaultGroupsHydrated = staticRemoteMode
        && groupOffset === 0
        && groupSort.metricKey === "total_mentions"
        && groupSort.direction === "desc";
    const staticDefaultPromptsHydrated = promptSort.metricKey === "total_mentions" && promptSort.direction === "desc";
    const staticDefaultBrandsHydrated = brandSort.metricKey === "rank" && brandSort.direction === "asc";
    const remoteMode = (!!rankingMatrixQuery || (staticRemoteMode && !staticDefaultGroupsHydrated)) && !exportMode;
    const { baseQueryKey, groupQueryKey, promptQueryKey } = buildVisibilityRankingRequestKeys({
        clientId: rankingMatrixQuery?.clientId || "",
        params: rankingMatrixQuery?.params || {},
        groupBy: effectiveGroupBy,
        groupSort,
        promptSort,
        brandSort,
    });
    const matrixBaseQueryKey = `${staticReportId || "dynamic"}:${baseQueryKey}`;
    const matrixGroupQueryKey = `${staticReportId || "dynamic"}:${groupQueryKey}`;
    const matrixPromptQueryKey = `${staticReportId || "dynamic"}:${promptQueryKey}`;
    const currentGroupQueryKeyRef = useRef(matrixGroupQueryKey);
    const currentPromptQueryKeyRef = useRef(matrixPromptQueryKey);
    useEffect(() => {
        currentGroupQueryKeyRef.current = matrixGroupQueryKey;
        currentPromptQueryKeyRef.current = matrixPromptQueryKey;
    }, [matrixGroupQueryKey, matrixPromptQueryKey]);
    const localData = effectiveGroupBy === "topic" ? topicSovRanking : productSovRanking;
    const data = remoteMode && remoteGroupsLoadedKey === matrixGroupQueryKey
        ? remoteGroups.map((group) => ({
            topic_id: group.group_key,
            topic_name: group.group_name,
            product: group.group_name,
            prompt_count: group.prompt_count,
            total_mentions: group.total_mentions,
            brands: group.brands,
            prompts: [],
        }))
        : localData;
    const effectiveGroupTotal = staticDefaultGroupsHydrated
        ? Number(staticFrozenLists?.[`visibility.${effectiveGroupBy}`]?.total ?? localData.length)
        : groupTotal;

    const PROMPT_PAGE_SIZE = 20;

    useEffect(() => {
        const invalidatePromptRequests = () => {
            Object.values(promptRequestControllers.current).forEach((controller) => controller.abort());
            promptRequestControllers.current = {};
            Object.keys(promptRequestSeq.current).forEach((rowKey) => {
                promptRequestSeq.current[rowKey] = (promptRequestSeq.current[rowKey] || 0) + 1;
            });
            groupBrandRequestManager.current.abortAll();
            promptBrandRequestManager.current.abortAll();
        };
        invalidatePromptRequests();
        setPromptPages({});
        setRemoteGroupsLoadedKey("");
        setGroupBrandPages({});
        setPromptBrandPages({});
        setExpandedRows(new Set());
        setFullPrompt(null);
        return invalidatePromptRequests;
    }, [groupOffset, matrixBaseQueryKey, matrixGroupQueryKey, matrixPromptQueryKey, remoteMode]);

    useEffect(() => {
        if (!remoteMode) {
            setRemoteGroupsVisible(true);
            return;
        }
        setRemoteGroupsVisible(false);
        const el = sectionRef.current;
        if (!el || typeof IntersectionObserver === "undefined") {
            setRemoteGroupsVisible(true);
            return;
        }
        const observer = new IntersectionObserver(
            ([entry]) => {
                if (entry?.isIntersecting) {
                    setRemoteGroupsVisible(true);
                    observer.disconnect();
                }
            },
            { rootMargin: "360px 0px" },
        );
        observer.observe(el);
        return () => observer.disconnect();
    }, [remoteMode, baseQueryKey]);

    useEffect(() => {
        const dynamicQuery = rankingMatrixQueryRef.current;
        if (!remoteMode || (!dynamicQuery && !staticReportId) || !remoteGroupsVisible) return;
        const controller = new AbortController();
        const requestId = ++groupRequestSeq.current;
        const requestQueryKey = matrixGroupQueryKey;
        setGroupsLoading(true);
        if (staticRemoteMode) setMatrixError(false);
        const request = staticRemoteMode && staticReportId
            ? getStaticReportFrozenList(staticReportId, `visibility.${effectiveGroupBy}`, {
                sort_by: groupSort.metricKey,
                sort_order: groupSort.direction,
                limit: 20,
                offset: groupOffset,
              }, { signal: controller.signal }).then((groupResponse) => {
                const groups = (groupResponse.items || []).map((raw) => {
                    const group = raw as any;
                    const groupKey = effectiveGroupBy === "topic" ? String(group.topic_id || "") : String(group.product || "");
                    return {
                        group_key: groupKey,
                        group_name: effectiveGroupBy === "topic" ? String(group.topic_name || "") : String(group.product || ""),
                        prompt_count: Number(group.prompt_count || 0),
                        total_mentions: Number(group.total_mentions || 0),
                        brands: [],
                        _brand_total: 0,
                        _brand_offset: 0,
                    } as VisibilityRankingGroup;
                });
                return { items: groups, total: groupResponse.total };
              })
            : getVisibilityRankingGroups(
                dynamicQuery!.clientId,
                withMetricSortParams(
                    withMetricSortParams({ ...dynamicQuery!.params, group_by: effectiveGroupBy }, groupSort),
                    brandSort,
                    "brand_",
                ),
                { signal: controller.signal },
              );
        request
            .then((res) => {
                if (requestId !== groupRequestSeq.current || requestQueryKey !== currentGroupQueryKeyRef.current) return;
                setRemoteGroups(res.items || []);
                setRemoteGroupsLoadedKey(requestQueryKey);
                setGroupTotal(Number((res as any).total || (res.items || []).length));
                if (staticRemoteMode) {
                    (res.items || []).forEach((group) => void loadGroupBrandPage(group.group_key, 0));
                }
            })
            .catch((err) => {
                if (err?.name === "AbortError") return;
                if (staticRemoteMode) setMatrixError(true);
                if (requestId === groupRequestSeq.current && requestQueryKey === currentGroupQueryKeyRef.current) setRemoteGroups([]);
            })
            .finally(() => {
                if (requestId === groupRequestSeq.current && requestQueryKey === currentGroupQueryKeyRef.current) setGroupsLoading(false);
            });
        return () => controller.abort();
    }, [brandSort, effectiveGroupBy, groupOffset, groupSort, matrixGroupQueryKey, matrixRetryNonce, remoteGroupsVisible, remoteMode, staticRemoteMode, staticReportId]);

    if ((!data || data.length === 0) && !groupsLoading && !remoteMode) return null;

    const toggleRow = (id: string) => {
        setExpandedRows(prev => {
            const next = new Set(prev);
            if (next.has(id)) next.delete(id);
            else next.add(id);
            return next;
        });
        if ((remoteMode || (staticRemoteMode && !staticDefaultPromptsHydrated)) && !expandedRows.has(id) && !promptPages[id]) {
            void loadPromptPage(id, 0);
        }
        if (staticRemoteMode && (remoteMode || !staticDefaultBrandsHydrated) && !expandedRows.has(id)) {
            void loadGroupBrandPage(id, 0);
        }
    };

    const getRowKey = (item: any) => effectiveGroupBy === "topic" ? item.topic_id : item.product;
    const getRowLabel = (item: any) => effectiveGroupBy === "topic" ? item.topic_name : item.product;
    const getPromptRows = (rowKey: string, item: any) => promptPages[rowKey]?.queryKey === matrixPromptQueryKey
        ? promptPages[rowKey].items
        : (remoteMode || (staticRemoteMode && !staticDefaultPromptsHydrated) ? [] : (item.prompts || []));
    const getPromptTotal = (rowKey: string, item: any) => promptPages[rowKey]?.queryKey === matrixPromptQueryKey
        ? promptPages[rowKey].total
        : (remoteMode
            ? item.prompt_count ?? 0
            : staticFrozenLists?.[`visibility.${effectiveGroupBy}_prompt`]?.scopes?.find((scope) => scope.parent_key === rowKey && !scope.prompt_key)?.total ?? item.prompts?.length ?? 0);

    const loadPromptPage = async (rowKey: string, offset: number) => {
        if ((!remoteMode && !staticRemoteMode) || (!rankingMatrixQuery && !staticReportId)) return;
        promptRequestControllers.current[rowKey]?.abort();
        const controller = new AbortController();
        promptRequestControllers.current[rowKey] = controller;
        const requestQueryKey = matrixPromptQueryKey;
        const localGroup = localData.find((item: any) => getRowKey(item) === rowKey);
        const localPromptRows = localGroup?.prompts || [];
        const localPromptTotal = staticFrozenLists?.[`visibility.${effectiveGroupBy}_prompt`]?.scopes?.find((scope) => scope.parent_key === rowKey && !scope.prompt_key)?.total ?? localPromptRows.length;
        const requestId = (promptRequestSeq.current[rowKey] || 0) + 1;
        promptRequestSeq.current[rowKey] = requestId;
        setPromptPages((prev) => ({
            ...prev,
            [rowKey]: {
                items: prev[rowKey]?.queryKey === requestQueryKey ? prev[rowKey].items : localPromptRows,
                total: prev[rowKey]?.queryKey === requestQueryKey ? prev[rowKey].total : localPromptTotal,
                offset,
                loading: true,
                queryKey: requestQueryKey,
            },
        }));
        try {
            const res = staticRemoteMode && staticReportId
                ? await getStaticReportFrozenList(staticReportId, `visibility.${effectiveGroupBy}_prompt`, {
                    sort_by: promptSort.metricKey,
                    sort_order: promptSort.direction,
                    limit: PROMPT_PAGE_SIZE,
                    offset,
                    parent_key: rowKey,
                  }, { signal: controller.signal }).then((promptResponse) => ({
                    ...promptResponse,
                    items: (promptResponse.items || []).map((raw) => {
                        const prompt = raw as any;
                        return { ...prompt, brands: [], _brand_total: 0, _brand_offset: 0 };
                    }),
                  }))
                : await getVisibilityRankingPrompts(
                    rankingMatrixQuery!.clientId,
                    withMetricSortParams(withMetricSortParams({
                        ...rankingMatrixQuery!.params,
                        group_by: effectiveGroupBy,
                        group_key: rowKey,
                        limit: String(PROMPT_PAGE_SIZE),
                        offset: String(offset),
                    }, promptSort), brandSort, "brand_"),
                    { signal: controller.signal },
                  );
            if (!isVisibilityRankingRequestCurrent({
                capturedQueryKey: requestQueryKey,
                currentQueryKey: currentPromptQueryKeyRef.current,
                capturedRowSequence: requestId,
                currentRowSequence: promptRequestSeq.current[rowKey] || 0,
            })) return;
            setPromptPages((prev) => ({
                ...prev,
                [rowKey]: {
                    items: res.items || [],
                    total: res.total || 0,
                    offset: res.offset || offset,
                    loading: false,
                    queryKey: requestQueryKey,
                },
            }));
            if (staticRemoteMode) {
                (res.items || []).forEach((prompt) => void loadPromptBrandPage(rowKey, String(prompt.prompt_id || ""), 0));
            }
        } catch (error: any) {
            if (error?.name === "AbortError") return;
            if (staticRemoteMode) setMatrixError(true);
            if (!isVisibilityRankingRequestCurrent({
                capturedQueryKey: requestQueryKey,
                currentQueryKey: currentPromptQueryKeyRef.current,
                capturedRowSequence: requestId,
                currentRowSequence: promptRequestSeq.current[rowKey] || 0,
            })) return;
            setPromptPages((prev) => ({
                ...prev,
                [rowKey]: {
                    items: prev[rowKey]?.items || [],
                    total: prev[rowKey]?.total || 0,
                    offset,
                    loading: false,
                    queryKey: requestQueryKey,
                },
            }));
        } finally {
            if (promptRequestControllers.current[rowKey] === controller) {
                delete promptRequestControllers.current[rowKey];
            }
        }
    };

    const loadGroupBrandPage = async (rowKey: string, offset: number) => {
        if (!staticRemoteMode || !staticReportId) return;
        const capturedQueryKey = matrixGroupQueryKey;
        const listType = `visibility.${effectiveGroupBy}_brand`;
        const localGroup = localData.find((item: any) => getRowKey(item) === rowKey);
        const localBrandRows = localGroup?.brands || [];
        const localBrandTotal = staticFrozenLists?.[listType]?.scopes?.find((scope) => scope.parent_key === rowKey && !scope.prompt_key)?.total ?? localBrandRows.length;
        setGroupBrandPages((current) => ({
            ...current,
            [rowKey]: { items: current[rowKey]?.items || localBrandRows, total: current[rowKey]?.total || localBrandTotal, offset: current[rowKey]?.offset || 0, loading: true },
        }));
        try {
            const outcome = await groupBrandRequestManager.current.run({
                reportId: staticReportId,
                listType,
                parentKey: rowKey,
                promptKey: "",
                sortBy: brandSort.metricKey,
                sortOrder: brandSort.direction,
                offset,
            }, (signal) => getStaticReportFrozenList(staticReportId, listType, {
                sort_by: brandSort.metricKey, sort_order: brandSort.direction, limit: 20, offset, parent_key: rowKey,
            }, { signal }));
            if (!outcome.applied) return;
            const response = outcome.value;
            if (capturedQueryKey !== currentGroupQueryKeyRef.current) return;
            setGroupBrandPages((current) => ({
                ...current,
                [rowKey]: { items: response.items as any[], total: response.total, offset, loading: false },
            }));
        } catch {
            setMatrixError(true);
            setGroupBrandPages((current) => current[rowKey]
                ? { ...current, [rowKey]: { ...current[rowKey], loading: false } }
                : current);
        }
    };

    const loadPromptBrandPage = async (rowKey: string, promptKey: string, offset: number) => {
        if (!staticRemoteMode || !staticReportId) return;
        const capturedQueryKey = matrixPromptQueryKey;
        const listType = `visibility.${effectiveGroupBy}_prompt_brand`;
        const compositeKey = `${rowKey}:${promptKey}`;
        const localGroup = localData.find((item: any) => getRowKey(item) === rowKey);
        const localPrompt = localGroup?.prompts?.find((prompt: any) => String(prompt.prompt_id || "") === promptKey);
        const localBrandRows = localPrompt?.brands || [];
        const localBrandTotal = staticFrozenLists?.[listType]?.scopes?.find((scope) => scope.parent_key === rowKey && scope.prompt_key === promptKey)?.total ?? localBrandRows.length;
        setPromptBrandPages((current) => ({
            ...current,
            [compositeKey]: { items: current[compositeKey]?.items || localBrandRows, total: current[compositeKey]?.total || localBrandTotal, offset: current[compositeKey]?.offset || 0, loading: true },
        }));
        try {
            const outcome = await promptBrandRequestManager.current.run({
                reportId: staticReportId,
                listType,
                parentKey: rowKey,
                promptKey,
                sortBy: brandSort.metricKey,
                sortOrder: brandSort.direction,
                offset,
            }, (signal) => getStaticReportFrozenList(staticReportId, listType, {
                sort_by: brandSort.metricKey, sort_order: brandSort.direction, limit: 20, offset,
                parent_key: rowKey, prompt_key: promptKey,
            }, { signal }));
            if (!outcome.applied) return;
            const response = outcome.value;
            if (capturedQueryKey !== currentPromptQueryKeyRef.current) return;
            setPromptBrandPages((current) => ({
                ...current,
                [compositeKey]: { items: response.items as any[], total: response.total, offset, loading: false },
            }));
        } catch {
            setMatrixError(true);
            setPromptBrandPages((current) => current[compositeKey]
                ? { ...current, [compositeKey]: { ...current[compositeKey], loading: false } }
                : current);
        }
    };

    return (
        <section ref={sectionRef}>
            {matrixError && staticRemoteMode && (
                <div role="alert" className="mb-3 flex items-center justify-between gap-3 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm">
                    <span>{reportT("detail.listLoadError")}</span>
                    <Button type="button" variant="outline" size="sm" onClick={() => { groupBrandRequestManager.current.abortAll(); promptBrandRequestManager.current.abortAll(); setMatrixError(false); setPromptPages({}); setExpandedRows(new Set()); setMatrixRetryNonce((value) => value + 1); }}>{commonT("actions.retry")}</Button>
                </div>
            )}
            <div className="flex items-center justify-between mb-4">
                <div>
                    <h2 className="text-lg font-semibold flex items-center gap-2">
                        <Settings2 className="h-5 w-5 text-primary" />
                        {effectiveGroupBy === "topic" ? t("visibility.topicRanking.titleByTopic") : t("visibility.topicRanking.titleByProduct")}
                    </h2>
                    <p className="text-sm text-muted-foreground">
                        {effectiveGroupBy === "topic"
                            ? t("visibility.topicRanking.subtitleTopic")
                            : t("visibility.topicRanking.subtitleProduct")}
                    </p>
                </div>
                <div className="flex items-center gap-1 bg-muted rounded-lg p-0.5" data-export-hidden={exportMode ? "true" : undefined}>
                    <Button
                        variant={groupBy === "topic" ? "secondary" : "ghost"}
                        size="sm"
                        className="h-7 text-xs gap-1"
                        onClick={() => { setGroupBy("topic"); setGroupOffset(0); setExpandedRows(new Set()); }}
                    >
                        <Hash className="h-3 w-3" /> {t("visibility.topicRanking.byTopic")}
                    </Button>
                    <Button
                        variant={groupBy === "product" ? "secondary" : "ghost"}
                        size="sm"
                        className="h-7 text-xs gap-1"
                        onClick={() => { setGroupBy("product"); setGroupOffset(0); setExpandedRows(new Set()); }}
                    >
                        <Package className="h-3 w-3" /> {t("visibility.topicRanking.byProduct")}
                    </Button>
                </div>
            </div>
            <Card className="shadow-none">
                <CardContent className="p-0">
                    <div className="isolate rounded-md border overflow-x-auto">
                        <Table className="min-w-[1120px]">
                            <TableHeader>
                                <TableRow className="bg-muted/20">
                                    <TableHead className="relative min-w-[360px] bg-muted 2xl:sticky 2xl:left-0 2xl:z-40 2xl:shadow-[1px_0_0_hsl(var(--border)),8px_0_18px_hsl(var(--border)/0.25)]">
                                        {effectiveGroupBy === "topic" ? t("visibility.topicRanking.columnTopic") : t("visibility.topicRanking.columnProduct")}
                                    </TableHead>
                                    {Array.from({ length: 10 }, (_, index) => (
                                        <TableHead key={index + 1} className="min-w-[118px] text-center tabular-nums">
                                            {`#${index + 1}`}
                                        </TableHead>
                                    ))}
                                </TableRow>
                            </TableHeader>
                            <TableBody>
                                {(groupsLoading || (remoteMode && !remoteGroupsVisible)) && (
                                    <TableRow>
                                        <TableCell colSpan={11} className="h-24 text-center text-sm text-muted-foreground">
                                            <Loader2 className="mr-2 inline h-4 w-4 animate-spin" />
                                            {t("visibility.topicRanking.loading")}
                                        </TableCell>
                                    </TableRow>
                                )}
                                {data.map((item: any) => {
                                    const rowKey = getRowKey(item);
                                    const isExpanded = exportMode || expandedRows.has(rowKey);
                                    const promptTotal = getPromptTotal(rowKey, item);
                                    const promptRows = getPromptRows(rowKey, item);
                                    const promptPage = promptPages[rowKey]?.queryKey === matrixPromptQueryKey
                                        ? promptPages[rowKey]
                                        : undefined;
                                    const hasPrompts = remoteMode ? promptTotal > 0 : item.prompts && item.prompts.length > 0;
                                    const groupBrandPage = groupBrandPages[rowKey];
                                    const groupBrandRows = groupBrandPage?.items ?? (staticRemoteMode && !staticDefaultBrandsHydrated ? [] : item.brands ?? []);
                                    const rankedGroupBrands = toCanonicalBrandMetricRows(groupBrandRows)
                                        .sort((left, right) => (left.rank ?? Number.MAX_SAFE_INTEGER) - (right.rank ?? Number.MAX_SAFE_INTEGER))
                                        .slice(0, 10);
                                    return (
                                        <React.Fragment key={rowKey}>
                                            {/* Group row (Topic or Product) */}
                                            <TableRow
                                                className={`${hasPrompts ? "cursor-pointer hover:bg-muted/30" : ""} ${isExpanded ? "bg-muted/10" : ""}`}
                                                onClick={() => !exportMode && hasPrompts && toggleRow(rowKey)}
                                            >
                                                <TableCell className={`relative min-w-[360px] font-medium 2xl:sticky 2xl:left-0 2xl:z-40 2xl:shadow-[1px_0_0_hsl(var(--border)),8px_0_18px_hsl(var(--border)/0.25)] ${isExpanded ? "bg-muted" : "bg-background"}`}>
                                                    <div className="flex items-center gap-2">
                                                        {hasPrompts ? (
                                                            isExpanded
                                                                ? <ChevronDown className="h-4 w-4 text-muted-foreground flex-shrink-0" />
                                                                : <ChevronRight className="h-4 w-4 text-muted-foreground flex-shrink-0" />
                                                        ) : <span className="w-4" />}
                                                        <span className="block min-w-0 flex-1 truncate leading-snug" title={getRowLabel(item)}>
                                                            {getRowLabel(item)}
                                                        </span>
                                                        {hasPrompts && (
                                                            <span className="shrink-0 text-[10px] text-muted-foreground/60">
                                                                {t("visibility.topicRanking.promptsCount", { count: promptTotal })}
                                                            </span>
                                                        )}
                                                    </div>
                                                </TableCell>
                                                {Array.from({ length: 10 }, (_, index) => {
                                                    const brand = rankedGroupBrands[index];
                                                    return (
                                                        <TableCell key={index} className={`text-center text-xs ${brand?.isOwn ? "bg-emerald-500/10 font-semibold text-emerald-600" : "text-muted-foreground"}`}>
                                                            <BrandRankCellContent brand={brand} />
                                                        </TableCell>
                                                    );
                                                })}
                                            </TableRow>
                                            {/* Expanded prompt rows */}
                                            {isExpanded && promptPage?.loading && (
                                                <TableRow className="bg-muted/5 border-l-2 border-l-primary/20">
                                                    <TableCell colSpan={11} className="h-16 text-center text-sm text-muted-foreground">
                                                        <Loader2 className="mr-2 inline h-4 w-4 animate-spin" />
                                                        {t("visibility.topicRanking.loadingPrompts")}
                                                    </TableCell>
                                                </TableRow>
                                            )}
                                            {isExpanded && promptRows.map((prompt: any) => {
                                                const promptKey = String(prompt.prompt_id || "");
                                                const compositeKey = `${rowKey}:${promptKey}`;
                                                const promptBrandPage = promptBrandPages[compositeKey];
                                                const promptBrandRows = promptBrandPage?.items ?? (staticRemoteMode && !staticDefaultBrandsHydrated ? [] : prompt.brands ?? []);
                                                const rankedPromptBrands = toCanonicalBrandMetricRows(promptBrandRows)
                                                    .sort((left, right) => (left.rank ?? Number.MAX_SAFE_INTEGER) - (right.rank ?? Number.MAX_SAFE_INTEGER))
                                                    .slice(0, 10);
                                                return <React.Fragment key={prompt.prompt_id || prompt.prompt_key || prompt.prompt_text}>
                                                <TableRow className="bg-muted/5 border-l-2 border-l-primary/20">
                                                    <TableCell className="relative min-w-[360px] bg-card pl-10 2xl:sticky 2xl:left-0 2xl:z-40 2xl:shadow-[1px_0_0_hsl(var(--border)),8px_0_18px_hsl(var(--border)/0.25)]">
                                                        <div className="flex items-center gap-2">
                                                            <span className="block min-w-0 flex-1 truncate text-xs leading-relaxed text-muted-foreground" title={prompt.prompt_text}>
                                                                {prompt.prompt_text}
                                                            </span>
                                                            <button
                                                                type="button"
                                                                onClick={(event) => {
                                                                    event.stopPropagation();
                                                                    setFullPrompt(prompt.prompt_text || "");
                                                                }}
                                                                className="shrink-0 rounded border border-border/50 px-1.5 py-0.5 text-[10px] text-muted-foreground transition-colors hover:border-primary/40 hover:text-foreground"
                                                                title={prompt.prompt_text}
                                                            >
                                                                {t("visibility.topicRanking.viewFullPrompt")}
                                                            </button>
                                                        </div>
                                                    </TableCell>
                                                    {Array.from({ length: 10 }, (_, index) => {
                                                        const brand = rankedPromptBrands[index];
                                                        return (
                                                            <TableCell key={index} className={`text-center text-xs ${brand?.isOwn ? "bg-emerald-500/10 font-semibold text-emerald-600" : "text-muted-foreground"}`}>
                                                                <BrandRankCellContent brand={brand} />
                                                            </TableCell>
                                                        );
                                                    })}
                                                </TableRow>
                                                </React.Fragment>;
                                            })}
                                            {isExpanded && (remoteMode || staticRemoteMode) && promptTotal > PROMPT_PAGE_SIZE && (
                                                <TableRow className="bg-muted/5 border-l-2 border-l-primary/20">
                                                    <TableCell colSpan={11}>
                                                        <div className="flex items-center justify-end gap-2 px-4 py-2 text-xs text-muted-foreground">
                                                            <span>
                                                                {t("visibility.topicRanking.promptPageRange", {
                                                                    start: (promptPage?.offset || 0) + 1,
                                                                    end: Math.min((promptPage?.offset || 0) + PROMPT_PAGE_SIZE, promptTotal),
                                                                    total: promptTotal,
                                                                })}
                                                            </span>
                                                            <Button
                                                                variant="outline"
                                                                size="sm"
                                                                className="h-7 text-xs"
                                                                disabled={(promptPage?.offset || 0) === 0 || promptPage?.loading}
                                                                onClick={() => void loadPromptPage(rowKey, Math.max(0, (promptPage?.offset || 0) - PROMPT_PAGE_SIZE))}
                                                            >
                                                                {t("visibility.topicRanking.previous")}
                                                            </Button>
                                                            <Button
                                                                variant="outline"
                                                                size="sm"
                                                                className="h-7 text-xs"
                                                                disabled={(promptPage?.offset || 0) + PROMPT_PAGE_SIZE >= promptTotal || promptPage?.loading}
                                                                onClick={() => void loadPromptPage(rowKey, (promptPage?.offset || 0) + PROMPT_PAGE_SIZE)}
                                                            >
                                                                {t("visibility.topicRanking.next")}
                                                            </Button>
                                                        </div>
                                                    </TableCell>
                                                </TableRow>
                                            )}
                                        </React.Fragment>
                                    );
                                })}
                            </TableBody>
                        </Table>
                    </div>
                </CardContent>
            </Card>
            {staticRemoteMode && effectiveGroupTotal > 20 && (
                <div className="mt-3 flex items-center justify-end gap-2 text-xs text-muted-foreground">
                    <span>{groupOffset + 1}–{Math.min(groupOffset + 20, effectiveGroupTotal)} / {effectiveGroupTotal}</span>
                    <Button variant="outline" size="sm" disabled={groupOffset === 0 || groupsLoading} onClick={() => setGroupOffset((value) => Math.max(0, value - 20))}>{t("visibility.topicRanking.previous")}</Button>
                    <Button variant="outline" size="sm" disabled={groupOffset + 20 >= effectiveGroupTotal || groupsLoading} onClick={() => setGroupOffset((value) => value + 20)}>{t("visibility.topicRanking.next")}</Button>
                </div>
            )}
            <Dialog open={!!fullPrompt} onOpenChange={(open) => !open && setFullPrompt(null)}>
                <DialogContent className="max-w-2xl">
                    <DialogHeader>
                        <DialogTitle>{t("visibility.topicRanking.fullPromptTitle")}</DialogTitle>
                        <DialogDescription>{t("visibility.topicRanking.fullPromptDescription")}</DialogDescription>
                    </DialogHeader>
                    <div className="rounded-md border bg-muted/20 p-3 text-sm leading-relaxed text-foreground whitespace-pre-wrap break-words">
                        {fullPrompt}
                    </div>
                </DialogContent>
            </Dialog>
        </section>
    );
}

function EmptyState({ message }: { message: string }) {
    return (
        <div className="flex flex-col items-center justify-center h-48 text-muted-foreground rounded-lg border border-dashed border-primary/20 bg-primary/[0.02]">
            <div className="h-12 w-12 rounded-full bg-primary/[0.06] border border-primary/10 mb-4 flex items-center justify-center">
                <BarChart3 className="h-5 w-5 text-primary/40" />
            </div>
            <p className="text-sm">{message}</p>
        </div>
    );
}
