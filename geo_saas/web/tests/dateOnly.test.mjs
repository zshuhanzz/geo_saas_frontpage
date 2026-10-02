import assert from "node:assert/strict";
import { toDateOnlyString, addLocalDays } from "../src/lib/dateOnly.ts";

assert.equal(
  toDateOnlyString(new Date(2026, 5, 19)),
  "2026-06-19",
  "calendar-selected local dates should not shift through UTC",
);

assert.equal(
  addLocalDays("2026-06-19", -6),
  "2026-06-13",
  "preset ranges should use local calendar arithmetic",
);

console.log("dateOnly tests passed");
