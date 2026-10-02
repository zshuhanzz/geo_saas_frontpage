import React, { useEffect, useState, useMemo, useRef } from "react";
import { getPromptConcepts, getPromptMetrics, getPromptIntentFacets } from "@/lib/api";
import { useSaaS } from "@/contexts/SaaSContext";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Select as UISelect, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Checkbox } from "@/components/ui/checkbox";
import { ChevronDown, ChevronRight, Edit2, Sparkles, FolderOpen, Search, FileDown, FileUp, BarChart3, SlidersHorizontal, Loader2, RotateCw } from "lucide-react";
import { useTranslation } from "react-i18next";
import { useNavigate } from "react-router-dom";
import { useInsightsFilters } from "../Insights";
import { todayDateOnlyString } from "@/lib/dateOnly";
import {
    applyPromptListFilters,
    buildLogicalPromptKey,
    buildIntentOptionGroups,
    selectPromptConceptVariants,
    toggleIntentOption,
    type IntentFacets,
    type IntentFilterOption,
    type IntentFilterState,
} from "./promptIntentFilter";
import {
    buildProductDrilldownHref,
    buildPromptDrilldownHref,
    buildTopicDrilldownHref,
} from "./promptDrilldownTarget";
import { SortableMetricHeader } from "@/components/ui/SortableMetricHeader";
import {
    isCompleteMetricCollection,
    sortCompleteMetricRows,
    type MetricSortState,
} from "@/lib/metricSort";
import { PromptImportDialog } from "@/components/prompts/PromptImportDialog";
import { promptImportWorkspaceRenderKey } from "@/lib/promptImport";

type GroupBy = "none" | "topic" | "product" | "country";

// Available metric columns (labels resolved from i18n at render time)
const ALL_COLUMN_KEYS = ["visibility_score", "brand_rank", "mentioned", "total_query", "avg_pos"] as const;
type ColumnKey = typeof ALL_COLUMN_KEYS[number];
const COLUMN_DICT_KEY: Record<ColumnKey, string> = {
    visibility_score: "visibilityScore",
    brand_rank: "brandRank",
    mentioned: "mentioned",
    total_query: "totalQuery",
    avg_pos: "avgPos",
};
const COLUMN_METRIC_KEY: Record<ColumnKey, string> = {
    visibility_score: "visibility_score",
    brand_rank: "brand_rank",
    mentioned: "mentioned",
    total_query: "total_query",
    avg_pos: "avg_position",
};

const REQUEST_START_DELAY_MS = 50;
const EMPTY_INTENT_FILTER: IntentFilterState = { values: [], includeBlank: false };

type PromptTableMetric = {
    mentioned: number;
    total_query: number;
    visibility_score: number;
    brand_rank?: number | null;
    avg_position: number | null;
    position_sum: number;
    position_count: number;
    brand_response_counts: Record<string, number>;
    brand_mention_counts: Record<string, number>;
    own_brand_names: string[];
};


/* ====================== Main Prompts Component ====================== */
export default function Prompts() {
    const { t } = useTranslation(["insights", "common"]);
    const { clients, clientId } = useSaaS();
    const { dateFrom, dateTo, selectedTopics, selectedPlatforms, selectedCountries } = useInsightsFilters();
    const navigate = useNavigate();
    const [data, setData] = useState<any[]>([]);
    const [metrics, setMetrics] = useState<Record<string, any>>({});
    const [metricOrder, setMetricOrder] = useState<string[]>([]);
    const [metricTotal, setMetricTotal] = useState<number | undefined>(undefined);
    const [promptSort, setPromptSort] = useState<MetricSortState>({ metricKey: "visibility_score", direction: "desc" });
    const [groupSort, setGroupSort] = useState<MetricSortState>({ metricKey: "visibility_score", direction: "desc" });
    const [loadedClientId, setLoadedClientId] = useState<string | null>(null);
    const [loadedInventoryKey, setLoadedInventoryKey] = useState<string | null>(null);
    const [loading, setLoading] = useState(true);
    const [error, setError] = useState("");
    const [errorClientId, setErrorClientId] = useState<string | null>(null);
    const [expandedGroups, setExpandedGroups] = useState<Record<string, boolean>>({});
    const [importOpen, setImportOpen] = useState(false);
    const [importRefreshKey, setImportRefreshKey] = useState(0);
    const loadSeq = useRef(0);
    const metricsLoadSeq = useRef(0);
    const intentFacetLoadSeq = useRef(0);

    // Filters
    const [searchQuery, setSearchQuery] = useState("");
    const [filterTopic, setFilterTopic] = useState("all");
    const [filterPlatform, setFilterPlatform] = useState("all");
    const [filterCountry, setFilterCountry] = useState("all");
    const [filterIntent, setFilterIntent] = useState<IntentFilterState>(EMPTY_INTENT_FILTER);
    const [intentFacets, setIntentFacets] = useState<IntentFacets | null>(null);
    const [intentFacetsClientId, setIntentFacetsClientId] = useState<string | null>(null);
    const [intentFacetsLoading, setIntentFacetsLoading] = useState(false);
    const [intentFacetsError, setIntentFacetsError] = useState(false);
    const [intentFacetsReloadKey, setIntentFacetsReloadKey] = useState(0);
    const [groupBy, setGroupBy] = useState<GroupBy>("topic");

    // Custom Columns
    const [visibleColumns, setVisibleColumns] = useState<Set<ColumnKey>>(
        new Set(["visibility_score", "brand_rank", "mentioned", "total_query", "avg_pos"])
    );

    const activeClient = clients.find(c => c.id === clientId);
    const inventoryKey = JSON.stringify([clientId, importRefreshKey]);
    const topics = (activeClient as any)?.topics || [];
    const visibleData = useMemo(
        () => loadedClientId === clientId ? data : [],
        [clientId, data, loadedClientId],
    );
    const visibleMetrics = useMemo(
        () => loadedClientId === clientId ? metrics : {},
        [clientId, loadedClientId, metrics],
    );

    useEffect(() => {
        loadSeq.current += 1;
        metricsLoadSeq.current += 1;
        setLoadedClientId(null);
        setLoadedInventoryKey(null);
        setData([]);
        setMetrics({});
        setMetricOrder([]);
        setMetricTotal(undefined);
        setExpandedGroups({});
        setError("");
        setErrorClientId(null);
        setLoading(Boolean(clientId));
    }, [clientId]);

    useEffect(() => {
        setFilterIntent(EMPTY_INTENT_FILTER);
        setIntentFacets(null);
        setIntentFacetsClientId(null);
        setIntentFacetsError(false);
    }, [clientId]);

    useEffect(() => {
        if (!clientId) {
            setIntentFacetsLoading(false);
            return;
        }

        const requestId = ++intentFacetLoadSeq.current;
        const controller = new AbortController();
        setIntentFacetsLoading(true);
        setIntentFacetsError(false);

        getPromptIntentFacets(clientId, { signal: controller.signal })
            .then((facets) => {
                if (requestId !== intentFacetLoadSeq.current) return;
                setIntentFacets(facets);
                setIntentFacetsClientId(clientId);
                const availableValues = new Set([...facets.active, ...facets.unconfigured]);
                setFilterIntent((current) => ({
                    values: current.values.filter((value) => availableValues.has(value)),
                    includeBlank: current.includeBlank && facets.has_unconfigured_blank,
                }));
            })
            .catch((err) => {
                if (err?.name === "AbortError" || requestId !== intentFacetLoadSeq.current) return;
                setIntentFacets(null);
                setIntentFacetsClientId(null);
                setFilterIntent(EMPTY_INTENT_FILTER);
                setIntentFacetsError(true);
            })
            .finally(() => {
                if (requestId === intentFacetLoadSeq.current) setIntentFacetsLoading(false);
            });

        return () => {
            controller.abort();
            if (intentFacetLoadSeq.current === requestId) intentFacetLoadSeq.current += 1;
        };
    }, [clientId, intentFacetsReloadKey]);

    useEffect(() => {
        if (!clientId) {
            loadSeq.current += 1;
            setData([]);
            setLoadedClientId(null);
            setLoading(false);
            return;
        }
        const requestId = ++loadSeq.current;
        const requestClientId = clientId;
        const requestInventoryKey = inventoryKey;
        const controller = new AbortController();
        const startTimer = window.setTimeout(() => {
            loadPrompts(requestId, requestClientId, requestInventoryKey, controller.signal);
        }, REQUEST_START_DELAY_MS);
        return () => {
            window.clearTimeout(startTimer);
            controller.abort();
            if (loadSeq.current === requestId) loadSeq.current += 1;
        };
    }, [clientId, importRefreshKey, inventoryKey]);

    useEffect(() => {
        if (!clientId || loadedInventoryKey !== inventoryKey) {
            metricsLoadSeq.current += 1;
            setMetrics({});
            setMetricOrder([]);
            setMetricTotal(undefined);
            return;
        }
        const requestId = ++metricsLoadSeq.current;
        const controller = new AbortController();
        const startTimer = window.setTimeout(() => {
            setMetrics({});
            setMetricOrder([]);
            setMetricTotal(undefined);
            getPromptMetrics(clientId, { date_from: dateFrom, date_to: dateTo }, { signal: controller.signal })
                .then((result) => {
                    if (requestId !== metricsLoadSeq.current) return;
                    setMetrics(result?.metrics || {});
                    setMetricOrder(result?.ordered_prompt_ids || []);
                    setMetricTotal(Number.isInteger(result?.total) && result.total >= 0 ? result.total : undefined);
                })
                .catch((err) => {
                    if (err?.name === "AbortError" || requestId !== metricsLoadSeq.current) return;
                    setMetrics({});
                    setMetricOrder([]);
                    setMetricTotal(undefined);
                });
        }, REQUEST_START_DELAY_MS);
        return () => {
            window.clearTimeout(startTimer);
            controller.abort();
            if (metricsLoadSeq.current === requestId) metricsLoadSeq.current += 1;
        };
    }, [clientId, loadedInventoryKey, inventoryKey, dateFrom, dateTo, importRefreshKey]);

    async function loadPrompts(requestId: number, requestClientId: string, requestInventoryKey: string, signal: AbortSignal) {
        setLoading(true);
        try {
            const promptsRes = await getPromptConcepts(requestClientId, { signal });
            if (requestId !== loadSeq.current) return;
            setData(promptsRes || []);
            setLoadedClientId(requestClientId);
            setLoadedInventoryKey(requestInventoryKey);
            setError("");
            setErrorClientId(null);

            // Expand all by default
            if (activeClient?.topics) {
                const initialExpanded: Record<string, boolean> = {};
                (activeClient.topics as any[]).forEach((t: any) => initialExpanded[t.id] = true);
                setExpandedGroups(initialExpanded);
            }
        } catch (err: any) {
            if (err?.name === "AbortError") return;
            if (requestId !== loadSeq.current) return;
            setError(err.message);
            setErrorClientId(requestClientId);
        } finally {
            if (requestId === loadSeq.current) setLoading(false);
        }
    }

    const toggleGroup = (key: string) => {
        setExpandedGroups(prev => ({ ...prev, [key]: !prev[key] }));
    };

    const toggleColumn = (col: ColumnKey) => {
        setVisibleColumns(prev => {
            const next = new Set(prev);
            if (next.has(col)) next.delete(col);
            else next.add(col);
            return next;
        });
    };

    // Filtered data
    const effectiveIntentFilter = intentFacetsClientId === clientId && !intentFacetsError
        ? filterIntent
        : EMPTY_INTENT_FILTER;

    const filteredData = useMemo(() => {
        const variantFiltered = visibleData
            .map((row) => selectPromptConceptVariants(row, {
                platform: filterPlatform === "all" ? null : filterPlatform,
                platforms: selectedPlatforms,
                country: filterCountry === "all" ? null : filterCountry,
                countries: selectedCountries,
            }))
            .filter((row): row is any => row !== null);
        return applyPromptListFilters(variantFiltered, {
            activeOnly: true,
            searchQuery,
            topicId: filterTopic === "all" ? null : filterTopic,
            topicIds: selectedTopics,
            intent: effectiveIntentFilter,
        });
    }, [visibleData, searchQuery, filterTopic, selectedTopics, filterPlatform, selectedPlatforms, filterCountry, selectedCountries, effectiveIntentFilter]);

    const intentOptionGroups = useMemo(
        () => intentFacets && intentFacetsClientId === clientId
            ? buildIntentOptionGroups(intentFacets)
            : { active: [], unconfigured: [] },
        [clientId, intentFacets, intentFacetsClientId],
    );
    const activeIntentValues = useMemo(
        () => intentOptionGroups.active.map((option) => option.value),
        [intentOptionGroups],
    );
    const selectedIntentCount = effectiveIntentFilter.values.length + (effectiveIntentFilter.includeBlank ? 1 : 0);

    function isIntentOptionSelected(option: IntentFilterOption): boolean {
        return option.kind === "blank"
            ? effectiveIntentFilter.includeBlank
            : effectiveIntentFilter.values.includes(option.value);
    }

    function renderIntentOption(option: IntentFilterOption) {
        const selected = isIntentOptionSelected(option);
        const label = option.kind === "blank"
            ? t("prompts.filters.intent.unconfiguredBlank")
            : option.value;
        const key = option.kind === "blank" ? "intent-option:blank" : `intent-option:value:${option.value}`;
        return (
            <label
                key={key}
                className="flex w-full cursor-pointer items-center gap-2 rounded-md px-2 py-1.5 text-left text-sm transition-colors hover:bg-accent"
            >
                <Checkbox
                    checked={selected}
                    onCheckedChange={() => setFilterIntent((current) => toggleIntentOption(current, option))}
                    aria-label={label}
                />
                <span className="truncate">{label}</span>
            </label>
        );
    }

    // Merge rows by text: group rows with same text into one merged row
    const mergedData = useMemo(() => {
        const map = new Map<string, { rowKey: string; text: string; topic_id: string; product: string; intent: string; language: string; platforms: string[]; countries: string[]; ids: string[] }>();
        filteredData.forEach((p: any) => {
            const key = buildLogicalPromptKey(p, clientId, activeIntentValues);
            if (!map.has(key)) {
                map.set(key, {
                    rowKey: key,
                    text: p.text,
                    topic_id: p.topic_id,
                    product: p.product || "",
                    intent: p.intent || "",
                    language: p.language || "",
                    platforms: [],
                    countries: [],
                    ids: [],
                });
            }
            const entry = map.get(key)!;
            for (const id of p.prompt_ids || [p.id]) {
                if (!entry.ids.includes(id)) entry.ids.push(id);
            }
            for (const platform of p.platforms || (p.platform ? [p.platform] : [])) {
                if (!entry.platforms.includes(platform)) entry.platforms.push(platform);
            }
            for (const country of p.countries || (p.country ? [p.country] : [])) {
                if (!entry.countries.includes(country)) entry.countries.push(country);
            }
        });
        return Array.from(map.values());
    }, [activeIntentValues, clientId, filteredData]);

    // Grouped data (uses mergedData instead of filteredData)
    const groupedData = useMemo(() => {
        if (groupBy === "none") return [{
            key: "all",
            label: t("prompts.filters.allPrompts"),
            items: mergedData,
            targetTopicId: "",
            targetProduct: "",
        }];

        const groups: Record<string, any[]> = {};
        mergedData.forEach(p => {
            let key: string;
            if (groupBy === "topic") key = p.topic_id || "unknown";
            else if (groupBy === "product") key = `${p.topic_id || "unknown"}\u001f${p.product || ""}`;
            else key = p.countries.join(", ") || t("prompts.fallback.noCountry");
            if (!groups[key]) groups[key] = [];
            groups[key].push(p);
        });

        return Object.entries(groups).map(([key, items]) => {
            let label = key;
            if (groupBy === "topic") {
                const topic = topics.find((top: any) => top.id === key);
                label = topic?.topic_name || key;
            } else if (groupBy === "product") {
                label = items[0]?.product || t("prompts.fallback.noProduct");
            }
            return {
                key,
                label,
                items,
                targetTopicId: items[0]?.topic_id || "",
                targetProduct: items[0]?.product || "",
            };
        });
    }, [mergedData, groupBy, topics, t]);

    // Unique platforms and countries for filter
    const platforms = useMemo(() => {
        const set = new Set(visibleData.flatMap((p: any) => p.platforms || (p.platform ? [p.platform] : [])));
        return Array.from(set).sort();
    }, [visibleData]);

    const countries = useMemo(() => {
        const set = new Set(visibleData.flatMap((p: any) => p.countries || (p.country ? [p.country] : [])));
        return Array.from(set).sort() as string[];
    }, [visibleData]);

    // Helper to get aggregated metrics for a merged prompt (across all its IDs)
    function mergeCountMaps(target: Record<string, number>, source: Record<string, number> | undefined) {
        if (!source) return;
        for (const [brand, count] of Object.entries(source)) {
            target[brand] = (target[brand] || 0) + (Number(count) || 0);
        }
    }

    function computeBrandRank(
        totalQuery: number,
        brandResponseCounts: Record<string, number>,
        brandMentionCounts: Record<string, number>,
        ownBrandNames: string[],
    ): number | null {
        if (totalQuery <= 0 || ownBrandNames.length === 0) return null;
        const ownBrands = new Set(ownBrandNames);
        const entries = Object.entries(brandResponseCounts).sort(([brandA, countA], [brandB, countB]) => {
            const scoreA = parseFloat(((countA / totalQuery) * 100).toFixed(1));
            const scoreB = parseFloat(((countB / totalQuery) * 100).toFixed(1));
            if (scoreB !== scoreA) return scoreB - scoreA;
            const mentionsA = brandMentionCounts[brandA] || 0;
            const mentionsB = brandMentionCounts[brandB] || 0;
            if (mentionsB !== mentionsA) return mentionsB - mentionsA;
            return brandA.toLowerCase().localeCompare(brandB.toLowerCase());
        });
        let currentRank = 0;
        let prevScore: number | null = null;
        for (let index = 0; index < entries.length; index += 1) {
            const [brand, count] = entries[index];
            const score = parseFloat(((count / totalQuery) * 100).toFixed(1));
            if (score !== prevScore) {
                currentRank = index + 1;
                prevScore = score;
            }
            if (ownBrands.has(brand) && count > 0) return currentRank;
        }
        return null;
    }

    function getMergedMetric(ids: string[]): PromptTableMetric {
        let mentioned = 0, totalQuery = 0, posSum = 0, posCount = 0;
        const brandResponseCounts: Record<string, number> = {};
        const brandMentionCounts: Record<string, number> = {};
        const ownBrandNames = new Set<string>();
        for (const id of ids) {
            const m = visibleMetrics[id] || {};
            mentioned += m.mentioned ?? m.mention_count ?? 0;
            totalQuery += m.total_query ?? 0;
            posSum += m.position_sum ?? 0;
            posCount += m.position_count ?? 0;
            mergeCountMaps(brandResponseCounts, m.brand_response_counts);
            mergeCountMaps(brandMentionCounts, m.brand_mention_counts);
            (m.own_brand_names || []).forEach((brand: string) => ownBrandNames.add(brand));
        }
        const visibilityScore = totalQuery > 0 ? parseFloat(((mentioned / totalQuery) * 100).toFixed(1)) : 0;
        const ownBrandNameList = Array.from(ownBrandNames);
        return {
            mentioned,
            total_query: totalQuery,
            visibility_score: visibilityScore,
            brand_rank: computeBrandRank(totalQuery, brandResponseCounts, brandMentionCounts, ownBrandNameList),
            avg_position: posCount > 0 ? parseFloat((posSum / posCount).toFixed(1)) : null,
            position_sum: posSum,
            position_count: posCount,
            brand_response_counts: brandResponseCounts,
            brand_mention_counts: brandMentionCounts,
            own_brand_names: ownBrandNameList,
        };
    }

    function aggregateItemMetrics(items: any[]): PromptTableMetric {
        let mentioned = 0, totalQuery = 0, posSum = 0, posCount = 0;
        const brandResponseCounts: Record<string, number> = {};
        const brandMentionCounts: Record<string, number> = {};
        const ownBrandNames = new Set<string>();
        for (const item of items) {
            const metric = getMergedMetric(item.ids);
            mentioned += metric.mentioned;
            totalQuery += metric.total_query;
            posSum += metric.position_sum;
            posCount += metric.position_count;
            mergeCountMaps(brandResponseCounts, metric.brand_response_counts);
            mergeCountMaps(brandMentionCounts, metric.brand_mention_counts);
            metric.own_brand_names.forEach(brand => ownBrandNames.add(brand));
        }
        const ownBrandNameList = Array.from(ownBrandNames);
        return {
            mentioned,
            total_query: totalQuery,
            visibility_score: totalQuery > 0 ? parseFloat(((mentioned / totalQuery) * 100).toFixed(1)) : 0,
            brand_rank: computeBrandRank(totalQuery, brandResponseCounts, brandMentionCounts, ownBrandNameList),
            avg_position: posCount > 0 ? parseFloat((posSum / posCount).toFixed(1)) : null,
            position_sum: posSum,
            position_count: posCount,
            brand_response_counts: brandResponseCounts,
            brand_mention_counts: brandMentionCounts,
            own_brand_names: ownBrandNameList,
        };
    }

    const promptMetricByKey = useMemo(
        () => new Map(mergedData.map((p: any) => [p.rowKey, getMergedMetric(p.ids)])),
        [mergedData, visibleMetrics],
    );

    const groupMetricByKey = useMemo(
        () => new Map(groupedData.map(group => [group.key, aggregateItemMetrics(group.items)])),
        [groupedData, visibleMetrics],
    );

    const promptMetricsComplete = useMemo(() => (
        loadedClientId === clientId
        && isCompleteMetricCollection(metricOrder, metricTotal)
        && Object.keys(visibleMetrics).length === metricTotal
        && visibleData.every((prompt: any) => (prompt.prompt_ids || [prompt.id])
            .every((id: string) => Object.prototype.hasOwnProperty.call(visibleMetrics, id)))
    ), [clientId, loadedClientId, metricOrder, metricTotal, visibleData, visibleMetrics]);

    const sortedGroupedData = useMemo(() => {
        if (!promptMetricsComplete) return groupedData;
        const groupsWithSortedPrompts = groupedData.map((group) => {
            const enrichedPrompts = group.items.map((item: any) => ({
                ...item,
                ...(promptMetricByKey.get(item.rowKey) || {}),
            }));
            const sortedItems = sortCompleteMetricRows(enrichedPrompts, enrichedPrompts.length, {
                ...promptSort,
                tieTextKey: "text",
                tieIdKey: "rowKey",
            });
            return { ...group, items: Array.from(sortedItems) };
        });
        if (groupBy === "none") return groupsWithSortedPrompts;
        const enrichedGroups = groupsWithSortedPrompts.map((group) => ({
            ...group,
            ...(groupMetricByKey.get(group.key) || {}),
        }));
        return Array.from(sortCompleteMetricRows(enrichedGroups, enrichedGroups.length, {
            ...groupSort,
            tieTextKey: "label",
            tieIdKey: "key",
        }));
    }, [groupBy, groupMetricByKey, groupedData, groupSort, promptMetricByKey, promptMetricsComplete, promptSort]);

    // CSV Export
    function handleExportCSV() {
        const escapeCsv = (value: any) => `"${String(value ?? "").replace(/"/g, '""')}"`;
        const headers = [
            t("prompts.export.headerTopic"),
            t("prompts.export.headerProduct"),
            t("prompts.export.headerPrompt"),
            t("prompts.export.headerPlatform"),
            t("prompts.export.headerCountry"),
            t("prompts.export.headerLanguage"),
            t("prompts.export.headerIntent"),
            t("prompts.tableColumns.visibilityScore"),
            t("prompts.tableColumns.brandRank"),
            t("prompts.tableColumns.mentioned"),
            t("prompts.tableColumns.totalQuery"),
            t("prompts.export.headerAvgPosition"),
        ];
        const rows = mergedData.map((p: any) => {
            const topicName = topics.find((top: any) => top.id === p.topic_id)?.topic_name || "";
            const m = promptMetricByKey.get(p.rowKey) || getMergedMetric(p.ids);
            return [
                topicName,
                p.product || "",
                p.text,
                p.platforms.join(";"),
                p.countries.join(";"),
                p.language,
                p.intent || "",
                `${m.visibility_score}%`,
                m.brand_rank || "",
                m.mentioned,
                m.total_query,
                m.avg_position || "",
            ];
        });
        const csv = [headers.map(escapeCsv).join(","), ...rows.map(r => r.map(escapeCsv).join(","))].join("\r\n");
        const blob = new Blob([`\uFEFF${csv}`], { type: "text/csv;charset=utf-8" });
        const url = URL.createObjectURL(blob);
        const a = document.createElement("a");
        a.href = url;
        a.download = `prompts_${todayDateOnlyString()}.csv`;
        a.click();
        URL.revokeObjectURL(url);
    }

    if (!clientId) {
        return <div className="p-8 text-center text-muted-foreground">{t("prompts.pleaseSelectWorkspace")}</div>;
    }

    if (loading && visibleData.length === 0) return <div className="p-8 text-center text-muted-foreground animate-pulse">{t("prompts.loadingPrompts")}</div>;
    if (error && errorClientId === clientId) return <div className="p-8 text-center text-red-500">{t("prompts.failedToLoad", { error })}</div>;

    const colCount = 4 + visibleColumns.size;

    return (
        <div className="space-y-4 animate-in slide-in-from-bottom p-6">
            <div className="flex justify-between items-end">
                <div>
                    <h2 className="text-2xl font-semibold tracking-tight">{t("prompts.pageTitle")}</h2>
                    <p className="text-sm text-muted-foreground mt-1">{t("prompts.pageDescription")}</p>
                </div>
                <Button onClick={() => navigate("/prompt-editor")}>
                    <Edit2 className="h-4 w-4 mr-2" />
                    {t("prompts.manageButton")}
                </Button>
            </div>

            {/* Filter Bar */}
            <div className="flex gap-3 items-center flex-wrap">
                <div className="relative flex-1 max-w-xs">
                    <Search className="h-4 w-4 absolute left-3 top-1/2 -translate-y-1/2 text-muted-foreground" />
                    <Input
                        placeholder={t("prompts.filters.searchPlaceholder")}
                        value={searchQuery}
                        onChange={e => setSearchQuery(e.target.value)}
                        className="pl-9 h-9"
                    />
                </div>
                <UISelect value={filterTopic} onValueChange={setFilterTopic}>
                    <SelectTrigger className="w-44 h-9">
                        <SelectValue placeholder={t("prompts.filters.allTopics")} />
                    </SelectTrigger>
                    <SelectContent>
                        <SelectItem value="all">{t("prompts.filters.allTopics")}</SelectItem>
                        {topics.map((top: any) => (
                            <SelectItem key={top.id} value={top.id}>{top.topic_name}</SelectItem>
                        ))}
                    </SelectContent>
                </UISelect>
                <UISelect value={filterPlatform} onValueChange={setFilterPlatform}>
                    <SelectTrigger className="w-36 h-9">
                        <SelectValue placeholder={t("prompts.filters.allPlatforms")} />
                    </SelectTrigger>
                    <SelectContent>
                        <SelectItem value="all">{t("prompts.filters.allPlatforms")}</SelectItem>
                        {platforms.map(p => (
                            <SelectItem key={p} value={p}>{p}</SelectItem>
                        ))}
                    </SelectContent>
                </UISelect>
                <UISelect value={filterCountry} onValueChange={setFilterCountry}>
                    <SelectTrigger className="w-36 h-9">
                        <SelectValue placeholder={t("prompts.filters.allCountries")} />
                    </SelectTrigger>
                    <SelectContent>
                        <SelectItem value="all">{t("prompts.filters.allCountries")}</SelectItem>
                        {countries.map(c => (
                            <SelectItem key={c} value={c}>{c}</SelectItem>
                        ))}
                    </SelectContent>
                </UISelect>
                <Popover>
                    <PopoverTrigger asChild>
                        <Button
                            variant="outline"
                            size="sm"
                            className="h-9 min-w-36 justify-between gap-2"
                            disabled={intentFacetsLoading}
                            aria-label={t("prompts.filters.intent.ariaLabel")}
                        >
                            {intentFacetsLoading ? (
                                <>
                                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                                    {t("common:states.loading")}
                                </>
                            ) : (
                                <>
                                    <span>
                                        {selectedIntentCount > 0
                                            ? t("prompts.filters.intent.selectedCount", { count: selectedIntentCount })
                                            : t("prompts.filters.intent.button")}
                                    </span>
                                    <ChevronDown className="h-3.5 w-3.5 text-muted-foreground" />
                                </>
                            )}
                        </Button>
                    </PopoverTrigger>
                    <PopoverContent className="w-64 p-2" align="start" aria-label={t("prompts.filters.intent.ariaLabel")}>
                        {intentFacetsError ? (
                            <div className="space-y-3 p-2">
                                <p className="text-sm text-muted-foreground">{t("prompts.filters.intent.loadFailed")}</p>
                                <Button
                                    type="button"
                                    variant="outline"
                                    size="sm"
                                    className="w-full"
                                    onClick={() => setIntentFacetsReloadKey((key) => key + 1)}
                                >
                                    <RotateCw className="mr-2 h-3.5 w-3.5" />
                                    {t("common:actions.retry")}
                                </Button>
                            </div>
                        ) : (
                            <div className="space-y-2">
                                {intentOptionGroups.active.length > 0 && (
                                    <div>
                                        <div className="px-2 pb-1 text-xs font-semibold text-muted-foreground">
                                            {t("prompts.filters.intent.activeGroup")}
                                        </div>
                                        {intentOptionGroups.active.map(renderIntentOption)}
                                    </div>
                                )}
                                {intentOptionGroups.unconfigured.length > 0 && (
                                    <div className={intentOptionGroups.active.length > 0 ? "border-t pt-2" : ""}>
                                        <div className="px-2 pb-1 text-xs font-semibold text-muted-foreground">
                                            {t("prompts.filters.intent.unconfiguredGroup")}
                                        </div>
                                        {intentOptionGroups.unconfigured.map(renderIntentOption)}
                                    </div>
                                )}
                                {intentOptionGroups.active.length === 0 && intentOptionGroups.unconfigured.length === 0 && (
                                    <p className="px-2 py-3 text-sm text-muted-foreground">
                                        {t("prompts.filters.intent.empty")}
                                    </p>
                                )}
                                {selectedIntentCount > 0 && (
                                    <Button
                                        type="button"
                                        variant="ghost"
                                        size="sm"
                                        className="w-full border-t"
                                        onClick={() => setFilterIntent(EMPTY_INTENT_FILTER)}
                                    >
                                        {t("prompts.filters.intent.clearSelection")}
                                    </Button>
                                )}
                            </div>
                        )}
                    </PopoverContent>
                </Popover>
                <UISelect value={groupBy} onValueChange={v => setGroupBy(v as GroupBy)}>
                    <SelectTrigger className="w-36 h-9">
                        <SelectValue placeholder={t("prompts.filters.groupByPlaceholder")} />
                    </SelectTrigger>
                    <SelectContent>
                        <SelectItem value="topic">{t("prompts.groupBy.topic")}</SelectItem>
                        <SelectItem value="product">{t("prompts.groupBy.product")}</SelectItem>
                        <SelectItem value="country">{t("prompts.groupBy.country")}</SelectItem>
                        <SelectItem value="none">{t("prompts.groupBy.none")}</SelectItem>
                    </SelectContent>
                </UISelect>

                {/* Custom Columns Dropdown */}
                <Popover>
                    <PopoverTrigger asChild>
                        <Button variant="outline" size="sm" className="h-9 gap-1.5">
                            <SlidersHorizontal className="h-3.5 w-3.5" />
                            {t("prompts.columnsButton")}
                        </Button>
                    </PopoverTrigger>
                    <PopoverContent className="w-48 p-2" align="start">
                        <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2 px-1">{t("prompts.toggleColumns")}</div>
                        {ALL_COLUMN_KEYS.map(colKey => (
                            <button
                                key={colKey}
                                onClick={() => toggleColumn(colKey)}
                                className="flex items-center gap-2 w-full px-2 py-1.5 text-sm rounded-md hover:bg-accent transition-colors"
                            >
                                <Checkbox
                                    checked={visibleColumns.has(colKey)}
                                    className="pointer-events-none"
                                />
                                <span>{t(`prompts.tableColumns.${COLUMN_DICT_KEY[colKey]}` as any)}</span>
                            </button>
                        ))}
                    </PopoverContent>
                </Popover>

                <Button variant="outline" size="sm" className="h-9" onClick={handleExportCSV}>
                    <FileDown className="h-4 w-4 mr-1" /> {t("prompts.exportCSV")}
                </Button>
                <Button variant="outline" size="sm" className="h-9" onClick={() => setImportOpen(true)}>
                    <FileUp className="h-4 w-4 mr-1" /> {t("prompts.import.entry")}
                </Button>
                <div className="text-xs text-muted-foreground ml-auto">
                    {t("prompts.promptCount", { count: mergedData.length })}
                    {mergedData.length !== filteredData.length && <span className="ml-1">{t("prompts.promptCountRows", { count: filteredData.length })}</span>}
                </div>
            </div>

            <PromptImportDialog
                key={promptImportWorkspaceRenderKey(clientId)}
                clientId={clientId}
                workspaceName={activeClient?.name || ""}
                open={importOpen}
                onOpenChange={setImportOpen}
                onImported={() => setImportRefreshKey((value) => value + 1)}
            />

            {!promptMetricsComplete && !loading && (
                <div className="rounded-md border border-amber-500/30 bg-amber-500/5 px-3 py-2 text-xs text-muted-foreground">
                    {t("metricSort.incompletePromptMetrics")}
                </div>
            )}

            {/* Table */}
            <div className="rounded-md border bg-card shadow-sm overflow-hidden">
                <Table>
                    <TableHeader>
                        <TableRow className="bg-muted/20">
                            <TableHead className="w-[35%] pl-6">
                                {groupBy !== "none" ? t("prompts.tableColumns.groupPrompt") : t("prompts.tableColumns.promptPlain")}
                            </TableHead>
                            <TableHead>{t("prompts.tableColumns.product")}</TableHead>
                            <TableHead>{t("prompts.tableColumns.platforms")}</TableHead>
                            <TableHead>{t("prompts.tableColumns.countries")}</TableHead>
                            {ALL_COLUMN_KEYS.filter((column) => visibleColumns.has(column)).map((column) => {
                                const metricKey = COLUMN_METRIC_KEY[column];
                                const label = t(`prompts.tableColumns.${COLUMN_DICT_KEY[column]}` as any);
                                return (
                                    <TableHead key={column} className="text-right min-w-[120px]">
                                        {groupBy !== "none" && (
                                            <span data-sort-list="prompt-groups">
                                                <SortableMetricHeader
                                                    label={t("metricSort.groupMetric", { label })}
                                                    metricKey={metricKey}
                                                    sort={groupSort}
                                                    onChange={setGroupSort}
                                                    disabled={!promptMetricsComplete}
                                                />
                                            </span>
                                        )}
                                        <span data-sort-list="prompt-rows">
                                            <SortableMetricHeader
                                                label={groupBy === "none" ? label : t("metricSort.promptMetric", { label })}
                                                metricKey={metricKey}
                                                sort={promptSort}
                                                onChange={setPromptSort}
                                                disabled={!promptMetricsComplete}
                                            />
                                        </span>
                                    </TableHead>
                                );
                            })}
                        </TableRow>
                    </TableHeader>
                    <TableBody>
                        {sortedGroupedData.map(group => {
                            const isExpanded = expandedGroups[group.key] !== false;

                            const groupMetrics = groupMetricByKey.get(group.key) || aggregateItemMetrics(group.items);

                            return (
                                <React.Fragment key={group.key}>
                                    {/* Group Header Row (only if grouping) */}
                                    {groupBy !== "none" && (
                                        <TableRow
                                            className="hover:bg-muted/50 cursor-pointer transition-colors bg-muted/10 group/topic"
                                            onClick={() => toggleGroup(group.key)}
                                        >
                                            <TableCell className="font-semibold pl-4 flex items-center gap-2 py-4">
                                                <Button variant="ghost" size="icon" className="h-6 w-6 shrink-0 pointer-events-none">
                                                    {isExpanded ? <ChevronDown className="h-4 w-4 text-primary" /> : <ChevronRight className="h-4 w-4 text-muted-foreground" />}
                                                </Button>
                                                <FolderOpen className="h-4 w-4 text-muted-foreground" />
                                                <span>{group.label}</span>
                                                <span className="text-xs text-muted-foreground ml-2 font-normal">({group.items.length})</span>
                                                {(() => {
                                                    const href = groupBy === "topic"
                                                        ? buildTopicDrilldownHref(group.key)
                                                        : groupBy === "product"
                                                            ? buildProductDrilldownHref(group.targetTopicId, group.targetProduct)
                                                            : null;
                                                    return href ? (
                                                        <Button
                                                            variant="ghost"
                                                            size="icon"
                                                            className="h-6 w-6 opacity-0 group-hover/topic:opacity-100 transition-opacity ml-1"
                                                            onClick={(e) => {
                                                                e.stopPropagation();
                                                                navigate(href);
                                                            }}
                                                            title={t("prompts.analysis.viewGroupAnalysis", { groupLabel: group.label })}
                                                        >
                                                            <BarChart3 className="h-3.5 w-3.5 text-primary" />
                                                        </Button>
                                                    ) : null;
                                                })()}
                                            </TableCell>
                                            <TableCell />
                                            <TableCell />
                                            <TableCell />
                                            {visibleColumns.has("visibility_score") && (
                                                <TableCell className="text-right font-medium text-muted-foreground">
                                                    {groupMetrics.total_query > 0 ? `${groupMetrics.visibility_score}%` : "—"}
                                                </TableCell>
                                            )}
                                            {visibleColumns.has("brand_rank") && (
                                                <TableCell className="text-right text-muted-foreground">
                                                    {groupMetrics.brand_rank ? `#${groupMetrics.brand_rank}` : "—"}
                                                </TableCell>
                                            )}
                                            {visibleColumns.has("mentioned") && (
                                                <TableCell className="text-right text-muted-foreground">
                                                    {groupMetrics.mentioned}
                                                </TableCell>
                                            )}
                                            {visibleColumns.has("total_query") && (
                                                <TableCell className="text-right text-muted-foreground">
                                                    {groupMetrics.total_query}
                                                </TableCell>
                                            )}
                                            {visibleColumns.has("avg_pos") && (
                                                <TableCell className="text-right text-muted-foreground">
                                                    {groupMetrics.avg_position != null ? `#${groupMetrics.avg_position}` : "—"}
                                                </TableCell>
                                            )}
                                        </TableRow>
                                    )}

                                    {/* Prompt Rows */}
                                    {(groupBy === "none" || isExpanded) && group.items.map((p: any) => {
                                        const m = promptMetricByKey.get(p.rowKey) || getMergedMetric(p.ids);
                                        return (
                                            <TableRow key={p.rowKey} className="text-sm bg-background group/prompt">
                                                <TableCell className={`${groupBy !== "none" ? "pl-14" : "pl-6"} py-3`}>
                                                    <div className="flex items-center gap-2">
                                                        <div className="flex flex-col gap-1 flex-1 min-w-0">
                                                            <span className="font-medium max-w-[400px] truncate" title={p.text}>{p.text}</span>
                                                            <div className="flex gap-2 items-center">
                                                                <span className="text-[10px] text-muted-foreground">{(p.language || "").toUpperCase()}</span>
                                                                {p.intent && <Badge variant="secondary" className="text-[10px] font-normal">{p.intent}</Badge>}
                                                            </div>
                                                        </div>
                                                        {/* Prompt-level Analysis Button */}
                                                        <Button
                                                            variant="ghost"
                                                            size="icon"
                                                            className="h-6 w-6 opacity-0 group-hover/prompt:opacity-100 transition-opacity shrink-0"
                                                            onClick={(e) => {
                                                                e.stopPropagation();
                                                                const href = buildPromptDrilldownHref(p.ids[0]);
                                                                if (href) navigate(href);
                                                            }}
                                                            title={t("prompts.analysis.viewPromptAnalysis")}
                                                        >
                                                            <BarChart3 className="h-3.5 w-3.5 text-primary" />
                                                        </Button>
                                                    </div>
                                                </TableCell>
                                                <TableCell><span className="text-xs text-muted-foreground">{p.product || "—"}</span></TableCell>
                                                <TableCell>
                                                    <div className="flex gap-1 flex-wrap">
                                                        {p.platforms.map((pl: string) => (
                                                            <Badge key={pl} variant="outline" className="text-[10px] uppercase font-normal">{pl}</Badge>
                                                        ))}
                                                    </div>
                                                </TableCell>
                                                <TableCell>
                                                    <div className="flex gap-1 flex-wrap">
                                                        {p.countries.map((ct: string) => (
                                                            <Badge key={ct} variant="secondary" className="text-[10px] font-normal">{ct}</Badge>
                                                        ))}
                                                    </div>
                                                </TableCell>
                                                {visibleColumns.has("visibility_score") && (
                                                    <TableCell className="text-right">
                                                        {m.total_query > 0 ? `${m.visibility_score}%` : "—"}
                                                    </TableCell>
                                                )}
                                                {visibleColumns.has("brand_rank") && (
                                                    <TableCell className="text-right">
                                                        {m.brand_rank ? `#${m.brand_rank}` : "—"}
                                                    </TableCell>
                                                )}
                                                {visibleColumns.has("mentioned") && (
                                                    <TableCell className="text-right">
                                                        {m.mentioned}
                                                    </TableCell>
                                                )}
                                                {visibleColumns.has("total_query") && (
                                                    <TableCell className="text-right">
                                                        {m.total_query}
                                                    </TableCell>
                                                )}
                                                {visibleColumns.has("avg_pos") && (
                                                    <TableCell className="text-right">
                                                        {m.avg_position != null ? `#${m.avg_position}` : "—"}
                                                    </TableCell>
                                                )}
                                            </TableRow>
                                        );
                                    })}

                                    {/* Empty Group */}
                                    {(groupBy === "none" || isExpanded) && group.items.length === 0 && (
                                        <TableRow className="bg-background">
                                            <TableCell colSpan={colCount + 2} className="py-6 text-center">
                                                <div className="flex flex-col items-center justify-center text-muted-foreground">
                                                    <Sparkles className="h-6 w-6 mb-2 opacity-50" />
                                                    <p className="text-sm">{t("prompts.emptyGroup.noActive")}</p>
                                                    <Button variant="link" size="sm" onClick={() => navigate("/prompt-editor")}>
                                                        {t("prompts.emptyGroup.initWithAI")}
                                                    </Button>
                                                </div>
                                            </TableCell>
                                        </TableRow>
                                    )}
                                </React.Fragment>
                            );
                        })}

                        {filteredData.length === 0 && groupedData.length === 0 && (
                            <TableRow>
                                <TableCell colSpan={colCount + 2} className="h-48 text-center text-muted-foreground">
                                    {t("prompts.emptyTable")}
                                </TableCell>
                            </TableRow>
                        )}
                    </TableBody>
                </Table>
            </div>
        </div>
    );
}
