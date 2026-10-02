import assert from "node:assert/strict";
import { applyStaticReportFilters } from "../src/pages/reports/components/staticReportFilters.ts";

const snapshot = {
  version: "test",
  client: { id: "client-1", name: "Dreamina" },
  report: {
    date: "2026-06-19",
    timezone: "Asia/Shanghai",
    window_start: "2026-06-19",
    window_end: "2026-06-19",
    window_days: 1,
    rendering_mode: "single_day",
  },
  data_completeness: {},
  visibility: {
    dashboard: {
      summary: {},
      source_rows: [
        {
          topic_id: "ai-video",
          topic_name: "AI Video",
          date: "2026-06-19",
          prompt_id: "prompt-1",
          platform: "chatgpt",
          company_name: "Dreamina",
          mention_count: 158,
          response_count: 158,
          avg_position: 8,
          is_own: true,
        },
        {
          topic_id: "ai-video",
          topic_name: "AI Video",
          date: "2026-06-19",
          prompt_id: "prompt-1",
          platform: "chatgpt",
          company_name: "Other Brand",
          mention_count: 4208,
          response_count: 900,
          avg_position: 2,
          is_own: false,
        },
      ],
      response_source_rows: [
        {
          topic_id: "ai-video",
          topic_name: "AI Video",
          date: "2026-06-19",
          prompt_id: "prompt-1",
          platform: "chatgpt",
          total_response_count: 1770,
          own_response_count: 158,
        },
      ],
      sov_ranking: [],
      visibility_ranking: [],
      position_ranking: [],
      topic_sov_ranking: [],
      product_sov_ranking: [],
    },
  },
  citations: {},
  sentiment: {},
  prompts: {},
  topics: {},
};

const filtered = applyStaticReportFilters(snapshot, { topicIds: ["ai-video"], platforms: [] });
const dashboard = filtered.visibility.dashboard;

assert.equal(dashboard.summary.visibility_score, 8.93);
assert.equal(dashboard.summary.mentioned, 158);
assert.equal(dashboard.summary.total_query, 1770);
assert.equal(dashboard.summary.total_mentions, 4366);
assert.equal(dashboard.summary.sov_pct, 3.62);
assert.equal(dashboard.summary.visibility_rank, 2);

const legacySnapshot = structuredClone(snapshot);
legacySnapshot.visibility.dashboard.response_source_rows = [];
delete legacySnapshot.visibility.dashboard.source_rows[0].total_response_count;
delete legacySnapshot.visibility.dashboard.source_rows[0].brand_response_count;
delete legacySnapshot.visibility.dashboard.source_rows[1].total_response_count;
delete legacySnapshot.visibility.dashboard.source_rows[1].brand_response_count;

const legacyFiltered = applyStaticReportFilters(legacySnapshot, { topicIds: ["ai-video"], platforms: [] });
const legacyDashboard = legacyFiltered.visibility.dashboard;

assert.equal(legacyDashboard.summary.visibility_score, 0);
assert.equal(legacyDashboard.summary.total_query, 0);
assert.equal(legacyDashboard.summary.sov_pct, 3.62);
assert.equal(legacyDashboard.summary.total_mentions, 4366);

console.log("staticReportFilters tests passed");

const sentimentSnapshot = structuredClone(snapshot);
sentimentSnapshot.sentiment = {
  dashboard: {
    summary: {},
    time_series: [],
    themes: [],
    examples: [],
    source_rows: [
      { topic_id: "ai-video", platform: "chatgpt", date: "2026-06-19", theme_name: "Ease of Use", sentiment: "Positive", occurrence_count: 5 },
      { topic_id: "ai-video", platform: "chatgpt", date: "2026-06-19", theme_name: "Reliability", sentiment: "Negative", occurrence_count: 1 },
    ],
    response_source_rows: [
      { topic_id: "ai-video", platform: "chatgpt", date: "2026-06-19", sentiment: "Positive", count: 2 },
      { topic_id: "ai-video", platform: "chatgpt", date: "2026-06-19", sentiment: "Mixed/Neutral", count: 1 },
      { topic_id: "ai-video", platform: "chatgpt", date: "2026-06-19", sentiment: "Negative", count: 1 },
      { topic_id: "ai-video", platform: "chatgpt", date: "2026-06-19", sentiment: "Insufficient Evidence", count: 2 },
      { topic_id: "other", platform: "chatgpt", date: "2026-06-19", sentiment: "Positive", count: 10 },
    ],
  },
};

const sentimentFiltered = applyStaticReportFilters(sentimentSnapshot, {
  topicIds: ["ai-video"],
  platforms: ["chatgpt"],
});
const sentimentSummary = sentimentFiltered.sentiment.dashboard.summary;

assert.equal(sentimentSummary.positive_count, 2);
assert.equal(sentimentSummary.mixed_neutral_count, 1);
assert.equal(sentimentSummary.negative_count, 1);
assert.equal(sentimentSummary.insufficient_evidence_count, 2);
assert.equal(sentimentSummary.rated_count, 4);
assert.equal(sentimentSummary.total_count, 6);
assert.equal(sentimentSummary.positive_pct, 50);
assert.equal(sentimentSummary.mixed_neutral_pct, 25);
assert.equal(sentimentSummary.negative_pct, 25);
