# Codex Visible E2E 本地测试指南

这份文档记录 Codex 在本机可视化浏览器里跑 AnswerX 内容生成 E2E 的推荐方式。目标是覆盖前端、SaaS API、Agent API、Cloud SQL 数据和内容 pipeline，而不是只跑无头单元测试。

生成完成后的文章质量评价，请同时参考 `docs/content-generation-quality-playbook.md`。

## Codex Session Rules

- 开始本地可视化 E2E 前，先确认当前 Session 读过本文件和仓库根目录的 `AGENTS.md`。
- 浏览器测试使用用户自己的账号：`gotyechen@gmail.com`。
- 不使用 dev client、Claude client、`CLAUDE.md` 中的测试客户或其他 mock/demo 客户，除非用户明确要求。
- Admin UI 固定使用 `http://localhost:6173`。
- SaaS UI 固定使用 `http://localhost:6174`。
- 不再使用 `6175` 做 Codex E2E；该端口没有稳定纳入 Google OAuth Authorized JavaScript Origins。
- 任何需要登录的页面，优先使用“使用 Google 账号登录”，并确认登录后账号是 `gotyechen@gmail.com`。
- 不能机械点击 Wizard。只要页面仍有 Loading、Discover 正在跑、Prompt/Topic/Strategy/Citation Analysis 正在生成，就必须等待完成后再进入下一步。
- 如果前序步骤没有等完就误点到后续步骤，本次 E2E 结果不可信，应重新开始该模板流程，而不是继续往后走。

## 推荐端口

| 服务 | Codex E2E 端口 | 说明 |
| --- | ---: | --- |
| `geo_saas/src` | `9101` | SaaS API |
| `geo_agent/src` | `9102` | Agent API |
| `geo_admin/web` | `6173` | Admin UI，配置模板 / Wizard Stack |
| `geo_saas/web` | `6174` | SaaS UI，内容 Agent E2E 入口 |
| Cloud SQL Auth Proxy | `5432` | 连接 Cloud SQL；本地 E2E 默认复用线上结构数据 |

## 环境文件

前端 E2E 使用：

```bash
geo_saas/web/.env.e2e.local
```

推荐内容：

```bash
VITE_GOOGLE_CLIENT_ID=414105678919-l45o3auq8bps4foet1nrlgd1692a2due.apps.googleusercontent.com
VITE_DEV_PORT=6174
VITE_SAAS_API_PROXY=http://localhost:9101
VITE_AGENT_API_PROXY=http://localhost:9102
VITE_DEV_AUTH_USER_EMAIL=gotyechen@gmail.com
VITE_DEV_AUTH_USER_NAME=lancelot
VITE_DEV_AUTH_USER_SUB=e2e-dev-sub-001
```

后端继续使用各自模块里的 `.env.local`，但启动时显式指定端口。

## 启动顺序

1. 启动 Cloud SQL Auth Proxy。

```bash
./cloud-sql-proxy project-90d7849c-de16-4c15-a0a:us-central1:answer-x-geo-instance --port=5432
```

2. 启动 SaaS API。

```bash
cd /Users/lancelot/Desktop/GEO_Demo/geo_saas/src
uvicorn main:app --reload --port 9101 --env-file .env.local
```

3. 启动 Agent API。

```bash
cd /Users/lancelot/Desktop/GEO_Demo/geo_agent/src
uvicorn main:app --reload --port 9102 --env-file .env.local
```

4. 启动 SaaS Web。

```bash
cd /Users/lancelot/Desktop/GEO_Demo/geo_saas/web
npm run dev -- --mode e2e
```

打开：

```text
http://localhost:6174/agents/content
```

## 内容生成 E2E Checklist

### 通用等待规则

每个 Wizard Step 都必须按下面顺序判断：

1. 页面字段是否已经渲染完成。
2. Prompt、Topic、Data Scope、Discover 结果是否已完成 hydration。
3. 如果该页有运行按钮，例如 Reddit Discover、Official Website Discover、Citation Analysis、Strategy Generate，必须点击运行并等待结果完整出现。
4. 中间结果出现后，先做简短质量判断，再点击 Next。
5. 如果页面没有任何需要填写或运行的内容，并且没有 Loading，可以继续。
6. 最后 Confirm 页提交前，确认模型选择正确，并按用户要求开启 Search Grounding。

### 中间节点质量检查

每次完整 E2E 至少检查这些节点是否生成合理，并确认最终内容是否吸收了它们：

- **Data Scope / Prompt / Topics**：是否加载出真实候选项；是否与用户目标相关。
- **Reddit Discover**：subreddit、关键词或 Reddit URL 是否填在正确位置；结果是否能反映社区问题、反对意见、竞品和发布风险。
- **Official Website Discover**：用户给定官网 URL 是否逐行填入；结果是否能抽取 use case、品牌术语、产品能力、内部链接机会。
- **Citation Analysis**：必须展示 Brand Mention Triage、Content Action Decision、Citation Grounded Brief、high-citation source patterns、`Why AI likely cites these sources`、`Gaps to fill for customer GEO visibility`、fetch status。
- **Strategy Generation**：必须是人类可读策略，不允许直接显示大 JSON；策略应整合 Discover、Citation、用户选择和模板要求。
- **Content Generation**：正文应体现策略和 Citation gaps，不应只重复模板口号。
- **Quality Gate**：检查 status、score、failures、warnings、blockers 是否与内容问题一致。
- **Revise / Recheck**：如果进入 Revise，确认 `pre_revision_quality_review` 保存修订前问题，最终 `quality_review` 对应修订后内容；未执行的第二轮应显示 `skipped`。

### Reddit AI Citable Post Generator

1. 打开 Content Agent。
2. 选择 `Reddit AI Citable Post Generator`。
3. 使用 `AI 帮我发现` 或手动选择 prompt/topic；等待候选 prompt/topic 完整加载。
4. 到 Reddit Discover 步骤，按用户要求填写 subreddit，例如：
   ```text
   r/aivideo,r/ArtificialInteligence
   ```
5. 点击 Discover 运行按钮，等待 Reddit discover 结果完成；不要在结果为空或仍 loading 时继续。
6. 到 `Citation Analysis` 步骤。
7. 确认 source scope 为 `reddit_citations`，include domains 通常为 `reddit.com`。
8. 点击 `Run Citation Analysis`。
9. 检查页面是否展示：
   - Brand mention summary / triage counts: unmentioned, positive, neutral, negative, misleading, ambiguous
   - Primary content action
   - Top cited source patterns
   - Why AI likely cites these sources
   - Gaps to fill for customer GEO visibility
   - Citation fetch status，尤其 Reddit URL 是否使用 `reddit_json_fetched` 或其他可用 fallback，不能只抓到 `Please wait for verification`
10. 到策略步骤，点击生成并等待完成；确认策略生成已经吸收 Citation brief，且不是 raw JSON。
11. 到 Confirm，确认执行流程显示：
   - Citation Analysis
   - Strategy Generation
   - Content Generation
   - Quality Gate
   - 第一轮 Revise
   - 修订后复查
   - 第二轮 Revise
   - 第二轮后复查
12. 执行任务后，在任务详情中检查：
   - `citation_analysis_result`
   - `citation_analysis_summary_markdown`
   - `quality_review.quality_gate.status`
   - `revision_metadata`
   - 第二轮未执行时 workflow step 是否是 `skipped`

#### Reddit 最终文章评价标准

- Reddit 标题必须是自然社区标题，不应像官网 SEO 标题。
- 文章可以有 Brand Fit 的内部目标，但公开小节标题要自然，例如 `Where Dreamina actually fits in this workflow`，不要机械显示 `Brand Fit Summary`。
- 保持个人视角、field-notes、trade-off、争论点和保守表达。
- 品牌提及要少而准，不能硬广。
- FAQ 如出现，必须社区化，不能重复，也不能像官网 FAQ schema 堆砌。
- 不能强制露出 RAFT / IATF / Citation Analysis / GEO visibility 等内部术语。

### Official Website AI Citable Article

流程同上，但 Citation Analysis 默认参考 `official_article_citations`，并排除 `youtube.com, instagram.com, tiktok.com`。

用户要求填入参考官网时，Website 字段使用换行分隔，例如：

```text
https://dreamina.capcut.com/ai-video/what-is-text-to-video
https://dreamina.capcut.com/ai-video/what-is-ai-video-generator
https://dreamina.capcut.com/resource/how-to-use-happy-horse-1-0
```

最终正文重点检查：

- Direct Answer
- Brand Fit Summary
- Value / Dream / Mini-benefits
- Feature-to-Benefit Mapping
- Related Resources / natural internal links，不能保留裸露的 `Internal Linking Suggestions` 编辑指南
- FAQ-friendly extractable answers
- 保守竞品对比与事实核验表达
- Brand density 合理；既要可抽取品牌，也不能刷屏
- Citation gaps 是否被正文自然补齐

#### 官网最终文章评价标准

- 适合官网直接发布：可信、克制、结构完整，没有后台编辑痕迹。
- Direct Answer 应该在开头明确回答核心查询，但避免重复出现。
- Brand Fit Summary、Feature-to-Benefit Mapping、Value/Dream/Mini-benefits 必须明确、可抽取。
- Related Resources 应该像读者资源区，而不是 SEO 操作清单。
- FAQ 要利于 AEO/GEO 抽取，但不能重复、残缺或过度营销。
- 避免 `ultimate`、`definitive`、`guaranteed`、`viral-ready`、`algorithm-ready` 等无证据强断言。

## 内容生成 Debug Checklist

当用户要求评价新生成文章或排查 Quality Gate / Revise 时，按这个顺序检查：

1. 查任务状态、模板名、模型、Search Grounding 是否开启。
2. 查 `workflow_steps`，确认 Citation、Strategy、Content、Quality Gate、两轮 Revise/Recheck 的状态是否准确，未执行分支是否为 `skipped`。
3. 查 `citation_analysis_result` 和 `citation_analysis_summary_markdown`，确认是否有可用 fetch 内容、source patterns 和 GEO gaps。
4. 查 strategy 文本，确认不是 JSON，且吸收了 Discover 和 Citation。
5. 查初稿、`pre_revision_quality_review`、最终 `quality_review`、`revision_metadata`。
6. 对最终文章单独人工评分，不要只相信 LLM reviewer 的分数。
7. 如果二轮 revise 后仍未通过，状态应进入 `Needs Human Review` 或明确提示人工复核风险。

## 数据库快速检查

本地默认数据库连接：

```bash
psql 'postgresql://answer-x-geo-db-user:answer-x-geo-db-user-123@localhost:5432/answer-x-geo-db'
```

检查最近内容任务：

```sql
SELECT id, status, current_step, created_at, completed_at
FROM geo_agent_tasks
WHERE task_type = 'content_generation'
ORDER BY created_at DESC
LIMIT 10;
```

检查 workflow steps / Quality Gate / Revise 元数据：

```sql
SELECT
  id,
  output->'workflow_steps' AS workflow_steps,
  output->'quality_review'->'quality_gate' AS final_quality_gate,
  output->'pre_revision_quality_review'->'quality_gate' AS pre_revision_quality_gate,
  output->'revision_metadata' AS revision_metadata
FROM geo_agent_tasks
WHERE id = '<task_id>';
```

检查 Citation Analysis 和 Strategy 是否进入任务输出：

```sql
SELECT
  output->'citation_analysis_result' AS citation_analysis_result,
  output->>'citation_analysis_summary_markdown' AS citation_analysis_summary,
  output->>'strategy' AS strategy
FROM geo_agent_tasks
WHERE id = '<task_id>';
```

## 常见问题

### `curl localhost` 报 `Operation not permitted`

Codex shell sandbox 有时会拦截本地端口连接。用于读取本机 API 状态时，使用 tool escalation 允许 `curl` 即可。

### 页面能生成内容，但步骤没有显示 Citation Analysis

检查数据库是否已执行最新 migration：

```sql
SELECT value->'fields'
FROM geo_workflow_config
WHERE scope = 'content_generation'
  AND config_type = 'workflow_step'
  AND key = 'citation_analysis';
```

应看到 `citation_analysis_preflight` 自定义字段。

### Confirm 里没有 5 个执行步骤

检查 Agent API 当前代码的 `CONTENT_WORKFLOW_STEPS` 是否包含 8 步语义：

```text
citation_analysis
strategy_generation
content_generation
quality_gate
revise_round_1
quality_recheck_round_1
revise_round_2
quality_recheck_round_2
```

如果真实任务没有进入第二轮 revise，第二轮相关步骤应显示 `skipped`，不要显示成已执行。

### 前端连错后端

确认 `geo_saas/web/.env.e2e.local`：

```bash
VITE_SAAS_API_PROXY=http://localhost:9101
VITE_AGENT_API_PROXY=http://localhost:9102
```

然后重启 Vite。
