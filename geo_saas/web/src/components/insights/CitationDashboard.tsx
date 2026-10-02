import { useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import type { TFunction } from "i18next";
import type { components } from "@/api/openapi";
import {
    getCitationCategories,
    getCitationRanking,
    getCitationShare,
    getCitedDomains,
    getCitedPages,
    getPublishedUrlTracking,
    getPublishedUrlTrackingDetail,
    getPublishedUrlTrackingVariants,
    setPublishedUrlCitationMatch,
    type CitedDomainsOut,
    type CitedPagesOut,
    type PublishedUrlTrackingDetailOut,
    type PublishedUrlTrackingRow,
    type PublishedUrlVariantRow,
} from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Input } from "@/components/ui/input";
import { Sheet, SheetContent, SheetDescription, SheetHeader, SheetTitle } from "@/components/ui/sheet";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import {
    LineChart, Line, XAxis, YAxis, Tooltip, ResponsiveContainer,
} from "recharts";
import { Link2, Loader2, Trophy, Expand, Search, Info, TrendingUp, TrendingDown, Check } from "lucide-react";
import { GlassTooltip } from "@/components/ui/chart-tooltip";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { HelpTooltip } from "@/components/ui/HelpTooltip";
import { selectDashboardFilterKey } from "@/pages/insights/promptDrilldownTarget";
import { SortableMetricHeader } from "@/components/ui/SortableMetricHeader";
import { type MetricSortState, withMetricSortParams } from "@/lib/metricSort";
import { buildCitationQueryKeys } from "@/components/insights/citationSortState";

const RANKING_PAGE_SIZE = 20;
const SEARCH_DEBOUNCE_MS = 300;
const REQUEST_START_DELAY_MS = 50;

type Schemas = components["schemas"];
type CitationsData = Schemas["CitationsOut"];
type CitationDomainRankingRow = Schemas["CitationDomainRow"];
type CitationCategoryLike = Schemas["CitationCategoryRow"] & {
    domain_category?: string | null;
    citation_count?: number;
};
type CitationTimePoint = Schemas["CitationTimePoint"] & { prev_own_share?: number | null };
type CitationTranslation = TFunction<readonly ["insights", "common"]>;
type PageUpdater = number | ((current: number) => number);

interface CriteriaPageState {
    criteriaKey: string;
    page: number;
}

const EMPTY_CITATION_SUMMARY: Schemas["CitationsSummary"] = {
    total_citations: 0,
    own_domain_share: 0,
    own_citation_count: 0,
};

function nextCriteriaPage(
    current: CriteriaPageState,
    criteriaKey: string,
    next: PageUpdater,
): CriteriaPageState {
    const currentPage = current.criteriaKey === criteriaKey ? current.page : 0;
    return {
        criteriaKey,
        page: typeof next === "function" ? next(currentPage) : next,
    };
}

// Category colors matching backend enum
const CATEGORY_COLORS: Record<string, string> = {
    "Earned Media": "#3b82f6",
    "Social Media": "#8b5cf6",
    "Owned Media": "#10b981",
    "Agency": "#f59e0b",
    "Other": "#6b7280",
};

function getCategoryColor(category: string | null | undefined): string {
    return CATEGORY_COLORS[category || "Other"] || CATEGORY_COLORS["Other"];
}

function fmtDate(v: unknown) {
    const s = String(v);
    const d = s.includes("T") ? new Date(s) : new Date(s + "T00:00:00");
    return `${d.getMonth() + 1}/${d.getDate()}`;
}

function fmtPercentValue(val: unknown) {
    if (val == null || Number.isNaN(Number(val))) return "—";
    return `${Number(val).toFixed(2)}%`;
}

export interface CitationDashboardFilters {
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

export interface CitationDashboardProps {
    clientId: string;
    filters: CitationDashboardFilters;
    filtersReady?: boolean;
    mode?: "sidebar" | "drilldown";
}

function applyMandatoryTarget(
    params: Record<string, string>,
    filters: Pick<CitationDashboardFilters, "products" | "promptIds">,
) {
    if (filters.products && filters.products.length > 0) params.products = filters.products.join(",");
    if (filters.promptIds && filters.promptIds.length > 0) params.prompt_ids = filters.promptIds.join(",");
}

export default function CitationDashboard({
    clientId,
    filters,
    filtersReady = true,
    mode = "sidebar",
}: CitationDashboardProps) {
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
    const [shareData, setShareData] = useState<CitationsData | null>(null);
    const [rankingData, setRankingData] = useState<CitationsData | null>(null);
    const [categoryData, setCategoryData] = useState<CitationsData | null>(null);
    const [shareLoading, setShareLoading] = useState(true);
    const [rankingLoading, setRankingLoading] = useState(true);
    const [categoryLoading, setCategoryLoading] = useState(true);
    const [shareError, setShareError] = useState(false);
    const [rankingError, setRankingError] = useState(false);
    const [categoryError, setCategoryError] = useState(false);
    const [shareSettledKey, setShareSettledKey] = useState("");
    const [rankingSettledKey, setRankingSettledKey] = useState("");
    const [rankingSettledBaseKey, setRankingSettledBaseKey] = useState("");
    const [categorySettledKey, setCategorySettledKey] = useState("");
    const [categorySettledBaseKey, setCategorySettledBaseKey] = useState("");
    const [shareRetryVersion, setShareRetryVersion] = useState(0);
    const [rankingRetryVersion, setRankingRetryVersion] = useState(0);
    const [categoryRetryVersion, setCategoryRetryVersion] = useState(0);
    const [expandRanking, setExpandRanking] = useState(false);
    const [domainSearch, setDomainSearch] = useState("");
    const [pageSearch, setPageSearch] = useState("");
    const [debouncedDomainSearch, setDebouncedDomainSearch] = useState("");
    const [debouncedPageSearch, setDebouncedPageSearch] = useState("");
    const [domainPageState, setDomainPageState] = useState<CriteriaPageState>({ criteriaKey: "", page: 0 });
    const [pagePageState, setPagePageState] = useState<CriteriaPageState>({ criteriaKey: "", page: 0 });
    const [domainData, setDomainData] = useState<CitedDomainsOut | null>(null);
    const [pageData, setPageData] = useState<CitedPagesOut | null>(null);
    const [domainLoading, setDomainLoading] = useState(false);
    const [pageLoading, setPageLoading] = useState(false);
    const [domainError, setDomainError] = useState(false);
    const [pageError, setPageError] = useState(false);
    const [domainSettledKey, setDomainSettledKey] = useState("");
    const [domainSettledBaseKey, setDomainSettledBaseKey] = useState("");
    const [pageSettledKey, setPageSettledKey] = useState("");
    const [pageSettledBaseKey, setPageSettledBaseKey] = useState("");
    const [domainRetryVersion, setDomainRetryVersion] = useState(0);
    const [pageRetryVersion, setPageRetryVersion] = useState(0);
    const [showPrevCitation, setShowPrevCitation] = useState(false);
    const [rankingSort, setRankingSort] = useState<MetricSortState>({ metricKey: "citation_count", direction: "desc" });
    const [categorySort, setCategorySort] = useState<MetricSortState>({ metricKey: "count", direction: "desc" });
    const [domainSort, setDomainSort] = useState<MetricSortState>({ metricKey: "citation_count", direction: "desc" });
    const [pageSort, setPageSort] = useState<MetricSortState>({ metricKey: "citation_count", direction: "desc" });
    const shareRequestSeq = useRef(0);
    const rankingRequestSeq = useRef(0);
    const categoryRequestSeq = useRef(0);
    const domainRequestSeq = useRef(0);
    const pageRequestSeq = useRef(0);
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
    const domainPageCriteriaKey = useMemo(() => JSON.stringify({
        effectiveFilterKey,
        search: debouncedDomainSearch,
        sort: domainSort,
    }), [debouncedDomainSearch, domainSort, effectiveFilterKey]);
    const pagePageCriteriaKey = useMemo(() => JSON.stringify({
        effectiveFilterKey,
        search: debouncedPageSearch,
        sort: pageSort,
    }), [debouncedPageSearch, effectiveFilterKey, pageSort]);
    const domainPage = domainPageState.criteriaKey === domainPageCriteriaKey ? domainPageState.page : 0;
    const pagePage = pagePageState.criteriaKey === pagePageCriteriaKey ? pagePageState.page : 0;
    const setDomainPage = (next: PageUpdater) => {
        setDomainPageState((current) => nextCriteriaPage(current, domainPageCriteriaKey, next));
    };
    const setPagePage = (next: PageUpdater) => {
        setPagePageState((current) => nextCriteriaPage(current, pagePageCriteriaKey, next));
    };
    const baseQueryKey = effectiveFilterKey;

    const {
        shareQueryKey,
        rankingQueryKey,
        categoryQueryKey,
        domainQueryKey,
        pageQueryKey,
    } = buildCitationQueryKeys({
        baseKey: effectiveFilterKey,
        rankingSort,
        categorySort,
        domainSearch: debouncedDomainSearch,
        domainPage,
        domainSort,
        pageSearch: debouncedPageSearch,
        pagePage,
        pageSort,
    });
    const currentShareQueryKeyRef = useRef(shareQueryKey);
    const currentRankingQueryKeyRef = useRef(rankingQueryKey);
    const currentCategoryQueryKeyRef = useRef(categoryQueryKey);
    useEffect(() => {
        currentShareQueryKeyRef.current = shareQueryKey;
        currentRankingQueryKeyRef.current = rankingQueryKey;
        currentCategoryQueryKeyRef.current = categoryQueryKey;
    }, [categoryQueryKey, rankingQueryKey, shareQueryKey]);

    const summaryParams = useMemo(() => {
        const params: Record<string, string> = {
            date_from: debouncedFilters.dateFrom,
            date_to: debouncedFilters.dateTo,
            interval: debouncedFilters.interval,
        };
        if (debouncedFilters.selectedTopics.length > 0) params.topic_ids = debouncedFilters.selectedTopics.join(",");
        if (debouncedFilters.selectedPlatforms.length > 0) params.platform = debouncedFilters.selectedPlatforms.join(",");
        if (debouncedFilters.selectedCountries.length > 0) params.country = debouncedFilters.selectedCountries.join(",");
        if (debouncedFilters.selectedPromptTypes.length > 0) params.prompt_type = debouncedFilters.selectedPromptTypes.join(",");
        applyMandatoryTarget(params, debouncedFilters);
        return params;
    }, [debouncedFilters]);

    useEffect(() => {
        if (!clientId || !filtersReady) return;
        const controller = new AbortController();
        const requestId = ++shareRequestSeq.current;
        const requestKey = shareQueryKey;
        const isCurrent = () => requestId === shareRequestSeq.current && requestKey === currentShareQueryKeyRef.current;
        const timer = window.setTimeout(() => {
            setShareLoading(true);
            setShareError(false);
            setShareData(null);
            getCitationShare(clientId, summaryParams, { signal: controller.signal })
                .then((res) => { if (isCurrent()) { setShareData(res); setShareSettledKey(requestKey); } })
                .catch((err) => { if (err?.name !== "AbortError" && isCurrent()) { setShareData(null); setShareError(true); setShareSettledKey(requestKey); } })
                .finally(() => { if (isCurrent()) setShareLoading(false); });
        }, REQUEST_START_DELAY_MS);
        return () => { window.clearTimeout(timer); controller.abort(); };
    }, [clientId, filtersReady, shareQueryKey, shareRetryVersion, summaryParams]);

    useEffect(() => {
        if (!clientId || !filtersReady) return;
        const controller = new AbortController();
        const requestId = ++rankingRequestSeq.current;
        const requestKey = rankingQueryKey;
        const requestBaseKey = baseQueryKey;
        const isCurrent = () => requestId === rankingRequestSeq.current && requestKey === currentRankingQueryKeyRef.current;
        const timer = window.setTimeout(() => {
            setRankingLoading(true);
            setRankingError(false);
            setRankingData(null);
            getCitationRanking(clientId, withMetricSortParams(summaryParams, rankingSort), { signal: controller.signal })
                .then((res) => { if (isCurrent()) { setRankingData(res); setRankingSettledKey(requestKey); setRankingSettledBaseKey(requestBaseKey); } })
                .catch((err) => { if (err?.name !== "AbortError" && isCurrent()) { setRankingData(null); setRankingError(true); setRankingSettledKey(requestKey); setRankingSettledBaseKey(requestBaseKey); } })
                .finally(() => { if (isCurrent()) setRankingLoading(false); });
        }, REQUEST_START_DELAY_MS);
        return () => { window.clearTimeout(timer); controller.abort(); };
    }, [clientId, filtersReady, rankingQueryKey, rankingRetryVersion, rankingSort, summaryParams]);

    const primarySummaryQueriesSettled = shareSettledKey === baseQueryKey
        && rankingSettledBaseKey === baseQueryKey;

    useEffect(() => {
        if (!clientId || !filtersReady || !primarySummaryQueriesSettled) return;
        const controller = new AbortController();
        const requestId = ++categoryRequestSeq.current;
        const requestKey = categoryQueryKey;
        const requestBaseKey = baseQueryKey;
        const isCurrent = () => requestId === categoryRequestSeq.current && requestKey === currentCategoryQueryKeyRef.current;
        const timer = window.setTimeout(() => {
            setCategoryLoading(true);
            setCategoryError(false);
            setCategoryData(null);
            getCitationCategories(clientId, withMetricSortParams(summaryParams, categorySort), { signal: controller.signal })
                .then((res) => { if (isCurrent()) { setCategoryData(res); setCategorySettledKey(requestKey); setCategorySettledBaseKey(requestBaseKey); } })
                .catch((err) => { if (err?.name !== "AbortError" && isCurrent()) { setCategoryData(null); setCategoryError(true); setCategorySettledKey(requestKey); setCategorySettledBaseKey(requestBaseKey); } })
                .finally(() => { if (isCurrent()) setCategoryLoading(false); });
        }, REQUEST_START_DELAY_MS);
        return () => { window.clearTimeout(timer); controller.abort(); };
    }, [categoryQueryKey, categoryRetryVersion, categorySort, clientId, filtersReady, primarySummaryQueriesSettled, summaryParams]);

    useEffect(() => {
        const timer = window.setTimeout(() => {
            setDebouncedDomainSearch(domainSearch);
        }, SEARCH_DEBOUNCE_MS);
        return () => window.clearTimeout(timer);
    }, [domainSearch]);

    useEffect(() => {
        const timer = window.setTimeout(() => {
            setDebouncedPageSearch(pageSearch);
        }, SEARCH_DEBOUNCE_MS);
        return () => window.clearTimeout(timer);
    }, [pageSearch]);

    const currentDomainQueryKeyRef = useRef(domainQueryKey);
    const currentPageQueryKeyRef = useRef(pageQueryKey);
    useEffect(() => {
        currentDomainQueryKeyRef.current = domainQueryKey;
        currentPageQueryKeyRef.current = pageQueryKey;
    }, [domainQueryKey, pageQueryKey]);

    // Release heavy list queries only after the first summary query has returned.
    // Ranking/category sorts must not restart unrelated domain/page lists.
    const summaryQueriesSettled = primarySummaryQueriesSettled
        && categorySettledBaseKey === baseQueryKey;

    useEffect(() => {
        if (!clientId || !filtersReady || !summaryQueriesSettled) return;
        const controller = new AbortController();
        const requestId = ++domainRequestSeq.current;
        const requestQueryKey = domainQueryKey;
        const requestBaseKey = baseQueryKey;
        const isCurrent = () => requestId === domainRequestSeq.current
            && requestQueryKey === currentDomainQueryKeyRef.current;
        const params: Record<string, string> = {
            date_from: debouncedFilters.dateFrom,
            date_to: debouncedFilters.dateTo,
            limit: String(RANKING_PAGE_SIZE),
            offset: String(domainPage * RANKING_PAGE_SIZE),
        };
        if (debouncedFilters.selectedTopics.length > 0) params.topic_ids = debouncedFilters.selectedTopics.join(",");
        if (debouncedFilters.selectedPlatforms.length > 0) params.platform = debouncedFilters.selectedPlatforms.join(",");
        if (debouncedFilters.selectedCountries.length > 0) params.country = debouncedFilters.selectedCountries.join(",");
        if (debouncedFilters.selectedPromptTypes.length > 0) params.prompt_type = debouncedFilters.selectedPromptTypes.join(",");
        applyMandatoryTarget(params, debouncedFilters);
        if (debouncedDomainSearch.trim()) params.search = debouncedDomainSearch.trim();
        const startTimer = window.setTimeout(() => {
            setDomainLoading(true);
            setDomainError(false);
            setDomainData(null);
            getCitedDomains(clientId, withMetricSortParams(params, domainSort), { signal: controller.signal })
                .then(res => {
                    if (isCurrent()) {
                        setDomainData(res);
                        setDomainSettledKey(requestQueryKey);
                        setDomainSettledBaseKey(requestBaseKey);
                    }
                })
                .catch((err) => {
                    if (err?.name === "AbortError") return;
                    if (isCurrent()) {
                        setDomainData(null);
                        setDomainError(true);
                        setDomainSettledKey(requestQueryKey);
                        setDomainSettledBaseKey(requestBaseKey);
                    }
                })
                .finally(() => {
                    if (isCurrent()) setDomainLoading(false);
                });
        }, REQUEST_START_DELAY_MS);
        return () => {
            window.clearTimeout(startTimer);
            controller.abort();
        };
    }, [clientId, filtersReady, summaryQueriesSettled, debouncedFilters, debouncedDomainSearch, domainPage, domainQueryKey, domainRetryVersion, domainSort]);

    useEffect(() => {
        if (!clientId || !filtersReady || domainSettledBaseKey !== baseQueryKey) return;
        const controller = new AbortController();
        const requestId = ++pageRequestSeq.current;
        const requestQueryKey = pageQueryKey;
        const requestBaseKey = baseQueryKey;
        const isCurrent = () => requestId === pageRequestSeq.current
            && requestQueryKey === currentPageQueryKeyRef.current;
        const params: Record<string, string> = {
            date_from: debouncedFilters.dateFrom,
            date_to: debouncedFilters.dateTo,
            limit: String(RANKING_PAGE_SIZE),
            offset: String(pagePage * RANKING_PAGE_SIZE),
        };
        if (debouncedFilters.selectedTopics.length > 0) params.topic_ids = debouncedFilters.selectedTopics.join(",");
        if (debouncedFilters.selectedPlatforms.length > 0) params.platform = debouncedFilters.selectedPlatforms.join(",");
        if (debouncedFilters.selectedCountries.length > 0) params.country = debouncedFilters.selectedCountries.join(",");
        if (debouncedFilters.selectedPromptTypes.length > 0) params.prompt_type = debouncedFilters.selectedPromptTypes.join(",");
        applyMandatoryTarget(params, debouncedFilters);
        if (debouncedPageSearch.trim()) params.search = debouncedPageSearch.trim();
        const startTimer = window.setTimeout(() => {
            setPageLoading(true);
            setPageError(false);
            setPageData(null);
            getCitedPages(clientId, withMetricSortParams(params, pageSort), { signal: controller.signal })
                .then(res => {
                    if (isCurrent()) {
                        setPageData(res);
                        setPageSettledKey(requestQueryKey);
                        setPageSettledBaseKey(requestBaseKey);
                    }
                })
                .catch((err) => {
                    if (err?.name === "AbortError") return;
                    if (isCurrent()) {
                        setPageData(null);
                        setPageError(true);
                        setPageSettledKey(requestQueryKey);
                        setPageSettledBaseKey(requestBaseKey);
                    }
                })
                .finally(() => {
                    if (isCurrent()) setPageLoading(false);
                });
        }, REQUEST_START_DELAY_MS);
        return () => {
            window.clearTimeout(startTimer);
            controller.abort();
        };
    }, [baseQueryKey, clientId, filtersReady, domainSettledBaseKey, debouncedFilters, debouncedPageSearch, pagePage, pageQueryKey, pageRetryVersion, pageSort]);

    const currentShareData = shareSettledKey === shareQueryKey && !shareError ? shareData : null;
    const currentRankingData = rankingSettledKey === rankingQueryKey && !rankingError ? rankingData : null;
    const currentCategoryData = categorySettledKey === categoryQueryKey && !categoryError ? categoryData : null;
    const currentDomainData = domainSettledKey === domainQueryKey && !domainError ? domainData : null;
    const currentPageData = pageSettledKey === pageQueryKey && !pageError ? pageData : null;
    const sharePending = shareLoading || shareSettledKey !== shareQueryKey;
    const rankingPending = rankingLoading || rankingSettledKey !== rankingQueryKey;
    const categoryPending = categoryLoading || categorySettledKey !== categoryQueryKey;
    const domainPending = domainLoading || domainSettledKey !== domainQueryKey;
    const pagePending = pageLoading || pageSettledKey !== pageQueryKey;
    const shareFailed = shareSettledKey === shareQueryKey && shareError;
    const rankingFailed = rankingSettledKey === rankingQueryKey && rankingError;
    const categoryFailed = categorySettledKey === categoryQueryKey && categoryError;
    const domainFailed = domainSettledKey === domainQueryKey && domainError;
    const pageFailed = pageSettledKey === pageQueryKey && pageError;
    const shareSummary = currentShareData?.summary || EMPTY_CITATION_SUMMARY;
    const rankingSummary = currentRankingData?.summary || EMPTY_CITATION_SUMMARY;
    const categorySummary = currentCategoryData?.summary || EMPTY_CITATION_SUMMARY;
    const summary = {
        ...shareSummary,
        total_citations: shareSummary.total_citations ?? categorySummary.total_citations ?? rankingSummary.total_citations ?? 0,
        own_rank: rankingSummary.own_rank ?? null,
        own_rank_change: rankingSummary.own_rank_change ?? null,
    };
    const domainRanking: CitationDomainRankingRow[] = currentRankingData?.domain_ranking || [];
    const rawTimeSeries = currentShareData?.time_series || [];
    const rawPrevTimeSeries = currentShareData?.prev_time_series || [];
    // Merge prev period data into main array by index (avoids Recharts XAxis distortion)
    const timeSeries: CitationTimePoint[] = rawTimeSeries.map((pt, i) => ({
        ...pt,
        prev_own_share: rawPrevTimeSeries[i]?.own_share ?? null,
    }));
    const prevHasData = rawPrevTimeSeries.length > 0;

    // Use backend domain_category (falls back to "Other" for NULL)
    const classifiedDomains = domainRanking.map((r) => ({
        ...r,
        categoryLabel: r.domain_category || "Other",
        categoryColor: getCategoryColor(r.domain_category),
    }));

    const domainRows = (currentDomainData?.domains || []).map((r) => ({
        ...r,
        categoryLabel: r.domain_category || "Other",
        categoryColor: getCategoryColor(r.domain_category),
    }));
    const pageRows = currentPageData?.pages || [];
    const domainTotal = currentDomainData?.total_unique_domains ?? domainRows.length;
    const pageTotal = currentPageData?.total_unique_pages ?? pageRows.length;
    const domainHasMore = !!currentDomainData?.has_more;
    const pageHasMore = !!currentPageData?.has_more;
    const domainStart = domainTotal > 0 ? domainPage * RANKING_PAGE_SIZE + 1 : 0;
    const domainEnd = Math.min((domainPage + 1) * RANKING_PAGE_SIZE, domainTotal);
    const pageStart = pageTotal > 0 ? pagePage * RANKING_PAGE_SIZE + 1 : 0;
    const pageEnd = Math.min((pagePage + 1) * RANKING_PAGE_SIZE, pageTotal);

    const categoryBreakdown: Array<{ label: string; color: string; count: number; pct: number }> = (() => {
        const explicit: CitationCategoryLike[] = currentCategoryData?.category_breakdown || [];
        if (explicit.length > 0) {
            return explicit.map((cat) => ({
                label: cat.label || cat.domain_category || "Other",
                color: getCategoryColor(cat.label || cat.domain_category),
                count: Number(cat.count || cat.citation_count || 0),
                pct: Number(cat.pct || 0),
            }));
        }
        const cats: Record<string, { label: string; color: string; count: number }> = {};
        for (const r of classifiedDomains) {
            const key = r.categoryLabel;
            if (!cats[key]) cats[key] = { label: key, color: r.categoryColor, count: 0 };
            cats[key].count += r.citation_count;
        }
        const total = Object.values(cats).reduce((s, c) => s + c.count, 0);
        return Object.values(cats).map(c => ({ ...c, pct: total > 0 ? Math.round(c.count / total * 10000) / 100 : 0 })).sort((a, b) => b.count - a.count);
    })();

    return (
        <div className="space-y-8">
            {/* ============== Section 1: Citation Share ============== */}
            <section>
                <SectionHeader
                    icon={<Link2 className="h-5 w-5 text-primary" />}
                    title={t("citations.sectionShare.title")}
                    subtitle={t("citations.sectionShare.subtitle")}
                />
                <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
                    <Card className="lg:col-span-2 shadow-none">
                        <CardHeader className="pb-2">
                            <div className="flex items-center gap-4">
                                <div>
                                    <div className="text-3xl font-bold flex items-center gap-2">
                                        <span className="gradient-text-static">{summary.own_domain_share ?? "—"}%</span>
                                        {summary.own_domain_share_change != null && summary.own_domain_share_change !== 0 && (
                                            <span className={`text-sm font-medium flex items-center gap-0.5 ${summary.own_domain_share_change > 0 ? "text-emerald-500" : "text-red-400"}`}>
                                                {summary.own_domain_share_change > 0 ? <TrendingUp className="h-3.5 w-3.5" /> : <TrendingDown className="h-3.5 w-3.5" />}
                                                {summary.own_domain_share_change > 0 ? "+" : ""}{summary.own_domain_share_change}%
                                            </span>
                                        )}
                                    </div>
                                    <div className="text-xs text-muted-foreground mt-0.5 flex items-center gap-1">
                                        {t("citations.sectionShare.yourShare")}
                                        <span className="relative group">
                                            <Info className="h-3 w-3 text-muted-foreground/50 cursor-help" />
                                            <span className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1.5 px-2.5 py-1.5 rounded-md bg-popover border text-popover-foreground text-[11px] leading-tight w-48 hidden group-hover:block shadow-md z-50">{t("citations.sectionShare.yourShareTooltip")}</span>
                                        </span>
                                    </div>
                                </div>
                                <div className="ml-auto text-right">
                                    <div className="text-lg font-semibold">{summary.total_citations ?? 0}</div>
                                    <div className="text-xs text-muted-foreground flex items-center gap-1 justify-end">
                                        {t("citations.sectionShare.totalCitations")}
                                        <span className="relative group">
                                            <Info className="h-3 w-3 text-muted-foreground/50 cursor-help" />
                                            <span className="absolute bottom-full right-0 mb-1.5 px-2.5 py-1.5 rounded-md bg-popover border text-popover-foreground text-[11px] leading-tight w-48 hidden group-hover:block shadow-md z-50">{t("citations.sectionShare.totalCitationsTooltip")}</span>
                                        </span>
                                    </div>
                                </div>
                            </div>
                        </CardHeader>
                        <CardContent>
                            {shareFailed ? (
                                <RetryableLoadError
                                    message={t("citations.loadFailed")}
                                    onRetry={() => setShareRetryVersion((value) => value + 1)}
                                />
                            ) : sharePending ? (
                                <div className="flex h-[260px] items-center justify-center">
                                    <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                                </div>
                            ) : timeSeries.length > 0 ? (
                                <>
                                    <ResponsiveContainer width="100%" height={260}>
                                        <LineChart data={timeSeries}>
                                            <XAxis dataKey="date" stroke="#888" fontSize={11} tickLine={false} axisLine={false} tickFormatter={fmtDate} />
                                            <YAxis stroke="#888" fontSize={11} tickLine={false} axisLine={false} unit="%" width={45} domain={[(dataMin: number) => Math.max(0, Math.floor(dataMin - 2)), (dataMax: number) => Math.ceil(dataMax + 2)]} />
                                            <Tooltip
                                                content={<GlassTooltip
                                                    formatter={(val: unknown, name: string) => [fmtPercentValue(val), name]}
                                                    labelFormatter={(v: unknown) => { const s = String(v); const d = s.includes("T") ? new Date(s) : new Date(s + "T00:00:00"); return d.toLocaleDateString(); }}
                                                />}
                                            />
                                            <Line type="monotone" dataKey="own_share" stroke="#10b981" strokeWidth={2.5} dot={{ r: 3, fill: "#10b981" }} activeDot={{ r: 5 }} name={t("visibility.chartLegend.current")} connectNulls={false} />
                                            {prevHasData && showPrevCitation && (
                                                <Line type="monotone" dataKey="prev_own_share" stroke="#10b981" strokeWidth={1.5} strokeDasharray="5 5" dot={false} opacity={0.35} name={t("visibility.chartLegend.previous")} connectNulls />
                                            )}
                                        </LineChart>
                                    </ResponsiveContainer>
                                    {prevHasData && (
                                        <div className="flex items-center gap-4 mt-2 ml-10">
                                            <label className="flex items-center gap-1.5 cursor-default select-none text-xs text-muted-foreground px-2 py-1 rounded-md">
                                                <span className="inline-flex items-center justify-center w-3.5 h-3.5 rounded-sm border border-emerald-500 bg-emerald-500"><Check className="w-2.5 h-2.5 text-white" /></span>
                                                {t("filters.currentPeriod")}
                                            </label>
                                            <label className="flex items-center gap-1.5 cursor-pointer select-none text-xs text-muted-foreground hover:bg-muted/50 px-2 py-1 rounded-md transition-colors" onClick={() => setShowPrevCitation(!showPrevCitation)}>
                                                <span className={"inline-flex items-center justify-center w-3.5 h-3.5 rounded-sm border transition-colors " + (showPrevCitation ? "border-gray-400 bg-gray-400" : "border-gray-300")}>{showPrevCitation && <Check className="w-2.5 h-2.5 text-white" />}</span>
                                                {t("filters.previousPeriod")}
                                            </label>
                                        </div>
                                    )}
                                </>
                            ) : (
                                <EmptyState message={t("citations.sectionShare.emptyState")} />
                            )}
                        </CardContent>
                    </Card>

                    {/* Domain Ranking Sidebar */}
                    <Card className="shadow-none">
                        <CardHeader className="pb-2">
                            <CardTitle className="text-sm font-medium flex items-center gap-2">
                                <Trophy className="h-4 w-4 text-amber-500" />
                                {t("citations.sectionShare.citationRank")}
                            </CardTitle>
                            <div className="text-2xl font-bold">
                                <span className="inline-flex items-center gap-2">
                                    <span>
                                        {summary.own_rank
                                            ? `#${summary.own_rank}`
                                            : "—"}
                                    </span>
                                    <RankChangeBadge change={summary.own_rank_change} />
                                </span>
                            </div>
                        </CardHeader>
                        <CardContent className="space-y-1.5">
                            <div className="text-[10px] text-muted-foreground uppercase tracking-wider mb-2 flex justify-between">
                                <span>{t("citations.sectionShare.columnDomain")}</span>
                                <div className="flex items-center gap-1" data-sort-list="citation-domain-ranking">
                                    <span>{t("citations.sectionDomains.columnHash")}</span>
                                    <SortableMetricHeader
                                        label={t("citations.sectionShare.columnShare")}
                                        metricKey="share_pct"
                                        sort={rankingSort}
                                        onChange={setRankingSort}
                                    />
                                </div>
                            </div>
                            {rankingFailed ? (
                                <RetryableLoadError
                                    message={t("citations.loadFailed")}
                                    onRetry={() => setRankingRetryVersion((value) => value + 1)}
                                    compact
                                />
                            ) : rankingPending ? (
                                <div className="flex items-center justify-center py-10">
                                    <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                                </div>
                            ) : domainRanking.slice(0, 5).map((r, i) => (
                                <div key={r.domain || i} className="flex items-center gap-2">
                                    <span className="text-xs text-muted-foreground w-5">{r.rank}.</span>
                                    <div className="flex-1 min-w-0">
                                        <div className="flex items-center gap-1.5">
                                            <span className={`text-sm truncate ${r.is_own ? "font-semibold text-blue-500" : ""}`}>
                                                {r.domain || "(unknown)"}
                                            </span>
                                            {r.is_own && <span className="text-[9px] bg-blue-500/10 text-blue-500 px-1 rounded">{t("citations.sectionShare.ownBadge")}</span>}
                                        </div>
                                        <div className="h-1 bg-muted rounded-full mt-0.5 overflow-hidden">
                                            <div className={`h-full rounded-full ${r.is_own ? "bg-blue-500" : "bg-muted-foreground/30"}`} style={{ width: `${Math.min(r.share_pct * 3, 100)}%` }} />
                                        </div>
                                    </div>
                                    <span className={`text-xs font-medium ${r.is_own ? "text-blue-500" : "text-muted-foreground"}`}>
                                        {r.share_pct}%
                                    </span>
                                </div>
                            ))}
                            {!rankingPending && !rankingFailed && domainRanking.length === 0 && <EmptyState message={t("citations.sectionShare.emptyDomains")} />}
                            {!rankingPending && !rankingFailed && domainRanking.length > 5 && (
                                <Button variant="ghost" size="sm" className="w-full mt-2 text-xs" onClick={() => setExpandRanking(true)}>
                                    <Expand className="h-3 w-3 mr-1" /> {t("citations.sectionShare.expand")}
                                </Button>
                            )}
                        </CardContent>
                    </Card>
                </div>
            </section>

            {/* ============== Section 2: Citation Categories ============== */}
            {(categoryPending || categoryFailed || categoryBreakdown.length > 0) && (
                <section>
                    <SectionHeader
                        icon={<Link2 className="h-5 w-5 text-primary" />}
                        title={t("citations.sectionCategories.title")}
                        subtitle={t("citations.sectionCategories.subtitle")}
                    />
                    <Card className="shadow-none">
                        <CardContent className="pt-6">
                            {categoryFailed ? (
                                <RetryableLoadError
                                    message={t("citations.loadFailed")}
                                    onRetry={() => setCategoryRetryVersion((value) => value + 1)}
                                    compact
                                />
                            ) : categoryPending ? (
                                <div className="flex h-20 items-center justify-center">
                                    <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                                </div>
                            ) : (
                                <>
                                    <div className="mb-3 flex justify-end gap-2" data-sort-list="citation-category-breakdown">
                                        <SortableMetricHeader
                                            label={t("citations.sectionDomains.columnCitations")}
                                            metricKey="count"
                                            sort={categorySort}
                                            onChange={setCategorySort}
                                        />
                                        <SortableMetricHeader
                                            label={t("citations.sectionDomains.columnShare")}
                                            metricKey="pct"
                                            sort={categorySort}
                                            onChange={setCategorySort}
                                        />
                                    </div>
                                    {/* Stacked horizontal bar */}
                                    <div className="flex h-8 rounded-md overflow-hidden mb-4 border">
                                        {categoryBreakdown.map((cat) => (
                                            <div
                                                key={cat.label}
                                                className="flex items-center justify-center text-xs font-medium text-white transition-all hover:opacity-80"
                                                style={{ width: `${cat.pct}%`, backgroundColor: cat.color, minWidth: cat.pct > 2 ? undefined : "20px" }}
                                                title={`${cat.label}: ${cat.pct}%`}
                                            >
                                                {cat.pct >= 5 ? `${cat.pct}%` : ""}
                                            </div>
                                        ))}
                                    </div>
                                    <div className="flex flex-wrap gap-4 justify-center">
                                        {categoryBreakdown.map(cat => (
                                            <div key={cat.label} className="flex items-center gap-1.5 text-sm">
                                                <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: cat.color }} />
                                                <span className="text-muted-foreground">{cat.label}</span>
                                                <span className="font-medium">{cat.count} · {cat.pct}%</span>
                                            </div>
                                        ))}
                                    </div>
                                </>
                            )}
                        </CardContent>
                    </Card>
                </section>
            )}

            {/* ============== Section 3: Most Cited Domains Table ============== */}
            {(domainPending || domainFailed || domainTotal > 0 || domainSearch) && (
                <section>
                    <SectionHeader
                        icon={<Link2 className="h-5 w-5 text-primary" />}
                        title={t("citations.sectionDomains.title")}
                        subtitle={t("citations.sectionDomains.subtitle")}
                    />
                    <Card className="shadow-none">
                        <CardHeader className="pb-2">
                            <div className="flex items-center gap-2">
                                <div className="relative flex-1 max-w-xs">
                                    <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                                    <Input
                                        placeholder={t("citations.sectionDomains.searchPlaceholder")}
                                        className="pl-8 h-8 text-sm"
                                        value={domainSearch}
                                        onChange={e => setDomainSearch(e.target.value)}
                                    />
                                </div>
                                <div className="text-xs text-muted-foreground">
                                    {t("citations.pagination.range", { start: domainStart, end: domainEnd, total: domainTotal })}
                                </div>
                            </div>
                        </CardHeader>
                        <CardContent className="p-0">
                            <div className="relative rounded-md border overflow-hidden">
                                {domainPending && domainRows.length > 0 && (
                                    <div className="absolute inset-0 z-10 flex items-center justify-center bg-background/55 backdrop-blur-[1px]">
                                        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                                    </div>
                                )}
                                <Table data-sort-list="citation-domains">
                                    <TableHeader>
                                        <TableRow className="bg-muted/20">
                                            <TableHead className="w-[70px]">{t("citations.sectionDomains.columnHash")}</TableHead>
                                            <TableHead>{t("citations.sectionDomains.columnDomain")}</TableHead>
                                            <TableHead>{t("citations.sectionDomains.columnCategory")}</TableHead>
                                            <TableHead className="text-right"><SortableMetricHeader label={t("citations.sectionDomains.columnCitations")} metricKey="citation_count" sort={domainSort} onChange={setDomainSort} /></TableHead>
                                            <TableHead className="text-right"><SortableMetricHeader label={t("citations.sectionDomains.columnShare")} metricKey="share_pct" sort={domainSort} onChange={setDomainSort} /></TableHead>
                                            <TableHead className="text-right"><SortableMetricHeader label={t("citations.sectionDomains.columnChange")} metricKey="change_pct" sort={domainSort} onChange={setDomainSort} /></TableHead>
                                        </TableRow>
                                    </TableHeader>
                                    <TableBody>
                                        {domainFailed && (
                                            <RetryableTableRow
                                                message={t("citations.loadFailed")}
                                                onRetry={() => setDomainRetryVersion((value) => value + 1)}
                                            />
                                        )}
                                        {!domainFailed && domainPending && domainRows.length === 0 && (
                                            <TableRow>
                                                <TableCell colSpan={6} className="py-8 text-center">
                                                    <Loader2 className="mx-auto h-5 w-5 animate-spin text-muted-foreground" />
                                                </TableCell>
                                            </TableRow>
                                        )}
                                        {!domainFailed && domainRows.map((r) => (
                                            <TableRow key={r.domain || r.rank} className={r.is_own ? "bg-blue-500/5" : ""}>
                                                <TableCell className="text-muted-foreground">{r.rank}</TableCell>
                                                <TableCell>
                                                    <div className="flex items-center gap-2">
                                                        <img
                                                            src={`https://www.google.com/s2/favicons?domain=${r.domain}&sz=16`}
                                                            alt="" className="w-4 h-4 rounded-sm"
                                                            onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
                                                        />
                                                        <span className={r.is_own ? "font-semibold text-blue-500" : ""}>{r.domain || "(unknown)"}</span>
                                                        {r.is_own && <span className="text-[9px] bg-blue-500/10 text-blue-500 px-1 rounded">{t("citations.sectionShare.ownBadge")}</span>}
                                                    </div>
                                                </TableCell>
                                                <TableCell>
                                                    <Badge variant="outline" className="text-[10px]" style={{ borderColor: r.categoryColor + "40", color: r.categoryColor }}>
                                                        {r.categoryLabel}
                                                    </Badge>
                                                </TableCell>
                                                <TableCell className="text-right">{r.citation_count}</TableCell>
                                                <TableCell className="text-right font-medium">{r.share_pct}%</TableCell>
                                                <TableCell className="text-right text-xs">
                                                    {r.change_pct != null && r.change_pct !== 0 ? (
                                                        <span className={r.change_pct > 0 ? "text-emerald-500" : "text-red-400"}>
                                                            {r.change_pct > 0 ? "+" : ""}{r.change_pct}%
                                                        </span>
                                                    ) : (
                                                        <span className="text-muted-foreground">—</span>
                                                    )}
                                                </TableCell>
                                            </TableRow>
                                        ))}
                                    </TableBody>
                                </Table>
                            </div>
                            <RankingPagination
                                loading={domainPending}
                                page={domainPage}
                                start={domainStart}
                                end={domainEnd}
                                total={domainTotal}
                                hasMore={domainHasMore}
                                totalIsLowerBound={false}
                                onPrev={() => setDomainPage(p => Math.max(0, p - 1))}
                                onNext={() => setDomainPage(p => p + 1)}
                                t={t}
                            />
                        </CardContent>
                    </Card>
                </section>
            )}

            {/* ============== Section 4: Most Cited Pages ============== */}
            {(pagePending || pageFailed || pageTotal > 0 || pageSearch) && (
                <section>
                    <SectionHeader
                        icon={<Link2 className="h-5 w-5 text-primary" />}
                        title={t("citations.sectionPages.title")}
                        subtitle={t("citations.sectionPages.subtitle")}
                    />
                    <Card className="shadow-none">
                        <CardHeader className="pb-2">
                            <div className="flex items-center gap-2">
                                <div className="relative flex-1 max-w-xs">
                                    <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                                    <Input
                                        placeholder={t("citations.sectionPages.searchPlaceholder")}
                                        className="pl-8 h-8 text-sm"
                                        value={pageSearch}
                                        onChange={e => setPageSearch(e.target.value)}
                                    />
                                </div>
                                <div className="text-xs text-muted-foreground">
                                    {t("citations.pagination.range", { start: pageStart, end: pageEnd, total: pageTotal })}
                                </div>
                            </div>
                        </CardHeader>
                        <CardContent className="p-0">
                            <div className="relative rounded-md border overflow-hidden">
                                {pagePending && pageRows.length > 0 && (
                                    <div className="absolute inset-0 z-10 flex items-center justify-center bg-background/55 backdrop-blur-[1px]">
                                        <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                                    </div>
                                )}
                                <Table data-sort-list="citation-pages">
                                    <TableHeader>
                                        <TableRow className="bg-muted/20">
                                            <TableHead className="w-[70px]">{t("citations.sectionDomains.columnHash")}</TableHead>
                                            <TableHead>{t("citations.sectionPages.columnPageUrl")}</TableHead>
                                            <TableHead>{t("citations.sectionDomains.columnCategory")}</TableHead>
                                            <TableHead className="text-right"><SortableMetricHeader label={t("citations.sectionDomains.columnCitations")} metricKey="citation_count" sort={pageSort} onChange={setPageSort} /></TableHead>
                                            <TableHead className="text-right"><SortableMetricHeader label={t("citations.sectionDomains.columnShare")} metricKey="share_pct" sort={pageSort} onChange={setPageSort} /></TableHead>
                                            <TableHead className="text-right"><SortableMetricHeader label={t("citations.sectionDomains.columnChange")} metricKey="change_pct" sort={pageSort} onChange={setPageSort} /></TableHead>
                                        </TableRow>
                                    </TableHeader>
                                    <TableBody>
                                        {pageFailed && (
                                            <RetryableTableRow
                                                message={t("citations.loadFailed")}
                                                onRetry={() => setPageRetryVersion((value) => value + 1)}
                                            />
                                        )}
                                        {!pageFailed && pagePending && pageRows.length === 0 && (
                                            <TableRow>
                                                <TableCell colSpan={6} className="py-8 text-center">
                                                    <Loader2 className="mx-auto h-5 w-5 animate-spin text-muted-foreground" />
                                                </TableCell>
                                            </TableRow>
                                        )}
                                        {!pageFailed && pageRows.map((r) => {
                                            const displayUrl = (r.url || "").replace(/^https?:\/\//, "").replace(/\/$/, "");
                                            const categoryColor = getCategoryColor(r.domain_category);
                                            return (
                                                <TableRow key={r.url || r.rank}>
                                                    <TableCell className="text-muted-foreground">{r.rank}</TableCell>
                                                    <TableCell>
                                                        <div className="flex items-center gap-2 min-w-0">
                                                            <img
                                                                src={`https://www.google.com/s2/favicons?domain=${r.domain}&sz=16`}
                                                                alt="" className="w-4 h-4 rounded-sm flex-shrink-0"
                                                                onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
                                                            />
                                                            <a
                                                                href={r.url || undefined}
                                                                target="_blank"
                                                                rel="noopener noreferrer"
                                                                className="text-sm text-blue-500 hover:underline truncate max-w-[400px]"
                                                                title={r.url || undefined}
                                                            >
                                                                {displayUrl.length > 60 ? displayUrl.slice(0, 60) + "…" : displayUrl}
                                                            </a>
                                                        </div>
                                                    </TableCell>
                                                    <TableCell>
                                                        <Badge variant="outline" className="text-[10px]" style={{ borderColor: categoryColor + "40", color: categoryColor }}>
                                                            {r.domain_category || "Other"}
                                                        </Badge>
                                                    </TableCell>
                                                    <TableCell className="text-right">{r.citation_count}</TableCell>
                                                    <TableCell className="text-right font-medium">{r.share_pct}%</TableCell>
                                                    <TableCell className="text-right text-xs">
                                                        {r.change_pct != null && r.change_pct !== 0 ? (
                                                            <span className={r.change_pct > 0 ? "text-emerald-500" : "text-red-400"}>
                                                                {r.change_pct > 0 ? "+" : ""}{r.change_pct}%
                                                            </span>
                                                        ) : (
                                                            <span className="text-muted-foreground">—</span>
                                                        )}
                                                    </TableCell>
                                                </TableRow>
                                            );
                                        })}
                                    </TableBody>
                                </Table>
                            </div>
                            <RankingPagination
                                loading={pagePending}
                                page={pagePage}
                                start={pageStart}
                                end={pageEnd}
                                total={pageTotal}
                                hasMore={pageHasMore}
                                totalIsLowerBound={false}
                                onPrev={() => setPagePage(p => Math.max(0, p - 1))}
                                onNext={() => setPagePage(p => p + 1)}
                                t={t}
                            />
                        </CardContent>
                    </Card>
                </section>
            )}

            {mode === "sidebar" && (
                <PublishedUrlTrackingSection
                    clientId={clientId}
                    dateFrom={debouncedFilters.dateFrom}
                    dateTo={debouncedFilters.dateTo}
                    selectedTopics={debouncedFilters.selectedTopics}
                    selectedPlatforms={debouncedFilters.selectedPlatforms}
                    selectedCountries={debouncedFilters.selectedCountries}
                    selectedPromptTypes={debouncedFilters.selectedPromptTypes}
                    products={debouncedFilters.products}
                    promptIds={debouncedFilters.promptIds}
                    filtersReady={filtersReady}
                    loadReady={pageSettledBaseKey === baseQueryKey}
                    t={t}
                />
            )}

            {/* ============== Expand Dialog ============== */}
            <Dialog open={expandRanking} onOpenChange={setExpandRanking}>
                <DialogContent className="max-w-lg max-h-[80vh] overflow-y-auto">
                    <DialogHeader>
                        <DialogTitle>{t("citations.fullDialog.title")}</DialogTitle>
                        <DialogDescription>{t("citations.fullDialog.description")}</DialogDescription>
                    </DialogHeader>
                    <div className="space-y-2 mt-2">
                        {domainRanking.map((r, i) => (
                            <div key={r.domain || i} className="flex items-center gap-2 py-1">
                                <span className="text-xs text-muted-foreground w-6">{r.rank}.</span>
                                <img
                                    src={`https://www.google.com/s2/favicons?domain=${r.domain}&sz=16`}
                                    alt="" className="w-4 h-4 rounded-sm"
                                    onError={(e) => { (e.target as HTMLImageElement).style.display = 'none'; }}
                                />
                                <span className={`text-sm flex-1 ${r.is_own ? "font-semibold text-blue-500" : ""}`}>
                                    {r.domain || "(unknown)"}
                                    {r.is_own && <span className="text-[9px] bg-blue-500/10 text-blue-500 px-1 ml-1 rounded">{t("citations.sectionShare.ownBadge")}</span>}
                                </span>
                                <span className="text-xs text-muted-foreground">{r.share_pct}%</span>
                            </div>
                        ))}
                    </div>
                </DialogContent>
            </Dialog>
        </div>
    );
}


// ============================================================================
// Reusable sub-components
// ============================================================================

function PublishedUrlTrackingSection({
    clientId,
    dateFrom,
    dateTo,
    selectedTopics,
    selectedPlatforms,
    selectedCountries,
    selectedPromptTypes,
    products,
    promptIds,
    filtersReady,
    loadReady,
    t,
}: {
    clientId?: string | null;
    dateFrom: string;
    dateTo: string;
    selectedTopics: string[];
    selectedPlatforms: string[];
    selectedCountries: string[];
    selectedPromptTypes: string[];
    products?: string[];
    promptIds?: string[];
    filtersReady: boolean;
    loadReady: boolean;
    t: CitationTranslation;
}) {
    const [rows, setRows] = useState<PublishedUrlTrackingRow[]>([]);
    const [total, setTotal] = useState(0);
    const [pageState, setPageState] = useState<CriteriaPageState>({ criteriaKey: "", page: 0 });
    const [loading, setLoading] = useState(false);
    const [detailOpen, setDetailOpen] = useState(false);
    const [detail, setDetail] = useState<PublishedUrlTrackingDetailOut | null>(null);
    const [selectedRow, setSelectedRow] = useState<PublishedUrlTrackingRow | null>(null);
    const [detailLoading, setDetailLoading] = useState(false);
    const [topicDetailLoading, setTopicDetailLoading] = useState(false);
    const [platformDetailLoading, setPlatformDetailLoading] = useState(false);
    const [countryDetailLoading, setCountryDetailLoading] = useState(false);
    const [promptDetailLoading, setPromptDetailLoading] = useState(false);
    const [responseDetailLoading, setResponseDetailLoading] = useState(false);
    const [variantOpen, setVariantOpen] = useState(false);
    const [variantRow, setVariantRow] = useState<PublishedUrlTrackingRow | null>(null);
    const [variants, setVariants] = useState<PublishedUrlVariantRow[]>([]);
    const [variantLoading, setVariantLoading] = useState(false);
    const [variantError, setVariantError] = useState(false);
    const [variantMutatingUrl, setVariantMutatingUrl] = useState<string | null>(null);
    const [trackingRefreshVersion, setTrackingRefreshVersion] = useState(0);
    const requestSeq = useRef(0);
    const detailRequestSeq = useRef(0);
    const variantRequestSeq = useRef(0);
    const detailLoadedRef = useRef(false);
    const detailBaseKeyRef = useRef("");
    const detailTopicKeyRef = useRef("");
    const detailPlatformKeyRef = useRef("");
    const detailCountryKeyRef = useRef("");
    const detailPromptKeyRef = useRef("");
    const detailResponseKeyRef = useRef("");
    const pageSize = 20;
    const detailPageSize = 10;
    const [promptPage, setPromptPage] = useState(0);
    const [responsePage, setResponsePage] = useState(0);
    const [promptTopic, setPromptTopic] = useState("all");
    const [promptPlatform, setPromptPlatform] = useState("all");
    const [promptCountry, setPromptCountry] = useState("all");
    const [responseTopic, setResponseTopic] = useState("all");
    const [responsePlatform, setResponsePlatform] = useState("all");
    const [responseCountry, setResponseCountry] = useState("all");
    const [trackingSort, setTrackingSort] = useState<MetricSortState>({ metricKey: "citation_count", direction: "desc" });
    const [detailPromptSort, setDetailPromptSort] = useState<MetricSortState>({ metricKey: "citation_count", direction: "desc" });
    const [detailTopicSort, setDetailTopicSort] = useState<MetricSortState>({ metricKey: "citation_count", direction: "desc" });
    const [detailPlatformSort, setDetailPlatformSort] = useState<MetricSortState>({ metricKey: "citation_count", direction: "desc" });
    const [detailCountrySort, setDetailCountrySort] = useState<MetricSortState>({ metricKey: "citation_count", direction: "desc" });
    const pageCriteriaKey = useMemo(() => JSON.stringify({
        dateFrom,
        dateTo,
        selectedTopics,
        selectedPlatforms,
        selectedCountries,
        selectedPromptTypes,
        products,
        promptIds,
        trackingSort,
    }), [dateFrom, dateTo, selectedTopics, selectedPlatforms, selectedCountries, selectedPromptTypes, products, promptIds, trackingSort]);
    const page = pageState.criteriaKey === pageCriteriaKey ? pageState.page : 0;
    const setPage = (next: PageUpdater) => {
        setPageState((current) => nextCriteriaPage(current, pageCriteriaKey, next));
    };

    useEffect(() => {
        if (!clientId || !filtersReady || !loadReady) return;
        const controller = new AbortController();
        const requestId = ++requestSeq.current;
        const params: Record<string, string> = {
            date_from: dateFrom,
            date_to: dateTo,
            limit: String(pageSize),
            offset: String(page * pageSize),
        };
        if (selectedTopics.length > 0) params.topic_ids = selectedTopics.join(",");
        if (selectedPlatforms.length > 0) params.platform = selectedPlatforms.join(",");
        if (selectedCountries.length > 0) params.country = selectedCountries.join(",");
        if (selectedPromptTypes.length > 0) params.prompt_type = selectedPromptTypes.join(",");
        applyMandatoryTarget(params, { products, promptIds });
        const startTimer = window.setTimeout(() => {
            setLoading(true);
            getPublishedUrlTracking(clientId, withMetricSortParams(params, trackingSort), { signal: controller.signal })
                .then((res) => {
                    if (requestId !== requestSeq.current) return;
                    setRows(res.items || []);
                    setTotal(res.total || 0);
                })
                .catch((err) => {
                    if (err?.name === "AbortError") return;
                    if (requestId === requestSeq.current) {
                        setRows([]);
                        setTotal(0);
                    }
                })
                .finally(() => {
                    if (requestId === requestSeq.current) setLoading(false);
                });
        }, REQUEST_START_DELAY_MS);
        return () => {
            window.clearTimeout(startTimer);
            controller.abort();
        };
    }, [clientId, filtersReady, loadReady, dateFrom, dateTo, selectedTopics, selectedPlatforms, selectedCountries, selectedPromptTypes, products, promptIds, page, trackingSort, trackingRefreshVersion]);

    const buildVariantParams = () => {
        const params: Record<string, string> = {
            date_from: dateFrom,
            date_to: dateTo,
        };
        if (selectedTopics.length > 0) params.topic_ids = selectedTopics.join(",");
        if (selectedPlatforms.length > 0) params.platform = selectedPlatforms.join(",");
        if (selectedCountries.length > 0) params.country = selectedCountries.join(",");
        if (selectedPromptTypes.length > 0) params.prompt_type = selectedPromptTypes.join(",");
        applyMandatoryTarget(params, { products, promptIds });
        return params;
    };

    const loadVariants = async (row: PublishedUrlTrackingRow) => {
        if (!clientId) return;
        const requestId = ++variantRequestSeq.current;
        setVariantLoading(true);
        setVariantError(false);
        try {
            const result = await getPublishedUrlTrackingVariants(
                clientId,
                row.published_url_id,
                buildVariantParams(),
            );
            if (requestId === variantRequestSeq.current) {
                setVariants(result.variants || []);
            }
        } catch {
            if (requestId === variantRequestSeq.current) {
                setVariants([]);
                setVariantError(true);
            }
        } finally {
            if (requestId === variantRequestSeq.current) {
                setVariantLoading(false);
            }
        }
    };

    const openVariants = (row: PublishedUrlTrackingRow) => {
        setVariantRow(row);
        setVariantOpen(true);
        setVariants([]);
        void loadVariants(row);
    };

    const updateVariantStatus = async (
        variant: PublishedUrlVariantRow,
        status: "confirmed" | "rejected",
    ) => {
        if (!clientId || !variantRow) return;
        setVariantMutatingUrl(variant.source_url);
        setVariantError(false);
        try {
            await setPublishedUrlCitationMatch(
                clientId,
                variantRow.published_url_id,
                variant.source_url,
                status,
            );
            await loadVariants(variantRow);
            setTrackingRefreshVersion((current) => current + 1);
        } catch {
            setVariantError(true);
        } finally {
            setVariantMutatingUrl(null);
        }
    };

    const openDetail = (row: PublishedUrlTrackingRow) => {
        if (!clientId) return;
        setDetailOpen(true);
        setDetail(null);
        setSelectedRow(row);
        setDetailLoading(false);
        setTopicDetailLoading(false);
        setPlatformDetailLoading(false);
        setCountryDetailLoading(false);
        setPromptDetailLoading(false);
        setResponseDetailLoading(false);
        detailLoadedRef.current = false;
        detailBaseKeyRef.current = "";
        detailTopicKeyRef.current = "";
        detailPlatformKeyRef.current = "";
        detailCountryKeyRef.current = "";
        detailPromptKeyRef.current = "";
        detailResponseKeyRef.current = "";
        setPromptPage(0);
        setResponsePage(0);
        setPromptTopic("all");
        setPromptPlatform("all");
        setPromptCountry("all");
        setResponseTopic("all");
        setResponsePlatform("all");
        setResponseCountry("all");
    };

    useEffect(() => {
        if (!clientId || !detailOpen || !selectedRow) return;
        const controller = new AbortController();
        const requestId = ++detailRequestSeq.current;
        const baseKey = JSON.stringify({
            clientId,
            publishedUrlId: selectedRow.published_url_id,
            dateFrom,
            dateTo,
            selectedTopics,
            selectedPlatforms,
            selectedCountries,
            selectedPromptTypes,
            products,
            promptIds,
        });
        const topicKey = `${baseKey}|topic:${detailTopicSort.metricKey}:${detailTopicSort.direction}`;
        const platformKey = `${baseKey}|platform:${detailPlatformSort.metricKey}:${detailPlatformSort.direction}`;
        const countryKey = `${baseKey}|country:${detailCountrySort.metricKey}:${detailCountrySort.direction}`;
        const promptKey = `${baseKey}|prompt:${promptPage}:${promptTopic}:${promptPlatform}:${promptCountry}:${detailPromptSort.metricKey}:${detailPromptSort.direction}`;
        const responseKey = `${baseKey}|response:${responsePage}:${responseTopic}:${responsePlatform}:${responseCountry}`;
        const isInitialLoad = !detailLoadedRef.current || detailBaseKeyRef.current !== baseKey;
        const topicChanged = !isInitialLoad && detailTopicKeyRef.current !== topicKey;
        const platformChanged = !isInitialLoad && detailPlatformKeyRef.current !== platformKey;
        const countryChanged = !isInitialLoad && detailCountryKeyRef.current !== countryKey;
        const promptChanged = !isInitialLoad && detailPromptKeyRef.current !== promptKey;
        const responseChanged = !isInitialLoad && detailResponseKeyRef.current !== responseKey;
        const params: Record<string, string> = {
            date_from: dateFrom,
            date_to: dateTo,
            prompt_limit: String(detailPageSize),
            prompt_offset: String(promptPage * detailPageSize),
            response_limit: String(detailPageSize),
            response_offset: String(responsePage * detailPageSize),
        };
        if (selectedTopics.length > 0) params.topic_ids = selectedTopics.join(",");
        if (selectedPlatforms.length > 0) params.platform = selectedPlatforms.join(",");
        if (selectedCountries.length > 0) params.country = selectedCountries.join(",");
        if (selectedPromptTypes.length > 0) params.prompt_type = selectedPromptTypes.join(",");
        applyMandatoryTarget(params, { products, promptIds });
        if (promptTopic !== "all") params.prompt_topic_id = promptTopic;
        if (promptPlatform !== "all") params.prompt_platform = promptPlatform;
        if (promptCountry !== "all") params.prompt_country = promptCountry;
        if (responseTopic !== "all") params.response_topic_id = responseTopic;
        if (responsePlatform !== "all") params.response_platform = responsePlatform;
        if (responseCountry !== "all") params.response_country = responseCountry;
        Object.assign(params, withMetricSortParams({}, detailPromptSort, "prompt_"));
        Object.assign(params, withMetricSortParams({}, detailTopicSort, "topic_"));
        Object.assign(params, withMetricSortParams({}, detailPlatformSort, "platform_"));
        Object.assign(params, withMetricSortParams({}, detailCountrySort, "country_"));
        const startTimer = window.setTimeout(() => {
            if (isInitialLoad) {
                setDetailLoading(true);
            } else {
                if (topicChanged) setTopicDetailLoading(true);
                if (platformChanged) setPlatformDetailLoading(true);
                if (countryChanged) setCountryDetailLoading(true);
                if (promptChanged) setPromptDetailLoading(true);
                if (responseChanged) setResponseDetailLoading(true);
            }
            getPublishedUrlTrackingDetail(clientId, selectedRow.published_url_id, params, { signal: controller.signal })
                .then((res) => {
                    if (requestId === detailRequestSeq.current) {
                        setDetail((current) => {
                            if (isInitialLoad || !current) return res;
                            return {
                                ...current,
                                ...(topicChanged ? { topics: res.topics } : {}),
                                ...(platformChanged ? { platforms: res.platforms } : {}),
                                ...(countryChanged ? { countries: res.countries } : {}),
                                ...(promptChanged ? {
                                    prompts: res.prompts,
                                    prompts_total: res.prompts_total,
                                    prompt_limit: res.prompt_limit,
                                    prompt_offset: res.prompt_offset,
                                } : {}),
                                ...(responseChanged ? {
                                    responses: res.responses,
                                    responses_total: res.responses_total,
                                    response_limit: res.response_limit,
                                    response_offset: res.response_offset,
                                } : {}),
                            };
                        });
                        detailLoadedRef.current = true;
                        detailBaseKeyRef.current = baseKey;
                        detailTopicKeyRef.current = topicKey;
                        detailPlatformKeyRef.current = platformKey;
                        detailCountryKeyRef.current = countryKey;
                        detailPromptKeyRef.current = promptKey;
                        detailResponseKeyRef.current = responseKey;
                    }
                })
                .catch((err) => {
                    if (err?.name !== "AbortError" && requestId === detailRequestSeq.current && isInitialLoad) setDetail(null);
                })
                .finally(() => {
                    if (requestId === detailRequestSeq.current) {
                        setDetailLoading(false);
                        setTopicDetailLoading(false);
                        setPlatformDetailLoading(false);
                        setCountryDetailLoading(false);
                        setPromptDetailLoading(false);
                        setResponseDetailLoading(false);
                    }
                });
        }, 0);
        return () => {
            window.clearTimeout(startTimer);
            controller.abort();
        };
    }, [
        clientId,
        detailOpen,
        selectedRow,
        dateFrom,
        dateTo,
        selectedTopics,
        selectedPlatforms,
        selectedCountries,
        selectedPromptTypes,
        products,
        promptIds,
        promptPage,
        responsePage,
        promptTopic,
        promptPlatform,
        promptCountry,
        responseTopic,
        responsePlatform,
        responseCountry,
        detailPromptSort,
        detailTopicSort,
        detailPlatformSort,
        detailCountrySort,
    ]);

    const start = total > 0 ? page * pageSize + 1 : 0;
    const end = Math.min((page + 1) * pageSize, total);

    return (
        <section>
            <SectionHeader
                icon={<Link2 className="h-5 w-5 text-primary" />}
                title={t("publishedTracking.title")}
                subtitle={t("publishedTracking.subtitle")}
                tooltip={t("publishedTracking.tooltip")}
            />
            <Card className="shadow-none">
                <CardContent className="p-0">
                    <div className="rounded-md border overflow-hidden">
                        <Table data-sort-list="published-url-tracking">
                            <TableHeader>
                                <TableRow className="bg-muted/20">
                                    <TableHead className="w-[80px]">{t("publishedTracking.table.rank")}</TableHead>
                                    <TableHead>{t("publishedTracking.table.page")}</TableHead>
                                    <TableHead>{t("publishedTracking.table.channel")}</TableHead>
                                    <TableHead>{t("publishedTracking.table.category")}</TableHead>
                                    <TableHead className="text-right"><SortableMetricHeader label={t("publishedTracking.table.citations")} metricKey="citation_count" sort={trackingSort} onChange={setTrackingSort} /></TableHead>
                                    <TableHead className="text-right"><SortableMetricHeader label={t("publishedTracking.table.share")} metricKey="share_pct" sort={trackingSort} onChange={setTrackingSort} /></TableHead>
                                    <TableHead className="text-right"><SortableMetricHeader label={t("publishedTracking.table.change")} metricKey="change_count" sort={trackingSort} onChange={setTrackingSort} /></TableHead>
                                    <TableHead>{t("publishedTracking.table.latest")}</TableHead>
                                    <TableHead className="text-right">{t("publishedTracking.table.actions")}</TableHead>
                                </TableRow>
                            </TableHeader>
                            <TableBody>
                                {loading ? (
                                    <TableRow>
                                        <TableCell colSpan={9} className="h-28 text-center">
                                            <Loader2 className="mx-auto h-5 w-5 animate-spin text-muted-foreground" />
                                        </TableCell>
                                    </TableRow>
                                ) : rows.length === 0 ? (
                                    <TableRow>
                                        <TableCell colSpan={9} className="h-28 text-center text-sm text-muted-foreground">
                                            {t("publishedTracking.empty")}
                                        </TableCell>
                                    </TableRow>
                                ) : rows.map((row) => {
                                    const change = row.change_count;
                                    return (
                                        <TableRow key={row.published_url_id}>
                                            <TableCell className="text-muted-foreground">{row.rank ?? "—"}</TableCell>
                                            <TableCell>
                                                <div className="max-w-[420px]">
                                                    <div className="font-medium">{row.title}</div>
                                                    <a
                                                        href={row.published_url}
                                                        target="_blank"
                                                        rel="noopener noreferrer"
                                                        className="line-clamp-1 text-xs text-blue-500 hover:underline"
                                                    >
                                                        {row.normalized_url}
                                                    </a>
                                                    <div className="mt-1 flex flex-wrap gap-1">
                                                        {(row.triggered_topics || []).slice(0, 4).map((topic) => (
                                                            <Badge key={`triggered-${topic.id}`} variant="outline" className="border-primary/30 text-[10px] text-primary">
                                                                {t("publishedTracking.triggeredTopicBadge", { topic: topic.topic_name })}
                                                            </Badge>
                                                        ))}
                                                        {(row.topics || []).map((topic) => (
                                                            <Badge key={`managed-${topic.id}`} variant="secondary" className="text-[10px]">
                                                                {t("publishedTracking.managedTopicBadge", { topic: topic.topic_name })}
                                                            </Badge>
                                                        ))}
                                                    </div>
                                                </div>
                                            </TableCell>
                                            <TableCell>{row.channel}</TableCell>
                                            <TableCell>
                                                <Badge variant="outline" className="text-[10px]">
                                                    {row.citation_category || t("publishedTracking.unknownCategory")}
                                                </Badge>
                                            </TableCell>
                                            <TableCell className="text-right">{row.citation_count}</TableCell>
                                            <TableCell className="text-right">{fmtPercentValue(row.share_pct)}</TableCell>
                                            <TableCell className="text-right text-xs">
                                                {change ? (
                                                    <span className={change > 0 ? "text-emerald-500" : "text-red-400"}>
                                                        {change > 0 ? "+" : ""}{change}
                                                    </span>
                                                ) : <span className="text-muted-foreground">—</span>}
                                            </TableCell>
                                            <TableCell className="text-xs text-muted-foreground">
                                                {row.last_cited_at ? new Date(row.last_cited_at).toLocaleString() : "—"}
                                            </TableCell>
                                            <TableCell className="text-right">
                                                <div className="flex items-center justify-end gap-1">
                                                    <Button
                                                        variant="outline"
                                                        size="sm"
                                                        className={row.candidate_count > 0
                                                            ? "border-emerald-500/60 bg-emerald-500/15 text-emerald-400 shadow-sm shadow-emerald-500/10 hover:bg-emerald-500/25 hover:text-emerald-300"
                                                            : "border-border/70 bg-background/40 hover:bg-muted/70"}
                                                        onClick={() => openVariants(row)}
                                                    >
                                                        {row.candidate_count > 0
                                                            ? t("publishedTracking.variants.pendingCount", { count: row.candidate_count })
                                                            : t("publishedTracking.variants.button")}
                                                    </Button>
                                                    <Button variant="ghost" size="sm" onClick={() => openDetail(row)}>
                                                        {t("publishedTracking.actions.detail")}
                                                    </Button>
                                                </div>
                                            </TableCell>
                                        </TableRow>
                                    );
                                })}
                            </TableBody>
                        </Table>
                    </div>
                    <RankingPagination
                        loading={loading}
                        page={page}
                        start={start}
                        end={end}
                        total={total}
                        hasMore={end < total}
                        onPrev={() => setPage((prev) => Math.max(0, prev - 1))}
                        onNext={() => setPage((prev) => prev + 1)}
                        t={t}
                    />
                </CardContent>
            </Card>
            <Dialog open={variantOpen} onOpenChange={setVariantOpen}>
                <DialogContent className="max-w-3xl">
                    <DialogHeader>
                        <DialogTitle>{t("publishedTracking.variants.title")}</DialogTitle>
                        <DialogDescription>
                            {variantRow?.title ? `${variantRow.title} · ` : ""}
                            {t("publishedTracking.variants.description")}
                        </DialogDescription>
                    </DialogHeader>
                    {variantLoading ? (
                        <div className="flex h-32 items-center justify-center">
                            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                        </div>
                    ) : variantError && variants.length === 0 ? (
                        <div className="py-8 text-center text-sm text-destructive">
                            {t("publishedTracking.variants.loadFailed")}
                        </div>
                    ) : variants.length === 0 ? (
                        <div className="py-8 text-center text-sm text-muted-foreground">
                            {t("publishedTracking.variants.empty")}
                        </div>
                    ) : (
                        <div className="max-h-[60vh] space-y-3 overflow-y-auto pr-1">
                            {variants.map((variant) => {
                                const mutating = variantMutatingUrl === variant.source_url;
                                return (
                                    <div key={variant.source_url} className="rounded-lg border p-3">
                                        <div className="flex items-start justify-between gap-3">
                                            <div className="min-w-0 flex-1">
                                                <div className="mb-2 flex flex-wrap items-center gap-2">
                                                    <Badge variant={variant.status === "pending" ? "default" : "outline"}>
                                                        {t(`publishedTracking.variants.${variant.status}`)}
                                                    </Badge>
                                                    <span className="text-xs text-muted-foreground">
                                                        {t("publishedTracking.variants.citations", { count: variant.citation_count })}
                                                    </span>
                                                </div>
                                                <a
                                                    href={variant.source_url}
                                                    target="_blank"
                                                    rel="noopener noreferrer"
                                                    className="block break-all text-sm text-blue-500 hover:underline"
                                                >
                                                    {variant.source_url}
                                                </a>
                                                <div className="mt-1 break-all text-[11px] text-muted-foreground">
                                                    {t("publishedTracking.variants.matchKey", { value: variant.match_key })}
                                                </div>
                                            </div>
                                            {(variant.status === "pending" || variant.status === "confirmed" || variant.status === "rejected") && (
                                                <div className="flex shrink-0 items-center gap-2">
                                                    {variant.status !== "confirmed" && (
                                                        <Button
                                                            size="sm"
                                                            disabled={mutating}
                                                            onClick={() => void updateVariantStatus(variant, "confirmed")}
                                                        >
                                                            {mutating && <Loader2 className="mr-1 h-3.5 w-3.5 animate-spin" />}
                                                            {t(variant.status === "rejected"
                                                                ? "publishedTracking.variants.restore"
                                                                : "publishedTracking.variants.confirm")}
                                                        </Button>
                                                    )}
                                                    {variant.status !== "rejected" && (
                                                        <Button
                                                            variant="outline"
                                                            size="sm"
                                                            disabled={mutating}
                                                            onClick={() => void updateVariantStatus(variant, "rejected")}
                                                        >
                                                            {t("publishedTracking.variants.reject")}
                                                        </Button>
                                                    )}
                                                </div>
                                            )}
                                        </div>
                                    </div>
                                );
                            })}
                            {variantError && (
                                <div className="text-sm text-destructive">
                                    {t("publishedTracking.variants.updateFailed")}
                                </div>
                            )}
                        </div>
                    )}
                </DialogContent>
            </Dialog>
            <Sheet open={detailOpen} onOpenChange={setDetailOpen}>
                <SheetContent side="right" className="w-full overflow-y-auto sm:max-w-3xl">
                    <SheetHeader>
                        <SheetTitle>{detail?.title || selectedRow?.title || t("publishedTracking.detail.title")}</SheetTitle>
                        <SheetDescription>
                            {detail?.normalized_url || selectedRow?.normalized_url || t("publishedTracking.detail.description")}
                        </SheetDescription>
                    </SheetHeader>
                    {detailLoading ? (
                        <div className="flex h-48 items-center justify-center">
                            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                        </div>
                    ) : detail ? (
                        <div className="mt-6 space-y-6">
                            <div className="grid gap-3 md:grid-cols-4">
                                <MetricBox label={t("publishedTracking.detail.citations")} value={selectedRow?.citation_count ?? "—"} />
                                <MetricBox label={t("publishedTracking.detail.share")} value={fmtPercentValue(selectedRow?.share_pct)} />
                                <MetricBox label={t("publishedTracking.detail.rank")} value={selectedRow?.rank ?? "—"} />
                                <MetricBox label={t("publishedTracking.detail.latest")} value={selectedRow?.last_cited_at ? fmtDate(selectedRow.last_cited_at) : "—"} />
                            </div>
                            <DetailBlock
                                title={t("publishedTracking.detail.topics")}
                                headerAction={<span data-sort-list="published-url-detail-topics"><SortableMetricHeader label={t("publishedTracking.detail.citations")} metricKey="citation_count" sort={detailTopicSort} onChange={setDetailTopicSort} /></span>}
                            >
                                {topicDetailLoading && (
                                    <div className="mb-2 flex items-center gap-2 text-xs text-muted-foreground">
                                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                        <span>{t("common:states.loading")}</span>
                                    </div>
                                )}
                                <div className={`flex flex-wrap gap-2 ${topicDetailLoading ? "opacity-60" : ""}`}>
                                    {detail.topics.map((item) => (
                                        <Badge key={item.id} variant="secondary">{item.topic_name}: {item.citation_count}</Badge>
                                    ))}
                                    {detail.topics.length === 0 && <span className="text-sm text-muted-foreground">—</span>}
                                </div>
                            </DetailBlock>
                            <DetailBlock
                                title={t("publishedTracking.detail.platforms")}
                                headerAction={<span data-sort-list="published-url-detail-platforms"><SortableMetricHeader label={t("publishedTracking.detail.citations")} metricKey="citation_count" sort={detailPlatformSort} onChange={setDetailPlatformSort} /></span>}
                            >
                                {platformDetailLoading && (
                                    <div className="mb-2 flex items-center gap-2 text-xs text-muted-foreground">
                                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                        <span>{t("common:states.loading")}</span>
                                    </div>
                                )}
                                <div className={`flex flex-wrap gap-2 ${platformDetailLoading ? "opacity-60" : ""}`}>
                                    {detail.platforms.map((item) => (
                                        <Badge key={item.platform} variant="secondary">{item.platform}: {item.citation_count}</Badge>
                                    ))}
                                    {detail.platforms.length === 0 && <span className="text-sm text-muted-foreground">—</span>}
                                </div>
                            </DetailBlock>
                            <DetailBlock
                                title={t("publishedTracking.detail.countries")}
                                headerAction={<span data-sort-list="published-url-detail-countries"><SortableMetricHeader label={t("publishedTracking.detail.citations")} metricKey="citation_count" sort={detailCountrySort} onChange={setDetailCountrySort} /></span>}
                            >
                                {countryDetailLoading && (
                                    <div className="mb-2 flex items-center gap-2 text-xs text-muted-foreground">
                                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                        <span>{t("common:states.loading")}</span>
                                    </div>
                                )}
                                <div className={`flex flex-wrap gap-2 ${countryDetailLoading ? "opacity-60" : ""}`}>
                                    {detail.countries.map((item) => (
                                        <Badge key={item.country} variant="secondary">{item.country}: {item.citation_count}</Badge>
                                    ))}
                                    {detail.countries.length === 0 && <span className="text-sm text-muted-foreground">—</span>}
                                </div>
                            </DetailBlock>
                            <DetailBlock
                                title={t("publishedTracking.detail.prompts")}
                                headerAction={(
                                    <span data-sort-list="published-url-detail-prompts">
                                        <SortableMetricHeader
                                            label={t("publishedTracking.detail.citations")}
                                            metricKey="citation_count"
                                            sort={detailPromptSort}
                                            onChange={(next) => { setPromptPage(0); setDetailPromptSort(next); }}
                                        />
                                    </span>
                                )}
                            >
                                <div className="mb-3 grid gap-2 md:grid-cols-3">
                                    <Select
                                        value={promptTopic}
                                        onValueChange={(value) => {
                                            setPromptTopic(value);
                                            setPromptPage(0);
                                        }}
                                    >
                                        <SelectTrigger>
                                            <SelectValue placeholder={t("publishedTracking.detail.topicFilter")} />
                                        </SelectTrigger>
                                        <SelectContent>
                                            <SelectItem value="all">{t("publishedTracking.detail.allTopics")}</SelectItem>
                                            {detail.topics.map((item) => (
                                                <SelectItem key={item.id} value={item.id}>{item.topic_name}</SelectItem>
                                            ))}
                                        </SelectContent>
                                    </Select>
                                    <Select
                                        value={promptPlatform}
                                        onValueChange={(value) => {
                                            setPromptPlatform(value);
                                            setPromptPage(0);
                                        }}
                                    >
                                        <SelectTrigger>
                                            <SelectValue placeholder={t("publishedTracking.detail.platformFilter")} />
                                        </SelectTrigger>
                                        <SelectContent>
                                            <SelectItem value="all">{t("publishedTracking.detail.allPlatforms")}</SelectItem>
                                            {detail.platforms.map((item) => (
                                                <SelectItem key={item.platform} value={item.platform}>{item.platform}</SelectItem>
                                            ))}
                                        </SelectContent>
                                    </Select>
                                    <Select
                                        value={promptCountry}
                                        onValueChange={(value) => {
                                            setPromptCountry(value);
                                            setPromptPage(0);
                                        }}
                                    >
                                        <SelectTrigger>
                                            <SelectValue placeholder={t("publishedTracking.detail.countryFilter")} />
                                        </SelectTrigger>
                                        <SelectContent>
                                            <SelectItem value="all">{t("publishedTracking.detail.allCountries")}</SelectItem>
                                            {detail.countries.map((item) => (
                                                <SelectItem key={item.country} value={item.country}>{item.country}</SelectItem>
                                            ))}
                                        </SelectContent>
                                    </Select>
                                </div>
                                {promptDetailLoading && (
                                    <div className="mb-2 flex items-center gap-2 text-xs text-muted-foreground">
                                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                        <span>{t("common:states.loading")}</span>
                                    </div>
                                )}
                                <div className={`space-y-2 ${promptDetailLoading ? "opacity-60" : ""}`}>
                                    {detail.prompts.map((item) => (
                                        <div key={item.client_prompt_id} className="rounded-md border p-3 text-sm">
                                            <div>{item.client_prompt_text}</div>
                                            <div className="mt-2 flex flex-wrap gap-1">
                                                {item.topic_name && <Badge variant="secondary" className="text-[10px]">{item.topic_name}</Badge>}
                                                {(item.platforms || []).map((value) => (
                                                    <Badge key={`platform-${item.client_prompt_id}-${value}`} variant="outline" className="text-[10px]">{value}</Badge>
                                                ))}
                                                {(item.countries || []).map((value) => (
                                                    <Badge key={`country-${item.client_prompt_id}-${value}`} variant="outline" className="text-[10px]">{value}</Badge>
                                                ))}
                                            </div>
                                            <div className="mt-1 text-xs text-muted-foreground">
                                                {t("publishedTracking.detail.promptCitations", { count: item.citation_count })}
                                            </div>
                                        </div>
                                    ))}
                                    {detail.prompts.length === 0 && <span className="text-sm text-muted-foreground">—</span>}
                                </div>
                                <RankingPagination
                                    loading={promptDetailLoading}
                                    page={promptPage}
                                    start={detail.prompts_total > 0 ? promptPage * detailPageSize + 1 : 0}
                                    end={Math.min((promptPage + 1) * detailPageSize, detail.prompts_total)}
                                    total={detail.prompts_total}
                                    hasMore={(promptPage + 1) * detailPageSize < detail.prompts_total}
                                    onPrev={() => setPromptPage((prev) => Math.max(0, prev - 1))}
                                    onNext={() => setPromptPage((prev) => prev + 1)}
                                    t={t}
                                />
                            </DetailBlock>
                            <DetailBlock title={t("publishedTracking.detail.responses")}>
                                <div className="mb-3 grid gap-2 md:grid-cols-3">
                                    <Select
                                        value={responseTopic}
                                        onValueChange={(value) => {
                                            setResponseTopic(value);
                                            setResponsePage(0);
                                        }}
                                    >
                                        <SelectTrigger>
                                            <SelectValue placeholder={t("publishedTracking.detail.topicFilter")} />
                                        </SelectTrigger>
                                        <SelectContent>
                                            <SelectItem value="all">{t("publishedTracking.detail.allTopics")}</SelectItem>
                                            {detail.topics.map((item) => (
                                                <SelectItem key={item.id} value={item.id}>{item.topic_name}</SelectItem>
                                            ))}
                                        </SelectContent>
                                    </Select>
                                    <Select
                                        value={responsePlatform}
                                        onValueChange={(value) => {
                                            setResponsePlatform(value);
                                            setResponsePage(0);
                                        }}
                                    >
                                        <SelectTrigger>
                                            <SelectValue placeholder={t("publishedTracking.detail.platformFilter")} />
                                        </SelectTrigger>
                                        <SelectContent>
                                            <SelectItem value="all">{t("publishedTracking.detail.allPlatforms")}</SelectItem>
                                            {detail.platforms.map((item) => (
                                                <SelectItem key={item.platform} value={item.platform}>{item.platform}</SelectItem>
                                            ))}
                                        </SelectContent>
                                    </Select>
                                    <Select
                                        value={responseCountry}
                                        onValueChange={(value) => {
                                            setResponseCountry(value);
                                            setResponsePage(0);
                                        }}
                                    >
                                        <SelectTrigger>
                                            <SelectValue placeholder={t("publishedTracking.detail.countryFilter")} />
                                        </SelectTrigger>
                                        <SelectContent>
                                            <SelectItem value="all">{t("publishedTracking.detail.allCountries")}</SelectItem>
                                            {detail.countries.map((item) => (
                                                <SelectItem key={item.country} value={item.country}>{item.country}</SelectItem>
                                            ))}
                                        </SelectContent>
                                    </Select>
                                </div>
                                {responseDetailLoading && (
                                    <div className="mb-2 flex items-center gap-2 text-xs text-muted-foreground">
                                        <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                        <span>{t("common:states.loading")}</span>
                                    </div>
                                )}
                                <div className={`space-y-3 ${responseDetailLoading ? "opacity-60" : ""}`}>
                                    {detail.responses.map((citation) => (
                                        <div key={`${citation.result_id}-${citation.source_position ?? "source"}`} className="rounded-lg border p-3">
                                            <div className="mb-2 flex flex-wrap items-center gap-2 text-xs text-muted-foreground">
                                                <Badge variant="outline">{citation.platform || "—"}</Badge>
                                                <Badge variant="outline">{citation.country || "—"}</Badge>
                                                <span>{citation.executed_at ? new Date(citation.executed_at).toLocaleString() : "—"}</span>
                                            </div>
                                            <div className="mb-2 text-sm font-medium">{citation.client_prompt_text || "—"}</div>
                                            <p className="line-clamp-5 whitespace-pre-wrap text-sm text-muted-foreground">
                                                {citation.response_excerpt || "—"}
                                            </p>
                                        </div>
                                    ))}
                                    {detail.responses.length === 0 && <span className="text-sm text-muted-foreground">—</span>}
                                </div>
                                <RankingPagination
                                    loading={responseDetailLoading}
                                    page={responsePage}
                                    start={detail.responses_total > 0 ? responsePage * detailPageSize + 1 : 0}
                                    end={Math.min((responsePage + 1) * detailPageSize, detail.responses_total)}
                                    total={detail.responses_total}
                                    hasMore={(responsePage + 1) * detailPageSize < detail.responses_total}
                                    onPrev={() => setResponsePage((prev) => Math.max(0, prev - 1))}
                                    onNext={() => setResponsePage((prev) => prev + 1)}
                                    t={t}
                                />
                            </DetailBlock>
                        </div>
                    ) : (
                        <div className="mt-6 text-sm text-muted-foreground">{t("publishedTracking.detail.empty")}</div>
                    )}
                </SheetContent>
            </Sheet>
        </section>
    );
}

function MetricBox({ label, value }: { label: string; value: React.ReactNode }) {
    return (
        <div className="rounded-lg border p-3">
            <div className="text-xs text-muted-foreground">{label}</div>
            <div className="mt-1 text-lg font-semibold">{value}</div>
        </div>
    );
}

function DetailBlock({ title, children, headerAction }: { title: string; children: React.ReactNode; headerAction?: React.ReactNode }) {
    return (
        <div>
            <div className="mb-2 flex items-center justify-between gap-3">
                <h3 className="text-sm font-semibold">{title}</h3>
                {headerAction}
            </div>
            {children}
        </div>
    );
}

function SectionHeader({ icon, title, subtitle, tooltip }: { icon: React.ReactNode; title: string; subtitle: string; tooltip?: string }) {
    return (
        <div className="mb-5">
            <h2 className="text-lg font-semibold flex items-center gap-2">
                {icon}
                {title}
                {tooltip ? <HelpTooltip content={tooltip} side="right" /> : null}
            </h2>
            <p className="text-sm text-muted-foreground mt-0.5">{subtitle}</p>
            <div className="mt-3 h-px bg-gradient-to-r from-primary/20 via-primary/5 to-transparent" />
        </div>
    );
}

function EmptyState({ message }: { message: string }) {
    return (
        <div className="flex flex-col items-center justify-center h-48 text-muted-foreground rounded-lg border border-dashed border-primary/20 bg-primary/[0.02]">
            <div className="h-12 w-12 rounded-full bg-primary/[0.06] border border-primary/10 mb-4 flex items-center justify-center">
                <Link2 className="h-5 w-5 text-primary/40" />
            </div>
            <p className="text-sm">{message}</p>
        </div>
    );
}

function RetryableLoadError({
    message,
    onRetry,
    compact = false,
}: {
    message: string;
    onRetry: () => void;
    compact?: boolean;
}) {
    const { t } = useTranslation("common");
    return (
        <div className={`flex flex-col items-center justify-center gap-3 text-center text-sm text-muted-foreground ${compact ? "py-8" : "h-[260px]"}`}>
            <span>{message}</span>
            <Button variant="outline" size="sm" onClick={onRetry}>{t("actions.retry")}</Button>
        </div>
    );
}

function RetryableTableRow({ message, onRetry }: { message: string; onRetry: () => void }) {
    const { t } = useTranslation("common");
    return (
        <TableRow>
            <TableCell colSpan={6} className="py-8 text-center">
                <div className="flex flex-col items-center gap-3 text-sm text-muted-foreground">
                    <span>{message}</span>
                    <Button variant="outline" size="sm" onClick={onRetry}>{t("actions.retry")}</Button>
                </div>
            </TableCell>
        </TableRow>
    );
}

function RankChangeBadge({ change }: { change?: number | null }) {
    if (change == null || change === 0) return null;
    const improved = change < 0;
    return (
        <span className={`text-sm font-medium flex items-center gap-0.5 ${improved ? "text-emerald-500" : "text-red-400"}`}>
            {improved ? <TrendingUp className="h-3.5 w-3.5" /> : <TrendingDown className="h-3.5 w-3.5" />}
            {improved ? "↑" : "↓"}{Math.abs(change)}
        </span>
    );
}

function RankingPagination({
    loading,
    page,
    start,
    end,
    total,
    hasMore,
    totalIsLowerBound = false,
    onPrev,
    onNext,
    t,
}: {
    loading: boolean;
    page: number;
    start: number;
    end: number;
    total: number;
    hasMore: boolean;
    totalIsLowerBound?: boolean;
    onPrev: () => void;
    onNext: () => void;
    t: CitationTranslation;
}) {
    return (
        <div className="flex items-center justify-between gap-3 border-t px-4 py-3">
            <div className="text-xs text-muted-foreground">
                {loading
                    ? t("citations.pagination.loading")
                    : t(totalIsLowerBound ? "citations.pagination.rangeMore" : "citations.pagination.range", { start, end, total })}
            </div>
            <div className="flex items-center gap-2">
                <Button variant="outline" size="sm" onClick={onPrev} disabled={page === 0 || loading}>
                    {t("citations.pagination.previous")}
                </Button>
                <Button variant="outline" size="sm" onClick={onNext} disabled={!hasMore || loading}>
                    {t("citations.pagination.next")}
                </Button>
            </div>
        </div>
    );
}
