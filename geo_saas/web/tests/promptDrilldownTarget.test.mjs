import assert from "node:assert/strict";
import {
  buildProductDrilldownHref,
  buildPromptDrilldownHref,
  buildTopicDrilldownHref,
  parsePromptDrilldownLocation,
  resolvePromptDrilldownFilters,
  selectDashboardFilterKey,
} from "../src/pages/insights/promptDrilldownTarget.ts";

const common = {
  dateFrom: "2026-07-01",
  dateTo: "2026-07-07",
  interval: "day",
  topicIds: ["topic-a", "topic-b"],
  platforms: ["chatgpt", "gemini"],
  countries: ["US", "DE"],
  promptTypes: ["question"],
};

{
  const href = buildTopicDrilldownHref("topic-a");
  assert.equal(href, "/insights/prompts/topic/topic-a");
  assert.deepEqual(parsePromptDrilldownLocation("/insights/prompts/topic/topic-a", ""), {
    kind: "topic",
    topicId: "topic-a",
  });
  const filters = resolvePromptDrilldownFilters(common, { kind: "topic", topicId: "topic-a" });
  assert.deepEqual(filters, { ...common, topicIds: ["topic-a"] });
  assert.notEqual(filters, common, "filter resolution returns an immutable snapshot");
  const replaced = resolvePromptDrilldownFilters(
    { ...common, topicIds: ["topic-b"] },
    { kind: "topic", topicId: "topic-a" },
  );
  assert.deepEqual(replaced.topicIds, ["topic-a"], "a Topic target replaces, rather than intersects, the global Topic filter");
}

{
  const href = buildProductDrilldownHref("topic-a", "  S8 MaxV / Ultra  ");
  assert.equal(href, "/insights/prompts/product?topic_id=topic-a&product=S8+MaxV+%2F+Ultra");
  const parsed = parsePromptDrilldownLocation(...href.split("?"));
  assert.deepEqual(parsed, { kind: "product", topicId: "topic-a", product: "S8 MaxV / Ultra" });
  assert.equal(buildProductDrilldownHref("topic-a", "   "), null, "blank products have no drilldown route");

  const intersected = resolvePromptDrilldownFilters(common, parsed);
  assert.deepEqual(intersected, { ...common, topicIds: ["topic-a"], products: ["S8 MaxV / Ultra"] });
  const empty = resolvePromptDrilldownFilters({ ...common, topicIds: ["topic-b"] }, parsed);
  assert.equal(empty.emptyIntersection, true, "a product target never broadens an incompatible global topic filter");
}

{
  const href = buildPromptDrilldownHref("prompt-representative");
  assert.equal(href, "/insights/prompts/prompt/prompt-representative");
  assert.deepEqual(parsePromptDrilldownLocation(href, ""), {
    kind: "prompt",
    promptId: "prompt-representative",
  });

  const concept = {
    topic_id: "topic-a",
    product: "S8 MaxV",
    prompt_ids: ["prompt-representative", "prompt-variant"],
  };
  const filters = resolvePromptDrilldownFilters(common, { kind: "prompt", promptId: "prompt-representative" }, concept);
  assert.deepEqual(filters, {
    ...common,
    topicIds: ["topic-a"],
    products: ["S8 MaxV"],
    promptIds: ["prompt-representative", "prompt-variant"],
  });
  const empty = resolvePromptDrilldownFilters(
    { ...common, topicIds: ["topic-b"] },
    { kind: "prompt", promptId: "prompt-representative" },
    concept,
  );
  assert.equal(empty.emptyIntersection, true);
  assert.ok(!href.includes("prompt-variant"), "Prompt URLs contain only the representative id");
}

{
  assert.equal(
    selectDashboardFilterKey("drilldown", "raw-target-b", "debounced-target-a"),
    "raw-target-b",
    "drilldown domains switch to the same raw immutable snapshot immediately",
  );
  assert.equal(
    selectDashboardFilterKey("sidebar", "raw-target-b", "debounced-target-a"),
    "debounced-target-a",
    "sidebar dashboards preserve their existing debounce",
  );
  assert.equal(
    selectDashboardFilterKey("sidebar", "raw-client-b", "debounced-client-a", true),
    "raw-client-b",
    "tenant ownership changes are never delayed by sidebar debounce",
  );
}

{
  assert.equal(
    parsePromptDrilldownLocation("/insights/prompts/country/US", ""),
    null,
    "country is not a complete drilldown target",
  );
  assert.equal(parsePromptDrilldownLocation("/insights/prompts/product", "?topic_id=topic-a&product=%20%20"), null);
  assert.equal(parsePromptDrilldownLocation("/insights/prompts/prompt/", ""), null);
}

console.log("promptDrilldownTarget tests passed");
