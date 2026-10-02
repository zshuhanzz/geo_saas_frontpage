# Reddit Research Preflight Design

## Purpose

Reddit content generation needs a visible, configurable research flow before final content execution. The current runtime-only Artifact Preparation substage hides the most important Reddit-native writing inputs from the user and makes it hard to control subreddit fit, community rules, and final prompt artifacts.

This design makes Reddit research an explicit Wizard UI group named **Reddit Research**. The group contains three independent, configuration-driven steps:

1. **Subreddit Targeting**
2. **Reddit Discovery**
3. **Artifact Preparation**

The flow is enabled only by template data. The Wizard engine remains generic and does not contain Reddit-specific branching.

## Non-Negotiable Boundaries

- Reddit behavior is not hardcoded into the Wizard shell, task engine, or generic field renderer.
- Non-Reddit templates do not see, run, or depend on Reddit Research steps unless their template data enables them.
- Reddit Research uses a provider abstraction with two concrete providers: `web_grounded` and `reddit_api`.
- `web_grounded` uses Gemini Search Grounding only for subreddit candidate discovery, then uses deterministic web fetch for subreddit metadata and rules. It never lets the model invent subreddit rules.
- `reddit_api` uses approved Reddit API access and is gated by explicit Admin configuration and Reddit commercial permission.
- Artifact Preparation for Reddit does not depend on Official Website Discovery.
- Final Content Generation reuses confirmed Wizard artifacts and does not regenerate them during execution.
- Legacy and API-created tasks without confirmed artifacts remain executable through an explicit compatibility branch controlled by template configuration.

## Provider and Compliance Position

Reddit states that commercial use of developer tools and services requires permission and may require a contract. The product is a commercial SaaS product, so Reddit API features must stay disabled until the company has Reddit-approved commercial access and valid API credentials.

The default provider is `web_grounded` because commercial Reddit API approval may not be available immediately. This provider uses Google Search Grounding to recommend candidate communities and deterministic Reddit public web endpoints to verify facts. It does not access Reddit API credentials and does not present generated text as subreddit rules.

The approved-API provider is `reddit_api`. It remains available in the same interface and becomes selectable after commercial access is approved and credentials are configured.

The system must not silently fabricate Reddit data. If a provider cannot verify subreddit rules, it returns `rules_status="unavailable"` and the UI requires manual review, manual paste, or a confirmed skip.

## Provider Capabilities Required

The implementation uses a provider abstraction. `web_grounded` uses the existing Gemini SDK plus deterministic HTTP fetch. `reddit_api` uses a PRAW-compatible adapter or direct OAuth-backed HTTP client.

Required configuration lives on each Reddit template under `wizard_config.reddit_research`, not in global settings:

- `provider`
- `provider_config.web_grounded.web_fetch_enabled`
- `provider_config.web_grounded.grounding_model_id`
- `provider_config.web_grounded.request_timeout_seconds`
- `provider_config.web_grounded.fetch_user_agent`
- `provider_config.web_grounded.max_subreddit_candidates`
- `provider_config.web_grounded.max_posts_per_subreddit`

`reddit_api` configuration is also template-scoped when enabled in the future. It is not seeded into global settings because Reddit API commercial access and credentials are not part of the current runnable path.

Required provider operations:

- Search subreddit candidates from keywords and topic/prompt context.
- Resolve manually entered subreddit names.
- Fetch subreddit metadata.
- Fetch subreddit rules.
- Fetch subreddit sidebar/about text when available.
- Search posts within selected subreddits.
- Return normalized source URLs and metadata.

Provider endpoints and fetch targets represented by the interface:

`web_grounded`:

- Gemini Search Grounding query for candidate subreddit discovery.
- `https://www.reddit.com/r/{subreddit}/about/rules.json`
- `https://www.reddit.com/r/{subreddit}/about.json`
- `https://www.reddit.com/r/{subreddit}/about/`

`reddit_api`:

- `/subreddits/search`
- `/api/search_reddit_names`
- `/r/{subreddit}/about`
- `/r/{subreddit}/about/rules`
- `/r/{subreddit}/sidebar`
- `/r/{subreddit}/search`

## Workflow Shape

### Visual Grouping

The Wizard step indicator groups steps 4-6 under **Reddit Research**. The underlying steps remain independent so each step can define its own field type, output, stale detection, and validation.

Suggested Reddit template order:

1. Content basics
2. Prompt and topic selection
3. Citation Analysis
4. Subreddit Targeting
5. Reddit Discovery
6. Artifact Preparation
7. Strategy
8. Generation Config
9. Confirm Execute

The exact ordering is owned by `geo_workflow_config.value.num` plus `template.wizard_config.steps[*].__sort_override`.

### Step 1: Subreddit Targeting

Purpose: determine which subreddit communities the article should target.

Supported modes:

- **AI Recommend**: uses the selected provider to discover and rank candidates from prior Wizard inputs. With `web_grounded`, Gemini Search Grounding recommends candidates and deterministic fetch verifies each selected subreddit. With `reddit_api`, Reddit API search provides candidates and metadata.
- **Manual Input**: user enters subreddit names and the selected provider validates and enriches them.

Inputs:

- `client_id`
- `template_id`
- selected topic IDs
- selected prompt IDs
- Citation Analysis result
- content type
- brand context
- user keywords
- manual subreddit names

Outputs:

```json
{
  "status": "ready",
  "mode": "ai_recommend",
  "selected_subreddits": [
    {
      "name": "r/example",
      "display_name": "example",
      "title": "Example",
      "public_description": "Short public description",
      "subscribers": 123456,
      "over18": false,
      "subreddit_type": "public",
      "relevance_reason": "Why this subreddit fits the selected topic and prompts",
      "posting_risk": "Rule or culture risk",
      "confidence": 0.82,
      "source": "web_grounded"
    }
  ],
  "candidate_subreddits": [],
  "generated_at": "ISO-8601",
  "fingerprint": "stable hash"
}
```

Stale when any of these fields changes:

- selected topic IDs
- selected prompt IDs
- Citation Analysis fingerprint
- content type
- manual subreddit input
- user keyword input

### Step 2: Reddit Discovery

Purpose: collect research evidence for the confirmed subreddit targets.

This is a research-material step. It does not create final writing rules and does not produce final prompt artifacts.

Inputs:

- confirmed Subreddit Targeting output
- selected topic IDs
- selected prompt IDs
- Citation Analysis result
- content type
- brand context

Outputs:

```json
{
  "status": "ready",
  "subreddits": [
    {
      "name": "r/example",
      "rules_status": "verified",
      "rules_source_url": "https://www.reddit.com/r/example/about/rules.json",
      "rules": [
        {
          "short_name": "No self-promotion",
          "description": "Rule description",
          "kind": "link"
        }
      ],
      "sidebar_summary": "Community sidebar/about summary",
      "community_questions": [],
      "objections": [],
      "competitor_signals": [],
      "content_angles": [],
      "risks": [],
      "source_urls": []
    }
  ],
  "generated_at": "ISO-8601",
  "fingerprint": "stable hash"
}
```

Stale when Subreddit Targeting output changes or Citation Analysis fingerprint changes.

### Step 3: Artifact Preparation

Purpose: transform confirmed Reddit research into final writing instructions and compact prompt artifacts.

This is a writing-instruction step. It uses template-configured artifact declarations and can generate:

- Subreddit Community Rules
- Experience Style Notes
- Community Brief
- other declared artifacts in `derived_prompt_artifacts.output_artifacts`

Inputs:

- confirmed Subreddit Targeting output
- confirmed Reddit Discovery output
- strategy
- selected topic IDs
- selected prompt IDs
- Citation Analysis result
- brand context
- template `derived_prompt_artifacts`
- template `prompt_input_policy`

Outputs:

```json
{
  "status": "ready",
  "prepared_json": {
    "subreddit_community_rules": {},
    "experience_style_notes": {},
    "community_brief": {}
  },
  "rendered_sections": "Markdown sections injected into final content prompt",
  "source": "wizard_confirmed",
  "edited": false,
  "generated_at": "ISO-8601",
  "fingerprint": "stable hash"
}
```

User actions:

- Generate artifacts
- Regenerate artifacts
- Edit generated artifacts
- Confirm artifact usage

Stale when Reddit Discovery output, Strategy output, selected prompts, selected topics, or Citation Analysis fingerprint changes.

## Data Contract

Final task inputs include:

```json
{
  "subreddit_targeting": {},
  "reddit_discovery": {},
  "derived_prompt_artifacts": {},
  "derived_prompt_artifacts_source": "wizard_confirmed",
  "derived_prompt_artifacts_edited": false
}
```

`step_content_generation` reads `derived_prompt_artifacts` from task inputs. When source is `wizard_confirmed`, it injects the confirmed artifacts and skips runtime artifact generation.

## Admin Configuration

### Global Config

Admin Global Config must expose Reddit API configuration values. Secret values should be write-only in the UI and masked on read.

### Template Config

Admin Template Edit must expose all JSON fields involved in the flow:

- `steps.subreddit_targeting`
- `steps.reddit_discovery`
- `steps.prompt_artifact_preparation`
- `prompt_input_policy`
- `derived_prompt_artifacts`
- `ratf_rendering`
- `reddit_native_contract`
- `quality_gate`

The existing full JSON editor remains available so every template-owned configuration field is editable.

## Backend Architecture

### Provider Layer

Create a provider module with a stable interface:

```python
class RedditResearchProvider:
    async def search_subreddits(self, query: str, limit: int) -> list[SubredditCandidate]: ...
    async def resolve_subreddit(self, name: str) -> SubredditCandidate: ...
    async def fetch_rules(self, name: str) -> list[SubredditRule]: ...
    async def fetch_sidebar(self, name: str) -> str: ...
    async def search_posts(self, name: str, query: str, limit: int) -> list[RedditPostEvidence]: ...
```

The implementation loads provider settings from the selected template runtime config, with legacy global settings only as a compatibility fallback. `reddit_api` refuses to run when commercial access is not enabled. `web_grounded` refuses to run when web fetch is disabled or no grounding model is configured.

### API Routes

Add three Wizard preflight endpoints:

- `POST /api/agent/tasks/content/subreddit-targeting/preview`
- `POST /api/agent/tasks/content/reddit-discovery/preview`
- `POST /api/agent/tasks/content/prompt-artifacts/preview`

Each endpoint:

- requires authenticated user context
- checks tenant scope through `client_id`
- loads template runtime config
- validates required previous-step inputs
- returns normalized JSON with `status`, `generated_at`, and `fingerprint`

### Content Pipeline

`step_content_generation` changes behavior:

- If confirmed artifacts are present, reuse them.
- If confirmed artifacts are absent and template config allows runtime compatibility, generate internally.
- If confirmed artifacts are absent and template config requires Wizard confirmation, fail the task with a clear error.

## Frontend Architecture

Create three custom field components:

- `SubredditTargetingPreflight`
- `RedditDiscoveryPreflight`
- `PromptArtifactPreparationPreflight`

Each component follows the existing Citation Analysis Preflight pattern:

- run button
- loading state
- ready state
- stale state
- error state
- compact preview
- regenerate action
- bulk `setFields` for hidden result payloads

Wizard Shell remains generic. It only reads grouping metadata and renders grouped labels in the step indicator.

## Grouping Model

Workflow step values may include:

```json
{
  "group": {
    "key": "reddit_research",
    "label": "Reddit Research",
    "description": "Subreddit targeting, discovery, and prompt artifacts"
  }
}
```

The group metadata is presentation-only. It does not affect dependency logic or backend execution.

## Error Handling

- Missing selected provider config: show configuration error and block run.
- Commercial access disabled for `reddit_api`: show compliance gate and block run.
- Web fetch disabled for `web_grounded`: show configuration gate and block run.
- Invalid subreddit: show per-subreddit validation failure.
- Private, banned, quarantined, or inaccessible subreddit: show status and exclude by default.
- Rate limit: show retry-after information if available.
- API timeout: show retryable error.
- Stale upstream input: show stale badge and require regeneration before final execution.

## Quality and Safety

- Never invent subreddit rules, subscriber counts, post URLs, comments, vote counts, or community norms.
- Rules must come from deterministic provider evidence. For `web_grounded`, accepted rule evidence is `about/rules.json`, `about.json`, or a parsed public `about/` page. For `reddit_api`, accepted rule evidence is `about/rules`.
- Gemini Search Grounding may recommend candidate communities, but it must not be treated as the source of truth for subreddit rules.
- Evidence URLs must be returned by the selected provider or omitted.
- Artifact Preparation may transform evidence into writing guidance, but must label style notes as writing guidance rather than product facts.
- Content generation must not publish Reddit API raw data directly unless template policy permits it.

## Testing Requirements

Backend tests:

- provider config refuses to run when the selected provider is not runnable
- manual subreddit input normalizes names
- AI recommend returns grounded candidates and marks their source
- rules fetch maps deterministic web JSON/HTML or API data into normalized schema
- Discovery requires confirmed subreddit targets
- Artifact Preparation requires confirmed Discovery output
- Content Generation skips runtime artifact generation when confirmed artifacts exist

Frontend tests:

- Reddit steps appear only when template config enables them
- Non-Reddit templates remain unchanged
- Subreddit Targeting supports AI Recommend and Manual Input
- Discovery blocks until targets are confirmed
- Artifact Preparation blocks until Discovery is ready
- Stale state appears when upstream fields change
- Final submitted task inputs include confirmed artifacts

Manual E2E:

- Reddit template with configured `web_grounded` can run all three preflight steps and final generation reuses artifacts
- Reddit template with configured `reddit_api` can run all three preflight steps and final generation reuses artifacts
- Reddit template with missing selected provider config shows disabled run actions
- Official Website template does not show Reddit Research steps

## Deployment Notes

The implementation requires:

- Agent API deployment
- SaaS Web deployment
- optional Admin Web deployment for expanded config editing
- database migration for workflow step rows and Reddit template configuration

No Cloud SQL schema change is required unless encrypted secret storage is introduced for Reddit API credentials. If secret handling remains in the existing Global Config table, the migration only seeds config keys and workflow/template JSON.
