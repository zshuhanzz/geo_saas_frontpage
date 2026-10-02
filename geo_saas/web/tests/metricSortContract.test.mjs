import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");
const visibility = read("../src/components/insights/VisibilityDashboard.tsx");
const citation = read("../src/components/insights/CitationDashboard.tsx");
const sentiment = read("../src/components/insights/SentimentDashboard.tsx");
const prompts = read("../src/pages/insights/Prompts.tsx");
const visibilityPage = read("../src/pages/insights/Visibility.tsx");
const drilldown = read("../src/pages/insights/PromptDrilldown.tsx");
const staticCitation = read("../src/pages/reports/components/StaticCitationSection.tsx");
const staticVisibility = read("../src/pages/reports/components/StaticVisibilitySection.tsx");
const staticSentiment = read("../src/pages/reports/components/StaticSentimentSection.tsx");
const staticPromptTopic = read("../src/pages/reports/components/StaticPromptTopicSection.tsx");
const snapshotTable = read("../src/pages/reports/components/SnapshotTable.tsx");
const header = read("../src/components/ui/SortableMetricHeader.tsx");

for (const [source, listId] of [
  [visibility, "visibility-ranking"],
  [visibility, "visibility-time-series"],
  [citation, "citation-domain-ranking"],
  [citation, "citation-category-breakdown"],
  [citation, "citation-domains"],
  [citation, "citation-pages"],
  [citation, "published-url-tracking"],
  [citation, "published-url-detail-topics"],
  [citation, "published-url-detail-platforms"],
  [citation, "published-url-detail-countries"],
  [citation, "published-url-detail-prompts"],
  [sentiment, "sentiment-themes"],
  [prompts, "prompt-groups"],
  [prompts, "prompt-rows"],
]) {
  assert.match(source, new RegExp(`data-sort-list=["']${listId}["']`), `${listId} declares its metric sort surface`);
}

assert.match(visibilityPage, /getVisibilityBrandRanking\(clientId, withMetricSortParams\(requestParams, rankingSorts\.visibility\)/);
assert.match(visibilityPage, /getVisibilitySovRanking\(clientId, withMetricSortParams\(requestParams, rankingSorts\.sov\)/);
assert.match(visibilityPage, /getVisibilityPositionRanking\(clientId, withMetricSortParams\(requestParams, rankingSorts\.position\)/);
assert.match(visibilityPage, /productRankingSorts\.visibility/);
assert.match(visibilityPage, /productRankingSorts\.sov/);
assert.match(visibilityPage, /productRankingSorts\.position/);
assert.match(visibilityPage, /topicRankingSorts\.visibility/);
assert.match(visibilityPage, /topicRankingSorts\.sov/);
assert.match(visibilityPage, /if \(effectiveDim === "brand"\)/, "Brand and standalone state updates are dimension-scoped");
assert.match(visibilityPage, /rankingSorts=\{dashboardRankingSorts\}/, "standalone controls receive standalone rather than Brand state");
assert.match(visibility, /sortVisibilityTimeSeries\(timeSeries, timeSeriesComplete, timeSeriesSort\)/);
assert.match(drilldown, /getVisibilityComposed\(clientId, resolvedVisibilityParams, \{ signal: controller\.signal \}\)/);
assert.doesNotMatch(drilldown, /getVisibilityComposed\([^\n]+visibilitySorts/, "drilldown sorts do not refetch the composed dashboard");
assert.match(drilldown, /getVisibilityBrandRanking\(clientId, withMetricSortParams/);
assert.match(sentiment, /getSentimentThemes\(clientId, withMetricSortParams/, "Sentiment sorting refreshes only the theme list");
assert.doesNotMatch(sentiment, /getSentiment\(clientId, withMetricSortParams/, "Sentiment sorting never refetches KPI and trend data");
assert.match(prompts, /isCompleteMetricCollection\(metricOrder, metricTotal\)/, "Prompt sorting requires an exact complete-set proof");
assert.match(prompts, /disabled=\{!promptMetricsComplete\}/, "Prompt metric headers fail safely when completeness is not proven");
assert.match(prompts, /ordered_prompt_ids/, "Prompt sorting consumes the server ordering contract");
assert.doesNotMatch(prompts, /\[clientId, dateFrom, dateTo, promptSort, importRefreshKey\]/, "Prompt row sorting does not refetch the complete Prompt collection");
assert.doesNotMatch(prompts, /getPromptMetrics\(requestClientId, withMetricSortParams/, "Prompt row sorting reuses the complete cached metric collection");
assert.match(visibilityPage, /sortStandaloneVisibilityResponse/, "Product and Topic sorts operate on their complete cached ranking rows");
assert.doesNotMatch(visibilityPage, /getProductVisibility\(clientId, withMetricSortParams/, "Product ranking sorts do not refetch shared chart data");
assert.doesNotMatch(visibilityPage, /getTopicVisibility\(clientId, withMetricSortParams/, "Topic ranking sorts do not refetch shared chart data");
assert.match(staticVisibility, /timeSeriesComplete=\{enabled\}/, "interactive static Visibility enables frozen time-series metric sorting");
assert.match(staticSentiment, /themeResult\.loading && displayedThemes\.length > 0/, "static Sentiment renders a list-local loading overlay");

const rankingMatrix = visibility.slice(
  visibility.indexOf("function TopicRankingMatrix"),
  visibility.indexOf("function EmptyState"),
);
assert.doesNotMatch(rankingMatrix, /SortableMetricHeader/, "Visibility Ranking is a rank matrix, not a metric-sort table");
assert.doesNotMatch(rankingMatrix, /data-sort-list=["']visibility-matrix["']/, "Visibility Ranking exposes no sorting surface");
assert.match(rankingMatrix, /Array\.from\(\{ length: 10 \}/, "Visibility Ranking renders the canonical 1-10 brand columns");
assert.match(rankingMatrix, /`#\$\{index \+ 1\}`/, "Visibility Ranking labels canonical columns as #1-#10");
assert.match(visibility, /function BrandRankCellContent/, "Visibility Ranking uses the shared brand identity cell");
assert.equal((rankingMatrix.match(/<BrandRankCellContent brand=\{brand\} \/>/g) || []).length, 2, "group and Prompt rows both render brand logos and names");

assert.doesNotMatch(prompts, /getPrompts\([\s\S]{0,300}return \[\]/, "Prompt inventory failures are never disguised as successful empty data");
assert.doesNotMatch(prompts, /Promise\.all\(\[\s*getPrompts/, "Prompt inventory renders independently from slow metrics");
assert.match(prompts, /if \(!clientId \|\| loadedInventoryKey !== inventoryKey\)/, "Prompt metrics wait until the latest compact inventory revision has released its database connection");
assert.match(citation, /summaryQueriesSettled/, "Citation heavy lists wait for summary queries to release connections");
assert.match(citation, /domainSettledBaseKey !== baseQueryKey/, "cited pages wait for the initial domain query to release its connection");
assert.doesNotMatch(citation, /\[clientId, filtersReady, domainQueryKey, domainSettled/, "Domain-local sorting never restarts the Pages list");
assert.match(citation, /primarySummaryQueriesSettled/, "Citation categories wait for Share and Ranking to cap initial concurrency");
assert.match(citation, /rankingSettledBaseKey === baseQueryKey/, "Ranking-local sorts never close downstream stage gates");
assert.match(citation, /categorySettledBaseKey === baseQueryKey/, "Category-local sorts never close downstream stage gates");
assert.match(citation, /loadReady=\{pageSettledBaseKey === baseQueryKey\}/, "Published URL tracking starts after the heavy Citation lists");

const publishedDetailEffect = citation.slice(
  citation.indexOf("const baseKey = JSON.stringify({", citation.indexOf("function PublishedUrlTrackingSection")),
  citation.indexOf("const start = total > 0", citation.indexOf("function PublishedUrlTrackingSection")),
);
const publishedDetailBaseKey = publishedDetailEffect.slice(0, publishedDetailEffect.indexOf("});") + 3);
assert.doesNotMatch(publishedDetailBaseKey, /detail(?:Prompt|Topic|Platform|Country)Sort/, "detail metric sorts are not part of the whole-drawer identity");
for (const scope of ["Topic", "Platform", "Country", "Prompt"]) {
  assert.match(citation, new RegExp(`set${scope}DetailLoading\\(true\\)`), `${scope} detail sorting has a list-local loading state`);
}
assert.match(citation, /setDetail\(\(current\) =>/, "detail refreshes merge into the existing drawer instead of replacing it wholesale");

assert.match(staticCitation, /const rankingCardRows = fallbackDomainRanking/, "static ranking side card remains pinned to snapshot ranking rows");
const staticCategorySection = staticCitation.slice(
  staticCitation.indexOf("data-sort-list=\"static-citation-categories\""),
  staticCitation.indexOf("<StaticCitationTable", staticCitation.indexOf("data-sort-list=\"static-citation-categories\"")),
);
assert.match(staticCategorySection, /categoryResult\.loading/, "static category sorting shows a category-local loading state");
assert.match(staticCategorySection, /commonT\("states\.loading"\)/, "static category loading copy comes from i18n");
assert.doesNotMatch(staticCitation, />\s*Loading\.\.\.\s*</, "static Citation loading copy comes from i18n");

for (const [source, label] of [
  [citation, "dynamic Citation"],
  [staticCitation, "static Citation"],
  [staticVisibility, "static Visibility"],
  [staticSentiment, "static Sentiment"],
  [staticPromptTopic, "static Prompt Topic Product"],
  [snapshotTable, "generic static Snapshot table"],
]) {
  assert.doesNotMatch(source, /metricKey=["']rank["']/, `${label} sequence columns are never sortable`);
}
for (const [source, label] of [
  [visibility, "dynamic Visibility"],
  [citation, "dynamic Citation"],
  [sentiment, "dynamic Sentiment"],
  [prompts, "dynamic Prompt"],
  [staticCitation, "static Citation"],
]) {
  assert.doesNotMatch(
    source,
    /(?:metricKey|key)=[{]?["'](?:rank|id|index|order|sequence|row_number)["']|\{\s*key:\s*["'](?:rank|id|index|order|sequence|row_number)["']/,
    `${label} never exposes a sequence or identifier field as a sortable metric`,
  );
}
assert.doesNotMatch(citation, /getCitedDomainsCount|getCitedPagesCount/, "Citation lists use totals returned by their list APIs");

assert.match(citation, /<TableHead>\{t\("citations\.sectionDomains\.columnDomain"\)\}<\/TableHead>/, "Domain remains a plain dimension header");
assert.match(citation, /<TableHead>\{t\("citations\.sectionPages\.columnPageUrl"\)\}<\/TableHead>/, "Page URL remains a plain dimension header");
assert.match(prompts, /<TableHead>\{t\("prompts\.tableColumns\.product"\)\}<\/TableHead>/, "Product remains a plain dimension header");
assert.doesNotMatch(header, /activeDirection === "asc"\s*\?\s*t\("metricSort\.activateDescending"/, "the accessible action is based on the actual next direction");
assert.match(header, /const next = nextMetricSort/);
assert.match(header, /metricSortCurrentStateKey\(activeDirection\)/, "screen readers receive the current sort direction");

console.log("metricSort contract tests passed");
