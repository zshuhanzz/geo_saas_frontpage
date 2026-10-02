import assert from "node:assert/strict";
import fs from "node:fs";
import {
  comparisonPresentation,
  canFilterFrozenSnapshot,
} from "../src/pages/reports/components/reportComparison.ts";
import { comparisonIndicatorState } from "../src/lib/comparisonIndicator.ts";

assert.deepEqual(comparisonPresentation(5, "higher"), { direction: "up", tone: "positive" });
assert.deepEqual(comparisonPresentation(-5, "higher"), { direction: "down", tone: "negative" });
assert.deepEqual(comparisonPresentation(-2, "lower"), { direction: "up", tone: "positive" });
assert.deepEqual(comparisonPresentation(2, "lower"), { direction: "down", tone: "negative" });
assert.deepEqual(comparisonPresentation(null, "higher"), { direction: "none", tone: "neutral" });

assert.equal(canFilterFrozenSnapshot({
  visibility: { dashboard: { source_rows: [{}], response_source_rows: [{}], previous: { source_rows: [{}], response_source_rows: [{}] } } },
  citations: { dashboard: { source_rows: [{}], previous: { source_rows: [{}] } } },
  sentiment: { dashboard: { source_rows: [{}], previous: { source_rows: [{}] } } },
}), true);
assert.equal(canFilterFrozenSnapshot({ visibility: { dashboard: { source_rows_limited: true } }, citations: { dashboard: {} }, sentiment: { dashboard: {} } }), false);

console.log("staticReportComparison tests passed");

assert.deepEqual(comparisonIndicatorState(null, "higher", true), { visible: true, display: "—", tone: "neutral", direction: "none" });
assert.deepEqual(comparisonIndicatorState(0, "higher", true), { visible: true, display: "0%", tone: "neutral", direction: "none" });
assert.equal(comparisonIndicatorState(null, "higher", false).visible, false);
assert.equal(comparisonIndicatorState(0, "higher", false).visible, false);
assert.deepEqual(comparisonIndicatorState(-2, "lower", true), { visible: true, display: "2%", tone: "positive", direction: "up" });

const visibilitySource = fs.readFileSync(new URL("../src/components/insights/VisibilityDashboard.tsx", import.meta.url), "utf8");
assert.match(visibilitySource, /<MetricChangeBadge value=\{r\[changeKey\]\} improvement="higher" enabled=\{comparisonEnabled\}/);
