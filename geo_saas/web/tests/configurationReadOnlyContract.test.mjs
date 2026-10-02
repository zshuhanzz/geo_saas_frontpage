import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const root = new URL("../", import.meta.url);
const readSource = (path) => readFileSync(new URL(path, root), "utf8");

const boundarySource = readSource(
  "src/components/permissions/FeatureAccessBoundary.tsx",
);
const settingsSource = readSource("src/pages/SettingsPage.tsx");
const suggestionsBannerSource = readSource(
  "src/pages/SettingsPage.parts/SuggestionsBanner.tsx",
);
const suggestionsPanelSource = readSource(
  "src/components/settings/SuggestionsPanel.tsx",
);
const promptEditorSource = readSource("src/pages/PromptEditor.tsx");

test("configuration read-only mode does not disable the entire routed page", () => {
  assert.doesNotMatch(
    boundarySource,
    /<fieldset disabled[^>]*>\{children\}<\/fieldset>/,
  );
});

test("Settings keeps navigation and suggestion browsing outside its write boundary", () => {
  assert.match(
    settingsSource,
    /const configurationReadOnly = !can\("actions\.configuration", "manage"\);/,
  );
  assert.match(
    settingsSource,
    /<SuggestionsBanner[\s\S]*readOnly=\{configurationReadOnly\}[\s\S]*<TabsList/,
  );

  const tabsListEnd = settingsSource.indexOf("</TabsList>");
  const writeBoundaryStart = settingsSource.indexOf("<fieldset");
  assert.ok(tabsListEnd >= 0, "Settings tabs list must exist");
  assert.ok(
    writeBoundaryStart > tabsListEnd,
    "Settings write boundary must begin after the tab navigation",
  );
});

test("Viewer can browse AI suggestions but cannot mutate candidate state", () => {
  assert.match(suggestionsBannerSource, /readOnly: boolean;/);
  assert.match(suggestionsBannerSource, /readOnly=\{readOnly\}/);
  assert.match(suggestionsPanelSource, /readOnly\?: boolean;/);
  assert.match(
    suggestionsPanelSource,
    /disabled=\{readOnly \|\| busyId === item\.id\}/g,
  );
});

test("Prompt library back navigation stays outside its write boundary", () => {
  assert.match(
    promptEditorSource,
    /const configurationReadOnly = !can\("actions\.configuration", "manage"\);/,
  );

  const backButton = promptEditorSource.indexOf(
    'onClick={() => navigate("/insights/prompts")}',
  );
  const writeBoundaryStart = promptEditorSource.indexOf("<fieldset");
  assert.ok(backButton >= 0, "Prompt library back button must exist");
  assert.ok(
    writeBoundaryStart > backButton,
    "Prompt write boundary must begin after the back navigation",
  );
});
