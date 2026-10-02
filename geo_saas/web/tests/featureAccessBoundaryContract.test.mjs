import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const root = new URL("../", import.meta.url);
const source = readFileSync(
  new URL("src/components/permissions/FeatureAccessBoundary.tsx", root),
  "utf8",
);
const zh = JSON.parse(
  readFileSync(new URL("src/i18n/locales/zh-CN/common.json", root), "utf8"),
);
const en = JSON.parse(
  readFileSync(new URL("src/i18n/locales/en-US/common.json", root), "utf8"),
);

test("protected page content is never rendered before Workspace access resolves", () => {
  assert.doesNotMatch(
    source,
    /if \(loadingClients \|\| !activeClient \|\| !feature\) return <>\{children\}<\/>/,
  );
  assert.match(source, /if \(loadingClients\) return <FeatureAccessLoading \/>/);
  assert.match(source, /if \(!activeClient\) return <NoActiveWorkspace \/>/);
});

test("permission loading and missing Workspace states are bilingual", () => {
  for (const messages of [zh, en]) {
    assert.equal(typeof messages.access.loading, "string");
    assert.equal(typeof messages.access.noWorkspaceTitle, "string");
    assert.equal(typeof messages.access.noWorkspaceDescription, "string");
  }
});
