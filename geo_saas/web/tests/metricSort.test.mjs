import assert from "node:assert/strict";

import {
  buildMetricSortRequestKey,
  defaultMetricSortDirection,
  isCompleteMetricCollection,
  isBusinessMetricSortKey,
  isMetricSortRequestCurrent,
  metricSortCurrentStateKey,
  nextMetricSort,
  resetPageForCriteriaChange,
  resetVisibleCountForCriteriaChange,
  sanitizeMetricSort,
  sortCompleteMetricRows,
  withMetricSortParams,
} from "../src/lib/metricSort.ts";

for (const key of [
  "rank",
  "id",
  "client_id",
  "index",
  "order",
  "sequence",
  "row_number",
  "row_no",
  "ordinal",
  "no",
  "number",
  "serial",
  "serial_no",
  "serial_number",
  "display_order",
]) {
  assert.equal(isBusinessMetricSortKey(key), false, `${key} is a sequence or identifier, not a business metric`);
}
for (const key of ["brand_rank", "avg_position", "citation_count", "prompt_count", "visibility_score"]) {
  assert.equal(isBusinessMetricSortKey(key), true, `${key} is a sortable business metric`);
}

assert.equal(metricSortCurrentStateKey(null), "metricSort.currentUnsorted");
assert.equal(metricSortCurrentStateKey("asc"), "metricSort.currentAscending");
assert.equal(metricSortCurrentStateKey("desc"), "metricSort.currentDescending");

assert.equal(defaultMetricSortDirection("rank"), "asc");
assert.equal(defaultMetricSortDirection("avg_position"), "asc");
assert.equal(defaultMetricSortDirection("visibility_score"), "desc");

assert.deepEqual(nextMetricSort(null, "citation_count"), {
  metricKey: "citation_count",
  direction: "desc",
});
assert.deepEqual(
  nextMetricSort({ metricKey: "citation_count", direction: "desc" }, "citation_count"),
  { metricKey: "citation_count", direction: "asc" },
);
assert.deepEqual(
  nextMetricSort({ metricKey: "citation_count", direction: "asc" }, "citation_count"),
  { metricKey: "citation_count", direction: "desc" },
);
assert.deepEqual(
  nextMetricSort({ metricKey: "citation_count", direction: "asc" }, "rank"),
  { metricKey: "rank", direction: "asc" },
);

assert.equal(isCompleteMetricCollection([{ id: "1" }], 1), true);
assert.equal(isCompleteMetricCollection([{ id: "1" }], 2), false);
assert.equal(isCompleteMetricCollection([{ id: "1" }], undefined), false);

const completeRows = [
  { id: "z", label: "Zulu", metric: null },
  { id: "b", label: "beta", metric: 2 },
  { id: "a2", label: "Alpha", metric: 2 },
  { id: "a1", label: "alpha", metric: 2 },
  { id: "c", label: "Charlie", metric: 1 },
];

assert.deepEqual(
  sortCompleteMetricRows(completeRows, completeRows.length, {
    metricKey: "metric",
    direction: "asc",
    tieTextKey: "label",
    tieIdKey: "id",
  }).map((row) => row.id),
  ["c", "a1", "a2", "b", "z"],
  "ascending sort keeps NULL last and uses normalized text then id ties",
);
assert.deepEqual(
  sortCompleteMetricRows(completeRows, completeRows.length, {
    metricKey: "metric",
    direction: "desc",
    tieTextKey: "label",
    tieIdKey: "id",
  }).map((row) => row.id),
  ["a1", "a2", "b", "c", "z"],
  "descending sort also keeps NULL last and keeps deterministic ties",
);
const incompleteRows = completeRows.slice(0, 2);
assert.equal(
  sortCompleteMetricRows(incompleteRows, completeRows.length, {
    metricKey: "metric",
    direction: "asc",
    tieTextKey: "label",
    tieIdKey: "id",
  }),
  incompleteRows,
  "an incomplete page is never client-sorted as if it were the full result",
);

assert.equal(resetPageForCriteriaChange(4, "old", "old"), 4);
assert.equal(resetPageForCriteriaChange(4, "old", "new"), 0);
assert.equal(resetVisibleCountForCriteriaChange(30, "same", "same", 10), 30);
assert.equal(resetVisibleCountForCriteriaChange(30, "old-filter", "new-filter", 10), 10);

const requestKey = buildMetricSortRequestKey("client-a", { date_from: "2026-07-01" }, {
  metricKey: "rank",
  direction: "asc",
});
assert.equal(
  requestKey,
  buildMetricSortRequestKey("client-a", { date_from: "2026-07-01" }, {
    metricKey: "rank",
    direction: "asc",
  }),
);
assert.notEqual(
  requestKey,
  buildMetricSortRequestKey("client-a", { date_from: "2026-07-01" }, {
    metricKey: "rank",
    direction: "desc",
  }),
);
assert.equal(isMetricSortRequestCurrent(requestKey, requestKey, 2, 2), true);
assert.equal(isMetricSortRequestCurrent(requestKey, `${requestKey}:stale`, 2, 2), false);
assert.equal(isMetricSortRequestCurrent(requestKey, requestKey, 1, 2), false);

const standaloneFallback = { metricKey: "mention_count", direction: "desc" };
assert.deepEqual(
  sanitizeMetricSort(
    { metricKey: "visibility_pct", direction: "desc" },
    ["mention_count", "sov_pct", "avg_position"],
    standaloneFallback,
  ),
  standaloneFallback,
  "switching Brand to Product cannot carry an unsupported Brand metric into the standalone API",
);
const allowedStandalone = { metricKey: "avg_position", direction: "asc" };
assert.equal(
  sanitizeMetricSort(allowedStandalone, ["mention_count", "sov_pct", "avg_position"], standaloneFallback),
  allowedStandalone,
  "an allowed standalone metric keeps its object identity",
);

assert.deepEqual(
  withMetricSortParams({ date_from: "2026-07-01" }, { metricKey: "rank", direction: "asc" }),
  { date_from: "2026-07-01", sort_by: "rank", sort_order: "asc" },
);
assert.deepEqual(
  withMetricSortParams(
    { limit: "20", offset: "40" },
    { metricKey: "citation_count", direction: "desc" },
    "prompt_",
  ),
  { limit: "20", offset: "40", prompt_sort_by: "citation_count", prompt_sort_order: "desc" },
);

console.log("metricSort tests passed");
