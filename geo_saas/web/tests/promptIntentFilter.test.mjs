import assert from "node:assert/strict";
import {
  applyPromptListFilters,
  areSelectedCandidateIntentsActive,
  buildLogicalPromptKey,
  canRemoveLogicalPromptDimensionVariants,
  buildIntentOptionGroups,
  getIntentWriteValidation,
  isWorkspaceStateOwned,
  matchesIntentFilter,
  resolveCanonicalIntent,
  selectPromptConceptVariants,
  toggleIntentOption,
} from "../src/pages/insights/promptIntentFilter.ts";

const rows = [
  { id: "1", is_active: true, topic_id: "topic-a", product: "Alpha", platform: "chatgpt", country: "US", text: "Alpha one", intent: "Discovery" },
  { id: "2", is_active: true, topic_id: "topic-a", product: "Beta", platform: "gemini", country: "DE", text: "Beta two", intent: "Evaluation" },
  { id: "3", is_active: true, topic_id: "topic-b", product: "Alpha", platform: "chatgpt", country: "US", text: "Alpha three", intent: "Historical" },
  { id: "4", is_active: true, topic_id: "topic-a", product: "Alpha", platform: "chatgpt", country: "US", text: "Blank null", intent: null },
  { id: "5", is_active: true, topic_id: "topic-a", product: "Alpha", platform: "chatgpt", country: "US", text: "Blank spaces", intent: "   " },
  { id: "6", is_active: false, topic_id: "topic-a", product: "Alpha", platform: "chatgpt", country: "US", text: "Inactive", intent: "Discovery" },
];

const logicalRows = [
  {
    id: "logical-1",
    prompt_ids: ["physical-1", "physical-2"],
    is_active: true,
    topic_id: "topic-a",
    product: "Alpha",
    platforms: ["chatgpt", "gemini"],
    countries: ["DE", "US"],
    variants: [
      { id: "physical-1", platform: "chatgpt", country: "US" },
      { id: "physical-2", platform: "gemini", country: "DE" },
    ],
    text: "Logical Prompt",
    intent: "Discovery",
  },
];

{
  assert.equal(applyPromptListFilters(logicalRows, {
    activeOnly: true,
    platform: "gemini",
    country: "US",
    intent: { values: [], includeBlank: false },
  }).length, 1, "logical Prompt arrays participate in single-value dimension filters");
  assert.equal(applyPromptListFilters(logicalRows, {
    activeOnly: true,
    platforms: ["perplexity", "gemini"],
    intent: { values: [], includeBlank: false },
  }).length, 1, "logical Prompt arrays use intersection semantics for global platform filters");
  assert.equal(applyPromptListFilters(logicalRows, {
    activeOnly: true,
    platform: "perplexity",
    intent: { values: [], includeBlank: false },
  }).length, 0);
}

{
  const filtered = applyPromptListFilters(rows, {
    activeOnly: true,
    intent: { values: ["Discovery", "Evaluation"], includeBlank: false },
  });
  assert.deepEqual(filtered.map((row) => row.id), ["1", "2"], "selected Intent values use OR semantics");
}

{
  const filtered = applyPromptListFilters(rows, {
    activeOnly: true,
    topicId: "topic-a",
    topicIds: ["topic-a"],
    product: "Alpha",
    platform: "chatgpt",
    platforms: ["chatgpt"],
    country: "US",
    searchQuery: "alpha",
    intent: { values: ["Discovery", "Evaluation"], includeBlank: false },
  });
  assert.deepEqual(filtered.map((row) => row.id), ["1"], "Intent OR is ANDed with every existing dimension filter");
}

{
  const filtered = applyPromptListFilters(rows, {
    activeOnly: true,
    intent: { values: [], includeBlank: false },
  });
  assert.deepEqual(filtered.map((row) => row.id), ["1", "2", "3", "4", "5"], "clearing Intent selection removes the Intent restriction");
}

{
  const groups = buildIntentOptionGroups({
    active: ["Discovery", "Evaluation"],
    unconfigured: ["Historical", "blank:internal-key"],
    has_unconfigured_blank: true,
  });
  assert.deepEqual(groups.active, [
    { kind: "value", value: "Discovery" },
    { kind: "value", value: "Evaluation" },
  ]);
  assert.deepEqual(groups.unconfigured, [
    { kind: "value", value: "Historical" },
    { kind: "value", value: "blank:internal-key" },
    { kind: "blank" },
  ]);

  const literalSelected = toggleIntentOption(
    { values: [], includeBlank: false },
    groups.unconfigured[1],
  );
  const withBlankSelected = toggleIntentOption(literalSelected, groups.unconfigured[2]);
  assert.deepEqual(withBlankSelected, {
    values: ["blank:internal-key"],
    includeBlank: true,
  }, "a literal value that resembles an internal key cannot collide with blank selection");
}

{
  const filtered = applyPromptListFilters(rows, {
    activeOnly: true,
    intent: { values: [], includeBlank: true },
  });
  assert.deepEqual(filtered.map((row) => row.id), ["4", "5"], "blank history is matched only through includeBlank");
}

{
  assert.equal(getIntentWriteValidation("", ["Discovery"]), "missing");
  assert.equal(getIntentWriteValidation("Historical", ["Discovery"]), "inactive");
  assert.equal(getIntentWriteValidation("Discovery", ["Discovery"]), null);
  assert.equal(getIntentWriteValidation("general", []), "inactive", "validation never manufactures or accepts a fallback write value");
}

{
  assert.equal(isWorkspaceStateOwned("client-a", "client-a"), true);
  assert.equal(isWorkspaceStateOwned("client-a", "client-b"), false);
  assert.equal(isWorkspaceStateOwned("client-a", null), false);
  assert.equal(isWorkspaceStateOwned("", ""), false, "an empty owner never authorizes a mutation");
}

{
  const candidates = [
    { selected: true, intent: "Discovery" },
    { selected: false, intent: "Historical" },
  ];
  assert.equal(areSelectedCandidateIntentsActive(candidates, ["Discovery"]), true);
  assert.equal(
    areSelectedCandidateIntentsActive([...candidates, { selected: true, intent: "Historical" }], ["Discovery"]),
    false,
  );
  assert.equal(
    areSelectedCandidateIntentsActive([...candidates, { selected: true, intent: "   " }], ["Discovery"]),
    false,
  );
}

{
  const base = {
    client_id: "client-a",
    topic_id: "topic-a",
    text: "  Best   Robot Vacuum  ",
    product: "  S8 MaxV  ",
    intent: " Discovery ",
    language: " en-US ",
    platform: "chatgpt",
    country: "US",
};

{
  const selected = selectPromptConceptVariants(logicalRows[0], {
    platform: "gemini",
    platforms: ["chatgpt", "gemini"],
    country: "DE",
    countries: ["DE"],
  });
  assert.deepEqual(selected?.prompt_ids, ["physical-2"], "Prompt metrics use only physical variants matching every selected dimension");
  assert.deepEqual(selected?.platforms, ["gemini"]);
  assert.deepEqual(selected?.countries, ["DE"]);
  assert.equal(selectPromptConceptVariants(logicalRows[0], {
    platform: "gemini",
    country: "US",
  }), null, "platform and country must match the same physical variant");
}
  const baseKey = buildLogicalPromptKey(base);

  assert.equal(
    buildLogicalPromptKey({ ...base, text: "best robot vacuum", platform: "gemini", country: "DE" }),
    baseKey,
    "platform and country variants belong to the same logical Prompt",
  );
  assert.notEqual(buildLogicalPromptKey({ ...base, product: "Qrevo" }), baseKey);
  assert.notEqual(buildLogicalPromptKey({ ...base, language: "de-DE" }), baseKey);
  assert.notEqual(buildLogicalPromptKey({ ...base, intent: "Evaluation" }), baseKey);
  assert.notEqual(buildLogicalPromptKey({ ...base, client_id: "client-b" }), baseKey);
  assert.notEqual(buildLogicalPromptKey(base, "client-b"), baseKey, "an explicit client owner participates in the key");
}

{
  assert.equal(resolveCanonicalIntent("  discovery ", ["Discovery", "Evaluation"]), "Discovery");
  assert.equal(resolveCanonicalIntent("Historical", ["Discovery"]), null);
  assert.equal(matchesIntentFilter(" discovery ", { values: ["Discovery"], includeBlank: false }), true);
  assert.equal(getIntentWriteValidation("discovery", ["Discovery"]), null);

  const canonical = {
    client_id: "client-a",
    topic_id: "topic-a",
    text: "Prompt",
    product: "Product",
    intent: "Discovery",
    language: "en-US",
  };
  assert.equal(
    buildLogicalPromptKey({ ...canonical, intent: " discovery " }, undefined, ["Discovery"]),
    buildLogicalPromptKey(canonical, undefined, ["Discovery"]),
    "active Intent case variants resolve to the configured canonical value in logical grouping",
  );
  assert.notEqual(
    buildLogicalPromptKey({ ...canonical, intent: "Historical Value" }, undefined, ["Discovery"]),
    buildLogicalPromptKey(canonical, undefined, ["Discovery"]),
    "historical Intent values remain distinct without hardcoded mappings",
  );
}

{
  assert.equal(canRemoveLogicalPromptDimensionVariants(1, 1, 3), false, "the only country/platform cannot be removed");
  assert.equal(canRemoveLogicalPromptDimensionVariants(2, 3, 3), false, "a removal that covers every physical variant is blocked");
  assert.equal(canRemoveLogicalPromptDimensionVariants(2, 1, 3), true, "one of multiple dimensions can be removed safely");
}

console.log("promptIntentFilter tests passed");
