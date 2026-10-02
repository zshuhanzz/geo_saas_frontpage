import { useEffect, useMemo, useRef, useState, useCallback } from "react";
import { useTranslation } from "react-i18next";
import type { components } from "@/api/openapi";
import { getSentiment, getSentimentThemes, getSentimentThemeResults, getSentimentResultDetail } from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import {
    Sheet, SheetContent, SheetHeader, SheetTitle, SheetDescription
} from "@/components/ui/sheet";
import {
    BarChart as RechartsBarChart, Bar, LineChart, Line, XAxis, YAxis, Tooltip as RechartsTooltip, ResponsiveContainer
} from "recharts";
import {
    SmilePlus, Frown, TrendingUp, TrendingDown, ChevronDown, ChevronUp,
    MessageSquareText, ExternalLink, Loader2, LayoutGrid, Activity, Scale
} from "lucide-react";
import { Switch } from "@/components/ui/switch";
import { Label } from "@/components/ui/label";
import { GlassTooltip } from "@/components/ui/chart-tooltip";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { selectDashboardFilterKey } from "@/pages/insights/promptDrilldownTarget";
import { SortableMetricHeader } from "@/components/ui/SortableMetricHeader";
import { resetVisibleCountForCriteriaChange, type MetricSortState, withMetricSortParams } from "@/lib/metricSort";

type Schemas = components["schemas"];
type SentimentData = Schemas["SentimentOut"];
type SentimentTheme = Schemas["ThemeRow"];
type SentimentThemeResult = Schemas["ThemeResultRow"];
type SentimentResultDetail = Schemas["ResultDetailOut"];
type SentimentTimePoint = Schemas["TimeSeriesPoint"] & { prev_positive_pct?: number | null };

const EMPTY_SENTIMENT_SUMMARY: Schemas["SentimentSummary"] = {
    positive_pct: 0,
    mixed_neutral_pct: 0,
    negative_pct: 0,
    positive_pct_change: 0,
    positive_count: 0,
    mixed_neutral_count: 0,
    negative_count: 0,
    insufficient_evidence_count: 0,
    rated_count: 0,
    total_count: 0,
    positive_top3_themes: [],
    negative_top3_themes: [],
};

// ─────────────────────────────────────────────────────────────────────────────
// Helpers
// ─────────────────────────────────────────────────────────────────────────────

function fmtDate(v: unknown) {
    const s = String(v);
    const d = s.includes("T") ? new Date(s) : new Date(s + "T00:00:00");
    return `${d.getMonth() + 1}/${d.getDate()}`;
}

function fmtPercentValue(val: unknown) {
    if (val == null || Number.isNaN(Number(val))) return "—";
    return `${Number(val).toFixed(2)}%`;
}

function isAbortError(error: unknown): boolean {
    return error instanceof Error && error.name === "AbortError";
}

function formatSearchQuery(value: unknown): string {
    if (typeof value === "string") return value;
    if (typeof value === "object" && value !== null && "query" in value) {
        return String(value.query ?? "");
    }
    try {
        return JSON.stringify(value) ?? String(value);
    } catch {
        return String(value);
    }
}

function resolveSearchQueriesStatus(detail: SentimentResultDetail) {
    if (detail.search_queries_status) return detail.search_queries_status;
    if ((detail.platform || "").toLowerCase() !== "chatgpt") return "not_applicable";
    return Array.isArray(detail.search_queries) && detail.search_queries.length > 0
        ? "available"
        : "upstream_not_provided";
}

function SentimentBadge({ sentiment }: { sentiment?: string | null }) {
    const { t } = useTranslation("insights");
    const isPos = sentiment === "Positive";
    const isMixed = sentiment === "Mixed/Neutral";
    const colorClass = isPos
        ? "bg-emerald-500/15 text-emerald-500"
        : isMixed
            ? "bg-amber-500/15 text-amber-600"
            : "bg-red-500/15 text-red-400";
    return (
        <span className={`inline-flex items-center gap-0.5 px-2 py-0.5 rounded-full text-xs font-medium ${colorClass}`}>
            {isPos ? <SmilePlus className="h-3 w-3" /> : isMixed ? <Scale className="h-3 w-3" /> : <Frown className="h-3 w-3" />}
            {isPos ? t("sentiment.filterPositive") : isMixed ? t("sentiment.filterMixedNeutral") : t("sentiment.filterNegative")}
        </span>
    );
}

function EmptyState({ message }: { message: string }) {
    return (
        <div className="flex flex-col items-center justify-center h-48 text-muted-foreground gap-3">
            <div className="h-12 w-12 rounded-full bg-muted/50 flex items-center justify-center">
                <LayoutGrid className="h-5 w-5 text-muted-foreground/40" />
            </div>
            <p className="text-sm">{message}</p>
        </div>
    );
}

// ─────────────────────────────────────────────────────────────────────────────
// Result Detail Drawer
// ─────────────────────────────────────────────────────────────────────────────

function ResultDetailDrawer({
    clientId,
    resultId,
    open,
    onClose,
    targetParams,
}: {
    clientId: string;
    resultId: number | null;
    open: boolean;
    onClose: () => void;
    targetParams: Record<string, string>;
}) {
    const { t } = useTranslation("insights");
    const [detail, setDetail] = useState<SentimentResultDetail | null>(null);
    const [loading, setLoading] = useState(false);
    const requestSeq = useRef(0);
    const searchQueriesStatus = detail ? resolveSearchQueriesStatus(detail) : "not_applicable";

    useEffect(() => {
        if (!open || !resultId || !clientId) return;
        const controller = new AbortController();
        const requestId = ++requestSeq.current;
        const timer = window.setTimeout(() => {
            setLoading(true);
            setDetail(null);
            getSentimentResultDetail(clientId, resultId, targetParams, { signal: controller.signal })
                .then((result) => { if (requestId === requestSeq.current) setDetail(result); })
                .catch((error: unknown) => {
                    if (!isAbortError(error) && requestId === requestSeq.current) setDetail(null);
                })
                .finally(() => { if (requestId === requestSeq.current) setLoading(false); });
        }, 0);
        return () => {
            window.clearTimeout(timer);
            controller.abort();
        };
    }, [open, resultId, clientId, targetParams]);

    return (
        <Sheet open={open} onOpenChange={o => { if (!o) onClose(); }}>
            <SheetContent className="w-full sm:max-w-[50vw] sm:w-[50vw] overflow-y-auto">
                <SheetHeader className="mb-4">
                    <SheetTitle className="flex items-center gap-2">
                        <MessageSquareText className="h-5 w-5 text-primary" />
                        {t("sentiment.responseSheetTitle")}
                    </SheetTitle>
                    <SheetDescription>{t("sentiment.responseSheetDesc")}</SheetDescription>
                </SheetHeader>

                {loading && (
                    <div className="flex items-center justify-center py-24">
                        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                    </div>
                )}

                {!loading && !detail && (
                    <EmptyState message={t("sentiment.responseLoadFailed")} />
                )}

                {!loading && detail && (
                    <div className="space-y-6 pb-8">
                        {/* Metadata row */}
                        <div className="flex flex-wrap gap-2 text-sm">
                            <Badge variant="outline">{detail.platform}</Badge>
                            <Badge variant="outline">{detail.country}</Badge>
                            {detail.language && <Badge variant="outline">{detail.language}</Badge>}
                            {detail.executed_at && (
                                <Badge variant="outline" className="text-muted-foreground">
                                    {new Date(detail.executed_at).toLocaleDateString()}
                                </Badge>
                            )}
                        </div>

                        {/* Query / Prompt */}
                        <div>
                            <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1.5">{t("sentiment.queryLabel")}</div>
                            <div className="bg-muted/40 rounded-lg px-4 py-3 text-sm leading-relaxed">
                                {detail.client_prompt || detail.final_prompt || "—"}
                            </div>
                        </div>

                        {/* Search queries */}
                        {searchQueriesStatus !== "not_applicable" && (
                            <div>
                                <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">{t("sentiment.searchQueriesLabel")}</div>
                                {searchQueriesStatus === "available" && Array.isArray(detail.search_queries) && (
                                    <div className="flex flex-wrap gap-2">
                                        {detail.search_queries.map((q: unknown, i: number) => (
                                            <span key={i} className="bg-muted rounded-md px-2 py-0.5 text-xs">
                                                {formatSearchQuery(q)}
                                            </span>
                                        ))}
                                    </div>
                                )}
                                {searchQueriesStatus === "upstream_not_provided" && (
                                    <p className="text-sm text-muted-foreground">
                                        {t("sentiment.searchQueriesUpstreamUnavailable")}
                                    </p>
                                )}
                                {searchQueriesStatus === "not_requested" && (
                                    <p className="text-sm text-muted-foreground">
                                        {t("sentiment.searchQueriesNotRequested")}
                                    </p>
                                )}
                            </div>
                        )}

                        {/* Response text */}
                        <div>
                            <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-1.5">{t("sentiment.aiResponseLabel")}</div>
                            <div className="bg-muted/20 border rounded-lg px-4 py-3 text-sm leading-relaxed whitespace-pre-wrap max-h-96 overflow-y-auto">
                                {detail.response_text || t("sentiment.noResponseText")}
                            </div>
                        </div>

                        {/* Citations */}
                        {detail.citations && detail.citations.length > 0 && (
                            <div>
                                <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">
                                    {t("sentiment.citationsLabel", { count: detail.citations.length })}
                                </div>
                                <div className="space-y-2">
                                    {detail.citations.map((c, i) => (
                                        <div key={i} className="flex items-start gap-3 bg-muted/20 rounded-lg px-3 py-2.5 border">
                                            <img
                                                src={`https://www.google.com/s2/favicons?domain=${c.source_domain}&sz=16`}
                                                alt="" className="w-4 h-4 mt-0.5 flex-shrink-0 rounded-sm"
                                                onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
                                            />
                                            <div className="min-w-0 flex-1">
                                                <div className="text-xs font-medium text-foreground truncate">
                                                    {c.source_label || c.source_domain || c.source_url}
                                                </div>
                                                <div className="text-[11px] text-muted-foreground truncate">{c.source_url}</div>
                                            </div>
                                            {c.source_url && (
                                                <a href={c.source_url} target="_blank" rel="noopener noreferrer" className="flex-shrink-0 text-muted-foreground hover:text-primary">
                                                    <ExternalLink className="h-3.5 w-3.5" />
                                                </a>
                                            )}
                                            {c.domain_category && (
                                                <Badge variant="outline" className="text-[10px] flex-shrink-0">{c.domain_category}</Badge>
                                            )}
                                        </div>
                                    ))}
                                </div>
                            </div>
                        )}
                    </div>
                )}
            </SheetContent>
        </Sheet>
    );
}

// ─────────────────────────────────────────────────────────────────────────────
// Theme Carousel Pager
// ─────────────────────────────────────────────────────────────────────────────

// ─────────────────────────────────────────────────────────────────────────────
// Theme Row with expandable results
// ─────────────────────────────────────────────────────────────────────────────

function ThemeRow({
    theme,
    clientId,
    dateFrom,
    dateTo,
    selectedTopics,
    selectedPlatforms,
    selectedCountries,
    selectedPromptTypes,
    products,
    promptIds,
    sentimentFilter,
    onOpenResult,
}: {
    theme: SentimentTheme;
    clientId: string;
    dateFrom: string;
    dateTo: string;
    selectedTopics: string[];
    selectedPlatforms: string[];
    selectedCountries: string[];
    selectedPromptTypes: string[];
    products?: string[];
    promptIds?: string[];
    sentimentFilter: string;
    onOpenResult: (resultId: number) => void;
}) {
    const { t } = useTranslation("insights");
    const [expanded, setExpanded] = useState(false);
    const [results, setResults] = useState<SentimentThemeResult[]>([]);
    const [total, setTotal] = useState(0);
    const [page, setPage] = useState(1);
    const [loadingResults, setLoadingResults] = useState(false);
    const requestSeq = useRef(0);
    const requestController = useRef<AbortController | null>(null);

    useEffect(() => () => requestController.current?.abort(), []);

    const loadResults = useCallback(async (p = 1) => {
        requestController.current?.abort();
        const controller = new AbortController();
        requestController.current = controller;
        const requestId = ++requestSeq.current;
        setLoadingResults(true);
        try {
            const res = await getSentimentThemeResults(clientId, theme.theme_name, {
                date_from: dateFrom,
                date_to: dateTo,
                page: p,
                page_size: 5,
                ...(selectedTopics.length > 0 ? { topic_ids: selectedTopics.join(",") } : {}),
                ...(selectedPlatforms.length > 0 ? { platform: selectedPlatforms.join(",") } : {}),
                ...(selectedCountries.length > 0 ? { country: selectedCountries.join(",") } : {}),
                ...(selectedPromptTypes.length > 0 ? { prompt_type: selectedPromptTypes.join(",") } : {}),
                ...(products && products.length > 0 ? { products: products.join(",") } : {}),
                ...(promptIds && promptIds.length > 0 ? { prompt_ids: promptIds.join(",") } : {}),
                ...(sentimentFilter ? { sentiment_filter: sentimentFilter } : {}),
            }, { signal: controller.signal });
            if (requestId === requestSeq.current) {
                setResults((prev) => p === 1 ? res.results : [...prev, ...res.results]);
                setTotal(res.total);
                setPage(p);
            }
        } catch (error: unknown) {
            if (!isAbortError(error) && requestId === requestSeq.current && p === 1) {
                setResults([]);
                setTotal(0);
            }
        } finally {
            if (requestId === requestSeq.current) setLoadingResults(false);
        }
    }, [clientId, theme.theme_name, dateFrom, dateTo, selectedTopics, selectedPlatforms, selectedCountries, selectedPromptTypes, products, promptIds, sentimentFilter]);

    function handleExpand() {
        setExpanded(e => {
            if (!e && results.length === 0) loadResults(1);
            return !e;
        });
    }

    const changePos = theme.occurrence_change > 0;

    return (
        <div className="border-b border-border last:border-0">
            {/* Theme header row */}
            <div
                className="flex items-center gap-4 px-4 py-3 hover:bg-muted/20 cursor-pointer transition-colors"
                onClick={handleExpand}
            >
                <div className="flex-1 min-w-0">
                    <div className="font-medium text-sm">{theme.theme_name}</div>
                </div>
                <SentimentBadge sentiment={theme.sentiment} />
                <div className="text-sm text-right w-28 font-medium">{theme.occurrence_count}</div>
                <div className={`text-xs text-right w-24 ${changePos ? "text-emerald-500" : theme.occurrence_change < 0 ? "text-red-400" : "text-muted-foreground"}`}>
                    {theme.occurrence_change > 0 ? "+" : ""}{theme.occurrence_change}
                </div>
                <div className="w-6 flex-shrink-0 flex justify-center">
                    {expanded ? <ChevronUp className="h-4 w-4 text-muted-foreground" /> : <ChevronDown className="h-4 w-4 text-muted-foreground" />}
                </div>
            </div>

            {/* Expandable sub-results */}
            {expanded && (
                <div className="bg-muted/10 border-t border-border/50 py-4">
                    {loadingResults && results.length === 0 && (
                        <div className="flex items-center justify-center py-6">
                            <Loader2 className="h-4 w-4 animate-spin text-muted-foreground" />
                        </div>
                    )}
                    {results.length > 0 && (
                        <div className="px-6 flex flex-col gap-4">
                            {/* Render strictly ONE item based on `page` index */}
                            {results[page - 1] && (() => {
                                const r = results[page - 1];
                                return (
                                    <div className="bg-background rounded-lg border border-border/50 p-5 shadow-sm">
                                        <div className="flex items-start justify-between gap-4">
                                            <div className="flex-1 min-w-0">
                                                <div className="text-xs text-muted-foreground mb-3 flex items-center gap-2">
                                                    <Badge variant="outline" className="text-[10px]">{r.platform}</Badge>
                                                    <Badge variant="outline" className="text-[10px]">{r.country}</Badge>
                                                    {r.executed_at && (
                                                        <span>{new Date(r.executed_at).toLocaleDateString()}</span>
                                                    )}
                                                </div>
                                                <div className="text-sm font-medium leading-relaxed">{r.prompt_text || "—"}</div>
                                                {r.excerpt && (
                                                    <div className="mt-3 text-sm text-foreground italic leading-relaxed whitespace-pre-wrap pl-3 border-l-2 border-primary/40">
                                                        "{r.excerpt}"
                                                    </div>
                                                )}
                                            </div>
                                            <Button
                                                variant="outline"
                                                size="sm"
                                                className="flex-shrink-0 text-xs shrink-0"
                                                onClick={(e) => { e.stopPropagation(); onOpenResult(r.result_id); }}
                                            >
                                                View Response
                                            </Button>
                                        </div>
                                    </div>
                                );
                            })()}

                            {/* Carousel Controls */}
                            {total > 1 && (
                                <div className="flex items-center justify-center gap-4 mt-2 mb-2">
                                    <Button
                                        variant="outline" size="sm" className="h-8 w-8 p-0 shrink-0"
                                        disabled={page === 1 || loadingResults}
                                        onClick={(e) => { e.stopPropagation(); setPage(p => Math.max(1, p - 1)); }}
                                    >
                                        &larr;
                                    </Button>
                                    <div className="text-xs font-medium w-12 text-center text-muted-foreground">
                                        {page} / {total}
                                    </div>
                                    <Button
                                        variant="outline" size="sm" className="h-8 w-8 p-0 shrink-0"
                                        disabled={page >= total || loadingResults}
                                        onClick={(e) => {
                                            e.stopPropagation();
                                            const nxt = page + 1;
                                            if (nxt > results.length) {
                                                loadResults(nxt); // Load dynamically if not cached
                                            } else {
                                                setPage(nxt);
                                            }
                                        }}
                                    >
                                        {loadingResults ? <Loader2 className="h-3 w-3 animate-spin" /> : <>&rarr;</>}
                                    </Button>
                                </div>
                            )}
                        </div>
                    )}
                    {results.length === 0 && !loadingResults && (
                        <div className="px-6 py-4 text-center text-xs text-muted-foreground">{t("sentiment.noThemeResults")}</div>
                    )}
                </div>
            )}
        </div>
    );
}

// ─────────────────────────────────────────────────────────────────────────────
// Main Sentiment Page
// ─────────────────────────────────────────────────────────────────────────────

export interface SentimentDashboardFilters {
    dateFrom: string;
    dateTo: string;
    interval: string;
    topicIds: string[];
    platforms: string[];
    countries: string[];
    promptTypes: string[];
    products?: string[];
    promptIds?: string[];
}

export interface SentimentDashboardProps {
    clientId: string;
    filters: SentimentDashboardFilters;
    filtersReady?: boolean;
    mode?: "sidebar" | "drilldown";
}

export default function SentimentDashboard({
    clientId,
    filters,
    filtersReady = true,
    mode = "sidebar",
}: SentimentDashboardProps) {
    const { t } = useTranslation(["insights", "common"]);
    const {
        dateFrom,
        dateTo,
        interval,
        topicIds: selectedTopics,
        platforms: selectedPlatforms,
        countries: selectedCountries,
        promptTypes: selectedPromptTypes,
        products,
        promptIds,
    } = filters;

    const [data, setData] = useState<SentimentData | null>(null);
    const [loading, setLoading] = useState(true);
    const [loadError, setLoadError] = useState(false);
    const [settledFilterKey, setSettledFilterKey] = useState("");
    const [retryVersion, setRetryVersion] = useState(0);
    const [sentimentFilter, setSentimentFilter] = useState<string>("");
    const [themeSort, setThemeSort] = useState<MetricSortState>({ metricKey: "occurrence_count", direction: "desc" });
    const [themeData, setThemeData] = useState<SentimentTheme[] | null>(null);
    const [themeLoading, setThemeLoading] = useState(false);
    const [themeLoadError, setThemeLoadError] = useState(false);
    const [themeSettledKey, setThemeSettledKey] = useState("");
    const [themeRetryVersion, setThemeRetryVersion] = useState(0);
    const themeCriteriaKey = useMemo(() => JSON.stringify({
        clientId,
        dateFrom,
        dateTo,
        interval,
        selectedTopics,
        selectedPlatforms,
        selectedCountries,
        selectedPromptTypes,
        products,
        promptIds,
        sentimentFilter,
    }), [clientId, dateFrom, dateTo, interval, selectedTopics, selectedPlatforms, selectedCountries, selectedPromptTypes, products, promptIds, sentimentFilter]);
    const [themePagination, setThemePagination] = useState({ criteriaKey: themeCriteriaKey, count: 10 });
    const themesVisible = resetVisibleCountForCriteriaChange(
        themePagination.count,
        themePagination.criteriaKey,
        themeCriteriaKey,
        10,
    );
    const setThemesVisible = (next: number | ((current: number) => number)) => {
        setThemePagination((current) => {
            const currentVisible = resetVisibleCountForCriteriaChange(
                current.count,
                current.criteriaKey,
                themeCriteriaKey,
                10,
            );
            return {
                criteriaKey: themeCriteriaKey,
                count: typeof next === "function" ? next(currentVisible) : next,
            };
        });
    };

    // Chart toggle state
    const [chartMode, setChartMode] = useState<"line" | "bar">("line");
    const [comparePrev, setComparePrev] = useState(false);

    // Drawer state
    const [drawerResultId, setDrawerResultId] = useState<number | null>(null);
    const [drawerOpen, setDrawerOpen] = useState(false);
    const sentimentRequestSeq = useRef(0);
    const themeRequestSeq = useRef(0);

    function openResult(resultId: number) {
        setDrawerResultId(resultId);
        setDrawerOpen(true);
    }

    const filterKey = useMemo(() => JSON.stringify({
        clientId,
        dateFrom,
        dateTo,
        interval,
        selectedTopics,
        selectedPlatforms,
        selectedCountries,
        selectedPromptTypes,
        products,
        promptIds,
    }), [clientId, dateFrom, dateTo, interval, selectedTopics, selectedPlatforms, selectedCountries, selectedPromptTypes, products, promptIds]);
    const debouncedFilterKey = useDebouncedValue(filterKey, 200);
    const debouncedClientId = useMemo(() => String(JSON.parse(debouncedFilterKey).clientId || ""), [debouncedFilterKey]);
    const effectiveFilterKey = selectDashboardFilterKey(mode, filterKey, debouncedFilterKey, debouncedClientId !== clientId);
    const currentFilterKeyRef = useRef(effectiveFilterKey);
    useEffect(() => {
        currentFilterKeyRef.current = effectiveFilterKey;
    }, [effectiveFilterKey]);
    const debouncedFilters = useMemo(() => JSON.parse(effectiveFilterKey) as {
        clientId: string;
        dateFrom: string;
        dateTo: string;
        interval: string;
        selectedTopics: string[];
        selectedPlatforms: string[];
        selectedCountries: string[];
        selectedPromptTypes: string[];
        products?: string[];
        promptIds?: string[];
    }, [effectiveFilterKey]);
    const defaultThemeCriteria = sentimentFilter === ""
        && themeSort.metricKey === "occurrence_count"
        && themeSort.direction === "desc";
    const themeQueryKey = useMemo(
        () => JSON.stringify([effectiveFilterKey, sentimentFilter, themeSort]),
        [effectiveFilterKey, sentimentFilter, themeSort],
    );

    useEffect(() => {
        if (!clientId || !filtersReady) return;
        const controller = new AbortController();
        const requestId = ++sentimentRequestSeq.current;
        const requestFilterKey = effectiveFilterKey;
        const isCurrent = () => requestId === sentimentRequestSeq.current
            && requestFilterKey === currentFilterKeyRef.current;
        const params: Record<string, string> = {
            date_from: debouncedFilters.dateFrom,
            date_to: debouncedFilters.dateTo,
            interval: debouncedFilters.interval,
        };
        if (debouncedFilters.selectedTopics.length > 0) params.topic_ids = debouncedFilters.selectedTopics.join(",");
        if (debouncedFilters.selectedPlatforms.length > 0) params.platform = debouncedFilters.selectedPlatforms.join(",");
        if (debouncedFilters.selectedCountries.length > 0) params.country = debouncedFilters.selectedCountries.join(",");
        if (debouncedFilters.selectedPromptTypes.length > 0) params.prompt_type = debouncedFilters.selectedPromptTypes.join(",");
        if (debouncedFilters.products && debouncedFilters.products.length > 0) params.products = debouncedFilters.products.join(",");
        if (debouncedFilters.promptIds && debouncedFilters.promptIds.length > 0) params.prompt_ids = debouncedFilters.promptIds.join(",");
        const timer = window.setTimeout(() => {
            setLoading(true);
            setLoadError(false);
            setData(null);
            getSentiment(clientId, params, { signal: controller.signal })
                .then(res => {
                    if (isCurrent()) {
                        setData(res);
                        setSettledFilterKey(requestFilterKey);
                    }
                })
                .catch((error: unknown) => {
                    if (isAbortError(error)) return;
                    if (isCurrent()) {
                        setData(null);
                        setLoadError(true);
                        setSettledFilterKey(requestFilterKey);
                    }
                })
                .finally(() => {
                    if (isCurrent()) setLoading(false);
                });
        }, 0);
        return () => {
            window.clearTimeout(timer);
            controller.abort();
        };
    }, [clientId, filtersReady, debouncedFilters, effectiveFilterKey, retryVersion]);

    useEffect(() => {
        if (!clientId || !filtersReady || defaultThemeCriteria) {
            themeRequestSeq.current += 1;
            return;
        }
        const controller = new AbortController();
        const requestId = ++themeRequestSeq.current;
        const params: Record<string, string> = {
            date_from: debouncedFilters.dateFrom,
            date_to: debouncedFilters.dateTo,
        };
        if (sentimentFilter) params.sentiment_filter = sentimentFilter;
        if (debouncedFilters.selectedTopics.length > 0) params.topic_ids = debouncedFilters.selectedTopics.join(",");
        if (debouncedFilters.selectedPlatforms.length > 0) params.platform = debouncedFilters.selectedPlatforms.join(",");
        if (debouncedFilters.selectedCountries.length > 0) params.country = debouncedFilters.selectedCountries.join(",");
        if (debouncedFilters.products && debouncedFilters.products.length > 0) params.products = debouncedFilters.products.join(",");
        if (debouncedFilters.promptIds && debouncedFilters.promptIds.length > 0) params.prompt_ids = debouncedFilters.promptIds.join(",");
        const timer = window.setTimeout(() => {
            setThemeLoading(true);
            setThemeLoadError(false);
            getSentimentThemes(clientId, withMetricSortParams(params, themeSort), { signal: controller.signal })
                .then((response) => {
                    if (requestId !== themeRequestSeq.current) return;
                    setThemeData(response.themes);
                    setThemeSettledKey(themeQueryKey);
                })
                .catch((error: unknown) => {
                    if (isAbortError(error) || requestId !== themeRequestSeq.current) return;
                    setThemeLoadError(true);
                    setThemeSettledKey(themeQueryKey);
                })
                .finally(() => {
                    if (requestId === themeRequestSeq.current) setThemeLoading(false);
                });
        }, 0);
        return () => { window.clearTimeout(timer); controller.abort(); };
    }, [clientId, defaultThemeCriteria, filtersReady, debouncedFilters, sentimentFilter, themeQueryKey, themeRetryVersion, themeSort]);

    const currentData = settledFilterKey === effectiveFilterKey && !loadError ? data : null;
    const requestPending = loading || settledFilterKey !== effectiveFilterKey;
    const requestFailed = settledFilterKey === effectiveFilterKey && loadError;
    const summary = currentData?.summary || EMPTY_SENTIMENT_SUMMARY;
    const timeSeries = currentData?.time_series || [];
    const prevTimeSeries = currentData?.prev_time_series || [];
    const themes: SentimentTheme[] = defaultThemeCriteria
        ? currentData?.themes || []
        : themeSettledKey === themeQueryKey && !themeLoadError
            ? themeData || []
            : themeData || [];
    const themeListPending = !defaultThemeCriteria && (themeLoading || themeSettledKey !== themeQueryKey);
    const currentThemeLoadError = !defaultThemeCriteria && themeSettledKey === themeQueryKey && themeLoadError;

    // Merge prev into time series for chart overlay
    const chartData: SentimentTimePoint[] = timeSeries.map((pt, i) => ({
        ...pt,
        prev_positive_pct: prevTimeSeries[i]?.positive_pct ?? null,
    }));
    const detailTargetParams = useMemo(() => ({
        date_from: debouncedFilters.dateFrom,
        date_to: debouncedFilters.dateTo,
        ...(debouncedFilters.selectedTopics.length > 0 ? { topic_ids: debouncedFilters.selectedTopics.join(",") } : {}),
        ...(debouncedFilters.selectedPlatforms.length > 0 ? { platform: debouncedFilters.selectedPlatforms.join(",") } : {}),
        ...(debouncedFilters.selectedCountries.length > 0 ? { country: debouncedFilters.selectedCountries.join(",") } : {}),
        ...(debouncedFilters.selectedPromptTypes.length > 0 ? { prompt_type: debouncedFilters.selectedPromptTypes.join(",") } : {}),
        ...(debouncedFilters.products && debouncedFilters.products.length > 0 ? { products: debouncedFilters.products.join(",") } : {}),
        ...(debouncedFilters.promptIds && debouncedFilters.promptIds.length > 0 ? { prompt_ids: debouncedFilters.promptIds.join(",") } : {}),
    }), [debouncedFilters]);

    if (requestFailed) {
        return (
            <RetryableSentimentError
                message={t("sentiment.loadFailed")}
                onRetry={() => setRetryVersion((value) => value + 1)}
            />
        );
    }

    if (requestPending) {
        return (
            <div className="flex items-center justify-center py-24">
                <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
        );
    }

    return (
        <div className="space-y-8">
            {/* ── Section 1: KPI Summary ──────────────────────────────────────── */}
            <section>
                <div className="flex items-center gap-2 mb-5">
                    <SmilePlus className="h-5 w-5 text-primary" />
                    <h2 className="text-lg font-semibold">{t("sentiment.aiSentimentOverview")}</h2>
                    <span className="text-sm text-muted-foreground">{t("sentiment.aiSentimentSubtitle")}</span>
                </div>

                <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 mb-8">
                    {/* Left Column: Trend Chart (col-span-8) */}
                    <div className="lg:col-span-8 space-y-6 flex flex-col">
                        <Card className="shadow-none flex-1 flex flex-col">
                            {/* Header with big KPI + Chart Toggles */}
                            <CardHeader className="pb-2 flex flex-row items-start justify-between border-b pb-4 mb-4">
                                <div>
                                    <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-2 mb-2">
                                        <Activity className="h-4 w-4" />
                                        {t("sentiment.trend")}
                                    </CardTitle>
                                    <div className="flex items-baseline gap-3">
                                        <div className="text-3xl font-bold gradient-text-static tracking-tight">
                                            {summary.positive_pct ?? "—"}%
                                        </div>
                                        {summary.positive_pct_change != null && (
                                            <div className={`text-sm flex items-center gap-0.5 font-medium ${summary.positive_pct_change >= 0 ? "text-emerald-500" : "text-red-400"}`}>
                                                {summary.positive_pct_change >= 0 ? <TrendingUp className="h-4 w-4" /> : <TrendingDown className="h-4 w-4" />}
                                                {summary.positive_pct_change >= 0 ? "+" : ""}{summary.positive_pct_change}% {t("sentiment.vsPrev")}
                                            </div>
                                        )}
                                    </div>
                                </div>
                                <div className="flex flex-col items-end gap-3">
                                    <div className="flex items-center gap-2 mr-1">
                                        <Switch id="compare-mode" checked={comparePrev} onCheckedChange={setComparePrev} />
                                        <Label htmlFor="compare-mode" className="text-xs cursor-pointer font-medium text-muted-foreground">{t("sentiment.comparePrevious")}</Label>
                                    </div>
                                    <div className="flex items-center bg-muted/50 p-1 rounded-md border border-border/50">
                                        <button
                                            onClick={() => setChartMode("line")}
                                            className={`px-3 py-1 rounded text-xs font-medium transition-colors ${chartMode === "line" ? "bg-background shadow-sm border border-border/50" : "hover:text-foreground text-muted-foreground"}`}
                                        >
                                            {t("sentiment.chartLine")}
                                        </button>
                                        <button
                                            onClick={() => setChartMode("bar")}
                                            className={`px-3 py-1 rounded text-xs font-medium transition-colors ${chartMode === "bar" ? "bg-background shadow-sm border border-border/50" : "hover:text-foreground text-muted-foreground"}`}
                                        >
                                            {t("sentiment.chartBar")}
                                        </button>
                                    </div>
                                </div>
                            </CardHeader>
                            <CardContent className="flex-1 pb-2">
                                {chartData.length > 0 ? (
                                    <ResponsiveContainer width="100%" height={360}>
                                        {chartMode === "bar" ? (
                                            <RechartsBarChart data={chartData} barGap={4} margin={{ top: 20, right: 12, left: 8, bottom: 0 }}>
                                                <XAxis dataKey="date" stroke="#888" fontSize={11} tickLine={false} axisLine={false} tickFormatter={fmtDate} tickMargin={10} />
                                                <YAxis stroke="#888" fontSize={11} tickLine={false} axisLine={false} unit="%" width={52} tickMargin={8} domain={[(dataMin: number) => Math.max(0, Math.floor(dataMin - 5)), (dataMax: number) => Math.min(100, Math.ceil(dataMax + 5))]} />
                                                <RechartsTooltip
                                                    content={<GlassTooltip />}
                                                    formatter={(val: unknown, name?: string | number) => [fmtPercentValue(val), name === "positive_pct" ? t("sentiment.positiveCurrent") : t("sentiment.positivePrevious")]}
                                                    labelFormatter={(v: unknown) => { const s = String(v); const d = s.includes("T") ? new Date(s) : new Date(s + "T00:00:00"); return d.toLocaleDateString(); }}
                                                />
                                                <Bar dataKey="positive_pct" radius={[4, 4, 0, 0]} maxBarSize={40} fill="#10b981" />
                                                {comparePrev && (
                                                    <Bar dataKey="prev_positive_pct" fill="#71717a" fillOpacity={0.2} radius={[4, 4, 0, 0]} maxBarSize={40} />
                                                )}
                                            </RechartsBarChart>
                                        ) : (
                                            <LineChart data={chartData} margin={{ top: 20, right: 12, left: 8, bottom: 0 }}>
                                                <XAxis dataKey="date" stroke="#888" fontSize={11} tickLine={false} axisLine={false} tickFormatter={fmtDate} tickMargin={10} />
                                                <YAxis stroke="#888" fontSize={11} tickLine={false} axisLine={false} unit="%" width={52} tickMargin={8} domain={[(dataMin: number) => Math.max(0, Math.floor(dataMin - 5)), (dataMax: number) => Math.min(100, Math.ceil(dataMax + 5))]} />
                                                <RechartsTooltip
                                                    content={<GlassTooltip />}
                                                    formatter={(val: unknown, name?: string | number) => [fmtPercentValue(val), name === "positive_pct" ? t("sentiment.positiveCurrent") : t("sentiment.positivePrevious")]}
                                                    labelFormatter={(v: unknown) => { const s = String(v); const d = s.includes("T") ? new Date(s) : new Date(s + "T00:00:00"); return d.toLocaleDateString(); }}
                                                />
                                                <Line type="monotone" dataKey="positive_pct" stroke="#10b981" strokeWidth={3} dot={{ r: 4, strokeWidth: 2 }} activeDot={{ r: 6 }} connectNulls={false} />
                                                {comparePrev && (
                                                    <Line type="monotone" dataKey="prev_positive_pct" stroke="#71717a" strokeWidth={1.5} strokeDasharray="5 5" opacity={0.35} dot={false} />
                                                )}
                                            </LineChart>
                                        )}
                                    </ResponsiveContainer>
                                ) : (
                                    <EmptyState message={t("sentiment.noTrendData")} />
                                )}
                            </CardContent>
                        </Card>
                    </div>

                    {/* Right Column: Themes & Stacked Bar (col-span-4) */}
                    <div className="lg:col-span-4 space-y-4 flex flex-col">

                        {/* Summary Stacked Sentiment Ratio Bar */}
                        {summary.total_count > 0 && (
                            <Card className="shadow-sm border-border">
                                <CardHeader className="pb-0 pt-4 px-5">
                                    <CardTitle className="text-xs text-muted-foreground font-medium uppercase tracking-wider">{t("sentiment.overallSentiment")}</CardTitle>
                                </CardHeader>
                                <CardContent className="pt-3 pb-5 px-5">
                                    <div className="grid grid-cols-3 gap-2 mb-2.5 text-xs font-bold">
                                        <div className="text-sm font-bold text-emerald-500">{t("sentiment.positivePctLabel", { pct: summary.positive_pct })}</div>
                                        <div className="text-center text-amber-600">{t("sentiment.mixedNeutralPctLabel", { pct: summary.mixed_neutral_pct })}</div>
                                        <div className="text-right text-red-500">{t("sentiment.negativePctLabel", { pct: summary.negative_pct })}</div>
                                    </div>
                                    <div className="w-full h-5 flex rounded-lg overflow-hidden shadow-inner bg-muted">
                                        <div className="h-full bg-emerald-500 transition-all duration-500" style={{ width: `${summary.positive_pct}%` }} />
                                        <div className="h-full bg-amber-400 transition-all duration-500" style={{ width: `${summary.mixed_neutral_pct}%` }} />
                                        <div className="h-full bg-red-500 transition-all duration-500" style={{ width: `${summary.negative_pct}%` }} />
                                    </div>
                                    <div className="mt-3 space-y-1 text-xs text-muted-foreground">
                                        <div>{t("sentiment.ratedResponses", { count: summary.rated_count })}</div>
                                        <div>{t("sentiment.insufficientEvidenceSummary", { count: summary.insufficient_evidence_count })}</div>
                                    </div>
                                </CardContent>
                            </Card>
                        )}

                        {/* Top Positive Themes */}
                        <Card className="shadow-sm border-border flex-1">
                            <CardHeader className="pb-3 pt-4 px-5">
                                <CardTitle className="text-xs text-muted-foreground font-medium uppercase tracking-wider flex items-center gap-1.5">
                                    <SmilePlus className="h-3.5 w-3.5 text-emerald-500" /> {t("sentiment.topPositiveThemes")}
                                </CardTitle>
                            </CardHeader>
                            <CardContent className="px-5 pb-5 space-y-0">
                                {(summary.positive_top3_themes || []).length > 0
                                    ? (summary.positive_top3_themes || []).map((t: string, i: number) => (
                                        <div key={t} className="flex items-start gap-3 py-2.5 border-b last:border-0 border-border/50">
                                            <div className="flex-shrink-0 w-5 h-5 rounded-full bg-emerald-500/10 flex items-center justify-center text-emerald-600 text-[10px] font-bold mt-0.5">
                                                {i + 1}
                                            </div>
                                            <div className="text-sm font-medium text-foreground leading-snug">{t}</div>
                                        </div>
                                    ))
                                    : <div className="text-sm text-muted-foreground pt-2">—</div>
                                }
                            </CardContent>
                        </Card>

                        {/* Top Negative Themes */}
                        <Card className="shadow-sm border-border flex-1">
                            <CardHeader className="pb-3 pt-4 px-5">
                                <CardTitle className="text-xs text-muted-foreground font-medium uppercase tracking-wider flex items-center gap-1.5">
                                    <Frown className="h-3.5 w-3.5 text-red-400" /> {t("sentiment.topNegativeThemes")}
                                </CardTitle>
                            </CardHeader>
                            <CardContent className="px-5 pb-5 space-y-0">
                                {(summary.negative_top3_themes || []).length > 0
                                    ? (summary.negative_top3_themes || []).map((t: string, i: number) => (
                                        <div key={t} className="flex items-start gap-3 py-2.5 border-b last:border-0 border-border/50">
                                            <div className="flex-shrink-0 w-5 h-5 rounded-full bg-red-500/10 flex items-center justify-center text-red-500 text-[10px] font-bold mt-0.5">
                                                {i + 1}
                                            </div>
                                            <div className="text-sm font-medium text-foreground leading-snug">{t}</div>
                                        </div>
                                    ))
                                    : <div className="text-sm text-muted-foreground pt-2">—</div>
                                }
                            </CardContent>
                        </Card>
                    </div>
                </div>
            </section>

            {/* ── Section 2: Themes Table ──────────────────────────────────────── */}
            <section>
                <div className="flex items-center justify-between mb-4">
                    <div>
                        <h2 className="text-lg font-semibold flex items-center gap-2">
                            <MessageSquareText className="h-5 w-5 text-primary" />
                            {t("sentiment.themesTitle")}
                        </h2>
                        <p className="text-sm text-muted-foreground">{t("sentiment.themesSubtitle")}</p>
                    </div>
                    {/* Sentiment filter toggle */}
                    <div className="flex items-center gap-1 bg-muted rounded-lg p-1">
                        {(["", "Positive", "Mixed/Neutral", "Negative"] as const).map(f => (
                            <button
                                key={f}
                                onClick={() => { setSentimentFilter(f); setThemesVisible(10); }}
                                className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${sentimentFilter === f ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"}`}
                            >
                                {f === "" ? t("sentiment.filterAll") : f === "Positive" ? t("sentiment.filterPositive") : f === "Mixed/Neutral" ? t("sentiment.filterMixedNeutral") : t("sentiment.filterNegative")}
                            </button>
                        ))}
                    </div>
                </div>

                <Card className="relative shadow-none">
                    {/* Table header */}
                    <div className="flex items-center gap-4 px-4 py-2 border-b border-border text-xs text-muted-foreground uppercase tracking-wider font-medium" data-sort-list="sentiment-themes">
                        <div className="flex-1">{t("sentiment.table.theme")}</div>
                        <div className="w-24">{t("sentiment.table.sentiment")}</div>
                        <div className="w-28 text-right"><SortableMetricHeader label={t("sentiment.table.occurrences")} metricKey="occurrence_count" sort={themeSort} onChange={(next) => { setThemesVisible(10); setThemeSort(next); }} /></div>
                        <div className="w-24 text-right"><SortableMetricHeader label={t("sentiment.table.change")} metricKey="occurrence_change" sort={themeSort} onChange={(next) => { setThemesVisible(10); setThemeSort(next); }} /></div>
                        <div className="w-6" />
                    </div>
                    <div className="relative min-h-32">
                    {themeListPending && (
                        <div className="absolute inset-0 z-10 flex items-center justify-center bg-background/60 backdrop-blur-[1px]">
                            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                        </div>
                    )}
                    {currentThemeLoadError && !themeListPending ? (
                        <div className="flex min-h-32 items-center justify-center gap-3 text-sm text-muted-foreground">
                            <span>{t("sentiment.loadFailed")}</span>
                            <Button variant="outline" size="sm" onClick={() => setThemeRetryVersion((value) => value + 1)}>
                                {t("common:actions.retry")}
                            </Button>
                        </div>
                    ) : themes.length > 0
                        ? themes.slice(0, themesVisible).map((theme, i) => (
                            <ThemeRow
                                key={`${effectiveFilterKey}:${theme.theme_name}:${theme.sentiment}:${i}`}
                                theme={theme}
                                clientId={clientId}
                                dateFrom={debouncedFilters.dateFrom}
                                dateTo={debouncedFilters.dateTo}
                                selectedTopics={debouncedFilters.selectedTopics}
                                selectedPlatforms={debouncedFilters.selectedPlatforms}
                                selectedCountries={debouncedFilters.selectedCountries}
                                selectedPromptTypes={debouncedFilters.selectedPromptTypes}
                                products={debouncedFilters.products}
                                promptIds={debouncedFilters.promptIds}
                                sentimentFilter={sentimentFilter}
                                onOpenResult={openResult}
                            />
                        ))
                        : (
                            <EmptyState message={t("sentiment.noThemesData")} />
                        )
                    }
                    {!currentThemeLoadError && themes.length > themesVisible && (
                        <div className="flex justify-center py-4 border-t border-border">
                            <button
                                onClick={() => setThemesVisible((v) => v + 10)}
                                className="text-sm font-medium text-primary hover:text-primary/80 transition-colors"
                            >
                                {t("sentiment.showMoreThemes", { count: themes.length - themesVisible })}
                            </button>
                        </div>
                    )}
                    </div>
                </Card>
            </section>

            {/* ── Result Detail Drawer ──────────────────────────────────────── */}
            <ResultDetailDrawer
                key={effectiveFilterKey}
                clientId={clientId}
                resultId={drawerResultId}
                open={drawerOpen}
                onClose={() => setDrawerOpen(false)}
                targetParams={detailTargetParams}
            />
        </div>
    );
}

function RetryableSentimentError({ message, onRetry }: { message: string; onRetry: () => void }) {
    const { t } = useTranslation("common");
    return (
        <div className="flex flex-col items-center justify-center gap-3 py-24 text-center text-sm text-muted-foreground">
            <span>{message}</span>
            <Button variant="outline" size="sm" onClick={onRetry}>{t("actions.retry")}</Button>
        </div>
    );
}
