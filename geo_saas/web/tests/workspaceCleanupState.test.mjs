import assert from "node:assert/strict";

import {
  CLEANUP_BATCH_SIZE,
  buildPromptBatchDeleteBody,
  createSingleFlightGuard,
  getManualPromptDeleteBatchSize,
  getWorkspaceCleanupRequest,
  isWorkspaceCleanupComplete,
  runSerialPromptCleanup,
} from "../src/lib/workspaceCleanup.ts";
import {
  buildWorkspaceSaaSLink,
  canSubmitWorkspaceDelete,
  getWorkspaceDeletionStep,
} from "../../../geo_admin/web/src/lib/workspaceDeletion.ts";
import { ApiError as AdminApiError } from "../../../geo_admin/web/src/api/types.ts";
import { ApiError as SaaSApiError } from "../src/lib/api/_errors.ts";

const baseReadiness = {
  workspace: { id: "workspace-1", name: "AnswerX" },
  schedulers: {
    collector: { state: "NOT_FOUND", stopped: true },
    analyzer: { state: "NOT_FOUND", stopped: true },
    llm_discovery: { state: "NOT_FOUND", stopped: true },
  },
  counts: {
    topics: 0,
    logical_prompts: 0,
    physical_prompts: 0,
    tasks: 0,
    results: 0,
    citations: 0,
    brand_mentions: 0,
    product_mentions: 0,
    sentiment_results: 0,
    sentiment_themes: 0,
    static_reports: 0,
    agent_tasks: 0,
    published_urls: 0,
  },
  cascade_footprint: { total_rows: 0, max_rows: 1000, by_table: {} },
  active_work: { guarded_writer: false, total_items: 0, by_table: {} },
  blockers: [],
  recommended_next_action: "FINALIZE_DELETE",
  can_finalize: true,
};

assert.equal(getWorkspaceDeletionStep(baseReadiness), "FINALIZE_DELETE");
assert.equal(
  getWorkspaceDeletionStep({
    ...baseReadiness,
    recommended_next_action: "STOP_SCHEDULING",
    can_finalize: false,
  }),
  "STOP_SCHEDULING",
);
assert.equal(
  getWorkspaceDeletionStep({
    ...baseReadiness,
    recommended_next_action: "DELETE_PROMPTS",
    can_finalize: false,
    counts: { ...baseReadiness.counts, physical_prompts: 3 },
  }),
  "DELETE_PROMPTS",
);
assert.equal(
  getWorkspaceDeletionStep({
    ...baseReadiness,
    recommended_next_action: "DELETE_TOPICS",
    can_finalize: false,
    counts: { ...baseReadiness.counts, topics: 2 },
  }),
  "DELETE_TOPICS",
);
assert.equal(
  getWorkspaceDeletionStep({
    ...baseReadiness,
    recommended_next_action: "INTERNAL_DATA_REPAIR",
    can_finalize: false,
    blockers: [{ code: "ORPHANED_FACT_DATA", message: "Internal repair required" }],
  }),
  "INTERNAL_DATA_REPAIR",
);

assert.equal(
  buildWorkspaceSaaSLink("https://saas.example.com/", "/prompt-editor", "workspace 1", {
    workspace_cleanup: "prompts",
  }),
  "https://saas.example.com/prompt-editor?client_id=workspace+1&workspace_cleanup=prompts",
  "the configured SaaS origin and workspace context are carried without a hardcoded host",
);
assert.equal(buildWorkspaceSaaSLink("", "/prompt-editor", "workspace-1"), null);
assert.equal(buildWorkspaceSaaSLink("not a URL", "/prompt-editor", "workspace-1"), null);

assert.equal(canSubmitWorkspaceDelete(baseReadiness, "AnswerX", false), true);
assert.equal(canSubmitWorkspaceDelete(baseReadiness, " AnswerX ", false), false, "name matching is exact");
assert.equal(canSubmitWorkspaceDelete(baseReadiness, "AnswerX", true), false, "an in-flight request disables duplicate submission");
assert.equal(canSubmitWorkspaceDelete({ ...baseReadiness, can_finalize: false }, "AnswerX", false), false);

assert.deepEqual(
  getWorkspaceCleanupRequest("?client_id=workspace-1&workspace_cleanup=prompts"),
  { enabled: true, clientId: "workspace-1" },
);
assert.deepEqual(getWorkspaceCleanupRequest("?client_id=workspace-1"), { enabled: false, clientId: "workspace-1" });

assert.equal(CLEANUP_BATCH_SIZE, 25);
assert.deepEqual(buildPromptBatchDeleteBody(["p1", "p2"], 25), {
  prompt_ids: ["p1", "p2"],
  batch_size: 25,
});
assert.deepEqual(buildPromptBatchDeleteBody(["p1"]), { prompt_ids: ["p1"] });
assert.equal(getManualPromptDeleteBatchSize(26), 26, "ordinary 26..100 selection preserves one-request behavior");
assert.equal(getManualPromptDeleteBatchSize(100), 100);
assert.equal(getManualPromptDeleteBatchSize(101), null, "oversized ordinary selection is rejected in the UI");
const promptIds = Array.from({ length: 61 }, (_, index) => `prompt-${index + 1}`);
const batches = [];
const progress = [];
let currentPromptIds = [...promptIds];
const complete = await runSerialPromptCleanup({
  loadPromptIds: async () => currentPromptIds,
  deleteBatch: async (ids, batchSize) => {
    batches.push({ ids: [...ids], batchSize });
    currentPromptIds = currentPromptIds.filter((id) => !ids.includes(id));
    return { deleted: ids.length };
  },
  onProgress: (state) => progress.push({ ...state }),
});
assert.deepEqual(batches.map((batch) => batch.ids.length), [25, 25, 11]);
assert.deepEqual(batches.map((batch) => batch.batchSize), [25, 25, 25]);
assert.equal(complete.status, "complete");
assert.equal(complete.total, 61);
assert.equal(complete.deleted, 61);
assert.equal(complete.remaining, 0);
assert.deepEqual(progress.at(-1), complete);

let attempts = 0;
let failedPromptIds = promptIds.slice(0, 30);
const failed = await runSerialPromptCleanup({
  loadPromptIds: async () => failedPromptIds,
  deleteBatch: async (ids) => {
    attempts += 1;
    if (attempts === 2) throw new Error("second batch failed");
    failedPromptIds = failedPromptIds.filter((id) => !ids.includes(id));
    return { deleted: ids.length };
  },
});
assert.equal(failed.status, "failed");
assert.equal(failed.deleted, 25);
assert.equal(failed.remaining, 5);
assert.equal(attempts, 2, "cleanup stops immediately after the first failed batch");

const resumedBatches = [];
let resumedPromptIds = promptIds.slice(25, 30);
const resumed = await runSerialPromptCleanup({
  loadPromptIds: async () => resumedPromptIds,
  deleteBatch: async (ids, batchSize) => {
    resumedBatches.push({ ids: [...ids], batchSize });
    resumedPromptIds = resumedPromptIds.filter((id) => !ids.includes(id));
    return { deleted: ids.length };
  },
});
assert.equal(resumed.status, "complete");
assert.deepEqual(resumedBatches.map((batch) => batch.ids.length), [5], "resume starts from a fresh tenant-scoped ID fetch");

let concurrentLoad = 0;
let refreshedConcurrentIds = [];
const concurrentCreate = await runSerialPromptCleanup({
  loadPromptIds: async () => {
    concurrentLoad += 1;
    return concurrentLoad === 1 ? ["original-1"] : ["concurrent-1", "concurrent-2"];
  },
  deleteBatch: async (ids) => ({ deleted: ids.length }),
  onRefreshedPromptIds: (ids) => {
    refreshedConcurrentIds = [...ids];
  },
});
assert.equal(concurrentLoad, 2, "the current tenant is fetched again after the final serial batch");
assert.equal(concurrentCreate.status, "failed", "new rows prevent a false complete state");
assert.equal(concurrentCreate.remaining, 2, "the resumable state reports the fresh physical count");
assert.equal(concurrentCreate.error.code, "CONCURRENT_PROMPTS_REMAIN");
assert.deepEqual(
  refreshedConcurrentIds,
  ["concurrent-1", "concurrent-2"],
  "the page-state handoff receives the same fresh snapshot used for the result",
);
assert.equal(isWorkspaceCleanupComplete(concurrentCreate, 2), false);
assert.equal(
  isWorkspaceCleanupComplete({ ...concurrentCreate, status: "complete", remaining: 0 }, 2),
  false,
  "the dialog cannot show complete while the freshly loaded page still has physical rows",
);
assert.equal(
  isWorkspaceCleanupComplete({ ...concurrentCreate, status: "complete", remaining: 0 }, 0),
  true,
);

const loadFailed = await runSerialPromptCleanup({
  loadPromptIds: async () => { throw new Error("ID refresh failed"); },
  deleteBatch: async () => { throw new Error("must not run"); },
});
assert.equal(loadFailed.status, "failed");
assert.equal(loadFailed.deleted, 0);
assert.equal(loadFailed.remaining, 0);
assert.match(loadFailed.error.message, /ID refresh failed/);

let partialPromptIds = ["prompt-1", "prompt-2"];
const partialDelete = await runSerialPromptCleanup({
  loadPromptIds: async () => partialPromptIds,
  deleteBatch: async () => {
    partialPromptIds = ["prompt-2"];
    return { deleted: 1 };
  },
});
assert.equal(partialDelete.status, "failed", "a server-side partial count must be resumed from fresh state");
assert.equal(partialDelete.remaining, 1);

const guard = createSingleFlightGuard();
assert.equal(guard.tryStart(), true);
assert.equal(guard.tryStart(), false, "a double click cannot start a second cleanup run");
guard.finish();
assert.equal(guard.tryStart(), true);

const structured = new AdminApiError({ code: "WORKSPACE_BLOCKED", message: "Remove Prompts first" }, 409);
assert.equal(structured.code, "WORKSPACE_BLOCKED");
assert.equal(structured.message, "Remove Prompts first");
assert.deepEqual(structured.structuredDetail, { code: "WORKSPACE_BLOCKED", message: "Remove Prompts first" });

const promptError = new SaaSApiError({ code: "prompt_delete_batch_size_exceeded", message: "Batch failed" }, 422);
assert.equal(promptError.code, "prompt_delete_batch_size_exceeded");
assert.equal(promptError.message, "Batch failed");

console.log("workspace cleanup state tests passed");
