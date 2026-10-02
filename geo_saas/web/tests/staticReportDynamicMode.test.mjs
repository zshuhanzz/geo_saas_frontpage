import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");
const page = read("../src/pages/reports/StaticReportPage.tsx");
const visibility = read("../src/pages/insights/Visibility.tsx");
const dynamicPath = new URL("../src/pages/reports/components/DynamicDateRangeReport.tsx", import.meta.url);

assert.equal(existsSync(dynamicPath), true, "dynamic report renderer exists");
const dynamicReport = read("../src/pages/reports/components/DynamicDateRangeReport.tsx");

assert.match(page, /summary\.snapshot_version === ["']dynamic-report-v1["']/, "report page selects dynamic mode from the authorized summary");
assert.match(page, /<DynamicDateRangeReport[\s\S]{0,200}summary=\{summary\}/, "dynamic reports render the dynamic dashboard composition");
assert.match(page, /if \(!reportId \|\| !summary \|\| isDynamicReport\) return;/, "filter loading waits for summary and dynamic reports never load legacy snapshot filters");
assert.match(page, /if \(!reportId \|\| !summary \|\| isDynamicReport\) return;/, "dynamic reports never load legacy snapshot sections");

assert.match(dynamicReport, /const reportClientId = summary\.client_id/, "dynamic API tenant comes from the authorized report summary");
assert.doesNotMatch(dynamicReport, /useSaaS/, "dynamic reports do not depend on the current workspace selector");
assert.match(dynamicReport, /dateFrom:\s*summary\.report\.window_start/, "dynamic report fixes the API start date to the saved report window");
assert.match(dynamicReport, /dateTo:\s*summary\.report\.window_end/, "dynamic report fixes the API end date to the saved report window");
assert.match(dynamicReport, /<InsightsFilterContext\.Provider value=\{filterContext\}>/, "existing Visibility consumes a fixed report filter context");
assert.match(dynamicReport, /<Visibility clientIdOverride=\{reportClientId\}/, "Visibility receives the report tenant explicitly");
assert.match(dynamicReport, /<CitationDashboard[\s\S]{0,240}clientId=\{reportClientId\}/, "Citation reuses the dynamic dashboard with the report tenant");
assert.match(dynamicReport, /<SentimentDashboard[\s\S]{0,240}clientId=\{reportClientId\}/, "Sentiment reuses the dynamic dashboard with the report tenant");
assert.match(dynamicReport, /selectedTopics/, "Topic selection remains interactive");
assert.match(dynamicReport, /selectedPlatforms/, "Platform selection remains interactive");

assert.match(visibility, /clientIdOverride\?: string/, "Visibility accepts a report-scoped tenant override");
assert.match(visibility, /const clientId = clientIdOverride \?\? workspaceClientId/, "Visibility prefers the report tenant over the selected workspace");

assert.match(page, /<StaticVisibilitySection/, "legacy snapshot Visibility remains available");
assert.match(page, /<StaticCitationSection/, "legacy snapshot Citation remains available");
assert.match(page, /<StaticSentimentSection/, "legacy snapshot Sentiment remains available");

console.log("static report dynamic mode tests passed");
