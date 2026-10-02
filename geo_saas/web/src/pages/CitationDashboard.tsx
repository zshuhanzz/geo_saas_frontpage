/**
 * CitationDashboard — Standalone Citation page for the Dashboards sidebar.
 *
 * Wraps the existing Citations component with a self-contained InsightsFilter
 * context so it can render outside of InsightsLayout (no tab switcher).
 */
import { useState, useMemo, useEffect } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { Checkbox } from "@/components/ui/checkbox";
import { Calendar } from "@/components/ui/calendar";
import { useSaaS } from "@/contexts/SaaSContext";
import { CalendarDays, ChevronDown, Hash, Layers, RotateCcw, Globe2 } from "lucide-react";
import { InsightsFilterContext } from "@/contexts/InsightsFilterContext";
import type { InsightsFilterCtx } from "@/contexts/InsightsFilterContext";
import Citations from "./insights/Citations";
import { formatPlatformLabel } from "@/lib/platformLabels";
import MultiSelectOptionRow from "@/components/insights/MultiSelectOptionRow";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import PublishedPagesManager from "@/components/citation/PublishedPagesManager";
import { dateRangeEndingToday, toDateOnlyString } from "@/lib/dateOnly";

function sameStringArray(a: string[], b: string[]) {
  return a.length === b.length && a.every((value, index) => value === b[index]);
}

type DatePresetKey = "2d" | "7d" | "14d" | "28d" | "90d";
const DATE_PRESETS: { value: DatePresetKey; days: number }[] = [
  { value: "2d", days: 2 },
  { value: "7d", days: 7 },
  { value: "14d", days: 14 },
  { value: "28d", days: 28 },
  { value: "90d", days: 90 },
];

function computeDateRange(rangeKey: string) {
  const preset = DATE_PRESETS.find((d) => d.value === rangeKey) || DATE_PRESETS[1];
  return dateRangeEndingToday(preset.days);
}

function fmtShortDate(d: string) {
  const dt = new Date(d + "T00:00:00");
  return dt.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

export default function CitationDashboard() {
  const { t } = useTranslation(["dashboards", "insights"]);
  const { clients, clientId } = useSaaS();
  const activeClient = clients.find((c) => c.id === clientId);

  const [dateRange, setDateRange] = useState("7d");
  const [interval, setIntervalState] = useState("daily");
  const [selectedTopics, setSelectedTopics] = useState<string[]>([]);
  const [selectedPlatforms, setSelectedPlatforms] = useState<string[]>([]);
  const [selectedCountries, setSelectedCountries] = useState<string[]>([]);
  const [selectedPromptTypes, setSelectedPromptTypes] = useState<string[]>([]);
  const [filtersReady, setFiltersReady] = useState(false);
  const [filtersReadyClientId, setFiltersReadyClientId] = useState<string | null>(null);
  const [customFrom, setCustomFrom] = useState<string | null>(null);
  const [customTo, setCustomTo] = useState<string | null>(null);
  const [datePickerOpen, setDatePickerOpen] = useState(false);
  const [calFrom, setCalFrom] = useState<Date | undefined>(undefined);
  const [calTo, setCalTo] = useState<Date | undefined>(undefined);

  const topics: { id: string; topic_name: string }[] = (activeClient as any)?.topics || [];
  const platforms: string[] = activeClient?.config_platforms || [];
  const countries: string[] = useMemo(
    () => Array.from(
      new Set((activeClient?.config_countries || []).map((country) => String(country).trim()).filter(Boolean)),
    ).sort((a, b) => a.localeCompare(b)),
    [activeClient?.config_countries],
  );
  const countriesKey = countries.join("|");

  useEffect(() => {
    if (!clientId || !activeClient) {
      setSelectedCountries([]);
      setFiltersReady(false);
      setFiltersReadyClientId(null);
      return;
    }
    setSelectedCountries((prev) => {
      const next = prev.filter((country) => countries.includes(country));
      return sameStringArray(prev, next) ? prev : next;
    });
    setFiltersReady(true);
    setFiltersReadyClientId(clientId);
  }, [clientId, activeClient?.id, countriesKey]);

  const { dateFrom, dateTo } = useMemo(() => {
    if (dateRange === "custom" && customFrom && customTo) {
      return { dateFrom: customFrom, dateTo: customTo };
    }
    return computeDateRange(dateRange);
  }, [dateRange, customFrom, customTo]);

  const toggleTopic = (id: string) =>
    setSelectedTopics((prev) => (prev.includes(id) ? prev.filter((t) => t !== id) : [...prev, id]));
  const togglePlatform = (id: string) =>
    setSelectedPlatforms((prev) => (prev.includes(id) ? prev.filter((p) => p !== id) : [...prev, id]));
  const toggleCountry = (id: string) =>
    setSelectedCountries((prev) => (prev.includes(id) ? prev.filter((c) => c !== id) : [...prev, id]));
  const setAllTopics = (all: boolean) =>
    setSelectedTopics((prev) => {
      const next = all ? topics.map((tp) => tp.id) : [];
      return sameStringArray(prev, next) ? prev : next;
    });
  const setAllPlatforms = (all: boolean) =>
    setSelectedPlatforms((prev) => {
      const next = all ? [...platforms] : [];
      return sameStringArray(prev, next) ? prev : next;
    });
  const setAllCountries = (all: boolean) =>
    setSelectedCountries((prev) => {
      const next = all ? [...countries] : [];
      return sameStringArray(prev, next) ? prev : next;
    });
  const togglePromptType = (id: string) =>
    setSelectedPromptTypes((prev) => (prev.includes(id) ? prev.filter((p) => p !== id) : [...prev, id]));
  const setAllPromptTypes = (all: boolean) =>
    setSelectedPromptTypes((prev) => {
      const next: string[] = all ? [] : [];
      return sameStringArray(prev, next) ? prev : next;
    });

  const handlePresetClick = (preset: string) => {
    setDateRange(preset);
    setCustomFrom(null);
    setCustomTo(null);
    setDatePickerOpen(false);
  };
  const handleCalendarApply = () => {
    if (calFrom && calTo) {
      setCustomFrom(toDateOnlyString(calFrom));
      setCustomTo(toDateOnlyString(calTo));
      setDateRange("custom");
      setDatePickerOpen(false);
    } else if (calFrom) {
      setCustomFrom(toDateOnlyString(calFrom));
      setCustomTo(toDateOnlyString(calFrom));
      setDateRange("custom");
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
    viewBy: "brand",
    filtersReady: effectiveFiltersReady,
    setDateRange: handlePresetClick,
    setInterval: setIntervalState,
    setCustomDateRange: (from: Date, to: Date) => {
      setCustomFrom(toDateOnlyString(from));
      setCustomTo(toDateOnlyString(to));
      setDateRange("custom");
    },
    toggleTopic,
    togglePlatform,
    toggleCountry,
    setAllTopics,
    setAllPlatforms,
    setAllCountries,
    togglePromptType,
    setAllPromptTypes,
    setViewBy: () => {
      // Citation dashboard does not expose view-by switching.
    },
  };

  const dateLabel =
    dateRange === "custom"
      ? `${fmtShortDate(dateFrom)} – ${fmtShortDate(dateTo)}`
      : t(`insights:filters.datePreset.${(DATE_PRESETS.find(d => d.value === dateRange)?.value) || "7d"}`);

  return (
    <InsightsFilterContext.Provider value={filterCtx}>
      <div className="flex flex-col h-full space-y-6">
        {/* Header */}
        <div>
          <h1 className="text-3xl font-bold tracking-tight">{t("citation.title")}</h1>
          <p className="text-muted-foreground mt-2">{t("citation.subtitle")}</p>
        </div>

        {/* Filters */}
        <div className="flex gap-3 items-center flex-wrap">
          {/* Date picker */}
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
                  {DATE_PRESETS.map((preset) => (
                    <button
                      key={preset.value}
                      onClick={() => handlePresetClick(preset.value)}
                      className={`text-left text-xs px-3 py-1.5 rounded-md transition-colors ${
                        dateRange === preset.value
                          ? "bg-primary text-primary-foreground"
                          : "hover:bg-muted text-muted-foreground"
                      }`}
                    >
                      {t(`insights:filters.datePreset.${preset.value}`)}
                    </button>
                  ))}
                </div>
                <div className="p-2">
                  <Calendar
                    mode="range"
                    selected={
                      calFrom && calTo
                        ? { from: calFrom, to: calTo }
                        : calFrom
                        ? { from: calFrom, to: calFrom }
                        : undefined
                    }
                    onSelect={(range: any) => {
                      setCalFrom(range?.from);
                      setCalTo(range?.to);
                    }}
                    numberOfMonths={2}
                    disabled={{ after: new Date() }}
                  />
                  <div className="flex items-center justify-between px-2 pt-2 border-t">
                    <div className="text-xs text-muted-foreground">
                      {calFrom ? calFrom.toLocaleDateString() : t("insights:filters.dateRange.start")} – {calTo ? calTo.toLocaleDateString() : t("insights:filters.dateRange.end")}
                    </div>
                    <Button size="sm" className="h-7 text-xs" onClick={handleCalendarApply} disabled={!calFrom}>
                      {t("insights:filters.dateRange.apply")}
                    </Button>
                  </div>
                </div>
              </div>
            </PopoverContent>
          </Popover>

          {/* Interval */}
          <div className="flex rounded-md border overflow-hidden">
            {(["daily", "weekly", "monthly"] as const).map((opt) => (
              <button
                key={opt}
                onClick={() => setIntervalState(opt)}
                className={`px-3 py-1.5 text-xs font-medium transition-colors ${
                  interval === opt
                    ? "bg-primary text-primary-foreground"
                    : "hover:bg-muted text-muted-foreground"
                }`}
              >
                {t(`insights:filters.interval.${opt}`)}
              </button>
            ))}
          </div>

          {/* Topic filter */}
          {topics.length > 0 && (
            <Popover>
              <PopoverTrigger asChild>
                <Button variant="outline" size="sm" className="h-9 gap-1.5">
                  <Hash className="h-3.5 w-3.5" />
                  {t("insights:filters.topics.button")}
                  {selectedTopics.length > 0 && (
                    <span className="ml-1 bg-primary text-primary-foreground rounded-full px-1.5 text-[10px] font-bold">
                      {selectedTopics.length}
                    </span>
                  )}
                  <ChevronDown className="h-3 w-3 ml-0.5" />
                </Button>
              </PopoverTrigger>
              <PopoverContent className="w-56 p-2" align="start">
                <button
                  onClick={() => setAllTopics(selectedTopics.length !== topics.length)}
                  className="flex items-center gap-2 w-full px-2 py-1.5 text-xs rounded-md hover:bg-accent transition-colors font-medium"
                >
                  <Checkbox checked={selectedTopics.length === topics.length && topics.length > 0} className="pointer-events-none" />
                  {t("insights:filters.topics.selectAll")}
                </button>
                <div className="border-t my-1" />
                {topics.map((tp) => (
                  <MultiSelectOptionRow
                    key={tp.id}
                    checked={selectedTopics.includes(tp.id)}
                    label={tp.topic_name}
                    onlyLabel={t("insights:filters.only")}
                    onToggle={() => toggleTopic(tp.id)}
                    onOnly={() => setSelectedTopics([tp.id])}
                  />
                ))}
              </PopoverContent>
            </Popover>
          )}

          {/* Platform filter */}
          {platforms.length > 0 && (
            <Popover>
              <PopoverTrigger asChild>
                <Button variant="outline" size="sm" className="h-9 gap-1.5">
                  <Layers className="h-3.5 w-3.5" />
                  {t("insights:filters.platforms.button")}
                  {selectedPlatforms.length > 0 && (
                    <span className="ml-1 bg-primary text-primary-foreground rounded-full px-1.5 text-[10px] font-bold">
                      {selectedPlatforms.length}
                    </span>
                  )}
                  <ChevronDown className="h-3 w-3 ml-0.5" />
                </Button>
              </PopoverTrigger>
              <PopoverContent className="w-52 p-2" align="start">
                <button
                  onClick={() => setAllPlatforms(selectedPlatforms.length !== platforms.length)}
                  className="flex items-center gap-2 w-full px-2 py-1.5 text-xs rounded-md hover:bg-accent transition-colors font-medium"
                >
                  <Checkbox checked={selectedPlatforms.length === platforms.length && platforms.length > 0} className="pointer-events-none" />
                  {t("insights:filters.platforms.selectAll")}
                </button>
                <div className="border-t my-1" />
                {platforms.map((p) => (
                  <MultiSelectOptionRow
                    key={p}
                    checked={selectedPlatforms.includes(p)}
                    label={formatPlatformLabel(p)}
                    onlyLabel={t("insights:filters.only")}
                    onToggle={() => togglePlatform(p)}
                    onOnly={() => setSelectedPlatforms([p])}
                  />
                ))}
              </PopoverContent>
            </Popover>
          )}

          {/* Country filter */}
          {countries.length > 0 && (
            <Popover>
              <PopoverTrigger asChild>
                <Button variant="outline" size="sm" className="h-9 gap-1.5">
                  <Globe2 className="h-3.5 w-3.5" />
                  {t("insights:filters.countries.button")}
                  {selectedCountries.length > 0 && (
                    <span className="ml-1 bg-primary text-primary-foreground rounded-full px-1.5 text-[10px] font-bold">
                      {selectedCountries.length}
                    </span>
                  )}
                  <ChevronDown className="h-3 w-3 ml-0.5" />
                </Button>
              </PopoverTrigger>
              <PopoverContent className="w-52 p-2" align="start">
                <button
                  onClick={() => setAllCountries(selectedCountries.length !== countries.length)}
                  className="flex items-center gap-2 w-full px-2 py-1.5 text-xs rounded-md hover:bg-accent transition-colors font-medium"
                >
                  <Checkbox checked={selectedCountries.length === countries.length && countries.length > 0} className="pointer-events-none" />
                  {t("insights:filters.countries.selectAll")}
                </button>
                <div className="border-t my-1" />
                {countries.map((country) => (
                  <MultiSelectOptionRow
                    key={country}
                    checked={selectedCountries.includes(country)}
                    label={country}
                    onlyLabel={t("insights:filters.only")}
                    onToggle={() => toggleCountry(country)}
                    onOnly={() => setSelectedCountries([country])}
                  />
                ))}
              </PopoverContent>
            </Popover>
          )}

          <Button variant="ghost" size="sm" className="h-9 text-xs text-muted-foreground" onClick={handleReset}>
            <RotateCcw className="h-3 w-3 mr-1" /> {t("insights:filters.reset")}
          </Button>
        </div>

        <Tabs defaultValue="monitor" className="flex min-h-0 flex-1 flex-col">
          <TabsList className="h-auto w-full justify-start gap-8 rounded-none border-b bg-transparent p-0">
            <TabsTrigger
              value="monitor"
              className="relative h-12 rounded-none border-b-2 border-transparent bg-transparent px-0 text-sm font-medium text-muted-foreground shadow-none transition-colors data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:text-foreground data-[state=active]:shadow-none"
            >
              {t("insights:citationPage.tabs.monitor")}
            </TabsTrigger>
            <TabsTrigger
              value="published"
              className="relative h-12 rounded-none border-b-2 border-transparent bg-transparent px-0 text-sm font-medium text-muted-foreground shadow-none transition-colors data-[state=active]:border-primary data-[state=active]:bg-transparent data-[state=active]:text-foreground data-[state=active]:shadow-none"
            >
              {t("insights:citationPage.tabs.publishedPages")}
            </TabsTrigger>
          </TabsList>
          <TabsContent value="monitor" className="min-h-0 flex-1 mt-6">
            <div className="h-full overflow-auto">
              <Citations />
            </div>
          </TabsContent>
          <TabsContent value="published" className="min-h-0 flex-1 mt-6">
            <div className="h-full overflow-auto">
              <PublishedPagesManager />
            </div>
          </TabsContent>
        </Tabs>
      </div>
    </InsightsFilterContext.Provider>
  );
}
