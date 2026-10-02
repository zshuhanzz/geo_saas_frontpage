/**
 * ChannelAnalysisPage — Spec §8 "渠道分析" tab.
 *
 * The user's mental model (2026-04-21 feedback): the View-By dimension on
 * this page answers "经销渠道 × 什么":
 *
 *   brand   → 渠道 × 自家品牌  (which own brand gets co-mentioned per channel)
 *   product → 渠道 × 自家产品  (which own SKU gets co-mentioned per channel)
 *   topic   → 渠道 × 话题      (which topic is each channel riding on)
 *
 * Charts 1-3 all react to viewBy; Chart 4 (citation distribution) is
 * dimension-independent and stays visible in all modes.
 *
 * Only surfaced when `availability.has_shadow_brands === true`. All charts
 * degrade to <EmptyStateCard> when the endpoint returns `{reason: "no_data"}`.
 */
import { useEffect, useMemo, useState, type ReactElement } from "react";
import {
    BarChart,
    Bar,
    XAxis,
    YAxis,
    Tooltip,
    ResponsiveContainer,
    Legend,
    PieChart,
    Pie,
    Cell,
    CartesianGrid,
} from "recharts";
import { Loader2, PackageSearch, Store, Layers, Quote, Tag, Building2 } from "lucide-react";
import { useSaaS } from "@/contexts/SaaSContext";
import { useInsightsFilters } from "../Insights";
import {
    getShadowProductCooccurrence,
    getShadowBrandCooccurrence,
    getShadowTopicCooccurrence,
    getCitationByRole,
} from "@/lib/api";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { GlassTooltip } from "@/components/ui/chart-tooltip";
import { useTranslation } from "react-i18next";
import HelpTooltip from "@/components/ui/HelpTooltip";
import EmptyStateCard from "@/components/EmptyStateCard";
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from "@/components/ui/select";

const COLORS = [
    "#10b981",
    "#3b82f6",
    "#f59e0b",
    "#ef4444",
    "#8b5cf6",
    "#ec4899",
    "#14b8a6",
    "#f97316",
    "#6366f1",
    "#84cc16",
];

// Normalized cross row: shadow brand × (secondary entity), with the entity
// name carried under a dimension-agnostic key so the pivot logic below can
// operate over all three modes uniformly.
interface CrossRow {
    shadow_brand_name: string;
    secondary_name: string;
    cooccurrence_count: number;
}

interface CitationByRoleRow {
    citation_role: string;
    citation_count: number;
    share_pct: number;
}

// Per-dimension config bundles — fetcher + secondary field + UI copy. Adding
// a new cross dimension becomes "add one entry here + one backend endpoint".
const DIM_CONFIG: Record<
    "brand" | "product" | "topic",
    {
        fetcher: (clientId: string, params: Record<string, string>) => Promise<any>;
        secondaryField: string;
        dimKey: "brand" | "product" | "topic";
        icon: ReactElement;
    }
> = {
    brand: {
        fetcher: getShadowBrandCooccurrence,
        secondaryField: "own_brand_name",
        dimKey: "brand",
        icon: <Building2 className="h-5 w-5 text-primary" />,
    },
    product: {
        fetcher: getShadowProductCooccurrence,
        secondaryField: "own_product_name",
        dimKey: "product",
        icon: <PackageSearch className="h-5 w-5 text-primary" />,
    },
    topic: {
        fetcher: getShadowTopicCooccurrence,
        secondaryField: "topic_name",
        dimKey: "topic",
        icon: <Tag className="h-5 w-5 text-primary" />,
    },
};

export default function ChannelAnalysisPage() {
    const { t } = useTranslation("insights");
    const { clientId } = useSaaS();
    const { dateFrom, dateTo } = useInsightsFilters();

    const [crossDimension, setCrossDimension] = useState<"brand" | "product" | "topic">("product");
    const effectiveDim = crossDimension;
    const cfg = DIM_CONFIG[effectiveDim];

    const [cross, setCross] = useState<CrossRow[] | null>(null);
    const [crossReason, setCrossReason] = useState<string | null>(null);
    const [crossLoading, setCrossLoading] = useState(true);
    const [citationRoles, setCitationRoles] = useState<CitationByRoleRow[] | null>(null);
    const [citationLoading, setCitationLoading] = useState(true);

    // ---- Fetch the dimension-specific cross matrix -------------------
    useEffect(() => {
        if (!clientId) return;
        setCrossLoading(true);
        const params = { date_from: dateFrom, date_to: dateTo };
        cfg.fetcher(clientId, params)
            .then((res: any) => {
                const raw: any[] = Array.isArray(res?.data) ? res.data : [];
                const normalized: CrossRow[] = raw.map((r) => ({
                    shadow_brand_name: r.shadow_brand_name,
                    secondary_name: r[cfg.secondaryField],
                    cooccurrence_count: r.cooccurrence_count,
                }));
                setCross(normalized);
                setCrossReason(typeof res?.reason === "string" ? res.reason : null);
            })
            .catch(() => {
                setCross([]);
                setCrossReason("request_failed");
            })
            .finally(() => setCrossLoading(false));
    }, [clientId, dateFrom, dateTo, effectiveDim, cfg]);

    // ---- Fetch citation role distribution (dimension-independent) ----
    useEffect(() => {
        if (!clientId) return;
        setCitationLoading(true);
        getCitationByRole(clientId, { date_from: dateFrom, date_to: dateTo })
            .then((res: any) => {
                setCitationRoles(Array.isArray(res?.data) ? res.data : []);
            })
            .catch(() => setCitationRoles([]))
            .finally(() => setCitationLoading(false));
    }, [clientId, dateFrom, dateTo]);

    // ---- Derived views -------------------------------------------------

    const topPairs = useMemo(() => {
        if (!cross) return [];
        return [...cross]
            .sort((a, b) => b.cooccurrence_count - a.cooccurrence_count)
            .slice(0, 10)
            .map((r) => ({
                label: `${r.shadow_brand_name} × ${r.secondary_name}`,
                count: r.cooccurrence_count,
            }));
    }, [cross]);

    const { brandPivot, brandKeys, secondaryPivot, secondaryKeys } = useMemo(() => {
        if (!cross || cross.length === 0) {
            return { brandPivot: [], brandKeys: [], secondaryPivot: [], secondaryKeys: [] };
        }

        // shadow_brand → { secondary_name: count }
        const brandMap = new Map<string, Record<string, number>>();
        const secondarySet = new Set<string>();
        for (const r of cross) {
            secondarySet.add(r.secondary_name);
            if (!brandMap.has(r.shadow_brand_name)) {
                brandMap.set(r.shadow_brand_name, {});
            }
            brandMap.get(r.shadow_brand_name)![r.secondary_name] = r.cooccurrence_count;
        }
        const bKeys = Array.from(secondarySet);
        const bPivot = Array.from(brandMap.entries()).map(([brand, counts]) => ({
            brand,
            ...counts,
        }));

        // secondary → { shadow_brand_name: count }
        const secondaryMap = new Map<string, Record<string, number>>();
        const brandSet = new Set<string>();
        for (const r of cross) {
            brandSet.add(r.shadow_brand_name);
            if (!secondaryMap.has(r.secondary_name)) {
                secondaryMap.set(r.secondary_name, {});
            }
            secondaryMap.get(r.secondary_name)![r.shadow_brand_name] = r.cooccurrence_count;
        }
        const pKeys = Array.from(brandSet);
        const pPivot = Array.from(secondaryMap.entries()).map(([secondary, counts]) => ({
            secondary,
            ...counts,
        }));

        return {
            brandPivot: bPivot,
            brandKeys: bKeys,
            secondaryPivot: pPivot,
            secondaryKeys: pKeys,
        };
    }, [cross]);

    const citationPieData = useMemo(() => {
        if (!citationRoles) return [];
        return citationRoles.map((r) => ({
            name: r.citation_role || "unclassified",
            value: r.citation_count,
            share: r.share_pct,
        }));
    }, [citationRoles]);

    const missingConfiguration = crossReason?.startsWith("missing_") ?? false;
    const emptyDescription = crossReason === "no_analyzed_product_mentions"
        ? t("channelAnalysis.emptyNoAnalyzedProductMentions")
        : crossReason === "request_failed"
            ? t("channelAnalysis.emptyRequestFailed")
            : crossReason === "missing_shadow_brand_configuration"
                ? t("channelAnalysis.emptyMissingShadowBrand")
                : crossReason === "missing_own_product_configuration"
                    ? t("channelAnalysis.emptyMissingOwnProduct")
                    : crossReason === "missing_own_brand_configuration"
                        ? t("channelAnalysis.emptyMissingOwnBrand")
                        : crossReason === "missing_topic_configuration"
                            ? t("channelAnalysis.emptyMissingTopic")
                            : effectiveDim === "topic"
                                ? t("channelAnalysis.emptyCooccurrenceDescTopic")
                                : effectiveDim === "brand"
                                    ? t("channelAnalysis.emptyCooccurrenceDescBrand")
                                    : t("channelAnalysis.emptyCooccurrenceDescProduct");

    const anyLoading = crossLoading || citationLoading;
    if (anyLoading) {
        return (
            <div className="flex items-center justify-center py-24">
                <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
            </div>
        );
    }

    return (
        <div className="space-y-8">
            <div className="flex items-center justify-end gap-2">
                <span className="text-xs text-muted-foreground">
                    {t("channelAnalysis.crossDimensionLabel")}
                </span>
                <Select
                    value={crossDimension}
                    onValueChange={(value) => setCrossDimension(value as "brand" | "product" | "topic")}
                >
                    <SelectTrigger className="h-9 w-[148px]">
                        <SelectValue />
                    </SelectTrigger>
                    <SelectContent>
                        <SelectItem value="product">{t("filters.viewBy.product")}</SelectItem>
                        <SelectItem value="topic">{t("filters.viewBy.topic")}</SelectItem>
                        <SelectItem value="brand">{t("filters.viewBy.brand")}</SelectItem>
                    </SelectContent>
                </Select>
            </div>

            {/* ========== Chart 1: top pairs (dimension-aware) ========== */}
            <section>
                <SectionHeader
                    icon={cfg.icon}
                    title={t(`channelAnalysis.dims.${cfg.dimKey}.pairLabel`)}
                    subtitle={t(`channelAnalysis.dims.${cfg.dimKey}.pairSubtitle`)}
                    tooltip={t("tooltips.channelCooccurrence")}
                />
                <Card className="shadow-none">
                    <CardContent className="pt-6">
                        {topPairs.length === 0 ? (
                            <EmptyStateCard
                                icon={<Store className="h-5 w-5" />}
                                title={t("channelAnalysis.emptyCooccurrenceTitle")}
                                description={emptyDescription}
                                ctaLabel={missingConfiguration ? t("channelAnalysis.ctaBrandSettings") : undefined}
                                ctaHref={missingConfiguration ? "/settings" : undefined}
                            />
                        ) : (
                            <ResponsiveContainer width="100%" height={Math.max(280, topPairs.length * 32)}>
                                <BarChart data={topPairs} layout="vertical" margin={{ left: 120, right: 20 }}>
                                    <CartesianGrid strokeDasharray="3 3" horizontal={false} />
                                    <XAxis type="number" stroke="#888" fontSize={11} />
                                    <YAxis
                                        type="category"
                                        dataKey="label"
                                        stroke="#888"
                                        fontSize={11}
                                        width={260}
                                    />
                                    <Tooltip content={<GlassTooltip />} />
                                    <Bar dataKey="count" fill="#10b981" radius={[0, 4, 4, 0]} />
                                </BarChart>
                            </ResponsiveContainer>
                        )}
                    </CardContent>
                </Card>
            </section>

            {/* ========== Chart 2: distribution per channel ========== */}
            <section>
                <SectionHeader
                    icon={<Layers className="h-5 w-5 text-primary" />}
                    title={t(`channelAnalysis.dims.${cfg.dimKey}.distributionTitle`)}
                    subtitle={t(`channelAnalysis.dims.${cfg.dimKey}.distributionSubtitle`)}
                    tooltip={t("tooltips.channelOtherProducts")}
                />
                <Card className="shadow-none">
                    <CardContent className="pt-6">
                        {brandPivot.length === 0 ? (
                            <EmptyStateCard
                                icon={<Layers className="h-5 w-5" />}
                                title={t("channelAnalysis.emptyDistributionTitle")}
                                description={emptyDescription}
                                ctaLabel={missingConfiguration ? t("channelAnalysis.ctaBrandSettings") : undefined}
                                ctaHref={missingConfiguration ? "/settings" : undefined}
                            />
                        ) : (
                            <ResponsiveContainer width="100%" height={320}>
                                <BarChart data={brandPivot}>
                                    <CartesianGrid strokeDasharray="3 3" vertical={false} />
                                    <XAxis dataKey="brand" stroke="#888" fontSize={11} />
                                    <YAxis stroke="#888" fontSize={11} />
                                    <Tooltip content={<GlassTooltip />} />
                                    <Legend
                                        formatter={(v: string) => (
                                            <span className="text-xs text-muted-foreground">{v}</span>
                                        )}
                                    />
                                    {brandKeys.map((k, i) => (
                                        <Bar
                                            key={k}
                                            dataKey={k}
                                            stackId="a"
                                            fill={COLORS[i % COLORS.length]}
                                        />
                                    ))}
                                </BarChart>
                            </ResponsiveContainer>
                        )}
                    </CardContent>
                </Card>
            </section>

            {/* ========== Chart 3: reverse pivot ========== */}
            <section>
                <SectionHeader
                    icon={<PackageSearch className="h-5 w-5 text-primary" />}
                    title={t(`channelAnalysis.dims.${cfg.dimKey}.reverseTitle`)}
                    subtitle={t(`channelAnalysis.dims.${cfg.dimKey}.reverseSubtitle`)}
                    tooltip={t("tooltips.peerVoiceShare")}
                />
                <Card className="shadow-none">
                    <CardContent className="pt-6">
                        {secondaryPivot.length === 0 ? (
                            <EmptyStateCard
                                icon={<PackageSearch className="h-5 w-5" />}
                                title={t("channelAnalysis.emptyReverseTitle")}
                                description={emptyDescription}
                                ctaLabel={missingConfiguration ? t("channelAnalysis.ctaBrandSettings") : undefined}
                                ctaHref={missingConfiguration ? "/settings" : undefined}
                            />
                        ) : (
                            <ResponsiveContainer width="100%" height={320}>
                                <BarChart data={secondaryPivot}>
                                    <CartesianGrid strokeDasharray="3 3" vertical={false} />
                                    <XAxis dataKey="secondary" stroke="#888" fontSize={11} />
                                    <YAxis stroke="#888" fontSize={11} />
                                    <Tooltip content={<GlassTooltip />} />
                                    <Legend
                                        formatter={(v: string) => (
                                            <span className="text-xs text-muted-foreground">{v}</span>
                                        )}
                                    />
                                    {secondaryKeys.map((k, i) => (
                                        <Bar
                                            key={k}
                                            dataKey={k}
                                            fill={COLORS[i % COLORS.length]}
                                        />
                                    ))}
                                </BarChart>
                            </ResponsiveContainer>
                        )}
                    </CardContent>
                </Card>
            </section>

            {/* ========== Chart 4: citation role (dimension-independent) ========== */}
            <section>
                <SectionHeader
                    icon={<Quote className="h-5 w-5 text-primary" />}
                    title={t("channelAnalysis.citationTitle")}
                    subtitle={t("channelAnalysis.citationSubtitle")}
                    tooltip={t("tooltips.citationRole")}
                />
                <Card className="shadow-none">
                    <CardContent className="pt-6">
                        {citationPieData.length === 0 ? (
                            <EmptyStateCard
                                icon={<Quote className="h-5 w-5" />}
                                title={t("channelAnalysis.emptyCitationTitle")}
                                description={t("channelAnalysis.emptyCitationDesc")}
                                ctaLabel={t("channelAnalysis.ctaCitations")}
                                ctaHref="/insights/citations"
                            />
                        ) : (
                            <ResponsiveContainer width="100%" height={320}>
                                <PieChart>
                                    <Pie
                                        data={citationPieData}
                                        cx="50%"
                                        cy="50%"
                                        innerRadius={70}
                                        outerRadius={120}
                                        paddingAngle={2}
                                        dataKey="value"
                                        nameKey="name"
                                    >
                                        {citationPieData.map((entry, index) => (
                                            <Cell
                                                key={`cell-${entry.name}`}
                                                fill={COLORS[index % COLORS.length]}
                                            />
                                        ))}
                                    </Pie>
                                    <Tooltip
                                        content={<GlassTooltip />}
                                        formatter={(val: any, name: any, item: any) => [
                                            `${val} (${item?.payload?.share ?? 0}%)`,
                                            name,
                                        ]}
                                    />
                                    <Legend
                                        verticalAlign="bottom"
                                        formatter={(value: string) => (
                                            <span className="text-xs text-muted-foreground">
                                                {value}
                                            </span>
                                        )}
                                    />
                                </PieChart>
                            </ResponsiveContainer>
                        )}
                    </CardContent>
                </Card>
            </section>
        </div>
    );
}

// ---- internal --------------------------------------------------------

function SectionHeader({
    icon,
    title,
    subtitle,
    tooltip,
}: {
    icon: React.ReactNode;
    title: string;
    subtitle: string;
    tooltip: string;
}) {
    return (
        <div className="mb-5">
            <div className="flex items-center justify-between">
                <div>
                    <h2 className="text-lg font-semibold flex items-center gap-2">
                        {icon}
                        <HelpTooltip content={tooltip}>
                            <span>{title}</span>
                        </HelpTooltip>
                    </h2>
                    <p className="text-sm text-muted-foreground mt-0.5">{subtitle}</p>
                </div>
            </div>
            <div className="mt-3 h-px bg-gradient-to-r from-primary/20 via-primary/5 to-transparent" />
        </div>
    );
}

// Keep CardHeader / CardTitle imported but unused references out of the
// bundle — the section header above composes titles manually to keep
// the tooltip trigger inline with the icon.
export { /* re-export noop to silence barrel scanners */ };
void CardHeader;
void CardTitle;
