import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const root = new URL("../src/", import.meta.url);
const read = (path) => readFileSync(new URL(path, root), "utf8");

test("Feature Access initializes its Workspace selector from a lightweight endpoint", () => {
  const api = read("api/client.ts");
  const page = read("pages/FeatureAccessPage.tsx");

  assert.match(api, /getFeatureWorkspaceOptions/);
  assert.match(api, /feature-access\/workspaces/);
  assert.match(page, /getFeatureWorkspaceOptions\(\)/);
  assert.doesNotMatch(page, /getClients\(\)/);
  assert.match(page, /WorkspaceOption/);
});

test("Workspace entitlement loading hides stale values and disables all write controls", () => {
  const page = read("pages/FeatureAccessPage.tsx");

  assert.match(page, /entitlementLoading/);
  assert.match(page, /WorkspaceEntitlementsSkeleton/);
  assert.match(page, /entitlementRequestSequence/);
  assert.match(page, /requestSequence !== entitlementRequestSequence\.current/);
  assert.match(page, /disabled=\{entitlementLoading \|\| saving\}/);
  assert.match(
    page,
    /disabled=\{saving \|\| entitlementLoading \|\| !selectedClientId\}/,
  );
});
