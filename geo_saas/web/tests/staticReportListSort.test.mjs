import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import {
  STATIC_REPORT_SORTABLE_VERSION,
  buildStaticListCriteriaKey,
  classifyStaticListError,
  effectiveStaticListCriteria,
  isHydratedDefaultStaticListCriteria,
  selectStaticListPresentation,
  isStaticListRequestCurrent,
  shouldRenderStaticSortControls,
} from "../src/pages/reports/components/staticReportListSort.ts";
import { ApiError } from "../src/lib/api/_errors.ts";
import { ScopedStaticListRequestManager } from "../src/pages/reports/components/scopedStaticListRequest.ts";
import { getStaticFrozenListMetadata, getStaticFrozenScopeTotal } from "../src/pages/reports/components/staticReportFrozenMetadata.ts";

assert.equal(STATIC_REPORT_SORTABLE_VERSION, "static-report-v5");
assert.equal(shouldRenderStaticSortControls("static-report-v5", false), true);
assert.equal(shouldRenderStaticSortControls("static-report-v3", false), false);
assert.equal(shouldRenderStaticSortControls("static-report-v5", true), false);

assert.equal(
  buildStaticListCriteriaKey("report-1", "citation.domain", { metricKey: "citation_count", direction: "desc" }, 20),
  '["report-1","citation.domain","citation_count","desc",20,{}]',
);
assert.notEqual(
  buildStaticListCriteriaKey("report-1", "citation.domain", { metricKey: "citation_count", direction: "desc" }, 0, { search: "a" }),
  buildStaticListCriteriaKey("report-1", "citation.domain", { metricKey: "citation_count", direction: "desc" }, 0, { search: "b" }),
);
assert.equal(classifyStaticListError(new ApiError("sorting_unavailable_for_snapshot_version", 409)), "legacy");
assert.equal(classifyStaticListError(new ApiError("different_conflict", 409)), "server");
assert.equal(classifyStaticListError(new ApiError("expired", 401)), "auth");
assert.equal(classifyStaticListError(new ApiError("busy", 503)), "server");
assert.equal(classifyStaticListError(new TypeError("network")), "network");

assert.deepEqual(effectiveStaticListCriteria({
  exportMode: true,
  defaultSort: { metricKey: "citation_count", direction: "desc" },
  sort: { metricKey: "share_pct", direction: "asc" },
  offset: 40,
  search: "filtered",
  filters: { sentiment: "Positive" },
}), {
  sort: { metricKey: "citation_count", direction: "desc" },
  offset: 0,
  search: "",
  filters: {},
});

let initialFetchCalls = 0;
const initialHydrated = isHydratedDefaultStaticListCriteria({
  sort: { metricKey: "citation_count", direction: "desc" },
  defaultSort: { metricKey: "citation_count", direction: "desc" },
  offset: 0,
  filters: {},
});
if (!initialHydrated) initialFetchCalls += 1;
assert.equal(initialFetchCalls, 0);
assert.deepEqual(selectStaticListPresentation({
  reportId: "report-1",
  cachedReportId: "report-1",
  cachedRows: ["fallback-now"],
  cachedTotal: 37,
  fallbackRows: ["fallback-now"],
  fallbackTotal: 37,
  criteriaLoaded: true,
  hasError: false,
}), { items: ["fallback-now"], total: 37, loading: false });

let changedFetchCalls = 0;
const changedHydrated = isHydratedDefaultStaticListCriteria({
  sort: { metricKey: "share_pct", direction: "asc" },
  defaultSort: { metricKey: "citation_count", direction: "desc" },
  offset: 0,
  filters: {},
});
if (!changedHydrated) changedFetchCalls += 1;
assert.equal(changedFetchCalls, 1);
assert.deepEqual(selectStaticListPresentation({
  reportId: "report-1",
  cachedReportId: "report-1",
  cachedRows: ["previous-page"],
  cachedTotal: 37,
  fallbackRows: ["fallback-now"],
  fallbackTotal: 37,
  criteriaLoaded: false,
  hasError: false,
}), { items: ["previous-page"], total: 37, loading: true });
assert.deepEqual(selectStaticListPresentation({
  reportId: "report-1",
  cachedReportId: "report-1",
  cachedRows: ["previous-page"],
  cachedTotal: 37,
  fallbackRows: ["fallback-now"],
  fallbackTotal: 37,
  criteriaLoaded: false,
  hasError: true,
}), { items: ["previous-page"], total: 37, loading: false });

const metadataSnapshot = {
  frozen_lists: {
    "visibility.topic_prompt_brand": {
      total: 9,
      default_sort_by: "rank",
      default_sort_order: "asc",
      scopes: [{ parent_key: "topic-1", prompt_key: "prompt-1", total: 23 }],
    },
  },
};
const nestedMetadata = getStaticFrozenListMetadata(metadataSnapshot, "visibility.topic_prompt_brand");
assert.equal(getStaticFrozenScopeTotal(nestedMetadata, "topic-1", "prompt-1"), 23);
assert.equal(isStaticListRequestCurrent("a", "a", 2, 2), true);
assert.equal(isStaticListRequestCurrent("a", "b", 2, 2), false);
assert.equal(isStaticListRequestCurrent("a", "a", 1, 2), false);

const deferred = () => {
  let resolve;
  let reject;
  const promise = new Promise((ok, fail) => { resolve = ok; reject = fail; });
  return { promise, resolve, reject };
};
const scopedManager = new ScopedStaticListRequestManager();
const page2 = deferred();
const page1 = deferred();
let page2Signal;
const identity = (offset) => ({
  reportId: "report-1",
  listType: "visibility.topic_brand",
  parentKey: "topic-1",
  promptKey: "",
  sortBy: "mention_count",
  sortOrder: "desc",
  offset,
});
const page2Request = scopedManager.run(identity(20), (signal) => { page2Signal = signal; return page2.promise; });
const page1Request = scopedManager.run(identity(0), () => page1.promise);
assert.equal(page2Signal.aborted, true);
page1.resolve({ items: ["latest"] });
assert.deepEqual(await page1Request, { applied: true, value: { items: ["latest"] } });
page2.reject(new Error("stale page failed"));
assert.deepEqual(await page2Request, { applied: false });

const independentManager = new ScopedStaticListRequestManager();
const scopeA = deferred();
const scopeB = deferred();
let scopeASignal;
const requestA = independentManager.run(identity(0), (signal) => { scopeASignal = signal; return scopeA.promise; });
const requestB = independentManager.run({ ...identity(0), parentKey: "topic-2" }, () => scopeB.promise);
assert.equal(scopeASignal.aborted, false);
scopeA.resolve("A");
scopeB.resolve("B");
assert.deepEqual(await requestA, { applied: true, value: "A" });
assert.deepEqual(await requestB, { applied: true, value: "B" });

const cleanupManager = new ScopedStaticListRequestManager();
const cleanupRequest = deferred();
let cleanupSignal;
const pendingCleanup = cleanupManager.run(identity(0), (signal) => { cleanupSignal = signal; return cleanupRequest.promise; });
cleanupManager.abortAll();
assert.equal(cleanupSignal.aborted, true);
cleanupRequest.reject(new Error("aborted during cleanup"));
assert.deepEqual(await pendingCleanup, { applied: false });

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");
const visibility = read("../src/pages/reports/components/StaticVisibilitySection.tsx");
const visibilityDashboard = read("../src/components/insights/VisibilityDashboard.tsx");
const citation = read("../src/pages/reports/components/StaticCitationSection.tsx");
const sentiment = read("../src/pages/reports/components/StaticSentimentSection.tsx");
const promptTopic = read("../src/pages/reports/components/StaticPromptTopicSection.tsx");
const snapshotTable = read("../src/pages/reports/components/SnapshotTable.tsx");
const page = read("../src/pages/reports/StaticReportPage.tsx");
const api = read("../src/lib/api/staticReports.ts");

for (const [source, listId] of [
  [visibility, "static-visibility-ranking"],
  [citation, "static-citation-domains"],
  [citation, "static-citation-pages"],
  [citation, "static-citation-categories"],
  [sentiment, "static-sentiment-themes"],
  [promptTopic, "static-prompt-ranking"],
  [promptTopic, "static-topic-ranking"],
  [promptTopic, "static-product-ranking"],
]) {
  assert.match(source, new RegExp(`(?:data-sort-list|sortListId)=["']${listId}["']`));
}
for (const source of [visibilityDashboard, citation, sentiment, snapshotTable]) assert.match(source, /SortableMetricHeader/);
for (const listType of [
  "visibility.${effectiveGroupBy}",
  "visibility.${effectiveGroupBy}_brand",
  "visibility.${effectiveGroupBy}_prompt",
  "visibility.${effectiveGroupBy}_prompt_brand",
]) assert.ok(visibilityDashboard.includes(listType));
assert.doesNotMatch(visibility, /compact=\{sortingAvailable\}/);
assert.doesNotMatch(visibility, /detail\.pagination\.(?:previous|next)/);
assert.doesNotMatch(visibility, /offsets/);
assert.equal((visibility.match(/limit: 100/g) || []).length, 3);

assert.match(api, /getStaticReportFrozenList/);
assert.match(api, /sort_by/);
assert.match(api, /sort_order/);
assert.doesNotMatch(page, /StaticPromptTopicSection/);
assert.doesNotMatch(page, /getStaticReportPromptTopic/);
assert.match(page, /sortingAvailable/);
assert.match(page, /exportMode/);
assert.doesNotMatch(page, /downloadHtml[\s\S]*getStaticReportFrozenList/);

console.log("static report frozen list sort tests passed");
