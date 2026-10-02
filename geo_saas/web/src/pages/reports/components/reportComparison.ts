import { comparisonIndicatorState } from "../../../lib/comparisonIndicator.ts";

export type ImprovementDirection = "higher" | "lower";
export type ComparisonTone = "positive" | "negative" | "neutral";

export interface ComparisonPresentation {
  direction: "up" | "down" | "none";
  tone: ComparisonTone;
}

export function comparisonPresentation(
  change: number | null | undefined,
  improvement: ImprovementDirection,
): ComparisonPresentation {
  const state = comparisonIndicatorState(change, improvement, true);
  return { direction: state.direction, tone: state.tone };
}

interface FrozenSnapshotLike {
  visibility?: { dashboard?: Record<string, unknown> };
  citations?: { dashboard?: Record<string, unknown> };
  sentiment?: { dashboard?: Record<string, unknown> };
}

export function canFilterFrozenSnapshot(snapshot: FrozenSnapshotLike): boolean {
  const visibility = snapshot.visibility?.dashboard || {};
  const citations = snapshot.citations?.dashboard || {};
  const sentiment = snapshot.sentiment?.dashboard || {};
  const previousVisibility = (visibility.previous || {}) as Record<string, unknown>;
  const previousCitations = (citations.previous || {}) as Record<string, unknown>;
  const previousSentiment = (sentiment.previous || {}) as Record<string, unknown>;
  return (
    !visibility.source_rows_limited &&
    !visibility.response_source_rows_limited &&
    Array.isArray(visibility.source_rows) &&
    Array.isArray(visibility.response_source_rows) &&
    !previousVisibility.source_rows_limited &&
    !previousVisibility.response_source_rows_limited &&
    Array.isArray(previousVisibility.source_rows) &&
    Array.isArray(previousVisibility.response_source_rows) &&
    !citations.source_rows_limited &&
    Array.isArray(citations.source_rows) &&
    !previousCitations.source_rows_limited &&
    Array.isArray(previousCitations.source_rows) &&
    !sentiment.source_rows_limited &&
    Array.isArray(sentiment.source_rows) &&
    !previousSentiment.source_rows_limited &&
    Array.isArray(previousSentiment.source_rows)
  );
}
