import assert from "node:assert/strict";
import test from "node:test";

import { createWorkspaceActionEpoch } from "../src/lib/workspaceDeletion.ts";

function deferred() {
  let resolve;
  const promise = new Promise((done) => {
    resolve = done;
  });
  return { promise, resolve };
}

test("a pending Workspace A stop cannot overwrite reopened Workspace B state", async () => {
  const actions = createWorkspaceActionEpoch();
  actions.setOwner(true, "workspace-a");
  const actionA = actions.begin("workspace-a");
  assert.ok(actionA);

  let state = { workspaceId: "workspace-a", stopping: true, loading: false, error: "" };
  const pendingStop = deferred();
  const stopRun = pendingStop.promise
    .then(() => {
      if (actions.isCurrent(actionA)) {
        state = { ...state, loading: true };
      }
    })
    .finally(() => {
      if (actions.isCurrent(actionA)) {
        state = { ...state, stopping: false };
      }
      actions.finish(actionA);
    });

  actions.setOwner(false, null);
  assert.equal(actionA.signal.aborted, true, "closing aborts A where fetch supports AbortSignal");
  actions.setOwner(true, "workspace-b");
  state = { workspaceId: "workspace-b", stopping: false, loading: true, error: "" };

  pendingStop.resolve();
  await stopRun;

  assert.deepEqual(state, {
    workspaceId: "workspace-b",
    stopping: false,
    loading: true,
    error: "",
  });
});
