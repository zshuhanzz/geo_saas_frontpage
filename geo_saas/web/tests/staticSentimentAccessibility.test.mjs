import assert from "node:assert/strict";
import fs from "node:fs";

const source = fs.readFileSync(
  new URL("../src/pages/reports/components/StaticSentimentSection.tsx", import.meta.url),
  "utf8",
);
const reportsEn = JSON.parse(fs.readFileSync(new URL("../src/i18n/locales/en-US/reports.json", import.meta.url), "utf8"));
const reportsZh = JSON.parse(fs.readFileSync(new URL("../src/i18n/locales/zh-CN/reports.json", import.meta.url), "utf8"));

assert.doesNotMatch(source, /No themes extracted yet\. Run the Analyzer/);
assert.doesNotMatch(source, /Show more \(/);
assert.match(source, /reportT\("sentiment\.emptyThemes"\)/);
assert.match(source, /reportT\("sentiment\.showMoreThemes", \{ count:/);
assert.equal(reportsEn.sentiment.emptyThemes.length > 0, true);
assert.equal(reportsZh.sentiment.emptyThemes.length > 0, true);
assert.equal(reportsEn.sentiment.showMoreThemes.includes("{{count}}"), true);
assert.equal(reportsZh.sentiment.showMoreThemes.includes("{{count}}"), true);

const disclosureButton = source.match(/<button[\s\S]*?aria-expanded=\{expanded\}[\s\S]*?aria-controls=\{detailsId\}[\s\S]*?onClick=\{\(\) => toggleTheme\(key\)\}[\s\S]*?<\/button>/);
assert.ok(disclosureButton, "theme disclosure must be a keyboard-focusable button with expansion semantics");
assert.match(source, /id=\{detailsId\}/);
assert.match(source, /hidden=\{!expanded\}/);

console.log("static sentiment accessibility tests passed");
