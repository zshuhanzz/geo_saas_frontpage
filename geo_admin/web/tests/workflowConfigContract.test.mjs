import assert from "node:assert/strict";

import {
  getWorkflowConfigItems,
  parseWorkflowConfigValue,
} from "../src/lib/workflowConfig.ts";

const grouped = {
  goal: [
    { config_type: "goal", scope: "analysis", key: "health", value: { label: "Health" } },
  ],
};

assert.deepEqual(getWorkflowConfigItems(grouped, "goal"), grouped.goal);
assert.deepEqual(getWorkflowConfigItems(grouped, "missing"), []);
assert.deepEqual(parseWorkflowConfigValue({ label: "Health" }), { label: "Health" });
assert.deepEqual(parseWorkflowConfigValue('{"label":"Health"}'), { label: "Health" });
assert.deepEqual(parseWorkflowConfigValue("invalid JSON"), {});
assert.deepEqual(parseWorkflowConfigValue(["not", "an", "object"]), {});

console.log("workflow config contract tests passed");
