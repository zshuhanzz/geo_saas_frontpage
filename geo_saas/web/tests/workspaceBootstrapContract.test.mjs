import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const root = new URL("../src/", import.meta.url);
const read = (path) => readFileSync(new URL(path, root), "utf8");

test("SaaS bootstrap lists lightweight Workspaces then loads selected context", () => {
  const api = read("lib/api/clients.ts");
  const context = read("contexts/SaaSContext.tsx");

  assert.match(api, /\/me\/workspaces/);
  assert.match(api, /\/workspaces\/\$\{clientId\}\/context/);
  assert.match(api, /\/me\/feature-catalog/);
  assert.match(context, /getWorkspaces/);
  assert.match(context, /getWorkspaceContext/);
  assert.match(context, /actions\.configuration/);
  assert.doesNotMatch(context, /getClients\(/);
});

test("unlock copy uses Admin-managed feature catalog with static fallback", () => {
  const boundary = read("components/permissions/FeatureAccessBoundary.tsx");
  const context = read("contexts/SaaSContext.tsx");

  assert.match(context, /featureCatalog/);
  assert.match(boundary, /featureCatalog/);
  assert.match(boundary, /feature\.description_zh/);
});

test("dynamic reports load only their authorized Workspace context", () => {
  const report = read("pages/reports/components/DynamicDateRangeReport.tsx");

  assert.match(report, /getWorkspaceContext\(reportClientId\)/);
  assert.doesNotMatch(report, /getClients\(/);
});
