import { Fragment, useMemo, useState } from "react";
import type React from "react";
import { useTranslation } from "react-i18next";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { StaticReportSnapshot } from "@/lib/api";
import { GlassTooltip } from "@/components/ui/chart-tooltip";
import { Activity, BarChart3, ChevronDown, ChevronRight, Frown, Loader2, MessageSquareText, Scale, SmilePlus } from "lucide-react";
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { PreviousPeriodChange } from "./PreviousPeriodChange";
import { SortableMetricHeader } from "@/components/ui/SortableMetricHeader";
import type { MetricSortState } from "@/lib/metricSort";
import { useStaticReportFrozenList } from "./useStaticReportFrozenList";
import { StaticListErrorState } from "./StaticListErrorState";
import { getStaticFrozenListMetadata } from "./staticReportFrozenMetadata";

interface SentimentSummary {
  positive_pct?: number | null;
  mixed_neutral_pct?: number | null;
  negative_pct?: number | null;
  positive_pct_change?: number | null;
  positive_count?: number;
  mixed_neutral_count?: number;
  negative_count?: number;
  insufficient_evidence_count?: number;
  rated_count?: number;
  total_count?: number;
  positive_top3_themes?: string[];
  negative_top3_themes?: string[];
}

interface SentimentTheme {
  theme_name: string;
  sentiment: string;
  occurrence_count: number;
  occurrence_change?: number | null;
}

interface SentimentExample {
  theme_name: string;
  sentiment: string;
  excerpt?: string | null;
}

interface SentimentPoint {
  date: string;
  total?: number;
  rated?: number;
  positive?: number;
  mixed_neutral?: number;
  negative?: number;
  insufficient_evidence?: number;
  positive_pct?: number | null;
  mixed_neutral_pct?: number | null;
  negative_pct?: number | null;
}

interface SentimentDashboardSnapshot {
  summary?: SentimentSummary;
  themes?: SentimentTheme[];
  examples?: SentimentExample[];
  time_series?: SentimentPoint[];
  prev_time_series?: SentimentPoint[];
}

function fmtDate(value: unknown) {
  const text = String(value);
  const date = text.includes("T") ? new Date(text) : new Date(`${text}T00:00:00`);
  return `${date.getMonth() + 1}/${date.getDate()}`;
}

function fmtPercentValue(value: unknown) {
  if (value == null || Number.isNaN(Number(value))) return "—";
  return `${Number(value).toFixed(2)}%`;
}

function SectionHeader({ icon, title, subtitle }: { icon: React.ReactNode; title: string; subtitle: string }) {
  return (
    <div className="mb-5">
      <h2 className="text-lg font-semibold flex items-center gap-2">{icon}{title}</h2>
      <p className="text-sm text-muted-foreground mt-0.5">{subtitle}</p>
      <div className="mt-3 h-px bg-gradient-to-r from-primary/20 via-primary/5 to-transparent" />
    </div>
  );
}

function EmptyState({ message }: { message: string }) {
  return (
    <div className="flex flex-col items-center justify-center h-48 text-muted-foreground rounded-lg border border-dashed border-primary/20 bg-primary/[0.02]">
      <div className="h-12 w-12 rounded-full bg-primary/[0.06] border border-primary/10 mb-4 flex items-center justify-center">
        <BarChart3 className="h-5 w-5 text-primary/40" />
      </div>
      <p className="text-sm">{message}</p>
    </div>
  );
}

function SentimentBadge({ sentiment }: { sentiment: string }) {
  const { t } = useTranslation("insights");
  const color =
    sentiment === "Positive"
      ? "bg-emerald-500/10 text-emerald-600 border-emerald-500/20"
      : sentiment === "Mixed/Neutral"
        ? "bg-amber-500/10 text-amber-600 border-amber-500/20"
      : sentiment === "Negative"
        ? "bg-red-500/10 text-red-500 border-red-500/20"
        : "bg-muted text-muted-foreground border-border";
  const label = sentiment === "Positive"
    ? t("sentiment.filterPositive")
    : sentiment === "Mixed/Neutral"
      ? t("sentiment.filterMixedNeutral")
      : sentiment === "Negative"
        ? t("sentiment.filterNegative")
        : sentiment || "—";
  return <span className={`inline-flex items-center gap-1 rounded-full border px-2 py-0.5 text-xs font-medium ${color}`}>{sentiment === "Mixed/Neutral" && <Scale className="h-3 w-3" />}{label}</span>;
}

export function StaticSentimentSection({ snapshot, reportId, sortingAvailable, exportMode = false }: { snapshot: StaticReportSnapshot; reportId: string; sortingAvailable: boolean; exportMode?: boolean }) {
  const { t } = useTranslation("insights");
  const { t: reportT } = useTranslation("reports");
  const dashboard = (snapshot.sentiment?.dashboard || {}) as SentimentDashboardSnapshot;
  const summary = dashboard.summary || {};
  const fallbackThemes = useMemo(() => dashboard.themes || [], [dashboard.themes]);
  const examples = useMemo(() => dashboard.examples || [], [dashboard.examples]);
  const timeSeries = dashboard.time_series || [];
  const previousTimeSeries = dashboard.prev_time_series || [];
  const chartData = timeSeries.map((point, index: number) => ({
    ...point,
    prev_positive_pct: previousTimeSeries[index]?.positive_pct ?? null,
  }));
  const showTrend = Number(snapshot.report?.window_days || 1) > 1 || timeSeries.length > 1;
  const [sentimentFilter, setSentimentFilter] = useState("");
  const [themeOffset, setThemeOffset] = useState(0);
  const [legacyVisibleCount, setLegacyVisibleCount] = useState(20);
  const [themeSort, setThemeSort] = useState<MetricSortState>({ metricKey: "occurrence_count", direction: "desc" });
  const [expandedThemes, setExpandedThemes] = useState<Set<string>>(new Set());
  const staticSortEnabled = sortingAvailable && !exportMode;
  const themeMetadata = getStaticFrozenListMetadata(snapshot, "sentiment.theme");
  const themeResult = useStaticReportFrozenList({
    reportId,
    listType: "sentiment.theme",
    sort: themeSort,
    offset: themeOffset,
    enabled: staticSortEnabled,
    fallbackRows: fallbackThemes,
    filters: { sentiment: exportMode ? undefined : sentimentFilter || undefined },
    fallbackTotal: themeMetadata?.total, defaultSort: { metricKey: themeMetadata?.default_sort_by || "occurrence_count", direction: themeMetadata?.default_sort_order || "desc" },
  });
  const themes = themeResult.items as unknown as SentimentTheme[];

  const filteredThemes = useMemo(() => {
    return themes.filter((theme) => !sentimentFilter || theme.sentiment === sentimentFilter);
  }, [sentimentFilter, themes]);
  const displayedThemes = staticSortEnabled ? themes : exportMode ? fallbackThemes.slice(0, 20) : filteredThemes.slice(0, legacyVisibleCount);

  const examplesByTheme = useMemo(() => {
    const grouped: Record<string, SentimentExample[]> = {};
    for (const example of examples) {
      const key = `${example.theme_name}|${example.sentiment}`;
      grouped[key] ||= [];
      grouped[key].push(example);
    }
    return grouped;
  }, [examples]);

  const toggleTheme = (key: string) => {
    setExpandedThemes((previous) => {
      const next = new Set(previous);
      if (next.has(key)) next.delete(key);
      else next.add(key);
      return next;
    });
  };

  return (
    <div className="space-y-8">
      <section>
        <SectionHeader
          icon={<SmilePlus className="h-5 w-5 text-primary" />}
          title={t("sentiment.aiSentimentOverview")}
          subtitle={t("sentiment.aiSentimentSubtitle")}
        />
        <div className="grid grid-cols-1 lg:grid-cols-12 gap-6 mb-8">
          <div className="lg:col-span-8 space-y-6 flex flex-col">
            <Card className="shadow-none flex-1 flex flex-col">
              <CardHeader className="pb-2 flex flex-row items-start justify-between border-b pb-4 mb-4">
                <div>
                  <CardTitle className="text-sm font-medium text-muted-foreground flex items-center gap-2 mb-2">
                    <Activity className="h-4 w-4" />
                    {t("sentiment.trend")}
                  </CardTitle>
                  <div className="flex items-baseline gap-3">
                    <div className="text-3xl font-bold gradient-text-static tracking-tight">
                      {summary.positive_pct ?? "—"}%
                    </div>
                  </div>
                  <PreviousPeriodChange value={summary.positive_pct_change} />
                </div>
              </CardHeader>
              <CardContent className="flex-1 pb-6">
                {showTrend ? (
                  <ResponsiveContainer width="100%" height={320}>
                    <LineChart data={chartData} margin={{ top: 20, right: 12, left: 8, bottom: 0 }}>
                      <XAxis dataKey="date" stroke="#888" fontSize={11} tickLine={false} axisLine={false} tickFormatter={fmtDate} tickMargin={10} />
                      <YAxis stroke="#888" fontSize={11} tickLine={false} axisLine={false} unit="%" width={52} tickMargin={8} domain={[(dataMin: number) => Math.max(0, Math.floor(dataMin - 5)), (dataMax: number) => Math.min(100, Math.ceil(dataMax + 5))]} />
                      <Tooltip
                        content={<GlassTooltip />}
                        formatter={(value, name) => [
                          fmtPercentValue(value),
                          name === "prev_positive_pct" ? reportT("comparison.previousPeriod") : reportT("comparison.currentPeriod"),
                        ]}
                        labelFormatter={(value) => {
                          const text = String(value);
                          const date = text.includes("T") ? new Date(text) : new Date(`${text}T00:00:00`);
                          return date.toLocaleDateString();
                        }}
                      />
                      <Line type="monotone" dataKey="positive_pct" stroke="#10b981" strokeWidth={3} dot={{ r: 4, strokeWidth: 2 }} activeDot={{ r: 6 }} connectNulls={false} />
                      <Line type="monotone" dataKey="prev_positive_pct" stroke="#94a3b8" strokeWidth={2} strokeDasharray="5 4" dot={false} connectNulls={false} />
                    </LineChart>
                  </ResponsiveContainer>
                ) : (
                  <div className="grid gap-3 sm:grid-cols-4">
                    <div className="rounded-lg border bg-muted/20 p-4">
                      <div className="text-xs text-muted-foreground">{t("sentiment.positiveCurrent")}</div>
                      <div className="mt-2 text-2xl font-bold text-emerald-500">{summary.positive_count ?? 0}</div>
                    </div>
                    <div className="rounded-lg border bg-muted/20 p-4">
                      <div className="text-xs text-muted-foreground">{t("sentiment.filterMixedNeutral")}</div>
                      <div className="mt-2 text-2xl font-bold text-amber-600">{summary.mixed_neutral_count ?? 0}</div>
                    </div>
                    <div className="rounded-lg border bg-muted/20 p-4">
                      <div className="text-xs text-muted-foreground">{t("sentiment.filterNegative")}</div>
                      <div className="mt-2 text-2xl font-bold text-red-500">{summary.negative_count ?? 0}</div>
                    </div>
                    <div className="rounded-lg border bg-muted/20 p-4"><div className="text-xs text-muted-foreground">{t("sentiment.insufficientEvidence")}</div><div className="mt-2 text-2xl font-bold text-muted-foreground">{summary.insufficient_evidence_count ?? 0}</div></div>
                  </div>
                )}
              </CardContent>
            </Card>
          </div>

          <div className="lg:col-span-4 space-y-4 flex flex-col">
            {Number(summary.total_count || 0) > 0 && (
              <Card className="shadow-sm border-border">
                <CardHeader className="pb-0 pt-4 px-5">
                  <CardTitle className="text-xs text-muted-foreground font-medium uppercase tracking-wider">{t("sentiment.overallSentiment")}</CardTitle>
                </CardHeader>
                <CardContent className="pt-3 pb-5 px-5">
                  <div className="grid grid-cols-3 gap-2 mb-2.5 text-xs font-bold">
                    <div className="text-sm font-bold text-emerald-500">{t("sentiment.positivePctLabel", { pct: summary.positive_pct })}</div>
                    <div className="text-center text-amber-600">{t("sentiment.mixedNeutralPctLabel", { pct: summary.mixed_neutral_pct })}</div>
                    <div className="text-right text-red-500">{t("sentiment.negativePctLabel", { pct: summary.negative_pct })}</div>
                  </div>
                  <div className="w-full h-5 flex rounded-lg overflow-hidden shadow-inner bg-muted">
                    <div className="h-full bg-emerald-500 transition-all duration-500" style={{ width: `${summary.positive_pct || 0}%` }} />
                    <div className="h-full bg-amber-400 transition-all duration-500" style={{ width: `${summary.mixed_neutral_pct || 0}%` }} />
                    <div className="h-full bg-red-500 transition-all duration-500" style={{ width: `${summary.negative_pct || 0}%` }} />
                  </div>
                  <div className="mt-3 space-y-1 text-xs text-muted-foreground"><div>{t("sentiment.ratedResponses", { count: summary.rated_count ?? 0 })}</div><div>{t("sentiment.insufficientEvidenceSummary", { count: summary.insufficient_evidence_count ?? 0 })}</div></div>
                </CardContent>
              </Card>
            )}

            <ThemeSummaryCard
              icon={<SmilePlus className="h-3.5 w-3.5 text-emerald-500" />}
              title={t("sentiment.topPositiveThemes")}
              themes={summary.positive_top3_themes || []}
              color="emerald"
            />
            <ThemeSummaryCard
              icon={<Frown className="h-3.5 w-3.5 text-red-400" />}
              title={t("sentiment.topNegativeThemes")}
              themes={summary.negative_top3_themes || []}
              color="red"
            />
          </div>
        </div>
      </section>

      <section>
        <div className="flex items-center justify-between mb-4">
          <div>
            <h2 className="text-lg font-semibold flex items-center gap-2">
              <MessageSquareText className="h-5 w-5 text-primary" />
              {t("sentiment.themesTitle")}
            </h2>
            <p className="text-sm text-muted-foreground">{t("sentiment.themesSubtitle")}</p>
          </div>
          <div className="flex items-center gap-1 bg-muted rounded-lg p-1">
            {(["", "Positive", "Mixed/Neutral", "Negative"] as const).map((filter) => (
              <button
                key={filter}
                onClick={() => { setSentimentFilter(filter); setThemeOffset(0); setLegacyVisibleCount(20); }}
                className={`px-3 py-1.5 rounded-md text-xs font-medium transition-colors ${sentimentFilter === filter ? "bg-background text-foreground shadow-sm" : "text-muted-foreground hover:text-foreground"}`}
              >
                {filter === "" ? t("sentiment.filterAll") : filter === "Positive" ? t("sentiment.filterPositive") : filter === "Mixed/Neutral" ? t("sentiment.filterMixedNeutral") : t("sentiment.filterNegative")}
              </button>
            ))}
          </div>
        </div>

        <Card className="shadow-none">
          {themeResult.error && <div className="p-4 pb-0"><StaticListErrorState onRetry={themeResult.retry} /></div>}
          <div className="relative">
            {themeResult.loading && displayedThemes.length > 0 && (
              <div className="absolute inset-0 z-10 flex items-center justify-center bg-background/55 backdrop-blur-[1px]">
                <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
              </div>
            )}
            <Table data-sort-list="static-sentiment-themes">
            <TableHeader>
              <TableRow className="bg-muted/20">
                <TableHead>{t("sentiment.table.theme")}</TableHead>
                <TableHead className="w-24">{t("sentiment.table.sentiment")}</TableHead>
                <TableHead className="w-24 text-right">{staticSortEnabled && !themeResult.unavailable ? <SortableMetricHeader label={t("sentiment.table.occurrences")} metricKey="occurrence_count" sort={themeSort} onChange={(next) => { setThemeSort(next); setThemeOffset(0); }} /> : t("sentiment.table.occurrences")}</TableHead>
                <TableHead className="w-20 text-right">{staticSortEnabled && !themeResult.unavailable ? <SortableMetricHeader label={t("sentiment.table.change")} metricKey="occurrence_change" sort={themeSort} onChange={(next) => { setThemeSort(next); setThemeOffset(0); }} /> : t("sentiment.table.change")}</TableHead>
                <TableHead className="w-8" />
              </TableRow>
            </TableHeader>
            <TableBody>
              {displayedThemes.map((theme, themeIndex: number) => {
                const key = `${theme.theme_name}|${theme.sentiment}`;
                const themeExamples = examplesByTheme[key] || [];
                const expanded = expandedThemes.has(key);
                const detailsId = `static-report-theme-${themeIndex}-details`;
                return (
                  <Fragment key={key}>
                    <TableRow key={key}>
                      <TableCell>
                        {themeExamples.length > 0 ? (
                          <button
                            type="button"
                            aria-expanded={expanded}
                            aria-controls={detailsId}
                            aria-label={reportT(expanded ? "sentiment.collapseTheme" : "sentiment.expandTheme", { theme: theme.theme_name })}
                            onClick={() => toggleTheme(key)}
                            className="flex items-center gap-2 rounded-sm text-left focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2"
                          >
                            {expanded ? <ChevronDown className="h-4 w-4 text-muted-foreground" /> : <ChevronRight className="h-4 w-4 text-muted-foreground" />}
                            <span className="font-medium">{theme.theme_name}</span>
                          </button>
                        ) : (
                          <div className="flex items-center gap-2">
                            <span className="w-4" />
                            <span className="font-medium">{theme.theme_name}</span>
                          </div>
                        )}
                      </TableCell>
                      <TableCell><SentimentBadge sentiment={theme.sentiment} /></TableCell>
                      <TableCell className="text-right">{theme.occurrence_count}</TableCell>
                      <TableCell className="text-right"><PreviousPeriodChange value={theme.occurrence_change} unit="" /></TableCell>
                      <TableCell />
                    </TableRow>
                    {themeExamples.length > 0 && (
                      <TableRow id={detailsId} hidden={!expanded} aria-hidden={!expanded} className="bg-muted/5">
                        <TableCell colSpan={5} className="pl-10 text-sm text-muted-foreground">
                          <div className="space-y-2">
                            {themeExamples.slice(0, 5).map((example, exampleIndex: number) => (
                              <div key={`${key}-${exampleIndex}`}>{example.excerpt || "—"}</div>
                            ))}
                          </div>
                        </TableCell>
                      </TableRow>
                    )}
                  </Fragment>
                );
              })}
            </TableBody>
            </Table>
            {themeResult.loading && displayedThemes.length === 0 && (
              <div className="flex h-24 items-center justify-center border-t border-border">
                <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
              </div>
            )}
          </div>
          {filteredThemes.length === 0 && <EmptyState message={reportT("sentiment.emptyThemes")} />}
          {staticSortEnabled && !themeResult.unavailable && (
            <div className="flex items-center justify-between border-t border-border px-4 py-3">
              <span className="text-xs text-muted-foreground">{themeOffset + (filteredThemes.length ? 1 : 0)}–{themeOffset + filteredThemes.length} / {themeResult.total}</span>
              <div className="flex gap-2">
                <button type="button" disabled={themeOffset === 0 || themeResult.loading} onClick={() => setThemeOffset((value) => Math.max(0, value - 20))} className="rounded-md border px-3 py-1.5 text-xs disabled:opacity-50">{t("citations.pagination.previous")}</button>
                <button type="button" disabled={themeOffset + filteredThemes.length >= themeResult.total || themeResult.loading} onClick={() => setThemeOffset((value) => value + 20)} className="rounded-md border px-3 py-1.5 text-xs disabled:opacity-50">{t("citations.pagination.next")}</button>
              </div>
            </div>
          )}
          {!staticSortEnabled && !exportMode && filteredThemes.length > legacyVisibleCount && (
            <div className="flex justify-center py-4 border-t border-border">
              <button onClick={() => setLegacyVisibleCount((value) => value + 20)} className="text-sm font-medium text-primary hover:text-primary/80 transition-colors">
                {reportT("sentiment.showMoreThemes", { count: filteredThemes.length - legacyVisibleCount })}
              </button>
            </div>
          )}
        </Card>
      </section>
    </div>
  );
}

function ThemeSummaryCard({
  icon,
  title,
  themes,
  color,
}: {
  icon: React.ReactNode;
  title: string;
  themes: string[];
  color: "emerald" | "red";
}) {
  const colorClass = color === "emerald" ? "bg-emerald-500/10 text-emerald-600" : "bg-red-500/10 text-red-500";
  return (
    <Card className="shadow-sm border-border flex-1">
      <CardHeader className="pb-3 pt-4 px-5">
        <CardTitle className="text-xs text-muted-foreground font-medium uppercase tracking-wider flex items-center gap-1.5">
          {icon} {title}
        </CardTitle>
      </CardHeader>
      <CardContent className="px-5 pb-5 space-y-0">
        {themes.length > 0 ? themes.map((theme, index) => (
          <div key={theme} className="flex items-start gap-3 py-2.5 border-b last:border-0 border-border/50">
            <div className={`flex-shrink-0 w-5 h-5 rounded-full flex items-center justify-center text-[10px] font-bold mt-0.5 ${colorClass}`}>
              {index + 1}
            </div>
            <div className="text-sm font-medium text-foreground leading-snug">{theme}</div>
          </div>
        )) : <div className="text-sm text-muted-foreground pt-2">—</div>}
      </CardContent>
    </Card>
  );
}
