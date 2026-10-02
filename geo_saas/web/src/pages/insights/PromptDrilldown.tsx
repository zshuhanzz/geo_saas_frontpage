import { useEffect, useMemo, useRef, useState } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { ArrowLeft, Loader2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import VisibilityDashboard from "@/components/insights/VisibilityDashboard";
import type { VisibilityRankingSorts } from "@/components/insights/VisibilityDashboard";
import CitationDashboard from "@/components/insights/CitationDashboard";
import SentimentDashboard from "@/components/insights/SentimentDashboard";
import { useSaaS } from "@/contexts/SaaSContext";
import {
    getPromptConcept,
    getPrompts,
    getVisibilityBrandRanking,
    getVisibilityComposed,
    getVisibilityPositionRanking,
    getVisibilitySovRanking,
} from "@/lib/api";
import { useInsightsFilters } from "../Insights";
import {
    parsePromptDrilldownLocation,
    resolvePromptDrilldownFilters,
    type PromptConceptTarget,
    type PromptDrilldownRouteTarget,
} from "./promptDrilldownTarget";
import { type MetricSortState, withMetricSortParams } from "@/lib/metricSort";

interface ResolvedTargetContext {
    target: PromptDrilldownRouteTarget;
    concept?: PromptConceptTarget;
    label: string;
    topicLabel: string;
    productLabel?: string;
}

interface WorkspaceTopic {
    id: string;
    topic_name?: string;
}

type ResolutionState =
    | { status: "loading" }
    | { status: "invalid" }
    | { status: "ready"; value: ResolvedTargetContext };

function topicName(topics: WorkspaceTopic[], topicId: string): string {
    const topic = topics.find((item) => item.id === topicId);
    return topic?.topic_name || topicId;
}

function isAbortError(error: unknown): boolean {
    return error instanceof DOMException && error.name === "AbortError";
}

function visibilityParams(filters: ReturnType<typeof resolvePromptDrilldownFilters> | null): Record<string, string> {
    if (!filters) return {};
    return {
        date_from: filters.dateFrom,
        date_to: filters.dateTo,
        interval: filters.interval,
        topic_ids: filters.topicIds.join(","),
        ...(filters.platforms.length > 0 ? { platform: filters.platforms.join(",") } : {}),
        ...(filters.countries.length > 0 ? { country: filters.countries.join(",") } : {}),
        ...(filters.promptTypes.length > 0 ? { prompt_type: filters.promptTypes.join(",") } : {}),
        ...(filters.products?.length ? { product: filters.products[0] } : {}),
        ...(filters.promptIds?.length ? { prompt_ids: filters.promptIds.join(",") } : {}),
    };
}

function isDefaultVisibilityListSort(list: keyof VisibilityRankingSorts, sort: MetricSortState) {
    const defaults: VisibilityRankingSorts = {
        visibility: { metricKey: "visibility_pct", direction: "desc" },
        sov: { metricKey: "mention_count", direction: "desc" },
        position: { metricKey: "avg_position", direction: "asc" },
    };
    return sort.metricKey === defaults[list].metricKey && sort.direction === defaults[list].direction;
}

export default function PromptDrilldown() {
    const { t } = useTranslation("insights");
    const navigate = useNavigate();
    const location = useLocation();
    const { clients, clientId, loadingClients } = useSaaS();
    const {
        dateFrom,
        dateTo,
        interval,
        selectedTopics,
        selectedPlatforms,
        selectedCountries,
        selectedPromptTypes,
        filtersReady,
    } = useInsightsFilters();
    const activeClient = clients.find((client) => client.id === clientId);
    const topics = useMemo(
        () => (activeClient?.topics || []) as WorkspaceTopic[],
        [activeClient?.topics],
    );
    const routeTarget = useMemo(
        () => parsePromptDrilldownLocation(location.pathname, location.search),
        [location.pathname, location.search],
    );
    const [resolution, setResolution] = useState<ResolutionState>({ status: "loading" });
    const resolutionSeq = useRef(0);

    useEffect(() => {
        const requestId = ++resolutionSeq.current;
        const controller = new AbortController();
        const timer = window.setTimeout(() => {
            if (!routeTarget) {
                setResolution({ status: "invalid" });
                return;
            }
            if (!clientId || loadingClients || !activeClient) {
                setResolution({ status: "loading" });
                return;
            }

            setResolution({ status: "loading" });
            const resolve = async () => {
                if (routeTarget.kind === "topic") {
                    if (!topics.some((topic) => topic.id === routeTarget.topicId)) {
                        setResolution({ status: "invalid" });
                        return;
                    }
                    setResolution({
                        status: "ready",
                        value: {
                            target: routeTarget,
                            label: topicName(topics, routeTarget.topicId),
                            topicLabel: topicName(topics, routeTarget.topicId),
                        },
                    });
                    return;
                }

                if (routeTarget.kind === "product") {
                    if (!topics.some((topic) => topic.id === routeTarget.topicId)) {
                        setResolution({ status: "invalid" });
                        return;
                    }
                    const rows = await getPrompts(
                        clientId,
                        { topic_id: routeTarget.topicId, is_active: "true" },
                        { signal: controller.signal },
                    );
                    const match = rows.find((row) => String(row.product || "").trim() === routeTarget.product);
                    if (!match) {
                        if (requestId === resolutionSeq.current) setResolution({ status: "invalid" });
                        return;
                    }
                    const canonicalProduct = String(match.product).trim();
                    if (requestId === resolutionSeq.current) {
                        setResolution({
                            status: "ready",
                            value: {
                                target: { kind: "product", topicId: routeTarget.topicId, product: canonicalProduct },
                                label: canonicalProduct,
                                topicLabel: topicName(topics, routeTarget.topicId),
                                productLabel: canonicalProduct,
                            },
                        });
                    }
                    return;
                }

                const response = await getPromptConcept(clientId, routeTarget.promptId, { signal: controller.signal });
                const representative = response.representative;
                if (
                    representative.client_id !== clientId
                    || !topics.some((topic) => topic.id === representative.topic_id)
                    || response.prompt_ids.length === 0
                ) {
                    if (requestId === resolutionSeq.current) setResolution({ status: "invalid" });
                    return;
                }
                const concept: PromptConceptTarget = {
                    topic_id: representative.topic_id,
                    product: representative.product,
                    prompt_ids: response.prompt_ids,
                };
                if (requestId === resolutionSeq.current) {
                    setResolution({
                        status: "ready",
                        value: {
                            target: routeTarget,
                            concept,
                            label: representative.text,
                            topicLabel: topicName(topics, representative.topic_id),
                            productLabel: representative.product || undefined,
                        },
                    });
                }
            };

            resolve().catch((error: unknown) => {
                if (!isAbortError(error) && requestId === resolutionSeq.current) {
                    setResolution({ status: "invalid" });
                }
            });
        }, 0);
        return () => {
            window.clearTimeout(timer);
            controller.abort();
        };
    }, [activeClient, clientId, loadingClients, routeTarget, topics]);

    const commonFilters = useMemo(() => ({
        dateFrom,
        dateTo,
        interval,
        topicIds: [...selectedTopics],
        platforms: [...selectedPlatforms],
        countries: [...selectedCountries],
        promptTypes: [...selectedPromptTypes],
    }), [dateFrom, dateTo, interval, selectedTopics, selectedPlatforms, selectedCountries, selectedPromptTypes]);

    const resolvedFilters = useMemo(() => resolution.status === "ready"
        ? resolvePromptDrilldownFilters(commonFilters, resolution.value.target, resolution.value.concept)
        : null, [commonFilters, resolution]);
    const [visibilityData, setVisibilityData] = useState<unknown>(null);
    const [visibilityLoading, setVisibilityLoading] = useState(false);
    const [visibilityError, setVisibilityError] = useState(false);
    const visibilitySeq = useRef(0);
    const rankingSeq = useRef({ visibility: 0, sov: 0, position: 0 });
    const [visibilityRankingOverride, setVisibilityRankingOverride] = useState<any>(null);
    const [sovRankingOverride, setSovRankingOverride] = useState<any>(null);
    const [positionRankingOverride, setPositionRankingOverride] = useState<any>(null);
    const [rankingLoading, setRankingLoading] = useState({ visibility: false, sov: false, position: false });
    const [visibilitySorts, setVisibilitySorts] = useState<VisibilityRankingSorts>({
        visibility: { metricKey: "visibility_pct", direction: "desc" },
        sov: { metricKey: "mention_count", direction: "desc" },
        position: { metricKey: "avg_position", direction: "asc" },
    });

    const handleVisibilitySortChange = (list: keyof VisibilityRankingSorts, next: MetricSortState) => {
        setVisibilitySorts((current) => ({ ...current, [list]: next }));
    };
    const resolvedVisibilityParams = useMemo(() => visibilityParams(resolvedFilters), [resolvedFilters]);

    useEffect(() => {
        const controller = new AbortController();
        const requestId = ++visibilitySeq.current;
        const timer = window.setTimeout(() => {
            if (!clientId || !filtersReady || !resolvedFilters || resolvedFilters.emptyIntersection) {
                setVisibilityData(null);
                setVisibilityLoading(false);
                setVisibilityError(false);
                return;
            }
            setVisibilityLoading(true);
            setVisibilityError(false);
            setVisibilityData(null);
            setVisibilityRankingOverride(null);
            setSovRankingOverride(null);
            setPositionRankingOverride(null);
            getVisibilityComposed(clientId, resolvedVisibilityParams, { signal: controller.signal })
                .then((response) => {
                    if (requestId === visibilitySeq.current) setVisibilityData(response);
                })
                .catch((error: unknown) => {
                    if (!isAbortError(error) && requestId === visibilitySeq.current) {
                        setVisibilityError(true);
                    }
                })
                .finally(() => {
                    if (requestId === visibilitySeq.current) setVisibilityLoading(false);
                });
        }, 0);
        return () => {
            window.clearTimeout(timer);
            controller.abort();
        };
    }, [clientId, filtersReady, resolvedFilters, resolvedVisibilityParams]);

    useEffect(() => {
        if (isDefaultVisibilityListSort("visibility", visibilitySorts.visibility)) {
            rankingSeq.current.visibility += 1;
            return;
        }
        if (!clientId || !filtersReady || !resolvedFilters || resolvedFilters.emptyIntersection) return;
        const controller = new AbortController();
        const requestId = ++rankingSeq.current.visibility;
        const timer = window.setTimeout(() => {
            setRankingLoading((current) => ({ ...current, visibility: true }));
            getVisibilityBrandRanking(clientId, withMetricSortParams(resolvedVisibilityParams, visibilitySorts.visibility), { signal: controller.signal })
                .then((response) => { if (requestId === rankingSeq.current.visibility) setVisibilityRankingOverride(response); })
                .catch(() => undefined)
                .finally(() => { if (requestId === rankingSeq.current.visibility) setRankingLoading((current) => ({ ...current, visibility: false })); });
        }, 0);
        return () => { window.clearTimeout(timer); controller.abort(); };
    }, [clientId, filtersReady, resolvedFilters, resolvedVisibilityParams, visibilitySorts.visibility]);

    useEffect(() => {
        if (isDefaultVisibilityListSort("sov", visibilitySorts.sov)) {
            rankingSeq.current.sov += 1;
            return;
        }
        if (!clientId || !filtersReady || !resolvedFilters || resolvedFilters.emptyIntersection) return;
        const controller = new AbortController();
        const requestId = ++rankingSeq.current.sov;
        const timer = window.setTimeout(() => {
            setRankingLoading((current) => ({ ...current, sov: true }));
            getVisibilitySovRanking(clientId, withMetricSortParams(resolvedVisibilityParams, visibilitySorts.sov), { signal: controller.signal })
                .then((response) => { if (requestId === rankingSeq.current.sov) setSovRankingOverride(response); })
                .catch(() => undefined)
                .finally(() => { if (requestId === rankingSeq.current.sov) setRankingLoading((current) => ({ ...current, sov: false })); });
        }, 0);
        return () => { window.clearTimeout(timer); controller.abort(); };
    }, [clientId, filtersReady, resolvedFilters, resolvedVisibilityParams, visibilitySorts.sov]);

    useEffect(() => {
        if (isDefaultVisibilityListSort("position", visibilitySorts.position)) {
            rankingSeq.current.position += 1;
            return;
        }
        if (!clientId || !filtersReady || !resolvedFilters || resolvedFilters.emptyIntersection) return;
        const controller = new AbortController();
        const requestId = ++rankingSeq.current.position;
        const timer = window.setTimeout(() => {
            setRankingLoading((current) => ({ ...current, position: true }));
            getVisibilityPositionRanking(clientId, withMetricSortParams(resolvedVisibilityParams, visibilitySorts.position), { signal: controller.signal })
                .then((response) => { if (requestId === rankingSeq.current.position) setPositionRankingOverride(response); })
                .catch(() => undefined)
                .finally(() => { if (requestId === rankingSeq.current.position) setRankingLoading((current) => ({ ...current, position: false })); });
        }, 0);
        return () => { window.clearTimeout(timer); controller.abort(); };
    }, [clientId, filtersReady, resolvedFilters, resolvedVisibilityParams, visibilitySorts.position]);

    const mergedVisibilityData = useMemo(() => {
        if (!visibilityData || typeof visibilityData !== "object") return visibilityData;
        const base = visibilityData as Record<string, any>;
        return {
            ...base,
            summary: {
                ...(base.summary || {}),
                ...(!isDefaultVisibilityListSort("visibility", visibilitySorts.visibility) ? visibilityRankingOverride?.summary || {} : {}),
                ...(!isDefaultVisibilityListSort("sov", visibilitySorts.sov) ? sovRankingOverride?.summary || {} : {}),
                ...(!isDefaultVisibilityListSort("position", visibilitySorts.position) ? positionRankingOverride?.summary || {} : {}),
            },
            visibility_ranking: !isDefaultVisibilityListSort("visibility", visibilitySorts.visibility) ? visibilityRankingOverride?.visibility_ranking || base.visibility_ranking || [] : base.visibility_ranking || [],
            sov_ranking: !isDefaultVisibilityListSort("sov", visibilitySorts.sov) ? sovRankingOverride?.sov_ranking || base.sov_ranking || [] : base.sov_ranking || [],
            position_ranking: !isDefaultVisibilityListSort("position", visibilitySorts.position) ? positionRankingOverride?.position_ranking || base.position_ranking || [] : base.position_ranking || [],
        };
    }, [positionRankingOverride, sovRankingOverride, visibilityData, visibilityRankingOverride, visibilitySorts]);

    if (resolution.status === "loading") {
        return (
            <div className="flex items-center justify-center py-24">
                <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
        );
    }
    if (resolution.status === "invalid" || !resolvedFilters) {
        return (
            <div className="space-y-4 p-6">
                <p className="text-sm text-muted-foreground">{t("prompts.drilldown.targetUnavailable")}</p>
                <Button variant="outline" onClick={() => navigate("/insights/prompts")}>
                    <ArrowLeft className="mr-2 h-4 w-4" />
                    {t("prompts.drilldown.back")}
                </Button>
            </div>
        );
    }

    const typeLabel = t(`prompts.drilldown.targetType.${resolution.value.target.kind}`);
    const dashboardFilters = {
        dateFrom: resolvedFilters.dateFrom,
        dateTo: resolvedFilters.dateTo,
        interval: resolvedFilters.interval,
        topicIds: resolvedFilters.topicIds,
        platforms: resolvedFilters.platforms,
        countries: resolvedFilters.countries,
        promptTypes: resolvedFilters.promptTypes,
        products: resolvedFilters.products,
        promptIds: resolvedFilters.promptIds,
    };
    const rankingParams: Record<string, string> = {
        date_from: resolvedFilters.dateFrom,
        date_to: resolvedFilters.dateTo,
        topic_ids: resolvedFilters.topicIds.join(","),
        ...(resolvedFilters.platforms.length > 0 ? { platform: resolvedFilters.platforms.join(",") } : {}),
        ...(resolvedFilters.countries.length > 0 ? { country: resolvedFilters.countries.join(",") } : {}),
        ...(resolvedFilters.promptTypes.length > 0 ? { prompt_type: resolvedFilters.promptTypes.join(",") } : {}),
        ...(resolvedFilters.products?.length ? { product: resolvedFilters.products[0] } : {}),
        ...(resolvedFilters.promptIds?.length ? { prompt_ids: resolvedFilters.promptIds.join(",") } : {}),
    };

    return (
        <div className="space-y-10 p-6 animate-in slide-in-from-right">
            <header className="space-y-3">
                <Button variant="ghost" className="px-0" onClick={() => navigate("/insights/prompts")}>
                    <ArrowLeft className="mr-2 h-4 w-4" />
                    {t("prompts.drilldown.back")}
                </Button>
                <div>
                    <p className="text-xs font-medium uppercase tracking-wide text-muted-foreground">{typeLabel}</p>
                    <h2 className="mt-1 text-2xl font-semibold break-words">{resolution.value.label}</h2>
                    <p className="mt-1 text-sm text-muted-foreground">
                        {t("prompts.drilldown.context", {
                            topic: resolution.value.topicLabel,
                            product: resolution.value.productLabel || t("prompts.fallback.noProduct"),
                        })}
                    </p>
                </div>
            </header>

            {resolvedFilters.emptyIntersection ? (
                <div className="rounded-lg border p-8 text-center text-sm text-muted-foreground">
                    {t("prompts.drilldown.emptyIntersection")}
                </div>
            ) : (
                <>
                    <section className="space-y-4">
                        <h3 className="text-xl font-semibold">{t("prompts.drilldown.sections.visibility")}</h3>
                        {visibilityLoading ? (
                            <div className="flex items-center justify-center py-24"><Loader2 className="h-6 w-6 animate-spin text-muted-foreground" /></div>
                        ) : visibilityError ? (
                            <div className="rounded-lg border p-8 text-center text-sm text-muted-foreground">{t("prompts.drilldown.domainLoadFailed")}</div>
                        ) : (
                            <VisibilityDashboard
                                timeSeriesComplete
                                data={mergedVisibilityData}
                                loadingSections={{
                                    visibilityRanking: !isDefaultVisibilityListSort("visibility", visibilitySorts.visibility) && rankingLoading.visibility,
                                    sovRanking: !isDefaultVisibilityListSort("sov", visibilitySorts.sov) && rankingLoading.sov,
                                    positionRanking: !isDefaultVisibilityListSort("position", visibilitySorts.position) && rankingLoading.position,
                                }}
                                rankingMatrixQuery={{ clientId, params: rankingParams }}
                                rankingSorts={visibilitySorts}
                                onRankingSortChange={handleVisibilitySortChange}
                            />
                        )}
                    </section>
                    <section className="space-y-4 border-t pt-8">
                        <h3 className="text-xl font-semibold">{t("prompts.drilldown.sections.citation")}</h3>
                        <CitationDashboard
                            clientId={clientId}
                            filters={dashboardFilters}
                            filtersReady={filtersReady}
                            mode="drilldown"
                        />
                    </section>
                    <section className="space-y-4 border-t pt-8">
                        <h3 className="text-xl font-semibold">{t("prompts.drilldown.sections.sentiment")}</h3>
                        <SentimentDashboard
                            clientId={clientId}
                            filters={dashboardFilters}
                            filtersReady={filtersReady}
                            mode="drilldown"
                        />
                    </section>
                </>
            )}
        </div>
    );
}
