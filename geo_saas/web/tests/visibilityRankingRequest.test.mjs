import assert from "node:assert/strict";
import {
  buildVisibilityRankingRequestKeys,
  buildVisibilityRankingQueryKey,
  isVisibilityRankingRequestCurrent,
} from "../src/components/insights/visibilityRankingRequest.ts";

const matrixKeys = buildVisibilityRankingRequestKeys({
  clientId: "client-a",
  params: { date_from: "2026-07-01" },
  groupBy: "topic",
  groupSort: { metricKey: "prompt_count", direction: "desc" },
  promptSort: { metricKey: "total_mentions", direction: "desc" },
  brandSort: { metricKey: "rank", direction: "asc" },
});
const promptResortedKeys = buildVisibilityRankingRequestKeys({
  clientId: "client-a",
  params: { date_from: "2026-07-01" },
  groupBy: "topic",
  groupSort: { metricKey: "prompt_count", direction: "desc" },
  promptSort: { metricKey: "total_mentions", direction: "asc" },
  brandSort: { metricKey: "rank", direction: "asc" },
});
assert.equal(matrixKeys.groupQueryKey, promptResortedKeys.groupQueryKey,
  "sorting expanded prompts must not refetch or reset the independent group list");
assert.notEqual(matrixKeys.promptQueryKey, promptResortedKeys.promptQueryKey,
  "sorting expanded prompts replaces only the prompt-list request identity");

const originalKey = buildVisibilityRankingQueryKey(
  "client-a",
  { date_to: "2026-07-07", topic_ids: "topic-a", date_from: "2026-07-01" },
  "topic",
);
const equivalentKey = buildVisibilityRankingQueryKey(
  "client-a",
  { date_from: "2026-07-01", date_to: "2026-07-07", topic_ids: "topic-a" },
  "topic",
);
assert.equal(originalKey, equivalentKey, "request identity is stable regardless of parameter insertion order");

const replacementKey = buildVisibilityRankingQueryKey(
  "client-a",
  { date_from: "2026-07-08", date_to: "2026-07-14", topic_ids: "topic-b" },
  "topic",
);
assert.equal(
  isVisibilityRankingRequestCurrent({ capturedQueryKey: originalKey, currentQueryKey: replacementKey, capturedRowSequence: 3, currentRowSequence: 3 }),
  false,
  "an old row response is rejected after the ranking query is replaced even when its row sequence matches",
);
assert.equal(
  isVisibilityRankingRequestCurrent({ capturedQueryKey: replacementKey, currentQueryKey: replacementKey, capturedRowSequence: 2, currentRowSequence: 3 }),
  false,
  "an older request for the same row and query is rejected",
);
assert.equal(
  isVisibilityRankingRequestCurrent({ capturedQueryKey: replacementKey, currentQueryKey: replacementKey, capturedRowSequence: 3, currentRowSequence: 3 }),
  true,
);

console.log("visibilityRankingRequest tests passed");
