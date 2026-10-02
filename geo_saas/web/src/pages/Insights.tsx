import { useState, useMemo, useEffect } from "react";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Checkbox } from "@/components/ui/checkbox";
import { Calendar } from "@/components/ui/calendar";
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from "@/components/ui/select";
import { Outlet, useNavigate, useLocation } from "react-router-dom";
import { useSaaS } from "@/contexts/SaaSContext";
import { CalendarDays, ChevronDown, Hash, Layers, RotateCcw, Filter, Eye, Globe2 } from "lucide-react";
import { InsightsFilterContext, useInsightsFilters } from "@/contexts/InsightsFilterContext";
import type { InsightsFilterCtx, ViewByDimension } from "@/contexts/InsightsFilterContext";
import { useTranslation } from "react-i18next";
import HelpTooltip from "@/components/ui/HelpTooltip";
import { getAvailability, getPromptFacets, type AvailabilityFlags } from "@/lib/api";
import { formatPlatformLabel } from "@/lib/platformLabels";
import MultiSelectOptionRow from "@/components/insights/MultiSelectOptionRow";
import { dateRangeEndingToday, toDateOnlyString } from "@/lib/dateOnly";
import { buildPromptTabs, PROMPTS_PATH } from "@/components/layout/sidebarNavigation";

function sameStringArray(a: string[], b: string[]) {
    return a.length === b.length && a.every((value, index) => value === b[index]);
}

const availabilityCache = new Map<string, Promise<AvailabilityFlags | null>>();
const insightCountriesCache = new Map<string, Promise<string[]>>();

function loadCachedAvailability(clientId: string) {
    const cached = availabilityCache.get(clientId);
    if (cached) return cached;
    const promise = getAvailability(clientId).catch(() => null);
    availabilityCache.set(clientId, promise);
    return promise;
}

function loadCachedInsightCountries(clientId: string) {
    const cached = insightCountriesCache.get(clientId);
    if (cached) return cached;
    const promise = getPromptFacets(clientId)
        .then((facets) => Array.from(
            new Set((facets.countries || []).map((country) => String(country).trim()).filter(Boolean)),
        ).sort((a, b) => a.localeCompare(b)))
        .catch(() => []);
    insightCountriesCache.set(clientId, promise);
    return promise;
}

// Re-export for backward compatibility (sub-pages import from here)
export { useInsightsFilters };

// Date presets — label resolved at render via t("filters.datePreset.*")
type DatePresetKey = "2d" | "7d" | "14d" | "28d" | "90d";
const DATE_PRESETS: { value: DatePresetKey; days: number }[] = [
    { value: "2d", days: 2 },
    { value: "7d", days: 7 },
    { value: "14d", days: 14 },
    { value: "28d", days: 28 },
    { value: "90d", days: 90 },
];

function computeDateRange(rangeKey: string) {
    const preset = DATE_PRESETS.find(d => d.value === rangeKey) || DATE_PRESETS[1];
    return dateRangeEndingToday(preset.days);
}

function fmtShortDate(d: string) {
    const dt = new Date(d + "T00:00:00");
    return dt.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

// ============================================================================
// InsightsLayout
// ============================================================================
export default function InsightsLayout() {
    const navigate = useNavigate();
    const location = useLocation();
    const { clients, clientId } = useSaaS();
    const activeClient = clients.find(c => c.id === clientId);
    const { t } = useTranslation("insights");

    // Filter state
    const [dateRange, setDateRange] = useState("7d");
    const [interval, setIntervalState] = useState("daily");
    const [selectedTopics, setSelectedTopics] = useState<string[]>([]);
    const [selectedPlatforms, setSelectedPlatforms] = useState<string[]>([]);
    const [selectedCountries, setSelectedCountries] = useState<string[]>([]);
    const [selectedPromptTypes, setSelectedPromptTypes] = useState<string[]>([]);
    const [countries, setCountries] = useState<string[]>([]);
    const [filtersReady, setFiltersReady] = useState(false);
    const [filtersReadyClientId, setFiltersReadyClientId] = useState<string | null>(null);
    const [customFrom, setCustomFrom] = useState<string | null>(null);
    const [customTo, setCustomTo] = useState<string | null>(null);
    const [datePickerOpen, setDatePickerOpen] = useState(false);

    // v1.2: "视图维度" toggle (Spec §8.4). Defaults to brand so existing
    // dashboards render exactly like before.
    const [viewBy, setViewBy] = useState<ViewByDimension>("brand");
    const [availability, setAvailability] = useState<AvailabilityFlags | null>(null);

    useEffect(() => {
        let cancelled = false;
        if (!clientId) {
            setAvailability(null);
            return;
        }
        loadCachedAvailability(clientId)
            .then((flags) => {
                if (!cancelled) setAvailability(flags);
            })
        return () => {
            cancelled = true;
        };
    }, [clientId]);

    useEffect(() => {
        if (!availability) return;
        if (viewBy === "product" && !availability.has_own_products) setViewBy("brand");
        if (viewBy === "cross" && !availability.has_shadow_brands) {
            setViewBy("brand");
            if (location.pathname === "/insights/channel-analysis") {
                navigate("/insights/visibility");
            }
        }
    }, [availability, location.pathname, navigate, viewBy]);

    useEffect(() => {
        let cancelled = false;
        if (!clientId) {
            setCountries([]);
            setSelectedCountries([]);
            setFiltersReady(false);
            setFiltersReadyClientId(null);
            return;
        }
        setFiltersReady(false);
        loadCachedInsightCountries(clientId)
            .then((nextCountries) => {
                if (cancelled) return;
                setCountries(nextCountries);
                setSelectedCountries((prev) => {
                    const next = prev.filter((country) => nextCountries.includes(country));
                    return sameStringArray(prev, next) ? prev : next;
                });
                setFiltersReady(true);
                setFiltersReadyClientId(clientId);
            })
            .catch(() => {
                if (!cancelled) {
                    setCountries([]);
                    setSelectedCountries((prev) => prev.length === 0 ? prev : []);
                    setFiltersReady(true);
                    setFiltersReadyClientId(clientId);
                }
            });
        return () => {
            cancelled = true;
        };
    }, [clientId]);

    const handleViewByChange = (v: ViewByDimension) => {
        setViewBy(v);
        const crossPath = "/insights/channel-analysis";
        const visPath = "/insights/visibility";
        if (v === "cross") {
            if (location.pathname !== crossPath) navigate(crossPath);
            return;
        }
        if (location.pathname !== visPath) navigate(visPath);
    };

    // Calendar temp state for range selection
    const [calFrom, setCalFrom] = useState<Date | undefined>(undefined);
    const [calTo, setCalTo] = useState<Date | undefined>(undefined);

    const topics: { id: string; topic_name: string }[] = (activeClient as any)?.topics || [];
    const platforms: string[] = activeClient?.config_platforms || [];
    const PROMPT_TYPES = ["Visibility", "Sentiment"];

    const { dateFrom, dateTo } = useMemo(() => {
        if (dateRange === "custom" && customFrom && customTo) {
            return { dateFrom: customFrom, dateTo: customTo };
        }
        return computeDateRange(dateRange);
    }, [dateRange, customFrom, customTo]);

    const toggleTopic = (id: string) => {
        setSelectedTopics(prev =>
            prev.includes(id) ? prev.filter(tid => tid !== id) : [...prev, id]
        );
    };
    const togglePlatform = (id: string) => {
        setSelectedPlatforms(prev =>
            prev.includes(id) ? prev.filter(p => p !== id) : [...prev, id]
        );
    };
    const toggleCountry = (id: string) => {
        setSelectedCountries(prev =>
            prev.includes(id) ? prev.filter(c => c !== id) : [...prev, id]
        );
    };
    const setAllTopics = (all: boolean) => {
        setSelectedTopics((prev) => {
            const next = all ? topics.map(tp => tp.id) : [];
            return sameStringArray(prev, next) ? prev : next;
        });
    };
    const setAllPlatforms = (all: boolean) => {
        setSelectedPlatforms((prev) => {
            const next = all ? [...platforms] : [];
            return sameStringArray(prev, next) ? prev : next;
        });
    };
    const setAllCountries = (all: boolean) => {
        setSelectedCountries((prev) => {
            const next = all ? [...countries] : [];
            return sameStringArray(prev, next) ? prev : next;
        });
    };
    const togglePromptType = (id: string) => {
        setSelectedPromptTypes(prev =>
            prev.includes(id) ? prev.filter(p => p !== id) : [...prev, id]
        );
    };
    const setAllPromptTypes = (all: boolean) => {
        setSelectedPromptTypes((prev) => {
            const next = all ? [...PROMPT_TYPES] : [];
            return sameStringArray(prev, next) ? prev : next;
        });
    };
    const setCustomDateRange = (from: Date, to: Date) => {
        setCustomFrom(toDateOnlyString(from));
        setCustomTo(toDateOnlyString(to));
        setDateRange("custom");
    };

    const handlePresetClick = (preset: string) => {
        setDateRange(preset);
        setCustomFrom(null);
        setCustomTo(null);
        setDatePickerOpen(false);
    };

    const handleCalendarApply = () => {
        if (calFrom && calTo) {
            setCustomDateRange(calFrom, calTo);
            setDatePickerOpen(false);
        } else if (calFrom) {
            setCustomDateRange(calFrom, calFrom);
            setDatePickerOpen(false);
        }
    };

    const handleReset = () => {
        setDateRange("7d");
        setCustomFrom(null);
        setCustomTo(null);
        setCalFrom(undefined);
        setCalTo(undefined);
        setSelectedTopics([]);
        setSelectedPlatforms([]);
        setSelectedCountries([]);
        setSelectedPromptTypes([]);
        setIntervalState("daily");
    };

    const effectiveFiltersReady = filtersReady && filtersReadyClientId === clientId;

    const filterCtx: InsightsFilterCtx = {
        dateRange,
        interval,
        selectedTopics,
        selectedPlatforms,
        selectedCountries,
        selectedPromptTypes,
        dateFrom,
        dateTo,
        viewBy,
        filtersReady: effectiveFiltersReady,
        setDateRange: handlePresetClick,
        setInterval: setIntervalState,
        setCustomDateRange,
        toggleTopic,
        togglePlatform,
        toggleCountry,
        setAllTopics,
        setAllPlatforms,
        setAllCountries,
        togglePromptType,
        setAllPromptTypes,
        setViewBy,
    };

    const tabs = buildPromptTabs();
    const showPromptTabs = location.pathname === "/insights/fanouts"
        || location.pathname === PROMPTS_PATH
        || location.pathname.startsWith(`${PROMPTS_PATH}/`);

    const dateLabel = dateRange === "custom"
        ? `${fmtShortDate(dateFrom)} – ${fmtShortDate(dateTo)}`
        : t(`filters.datePreset.${(DATE_PRESETS.find(d => d.value === dateRange)?.value) || "7d"}`);

    return (
        <InsightsFilterContext.Provider value={filterCtx}>
            <div className="flex flex-col h-full space-y-6">
                {/* Header */}
                <div className="flex justify-between items-center">
                    <div>
                        <h1 className="text-3xl font-bold tracking-tight">{t("page.title")}</h1>
                        <p className="text-muted-foreground mt-2">{t("page.subtitle")}</p>
                    </div>
                    <div className="flex space-x-3 items-center">
                        <Button variant="outline" onClick={() => navigate("/settings")}>{t("page.brandSettings")}</Button>
                    </div>
                </div>

                {/* Tabs */}
                {showPromptTabs && <div className="flex border-b">
                    {tabs.map((tab) => {
                        const isActive = tab.key === "prompts"
                            ? location.pathname === tab.path || location.pathname.startsWith(`${tab.path}/`)
                            : location.pathname === tab.path;
                        return (
                            <button
                                key={tab.path}
                                onClick={() => navigate(tab.path)}
                                className={`pb-3 px-1 mr-8 font-medium text-sm border-b-2 transition-colors ${isActive
                                    ? "border-primary text-foreground"
                                    : "border-transparent text-muted-foreground hover:text-foreground"
                                    }`}
                            >
                                {t(`tabs.${tab.key}`)}
                            </button>
                        );
                    })}
                </div>}

                {/* Global Filters Row */}
                <div className="flex gap-3 items-center flex-wrap">
                    {/* Date Range Picker with Calendar */}
                    <Popover open={datePickerOpen} onOpenChange={setDatePickerOpen}>
                        <PopoverTrigger asChild>
                            <Button variant="outline" size="sm" className="h-9 gap-1.5 min-w-[160px] justify-start">
                                <CalendarDays className="h-3.5 w-3.5 text-muted-foreground" />
                                <span className="text-sm">{dateLabel}</span>
                                <ChevronDown className="h-3 w-3 ml-auto" />
                            </Button>
                        </PopoverTrigger>
                        <PopoverContent className="w-auto p-0" align="start">
                            <div className="flex">
                                <div className="border-r p-2 flex flex-col gap-0.5 min-w-[130px]">
                                    {DATE_PRESETS.map(preset => (
                                        <button
                                            key={preset.value}
                                            onClick={() => handlePresetClick(preset.value)}
                                            className={`text-left text-xs px-3 py-1.5 rounded-md transition-colors ${dateRange === preset.value
                                                ? "bg-primary text-primary-foreground"
                                                : "hover:bg-muted text-muted-foreground"
                                                }`}
                                        >
                                            {t(`filters.datePreset.${preset.value}`)}
                                        </button>
                                    ))}
                                    <div className="border-t my-1" />
                                    <button
                                        className={`text-left text-xs px-3 py-1.5 rounded-md transition-colors ${dateRange === "custom"
                                            ? "bg-primary text-primary-foreground"
                                            : "hover:bg-muted text-muted-foreground"
                                            }`}
                                        onClick={() => setDateRange("custom")}
                                    >
                                        {t("filters.datePreset.custom")}
                                    </button>
                                </div>
                                <div className="p-2">
                                    <Calendar
                                        mode="range"
                                        selected={calFrom && calTo ? { from: calFrom, to: calTo } : calFrom ? { from: calFrom, to: calFrom } : undefined}
                                        onSelect={(range: any) => {
                                            setCalFrom(range?.from);
                                            setCalTo(range?.to);
                                        }}
                                        numberOfMonths={2}
                                        disabled={{ after: new Date() }}
                                    />
                                    <div className="flex items-center justify-between px-2 pt-2 border-t">
                                        <div className="text-xs text-muted-foreground">
                                            {calFrom ? `${calFrom.toLocaleDateString()}` : t("filters.dateRange.start")} – {calTo ? `${calTo.toLocaleDateString()}` : t("filters.dateRange.end")}
                                        </div>
                                        <Button size="sm" className="h-7 text-xs" onClick={handleCalendarApply} disabled={!calFrom}>
                                            {t("filters.dateRange.apply")}
                                        </Button>
                                    </div>
                                </div>
                            </div>
                        </PopoverContent>
                    </Popover>

                    {/* vs. Previous Period indicator */}
                    <div className="flex items-center gap-1.5 text-xs text-muted-foreground px-1">
                        <span>{t("filters.vsPrevious")}</span>
                        <span className="font-medium text-foreground">{t("filters.previousPeriod")}</span>
                    </div>

                    {/* Interval Toggle */}
                    <div className="flex rounded-md border overflow-hidden">
                        {(["daily", "weekly", "monthly"] as const).map(opt => (
                            <button
                                key={opt}
                                onClick={() => setIntervalState(opt)}
                                className={`px-3 py-1.5 text-xs font-medium transition-colors ${interval === opt
                                    ? "bg-primary text-primary-foreground"
                                    : "hover:bg-muted text-muted-foreground"
                                    }`}
                            >
                                {t(`filters.interval.${opt}`)}
                            </button>
                        ))}
                    </div>

                    {/* Topic Multi-select */}
                    {topics.length > 0 && (
                        <Popover>
                            <PopoverTrigger asChild>
                                <Button variant="outline" size="sm" className="h-9 gap-1.5">
                                    <Hash className="h-3.5 w-3.5" />
                                    {t("filters.topics.button")}
                                    {selectedTopics.length > 0 && (
                                        <span className="ml-1 bg-primary text-primary-foreground rounded-full px-1.5 text-[10px] font-bold">
                                            {selectedTopics.length}
                                        </span>
                                    )}
                                    <ChevronDown className="h-3 w-3 ml-0.5" />
                                </Button>
                            </PopoverTrigger>
                            <PopoverContent className="w-56 p-2" align="start">
                                <div
                                    role="button"
                                    tabIndex={0}
                                    onClick={() => setAllTopics(selectedTopics.length !== topics.length)}
                                    className="flex items-center gap-2 w-full px-2 py-1.5 text-xs rounded-md hover:bg-accent transition-colors font-medium cursor-pointer"
                                >
                                    <Checkbox checked={selectedTopics.length === topics.length && topics.length > 0} className="pointer-events-none" />
                                    {t("filters.topics.selectAll")}
                                </div>
                                <div className="border-t my-1" />
                                {topics.map(tp => (
                                    <MultiSelectOptionRow
                                        key={tp.id}
                                        checked={selectedTopics.includes(tp.id)}
                                        label={tp.topic_name}
                                        onlyLabel={t("filters.only")}
                                        onToggle={() => toggleTopic(tp.id)}
                                        onOnly={() => setSelectedTopics([tp.id])}
                                    />
                                ))}
                            </PopoverContent>
                        </Popover>
                    )}

                    {/* Platform Multi-select */}
                    {platforms.length > 0 && (
                        <Popover>
                            <PopoverTrigger asChild>
                                <Button variant="outline" size="sm" className="h-9 gap-1.5">
                                    <Layers className="h-3.5 w-3.5" />
                                    {t("filters.platforms.button")}
                                    {selectedPlatforms.length > 0 && (
                                        <span className="ml-1 bg-primary text-primary-foreground rounded-full px-1.5 text-[10px] font-bold">
                                            {selectedPlatforms.length}
                                        </span>
                                    )}
                                    <ChevronDown className="h-3 w-3 ml-0.5" />
                                </Button>
                            </PopoverTrigger>
                            <PopoverContent className="w-52 p-2" align="start">
                                <div
                                    role="button"
                                    tabIndex={0}
                                    onClick={() => setAllPlatforms(selectedPlatforms.length !== platforms.length)}
                                    className="flex items-center gap-2 w-full px-2 py-1.5 text-xs rounded-md hover:bg-accent transition-colors font-medium cursor-pointer"
                                >
                                    <Checkbox checked={selectedPlatforms.length === platforms.length && platforms.length > 0} className="pointer-events-none" />
                                    {t("filters.platforms.selectAll")}
                                </div>
                                <div className="border-t my-1" />
                                {platforms.map(p => (
                                    <MultiSelectOptionRow
                                        key={p}
                                        checked={selectedPlatforms.includes(p)}
                                        label={formatPlatformLabel(p)}
                                        onlyLabel={t("filters.only")}
                                        onToggle={() => togglePlatform(p)}
                                        onOnly={() => setSelectedPlatforms([p])}
                                    />
                                ))}
                            </PopoverContent>
                        </Popover>
                    )}

                    {/* Country Multi-select */}
                    {countries.length > 0 && (
                        <Popover>
                            <PopoverTrigger asChild>
                                <Button variant="outline" size="sm" className="h-9 gap-1.5">
                                    <Globe2 className="h-3.5 w-3.5" />
                                    {t("filters.countries.button")}
                                    {selectedCountries.length > 0 && (
                                        <span className="ml-1 bg-primary text-primary-foreground rounded-full px-1.5 text-[10px] font-bold">
                                            {selectedCountries.length}
                                        </span>
                                    )}
                                    <ChevronDown className="h-3 w-3 ml-0.5" />
                                </Button>
                            </PopoverTrigger>
                            <PopoverContent className="w-52 p-2" align="start">
                                <div
                                    role="button"
                                    tabIndex={0}
                                    onClick={() => setAllCountries(selectedCountries.length !== countries.length)}
                                    className="flex items-center gap-2 w-full px-2 py-1.5 text-xs rounded-md hover:bg-accent transition-colors font-medium cursor-pointer"
                                >
                                    <Checkbox checked={selectedCountries.length === countries.length && countries.length > 0} className="pointer-events-none" />
                                    {t("filters.countries.selectAll")}
                                </div>
                                <div className="border-t my-1" />
                                {countries.map(country => (
                                    <MultiSelectOptionRow
                                        key={country}
                                        checked={selectedCountries.includes(country)}
                                        label={country}
                                        onlyLabel={t("filters.only")}
                                        onToggle={() => toggleCountry(country)}
                                        onOnly={() => setSelectedCountries([country])}
                                    />
                                ))}
                            </PopoverContent>
                        </Popover>
                    )}

                    {/* Prompt Type Multi-select (Citations only) */}
                    {location.pathname.includes("citations") && (
                        <Popover>
                            <PopoverTrigger asChild>
                                <Button variant="outline" size="sm" className="h-9 gap-1.5">
                                    <Filter className="h-3.5 w-3.5" />
                                    {t("filters.promptTypes.button")}
                                    {selectedPromptTypes.length > 0 && (
                                        <span className="ml-1 bg-primary text-primary-foreground rounded-full px-1.5 text-[10px] font-bold">
                                            {selectedPromptTypes.length}
                                        </span>
                                    )}
                                    <ChevronDown className="h-3 w-3 ml-0.5" />
                                </Button>
                            </PopoverTrigger>
                            <PopoverContent className="w-52 p-2" align="start">
                                <div
                                    role="button"
                                    tabIndex={0}
                                    onClick={() => setAllPromptTypes(selectedPromptTypes.length !== PROMPT_TYPES.length)}
                                    className="flex items-center gap-2 w-full px-2 py-1.5 text-xs rounded-md hover:bg-accent transition-colors font-medium cursor-pointer"
                                >
                                    <Checkbox checked={selectedPromptTypes.length === PROMPT_TYPES.length && PROMPT_TYPES.length > 0} className="pointer-events-none" />
                                    {t("filters.promptTypes.selectAll")}
                                </div>
                                <div className="border-t my-1" />
                                {PROMPT_TYPES.map(p => (
                                    <div
                                        key={p}
                                        role="button"
                                        tabIndex={0}
                                        onClick={() => togglePromptType(p)}
                                        className="flex items-center gap-2 w-full px-2 py-1.5 text-xs rounded-md hover:bg-accent transition-colors cursor-pointer"
                                    >
                                        <Checkbox checked={selectedPromptTypes.includes(p)} className="pointer-events-none" />
                                        {p}
                                    </div>
                                ))}
                            </PopoverContent>
                        </Popover>
                    )}

                    {/* View By */}
                    <div className="flex items-center gap-1">
                        <HelpTooltip content={t("tooltips.viewByDimension")} side="bottom" />
                        <Select
                            value={viewBy}
                            onValueChange={(v) => handleViewByChange(v as ViewByDimension)}
                        >
                            <SelectTrigger className="h-9 w-[148px] gap-1.5 text-sm">
                                <Eye className="h-3.5 w-3.5 text-muted-foreground" />
                                <SelectValue placeholder={t("filters.viewBy.placeholder")} />
                            </SelectTrigger>
                            <SelectContent>
                                <SelectItem value="brand">{t("filters.viewBy.brand")}</SelectItem>
                                <SelectItem value="topic">{t("filters.viewBy.topic")}</SelectItem>
                                {(availability?.has_own_products ?? true) && (
                                    <SelectItem value="product">{t("filters.viewBy.product")}</SelectItem>
                                )}
                                {(availability?.has_shadow_brands ?? false) && (
                                    <SelectItem value="cross">{t("filters.viewBy.cross")}</SelectItem>
                                )}
                            </SelectContent>
                        </Select>
                    </div>

                    {/* Reset Button */}
                    <Button variant="ghost" size="sm" className="h-9 text-xs text-muted-foreground" onClick={handleReset}>
                        <RotateCcw className="h-3 w-3 mr-1" /> {t("filters.reset")}
                    </Button>
                </div>

                {/* Content Outlet */}
                <div className="flex-1 bg-background rounded-lg border p-6 overflow-auto">
                    <Outlet />
                </div>
            </div>
        </InsightsFilterContext.Provider>
    );
}
