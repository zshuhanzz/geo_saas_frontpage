# Reddit Research Preflight Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a configuration-driven Reddit Research Wizard group with Subreddit Targeting, Reddit Discovery, and Artifact Preparation, backed by selectable `web_grounded` and `reddit_api` providers and reused by final content generation.

**Architecture:** The generic Wizard engine remains template-driven. Reddit-specific behavior lives in workflow/template data, custom Wizard fields, Agent preflight routes, and a Reddit provider service. `web_grounded` uses Gemini Search Grounding for candidate subreddit discovery and deterministic web fetch for rules; `reddit_api` uses approved Reddit API access. Final content generation consumes confirmed Wizard artifacts instead of regenerating them.

**Tech Stack:** FastAPI, async Python, google-genai Search Grounding, async HTTP fetch, PRAW-compatible Reddit provider, PostgreSQL JSON config, React/TypeScript, Vite, shadcn/radix UI, react-i18next.

---

## File Map

- Create: `geo_agent/src/services/reddit_research.py`
  - Provider interface, `web_grounded` provider, PRAW-backed `reddit_api` provider, config loading, normalization helpers.
- Modify: `geo_agent/src/routers/tasks.py`
  - Add three content preflight endpoints.
- Modify: `geo_agent/src/pipelines/content_pipeline.py`
  - Reuse confirmed artifacts during final generation.
- Modify: `geo_saas/web/src/components/wizard/schema.ts`
  - Register new custom field types and optional step group metadata.
- Modify: `geo_saas/web/src/components/wizard/customFields/index.ts`
  - Import new custom field components.
- Create: `geo_saas/web/src/components/wizard/customFields/SubredditTargetingPreflight.tsx`
  - AI Recommend and Manual Input UI for subreddit targets.
- Create: `geo_saas/web/src/components/wizard/customFields/RedditDiscoveryPreflight.tsx`
  - Rules, sidebar, community questions, risks, and evidence UI.
- Create: `geo_saas/web/src/components/wizard/customFields/PromptArtifactPreparationPreflight.tsx`
  - Generate, regenerate, edit, confirm prompt artifacts.
- Modify: `geo_saas/web/src/components/agents/ContentPipelineModal.tsx`
  - Map new preflight values into task inputs and restore them on edit.
- Modify: `geo_saas/web/src/components/wizard/WizardShell.tsx`
  - Render step group labels from metadata without changing execution semantics.
- Modify: `geo_saas/web/src/i18n/locales/zh-CN/wizard.json`
  - Add Chinese copy for Reddit Research fields and states.
- Modify: `geo_saas/web/src/i18n/locales/en-US/wizard.json`
  - Add English copy for Reddit Research fields and states.
- Modify: `geo_admin/web/src/components/WizardConfigEditor.tsx`
  - Ensure new advanced JSON fields and step config remain visible.
- Add: `migrations/106_reddit_research_preflight_steps.sql`
  - Seed Reddit Research provider config keys, workflow steps, and Reddit template overrides.
- Add tests under `geo_agent/tests/` and frontend type checks under existing commands.

## Task 1: Backend Reddit Provider Contract

**Files:**
- Create: `geo_agent/src/services/reddit_research.py`
- Test: `geo_agent/tests/test_reddit_research.py`

- [ ] **Step 1: Add provider data models and config loader tests**

Create tests that construct fake config rows and assert:

```python
def test_web_grounded_config_can_run_without_reddit_api_credentials():
    cfg = build_reddit_research_config({
        "reddit_research_provider": "web_grounded",
        "reddit_web_fetch_enabled": "true",
        "reddit_grounding_model_id": "gemini-3-flash-preview",
        "reddit_research_fetch_user_agent": "AnswerX-GEO/1.0",
    })
    assert cfg.provider == "web_grounded"
    assert cfg.can_run is True

def test_reddit_api_config_requires_commercial_access():
    cfg = build_reddit_research_config({
        "reddit_research_provider": "reddit_api",
        "reddit_api_enabled": "true",
        "reddit_api_commercial_access_approved": "false",
        "reddit_api_client_id": "cid",
        "reddit_api_client_secret": "secret",
        "reddit_api_user_agent": "AnswerX/1.0",
    })
    assert cfg.can_run is False
    assert "commercial" in cfg.block_reason.lower()

def test_normalize_subreddit_name_accepts_common_forms():
    assert normalize_subreddit_name("r/robotvacuums") == "robotvacuums"
    assert normalize_subreddit_name("https://www.reddit.com/r/VideoEditing/") == "VideoEditing"
    assert normalize_subreddit_name("  artificial  ") == "artificial"
```

- [ ] **Step 2: Implement config parsing and subreddit normalization**

Implement:

```python
@dataclass(frozen=True)
class RedditResearchConfig:
    provider: Literal["web_grounded", "reddit_api"]
    web_fetch_enabled: bool
    grounding_model_id: str
    fetch_user_agent: str
    request_timeout_seconds: int
    max_subreddit_candidates: int
    max_posts_per_subreddit: int
    api_enabled: bool
    api_commercial_access_approved: bool
    client_id: str
    client_secret: str
    api_user_agent: str

    @property
    def can_run(self) -> bool:
        if self.provider == "web_grounded":
            return self.web_fetch_enabled and bool(self.grounding_model_id) and bool(self.fetch_user_agent)
        return (
            self.api_enabled
            and self.api_commercial_access_approved
            and bool(self.client_id)
            and bool(self.client_secret)
            and bool(self.api_user_agent)
        )
```

Add `block_reason` and pure helpers for value coercion.

- [ ] **Step 3: Add provider interface, web-grounded adapter, and PRAW adapter**

Define `RedditResearchProvider` with async methods:

```python
async def recommend_subreddits(self, context: RedditTargetingContext, limit: int) -> list[SubredditCandidate]: ...
async def resolve_subreddit(self, name: str) -> SubredditCandidate: ...
async def fetch_rules(self, name: str) -> list[SubredditRule]: ...
async def fetch_sidebar(self, name: str) -> str: ...
async def search_posts(self, name: str, query: str, limit: int) -> list[RedditPostEvidence]: ...
```

`WebGroundedRedditResearchProvider.recommend_subreddits` calls Gemini Search Grounding and requires source-backed subreddit URLs in the model output. `WebGroundedRedditResearchProvider.fetch_rules` first requests `https://www.reddit.com/r/{name}/about/rules.json`, then falls back to `about.json`, then to parsing the public `about/` page. It returns `rules_status="unavailable"` when rules cannot be verified.

Wrap blocking PRAW calls with `asyncio.to_thread`. Raise `RedditResearchConfigError` when the selected provider cannot run.

- [ ] **Step 4: Run backend tests**

Run:

```bash
python3 -m pytest geo_agent/tests/test_reddit_research.py -q
```

Expected: provider config, source normalization, and rules parsing tests pass.

## Task 2: Agent Preflight Routes

**Files:**
- Modify: `geo_agent/src/routers/tasks.py`
- Test: `geo_agent/tests/test_reddit_research_routes.py`

- [ ] **Step 1: Add route tests with mocked provider**

Cover:

```python
async def test_subreddit_targeting_manual_uses_provider_resolution(mock_provider):
    response = await client.post("/api/agent/tasks/content/subreddit-targeting/preview", json={
        "client_id": CLIENT_ID,
        "template_id": REDDIT_TEMPLATE_ID,
        "mode": "manual",
        "manual_subreddits": "r/robotvacuums\nVideoEditing",
        "inputs": {"topic_ids": [], "prompt_ids": []}
    })
    assert response.status_code == 200
    assert response.json()["status"] == "ready"
    assert response.json()["selected_subreddits"][0]["name"].startswith("r/")

async def test_reddit_discovery_requires_confirmed_targets(mock_provider):
    response = await client.post("/api/agent/tasks/content/reddit-discovery/preview", json={
        "client_id": CLIENT_ID,
        "template_id": REDDIT_TEMPLATE_ID,
        "subreddit_targeting": None,
        "inputs": {}
    })
    assert response.status_code == 400
```

- [ ] **Step 2: Implement request handlers**

Add endpoints:

```python
@router.post("/content/subreddit-targeting/preview")
async def preview_subreddit_targeting(...): ...

@router.post("/content/reddit-discovery/preview")
async def preview_reddit_discovery(...): ...

@router.post("/content/prompt-artifacts/preview")
async def preview_prompt_artifacts(...): ...
```

Use existing `_load_template_runtime_config_by_id` and `_load_brand_context_for_preview`.

- [ ] **Step 3: Reuse artifact preparation service logic**

Refactor current artifact helpers so the route and final pipeline call the same preparation function. Keep the function generic: it accepts template config and input payloads, not template names.

- [ ] **Step 4: Run route tests**

Run:

```bash
python3 -m pytest geo_agent/tests/test_reddit_research_routes.py -q
```

Expected: route tests pass with mocked provider.

## Task 3: Final Content Pipeline Reuse

**Files:**
- Modify: `geo_agent/src/pipelines/content_pipeline.py`
- Test: `geo_agent/tests/test_content_pipeline_options.py`

- [ ] **Step 1: Add tests for confirmed artifact reuse**

Add:

```python
def test_confirmed_prompt_artifacts_skip_runtime_preparation():
    inputs = {
        "derived_prompt_artifacts": {
            "status": "ready",
            "source": "wizard_confirmed",
            "prepared_json": {"community_brief": {"summary": "Use native Reddit tone."}},
            "rendered_sections": "## Community Brief\nUse native Reddit tone."
        },
        "derived_prompt_artifacts_source": "wizard_confirmed",
    }
    artifacts = resolve_confirmed_prompt_artifacts(inputs)
    assert artifacts["rendered_sections"].startswith("## Community Brief")
```

- [ ] **Step 2: Implement confirmed artifact resolver**

Add a pure resolver:

```python
def _resolve_confirmed_prompt_artifacts(inputs: dict[str, Any]) -> dict[str, Any] | None:
    artifacts = inputs.get("derived_prompt_artifacts")
    if not isinstance(artifacts, dict):
        return None
    source = inputs.get("derived_prompt_artifacts_source") or artifacts.get("source")
    if source != "wizard_confirmed":
        return None
    if artifacts.get("status") not in (None, "ready"):
        return None
    return artifacts
```

- [ ] **Step 3: Change content generation to reuse artifacts**

Before calling runtime artifact preparation, check `_resolve_confirmed_prompt_artifacts(inputs)`. If present, use it as `derived_prompt_artifacts`.

- [ ] **Step 4: Run focused pipeline tests**

Run:

```bash
python3 -m pytest geo_agent/tests/test_content_pipeline_options.py -q
```

Expected: existing content pipeline tests plus new reuse test pass.

## Task 4: Workflow Data Migration

**Files:**
- Add: `migrations/106_reddit_research_preflight_steps.sql`

- [ ] **Step 1: Seed Global Config keys**

Insert missing config keys:

```sql
INSERT INTO geo_global_config (key, value, description)
VALUES
  ('reddit_research_provider', 'web_grounded', 'Selected Reddit Research provider: web_grounded or reddit_api.'),
  ('reddit_web_fetch_enabled', 'true', 'Enable deterministic public web fetch for Reddit rules and about metadata.'),
  ('reddit_grounding_model_id', 'gemini-3-flash-preview', 'Gemini model used only for grounded subreddit candidate discovery.'),
  ('reddit_research_request_timeout_seconds', '20', 'Timeout for Reddit Research provider calls.'),
  ('reddit_research_fetch_user_agent', 'AnswerX-GEO/1.0', 'User agent for deterministic Reddit public web fetch.'),
  ('reddit_research_max_subreddit_candidates', '12', 'Maximum subreddit candidates returned by AI Recommend.'),
  ('reddit_research_max_posts_per_subreddit', '10', 'Maximum posts read per subreddit during Reddit Discovery.'),
  ('reddit_api_enabled', 'false', 'Enable approved Reddit API access for Reddit Research Wizard steps.'),
  ('reddit_api_commercial_access_approved', 'false', 'Set true only after Reddit grants commercial API permission.'),
  ('reddit_api_client_id', '', 'Reddit API OAuth client id.'),
  ('reddit_api_client_secret', '', 'Reddit API OAuth client secret.'),
  ('reddit_api_user_agent', 'AnswerX-GEO/1.0', 'Reddit API user agent string.')
ON CONFLICT (key) DO NOTHING;
```

- [ ] **Step 2: Seed workflow steps**

Upsert `geo_workflow_config` rows for:

- `subreddit_targeting`
- `reddit_discovery`
- `prompt_artifact_preparation`

Each row has `scope='content_generation'`, `config_type='workflow_step'`, `default_enabled=false`, group metadata `{key:"reddit_research",label:"Reddit Research"}`, and a custom field type matching the React component.

- [ ] **Step 3: Enable steps on Reddit templates**

Update templates where `name ILIKE '%reddit%'`, `defaults.content_type='reddit_article'`, `defaults.publish_platform='reddit'`, or `wizard_config.platform_profile='reddit'`.

Set:

```json
{
  "steps": {
    "subreddit_targeting": {"enabled": true},
    "reddit_discovery": {"enabled": true},
    "prompt_artifact_preparation": {"enabled": true}
  }
}
```

Keep existing `derived_prompt_artifacts`, `prompt_input_policy`, `ratf_rendering`, and `quality_gate` values intact.

- [ ] **Step 4: Validate migration in transaction**

Run:

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -f migrations/106_reddit_research_preflight_steps.sql
```

Expected: rows are inserted or updated without schema changes.

## Task 5: Frontend Custom Fields

**Files:**
- Modify: `geo_saas/web/src/components/wizard/schema.ts`
- Modify: `geo_saas/web/src/components/wizard/customFields/index.ts`
- Create: `geo_saas/web/src/components/wizard/customFields/SubredditTargetingPreflight.tsx`
- Create: `geo_saas/web/src/components/wizard/customFields/RedditDiscoveryPreflight.tsx`
- Create: `geo_saas/web/src/components/wizard/customFields/PromptArtifactPreparationPreflight.tsx`

- [ ] **Step 1: Register custom field types**

Extend `WizardFieldCustomType`:

```ts
| "subreddit_targeting_preflight"
| "reddit_discovery_preflight"
| "prompt_artifact_preparation_preflight"
```

Import each component in `customFields/index.ts`.

- [ ] **Step 2: Build Subreddit Targeting component**

Implement:

- mode toggle: AI Recommend / Manual Input
- keyword input
- manual subreddit textarea
- run button
- candidate result table
- selected subreddit checkboxes
- status badge
- error display

The component writes:

```ts
setFields?.({
  subreddit_targeting: result,
  reddit_discovery: undefined,
  reddit_discovery_preflight: { status: "stale" },
  derived_prompt_artifacts: undefined,
  prompt_artifact_preparation: { status: "stale" },
}, true)
```

- [ ] **Step 3: Build Reddit Discovery component**

Implement:

- block until `subreddit_targeting.status === "ready"`
- run button
- rules preview per subreddit
- community questions, objections, risks, and evidence URLs
- status badge
- stale state

- [ ] **Step 4: Build Prompt Artifact Preparation component**

Implement:

- block until `reddit_discovery.status === "ready"`
- generate button
- regenerate button
- editable JSON/Markdown panes
- confirm usage action
- writes `derived_prompt_artifacts_source="wizard_confirmed"`

- [ ] **Step 5: Run typecheck**

Run:

```bash
cd geo_saas/web && npm run typecheck
```

Expected: TypeScript passes.

## Task 6: Wizard Group Rendering

**Files:**
- Modify: `geo_saas/web/src/components/wizard/schema.ts`
- Modify: `geo_saas/web/src/components/wizard/resolveSteps.ts`
- Modify: `geo_saas/web/src/components/wizard/WizardShell.tsx`

- [ ] **Step 1: Add group metadata types**

Add optional group data to `WorkflowStepDefinition` and `ResolvedWizardStep`:

```ts
group?: {
  key: string;
  label: string;
  description?: string;
}
```

- [ ] **Step 2: Preserve group metadata in resolver**

Read `value.group` from workflow config and copy it into resolved steps.

- [ ] **Step 3: Render presentation-only group labels**

Update StepIndicator to show a compact group label before the first step in a group. The group has no effect on navigation or validation.

- [ ] **Step 4: Typecheck**

Run:

```bash
cd geo_saas/web && npm run typecheck
```

Expected: TypeScript passes.

## Task 7: Content Task Input Mapping

**Files:**
- Modify: `geo_saas/web/src/components/agents/ContentPipelineModal.tsx`

- [ ] **Step 1: Extend ContentTaskInputs**

Add:

```ts
subreddit_targeting?: Record<string, unknown> | null;
reddit_discovery?: Record<string, unknown> | null;
derived_prompt_artifacts?: Record<string, unknown> | null;
derived_prompt_artifacts_source?: string | null;
derived_prompt_artifacts_edited?: boolean;
```

- [ ] **Step 2: Map form state into task inputs**

In `buildTaskInputs`, include:

```ts
subreddit_targeting: (formState.subreddit_targeting as Record<string, unknown> | undefined) || null,
reddit_discovery: (formState.reddit_discovery as Record<string, unknown> | undefined) || null,
derived_prompt_artifacts: (formState.derived_prompt_artifacts as Record<string, unknown> | undefined) || null,
derived_prompt_artifacts_source: (formState.derived_prompt_artifacts_source as string | undefined) || null,
derived_prompt_artifacts_edited: Boolean(formState.derived_prompt_artifacts_edited),
```

- [ ] **Step 3: Restore existing task inputs on edit**

In `buildInitialValues`, restore each new field into the wizard form state.

- [ ] **Step 4: Typecheck**

Run:

```bash
cd geo_saas/web && npm run typecheck
```

Expected: TypeScript passes.

## Task 8: i18n Copy

**Files:**
- Modify: `geo_saas/web/src/i18n/locales/zh-CN/wizard.json`
- Modify: `geo_saas/web/src/i18n/locales/en-US/wizard.json`

- [ ] **Step 1: Add semantic keys**

Add keys under:

- `subredditTargeting`
- `redditDiscovery`
- `promptArtifactPreparation`
- `redditResearchGroup`

- [ ] **Step 2: Verify no hardcoded visible strings**

Run:

```bash
rg -n "Subreddit Targeting|Reddit Discovery|Artifact Preparation|AI Recommend|Manual Input" geo_saas/web/src --glob '*.tsx'
```

Expected: matches only code identifiers or i18n key references, not visible literal labels.

## Task 9: Admin Config Visibility

**Files:**
- Modify: `geo_admin/web/src/components/WizardConfigEditor.tsx`

- [ ] **Step 1: Verify advanced fields include new JSON**

Ensure the editor visibly exposes:

- `steps.subreddit_targeting`
- `steps.reddit_discovery`
- `steps.prompt_artifact_preparation`
- `derived_prompt_artifacts`
- `prompt_input_policy`

- [ ] **Step 2: Run Admin typecheck**

Run:

```bash
cd geo_admin/web && npm run typecheck
```

Expected: TypeScript passes.

## Task 10: Verification

**Files:**
- All files changed above

- [ ] **Step 1: Backend compile**

Run:

```bash
python3 -m py_compile geo_agent/src/services/reddit_research.py geo_agent/src/routers/tasks.py geo_agent/src/pipelines/content_pipeline.py
```

Expected: no compile errors.

- [ ] **Step 2: Backend tests**

Run:

```bash
python3 -m pytest geo_agent/tests/test_reddit_research.py geo_agent/tests/test_reddit_research_routes.py geo_agent/tests/test_content_pipeline_options.py -q
```

Expected: all selected tests pass.

- [ ] **Step 3: Frontend typechecks**

Run:

```bash
cd geo_saas/web && npm run typecheck
cd ../../geo_admin/web && npm run typecheck
```

Expected: both typechecks pass.

- [ ] **Step 4: Migration dry run**

Run in a transaction against local DB:

```bash
psql "$DATABASE_URL" -v ON_ERROR_STOP=1 -c "BEGIN;" -f migrations/106_reddit_research_preflight_steps.sql -c "ROLLBACK;"
```

Expected: migration applies inside transaction and rolls back cleanly.

- [ ] **Step 5: SaaS visible E2E**

Using `docs/local-dev/codex-visible-e2e.md`, verify:

- Reddit template shows Reddit Research group.
- Official Website template does not show Reddit Research group.
- `web_grounded` provider can recommend candidate subreddits when web fetch and grounding model config are enabled.
- `web_grounded` provider displays verified `rules.json` rules when available.
- Missing selected provider config disables run buttons with a configuration message.
- Confirmed artifacts are included in the created task inputs.

## Task 11: Deploy Script Update

**Files:**
- Modify: `deploy_all.sh`

- [ ] **Step 1: Identify changed modules**

Changed modules:

- `geo_agent`
- `geo_saas/web`
- `geo_admin/web`

- [ ] **Step 2: Increment changed module versions**

Increase:

- `AGENT_VERSION`
- `SAAS_WEB_VERSION`
- `ADMIN_WEB_VERSION`

- [ ] **Step 3: Keep deployment commands only for changed modules**

Comment image build and Terraform commands for unchanged modules. Keep deploy commands for Agent, SaaS Web, and Admin Web.

- [ ] **Step 4: Validate script syntax**

Run:

```bash
bash -n deploy_all.sh
```

Expected: no syntax errors.
