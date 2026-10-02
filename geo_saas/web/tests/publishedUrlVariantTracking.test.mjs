import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const dashboard = readFileSync(
  new URL("../src/components/insights/CitationDashboard.tsx", import.meta.url),
  "utf8",
);
const api = readFileSync(new URL("../src/lib/api/insights.ts", import.meta.url), "utf8");
const zh = JSON.parse(readFileSync(new URL("../src/i18n/locales/zh-CN/insights.json", import.meta.url), "utf8"));
const en = JSON.parse(readFileSync(new URL("../src/i18n/locales/en-US/insights.json", import.meta.url), "utf8"));

assert.match(api, /export async function getPublishedUrlTrackingVariants\(/);
assert.match(api, /export async function setPublishedUrlCitationMatch\(/);
assert.match(dashboard, /row\.candidate_count/);
assert.match(
  dashboard,
  /variant="outline"[\s\S]*className=\{row\.candidate_count > 0[\s\S]*border-emerald-[\s\S]*publishedTracking\.variants\.pendingCount/,
  "the URL variants action must be outlined and pending-review candidates must be emphasized in green",
);
assert.match(dashboard, /getPublishedUrlTrackingVariants/);
assert.match(dashboard, /setPublishedUrlCitationMatch/);
assert.match(dashboard, /publishedTracking\.variants\.confirm/);
assert.match(dashboard, /publishedTracking\.variants\.reject/);
assert.equal(zh.publishedTracking.variants.pending, "待确认");
assert.equal(en.publishedTracking.variants.pending, "Pending review");

console.log("published URL variant tracking contract tests passed");
