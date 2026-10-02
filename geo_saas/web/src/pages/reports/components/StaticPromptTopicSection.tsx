import { useState } from "react";
import type { ReactNode } from "react";
import { useTranslation } from "react-i18next";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import type { StaticReportSnapshot } from "@/lib/api";
import type { MetricSortState } from "@/lib/metricSort";
import { SnapshotTable, type SnapshotColumn } from "./SnapshotTable";
import { formatNumber, type SnapshotRow } from "./reportUtils";
import { useStaticReportFrozenList } from "./useStaticReportFrozenList";
import { StaticListErrorState } from "./StaticListErrorState";
import { effectiveStaticListCriteria } from "./staticReportListSort";
import type { StaticFrozenListMetadata } from "./staticReportFrozenMetadata";
import { getStaticFrozenListMetadata } from "./staticReportFrozenMetadata";

const PAGE_SIZE = 20;

function RankingCard({
  reportId,
  listType,
  title,
  fallbackRows,
  columns,
  initialSort,
  sortingAvailable,
  exportMode,
  getRowKey,
  expandable,
  sortListId,
  metadata,
}: {
  reportId: string;
  listType: string;
  title: string;
  fallbackRows: SnapshotRow[];
  columns: SnapshotColumn[];
  initialSort: MetricSortState;
  sortingAvailable: boolean;
  exportMode: boolean;
  getRowKey: (row: SnapshotRow, index: number) => string;
  expandable?: (row: SnapshotRow) => ReactNode;
  sortListId: string;
  metadata?: StaticFrozenListMetadata;
}) {
  const { t } = useTranslation("reports");
  const [sort, setSort] = useState(initialSort);
  const [offset, setOffset] = useState(0);
  const [search, setSearch] = useState("");
  const enabled = sortingAvailable && !exportMode;
  const criteria = effectiveStaticListCriteria({
    exportMode,
    defaultSort: initialSort,
    sort,
    offset,
    search,
  });
  const result = useStaticReportFrozenList({
    reportId, listType, sort: criteria.sort, offset: criteria.offset, enabled, fallbackRows,
    filters: { search: criteria.search.trim() || undefined },
    fallbackTotal: metadata?.total,
    defaultSort: { metricKey: metadata?.default_sort_by || initialSort.metricKey, direction: metadata?.default_sort_order || initialSort.direction },
  });
  const controlsEnabled = enabled && !result.unavailable;
  return (
    <Card className="shadow-none">
      <CardHeader><CardTitle className="text-base">{title}</CardTitle></CardHeader>
      <CardContent className="space-y-3">
        {result.error && <StaticListErrorState onRetry={result.retry} />}
        <SnapshotTable
          rows={result.items}
          getRowKey={getRowKey}
          columns={columns}
          expandable={expandable}
          initialLimit={PAGE_SIZE}
          sort={sort}
          onSortChange={(next) => { setSort(next); setOffset(0); }}
          sortingEnabled={controlsEnabled}
          sortListId={sortListId}
          query={exportMode ? "" : search}
          onQueryChange={enabled ? (value) => { setSearch(value); setOffset(0); } : undefined}
        />
        {controlsEnabled && (
          <div className="flex items-center justify-between">
            <span className="text-xs text-muted-foreground">{offset + (result.items.length ? 1 : 0)}–{offset + result.items.length} / {result.total}</span>
            <div className="flex gap-2">
              <Button variant="outline" size="sm" disabled={offset === 0 || result.loading} onClick={() => setOffset((value) => Math.max(0, value - PAGE_SIZE))}>{t("detail.pagination.previous")}</Button>
              <Button variant="outline" size="sm" disabled={offset + result.items.length >= result.total || result.loading} onClick={() => setOffset((value) => value + PAGE_SIZE)}>{t("detail.pagination.next")}</Button>
            </div>
          </div>
        )}
      </CardContent>
    </Card>
  );
}

export function StaticPromptTopicSection({
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
  const { t } = useTranslation("reports");
  const prompts = snapshot.prompts?.ranking || [];
  const topics = snapshot.topics?.ranking || [];
  const products = snapshot.visibility?.dashboard?.product_sov_ranking || [];
  return (
    <section className="space-y-4">
      <h2 className="text-xl font-semibold">{t("detail.sections.promptTopic")}</h2>
      <div className="grid gap-4 xl:grid-cols-3">
        <RankingCard
          reportId={reportId}
          listType="prompt.ranking"
          title={t("fields.prompt")}
          fallbackRows={prompts}
          initialSort={{ metricKey: "mention_count", direction: "desc" }}
          sortingAvailable={sortingAvailable}
          exportMode={exportMode}
          sortListId="static-prompt-ranking"
          metadata={getStaticFrozenListMetadata(snapshot, "prompt.ranking")}
          getRowKey={(row, index) => String(row.row_key || row.prompt_id || index)}
          columns={[
            { key: "prompt_text", label: t("fields.prompt"), render: (row) => <span className="line-clamp-2 whitespace-normal">{row.prompt_text || "-"}</span> },
            { key: "mention_count", label: t("fields.mentions"), className: "text-right", metricKey: "mention_count", render: (row) => formatNumber(row.mention_count) },
            { key: "citation_count", label: t("fields.citations"), className: "text-right", metricKey: "citation_count", render: (row) => formatNumber(row.citation_count) },
          ]}
          expandable={(row) => <div className="grid gap-1"><div>{t("fields.intent")}: {row.intent || "-"}</div><div>{t("fields.platform")}: {row.platform || "-"}</div><div>{t("fields.country")}: {row.country || "-"}</div><div>{t("fields.language")}: {row.language || "-"}</div></div>}
        />
        <RankingCard
          reportId={reportId}
          listType="topic.ranking"
          title={t("fields.topic")}
          fallbackRows={topics}
          initialSort={{ metricKey: "mention_count", direction: "desc" }}
          sortingAvailable={sortingAvailable}
          exportMode={exportMode}
          sortListId="static-topic-ranking"
          metadata={getStaticFrozenListMetadata(snapshot, "topic.ranking")}
          getRowKey={(row, index) => String(row.row_key || row.topic_name || index)}
          columns={[
            { key: "topic_name", label: t("fields.topic") },
            { key: "mention_count", label: t("fields.mentions"), className: "text-right", metricKey: "mention_count", render: (row) => formatNumber(row.mention_count) },
            { key: "citation_count", label: t("fields.citations"), className: "text-right", metricKey: "citation_count", render: (row) => formatNumber(row.citation_count) },
          ]}
        />
        <RankingCard
          reportId={reportId}
          listType="visibility.product"
          title={t("fields.product")}
          fallbackRows={products}
          initialSort={{ metricKey: "total_mentions", direction: "desc" }}
          sortingAvailable={sortingAvailable}
          exportMode={exportMode}
          sortListId="static-product-ranking"
          metadata={getStaticFrozenListMetadata(snapshot, "visibility.product")}
          getRowKey={(row, index) => String(row.row_key || row.product || index)}
          columns={[
            { key: "product", label: t("fields.product") },
            { key: "prompt_count", label: t("fields.prompts"), className: "text-right", metricKey: "prompt_count", render: (row) => formatNumber(row.prompt_count) },
            { key: "total_mentions", label: t("fields.mentions"), className: "text-right", metricKey: "total_mentions", render: (row) => formatNumber(row.total_mentions) },
          ]}
        />
      </div>
    </section>
  );
}
