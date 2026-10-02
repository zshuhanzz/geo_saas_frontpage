import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const authContext = readFileSync(
  new URL("../src/contexts/AuthContext.tsx", import.meta.url),
  "utf8",
);
const apiClient = readFileSync(
  new URL("../src/api/client.ts", import.meta.url),
  "utf8",
);

test("Admin exchanges Google credential for an independent server Session", () => {
  assert.match(authContext, /\/auth\/session/);
  assert.doesNotMatch(authContext, /jwtDecode/);
  assert.doesNotMatch(authContext, /localStorage\.setItem\(['"]geo_admin_token/);
  assert.match(authContext, /\/auth\/logout/);
});

test("Admin API calls use same-origin cookies without Google bearer headers", () => {
  assert.match(apiClient, /credentials:\s*["']same-origin["']/);
  assert.doesNotMatch(apiClient, /Bearer \$\{token\}/);
});
