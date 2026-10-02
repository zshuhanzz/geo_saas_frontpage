import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const root = new URL("../src/", import.meta.url);
const read = (path) => readFileSync(new URL(path, root), "utf8");

test("scheduler controls expose Enable for missing jobs and call the enable API", () => {
    const page = read("pages/ClientsPage.tsx");
    const api = read("api/client.ts");

    assert.match(page, /enableSchedulerJob/);
    assert.doesNotMatch(page, /state === ['"]NOT_FOUND['"]\) return null/);
    assert.match(page, /currentState === ['"]NOT_FOUND['"]/);
    assert.match(page, /['"]Enable['"]/);
    assert.match(api, /export async function enableSchedulerJob/);
    assert.match(api, /scheduler\/\$\{jobType\}\/enable/);
});
