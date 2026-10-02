export type VisibilityRankingGroupBy = "topic" | "product";

interface MetricSortIdentity {
  metricKey: string;
  direction: "asc" | "desc";
}

export function buildVisibilityRankingQueryKey(
  clientId: string,
  params: Record<string, string>,
  groupBy: VisibilityRankingGroupBy,
): string {
  return JSON.stringify({
    clientId,
    groupBy,
    params: Object.entries(params).sort(([left], [right]) => left.localeCompare(right)),
  });
}

export function buildVisibilityRankingRequestKeys({
  clientId,
  params,
  groupBy,
  groupSort,
  promptSort,
  brandSort,
}: {
  clientId: string;
  params: Record<string, string>;
  groupBy: VisibilityRankingGroupBy;
  groupSort: MetricSortIdentity;
  promptSort: MetricSortIdentity;
  brandSort: MetricSortIdentity;
}): { baseQueryKey: string; groupQueryKey: string; promptQueryKey: string } {
  const baseQueryKey = buildVisibilityRankingQueryKey(clientId, params, groupBy);
  return {
    baseQueryKey,
    groupQueryKey: buildVisibilityRankingQueryKey(clientId, {
      ...params,
      sort_by: groupSort.metricKey,
      sort_order: groupSort.direction,
      brand_sort_by: brandSort.metricKey,
      brand_sort_order: brandSort.direction,
    }, groupBy),
    promptQueryKey: buildVisibilityRankingQueryKey(clientId, {
      ...params,
      sort_by: promptSort.metricKey,
      sort_order: promptSort.direction,
      brand_sort_by: brandSort.metricKey,
      brand_sort_order: brandSort.direction,
    }, groupBy),
  };
}

export function isVisibilityRankingRequestCurrent({
  capturedQueryKey,
  currentQueryKey,
  capturedRowSequence,
  currentRowSequence,
}: {
  capturedQueryKey: string;
  currentQueryKey: string;
  capturedRowSequence: number;
  currentRowSequence: number;
}): boolean {
  return capturedQueryKey === currentQueryKey && capturedRowSequence === currentRowSequence;
}
