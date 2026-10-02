# Content Generation Quality Playbook

这份文档用于评价 AnswerX 内容生成结果，尤其是 Reddit 与官网文章。它补充 `docs/local-dev/codex-visible-e2e.md`：E2E runbook 负责“怎么跑流程”，本 playbook 负责“怎么判断内容质量和流程是否真的有效”。

## Core Principle

不要只相信 LLM reviewer 的分数。评价内容生成质量时，必须同时看：

1. 中间过程是否真实生成并被带入后续节点。
2. Quality Gate 是否准确识别问题。
3. Revise 是否真实修复问题，而不是只改变状态。
4. 最终文章是否适合目标平台发布。
5. 最终文章是否能提升 GEO visibility。

## Required Evidence Before Evaluation

评价一篇生成文章前，先收集这些证据：

- `workflow_steps`
- `citation_analysis_result`
- `citation_analysis_summary_markdown`
- `strategy`
- `content_markdown`
- `pre_revision_quality_review`
- `quality_review`
- `revision_metadata`
- `status_logs`

如果只看最终正文，不足以判断系统是否工作正常。

## Process Quality Checklist

### 1. Citation Analysis

检查 Citation Analysis 是否输出并被后续使用：

- Brand Mention Triage 是否包含 `unmentioned`、`positive_neutral`、`negative_misleading`、`ambiguous`。
- Content Action Decision 是否清楚，例如 `new_content_gap`、`refresh_existing_asset`、`clarification_or_rebuttal`。
- Citation Grounded Brief 是否包含：
  - Why AI likely cites these sources
  - Gaps to fill for customer GEO visibility
  - Top cited source patterns
- Reddit citation fetch 是否避免只抓到 `Please wait for verification`。
- 官网 citation 是否抓到 title、canonical URL、正文摘要、meta description 或可用页面内容。

判断标准：

- 好：文章明显学习了已被 AI 引用内容的结构优势，并补足客户品牌缺失。
- 差：Citation 只作为日志存在，正文没有体现 source patterns 或 GEO gaps。

### 2. Strategy Generation

策略必须是人类可读的策略说明，不应该直接显示 raw JSON。

检查：

- 是否整合了用户选择、Discover、Citation Analysis、模板配置。
- 是否说明目标平台、目标受众、核心角度、风险控制。
- Reddit 策略是否强调社区语气、争论点、保守表达。
- 官网策略是否强调 Direct Answer、Brand Fit、Feature-to-Benefit、FAQ extractability。

如果 `strategy` 字段仍是 JSON envelope，应记录为流程问题，即使最终文章质量尚可。

### 3. Quality Gate

Quality Gate 不应该只给高分。它必须能识别阻断项。

强制关注：

- Overall score 是否低于模板阈值。
- 是否识别重复 FAQ、重复 Conclusion、残缺句、重复结尾。
- 是否识别结构性错误，例如多个 FAQ section、Direct Answer 重复、Final Thoughts 与 Conclusion 并存。
- 官网是否识别品牌密度过高。
- Reddit 是否识别硬广、标题 SEO 化、Brand Fit Summary 标题机械化。
- Citation Alignment 是否检查正文是否回应 Citation gap。

判断标准：

- 好：Gate 发现的问题和人工观察一致。
- 差：文章明显有问题，但 Gate 仍给 9 或 10 且没有 warning/failure。

### 4. Revise And Recheck

Revise 是否有效，不能只看 `status = revised`。

必须检查：

- `pre_revision_quality_review` 是否保留修订前问题。
- 最终 `quality_review` 是否对应修订后的正文。
- `revision_metadata.attempt_count` 是否真实反映修订次数。
- 第一轮 Revise 是否修结构和主要 blocker。
- 第二轮 Revise 如执行，是否修残缺句、重复 FAQ、重复 Conclusion、品牌密度等残留问题。
- 未执行的第二轮是否显示为 `skipped`，不要误显示成已执行。

判断标准：

- 好：修订前 failure 在最终正文中被真正修复，最终 review 不残留旧问题。
- 差：状态变成 passed/revised，但 final review 或正文仍保留旧 blocker。

## Reddit Article Evaluation

Reddit 文章的目标不是官网转化页，而是社区原生、可信、可被 AI 引用的经验型内容。

### Platform Fit

高质量 Reddit 文章应具备：

- 标题自然，像真实社区帖，不像 SEO 标题。
- 第一人称或 field-notes 视角。
- 有明确争论点或 trade-off。
- 承认限制，不做过度确定性判断。
- 品牌出现少而准，像 workflow fit，不像广告。
- 结尾有自然讨论问题。

扣分项：

- 标题像 `The Best X in 2026: Ultimate Guide`。
- 机械出现 `Brand Fit Summary` 作为公开小节标题。
- 频繁重复品牌名。
- 过度夸大、缺少限制和反方观点。
- FAQ 像官网 schema，而不是社区问答。

### GEO Visibility

Reddit 文章对 GEO visibility 的价值来自：

- 能被 AI 当作第三方社区观点引用。
- 回答具体长尾问题。
- 有清晰可抽取的 workflow、checklist、trade-off。
- 自然补上客户品牌在已引用 Reddit 来源中的缺席。

高分信号：

- 明确回答用户问题，但不是硬推品牌。
- 使用可引用的中立表述，例如 “where I would use X”。
- 对竞品/工具类别有合理比较。
- 有足够上下文让 AI 理解品牌适用场景。

## Official Website Article Evaluation

官网文章的目标是可发布、可索引、可抽取、可转化。

### Publishability

高质量官网文章应具备：

- 开头 120-180 词内有 Direct Answer。
- Brand Fit Summary 清楚解释品牌为什么适合这个场景。
- Value / Dream / Mini-benefits 明确。
- Feature-to-Benefit Mapping 表格可读。
- Related Resources 是读者资源区，不是后台编辑建议。
- FAQ 可以被 AEO/GEO 抽取。
- 语气可信、克制、品牌专业。

扣分项：

- 绝对化表达，例如 `ultimate`、`definitive`、`guaranteed`。
- 无来源数字、结果承诺、算法承诺。
- 竞品版本或能力未经核验却写得很确定。
- `Internal Linking Suggestions`、`Insert URL` 等编辑痕迹外露。
- 品牌名刷屏。
- Direct Answer 或 FAQ 重复。

### GEO Visibility

官网文章对 GEO visibility 的价值来自：

- 清楚告诉 AI：品牌是什么、适合谁、解决什么场景。
- 将 feature 映射到 creator / marketer / agency 的实际 benefit。
- 提供 FAQ-ready answers。
- 提供内部链接和相关资源，帮助 AI 建立站内语义图谱。
- 使用 Citation data 补足已被 AI 引用来源中缺失的品牌信息。

高分信号：

- AI 可以直接抽取一句话答案。
- Brand Fit Summary 和 Feature-to-Benefit table 信息密度高。
- Related Resources 使用真实 URL。
- 对限制、适用边界、事实不确定性有保守表达。

## Suggested Scoring

每篇文章建议人工给两个分数：

| 维度 | 说明 |
| --- | --- |
| Platform Fit | 是否适合目标平台发布 |
| GEO Visibility Lift | 是否明显提升 AI 引用与品牌可见性 |

建议评分解释：

- `9.0-10`: 可直接发布，仅需轻微编辑。
- `8.0-8.9`: 基本可发布，有少量表达或结构优化空间。
- `7.0-7.9`: 方向正确，但需要人工编辑后发布。
- `<7.0`: 不建议发布，应进入人工复核或重新生成。

## Evaluation Output Format

最终评价建议使用这个格式：

```text
Task: <task_id>
Template: <template_name>
Status: <completed / failed / needs_review>

Process Quality:
- Citation Analysis:
- Strategy:
- Quality Gate:
- Revise:

Article Quality:
- Platform Fit: x/10
- GEO Visibility Lift: x/10
- Overall: x/10

Key Strengths:
- ...

Key Issues:
- ...

Recommendation:
- Publish / Publish after light edit / Needs human review / Regenerate
```

## Known Watch Items

- Strategy output still needs a hard guard against raw JSON display.
- Reddit API/PRAW fallback remains a future improvement for Reddit citation fetch reliability.
- Citation Alignment should evolve from keyword matching to evidence-based evaluation.
- A mock/integration test should force second-round Revise execution and second recheck coverage.
