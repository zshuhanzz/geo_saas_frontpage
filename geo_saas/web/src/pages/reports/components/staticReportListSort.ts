import type { MetricSortState } from "@/lib/metricSort";

export const STATIC_REPORT_SORTABLE_VERSION = "static-report-v5";

export function shouldRenderStaticSortControls(snapshotVersion: string, exportMode: boolean): boolean {
  return snapshotVersion === STATIC_REPORT_SORTABLE_VERSION && !exportMode;
}

export function buildStaticListCriteriaKey(
  reportId: string,
  listType: string,
  sort: MetricSortState,
  offset: number,
  filters: Record<string, string | undefined> = {},
): string {
  return JSON.stringify([reportId, listType, sort.metricKey, sort.direction, offset, filters]);
}

export type StaticListErrorKind = "legacy" | "auth" | "server" | "network";

export function classifyStaticListError(error: unknown): StaticListErrorKind {
  const candidate = error as { status?: unknown; detail?: unknown } | null;
  const status = typeof candidate?.status === "number" ? candidate.status : 0;
  const detail = typeof candidate?.detail === "string" ? candidate.detail : "";
  if (status === 409 && detail === "sorting_unavailable_for_snapshot_version") return "legacy";
  if (status === 401 || status === 403) return "auth";
  if (status >= 400) return "server";
  return "network";
}

export function effectiveStaticListCriteria({
  exportMode,
  defaultSort,
  sort,
  offset,
  search = "",
  filters = {},
}: {
  exportMode: boolean;
  defaultSort: MetricSortState;
  sort: MetricSortState;
  offset: number;
  search?: string;
  filters?: Record<string, string | undefined>;
}) {
  return exportMode
    ? { sort: defaultSort, offset: 0, search: "", filters: {} }
    : { sort, offset, search, filters };
}

export function isHydratedDefaultStaticListCriteria({
  sort,
  defaultSort,
  offset,
  filters,
}: {
  sort: MetricSortState;
  defaultSort: MetricSortState;
  offset: number;
  filters: Record<string, string | undefined>;
}): boolean {
  return sort.metricKey === defaultSort.metricKey
    && sort.direction === defaultSort.direction
    && offset === 0
    && Object.values(filters).every((value) => !value?.trim());
}

export function selectStaticListPresentation<T>({
  reportId,
  cachedReportId,
  cachedRows,
  cachedTotal,
  fallbackRows,
  fallbackTotal,
  criteriaLoaded,
  hasError,
}: {
  reportId: string;
  cachedReportId: string;
  cachedRows: T[];
  cachedTotal: number;
  fallbackRows: T[];
  fallbackTotal: number;
  criteriaLoaded: boolean;
  hasError: boolean;
}) {
  const cacheBelongsToReport = cachedReportId === reportId;
  return {
    items: cacheBelongsToReport ? cachedRows : fallbackRows,
    total: cacheBelongsToReport ? cachedTotal : fallbackTotal,
    loading: !hasError && !criteriaLoaded,
  };
}

export function isStaticListRequestCurrent(
  capturedCriteriaKey: string,
  currentCriteriaKey: string,
  capturedSequence: number,
  currentSequence: number,
): boolean {
  return capturedCriteriaKey === currentCriteriaKey && capturedSequence === currentSequence;
}
