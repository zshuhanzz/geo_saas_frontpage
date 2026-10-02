import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useTranslation } from "react-i18next";
import { Link, useParams } from "react-router-dom";
import { AlertCircle, ArrowLeft, CalendarDays, ChevronDown, Download, ExternalLink, Hash, Layers, Loader2, RotateCcw, SlidersHorizontal } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Card, CardContent } from "@/components/ui/card";
import { Checkbox } from "@/components/ui/checkbox";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";
import {
  getStaticReportCitationCategories,
  getStaticReportCitationRanking,
  getStaticReportCitationShare,
  getStaticReportFilters,
  getStaticReportSentiment,
  getStaticReportSummary,
  getStaticReportVisibilityBrandRanking,
  getStaticReportVisibilityPosition,
  getStaticReportVisibilityScore,
  getStaticReportVisibilitySov,
  type StaticReportSnapshot,
  type StaticReportSummary,
} from "@/lib/api";
import { getFriendlyApiErrorMessage } from "@/lib/api/_errors";
import { ReportStatusBadge } from "./components/ReportStatusBadge";
import DynamicDateRangeReport from "./components/DynamicDateRangeReport";
import { StaticCitationSection } from "./components/StaticCitationSection";
import { StaticSentimentSection } from "./components/StaticSentimentSection";
import { StaticVisibilitySection } from "./components/StaticVisibilitySection";
import { formatDate, formatDateTime } from "./components/reportUtils";
import { applyStaticReportFilters, type StaticReportFilterState } from "./components/staticReportFilters";
import { canFilterFrozenSnapshot } from "./components/reportComparison";
import { shouldRenderStaticSortControls } from "./components/staticReportListSort";

function toggleValue(values: string[], value: string): string[] {
  return values.includes(value) ? values.filter((item) => item !== value) : [...values, value];
}

function collectPageCss(): string {
  return Array.from(document.styleSheets)
    .map((sheet) => {
      try {
        return Array.from(sheet.cssRules).map((rule) => rule.cssText).join("\n");
      } catch {
        return "";
      }
    })
    .filter(Boolean)
    .join("\n");
}

function downloadHtml(filename: string, title: string, content: HTMLElement) {
  const cloned = content.cloneNode(true) as HTMLElement;
  cloned.querySelectorAll("[data-export-hidden='true']").forEach((node) => node.remove());
  const html = `<!doctype html>
<html lang="${document.documentElement.lang || "en"}">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>${title.replace(/[<>&"]/g, "")}</title>
  <style>${collectPageCss()}</style>
</head>
<body>
  <main class="min-h-screen bg-background text-foreground">
    ${cloned.outerHTML}
  </main>
</body>
</html>`;
  const blob = new Blob([html], { type: "text/html;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
}

function ReportFilterBar({
  filters,
  value,
  onChange,
  enabled,
}: {
  filters: StaticReportSnapshot["filters"];
  value: StaticReportFilterState;
  onChange: (next: StaticReportFilterState) => void;
  enabled: boolean;
}) {
  const { t } = useTranslation("reports");
  const topics = filters?.topics || [];
  const platforms = filters?.platforms || [];
  const hasOptions = topics.length > 0 || platforms.length > 0;
  if (!hasOptions) return null;
  const setAllTopics = (all: boolean) => onChange({ ...value, topicIds: all ? topics.map((topic) => topic.id) : [] });
  const setAllPlatforms = (all: boolean) => onChange({ ...value, platforms: all ? platforms.map((platform) => platform.id) : [] });

  return (
    <Card className="shadow-none">
      <CardContent className="flex flex-wrap items-center gap-3 p-4">
        <div className="flex items-center gap-2 text-sm font-medium">
          <SlidersHorizontal className="h-4 w-4 text-primary" />
          {t("detail.filters.title")}
        </div>

        {topics.length > 0 && (
          <Popover>
            <PopoverTrigger asChild>
              <Button variant="outline" size="sm" className="h-9 gap-1.5" disabled={!enabled}>
                <Hash className="h-3.5 w-3.5" />
                {t("detail.filters.topics")}
                {value.topicIds.length > 0 && (
                  <span className="ml-1 rounded-full bg-primary px-1.5 text-[10px] font-bold text-primary-foreground">
                    {value.topicIds.length}
                  </span>
                )}
                <ChevronDown className="h-3 w-3" />
              </Button>
            </PopoverTrigger>
            <PopoverContent className="w-64 p-2" align="start">
              <button
                type="button"
                onClick={() => enabled && setAllTopics(value.topicIds.length !== topics.length)}
                className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs font-medium transition-colors hover:bg-accent"
              >
                <Checkbox checked={value.topicIds.length === topics.length && topics.length > 0} className="pointer-events-none" />
                {t("detail.filters.selectAll")}
              </button>
              <div className="my-1 border-t" />
              {topics.map((topic) => (
                <button
                  key={topic.id}
                  type="button"
                  onClick={() => enabled && onChange({ ...value, topicIds: toggleValue(value.topicIds, topic.id) })}
                  className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs transition-colors hover:bg-accent"
                >
                  <Checkbox checked={value.topicIds.includes(topic.id)} className="pointer-events-none" />
                  <span className="truncate">{topic.name || topic.id}</span>
                </button>
              ))}
            </PopoverContent>
          </Popover>
        )}

        {platforms.length > 0 && (
          <Popover>
            <PopoverTrigger asChild>
              <Button variant="outline" size="sm" className="h-9 gap-1.5" disabled={!enabled}>
                <Layers className="h-3.5 w-3.5" />
                {t("detail.filters.platforms")}
                {value.platforms.length > 0 && (
                  <span className="ml-1 rounded-full bg-primary px-1.5 text-[10px] font-bold text-primary-foreground">
                    {value.platforms.length}
                  </span>
                )}
                <ChevronDown className="h-3 w-3" />
              </Button>
            </PopoverTrigger>
            <PopoverContent className="w-56 p-2" align="start">
              <button
                type="button"
                onClick={() => enabled && setAllPlatforms(value.platforms.length !== platforms.length)}
                className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs font-medium transition-colors hover:bg-accent"
              >
                <Checkbox checked={value.platforms.length === platforms.length && platforms.length > 0} className="pointer-events-none" />
                {t("detail.filters.selectAll")}
              </button>
              <div className="my-1 border-t" />
              {platforms.map((platform) => (
                <button
                  key={platform.id}
                  type="button"
                  onClick={() => enabled && onChange({ ...value, platforms: toggleValue(value.platforms, platform.id) })}
                  className="flex w-full items-center gap-2 rounded-md px-2 py-1.5 text-left text-xs capitalize transition-colors hover:bg-accent"
                >
                  <Checkbox checked={value.platforms.includes(platform.id)} className="pointer-events-none" />
                  <span className="truncate">{platform.name || platform.id}</span>
                </button>
              ))}
            </PopoverContent>
          </Popover>
        )}

          {(value.topicIds.length > 0 || value.platforms.length > 0) && (
            <Button variant="ghost" size="sm" className="h-9 text-xs text-muted-foreground" onClick={() => onChange({ topicIds: [], platforms: [] })}>
              <RotateCcw className="mr-1 h-3 w-3" />
              {t("detail.filters.reset")}
            </Button>
          )}
        {!enabled && (
          <span className="text-xs text-muted-foreground">{t("detail.filters.notMaterialized")}</span>
        )}
      </CardContent>
    </Card>
  );
}

type SectionKey = "visibility" | "citations" | "sentiment";
type SectionState = Record<SectionKey, Record<string, any> | null>;
type SectionLoadingState = Record<SectionKey, boolean>;
type SectionErrorState = Record<SectionKey, string | null>;

const EMPTY_SECTIONS: SectionState = {
  visibility: null,
  citations: null,
  sentiment: null,
};

const INITIAL_SECTION_LOADING: SectionLoadingState = {
  visibility: true,
  citations: true,
  sentiment: true,
};

const INITIAL_SECTION_ERRORS: SectionErrorState = {
  visibility: null,
  citations: null,
  sentiment: null,
};

function formatStaticReportError(error: unknown, t: any) {
  return getFriendlyApiErrorMessage(error, {
    timeout: t("common:states.requestTimeout"),
    serverBusy: t("common:states.serverBusy"),
    fallback: t("common:states.loadingFailed"),
  });
}

function getDashboard(section: { data?: Record<string, any> }) {
  return section?.data?.dashboard || {};
}

function composeStaticVisibilitySection(sections: Array<{ data: Record<string, any> }>): { data: Record<string, any> } {
  const [score, brandRanking, sov, position] = sections.map(getDashboard);
  const scoreSummary = score.summary || {};
  const brandRankingSummary = brandRanking.summary || {};
  const sovSummary = sov.summary || {};
  const positionSummary = position.summary || {};
  return {
    data: {
      dashboard: {
        ...score,
        summary: {
          ...scoreSummary,
          ...sovSummary,
          visibility_score: scoreSummary.visibility_score ?? null,
          visibility_score_change: scoreSummary.visibility_score_change ?? null,
          mentioned: scoreSummary.mentioned ?? 0,
          total_query: scoreSummary.total_query ?? 0,
          visibility_rank: brandRankingSummary.visibility_rank ?? scoreSummary.visibility_rank ?? null,
          visibility_rank_change: brandRankingSummary.visibility_rank_change ?? scoreSummary.visibility_rank_change ?? null,
          sov_pct: sovSummary.sov_pct ?? null,
          sov_pct_change: sovSummary.sov_pct_change ?? null,
          sov_rank: sovSummary.sov_rank ?? null,
          sov_rank_change: sovSummary.sov_rank_change ?? null,
          total_mentions: sovSummary.total_mentions ?? 0,
          own_mentions: sovSummary.own_mentions ?? 0,
          avg_position: positionSummary.avg_position ?? null,
          avg_position_change: positionSummary.avg_position_change ?? null,
          avg_position_rank: positionSummary.avg_position_rank ?? null,
          avg_position_rank_change: positionSummary.avg_position_rank_change ?? null,
        },
        sov_ranking: sov.sov_ranking || [],
        visibility_ranking: brandRanking.visibility_ranking || [],
        position_ranking: position.position_ranking || [],
        competitive_series: sov.competitive_series || {},
        topic_sov_ranking: sov.topic_sov_ranking || [],
        product_sov_ranking: sov.product_sov_ranking || [],
        avg_position_series: position.avg_position_series || [],
        prev_avg_position_series: position.prev_avg_position_series || [],
        source_rows_limited: true,
        response_source_rows_limited: true,
      },
    },
  };
}

function composeStaticCitationSection(sections: Array<{ data: Record<string, any> }>): { data: Record<string, any> } {
  const [share, ranking, categories] = sections.map(getDashboard);
  return {
    data: {
      dashboard: {
        ...share,
        summary: {
          ...(share.summary || {}),
          own_rank: ranking.summary?.own_rank ?? share.summary?.own_rank ?? null,
          own_rank_change: ranking.summary?.own_rank_change ?? share.summary?.own_rank_change ?? null,
        },
        domain_ranking: ranking.domain_ranking || [],
        page_ranking: ranking.page_ranking || [],
        category_breakdown: categories.category_breakdown || [],
        source_rows_limited: true,
      },
    },
  };
}

function composeSnapshot(
  summary: StaticReportSummary,
  filters: StaticReportSnapshot["filters"],
  sections: SectionState,
): StaticReportSnapshot {
  return {
    version: summary.snapshot_version,
    client: summary.client || { id: summary.client_id, name: "" },
    report: summary.report || {
      date: summary.report_date,
      timezone: summary.timezone,
      window_start: summary.data_window_start,
      window_end: summary.data_window_end,
      window_days: summary.window_days,
      rendering_mode: summary.rendering_mode,
    },
    data_completeness: summary.data_completeness || {},
    filters: filters || { topics: [], platforms: [] },
    visibility: sections.visibility || {},
    citations: sections.citations || {},
    sentiment: sections.sentiment || {},
    prompts: {},
    topics: {},
    frozen_lists: summary.frozen_lists || {},
  };
}

function SectionLoading({ label }: { label: string }) {
  return (
    <Card className="shadow-none">
      <CardContent className="flex items-center justify-center p-10 text-sm text-muted-foreground">
        <Loader2 className="mr-2 h-4 w-4 animate-spin" />
        {label}
      </CardContent>
    </Card>
  );
}

function SectionError({ message }: { message: string }) {
  return (
    <Card className="border-destructive/30 bg-destructive/5 shadow-none">
      <CardContent className="flex items-center gap-3 p-6 text-sm text-destructive">
        <AlertCircle className="h-4 w-4" />
        {message}
      </CardContent>
    </Card>
  );
}

export default function StaticReportPage({ presentation = false }: { presentation?: boolean }) {
  const { t } = useTranslation("reports");
  const { reportId } = useParams();
  const [summary, setSummary] = useState<StaticReportSummary | null>(null);
  const [reportFilters, setReportFilters] = useState<StaticReportSnapshot["filters"]>({ topics: [], platforms: [] });
  const [sections, setSections] = useState<SectionState>(EMPTY_SECTIONS);
  const [sectionLoading, setSectionLoading] = useState<SectionLoadingState>(INITIAL_SECTION_LOADING);
  const [sectionErrors, setSectionErrors] = useState<SectionErrorState>(INITIAL_SECTION_ERRORS);
  const [filtersLoading, setFiltersLoading] = useState(true);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filters, setFilters] = useState<StaticReportFilterState>({ topicIds: [], platforms: [] });
  const [exportMode, setExportMode] = useState(false);
  const reportRef = useRef<HTMLDivElement>(null);
  const summaryRequestSeqRef = useRef(0);
  const filtersRequestSeqRef = useRef(0);
  const sectionRequestSeqRef = useRef(0);
  const isDynamicReport = summary !== null && summary.snapshot_version === "dynamic-report-v1";

  const load = useCallback(async () => {
    if (!reportId) return;
    const requestId = summaryRequestSeqRef.current + 1;
    summaryRequestSeqRef.current = requestId;
    const isCurrentRequest = () => summaryRequestSeqRef.current === requestId;
    setLoading(true);
    setSummary(null);
    setError(null);
    try {
      const nextSummary = await getStaticReportSummary(reportId);
      if (isCurrentRequest()) setSummary(nextSummary);
    } catch (err: any) {
      if (isCurrentRequest()) setError(formatStaticReportError(err, t));
    } finally {
      if (isCurrentRequest()) setLoading(false);
    }
  }, [reportId, t]);

  useEffect(() => {
    void load();
  }, [load]);

  useEffect(() => {
    if (!reportId || !summary || isDynamicReport) return;
    const requestId = filtersRequestSeqRef.current + 1;
    filtersRequestSeqRef.current = requestId;
    const isCurrentRequest = () => filtersRequestSeqRef.current === requestId;
    setFiltersLoading(true);
    void getStaticReportFilters(reportId)
      .then((result) => {
        if (isCurrentRequest()) setReportFilters(result.filters || { topics: [], platforms: [] });
      })
      .catch(() => {
        if (isCurrentRequest()) setReportFilters({ topics: [], platforms: [] });
      })
      .finally(() => {
        if (isCurrentRequest()) setFiltersLoading(false);
      });
    return () => {
      if (isCurrentRequest()) filtersRequestSeqRef.current += 1;
    };
  }, [isDynamicReport, reportId, summary]);

  useEffect(() => {
    if (!reportId || !summary || isDynamicReport) return;
    const requestId = sectionRequestSeqRef.current + 1;
    sectionRequestSeqRef.current = requestId;
    const isCurrentRequest = () => sectionRequestSeqRef.current === requestId;

    setSections(EMPTY_SECTIONS);
    setSectionLoading(INITIAL_SECTION_LOADING);
    setSectionErrors(INITIAL_SECTION_ERRORS);

    const loaders: Array<[SectionKey, () => Promise<{ data: Record<string, any> }>]> = [
      ["visibility", () => Promise.all([
            getStaticReportVisibilityScore(reportId),
            getStaticReportVisibilityBrandRanking(reportId),
            getStaticReportVisibilitySov(reportId),
            getStaticReportVisibilityPosition(reportId),
          ]).then(composeStaticVisibilitySection)],
      ["citations", () => Promise.all([
            getStaticReportCitationShare(reportId),
            getStaticReportCitationRanking(reportId),
            getStaticReportCitationCategories(reportId),
          ]).then(composeStaticCitationSection)],
      ["sentiment", () => getStaticReportSentiment(reportId)],
    ];

    for (const [key, request] of loaders) {
      void request()
        .then((result) => {
          if (!isCurrentRequest()) return;
          setSections((previous) => ({ ...previous, [key]: result.data || {} }));
        })
        .catch((err: any) => {
          if (!isCurrentRequest()) return;
          setSectionErrors((previous) => ({ ...previous, [key]: formatStaticReportError(err, t) }));
        })
        .finally(() => {
          if (!isCurrentRequest()) return;
          setSectionLoading((previous) => ({ ...previous, [key]: false }));
        });
    }
    return () => {
      sectionRequestSeqRef.current += 1;
    };
  }, [isDynamicReport, reportId, summary, t]);

  const snapshot = useMemo(
    () => (summary && !isDynamicReport ? composeSnapshot(summary, reportFilters, sections) : null),
    [isDynamicReport, reportFilters, sections, summary],
  );
  const filteredSnapshot = useMemo(
    () => (snapshot ? applyStaticReportFilters(snapshot, filters) : null),
    [filters, snapshot],
  );
  const frozenFiltersAvailable = snapshot ? canFilterFrozenSnapshot(snapshot) : false;
  const previousCompleteness = snapshot?.data_completeness?.previous_period;
  const comparisonUnavailable = !previousCompleteness || [
    previousCompleteness.visibility,
    previousCompleteness.citation,
    previousCompleteness.sentiment,
  ].some((available) => available === false);
  const sortingAvailable = snapshot ? shouldRenderStaticSortControls(snapshot.version, false) : false;

  if (loading) {
    return (
      <div className="flex h-full items-center justify-center py-24">
        <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
        <span className="ml-2 text-sm text-muted-foreground">{t("detail.loading")}</span>
      </div>
    );
  }

  if (error || !summary || (!isDynamicReport && !snapshot)) {
    return (
      <div className="mx-auto flex max-w-3xl flex-col gap-4 py-12">
        <Button asChild variant="ghost" className="w-fit">
          <Link to="/reports">
            <ArrowLeft className="mr-2 h-4 w-4" />
            {t("detail.back")}
          </Link>
        </Button>
        <Card className="border-destructive/30 bg-destructive/5 shadow-none">
          <CardContent className="flex items-center gap-3 p-6 text-destructive">
            <AlertCircle className="h-5 w-5" />
            <span>{error || t("detail.notFound")}</span>
          </CardContent>
        </Card>
      </div>
    );
  }

  const reportClient = isDynamicReport ? summary.client : snapshot!.client;
  const reportWindow = isDynamicReport ? summary.report : snapshot!.report;
  const isSingleDay = reportWindow.rendering_mode === "single_day";
  const title = `${reportClient.name || "GEO"} GEO Report ${reportWindow.date}`;
  const exportFilename = `geo-report-${reportClient.name || "client"}-${reportWindow.date}-${reportWindow.window_days || 7}d.html`;

  async function handleExport() {
    if (!reportRef.current) return;
    setExportMode(true);
    await new Promise((resolve) => requestAnimationFrame(() => requestAnimationFrame(resolve)));
    downloadHtml(exportFilename, title, reportRef.current);
    setExportMode(false);
    toast.success(t("detail.exportStarted"));
  }

  return (
    <div ref={reportRef} className={`mx-auto flex max-w-7xl flex-col gap-6 pb-10 ${presentation ? "px-4 py-8 sm:px-6 lg:px-8" : ""}`}>
      <div className="flex flex-col gap-5">
        {!presentation && (
          <Button asChild variant="ghost" className="w-fit px-0" data-export-hidden="true">
            <Link to="/reports">
              <ArrowLeft className="mr-2 h-4 w-4" />
              {t("detail.back")}
            </Link>
          </Button>
        )}

        <div className="flex flex-col gap-4 lg:flex-row lg:items-end lg:justify-between">
          <div>
            <div className="flex flex-wrap items-center gap-3">
              <h1 className="text-3xl font-bold tracking-tight">{reportClient.name || t("list.title")}</h1>
              <ReportStatusBadge status={summary.status} />
            </div>
            <div className="mt-3 flex flex-wrap gap-4 text-sm text-muted-foreground">
              <span className="inline-flex items-center gap-1">
                <CalendarDays className="h-4 w-4" />
                {formatDate(reportWindow.date)}
              </span>
              <span>{t("detail.window")}: {formatDate(reportWindow.window_start)} - {formatDate(reportWindow.window_end)}</span>
              <span>{t("detail.windowDays", { count: reportWindow.window_days || 7 })}</span>
              <span>{t("detail.materializedAt")}: {formatDateTime(summary.materialized_at)}</span>
            </div>
          </div>
          <div className="flex flex-wrap gap-2" data-export-hidden="true">
            {!presentation && (
              <Button asChild variant="outline" size="sm">
                <Link to={`/share/reports/${summary.id}`}>
                  <ExternalLink className="mr-2 h-4 w-4" />
                  {t("detail.presentationView")}
                </Link>
              </Button>
            )}
            <Button variant="outline" size="sm" onClick={handleExport}>
              <Download className="mr-2 h-4 w-4" />
              {t("detail.exportHtml")}
            </Button>
          </div>
        </div>
      </div>

      {isSingleDay && (
        <Card className="border-amber-500/20 bg-amber-500/5 shadow-none">
          <CardContent className="p-4 text-sm text-amber-700 dark:text-amber-300">
            {t("detail.singleDayNotice")}
          </CardContent>
        </Card>
      )}

      {!isDynamicReport && comparisonUnavailable && (
        <Card className="border-amber-500/20 bg-amber-500/5 shadow-none">
          <CardContent className="p-4 text-sm text-amber-700 dark:text-amber-300">
            {previousCompleteness ? t("comparison.incompleteBaseline") : t("comparison.legacyUnavailable")}
          </CardContent>
        </Card>
      )}

      {!isDynamicReport && !sortingAvailable && (
        <Card className="border-amber-500/20 bg-amber-500/5 shadow-none">
          <CardContent className="p-4 text-sm text-amber-700 dark:text-amber-300">
            {t("detail.sortingLegacyUnavailable")}
          </CardContent>
        </Card>
      )}

      {isDynamicReport ? (
        <DynamicDateRangeReport key={summary.id} summary={summary} />
      ) : (
        <>
          {filtersLoading ? (
            <SectionLoading label={t("detail.loading")} />
          ) : (
            <ReportFilterBar filters={snapshot!.filters} value={filters} onChange={setFilters} enabled={frozenFiltersAvailable} />
          )}
          {filteredSnapshot && (
            <>
          {sectionLoading.visibility ? (
            <SectionLoading label={t("detail.loading")} />
          ) : sectionErrors.visibility ? (
            <SectionError message={sectionErrors.visibility} />
          ) : (
            <StaticVisibilitySection snapshot={filteredSnapshot} reportId={summary.id} sortingAvailable={sortingAvailable} exportMode={exportMode} />
          )}
          {sectionLoading.citations ? (
            <SectionLoading label={t("detail.loading")} />
          ) : sectionErrors.citations ? (
            <SectionError message={sectionErrors.citations} />
          ) : (
            <StaticCitationSection snapshot={filteredSnapshot} reportId={summary.id} sortingAvailable={sortingAvailable} exportMode={exportMode} />
          )}
          {sectionLoading.sentiment ? (
            <SectionLoading label={t("detail.loading")} />
          ) : sectionErrors.sentiment ? (
            <SectionError message={sectionErrors.sentiment} />
          ) : (
            <StaticSentimentSection snapshot={filteredSnapshot} reportId={summary.id} sortingAvailable={sortingAvailable} exportMode={exportMode} />
          )}
            </>
          )}
        </>
      )}
    </div>
  );
}
