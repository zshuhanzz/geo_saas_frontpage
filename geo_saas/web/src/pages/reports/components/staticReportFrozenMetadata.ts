import type { StaticReportSnapshot } from "@/lib/api";
import type { MetricSortState } from "@/lib/metricSort";

export interface StaticFrozenListScopeMetadata {
  parent_key: string;
  prompt_key: string;
  total: number;
}

export interface StaticFrozenListMetadata {
  total: number;
  default_sort_by: string;
  default_sort_order: "asc" | "desc";
  scopes?: StaticFrozenListScopeMetadata[];
}

export function getStaticFrozenListMetadata(
  snapshot: StaticReportSnapshot,
  listType: string,
): StaticFrozenListMetadata | undefined {
  return snapshot.frozen_lists?.[listType];
}

export function getStaticFrozenListDefaultSort(
  metadata: StaticFrozenListMetadata | undefined,
  fallback: MetricSortState,
): MetricSortState {
  return metadata
    ? { metricKey: metadata.default_sort_by, direction: metadata.default_sort_order }
    : fallback;
}

export function getStaticFrozenScopeTotal(
  metadata: StaticFrozenListMetadata | undefined,
  parentKey: string,
  promptKey = "",
): number | undefined {
  return metadata?.scopes?.find((scope) => (
    scope.parent_key === parentKey && scope.prompt_key === promptKey
  ))?.total;
}
