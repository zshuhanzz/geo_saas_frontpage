import assert from "node:assert/strict";
import { buildCitationQueryKeys } from "../src/components/insights/citationSortState.ts";

const initial = buildCitationQueryKeys({
  baseKey: "filters-a",
  rankingSort: { metricKey: "citation_count", direction: "desc" },
  categorySort: { metricKey: "count", direction: "desc" },
  domainSearch: "",
  domainPage: 0,
  domainSort: { metricKey: "citation_count", direction: "desc" },
  pageSearch: "",
  pagePage: 0,
  pageSort: { metricKey: "citation_count", direction: "desc" },
});
const domainResorted = buildCitationQueryKeys({
  baseKey: "filters-a",
  rankingSort: { metricKey: "citation_count", direction: "desc" },
  categorySort: { metricKey: "count", direction: "desc" },
  domainSearch: "",
  domainPage: 0,
  domainSort: { metricKey: "citation_count", direction: "asc" },
  pageSearch: "",
  pagePage: 0,
  pageSort: { metricKey: "citation_count", direction: "desc" },
});

assert.notEqual(initial.domainQueryKey, domainResorted.domainQueryKey);
assert.equal("domainCountQueryKey" in initial, false, "the list response owns the exact domain total");
assert.equal("pageCountQueryKey" in initial, false, "the list response owns the exact page total");
assert.equal(initial.pageQueryKey, domainResorted.pageQueryKey);
assert.equal(initial.shareQueryKey, domainResorted.shareQueryKey);
assert.equal(initial.rankingQueryKey, domainResorted.rankingQueryKey);
assert.equal(initial.categoryQueryKey, domainResorted.categoryQueryKey);

console.log("citationSortState tests passed");
