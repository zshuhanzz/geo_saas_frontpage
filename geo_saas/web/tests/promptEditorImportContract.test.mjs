import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const editorSource = readFileSync(new URL("../src/pages/PromptEditor.tsx", import.meta.url), "utf8");
const promptsSource = readFileSync(new URL("../src/pages/insights/Prompts.tsx", import.meta.url), "utf8");
const dialogSource = readFileSync(new URL("../src/components/prompts/PromptImportDialog.tsx", import.meta.url), "utf8");

assert.match(editorSource, /import \{ PromptImportDialog \} from "@\/components\/prompts\/PromptImportDialog";/);
assert.match(editorSource, /onClick=\{\(\) => setImportOpen\(true\)\}/, "the existing Batch Upload button opens the shared import flow");
assert.match(
  editorSource,
  /<PromptImportDialog\s+key=\{promptImportWorkspaceRenderKey\(clientId\)\}[\s\S]*?clientId=\{clientId\}[\s\S]*?workspaceName=\{activeClient\?\.name \|\| ""\}[\s\S]*?onImported=\{handlePromptImported\}/,
  "PromptEditor mounts one tenant-keyed shared dialog with the authorized Workspace name and refresh callback",
);
assert.match(
  promptsSource,
  /<PromptImportDialog[\s\S]*?workspaceName=\{activeClient\?\.name \|\| ""\}/,
  "the original Prompt page supplies the same explicit Workspace identity",
);
assert.match(dialogSource, /workspaceName: string;/, "the shared dialog requires an explicit authorized Workspace name");
assert.match(dialogSource, /prompts\.import\.workspace/, "the dialog visibly binds the import to that Workspace");

console.log("PromptEditor shared import contract tests passed");
