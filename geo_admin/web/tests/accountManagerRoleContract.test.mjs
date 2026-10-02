import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const root = new URL("../src/", import.meta.url);
const read = (path) => readFileSync(new URL(path, root), "utf8");

test("Access Control supports the Workspace-scoped Account Manager role", () => {
  const api = read("api/client.ts");
  const page = read("pages/AccessControlPage.tsx");

  assert.match(api, /"admin" \| "viewer" \| "account_manager"/);
  assert.match(page, /type ClientRole = "admin" \| "viewer" \| "account_manager"/);
  assert.match(page, /<SelectItem value="account_manager">Account Manager<\/SelectItem>/);
});

test("Feature Access displays both external and internal capability matrices", () => {
  const page = read("pages/FeatureAccessPage.tsx");
  assert.match(
    page,
    /\["super_admin", "account_manager", "admin", "viewer"\]/,
  );
});

test("standard packages cannot remove Configuration in the Admin UI", () => {
  const page = read("pages/FeatureAccessPage.tsx");
  assert.match(page, /lockedKeys/);
  assert.match(page, /actions\.configuration/);
  assert.match(page, /selectedPackageKey === "analytics"/);
  assert.match(page, /selectedPackageKey === "full_platform"/);
});
