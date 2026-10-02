import assert from "node:assert/strict";

import {
  LEGACY_PROMPTS_PATH,
  LEGACY_PROMPTS_REDIRECT_TARGET,
  PROMPT_ROUTE_CONTRACT,
  PROMPTS_PATH,
  SIDEBAR_NAV_GROUPS,
  buildPromptTabs,
  isSidebarNavItemActive,
} from "../src/components/layout/sidebarNavigation.ts";

const dashboardGroup = SIDEBAR_NAV_GROUPS.find((group) => group.id === "dashboards");
assert.ok(dashboardGroup, "the dashboard navigation group is present");

const dashboardIds = dashboardGroup.items.map((item) => item.id);
assert.deepEqual(
  dashboardIds.slice(
    dashboardIds.indexOf("sentiment"),
    dashboardIds.indexOf("reports") + 1,
  ),
  ["sentiment", "prompts", "reports"],
  "Prompt is an independent top-level item between Sentiment and Report",
);

assert.equal(PROMPTS_PATH, "/insights/prompts");
assert.equal(LEGACY_PROMPTS_PATH, "/prompts");
assert.equal(
  LEGACY_PROMPTS_REDIRECT_TARGET,
  PROMPTS_PATH,
  "the legacy route redirects to the one canonical Prompt page",
);
assert.deepEqual(PROMPT_ROUTE_CONTRACT, {
  canonicalPath: "/insights/prompts",
  childSegment: "prompts",
  legacyPath: "/prompts",
  redirectTarget: "/insights/prompts",
  replace: true,
});

assert.deepEqual(
  buildPromptTabs(),
  [
    { key: "prompts", path: "/insights/prompts" },
    { key: "fanouts", path: "/insights/fanouts" },
  ],
  "the Prompt section owns exactly the Prompt and Query Fanout tabs",
);

for (const path of [PROMPTS_PATH, `${PROMPTS_PATH}/`, `${PROMPTS_PATH}/topic/topic-1`, "/prompts/"]) {
  assert.equal(isSidebarNavItemActive("prompts", path), true, `${path} activates Prompt`);
  assert.equal(isSidebarNavItemActive("visibility", path), false, `${path} does not activate Visibility`);
  assert.deepEqual(
    SIDEBAR_NAV_GROUPS.flatMap((group) => group.items)
      .filter((item) => isSidebarNavItemActive(item.id, path))
      .map((item) => item.id),
    ["prompts"],
    `${path} activates only Prompt`,
  );
}

for (const path of ["/prompts-old", "/insights/prompts-old", "/citationary", "/reports-old"]) {
  assert.deepEqual(
    SIDEBAR_NAV_GROUPS.flatMap((group) => group.items)
      .filter((item) => isSidebarNavItemActive(item.id, path))
      .map((item) => item.id),
    [],
    `${path} does not activate a similarly-prefixed Sidebar item`,
  );
}

for (const path of ["/insights", "/insights/visibility"]) {
  assert.equal(isSidebarNavItemActive("visibility", path), true, `${path} activates Visibility`);
  assert.equal(isSidebarNavItemActive("prompts", path), false, `${path} does not activate Prompt`);
}

assert.equal(isSidebarNavItemActive("prompts", "/insights/fanouts"), true, "Query Fanout belongs to Prompt");
assert.equal(isSidebarNavItemActive("visibility", "/insights/fanouts"), false, "Query Fanout no longer belongs to Visibility");

for (const [path, expectedId] of [
  ["/overview", "overview"],
  ["/citation/details", "citation"],
  ["/sentiment", "sentiment"],
  ["/reports/static/report-1", "reports"],
  ["/settings", null],
  ["/unknown", null],
]) {
  const activeIds = SIDEBAR_NAV_GROUPS.flatMap((group) => group.items)
    .filter((item) => isSidebarNavItemActive(item.id, path))
    .map((item) => item.id);
  assert.deepEqual(activeIds, expectedId ? [expectedId] : [], `${path} has the expected active item`);
}

console.log("promptNavigation tests passed");
