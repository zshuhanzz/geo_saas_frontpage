import { useMemo, useState } from "react";
import type React from "react";
import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Dialog, DialogContent, DialogDescription, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import {
  type StaticReportSnapshot,
} from "@/lib/api";
import { GlassTooltip } from "@/components/ui/chart-tooltip";
import { Expand, Info, Link2, Loader2, Search, Trophy } from "lucide-react";
import { Line, LineChart, ResponsiveContainer, Tooltip, XAxis, YAxis } from "recharts";
import { PreviousPeriodChange } from "./PreviousPeriodChange";
import { SortableMetricHeader } from "@/components/ui/SortableMetricHeader";
import type { MetricSortState } from "@/lib/metricSort";
import { useStaticReportFrozenList } from "./useStaticReportFrozenList";
import { StaticListErrorState } from "./StaticListErrorState";
import { getStaticFrozenListMetadata } from "./staticReportFrozenMetadata";

const CATEGORY_COLORS: Record<string, string> = {
  "Earned Media": "#3b82f6",
  "Social Media": "#8b5cf6",
  "Owned Media": "#10b981",
  Agency: "#f59e0b",
  Other: "#6b7280",
};
const PAGE_SIZE = 20;
const EMPTY_ROWS: any[] = [];
const EMPTY_DASHBOARD: Record<string, any> = {};

interface StaticCitationCategoryRow {
  label?: string;
  domain_category?: string;
  count?: number;
  citation_count?: number;
  pct?: number;
}

interface StaticCitationRankingRow {
  [key: string]: unknown;
  domain?: string;
  domain_category?: string;
  citation_count?: number;
  url?: string;
  rank?: number;
  is_own?: boolean;
  share_pct?: number;
  change_pct?: number | null;
}

function getCategoryColor(category: string | null | undefined): string {
  return CATEGORY_COLORS[category || "Other"] || CATEGORY_COLORS.Other;
}

function fmtDate(value: any) {
  const text = String(value);
  const date = text.includes("T") ? new Date(text) : new Date(`${text}T00:00:00`);
  return `${date.getMonth() + 1}/${date.getDate()}`;
}

function fmtPercentValue(value: any) {
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
        <Link2 className="h-5 w-5 text-primary/40" />
      </div>
      <p className="text-sm">{message}</p>
    </div>
  );
}

export function StaticCitationSection({
  snapshot,
  reportId,
  sortingAvailable,
  exportMode = false,
}: {
  snapshot: StaticReportSnapshot;
  reportId: string;
  sortingAvailable: boolean;
  exportMode?: boolean;
}) {
  const { t } = useTranslation("insights");
  const { t: reportT } = useTranslation("reports");
  const { t: commonT } = useTranslation("common");
  const dashboard = snapshot.citations?.dashboard || EMPTY_DASHBOARD;
  const summary = dashboard.summary || EMPTY_DASHBOARD;
  const fallbackDomainRanking = dashboard.domain_ranking || EMPTY_ROWS;
  const fallbackPageRanking = dashboard.page_ranking || EMPTY_ROWS;
  const timeSeries = dashboard.time_series || EMPTY_ROWS;
  const previousTimeSeries = dashboard.prev_time_series || EMPTY_ROWS;
  const chartData = timeSeries.map((point: any, index: number) => ({
    ...point,
    prev_own_share: previousTimeSeries[index]?.own_share ?? null,
  }));
  const showTrend = Number(snapshot.report?.window_days || 1) > 1 || timeSeries.length > 1;
  const [expandRanking, setExpandRanking] = useState(false);
  const [domainSearch, setDomainSearch] = useState("");
  const [pageSearch, setPageSearch] = useState("");
  const [domainPage, setDomainPage] = useState(0);
  const [pagePage, setPagePage] = useState(0);
  const [categoryPage, setCategoryPage] = useState(0);
  const [domainSort, setDomainSort] = useState<MetricSortState>({ metricKey: "citation_count", direction: "desc" });
  const [pageSort, setPageSort] = useState<MetricSortState>({ metricKey: "citation_count", direction: "desc" });
  const [categorySort, setCategorySort] = useState<MetricSortState>({ metricKey: "count", direction: "desc" });
  const staticSortEnabled = sortingAvailable && !exportMode;
  const domainMetadata = getStaticFrozenListMetadata(snapshot, "citation.domain");
  const pageMetadata = getStaticFrozenListMetadata(snapshot, "citation.page");
  const categoryMetadata = getStaticFrozenListMetadata(snapshot, "citation.category");
  const domainResult = useStaticReportFrozenList<StaticCitationRankingRow>({
    reportId, listType: "citation.domain", sort: domainSort, offset: exportMode ? 0 : domainPage * PAGE_SIZE,
    enabled: staticSortEnabled, fallbackRows: fallbackDomainRanking as StaticCitationRankingRow[],
    filters: { search: exportMode ? undefined : domainSearch.trim() || undefined },
    fallbackTotal: domainMetadata?.total, defaultSort: { metricKey: domainMetadata?.default_sort_by || "citation_count", direction: domainMetadata?.default_sort_order || "desc" },
  });
  const pageResult = useStaticReportFrozenList<StaticCitationRankingRow>({
    reportId, listType: "citation.page", sort: pageSort, offset: exportMode ? 0 : pagePage * PAGE_SIZE,
    enabled: staticSortEnabled, fallbackRows: fallbackPageRanking as StaticCitationRankingRow[],
    filters: { search: exportMode ? undefined : pageSearch.trim() || undefined },
    fallbackTotal: pageMetadata?.total, defaultSort: { metricKey: pageMetadata?.default_sort_by || "citation_count", direction: pageMetadata?.default_sort_order || "desc" },
  });
  const categoryResult = useStaticReportFrozenList<StaticCitationCategoryRow>({
    reportId, listType: "citation.category", sort: categorySort, offset: exportMode ? 0 : categoryPage * PAGE_SIZE,
    enabled: staticSortEnabled, fallbackRows: (dashboard.category_breakdown || EMPTY_ROWS) as StaticCitationCategoryRow[],
    fallbackTotal: categoryMetadata?.total, defaultSort: { metricKey: categoryMetadata?.default_sort_by || "count", direction: categoryMetadata?.default_sort_order || "desc" },
  });
  const domainRanking = domainResult.items;
  const pageRanking = pageResult.items;
  const rankingCardRows = fallbackDomainRanking;

  const categoryBreakdown = useMemo(() => {
    if (categoryResult.error) return [];
    const explicit = categoryResult.items || [];
    if (explicit.length > 0) {
      return explicit.map((row: any) => ({
        label: row.label || row.domain_category || "Other",
        count: Number(row.count || row.citation_count || 0),
        pct: Number(row.pct || 0),
        color: getCategoryColor(row.label || row.domain_category),
      }));
    }
    const categories: Record<string, { label: string; count: number; color: string }> = {};
    for (const row of domainRanking) {
      const label = row.domain_category || "Other";
      if (!categories[label]) categories[label] = { label, count: 0, color: getCategoryColor(label) };
      categories[label].count += Number(row.citation_count || 0);
    }
    const total = Object.values(categories).reduce((sum, row) => sum + row.count, 0);
    return Object.values(categories).map((row) => ({
      ...row,
      pct: total > 0 ? Math.round((row.count / total) * 10000) / 100 : 0,
    }));
  }, [categoryResult.error, categoryResult.items, domainRanking]);

  const filteredDomainRows = useMemo(
    () => domainRanking.filter((row: any) => `${row.domain || ""} ${row.domain_category || ""}`.toLowerCase().includes(domainSearch.trim().toLowerCase())),
    [domainRanking, domainSearch],
  );
  const filteredPageRows = useMemo(
    () => pageRanking.filter((row: any) => `${row.url || ""} ${row.domain || ""} ${row.domain_category || ""}`.toLowerCase().includes(pageSearch.trim().toLowerCase())),
    [pageRanking, pageSearch],
  );
  const domainRows = staticSortEnabled ? domainRanking : exportMode ? fallbackDomainRanking.slice(0, PAGE_SIZE) : filteredDomainRows.slice(domainPage * PAGE_SIZE, domainPage * PAGE_SIZE + PAGE_SIZE);
  const pageRows = staticSortEnabled ? pageRanking : exportMode ? fallbackPageRanking.slice(0, PAGE_SIZE) : filteredPageRows.slice(pagePage * PAGE_SIZE, pagePage * PAGE_SIZE + PAGE_SIZE);
  const domainTotal = staticSortEnabled ? domainResult.total : domainSearch ? filteredDomainRows.length : domainResult.total;
  const pageTotal = staticSortEnabled ? pageResult.total : pageSearch ? filteredPageRows.length : pageResult.total;
  const domainHasMore = domainPage * PAGE_SIZE + domainRows.length < domainTotal;
  const pageHasMore = pagePage * PAGE_SIZE + pageRows.length < pageTotal;
  const domainStart = domainTotal > 0 ? domainPage * PAGE_SIZE + 1 : 0;
  const domainEnd = Math.min(domainTotal, domainPage * PAGE_SIZE + domainRows.length);
  const pageStart = pageTotal > 0 ? pagePage * PAGE_SIZE + 1 : 0;
  const pageEnd = Math.min(pageTotal, pagePage * PAGE_SIZE + pageRows.length);
  return (
    <div className="space-y-8">
      {domainResult.error && <StaticListErrorState onRetry={domainResult.retry} />}
      {pageResult.error && <StaticListErrorState onRetry={pageResult.retry} />}
      {categoryResult.error && <StaticListErrorState onRetry={categoryResult.retry} />}
      <section>
        <SectionHeader
          icon={<Link2 className="h-5 w-5 text-primary" />}
          title={t("citations.sectionShare.title")}
          subtitle={t("citations.sectionShare.subtitle")}
        />
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-4">
          <Card className="lg:col-span-2 shadow-none">
            <CardHeader className="pb-2">
              <div className="flex items-center gap-4">
                <div>
                  <div className="text-3xl font-bold flex items-center gap-2">
                    <span className="gradient-text-static">{summary.own_domain_share ?? "—"}%</span>
                  </div>
                  <PreviousPeriodChange value={summary.own_domain_share_change} />
                  <div className="text-xs text-muted-foreground mt-0.5 flex items-center gap-1">
                    {t("citations.sectionShare.yourShare")}
                    <span className="relative group">
                      <Info className="h-3 w-3 text-muted-foreground/50 cursor-help" />
                      <span className="absolute bottom-full left-1/2 -translate-x-1/2 mb-1.5 px-2.5 py-1.5 rounded-md bg-popover border text-popover-foreground text-[11px] leading-tight w-48 hidden group-hover:block shadow-md z-50">{t("citations.sectionShare.yourShareTooltip")}</span>
                    </span>
                  </div>
                </div>
                <div className="ml-auto text-right">
                  <div className="text-lg font-semibold">{summary.total_citations ?? 0}</div>
                  <div className="text-xs text-muted-foreground flex items-center gap-1 justify-end">
                    {t("citations.sectionShare.totalCitations")}
                    <span className="relative group">
                      <Info className="h-3 w-3 text-muted-foreground/50 cursor-help" />
                      <span className="absolute bottom-full right-0 mb-1.5 px-2.5 py-1.5 rounded-md bg-popover border text-popover-foreground text-[11px] leading-tight w-48 hidden group-hover:block shadow-md z-50">{t("citations.sectionShare.totalCitationsTooltip")}</span>
                    </span>
                  </div>
                </div>
              </div>
            </CardHeader>
            <CardContent>
              {showTrend ? (
                <ResponsiveContainer width="100%" height={260}>
                  <LineChart data={chartData}>
                    <XAxis dataKey="date" stroke="#888" fontSize={11} tickLine={false} axisLine={false} tickFormatter={fmtDate} />
                    <YAxis stroke="#888" fontSize={11} tickLine={false} axisLine={false} unit="%" width={45} domain={[(dataMin: number) => Math.max(0, Math.floor(dataMin - 2)), (dataMax: number) => Math.ceil(dataMax + 2)]} />
                    <Tooltip
                      content={<GlassTooltip />}
                      formatter={(value: any, name: any) => [
                        fmtPercentValue(value),
                        name === "prev_own_share" ? reportT("comparison.previousPeriod") : reportT("comparison.currentPeriod"),
                      ]}
                      labelFormatter={(value: any) => {
                        const text = String(value);
                        const date = text.includes("T") ? new Date(text) : new Date(`${text}T00:00:00`);
                        return date.toLocaleDateString();
                      }}
                    />
                    <Line type="monotone" dataKey="own_share" stroke="#10b981" strokeWidth={2.5} dot={{ r: 3, fill: "#10b981" }} activeDot={{ r: 5 }} connectNulls={false} />
                    <Line type="monotone" dataKey="prev_own_share" stroke="#94a3b8" strokeWidth={2} strokeDasharray="5 4" dot={false} connectNulls={false} />
                  </LineChart>
                </ResponsiveContainer>
              ) : (
                <div className="grid gap-3 sm:grid-cols-3">
                  <div className="rounded-lg border bg-muted/20 p-4">
                    <div className="text-xs text-muted-foreground">{t("citations.sectionShare.yourShare")}</div>
                    <div className="mt-2 text-2xl font-bold gradient-text-static">{summary.own_domain_share ?? "—"}%</div>
                  </div>
                  <div className="rounded-lg border bg-muted/20 p-4">
                    <div className="text-xs text-muted-foreground">{t("citations.sectionShare.totalCitations")}</div>
                    <div className="mt-2 text-2xl font-bold">{summary.total_citations ?? 0}</div>
                  </div>
                  <div className="rounded-lg border bg-muted/20 p-4">
                    <div className="text-xs text-muted-foreground">{t("citations.sectionShare.citationRank")}</div>
                    <div className="mt-2 text-2xl font-bold">{summary.own_rank ? `#${summary.own_rank}` : "—"}</div>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>

          <Card className="shadow-none">
            <CardHeader className="pb-2">
              <CardTitle className="text-sm font-medium flex items-center gap-2">
                <Trophy className="h-4 w-4 text-amber-500" />
                {t("citations.sectionShare.citationRank")}
              </CardTitle>
              <div className="text-2xl font-bold">{summary.own_rank ? `#${summary.own_rank}` : "—"}</div>
              <PreviousPeriodChange value={summary.own_rank_change} improvement="lower" unit="" absolute />
            </CardHeader>
            <CardContent className="space-y-1.5">
              <div className="text-[10px] text-muted-foreground uppercase tracking-wider mb-2 flex justify-between">
                <span>{t("citations.sectionShare.columnDomain")}</span>
                <span>{t("citations.sectionShare.columnShare")}</span>
              </div>
              {rankingCardRows.slice(0, 5).map((row: any, index: number) => (
                <div key={row.domain || index} className="flex items-center gap-2">
                  <span className="text-xs text-muted-foreground w-5">{row.rank ?? index + 1}.</span>
                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-1.5">
                      <span className={`text-sm truncate ${row.is_own ? "font-semibold text-blue-500" : ""}`}>{row.domain || "(unknown)"}</span>
                      {row.is_own && <span className="text-[9px] bg-blue-500/10 text-blue-500 px-1 rounded">{t("citations.sectionShare.ownBadge")}</span>}
                    </div>
                    <div className="h-1 bg-muted rounded-full mt-0.5 overflow-hidden">
                      <div className={`h-full rounded-full ${row.is_own ? "bg-blue-500" : "bg-muted-foreground/30"}`} style={{ width: `${Math.min(Number(row.share_pct || 0) * 3, 100)}%` }} />
                    </div>
                  </div>
                  <span className={`text-xs font-medium ${row.is_own ? "text-blue-500" : "text-muted-foreground"}`}>{row.share_pct}%</span>
                </div>
              ))}
              {rankingCardRows.length === 0 && <EmptyState message={t("citations.sectionShare.emptyDomains")} />}
              {rankingCardRows.length > 5 && (
                <Button variant="ghost" size="sm" className="w-full mt-2 text-xs" onClick={() => setExpandRanking(true)}>
                  <Expand className="h-3 w-3 mr-1" /> {t("citations.sectionShare.expand")}
                </Button>
              )}
            </CardContent>
          </Card>
        </div>
      </section>

      {categoryBreakdown.length > 0 && (
        <section>
          <SectionHeader
            icon={<Link2 className="h-5 w-5 text-primary" />}
            title={t("citations.sectionCategories.title")}
            subtitle={t("citations.sectionCategories.subtitle")}
          />
          <Card className="shadow-none">
            <CardContent className="relative pt-6">
              {staticSortEnabled && !categoryResult.unavailable && (
                <div className="mb-4 flex justify-end gap-2" data-sort-list="static-citation-categories">
                  <SortableMetricHeader label={t("citations.sectionDomains.columnCitations")} metricKey="count" sort={categorySort} onChange={(next) => { setCategorySort(next); setCategoryPage(0); }} />
                  <SortableMetricHeader label={t("citations.sectionDomains.columnShare")} metricKey="pct" sort={categorySort} onChange={(next) => { setCategorySort(next); setCategoryPage(0); }} />
                </div>
              )}
              <div className="flex h-8 rounded-md overflow-hidden mb-4 border">
                {categoryBreakdown.map((cat: any) => (
                  <div
                    key={cat.label}
                    className="flex items-center justify-center text-xs font-medium text-white transition-all hover:opacity-80"
                    style={{ width: `${cat.pct}%`, backgroundColor: cat.color, minWidth: cat.pct > 2 ? undefined : "20px" }}
                    title={`${cat.label}: ${cat.pct}%`}
                  >
                    {cat.pct >= 5 ? `${cat.pct}%` : ""}
                  </div>
                ))}
              </div>
              <div className="flex flex-wrap gap-4 justify-center">
                {categoryBreakdown.map((cat: any) => (
                  <div key={cat.label} className="flex items-center gap-1.5 text-sm">
                    <span className="w-2.5 h-2.5 rounded-full" style={{ backgroundColor: cat.color }} />
                    <span className="text-muted-foreground">{cat.label}</span>
                    <span className="font-medium">{cat.pct}%</span>
                  </div>
                ))}
              </div>
              {categoryResult.loading && (
                <div className="absolute inset-0 flex items-center justify-center rounded-lg bg-background/65 text-sm text-muted-foreground backdrop-blur-[1px]">
                  <Loader2 className="mr-2 h-4 w-4 animate-spin" />
                  {commonT("states.loading")}
                </div>
              )}
              {staticSortEnabled && !categoryResult.unavailable && (
                <div className="mt-4 flex items-center justify-between">
                  <span className="text-xs text-muted-foreground">{categoryPage * PAGE_SIZE + (categoryResult.items.length ? 1 : 0)}–{categoryPage * PAGE_SIZE + categoryResult.items.length} / {categoryResult.total}</span>
                  <div className="flex gap-2">
                    <Button variant="outline" size="sm" disabled={categoryPage === 0 || categoryResult.loading} onClick={() => setCategoryPage((value) => Math.max(0, value - 1))}>{reportT("detail.pagination.previous")}</Button>
                    <Button variant="outline" size="sm" disabled={(categoryPage + 1) * PAGE_SIZE >= categoryResult.total || categoryResult.loading} onClick={() => setCategoryPage((value) => value + 1)}>{reportT("detail.pagination.next")}</Button>
                  </div>
                </div>
              )}
            </CardContent>
          </Card>
        </section>
      )}

      <StaticCitationTable
        title={t("citations.sectionDomains.title")}
        subtitle={t("citations.sectionDomains.subtitle")}
        search={domainSearch}
        onSearch={(value) => { setDomainSearch(value); setDomainPage(0); }}
        placeholder={t("citations.sectionDomains.searchPlaceholder")}
        rows={domainRows}
        page={domainPage}
        start={domainStart}
        end={domainEnd}
        total={domainTotal}
        hasMore={domainHasMore}
        totalIsLowerBound={false}
        sort={domainSort}
        onSortChange={(next) => { setDomainSort(next); setDomainPage(0); }}
        sortingEnabled={staticSortEnabled && !domainResult.unavailable}
        sortListId="static-citation-domains"
        loading={domainResult.loading}
        exportMode={exportMode}
        onPrev={() => setDomainPage((value) => Math.max(0, value - 1))}
        onNext={() => setDomainPage((value) => value + 1)}
        type="domain"
      />

      <StaticCitationTable
        title={t("citations.sectionPages.title")}
        subtitle={t("citations.sectionPages.subtitle")}
        search={pageSearch}
        onSearch={(value) => { setPageSearch(value); setPagePage(0); }}
        placeholder={t("citations.sectionPages.searchPlaceholder")}
        rows={pageRows}
        page={pagePage}
        start={pageStart}
        end={pageEnd}
        total={pageTotal}
        hasMore={pageHasMore}
        totalIsLowerBound={false}
        sort={pageSort}
        onSortChange={(next) => { setPageSort(next); setPagePage(0); }}
        sortingEnabled={staticSortEnabled && !pageResult.unavailable}
        sortListId="static-citation-pages"
        loading={pageResult.loading}
        exportMode={exportMode}
        onPrev={() => setPagePage((value) => Math.max(0, value - 1))}
        onNext={() => setPagePage((value) => value + 1)}
        type="page"
      />

      <Dialog open={expandRanking} onOpenChange={setExpandRanking}>
        <DialogContent className="max-w-lg max-h-[80vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{t("citations.fullDialog.title")}</DialogTitle>
            <DialogDescription>{t("citations.fullDialog.description")}</DialogDescription>
          </DialogHeader>
          <div className="space-y-2 mt-2">
            {rankingCardRows.map((row: any, index: number) => (
              <div key={row.domain || index} className="flex items-center gap-2 py-1">
                <span className="text-xs text-muted-foreground w-6">{row.rank ?? index + 1}.</span>
                <img src={`https://www.google.com/s2/favicons?domain=${row.domain}&sz=16`} alt="" className="w-4 h-4 rounded-sm" onError={(event) => { (event.target as HTMLImageElement).style.display = "none"; }} />
                <span className={`text-sm flex-1 ${row.is_own ? "font-semibold text-blue-500" : ""}`}>
                  {row.domain || "(unknown)"}
                  {row.is_own && <span className="text-[9px] bg-blue-500/10 text-blue-500 px-1 ml-1 rounded">{t("citations.sectionShare.ownBadge")}</span>}
                </span>
                <span className="text-xs text-muted-foreground">{row.share_pct}%</span>
              </div>
            ))}
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}

function StaticCitationTable({
  title,
  subtitle,
  search,
  onSearch,
  placeholder,
  rows,
  page,
  start,
  end,
  total,
  hasMore,
  totalIsLowerBound = false,
  loading = false,
  sort,
  onSortChange,
  sortingEnabled,
  sortListId,
  exportMode = false,
  onPrev,
  onNext,
  type,
}: {
  title: string;
  subtitle: string;
  search: string;
  onSearch: (value: string) => void;
  placeholder: string;
  rows: any[];
  page: number;
  start: number;
  end: number;
  total: number;
  hasMore: boolean;
  totalIsLowerBound?: boolean;
  loading?: boolean;
  sort: MetricSortState;
  onSortChange: (next: MetricSortState) => void;
  sortingEnabled: boolean;
  sortListId: string;
  exportMode?: boolean;
  onPrev: () => void;
  onNext: () => void;
  type: "domain" | "page";
}) {
  const { t } = useTranslation("insights");
  const { t: commonT } = useTranslation("common");
  return (
    <section>
      <SectionHeader icon={<Link2 className="h-5 w-5 text-primary" />} title={title} subtitle={subtitle} />
      <Card className="shadow-none">
        <CardHeader className="pb-2">
          <div className="flex items-center gap-2">
            <div className="relative flex-1 max-w-xs">
              <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
              <Input placeholder={placeholder} className="pl-8 h-8 text-sm" value={search} onChange={(event) => onSearch(event.target.value)} />
            </div>
            <div className="text-xs text-muted-foreground">
              {t(totalIsLowerBound ? "citations.pagination.rangeMore" : "citations.pagination.range", { start, end, total })}
            </div>
          </div>
        </CardHeader>
        <CardContent className="p-0">
          <div className="rounded-md border overflow-hidden">
            <Table data-sort-list={sortListId}>
              <TableHeader>
                <TableRow className="bg-muted/20">
                  <TableHead className="w-[70px]">
                    {t("citations.sectionDomains.columnHash")}
                  </TableHead>
                  <TableHead>{type === "domain" ? t("citations.sectionDomains.columnDomain") : t("citations.sectionPages.columnPageUrl")}</TableHead>
                  <TableHead>{type === "domain" ? t("citations.sectionDomains.columnCategory") : t("citations.sectionPages.columnCategory")}</TableHead>
                  <TableHead className="text-right">{sortingEnabled ? <SortableMetricHeader label={type === "domain" ? t("citations.sectionDomains.columnCitations") : t("citations.sectionPages.columnCitations")} metricKey="citation_count" sort={sort} onChange={onSortChange} /> : type === "domain" ? t("citations.sectionDomains.columnCitations") : t("citations.sectionPages.columnCitations")}</TableHead>
                  <TableHead className="text-right">{sortingEnabled ? <SortableMetricHeader label={type === "domain" ? t("citations.sectionDomains.columnShare") : t("citations.sectionPages.columnShare")} metricKey="share_pct" sort={sort} onChange={onSortChange} /> : type === "domain" ? t("citations.sectionDomains.columnShare") : t("citations.sectionPages.columnShare")}</TableHead>
                  <TableHead className="text-right">{sortingEnabled ? <SortableMetricHeader label={type === "domain" ? t("citations.sectionDomains.columnChange") : t("citations.sectionPages.columnChange")} metricKey="change_pct" sort={sort} onChange={onSortChange} /> : type === "domain" ? t("citations.sectionDomains.columnChange") : t("citations.sectionPages.columnChange")}</TableHead>
                </TableRow>
              </TableHeader>
              <TableBody>
                {loading && (
                  <TableRow>
                    <TableCell colSpan={6} className="h-24 text-center text-sm text-muted-foreground">
                      <Loader2 className="mr-2 inline h-4 w-4 animate-spin" />
                      {commonT("states.loading")}
                    </TableCell>
                  </TableRow>
                )}
                {rows.map((row: any) => {
                  const categoryColor = getCategoryColor(row.domain_category);
                  const displayUrl = String(row.url || "").replace(/^https?:\/\//, "").replace(/\/$/, "");
                  return (
                    <TableRow key={type === "domain" ? row.domain || row.rank : row.url || row.rank} className={row.is_own ? "bg-blue-500/5" : ""}>
                      <TableCell className="text-muted-foreground">{row.rank}</TableCell>
                      <TableCell>
                        <div className="flex items-center gap-2 min-w-0">
                          <img src={`https://www.google.com/s2/favicons?domain=${row.domain}&sz=16`} alt="" className="w-4 h-4 rounded-sm flex-shrink-0" onError={(event) => { (event.target as HTMLImageElement).style.display = "none"; }} />
                          {type === "domain" ? (
                            <span className={row.is_own ? "font-semibold text-blue-500" : ""}>{row.domain || "(unknown)"}</span>
                          ) : (
                            <a href={row.url} target="_blank" rel="noopener noreferrer" className="text-sm text-blue-500 hover:underline truncate max-w-[400px]" title={row.url}>
                              {displayUrl.length > 60 ? displayUrl.slice(0, 60) + "..." : displayUrl}
                            </a>
                          )}
                          {row.is_own && <span className="text-[9px] bg-blue-500/10 text-blue-500 px-1 rounded">{t("citations.sectionShare.ownBadge")}</span>}
                        </div>
                      </TableCell>
                      <TableCell>
                        <Badge variant="outline" className="text-[10px]" style={{ borderColor: `${categoryColor}40`, color: categoryColor }}>
                          {row.domain_category || "Other"}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-right">{row.citation_count}</TableCell>
                      <TableCell className="text-right font-medium">{row.share_pct}%</TableCell>
                      <TableCell className="text-right text-xs">
                        {row.change_pct != null ? (
                          <span className={row.change_pct > 0 ? "text-emerald-500" : row.change_pct < 0 ? "text-red-400" : "text-muted-foreground"}>
                            {row.change_pct > 0 ? "+" : ""}{row.change_pct}%
                          </span>
                        ) : (
                          <span className="text-muted-foreground">—</span>
                        )}
                      </TableCell>
                    </TableRow>
                  );
                })}
                {!loading && rows.length === 0 && (
                  <TableRow>
                    <TableCell colSpan={6} className="h-24 text-center text-sm text-muted-foreground">
                      —
                    </TableCell>
                  </TableRow>
                )}
              </TableBody>
            </Table>
          </div>
          {!exportMode && (
            <RankingPagination
              page={page}
              start={start}
              end={end}
              total={total}
              hasMore={hasMore}
              totalIsLowerBound={totalIsLowerBound}
              loading={loading}
              onPrev={onPrev}
              onNext={onNext}
              t={t}
            />
          )}
        </CardContent>
      </Card>
    </section>
  );
}

function RankingPagination({
  page,
  start,
  end,
  total,
  hasMore,
  totalIsLowerBound = false,
  loading,
  onPrev,
  onNext,
  t,
}: {
  page: number;
  start: number;
  end: number;
  total: number;
  hasMore: boolean;
  totalIsLowerBound?: boolean;
  loading?: boolean;
  onPrev: () => void;
  onNext: () => void;
  t: any;
}) {
  return (
    <div className="flex items-center justify-between gap-3 border-t px-4 py-3">
      <div className="text-xs text-muted-foreground">
        {t(totalIsLowerBound ? "citations.pagination.rangeMore" : "citations.pagination.range", { start, end, total })}
      </div>
      <div className="flex items-center gap-2">
        <Button variant="outline" size="sm" onClick={onPrev} disabled={page === 0 || loading}>
          {t("citations.pagination.previous")}
        </Button>
        <Button variant="outline" size="sm" onClick={onNext} disabled={!hasMore || loading}>
          {t("citations.pagination.next")}
        </Button>
      </div>
    </div>
  );
}
