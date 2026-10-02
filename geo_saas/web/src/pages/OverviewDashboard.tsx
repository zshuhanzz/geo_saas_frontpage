import { useEffect, useMemo, useState } from "react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import {
  Area,
  AreaChart,
  CartesianGrid,
  Line,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";
import {
  Activity,
  BarChart3,
  CalendarDays,
  Clock3,
  ExternalLink,
  Globe2,
  Layers,
  Loader2,
  MessageSquareQuote,
  ShieldCheck,
  SmilePlus,
  Sparkles,
  Target,
  TrendingDown,
  TrendingUp,
} from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { useSaaS } from "@/contexts/SaaSContext";
import {
  getOverviewCompetitors,
  getOverviewInsights,
  getOverviewKpis,
  getOverviewPlatformHealth,
  getOverviewStatus,
  getOverviewTopicOpportunities,
  getOverviewTrends,
  type OverviewAlert,
  type OverviewCompetitorRow,
  type OverviewKpisOut,
  type OverviewMomentumPoint,
  type OverviewPlatformHealthRow,
  type OverviewStatusOut,
  type OverviewTopicOpportunityRow,
  type OverviewTrendsOut,
} from "@/lib/api";
import {
  DEV_MOCK_COMPETITORS,
  DEV_MOCK_INSIGHTS,
  DEV_MOCK_KPIS,
  DEV_MOCK_PLATFORM_HEALTH,
  DEV_MOCK_STATUS,
  DEV_MOCK_TOPICS,
  DEV_MOCK_TRENDS,
} from "@/lib/api/_devMocks";
import { getFriendlyApiErrorMessage } from "@/lib/api/_errors";
import { dateRangeEndingToday } from "@/lib/dateOnly";
import { formatPlatformLabel } from "@/lib/platformLabels";
import { cn } from "@/lib/utils";

type DatePresetKey = "2d" | "7d" | "14d" | "28d" | "90d";
type LoadKey = "status" | "kpis" | "trends" | "insights" | "topics" | "competitors" | "platform";

const DATE_PRESETS: { value: DatePresetKey; days: number }[] = [
  { value: "2d", days: 2 },
  { value: "7d", days: 7 },
  { value: "14d", days: 14 },
  { value: "28d", days: 28 },
  { value: "90d", days: 90 },
];
const REQUEST_START_DELAY_MS = 50;

function computeDateRange(rangeKey: DatePresetKey) {
  const preset = DATE_PRESETS.find((item) => item.value === rangeKey) || DATE_PRESETS[1];
  return dateRangeEndingToday(preset.days);
}

function formatPct(value?: number | null) {
  if (value === null || value === undefined) return "—";
  return `${value.toFixed(2)}%`;
}

function formatNumber(value?: number | null) {
  if (value === null || value === undefined) return "—";
  return new Intl.NumberFormat("en-US").format(value);
}

function formatRank(value?: number | null) {
  if (value === null || value === undefined) return "—";
  return `#${value}`;
}

function fmtShortDate(value: string) {
  const date = new Date(`${value}T00:00:00`);
  return date.toLocaleDateString("en-US", { month: "short", day: "numeric" });
}

function fmtDateTime(value?: string | null) {
  if (!value) return "—";
  return new Date(value).toLocaleString();
}

function metricTone(delta?: number | null, positiveIsGood = true) {
  if (delta === null || delta === undefined || delta === 0) return "text-foreground";
  const good = positiveIsGood ? delta > 0 : delta < 0;
  return good ? "text-emerald-600 dark:text-emerald-300" : "text-rose-600 dark:text-rose-300";
}

function DeltaPill({ value, positiveIsGood = true }: { value?: number | null; positiveIsGood?: boolean }) {
  const { t } = useTranslation("dashboards");
  if (value === null || value === undefined) {
    return <span className="text-xs text-muted-foreground">{t("overview.deltaFlat")}</span>;
  }
  const good = value === 0 ? null : positiveIsGood ? value > 0 : value < 0;
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-xs font-medium",
        good === null && "bg-muted text-muted-foreground",
        good === true && "bg-emerald-500/10 text-emerald-700 dark:text-emerald-300",
        good === false && "bg-rose-500/10 text-rose-700 dark:text-rose-300",
      )}
    >
      {value > 0 ? <TrendingUp className="h-3 w-3" /> : value < 0 ? <TrendingDown className="h-3 w-3" /> : null}
      {value > 0 ? "+" : ""}
      {value.toFixed(2)}%
    </span>
  );
}

function LoadingBlock({ className }: { className?: string }) {
  return (
    <div className={cn("animate-pulse rounded-lg bg-muted/40", className)}>
      <div className="h-full min-h-[120px]" />
    </div>
  );
}

function EmptyState({ message }: { message: string }) {
  return (
    <div className="flex min-h-[180px] items-center justify-center rounded-lg border border-dashed border-border/70 bg-muted/20 text-sm text-muted-foreground">
      {message}
    </div>
  );
}

function formatLoadError(error: unknown, t: any) {
  return getFriendlyApiErrorMessage(error, {
    timeout: t("common:states.requestTimeout"),
    serverBusy: t("common:states.serverBusy"),
    fallback: t("common:states.loadingFailed"),
  });
}

function MetricTile({
  label,
  value,
  tone = "default",
  detail,
}: {
  label: string;
  value: string;
  tone?: "default" | "green" | "blue" | "amber";
  detail?: string;
}) {
  return (
    <div className="rounded-md border border-border/40 bg-muted/15 px-2.5 py-2">
      <div className="flex min-h-5 items-baseline justify-between gap-3">
        <p className="text-[11px] text-muted-foreground">{label}</p>
        <p
          className={cn(
            "text-sm font-semibold",
            tone === "green" && "text-emerald-700 dark:text-emerald-300",
            tone === "blue" && "text-sky-700 dark:text-sky-300",
            tone === "amber" && "text-amber-700 dark:text-amber-300",
            tone === "default" && "text-foreground",
          )}
        >
          {value}
        </p>
      </div>
      {detail ? <p className="mt-0.5 truncate text-[10px] text-muted-foreground">{detail}</p> : null}
    </div>
  );
}

function MetricCard({
  title,
  value,
  description,
  delta,
  icon,
  accent,
  loading,
  positiveIsGood = true,
}: {
  title: string;
  value: string;
  description: string;
  delta?: number | null;
  icon: ReactNode;
  accent: string;
  loading: boolean;
  positiveIsGood?: boolean;
}) {
  if (loading) return <LoadingBlock className="min-h-[104px]" />;
  return (
    <Card className="overflow-hidden rounded-lg border-border/60 bg-background/85 shadow-sm">
      <CardContent className="p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0 flex-1 space-y-1.5">
            <p className="text-[11px] font-medium uppercase tracking-[0.12em] text-muted-foreground">{title}</p>
            <div className="flex flex-wrap items-end gap-3">
              <div className={cn("text-2xl font-semibold tracking-tight", metricTone(delta, positiveIsGood))}>
                {value}
              </div>
              {delta !== undefined ? <DeltaPill value={delta} positiveIsGood={positiveIsGood} /> : null}
            </div>
            <p className="text-xs leading-5 text-muted-foreground">{description}</p>
          </div>
          <div className={cn("flex h-9 w-9 shrink-0 items-center justify-center rounded-md", accent)}>
            {icon}
          </div>
        </div>
      </CardContent>
    </Card>
  );
}

function StatusBar({
  status,
  loading,
  dateFrom,
  dateTo,
}: {
  status: OverviewStatusOut | null;
  loading: boolean;
  dateFrom: string;
  dateTo: string;
}) {
  const { t } = useTranslation("dashboards");
  const items = [
    { icon: <Sparkles className="h-4 w-4" />, label: t("overview.status.scope"), value: t("overview.status.scopeValue") },
    { icon: <CalendarDays className="h-4 w-4" />, label: t("overview.status.period"), value: `${fmtShortDate(dateFrom)} – ${fmtShortDate(dateTo)}` },
    { icon: <ShieldCheck className="h-4 w-4" />, label: t("overview.status.latestAnalysis"), value: fmtDateTime(status?.latest_analysis_time) },
    { icon: <Clock3 className="h-4 w-4" />, label: t("overview.status.nextAnalysis"), value: fmtDateTime(status?.next_analysis_time) },
  ];
  return (
    <div className="grid gap-3 rounded-lg border border-border/60 bg-background/80 p-3 shadow-sm backdrop-blur-xl md:grid-cols-2 xl:grid-cols-4">
      {items.map((item) => (
        <div key={item.label} className="flex items-center gap-3 rounded-md border border-border/50 bg-muted/15 px-3 py-2.5">
          <div className="flex h-9 w-9 shrink-0 items-center justify-center rounded-md bg-emerald-500/12 text-emerald-600 dark:text-emerald-300">
            {loading ? <Loader2 className="h-4 w-4 animate-spin" /> : item.icon}
          </div>
          <div className="min-w-0">
            <p className="text-[11px] uppercase tracking-[0.12em] text-muted-foreground">{item.label}</p>
            <p className="truncate text-sm font-semibold">{item.value}</p>
          </div>
        </div>
      ))}
    </div>
  );
}

function insightTone(severity: string) {
  if (severity === "positive") return "border-emerald-500/25 bg-emerald-500/8";
  if (severity === "negative") return "border-rose-500/25 bg-rose-500/8";
  return "border-border/60 bg-muted/10";
}

function opportunityTone(label: string) {
  if (label === "defend") return "border-emerald-500/35 bg-emerald-500/10 text-emerald-700 dark:text-emerald-300";
  if (label === "improve") return "border-sky-500/35 bg-sky-500/10 text-sky-700 dark:text-sky-300";
  if (label === "content_gap") return "border-amber-500/35 bg-amber-500/10 text-amber-700 dark:text-amber-300";
  return "border-border bg-muted/30 text-muted-foreground";
}

export default function OverviewDashboard() {
  const { t, i18n } = useTranslation(["dashboards", "insights", "common"]);
  const { clients, clientId, activeClientName } = useSaaS();
  const [dateRange, setDateRange] = useState<DatePresetKey>("7d");
  const [status, setStatus] = useState<OverviewStatusOut | null>(null);
  const [kpis, setKpis] = useState<OverviewKpisOut | null>(null);
  const [trends, setTrends] = useState<OverviewTrendsOut | null>(null);
  const [insights, setInsights] = useState<OverviewAlert[]>([]);
  const [topics, setTopics] = useState<OverviewTopicOpportunityRow[]>([]);
  const [competitors, setCompetitors] = useState<OverviewCompetitorRow[]>([]);
  const [platformHealth, setPlatformHealth] = useState<OverviewPlatformHealthRow[]>([]);
  const [selectedInsight, setSelectedInsight] = useState<OverviewAlert | null>(null);
  const [loading, setLoading] = useState<Record<LoadKey, boolean>>({
    status: false,
    kpis: false,
    trends: false,
    insights: false,
    topics: false,
    competitors: false,
    platform: false,
  });
  const [errors, setErrors] = useState<Record<LoadKey, string | null>>({
    status: null,
    kpis: null,
    trends: null,
    insights: null,
    topics: null,
    competitors: null,
    platform: null,
  });

  const activeClient = clients.find((client) => client.id === clientId);
  const { dateFrom, dateTo } = useMemo(() => computeDateRange(dateRange), [dateRange]);
  const clientName = activeClientName || activeClient?.name || t("overview.workspaceFallback");

  useEffect(() => {
    if (!clientId) return;

    // DEV BYPASS: use mock data when dev auth is active — no backend needed
    if (import.meta.env.VITE_DEV_AUTH_USER_EMAIL) {
      setStatus(DEV_MOCK_STATUS);
      setKpis(DEV_MOCK_KPIS);
      setTrends(DEV_MOCK_TRENDS);
      setInsights(DEV_MOCK_INSIGHTS.items);
      setTopics(DEV_MOCK_TOPICS.items);
      setCompetitors(DEV_MOCK_COMPETITORS.items);
      setPlatformHealth(DEV_MOCK_PLATFORM_HEALTH.items);
      setLoading({ status: false, kpis: false, trends: false, insights: false, topics: false, competitors: false, platform: false });
      return;
    }

    let active = true;
    const cleanups: Array<() => void> = [];
    const params = { date_from: dateFrom, date_to: dateTo, interval: "daily" };

    function run<T>(
      key: LoadKey,
      request: (options: RequestInit) => Promise<T>,
      apply: (value: T) => void,
    ) {
      const controller = new AbortController();
      const timer = window.setTimeout(() => {
        if (!active) return;
        request({ signal: controller.signal })
          .then((value) => {
            if (active) apply(value);
          })
          .catch((err) => {
            if (err?.name !== "AbortError" && active) {
              setErrors((prev) => ({ ...prev, [key]: formatLoadError(err, t) }));
            }
          })
          .finally(() => {
            if (active) setLoading((prev) => ({ ...prev, [key]: false }));
          });
      }, REQUEST_START_DELAY_MS);
      cleanups.push(() => {
        window.clearTimeout(timer);
        controller.abort();
      });
      setLoading((prev) => ({ ...prev, [key]: true }));
      setErrors((prev) => ({ ...prev, [key]: null }));
    }

    run("status", (options) => getOverviewStatus(clientId, params, options), setStatus);
    run("kpis", (options) => getOverviewKpis(clientId, params, options), setKpis);
    run("trends", (options) => getOverviewTrends(clientId, params, options), setTrends);
    run("topics", (options) => getOverviewTopicOpportunities(clientId, params, options), (value) => setTopics(value.items || []));
    run("competitors", (options) => getOverviewCompetitors(clientId, params, options), (value) => setCompetitors(value.items || []));
    run("platform", (options) => getOverviewPlatformHealth(clientId, params, options), (value) => setPlatformHealth(value.items || []));

    return () => {
      active = false;
      cleanups.forEach((cleanup) => cleanup());
    };
  }, [clientId, dateFrom, dateTo]);

  useEffect(() => {
    if (!clientId) return;
    // DEV BYPASS: insights already set by the main mock effect above
    if (import.meta.env.VITE_DEV_AUTH_USER_EMAIL) return;
    const controller = new AbortController();
    let active = true;
    const params = { date_from: dateFrom, date_to: dateTo, interval: "daily", language: i18n.language };
    const timer = window.setTimeout(() => {
      if (!active) return;
      getOverviewInsights(clientId, params, { signal: controller.signal })
        .then((value) => {
          if (active) setInsights(value.items || []);
        })
        .catch((err) => {
          if (err?.name !== "AbortError" && active) {
            setErrors((prev) => ({ ...prev, insights: formatLoadError(err, t) }));
          }
        })
        .finally(() => {
          if (active) setLoading((prev) => ({ ...prev, insights: false }));
        });
    }, REQUEST_START_DELAY_MS);
    setLoading((prev) => ({ ...prev, insights: true }));
    setErrors((prev) => ({ ...prev, insights: null }));
    return () => {
      active = false;
      window.clearTimeout(timer);
      controller.abort();
    };
  }, [clientId, dateFrom, dateTo, i18n.language, t]);

  const chartData = useMemo(
    () =>
      (trends?.momentum || []).map((point: OverviewMomentumPoint) => ({
        ...point,
        label: fmtShortDate(point.date),
      })),
    [trends?.momentum],
  );

  const summary = kpis?.summary;

  return (
    <div className="relative min-h-full overflow-hidden">
      <div className="relative mx-auto flex max-w-[1480px] flex-col gap-6 px-1 pb-8">
        <section className="space-y-5 rounded-lg border border-border/60 bg-background/75 p-6 shadow-sm backdrop-blur-xl">
          <div className="flex flex-col gap-4 lg:flex-row lg:items-start lg:justify-between">
            <div className="max-w-4xl">
              <p className="text-xs font-semibold uppercase tracking-[0.2em] text-primary">{t("overview.eyebrow")}</p>
              <h1 className="mt-2 text-4xl font-semibold tracking-tight text-foreground lg:text-5xl">{clientName}</h1>
              <p className="mt-3 max-w-3xl text-base leading-7 text-muted-foreground">{t("overview.subtitle")}</p>
            </div>
            <div className="flex flex-wrap gap-2">
              {DATE_PRESETS.map((preset) => (
                <Button
                  key={preset.value}
                  variant={dateRange === preset.value ? "default" : "outline"}
                  size="sm"
                  className="h-9 rounded-md"
                  onClick={() => setDateRange(preset.value)}
                >
                  {t(`insights:filters.datePreset.${preset.value}`)}
                </Button>
              ))}
            </div>
          </div>
          <StatusBar status={status} loading={loading.status} dateFrom={dateFrom} dateTo={dateTo} />
          {errors.status && <p className="text-sm text-destructive">{errors.status}</p>}
        </section>

        <section className="grid gap-3 sm:grid-cols-2 xl:grid-cols-4">
          <MetricCard
            loading={loading.kpis}
            title={t("overview.metrics.visibility")}
            value={summary ? formatPct(summary.visibility_score) : "—"}
            delta={summary?.visibility_score_change}
            description={t("overview.metrics.visibilityDescription", {
              rank: summary ? formatRank(summary.visibility_rank) : "—",
              count: summary ? formatNumber(summary.mentioned_responses) : "—",
              total: summary ? formatNumber(summary.total_responses) : "—",
            })}
            icon={<Target className="h-5 w-5 text-emerald-700 dark:text-emerald-200" />}
            accent="bg-emerald-500/15"
          />
          <MetricCard
            loading={loading.kpis}
            title={t("overview.metrics.citation")}
            value={summary ? formatPct(summary.own_citation_share) : "—"}
            delta={summary?.own_citation_share_change}
            description={t("overview.metrics.citationDescription", {
              rank: summary ? formatRank(summary.own_citation_rank) : "—",
              count: summary ? formatNumber(summary.own_citation_count) : "—",
              total: summary ? formatNumber(summary.total_citations) : "—",
            })}
            icon={<MessageSquareQuote className="h-5 w-5 text-sky-700 dark:text-sky-200" />}
            accent="bg-sky-500/15"
          />
          <MetricCard
            loading={loading.kpis}
            title={t("overview.metrics.sentiment")}
            value={summary ? formatPct(summary.positive_sentiment_pct) : "—"}
            delta={summary?.positive_sentiment_pct_change}
            description={t("overview.metrics.sentimentDescription", {
              positive: summary ? formatNumber(summary.positive_count) : "—",
              negative: summary ? formatNumber(summary.negative_count) : "—",
            })}
            icon={<SmilePlus className="h-5 w-5 text-amber-700 dark:text-amber-200" />}
            accent="bg-amber-500/15"
          />
          <MetricCard
            loading={loading.kpis}
            title={t("overview.metrics.coverage")}
            value={summary ? formatNumber(summary.total_responses) : "—"}
            delta={undefined}
            description={t("overview.metrics.coverageDescription", {
              mentions: summary ? formatNumber(summary.own_mentions) : "—",
              sov: summary ? formatPct(summary.sov_pct) : "—",
            })}
            icon={<Activity className="h-5 w-5 text-rose-700 dark:text-rose-200" />}
            accent="bg-rose-500/15"
          />
          {errors.kpis && <p className="col-span-full text-sm text-destructive">{errors.kpis}</p>}
        </section>

        <section className="grid items-start gap-6 xl:grid-cols-[minmax(0,1fr)_420px]">
          {/* Left: Insights + Platform Health stacked */}
          <div className="grid gap-6">
            <Card className="flex flex-col rounded-lg border-border/60 bg-background/85 shadow-sm">
              <CardHeader className="pb-3">
                <CardTitle className="flex items-center gap-2 text-base">
                  <Sparkles className="h-4 w-4 text-primary" />
                  {t("overview.insights.title")}
                </CardTitle>
              </CardHeader>
              <CardContent className="flex flex-1 flex-col space-y-3">
                {loading.insights ? (
                  <>
                    <LoadingBlock className="min-h-[84px]" />
                    <LoadingBlock className="min-h-[84px]" />
                    <LoadingBlock className="min-h-[84px]" />
                  </>
                ) : insights.length > 0 ? (
                  insights.slice(0, 3).map((item) => (
                    <button
                      key={`${item.kind}-${item.metric}`}
                      type="button"
                      onClick={() => setSelectedInsight(item)}
                      className={cn("min-h-[84px] rounded-lg border p-4 text-left transition hover:border-primary/45", insightTone(item.severity))}
                    >
                      <div className="mb-1.5 flex items-center justify-between gap-3">
                        <p className="min-w-0 truncate text-sm font-semibold text-foreground">{item.title}</p>
                        <DeltaPill value={item.delta} />
                      </div>
                      <div className="flex items-center justify-between gap-3">
                        <p className="min-w-0 line-clamp-2 text-xs leading-5 text-muted-foreground">{item.detail}</p>
                        <span className="shrink-0 text-xs font-medium text-primary">{t("overview.insights.viewDetail")}</span>
                      </div>
                    </button>
                  ))
                ) : (
                  <div className="flex flex-1">
                    <EmptyState message={errors.insights || t("overview.insights.empty")} />
                  </div>
                )}
              </CardContent>
            </Card>

            <Card className="rounded-lg border-border/60 bg-background/85 shadow-sm">
              <CardHeader className="pb-3">
                <CardTitle className="flex items-center gap-2 text-base">
                  <Globe2 className="h-4 w-4 text-primary" />
                  {t("overview.platform.title")}
                </CardTitle>
              </CardHeader>
              <CardContent className="space-y-2">
                {loading.platform ? (
                  <LoadingBlock className="min-h-[120px]" />
                ) : platformHealth.length > 0 ? (
                  platformHealth.map((row) => (
                    <div key={row.platform} className="rounded-lg border border-border/60 p-3">
                      <div className="mb-2 flex items-center justify-between">
                        <span className="text-sm font-semibold text-foreground">{formatPlatformLabel(row.platform)}</span>
                      </div>
                      <div className="grid grid-cols-3 gap-2 text-xs">
                        <div>
                          <p className="text-muted-foreground">{t("overview.platform.visibility")}</p>
                          <p className="font-semibold text-emerald-700 dark:text-emerald-300">{formatPct(row.visibility_score)}</p>
                        </div>
                        <div>
                          <p className="text-muted-foreground">{t("overview.platform.citation")}</p>
                          <p className="font-semibold text-sky-700 dark:text-sky-300">{formatPct(row.own_citation_share)}</p>
                        </div>
                        <div>
                          <p className="text-muted-foreground">{t("overview.platform.sentiment")}</p>
                          <p className="font-semibold text-amber-700 dark:text-amber-300">{formatPct(row.positive_sentiment_pct)}</p>
                        </div>
                      </div>
                    </div>
                  ))
                ) : (
                  <EmptyState message={errors.platform || t("overview.empty")} />
                )}
              </CardContent>
            </Card>
          </div>

          {/* Right: Trend chart — tall, prominent */}
          <Card className="flex h-full flex-col rounded-lg border-border/60 bg-background/85 shadow-sm">
            <CardHeader className="pb-2">
              <div className="flex items-center justify-between gap-3">
                <CardTitle className="flex items-center gap-2 text-base">
                  <BarChart3 className="h-4 w-4 text-primary" />
                  {t("overview.momentum.title")}
                </CardTitle>
                <div className="flex flex-wrap items-center gap-3 text-xs text-muted-foreground">
                  <span className="inline-flex items-center gap-1.5"><i className="h-2 w-2 rounded-full bg-emerald-500" />{t("overview.momentum.series.visibility_score")}</span>
                  <span className="inline-flex items-center gap-1.5"><i className="h-2 w-2 rounded-full bg-sky-500" />{t("overview.momentum.series.own_citation_share")}</span>
                  <span className="inline-flex items-center gap-1.5"><i className="h-2 w-2 rounded-full bg-amber-500" />{t("overview.momentum.series.positive_sentiment_pct")}</span>
                </div>
              </div>
            </CardHeader>
            <CardContent className="flex flex-1 flex-col">
              {loading.trends ? (
                <LoadingBlock className="min-h-[480px] flex-1" />
              ) : chartData.length > 0 ? (
                <ResponsiveContainer width="100%" height="100%" minHeight={480}>
                  <AreaChart data={chartData} margin={{ top: 16, right: 20, bottom: 0, left: -18 }}>
                    <defs>
                      <linearGradient id="overviewVisibility" x1="0" y1="0" x2="0" y2="1">
                        <stop offset="5%" stopColor="#10b981" stopOpacity={0.28} />
                        <stop offset="95%" stopColor="#10b981" stopOpacity={0} />
                      </linearGradient>
                    </defs>
                    <CartesianGrid strokeDasharray="3 3" stroke="hsl(var(--border))" opacity={0.65} />
                    <XAxis dataKey="label" tick={{ fontSize: 12 }} tickLine={false} axisLine={false} />
                    <YAxis tick={{ fontSize: 12 }} tickLine={false} axisLine={false} width={48} tickFormatter={(value) => `${value}%`} />
                    <Tooltip
                      contentStyle={{
                        background: "hsl(var(--popover))",
                        border: "1px solid hsl(var(--border))",
                        borderRadius: 8,
                        color: "hsl(var(--popover-foreground))",
                      }}
                      formatter={(value, name) => [
                        typeof value === "number" ? formatPct(value) : "—",
                        t(`overview.momentum.series.${String(name)}` as any),
                      ]}
                    />
                    <Area type="monotone" dataKey="visibility_score" stroke="#10b981" fill="url(#overviewVisibility)" strokeWidth={2.5} />
                    <Line type="monotone" dataKey="own_citation_share" stroke="#0ea5e9" strokeWidth={2.5} dot={false} />
                    <Line type="monotone" dataKey="positive_sentiment_pct" stroke="#f59e0b" strokeWidth={2.5} dot={false} />
                  </AreaChart>
                </ResponsiveContainer>
              ) : (
                <EmptyState message={errors.trends || t("overview.empty")} />
              )}
            </CardContent>
          </Card>
        </section>

        <section className="grid items-stretch gap-6 xl:grid-cols-[minmax(0,1fr)_minmax(0,1fr)]">
          <Card className="flex h-[650px] flex-col rounded-lg border-border/60 bg-background/85 shadow-sm">
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center gap-2 text-base">
                <Layers className="h-4 w-4 text-primary" />
                {t("overview.topics.title")}
              </CardTitle>
            </CardHeader>
            <CardContent className="min-h-0 flex-1 space-y-2 overflow-y-auto pr-2">
              {loading.topics ? (
                <LoadingBlock className="min-h-[280px]" />
              ) : topics.length > 0 ? (
                topics.map((topic) => (
                  <div key={topic.topic_id} className="rounded-lg border border-border/60 p-3">
                    <div className="min-w-0">
                      <div className="flex items-start justify-between gap-3">
                        <div className="min-w-0">
                          <p className="truncate text-sm font-semibold text-foreground">{topic.topic_name || t("overview.topics.unknown")}</p>
                          <p className="mt-1 text-xs text-muted-foreground">
                            {t("overview.topics.leader", {
                              brand: topic.leading_brand || "—",
                              count: formatNumber(topic.leading_mentions),
                            })}
                          </p>
                        </div>
                        <div className="flex shrink-0 items-center gap-2">
                          <Badge variant="outline" className={cn("rounded-md", opportunityTone(topic.opportunity_label))}>
                            {t(`overview.topics.labels.${topic.opportunity_label}` as any)}
                          </Badge>
                          <span className="text-sm font-semibold text-foreground">{formatRank(topic.own_rank)}</span>
                        </div>
                      </div>
                      <div className="mt-3 grid grid-cols-1 gap-2 md:grid-cols-2 2xl:grid-cols-3">
                        <MetricTile label={t("overview.topics.visibility")} value={formatPct(topic.visibility_pct)} tone="green" />
                        <MetricTile label={t("overview.topics.citation")} value={formatPct(topic.citation_coverage)} tone="blue" />
                        <MetricTile label={t("overview.topics.sentiment")} value={formatPct(topic.sentiment_polarity)} tone="amber" />
                        <MetricTile label={t("overview.topics.promptVolume")} value={formatNumber(topic.prompt_volume)} />
                        <MetricTile
                          label={t("overview.topics.mentionShare")}
                          value={formatPct(topic.mention_share_pct)}
                          detail={t("overview.topics.mentionShareDetail", { count: formatNumber(topic.own_mentions) })}
                        />
                        <MetricTile label={t("overview.topics.ownRank")} value={formatRank(topic.own_rank)} />
                      </div>
                    </div>
                  </div>
                ))
              ) : (
                <EmptyState message={errors.topics || t("overview.empty")} />
              )}
            </CardContent>
          </Card>

          <Card className="flex h-[650px] flex-col rounded-lg border-border/60 bg-background/85 shadow-sm">
            <CardHeader className="pb-3">
              <CardTitle className="flex items-center gap-2 text-base">
                <ExternalLink className="h-4 w-4 text-primary" />
                {t("overview.competitors.title")}
              </CardTitle>
            </CardHeader>
            <CardContent className="min-h-0 flex-1 overflow-y-auto pr-2 space-y-2">
              {loading.competitors ? (
                <LoadingBlock className="min-h-[280px]" />
              ) : competitors.length > 0 ? (
                <div className="space-y-2">
                  {competitors.slice(0, 10).map((row) => (
                    <div
                      key={`${row.rank}-${row.brand_name}`}
                      className={cn(
                        "rounded-lg border border-border/60 p-3",
                        row.is_own ? "border-emerald-500/35 bg-emerald-500/10" : "bg-background/40",
                      )}
                    >
                      <div className="flex items-center justify-between gap-3">
                        <div className="min-w-0">
                          <p className="truncate text-sm font-semibold text-foreground">{row.brand_name || "—"}</p>
                          <p className="mt-1 text-xs text-muted-foreground">{formatRank(row.rank)}</p>
                        </div>
                        {row.is_own ? <Badge variant="outline" className="rounded-md border-emerald-500/35 text-emerald-700 dark:text-emerald-300">{t("overview.competitors.ownBrand")}</Badge> : null}
                      </div>
                      <div className="mt-3 grid grid-cols-1 gap-2 md:grid-cols-2">
                        <MetricTile label={t("overview.competitors.visibility")} value={formatPct(row.visibility_pct)} tone="green" />
                        <MetricTile label={t("overview.competitors.sov")} value={formatPct(row.sov_pct)} tone="blue" />
                        <MetricTile label={t("overview.competitors.mentions")} value={formatNumber(row.mention_count)} />
                        <MetricTile label={t("overview.competitors.position")} value={row.avg_position?.toFixed(1) || "—"} />
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <EmptyState message={errors.competitors || t("overview.empty")} />
              )}
            </CardContent>
          </Card>
        </section>

        <Dialog open={!!selectedInsight} onOpenChange={(open) => { if (!open) setSelectedInsight(null); }}>
          <DialogContent className="max-w-lg">
            <DialogHeader>
              <DialogTitle>{selectedInsight?.title || t("overview.insights.title")}</DialogTitle>
              <DialogDescription>{t("overview.insights.dialogDescription")}</DialogDescription>
            </DialogHeader>
            <div className="space-y-4">
              <div className="flex items-center justify-between rounded-lg border border-border/60 bg-muted/20 p-3">
                <span className="text-sm text-muted-foreground">
                  {selectedInsight ? t(`overview.momentum.series.${selectedInsight.metric}` as any) : "—"}
                </span>
                <DeltaPill value={selectedInsight?.delta} />
              </div>
              <p className="text-sm leading-7 text-foreground">{selectedInsight?.detail}</p>
            </div>
          </DialogContent>
        </Dialog>
      </div>
    </div>
  );
}
