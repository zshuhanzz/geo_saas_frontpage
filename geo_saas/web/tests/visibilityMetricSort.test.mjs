import assert from "node:assert/strict";
import {
  buildStandaloneVisibilitySorts,
  sortVisibilityTimeSeries,
  toCanonicalBrandMetricRows,
} from "../src/components/insights/visibilityMetricSort.ts";

const timeSeries = [
  { date: "2026-07-01", score: 10, own_count: 5, total: 8 },
  { date: "2026-07-02", score: 30, own_count: 2, total: 9 },
];
assert.deepEqual(
  sortVisibilityTimeSeries(timeSeries, true, { metricKey: "score", direction: "desc" }).map((row) => row.date),
  ["2026-07-02", "2026-07-01"],
  "the complete dynamic time-series table can be sorted by a metric",
);
assert.equal(
  sortVisibilityTimeSeries(timeSeries, false, { metricKey: "score", direction: "desc" }),
  timeSeries,
  "an unproven static/export slice is not client-sorted as though it were complete",
);

const productSorts = buildStandaloneVisibilitySorts("product");
assert.deepEqual(productSorts, {
  visibility: { metricKey: "visibility_pct", direction: "desc" },
  sov: { metricKey: "mention_count", direction: "desc" },
  position: { metricKey: "avg_position", direction: "asc" },
});
assert.notEqual(productSorts.visibility, productSorts.sov, "each rendered Product list has independent sort state");

const topicSorts = buildStandaloneVisibilitySorts("topic");
assert.deepEqual(topicSorts, {
  visibility: { metricKey: "own_sov_pct", direction: "desc" },
  sov: { metricKey: "mention_count", direction: "desc" },
  position: { metricKey: "mention_count", direction: "desc" },
});

assert.deepEqual(
  toCanonicalBrandMetricRows([
    { company_name: "Gamma", rank: 3, mention_count: 50 },
    { company_name: "Alpha", rank: 1, mention_count: 10 },
  ]),
  [
    { key: "Gamma", name: "Gamma", rank: 3, mentionCount: 50, isOwn: false },
    { key: "Alpha", name: "Alpha", rank: 1, mentionCount: 10, isOwn: false },
  ],
  "server metric ordering never rewrites canonical rank values",
);

console.log("visibilityMetricSort tests passed");
