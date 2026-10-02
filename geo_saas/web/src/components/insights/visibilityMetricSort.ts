import { sortCompleteMetricRows, type MetricSortState } from "../../lib/metricSort.ts";

export interface VisibilityListSorts {
    visibility: MetricSortState;
    sov: MetricSortState;
    position: MetricSortState;
}

export function buildStandaloneVisibilitySorts(dimension: "product" | "topic"): VisibilityListSorts {
    return dimension === "product"
        ? {
            visibility: { metricKey: "visibility_pct", direction: "desc" },
            sov: { metricKey: "mention_count", direction: "desc" },
            position: { metricKey: "avg_position", direction: "asc" },
        }
        : {
            visibility: { metricKey: "own_sov_pct", direction: "desc" },
            sov: { metricKey: "mention_count", direction: "desc" },
            position: { metricKey: "mention_count", direction: "desc" },
        };
}

export interface CanonicalBrandMetricRow {
    key: string;
    name: string;
    rank: number | null;
    mentionCount: number;
    isOwn: boolean;
}

export function toCanonicalBrandMetricRows(brands: readonly Record<string, unknown>[]): CanonicalBrandMetricRow[] {
    return brands.map((brand, index) => {
        const name = String(brand.company_name ?? brand.brand_name ?? "");
        return {
            key: name || String(brand.brand_id ?? index),
            name,
            rank: typeof brand.rank === "number" ? brand.rank : null,
            mentionCount: Number(brand.mention_count ?? brand.count ?? 0),
            isOwn: brand.is_own === true,
        };
    });
}

export function sortVisibilityTimeSeries<T extends Record<string, unknown>>(
    rows: readonly T[],
    complete: boolean,
    sort: MetricSortState,
): readonly T[] {
    return sortCompleteMetricRows(rows, complete ? rows.length : undefined, {
        ...sort,
        tieTextKey: "date",
        tieIdKey: "date",
    });
}
