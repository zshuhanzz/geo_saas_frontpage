import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const page = readFileSync(
  new URL("../src/pages/FeatureAccessPage.tsx", import.meta.url),
  "utf8",
);

test("feature catalog follows product module order instead of alphabetic key order", () => {
  assert.match(page, /const MODULE_ORDER = \["analytics", "actions"\]/);
  assert.match(page, /MODULE_ORDER\.indexOf\(a\.module_key\)/);
  assert.doesNotMatch(page, /a\.module_key\.localeCompare\(b\.module_key\)/);
});

test("role badges expose the effective capabilities instead of only view access", () => {
  assert.match(page, /capabilities\.join\(" · "\)/);
  assert.match(page, /\{role\}: \{capabilities\.length/);
});
