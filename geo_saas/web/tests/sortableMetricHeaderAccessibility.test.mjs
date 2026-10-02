import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { buildMetricSortAccessibility } from "../src/lib/metricSort.ts";

const attributes = buildMetricSortAccessibility({
  actionLabel: "Sort Score descending",
  currentStateLabel: "Currently sorted ascending.",
  direction: "asc",
});
const markup = renderToStaticMarkup(createElement("button", attributes, "Score"));

assert.match(
  markup,
  /aria-label="Sort Score descending Currently sorted ascending\."/,
  "the rendered accessible name includes both the next action and current state",
);
assert.match(markup, /data-sort-direction="asc"/, "the rendered control exposes its current direction as state");

console.log("sortableMetricHeader accessibility tests passed");
