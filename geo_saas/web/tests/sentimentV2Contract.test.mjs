import assert from "node:assert/strict";
import fs from "node:fs";

const dashboard = fs.readFileSync(
  new URL("../src/components/insights/SentimentDashboard.tsx", import.meta.url),
  "utf8",
);
const staticSection = fs.readFileSync(
  new URL("../src/pages/reports/components/StaticSentimentSection.tsx", import.meta.url),
  "utf8",
);
const openapi = fs.readFileSync(new URL("../src/api/openapi.d.ts", import.meta.url), "utf8");
const insightsEn = JSON.parse(fs.readFileSync(new URL("../src/i18n/locales/en-US/insights.json", import.meta.url), "utf8"));
const insightsZh = JSON.parse(fs.readFileSync(new URL("../src/i18n/locales/zh-CN/insights.json", import.meta.url), "utf8"));

for (const source of [dashboard, staticSection]) {
  assert.match(source, /mixed_neutral_count/);
  assert.match(source, /insufficient_evidence_count/);
  assert.match(source, /mixed_neutral_pct/);
  assert.match(source, /negative_pct/);
  assert.doesNotMatch(source, /100\s*-\s*(?:Number\()?summary\.positive_pct/);
}

assert.doesNotMatch(dashboard, /entry\.positive_pct\s*>=\s*50/);

for (const locale of [insightsEn, insightsZh]) {
  assert.ok(locale.sentiment.filterMixedNeutral);
  assert.ok(locale.sentiment.insufficientEvidence);
  assert.ok(locale.sentiment.ratedResponses);
}

for (const field of [
  "mixed_neutral_pct",
  "negative_pct",
  "mixed_neutral_count",
  "insufficient_evidence_count",
  "rated_count",
]) {
  assert.match(openapi, new RegExp(`\\b${field}:`));
}

console.log("sentiment V2 UI contract tests passed");
