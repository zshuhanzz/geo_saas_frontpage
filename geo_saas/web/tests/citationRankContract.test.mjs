import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const dashboard = readFileSync(
  new URL("../src/components/insights/CitationDashboard.tsx", import.meta.url),
  "utf8",
);
const openapi = readFileSync(new URL("../src/api/openapi.d.ts", import.meta.url), "utf8");

const domainSchema = openapi.slice(
  openapi.indexOf("CitationDomainRow: {"),
  openapi.indexOf("CitationPageRow: {"),
);
const pageSchema = openapi.slice(
  openapi.indexOf("CitationPageRow: {"),
  openapi.indexOf("CitationTimePoint: {"),
);

assert.match(domainSchema, /\brank: number;/, "generated full citation domain rows require rank");
assert.match(pageSchema, /\brank: number;/, "generated full citation page rows require rank");
assert.doesNotMatch(dashboard, /rank\?: number/, "dashboard must trust the generated required rank");
assert.doesNotMatch(
  dashboard,
  /r\.rank\s*\?\?\s*i\s*\+\s*1/,
  "dashboard must never renumber a user-sorted result by its rendered index",
);
assert.match(dashboard, /\{r\.rank\}\.?<\/span>/, "ranking surfaces render the canonical row rank");

console.log("citation rank contract tests passed");
