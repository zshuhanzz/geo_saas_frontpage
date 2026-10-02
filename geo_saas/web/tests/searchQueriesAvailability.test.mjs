import assert from "node:assert/strict";
import fs from "node:fs";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const webRoot = path.resolve(here, "..");

test("ResultDetailDrawer renders explicit ChatGPT search-query availability states", () => {
  const component = fs.readFileSync(
    path.join(webRoot, "src/components/insights/SentimentDashboard.tsx"),
    "utf8",
  );
  const zh = JSON.parse(
    fs.readFileSync(path.join(webRoot, "src/i18n/locales/zh-CN/insights.json"), "utf8"),
  );
  const en = JSON.parse(
    fs.readFileSync(path.join(webRoot, "src/i18n/locales/en-US/insights.json"), "utf8"),
  );

  assert.match(component, /searchQueriesStatus === "upstream_not_provided"/);
  assert.match(component, /searchQueriesStatus === "not_requested"/);
  assert.match(component, /searchQueriesUpstreamUnavailable/);
  assert.match(component, /searchQueriesNotRequested/);
  assert.equal(
    zh.sentiment.searchQueriesUpstreamUnavailable,
    "本次 ChatGPT 返回格式未提供内部搜索查询。",
  );
  assert.equal(
    zh.sentiment.searchQueriesNotRequested,
    "本次采集未请求 Search Queries。",
  );
  assert.ok(en.sentiment.searchQueriesUpstreamUnavailable);
  assert.ok(en.sentiment.searchQueriesNotRequested);
});
