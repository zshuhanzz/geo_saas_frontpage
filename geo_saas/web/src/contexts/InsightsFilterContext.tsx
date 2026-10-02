/**
 * InsightsFilterContext — shared filter state between InsightsLayout and sub-pages.
 *
 * v1.2 addition: `viewBy` (品牌 / 产品 / 话题 / 交叉). This is the frontend
 * dimension toggle described in Spec §8.4. Existing Dashboards keep rendering
 * brand-level charts by default ("品牌" keeps the Roborock experience 无感);
 * new charts read `viewBy` to pivot to product-level, topic-level, or
 * shadow × own cross views when the feature flags allow.
 */
import { createContext, useContext } from "react";

// ============================================================================
// Types
// ============================================================================

export type ViewByDimension = "brand" | "product" | "topic" | "cross";

export interface InsightsFilterState {
    dateRange: string;       // "7d" | "14d" | "28d" | "custom"
    interval: string;        // "daily" | "weekly" | "monthly"
    selectedTopics: string[];
    selectedPlatforms: string[];
    selectedCountries: string[];
    selectedPromptTypes: string[];
    dateFrom: string;
    dateTo: string;
    viewBy: ViewByDimension;
    filtersReady: boolean;
}

export interface InsightsFilterCtx extends InsightsFilterState {
    setDateRange: (v: string) => void;
    setInterval: (v: string) => void;
    setCustomDateRange: (from: Date, to: Date) => void;
    toggleTopic: (id: string) => void;
    togglePlatform: (id: string) => void;
    toggleCountry: (id: string) => void;
    setAllTopics: (all: boolean) => void;
    setAllPlatforms: (all: boolean) => void;
    setAllCountries: (all: boolean) => void;
    togglePromptType: (id: string) => void;
    setAllPromptTypes: (all: boolean) => void;
    setViewBy: (v: ViewByDimension) => void;
}

// ============================================================================
// Context + Hook
// ============================================================================

export const InsightsFilterContext = createContext<InsightsFilterCtx | null>(null);

export function useInsightsFilters() {
    const ctx = useContext(InsightsFilterContext);
    if (!ctx) throw new Error("useInsightsFilters must be inside InsightsLayout");
    return ctx;
}
