/**
 * Visibility page — dispatches on viewBy dimension (Spec §8.4).
 *
 *   brand   → /insights/visibility (current — brand-level SOV + time series)
 *   product → /insights/product-visibility (own products; role=own)
 *   topic   → /insights/topic-visibility (aggregated per-topic mentions)
 *   cross   → redirect to /insights/channel-analysis (shadow × own)
 *
 * Same page, same filter context. The response from product/topic endpoints
 * is normalized into the brand-shape (`sov_ranking` / `time_series`) so
 * VisibilityDashboard renders without forking — it only relabels the axis
 * header using the `dimension` prop.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import {
    getProductVisibility,
    getTopicVisibility,
    getVisibilityBrandRanking,
    getVisibilityPosition,
    getVisibilityPositionRanking,
    getVisibilityScore,
    getVisibilitySov,
    getVisibilitySovRanking,
} from "@/lib/api";
import { useSaaS } from "@/contexts/SaaSContext";
import { useInsightsFilters } from "../Insights";
import VisibilityDashboard from "@/components/insights/VisibilityDashboard";
import type { VisibilityRankingSorts } from "@/components/insights/VisibilityDashboard";
import { buildStandaloneVisibilitySorts } from "@/components/insights/visibilityMetricSort";
import { useDebouncedValue } from "@/hooks/useDebouncedValue";
import { sortCompleteMetricRows, type MetricSortState, withMetricSortParams } from "@/lib/metricSort";

type Dim = "brand" | "product" | "topic";

const REQUEST_START_DELAY_MS = 50;

// Map /product-visibility (role=own) response → /visibility-shaped data.
// Visibility is response coverage; SOV remains share of product mentions.
function productRanking(res: any): any[] {
    return (res?.ranking || []).map((r: any) => ({
        company_name: r.product_name,
        brand_name: r.product_name,
        mention_count: r.mention_count,
        visibility_pct: r.visibility_pct,
        sov_pct: r.sov_pct,
        avg_position: r.avg_position,
        rank: r.rank,
        is_own: true,
        _owner: r.owner_brand_name || r.owner_peer_name || "",
    }));
}

function normalizeProduct(visibilityRes: any, sovRes: any, positionRes: any): any {
    if (!visibilityRes || visibilityRes.reason === "no_data") {
        return { summary: { visibility_score: 0 }, sov_ranking: [], time_series: [], avg_position_series: [], competitive_series: {} };
    }
    const total = visibilityRes.summary?.total_mentions || 0;
    const time_series = (visibilityRes.time_series || []).map((pt: any) => ({
        date: pt.date,
        total: pt.total_responses,
        own_count: pt.mentioned_responses,
        product_mentions: pt.total,
        score: pt.visibility_score,
    }));
    const leadingProductSov = Math.max(
        0,
        ...(visibilityRes.ranking || []).map((row: any) => Number(row.sov_pct || 0)),
    );
    return {
        summary: {
            visibility_score: visibilityRes.summary?.visibility_score ?? 0,
            visibility_score_change: null,
            visibility_rank: 1,
            total_mentions: total,
            own_mentions: visibilityRes.summary?.mentioned_responses ?? 0,
            total_responses: visibilityRes.summary?.total_responses ?? 0,
            mentioned_responses: visibilityRes.summary?.mentioned_responses ?? 0,
            sov_pct: leadingProductSov,
            avg_position: null,
            avg_position_change: null,
        },
        visibility_ranking: productRanking(visibilityRes),
        sov_ranking: productRanking(sovRes),
        position_ranking: productRanking(positionRes),
        prev_time_series: [],
        time_series,
        avg_position_series: [],
        prev_avg_position_series: [],
        competitive_series: {},
    };
}

function topicRanking(res: any): any[] {
    return (res?.ranking || []).map((r: any) => ({
        company_name: r.topic_name,
        brand_name: r.topic_name,
        mention_count: r.mention_count,
        visibility_pct: r.own_sov_pct,
        sov_pct: r.sov_pct,
        avg_position: null,
        is_own: r.own_mention_count > 0,
        _own_count: r.own_mention_count,
        _own_sov_pct: r.own_sov_pct,
    }));
}

function sortStandaloneVisibilityResponse(
    response: any,
    sort: MetricSortState,
    dimension: "product" | "topic",
): any {
    if (!response || !Array.isArray(response.ranking)) return response;
    const textKey = dimension === "product" ? "product_name" : "topic_name";
    const idKey = dimension === "product" ? "product_name" : "topic_id";
    return {
        ...response,
        ranking: sortCompleteMetricRows(response.ranking, response.ranking.length, {
            ...sort,
            tieTextKey: textKey,
            tieIdKey: idKey,
        }),
    };
}

function normalizeTopic(visibilityRes: any, sovRes: any): any {
    if (!visibilityRes || visibilityRes.reason === "no_data") {
        return { summary: { visibility_score: 0 }, sov_ranking: [], time_series: [], avg_position_series: [], competitive_series: {} };
    }
    const total = visibilityRes.totals?.mentions || 0;
    const own = visibilityRes.totals?.own_mentions || 0;
    const ownSov = total > 0 ? Math.round((own / total) * 10000) / 100 : 0;
    return {
        summary: {
            visibility_score: ownSov,
            visibility_score_change: null,
            visibility_rank: null,
            total_mentions: total,
            own_mentions: own,
            avg_position: null,
            avg_position_change: null,
        },
        visibility_ranking: topicRanking(visibilityRes),
        sov_ranking: topicRanking(sovRes),
        prev_time_series: [],
        time_series: visibilityRes.time_series || [],
        avg_position_series: [],
        prev_avg_position_series: [],
        competitive_series: visibilityRes.top_entities_series || {},
    };
}

export default function Visibility({ clientIdOverride }: { clientIdOverride?: string }) {
    const { clientId: workspaceClientId } = useSaaS();
    const clientId = clientIdOverride ?? workspaceClientId;
    const { dateFrom, dateTo, interval, selectedTopics, selectedPlatforms, selectedCountries, viewBy, setViewBy, filtersReady } = useInsightsFilters();
    const [standaloneData, setStandaloneData] = useState<any>(null);
    const [scoreData, setScoreData] = useState<any>(null);
    const [brandRankingData, setBrandRankingData] = useState<any>(null);
    const [sovData, setSovData] = useState<any>(null);
    const [sovRankingData, setSovRankingData] = useState<any>(null);
    const [positionData, setPositionData] = useState<any>(null);
    const [positionRankingData, setPositionRankingData] = useState<any>(null);
    const [chartLoading, setChartLoading] = useState({
        score: false,
        visibilityRanking: false,
        sov: false,
        sovRanking: false,
        position: false,
        positionRanking: false,
    });
    const requestSeq = useRef({ score: 0, visibilityRanking: 0, sov: 0, sovRanking: 0, position: 0, positionRanking: 0 });
    const [rankingSorts, setRankingSorts] = useState<VisibilityRankingSorts>({
        visibility: { metricKey: "visibility_pct", direction: "desc" },
        sov: { metricKey: "mention_count", direction: "desc" },
        position: { metricKey: "avg_position", direction: "asc" },
    });
    const [productRankingSorts, setProductRankingSorts] = useState<VisibilityRankingSorts>(() => buildStandaloneVisibilitySorts("product"));
    const [topicRankingSorts, setTopicRankingSorts] = useState<VisibilityRankingSorts>(() => buildStandaloneVisibilitySorts("topic"));

    // Self-correct when this page is entered with viewBy=cross (can happen
    // if the user navigated from /insights/channel-analysis via the tab
    // nav without re-picking a dimension). Snap back to brand — the
    // Visibility page has no cross chart to render.
    useEffect(() => {
        if (viewBy === "cross") setViewBy("brand");
    }, [viewBy, setViewBy]);

    // Effective dimension: treat "cross" as "brand" for this render pass
    // until the setViewBy above propagates on the next tick.
    const effectiveDim: Dim = viewBy === "cross" ? "brand" : (viewBy as Dim);
    const dashboardRankingSorts = effectiveDim === "brand"
        ? rankingSorts
        : effectiveDim === "product"
            ? productRankingSorts
            : topicRankingSorts;

    const handleRankingSortChange = (list: keyof VisibilityRankingSorts, next: MetricSortState) => {
        if (effectiveDim === "brand") {
            setRankingSorts((current) => ({ ...current, [list]: next }));
            return;
        }
        if (effectiveDim === "product") {
            setProductRankingSorts((current) => ({ ...current, [list]: next }));
        } else {
            setTopicRankingSorts((current) => ({ ...current, [list]: next }));
        }
    };

    const filterKey = useMemo(() => JSON.stringify({
        dateFrom,
        dateTo,
        interval,
        selectedTopics,
        selectedPlatforms,
        selectedCountries,
        effectiveDim,
    }), [dateFrom, dateTo, interval, selectedTopics, selectedPlatforms, selectedCountries, effectiveDim]);
    const debouncedFilterKey = useDebouncedValue(filterKey, 200);
    const debouncedFilters = useMemo(() => JSON.parse(debouncedFilterKey) as {
        dateFrom: string;
        dateTo: string;
        interval: string;
        selectedTopics: string[];
        selectedPlatforms: string[];
        selectedCountries: string[];
        effectiveDim: Dim;
    }, [debouncedFilterKey]);

    const requestParams = useMemo(() => {
        const params: Record<string, string> = {
            date_from: debouncedFilters.dateFrom,
            date_to: debouncedFilters.dateTo,
            interval: debouncedFilters.interval,
        };
        if (debouncedFilters.selectedTopics.length > 0) params.topic_ids = debouncedFilters.selectedTopics.join(",");
        if (debouncedFilters.selectedPlatforms.length > 0) params.platform = debouncedFilters.selectedPlatforms.join(",");
        if (debouncedFilters.selectedCountries.length > 0) params.country = debouncedFilters.selectedCountries.join(",");
        return params;
    }, [debouncedFilters]);

    useEffect(() => {
        const timer = window.setTimeout(() => {
            setStandaloneData(null);
            setScoreData(null);
            setBrandRankingData(null);
            setSovData(null);
            setSovRankingData(null);
            setPositionData(null);
            setPositionRankingData(null);
            setChartLoading({ score: true, visibilityRanking: true, sov: true, sovRanking: true, position: true, positionRanking: true });
        }, 0);
        return () => window.clearTimeout(timer);
    }, [clientId, debouncedFilters.effectiveDim]);

    useEffect(() => {
        if (!clientId || !filtersReady) return;
        if (debouncedFilters.effectiveDim !== "brand") return;
        const controller = new AbortController();
        const requestId = ++requestSeq.current.score;
        const timer = window.setTimeout(() => {
            setChartLoading((current) => ({ ...current, score: true }));
            getVisibilityScore(clientId, requestParams, { signal: controller.signal }).then((response) => {
                if (requestId !== requestSeq.current.score) return;
                setScoreData(response);
            }).catch((error) => {
                if (error?.name !== "AbortError" && requestId === requestSeq.current.score) setScoreData(null);
            }).finally(() => {
                if (requestId === requestSeq.current.score) setChartLoading((current) => ({ ...current, score: false }));
            });
        }, REQUEST_START_DELAY_MS);
        return () => { window.clearTimeout(timer); controller.abort(); };
    }, [clientId, filtersReady, debouncedFilters.effectiveDim, requestParams]);

    useEffect(() => {
        if (!clientId || !filtersReady || debouncedFilters.effectiveDim === "brand") return;
        const controller = new AbortController();
        const requestId = ++requestSeq.current.visibilityRanking;
        const timer = window.setTimeout(() => {
            setChartLoading((current) => ({
                ...current,
                score: true,
                visibilityRanking: true,
                sov: true,
                sovRanking: true,
                position: debouncedFilters.effectiveDim === "product",
                positionRanking: debouncedFilters.effectiveDim === "product",
            }));
            const request = debouncedFilters.effectiveDim === "product"
                ? getProductVisibility(clientId, { product_role: "own", ...requestParams }, { signal: controller.signal })
                : getTopicVisibility(clientId, requestParams, { signal: controller.signal });
            request.then((response) => {
                if (requestId === requestSeq.current.visibilityRanking) setStandaloneData(response);
            }).catch((error) => {
                if (error?.name !== "AbortError" && requestId === requestSeq.current.visibilityRanking) setStandaloneData(null);
            }).finally(() => {
                if (requestId !== requestSeq.current.visibilityRanking) return;
                setChartLoading((current) => ({
                    ...current,
                    score: false,
                    visibilityRanking: false,
                    sov: false,
                    sovRanking: false,
                    position: false,
                    positionRanking: false,
                }));
            });
        }, REQUEST_START_DELAY_MS);
        return () => { window.clearTimeout(timer); controller.abort(); };
    }, [clientId, filtersReady, debouncedFilters.effectiveDim, requestParams]);

    useEffect(() => {
        if (!clientId || !filtersReady || debouncedFilters.effectiveDim !== "brand") return;
        const controller = new AbortController();
        const requestId = ++requestSeq.current.visibilityRanking;
        const timer = window.setTimeout(() => {
            setChartLoading((current) => ({ ...current, visibilityRanking: true }));
            getVisibilityBrandRanking(clientId, withMetricSortParams(requestParams, rankingSorts.visibility), { signal: controller.signal })
                .then((response) => { if (requestId === requestSeq.current.visibilityRanking) setBrandRankingData(response); })
                .catch((error) => { if (error?.name !== "AbortError" && requestId === requestSeq.current.visibilityRanking) setBrandRankingData(null); })
                .finally(() => { if (requestId === requestSeq.current.visibilityRanking) setChartLoading((current) => ({ ...current, visibilityRanking: false })); });
        }, REQUEST_START_DELAY_MS);
        return () => { window.clearTimeout(timer); controller.abort(); };
    }, [clientId, filtersReady, debouncedFilters.effectiveDim, rankingSorts.visibility, requestParams]);

    useEffect(() => {
        if (!clientId || !filtersReady || debouncedFilters.effectiveDim !== "brand") return;
        const controller = new AbortController();
        const requestId = ++requestSeq.current.sovRanking;
        const timer = window.setTimeout(() => {
            setChartLoading((current) => ({ ...current, sovRanking: true }));
            getVisibilitySovRanking(clientId, withMetricSortParams(requestParams, rankingSorts.sov), { signal: controller.signal }).then((response) => {
                if (requestId !== requestSeq.current.sovRanking) return;
                setSovRankingData(response);
            }).catch((error) => {
                if (error?.name !== "AbortError" && requestId === requestSeq.current.sovRanking) {
                    setSovRankingData(null);
                }
            }).finally(() => {
                if (requestId === requestSeq.current.sovRanking) setChartLoading((current) => ({ ...current, sovRanking: false }));
            });
        }, REQUEST_START_DELAY_MS);
        return () => { window.clearTimeout(timer); controller.abort(); };
    }, [clientId, filtersReady, debouncedFilters.effectiveDim, rankingSorts.sov, requestParams]);

    useEffect(() => {
        if (!clientId || !filtersReady || debouncedFilters.effectiveDim !== "brand") return;
        const controller = new AbortController();
        const requestId = ++requestSeq.current.sov;
        const timer = window.setTimeout(() => {
            setChartLoading((current) => ({ ...current, sov: true }));
            getVisibilitySov(clientId, requestParams, { signal: controller.signal })
                .then((response) => { if (requestId === requestSeq.current.sov) setSovData(response); })
                .catch((error) => { if (error?.name !== "AbortError" && requestId === requestSeq.current.sov) setSovData(null); })
                .finally(() => { if (requestId === requestSeq.current.sov) setChartLoading((current) => ({ ...current, sov: false })); });
        }, 0);
        return () => { window.clearTimeout(timer); controller.abort(); };
    }, [clientId, filtersReady, debouncedFilters.effectiveDim, requestParams]);

    useEffect(() => {
        if (!clientId || !filtersReady || debouncedFilters.effectiveDim !== "brand") return;
        const controller = new AbortController();
        const requestId = ++requestSeq.current.positionRanking;
        const timer = window.setTimeout(() => {
            setChartLoading((current) => ({ ...current, positionRanking: true }));
            getVisibilityPositionRanking(clientId, withMetricSortParams(requestParams, rankingSorts.position), { signal: controller.signal }).then((response) => {
                if (requestId !== requestSeq.current.positionRanking) return;
                setPositionRankingData(response);
            }).catch((error) => {
                if (error?.name !== "AbortError" && requestId === requestSeq.current.positionRanking) {
                    setPositionRankingData(null);
                }
            }).finally(() => {
                if (requestId === requestSeq.current.positionRanking) setChartLoading((current) => ({ ...current, positionRanking: false }));
            });
        }, 0);
        return () => { window.clearTimeout(timer); controller.abort(); };
    }, [clientId, filtersReady, debouncedFilters.effectiveDim, rankingSorts.position, requestParams]);

    useEffect(() => {
        if (!clientId || !filtersReady || debouncedFilters.effectiveDim !== "brand") return;
        const controller = new AbortController();
        const requestId = ++requestSeq.current.position;
        const timer = window.setTimeout(() => {
            setChartLoading((current) => ({ ...current, position: true }));
            getVisibilityPosition(clientId, requestParams, { signal: controller.signal })
                .then((response) => { if (requestId === requestSeq.current.position) setPositionData(response); })
                .catch((error) => { if (error?.name !== "AbortError" && requestId === requestSeq.current.position) setPositionData(null); })
                .finally(() => { if (requestId === requestSeq.current.position) setChartLoading((current) => ({ ...current, position: false })); });
        }, 0);
        return () => { window.clearTimeout(timer); controller.abort(); };
    }, [clientId, filtersReady, debouncedFilters.effectiveDim, requestParams]);

    const brandChartData = useMemo(() => {
        const scoreSummary = scoreData?.summary || {};
        const brandRankingSummary = brandRankingData?.summary || {};
        const sovSummary = sovData?.summary || {};
        const sovRankingSummary = sovRankingData?.summary || {};
        const positionSummary = positionData?.summary || {};
        const positionRankingSummary = positionRankingData?.summary || {};
        const summary = {
            ...scoreSummary,
            visibility_rank: brandRankingSummary.visibility_rank ?? null,
            visibility_rank_change: brandRankingSummary.visibility_rank_change ?? null,
            sov_pct: sovSummary.sov_pct ?? null,
            sov_pct_change: sovSummary.sov_pct_change ?? null,
            total_mentions: sovSummary.total_mentions ?? 0,
            own_mentions: sovSummary.own_mentions ?? 0,
            sov_rank: sovRankingSummary.sov_rank ?? sovSummary.sov_rank ?? null,
            sov_rank_change: sovRankingSummary.sov_rank_change ?? sovSummary.sov_rank_change ?? null,
            avg_position: positionSummary.avg_position ?? null,
            avg_position_change: positionSummary.avg_position_change ?? null,
            avg_position_rank: positionRankingSummary.avg_position_rank ?? positionSummary.avg_position_rank ?? null,
            avg_position_rank_change: positionRankingSummary.avg_position_rank_change ?? positionSummary.avg_position_rank_change ?? null,
        };
        return {
            summary,
            time_series: scoreData?.time_series || [],
            prev_time_series: scoreData?.prev_time_series || [],
            visibility_ranking: brandRankingData?.visibility_ranking || [],
            sov_ranking: sovRankingData?.sov_ranking || sovData?.sov_ranking || [],
            avg_position_series: positionData?.avg_position_series || [],
            prev_avg_position_series: positionData?.prev_avg_position_series || [],
            position_ranking: positionRankingData?.position_ranking || positionData?.position_ranking || [],
            competitive_series: sovData?.competitive_series || {},
            topic_sov_ranking: [],
            product_sov_ranking: [],
            filters: scoreData?.filters || sovData?.filters || positionData?.filters || {},
        };
    }, [scoreData, brandRankingData, sovData, sovRankingData, positionData, positionRankingData]);

    const standaloneVisibilityResponse = useMemo(() => sortStandaloneVisibilityResponse(
        standaloneData,
        debouncedFilters.effectiveDim === "product" ? productRankingSorts.visibility : topicRankingSorts.visibility,
        debouncedFilters.effectiveDim === "product" ? "product" : "topic",
    ), [debouncedFilters.effectiveDim, productRankingSorts.visibility, standaloneData, topicRankingSorts.visibility]);
    const standaloneSovResponse = useMemo(() => sortStandaloneVisibilityResponse(
        standaloneData,
        debouncedFilters.effectiveDim === "product" ? productRankingSorts.sov : topicRankingSorts.sov,
        debouncedFilters.effectiveDim === "product" ? "product" : "topic",
    ), [debouncedFilters.effectiveDim, productRankingSorts.sov, standaloneData, topicRankingSorts.sov]);
    const standalonePositionResponse = useMemo(() => sortStandaloneVisibilityResponse(
        standaloneData,
        productRankingSorts.position,
        "product",
    ), [productRankingSorts.position, standaloneData]);

    const effectiveData = debouncedFilters.effectiveDim === "brand"
        ? brandChartData
        : debouncedFilters.effectiveDim === "product"
            ? normalizeProduct(standaloneVisibilityResponse, standaloneSovResponse, standalonePositionResponse)
            : normalizeTopic(standaloneVisibilityResponse, standaloneSovResponse);
    const dashboardLoading = debouncedFilters.effectiveDim === "brand"
        ? chartLoading
        : {
            ...chartLoading,
            score: chartLoading.visibilityRanking,
            sov: chartLoading.sovRanking,
            position: false,
            positionRanking: debouncedFilters.effectiveDim === "topic" ? false : chartLoading.positionRanking,
        };

    return (
        <VisibilityDashboard
            timeSeriesComplete
            data={effectiveData}
            dimension={debouncedFilters.effectiveDim}
            loadingSections={dashboardLoading}
            rankingMatrixQuery={debouncedFilters.effectiveDim === "brand" && clientId ? { clientId, params: {
                date_from: debouncedFilters.dateFrom,
                date_to: debouncedFilters.dateTo,
                ...(debouncedFilters.selectedTopics.length > 0 ? { topic_ids: debouncedFilters.selectedTopics.join(",") } : {}),
                ...(debouncedFilters.selectedPlatforms.length > 0 ? { platform: debouncedFilters.selectedPlatforms.join(",") } : {}),
                ...(debouncedFilters.selectedCountries.length > 0 ? { country: debouncedFilters.selectedCountries.join(",") } : {}),
            } } : undefined}
            rankingSorts={dashboardRankingSorts}
            onRankingSortChange={handleRankingSortChange}
        />
    );
}
