import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

import {
  applyCommittedImport,
  applyPreview,
  applyStalePreview,
  applyUndoResult,
  canCommitPromptImport,
  canCommitPromptImportForClient,
  createPromptImportState,
  getOwnedPromptImportState,
  groupAllowedValues,
  isPromptImportStateOwned,
  lazyPromptImportVariants,
  paginatePromptImportRows,
  resetPromptImportForWorkspace,
  selectPromptImportFile,
  summarizePromptImport,
} from "../src/components/prompts/promptImportViewModel.ts";
import {
  allowedValuesWorkspaceKey,
  buildPromptImportCommitFields,
  buildPromptImportLocaleParams,
  buildPromptImportRequestUrl,
  describePromptImportIssue,
  getTemplateTopicStatus,
  getTemplateDownloadReadiness,
  getOwnedAllowedValues,
  normalizePromptImportLocale,
  promptImportWorkspaceRenderKey,
} from "../src/lib/promptImport.ts";

const fileA = { name: "prompts-a.csv", size: 240 };
const preview = {
  raw_csv_sha256: "a".repeat(64),
  normalized_manifest_sha256: "b".repeat(64),
  preview_state_sha256: "c".repeat(64),
  input_row_count: 3,
  expanded_variant_count: 8,
  unique_physical_variant_count: 7,
  action_counts: { create: 5, skip: 2, conflict: 0, invalid: 1 },
  quota_before: 10,
  quota_after: 13,
  quota_limit: 100,
  rows: [],
  physical_variants: [],
};

assert.deepEqual(buildPromptImportCommitFields(preview), {
  expected_manifest_sha256: "b".repeat(64),
  expected_preview_state_sha256: "c".repeat(64),
}, "Commit must carry both the normalized manifest hash and the mutable Preview-state hash");

assert.equal(normalizePromptImportLocale("zh-CN"), "zh-CN");
assert.equal(normalizePromptImportLocale("en-US"), "en-US");
assert.equal(normalizePromptImportLocale("en"), "en-US");
assert.equal(normalizePromptImportLocale("fr-FR"), "zh-CN");
assert.deepEqual(buildPromptImportLocaleParams("client-a", "en-US"), {
  client_id: "client-a",
  locale: "en-US",
});
assert.equal(
  buildPromptImportRequestUrl("/api", "client a", "/allowed-values", "en-US"),
  "/api/prompts/import/allowed-values?client_id=client+a&locale=en-US",
  "Allowed Values request contract carries the current validated locale",
);

assert.deepEqual(describePromptImportIssue({
  code: "file_too_large",
  message: "backend English must not leak",
  actual: 11,
  allowed: 10,
}), {
  key: "prompts.import.issues.fileTooLarge",
  values: { actual: 11, allowed: 10 },
  known: true,
});
assert.deepEqual(describePromptImportIssue({
  code: "file_duplicate",
  message: "backend English must not leak",
  first_row_numbers: [2, 3],
}), {
  key: "prompts.import.issues.fileDuplicate",
  values: { rows: "2, 3" },
  known: true,
});
assert.equal(describePromptImportIssue({ code: "future_code", message: "Future backend detail" }).known, false);
assert.deepEqual(describePromptImportIssue({ code: "future code/<script>", message: "Raw backend English" }), {
  key: "prompts.import.issues.unknown",
  values: { code: "unknown" },
  known: false,
}, "unknown backend text is not part of the user-visible descriptor");

assert.notEqual(allowedValuesWorkspaceKey("client-a"), allowedValuesWorkspaceKey("client-b"), "workspace change remounts local search/copy state");
assert.notEqual(promptImportWorkspaceRenderKey("client-a"), promptImportWorkspaceRenderKey("client-b"));
assert.equal(getTemplateTopicStatus(null, true, ""), "unknown");
assert.equal(getTemplateTopicStatus(null, false, "load failed"), "unknown");
assert.equal(getTemplateTopicStatus({ customer_name: "A", rows: [] }, false, ""), "empty");
assert.equal(getTemplateTopicStatus({ customer_name: "A", rows: [{ type: "Topic" }] }, false, ""), "present");
assert.equal(getTemplateDownloadReadiness({ ownerClientId: "client-a", locale: "en-US", loading: true, error: "", allowed: null }, "client-a", "en-US"), "wait");
assert.equal(getTemplateDownloadReadiness({ ownerClientId: "client-a", locale: "en-US", loading: false, error: "load failed", allowed: null }, "client-a", "en-US"), "error");
assert.equal(getTemplateDownloadReadiness({ ownerClientId: "client-a", locale: "en-US", loading: false, error: "", allowed: { customer_name: "A", rows: [] } }, "client-a", "en-US"), "ready-empty");
assert.equal(getTemplateDownloadReadiness({ ownerClientId: "client-a", locale: "en-US", loading: false, error: "", allowed: { customer_name: "A", rows: [{ type: "Topic" }] } }, "client-a", "en-US"), "ready-present");
assert.equal(getTemplateDownloadReadiness({ ownerClientId: "client-a", locale: "en-US", loading: false, error: "", allowed: { customer_name: "A", rows: [] } }, "client-b", "en-US"), "stale");
assert.equal(getOwnedAllowedValues({ ownerClientId: "client-a", locale: "en-US", allowed: { customer_name: "A", rows: [{ type: "Topic" }] } }, "client-b", "en-US"), null, "old tenant Allowed Values are not renderable");
assert.equal(getOwnedAllowedValues({ ownerClientId: "client-a", locale: "en-US", allowed: { customer_name: "A", rows: [{ type: "Topic" }] } }, "client-a", "zh-CN"), null, "old locale Allowed Values are not renderable");

{
  const initial = createPromptImportState("client-a");
  const selected = selectPromptImportFile({ ...initial, preview, committed: { batch_id: "old" } }, fileA);
  assert.equal(selected.file, fileA);
  assert.equal(selected.preview, null);
  assert.equal(selected.committed, null);
  assert.equal(selected.previewStale, false);
}

{
  const summary = summarizePromptImport(preview);
  assert.deepEqual(summary, {
    inputRows: 3,
    expandedVariants: 8,
    quotaImpact: 3,
    quotaBefore: 10,
    quotaAfter: 13,
    quotaLimit: 100,
    create: 5,
    skip: 2,
    conflict: 0,
    invalid: 1,
  });
}

{
  const base = selectPromptImportFile(createPromptImportState("client-a"), fileA);
  const valid = { ...preview, action_counts: { create: 5, skip: 2, conflict: 0, invalid: 0 } };
  assert.equal(canCommitPromptImport(applyPreview(base, valid)), true);
  assert.equal(canCommitPromptImport(applyPreview(base, preview)), false, "invalid rows block commit");
  assert.equal(canCommitPromptImport(applyPreview(base, { ...valid, action_counts: { ...valid.action_counts, conflict: 1 } })), false, "conflicts block commit");
  assert.equal(canCommitPromptImport({ ...applyPreview(base, valid), previewStale: true }), false, "a stale preview requires reconfirmation");
  assert.equal(canCommitPromptImport({ ...applyPreview(base, valid), file: null }), false, "the source file is mandatory");
  assert.equal(canCommitPromptImportForClient(applyPreview(base, valid), "client-a"), true);
  assert.equal(canCommitPromptImportForClient(applyPreview(base, valid), "client-b"), false, "action guard refuses stale tenant state synchronously");
  assert.equal(isPromptImportStateOwned(base, "client-a"), true);
  assert.equal(isPromptImportStateOwned(base, "client-b"), false);
  assert.equal(getOwnedPromptImportState(applyPreview(base, valid), "client-b").preview, null, "render boundary never exposes the old tenant preview");
}

{
  const rows = Array.from({ length: 55 }, (_, index) => ({ row_number: 55 - index, variants: [{ id: index }] }));
  const firstPage = paginatePromptImportRows(rows, 0, 20);
  const lastPage = paginatePromptImportRows(rows, 2, 20);
  assert.deepEqual(firstPage.rows.map((row) => row.row_number), Array.from({ length: 20 }, (_, index) => index + 1));
  assert.equal(firstPage.pageCount, 3);
  assert.deepEqual(lastPage.rows.map((row) => row.row_number), Array.from({ length: 15 }, (_, index) => index + 41));
  assert.deepEqual(lazyPromptImportVariants(firstPage.rows[0], null), [], "collapsed rows do not expose variant nodes for rendering");
  assert.equal(lazyPromptImportVariants(firstPage.rows[0], 1).length, 1);
}

{
  const base = applyPreview(selectPromptImportFile(createPromptImportState("client-a"), fileA), preview);
  const refreshed = { ...preview, preview_state_sha256: "d".repeat(64), action_counts: { create: 4, skip: 3, conflict: 0, invalid: 0 } };
  const stale = applyStalePreview(base, refreshed);
  assert.equal(stale.preview, refreshed, "409 replaces the displayed preview with the server refresh");
  assert.equal(stale.previewStale, true);
  assert.equal(canCommitPromptImport(stale), false);
  assert.equal(canCommitPromptImport(applyPreview(stale, refreshed)), true, "explicit preview confirmation clears stale state");
}

{
  const groups = groupAllowedValues([
    { type: "Product", value: "S8", label: "S8", parent_type: "Topic", parent_value: "Robot Vacuum", notes: "" },
    { type: "Topic", value: "Robot Vacuum", label: "Robot Vacuum", parent_type: "", parent_value: "", notes: "" },
    { type: "AI Platform", value: "chatgpt", label: "ChatGPT", parent_type: "", parent_value: "", notes: "US" },
  ], "s8");
  assert.deepEqual(Object.keys(groups), ["Product"]);
  assert.equal(groups.Product[0].parent_value, "Robot Vacuum", "Product preserves its Topic parent for disambiguation");
  assert.equal(groups.Product[0].value, "S8", "copy/download use the canonical Value, not the display label");
}

{
  const imported = applyCommittedImport(
    applyPreview(selectPromptImportFile(createPromptImportState("client-a"), fileA), preview),
    { batch_id: "batch-1", created: 5, ids: ["p1"], preview },
  );
  const reset = resetPromptImportForWorkspace(imported, "client-b");
  assert.equal(reset.clientId, "client-b");
  assert.equal(reset.file, null);
  assert.equal(reset.preview, null);
  assert.equal(reset.committed, null);
  assert.equal(reset.undoResult, null);

  const undone = applyUndoResult(imported, {
    batch_id: "batch-1",
    status: "REVERTED",
    already_reverted: false,
    deleted: 5,
  });
  assert.equal(undone.undoResult?.deleted, 5);
  assert.equal(undone.committed?.batch_id, "batch-1", "result remains visible after Undo");
}

console.log("prompt import view-model tests passed");

const promptsSource = readFileSync(new URL("../src/pages/insights/Prompts.tsx", import.meta.url), "utf8");
assert.match(promptsSource, /<PromptImportDialog\s+key=\{promptImportWorkspaceRenderKey\(clientId\)\}/s, "parent render key must be tenant-owned");
