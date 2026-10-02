import { useEffect, useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { ChevronDown, Hash, Layers, RotateCcw, SlidersHorizontal } from "lucide-react";
import CitationDashboard from "@/components/insights/CitationDashboard";
import SentimentDashboard from "@/components/insights/SentimentDashboard";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import { InsightsFilterContext, type InsightsFilterCtx, type ViewByDimension } from "@/contexts/InsightsFilterContext";
import { getWorkspaceContext, type StaticReportSummary } from "@/lib/api";
import Visibility from "@/pages/insights/Visibility";

interface FilterOption {
  id: string;
  name: string;
}

interface ClientConfiguration {
  id: string;
  topics?: Array<{ id: string; topic_name?: string; name?: string }>;
  config_platforms?: string[];
}

function mergeOptions(saved: FilterOption[], configured: FilterOption[]): FilterOption[] {
  const merged = new Map<string, FilterOption>();
  for (const option of [...saved, ...configured]) {
    const id = String(option.id || "").trim();
    if (!id) continue;
    const existing = merged.get(id);
    merged.set(id, { id, name: existing?.name || String(option.name || id).trim() || id });
  }
  return Array.from(merged.values()).sort((a, b) => a.name.localeCompare(b.name));
}

function toggleValue(values: string[], value: string): string[] {
  return values.includes(value) ? values.filter((item) => item !== value) : [...values, value];
}

function DynamicFilterBar({
  topics,
  platforms,
  selectedTopics,
  selectedPlatforms,
  onTopicsChange,
  onPlatformsChange,
}: {
  topics: FilterOption[];
  platforms: FilterOption[];
  selectedTopics: string[];
  selectedPlatforms: string[];
  onTopicsChange: (next: string[]) => void;
  onPlatformsChange: (next: string[]) => void;
}) {
  const { t } = useTranslation("reports");
  if (topics.length === 0 && platforms.length === 0) return null;

  return (
    <Card className="shadow-none" data-export-hidden="true">
      <CardContent className="flex flex-wrap items-center gap-3 p-4">
        <div className="flex items-center gap-2 text-sm font-medium">
          <SlidersHorizontal className="h-4 w-4 text-primary" />
          {t("detail.filters.title")}
        </div>
        {topics.length > 0 && (
          <Popover>
            <PopoverTrigger asChild>
              <Button variant="outline" size="sm" className="h-9 gap-1.5">
                <Hash className="h-3.5 w-3.5" />
                {t("detail.filters.topics")}
                {selectedTopics.length > 0 && <span className="ml-1 rounded-full bg-primary px-1.5 text-[10px] font-bold text-primary-foreground">{selectedTopics.length}</span>}
                <ChevronDown className="h-3 w-3" />
              </Button>
            </PopoverTrigger>
            <PopoverContent className="w-64 p-2" align="start">
              <button type="button" onClick={() => onTopicsChange(selectedTopics.length === topics.length ? [] : topics.map((topic) => topic.id))} className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs font-medium transition-colors hover:bg-accent">
                <Checkbox checked={selectedTopics.length === topics.length && topics.length > 0} className="pointer-events-none" />
                {t("detail.filters.selectAll")}
              </button>
              <div className="my-1 border-t" />
              {topics.map((topic) => (
                <button key={topic.id} type="button" onClick={() => onTopicsChange(toggleValue(selectedTopics, topic.id))} className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs transition-colors hover:bg-accent">
                  <Checkbox checked={selectedTopics.includes(topic.id)} className="pointer-events-none" />
                  <span className="truncate">{topic.name}</span>
                </button>
              ))}
            </PopoverContent>
          </Popover>
        )}
        {platforms.length > 0 && (
          <Popover>
            <PopoverTrigger asChild>
              <Button variant="outline" size="sm" className="h-9 gap-1.5">
                <Layers className="h-3.5 w-3.5" />
                {t("detail.filters.platforms")}
                {selectedPlatforms.length > 0 && <span className="ml-1 rounded-full bg-primary px-1.5 text-[10px] font-bold text-primary-foreground">{selectedPlatforms.length}</span>}
                <ChevronDown className="h-3 w-3" />
              </Button>
            </PopoverTrigger>
            <PopoverContent className="w-56 p-2" align="start">
              <button type="button" onClick={() => onPlatformsChange(selectedPlatforms.length === platforms.length ? [] : platforms.map((platform) => platform.id))} className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs font-medium transition-colors hover:bg-accent">
                <Checkbox checked={selectedPlatforms.length === platforms.length && platforms.length > 0} className="pointer-events-none" />
                {t("detail.filters.selectAll")}
              </button>
              <div className="my-1 border-t" />
              {platforms.map((platform) => (
                <button key={platform.id} type="button" onClick={() => onPlatformsChange(toggleValue(selectedPlatforms, platform.id))} className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs transition-colors hover:bg-accent">
                  <Checkbox checked={selectedPlatforms.includes(platform.id)} className="pointer-events-none" />
                  <span className="truncate">{platform.name}</span>
                </button>
              ))}
            </PopoverContent>
          </Popover>
        )}
        {(selectedTopics.length > 0 || selectedPlatforms.length > 0) && (
          <Button variant="ghost" size="sm" className="h-9 text-xs text-muted-foreground" onClick={() => { onTopicsChange([]); onPlatformsChange([]); }}>
            <RotateCcw className="mr-1 h-3 w-3" />
            {t("detail.filters.reset")}
          </Button>
        )}
      </CardContent>
    </Card>
  );
}

export default function DynamicDateRangeReport({ summary }: { summary: StaticReportSummary }) {
  const reportClientId = summary.client_id;
  const [configuredClient, setConfiguredClient] = useState<ClientConfiguration | null>(null);
  const [selectedTopics, setSelectedTopics] = useState<string[]>([]);
  const [selectedPlatforms, setSelectedPlatforms] = useState<string[]>([]);
  const [viewBy, setViewBy] = useState<ViewByDimension>("brand");

  useEffect(() => {
    let active = true;
    void getWorkspaceContext(reportClientId)
      .then((context) => {
        if (active) setConfiguredClient(context as ClientConfiguration);
      })
      .catch(() => {
        if (active) setConfiguredClient(null);
      });
    return () => { active = false; };
  }, [reportClientId]);

  const topicOptions = useMemo(() => mergeOptions(
    summary.filters?.topics || [],
    (configuredClient?.topics || []).map((topic) => ({ id: topic.id, name: topic.topic_name || topic.name || topic.id })),
  ), [configuredClient?.topics, summary.filters?.topics]);
  const platformOptions = useMemo(() => mergeOptions(
    summary.filters?.platforms || [],
    (configuredClient?.config_platforms || []).map((platform) => ({ id: platform, name: platform })),
  ), [configuredClient?.config_platforms, summary.filters?.platforms]);

  const filterContext = useMemo<InsightsFilterCtx>(() => ({
    dateRange: "custom",
    interval: "daily",
    selectedTopics,
    selectedPlatforms,
    selectedCountries: [],
    selectedPromptTypes: [],
    dateFrom: summary.report.window_start,
    dateTo: summary.report.window_end,
    viewBy,
    filtersReady: true,
    setDateRange: () => undefined,
    setInterval: () => undefined,
    setCustomDateRange: () => undefined,
    toggleTopic: (id) => setSelectedTopics((current) => toggleValue(current, id)),
    togglePlatform: (id) => setSelectedPlatforms((current) => toggleValue(current, id)),
    toggleCountry: () => undefined,
    setAllTopics: (all) => setSelectedTopics(all ? topicOptions.map((topic) => topic.id) : []),
    setAllPlatforms: (all) => setSelectedPlatforms(all ? platformOptions.map((platform) => platform.id) : []),
    setAllCountries: () => undefined,
    togglePromptType: () => undefined,
    setAllPromptTypes: () => undefined,
    setViewBy,
  }), [platformOptions, selectedPlatforms, selectedTopics, summary.report.window_end, summary.report.window_start, topicOptions, viewBy]);

  const dashboardFilters = useMemo(() => ({
    dateFrom: summary.report.window_start,
    dateTo: summary.report.window_end,
    interval: "daily",
    topicIds: selectedTopics,
    platforms: selectedPlatforms,
    countries: [],
    promptTypes: [],
  }), [selectedPlatforms, selectedTopics, summary.report.window_end, summary.report.window_start]);

  return (
    <div className="flex flex-col gap-8">
      <DynamicFilterBar
        topics={topicOptions}
        platforms={platformOptions}
        selectedTopics={selectedTopics}
        selectedPlatforms={selectedPlatforms}
        onTopicsChange={setSelectedTopics}
        onPlatformsChange={setSelectedPlatforms}
      />
      <InsightsFilterContext.Provider value={filterContext}>
        <Visibility clientIdOverride={reportClientId} />
      </InsightsFilterContext.Provider>
      <CitationDashboard clientId={reportClientId} filters={dashboardFilters} filtersReady mode="sidebar" />
      <SentimentDashboard clientId={reportClientId} filters={dashboardFilters} filtersReady mode="sidebar" />
    </div>
  );
}
