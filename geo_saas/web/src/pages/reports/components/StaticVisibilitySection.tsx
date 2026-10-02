import { useState } from "react";
import VisibilityDashboard from "@/components/insights/VisibilityDashboard";
import type { StaticReportSnapshot } from "@/lib/api";
import type { MetricSortState } from "@/lib/metricSort";
import { useStaticReportFrozenList } from "./useStaticReportFrozenList";
import { StaticListErrorState } from "./StaticListErrorState";
import { getStaticFrozenListMetadata } from "./staticReportFrozenMetadata";

export function StaticVisibilitySection({
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
  const dashboard = snapshot.visibility?.dashboard || {};
  const [rankingSorts, setRankingSorts] = useState<Record<"visibility" | "sov" | "position", MetricSortState>>({
    visibility: { metricKey: "visibility_pct", direction: "desc" },
    sov: { metricKey: "sov_pct", direction: "desc" },
    position: { metricKey: "avg_position", direction: "asc" },
  });
  const enabled = sortingAvailable && !exportMode;
  const visibilityMetadata = getStaticFrozenListMetadata(snapshot, "visibility.brand_visibility");
  const sovMetadata = getStaticFrozenListMetadata(snapshot, "visibility.brand_sov");
  const positionMetadata = getStaticFrozenListMetadata(snapshot, "visibility.brand_position");
  const visibilityRows = useStaticReportFrozenList({
    reportId, listType: "visibility.brand_visibility", sort: rankingSorts.visibility,
    offset: 0, limit: 100, enabled, fallbackRows: dashboard.visibility_ranking || [],
    fallbackTotal: visibilityMetadata?.total, defaultSort: { metricKey: visibilityMetadata?.default_sort_by || "visibility_pct", direction: visibilityMetadata?.default_sort_order || "desc" },
  });
  const sovRows = useStaticReportFrozenList({
    reportId, listType: "visibility.brand_sov", sort: rankingSorts.sov,
    offset: 0, limit: 100, enabled, fallbackRows: dashboard.sov_ranking || [],
    fallbackTotal: sovMetadata?.total, defaultSort: { metricKey: sovMetadata?.default_sort_by || "sov_pct", direction: sovMetadata?.default_sort_order || "desc" },
  });
  const positionRows = useStaticReportFrozenList({
    reportId, listType: "visibility.brand_position", sort: rankingSorts.position,
    offset: 0, limit: 100, enabled, fallbackRows: dashboard.position_ranking || [],
    fallbackTotal: positionMetadata?.total, defaultSort: { metricKey: positionMetadata?.default_sort_by || "avg_position", direction: positionMetadata?.default_sort_order || "asc" },
  });
  const controlsAvailable = enabled && !visibilityRows.unavailable && !sovRows.unavailable && !positionRows.unavailable;
  return (
    <div data-sort-list="static-visibility-ranking">
      {visibilityRows.error && <StaticListErrorState onRetry={visibilityRows.retry} />}
      {sovRows.error && <StaticListErrorState onRetry={sovRows.retry} />}
      {positionRows.error && <StaticListErrorState onRetry={positionRows.retry} />}
      <VisibilityDashboard
        timeSeriesComplete={enabled}
        data={{
          ...dashboard,
          visibility_ranking: visibilityRows.items,
          sov_ranking: sovRows.items,
          position_ranking: positionRows.items,
          filters: { ...(dashboard.filters || {}), window_days: snapshot.report?.window_days || 1 },
        }}
        staticMode
        staticReportId={enabled ? reportId : undefined}
        staticFrozenLists={snapshot.frozen_lists}
        comparisonEnabled
        exportMode={exportMode}
        loadingSections={{
          visibilityRanking: visibilityRows.loading,
          sovRanking: sovRows.loading,
          positionRanking: positionRows.loading,
        }}
        rankingSorts={controlsAvailable ? rankingSorts : undefined}
        onRankingSortChange={controlsAvailable ? (list, next) => setRankingSorts((current) => ({ ...current, [list]: next })) : undefined}
      />
    </div>
  );
}
