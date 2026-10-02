import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const source = readFileSync(new URL("../src/api/openapi.d.ts", import.meta.url), "utf8");

for (const path of [
  "/api/prompts/intent-facets",
  "/api/prompts/concepts",
  "/api/prompts/{prompt_id}/concept",
  "/api/prompts/import/allowed-values",
  "/api/prompts/import/allowed-values.csv",
  "/api/prompts/import/template.csv",
  "/api/prompts/import/preview",
  "/api/prompts/import/commit",
  "/api/prompts/import/{batch_id}/undo",
  "/api/static-reports/{report_id}/lists/{list_type}",
  "/api/insights/published-url-tracking",
]) {
  assert.ok(source.includes(`"${path}"`), `generated SaaS OpenAPI types must include ${path}`);
}

for (const schema of ["PromptIntentFacetsOut", "PromptConceptOut", "PromptListConceptOut", "StaticReportFrozenListOut"]) {
  assert.match(source, new RegExp(`\\b${schema}: \\{`), `generated schema ${schema} must be current`);
}

const publishedStart = source.indexOf("get_published_url_tracking_api_insights_published_url_tracking_get: {");
const publishedEnd = source.indexOf("get_published_url_tracking_detail_api_insights_published_url_tracking__published_url_id__get: {");
const publishedContract = source.slice(publishedStart, publishedEnd);
for (const queryName of ["products", "prompt_id", "prompt_ids", "sort_by", "sort_order"]) {
  assert.match(publishedContract, new RegExp(`\\b${queryName}\\?:`), `published tracking must expose ${queryName}`);
}

console.log("generated SaaS OpenAPI contract tests passed");
