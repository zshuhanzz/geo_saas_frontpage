import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const authContext = readFileSync(
  new URL("../src/contexts/AuthContext.tsx", import.meta.url),
  "utf8",
);
const apiBase = readFileSync(
  new URL("../src/lib/api/_base.ts", import.meta.url),
  "utf8",
);

test("SaaS exchanges Google credential for an HttpOnly server Session", () => {
  assert.match(authContext, /\/auth\/session/);
  assert.match(authContext, /credential/);
  assert.doesNotMatch(authContext, /jwtDecode/);
  assert.doesNotMatch(authContext, /localStorage\.setItem\(['"]geo_saas_token/);
  assert.match(authContext, /\/auth\/logout/);
});

test("SaaS API calls stay same-origin and do not send Google bearer tokens", () => {
  assert.match(apiBase, /credentials:\s*["']same-origin["']/);
  assert.doesNotMatch(apiBase, /Authorization\s*=/);
  assert.doesNotMatch(apiBase, /Bearer \$\{token\}/);
});
