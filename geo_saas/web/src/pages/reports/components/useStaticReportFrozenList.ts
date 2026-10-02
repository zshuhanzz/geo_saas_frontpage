import { useEffect, useRef, useState } from "react";
import { getStaticReportFrozenList } from "@/lib/api";
import type { MetricSortState } from "@/lib/metricSort";
import { buildStaticListCriteriaKey, classifyStaticListError, isHydratedDefaultStaticListCriteria, isStaticListRequestCurrent, selectStaticListPresentation, type StaticListErrorKind } from "./staticReportListSort";

export function useStaticReportFrozenList<T extends object>({
  reportId,
  listType,
  sort,
  offset,
  limit = 20,
  enabled,
  fallbackRows,
  fallbackTotal,
  defaultSort = sort,
  filters = {},
}: {
  reportId: string;
  listType: string;
  sort: MetricSortState;
  offset: number;
  limit?: number;
  enabled: boolean;
  fallbackRows: T[];
  fallbackTotal?: number;
  defaultSort?: MetricSortState;
  filters?: { parent_key?: string; prompt_key?: string; search?: string; sentiment?: string };
}) {
  const [items, setItems] = useState<T[]>(fallbackRows);
  const [total, setTotal] = useState(fallbackTotal ?? fallbackRows.length);
  const [itemsReportId, setItemsReportId] = useState(reportId);
  const [loadedCriteriaKey, setLoadedCriteriaKey] = useState("");
  const [unavailableCriteriaKey, setUnavailableCriteriaKey] = useState("");
  const [errorState, setErrorState] = useState<{ key: string; kind: Exclude<StaticListErrorKind, "legacy">; error: unknown } | null>(null);
  const [retryNonce, setRetryNonce] = useState(0);
  const requestSequence = useRef(0);
  const parentKey = filters.parent_key;
  const promptKey = filters.prompt_key;
  const search = filters.search;
  const sentiment = filters.sentiment;
  const criteriaKey = buildStaticListCriteriaKey(reportId, listType, sort, offset, { parent_key: parentKey, prompt_key: promptKey, search, sentiment });
  const defaultCriteriaHydrated = isHydratedDefaultStaticListCriteria({
    sort,
    defaultSort,
    offset,
    filters: { parent_key: parentKey, prompt_key: promptKey, search, sentiment },
  });
  const exactFallbackTotal = fallbackTotal ?? fallbackRows.length;

  useEffect(() => {
    if (!enabled || !reportId || defaultCriteriaHydrated) {
      requestSequence.current += 1;
      return;
    }
    const controller = new AbortController();
    const capturedCriteriaKey = criteriaKey;
    const capturedSequence = ++requestSequence.current;
    void getStaticReportFrozenList(reportId, listType, {
      sort_by: sort.metricKey,
      sort_order: sort.direction,
      limit,
      offset,
      parent_key: parentKey,
      prompt_key: promptKey,
      search,
      sentiment,
    }, { signal: controller.signal })
      .then((response) => {
        if (!isStaticListRequestCurrent(capturedCriteriaKey, capturedCriteriaKey, capturedSequence, requestSequence.current)) return;
        setItems((response.items || []) as T[]);
        setTotal(response.total || 0);
        setItemsReportId(reportId);
        setLoadedCriteriaKey(capturedCriteriaKey);
        setUnavailableCriteriaKey("");
        setErrorState(null);
      })
      .catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return;
        if (!isStaticListRequestCurrent(capturedCriteriaKey, capturedCriteriaKey, capturedSequence, requestSequence.current)) return;
        const kind = classifyStaticListError(error);
        if (kind === "legacy") {
          setLoadedCriteriaKey(capturedCriteriaKey);
          setUnavailableCriteriaKey(capturedCriteriaKey);
          setErrorState(null);
        } else {
          setErrorState({ key: capturedCriteriaKey, kind, error });
        }
      });
    return () => controller.abort();
  }, [criteriaKey, defaultCriteriaHydrated, enabled, limit, listType, offset, parentKey, promptKey, reportId, retryNonce, search, sentiment, sort.direction, sort.metricKey]);

  if (!enabled) {
    return { items: fallbackRows, total: exactFallbackTotal, loading: false, unavailable: false, error: null, retry: () => setRetryNonce((value) => value + 1) };
  }
  if (defaultCriteriaHydrated) {
    return { items: fallbackRows, total: exactFallbackTotal, loading: false, unavailable: false, error: null, retry: () => setRetryNonce((value) => value + 1) };
  }
  if (unavailableCriteriaKey === criteriaKey) {
    return { items: fallbackRows, total: exactFallbackTotal, loading: false, unavailable: true, error: null, retry: () => setRetryNonce((value) => value + 1) };
  }
  const currentError = errorState?.key === criteriaKey ? errorState : null;
  const presentation = selectStaticListPresentation({
    reportId,
    cachedReportId: itemsReportId,
    cachedRows: items,
    cachedTotal: total,
    fallbackRows,
    fallbackTotal: exactFallbackTotal,
    criteriaLoaded: loadedCriteriaKey === criteriaKey,
    hasError: Boolean(currentError),
  });
  return {
    ...presentation,
    unavailable: false,
    error: currentError,
    retry: () => setRetryNonce((value) => value + 1),
  };
}
