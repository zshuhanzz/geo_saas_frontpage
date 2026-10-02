import { Target, TrendingUp, MessageSquare, Shield } from "lucide-react";
import type {
  ContentTypeDef,
  DomainKey,
  SortKey,
  ContentGoal,
  GoalDictKey,
  ContentGoalDef,
  ContentDepth,
  RaftCategoryKey,
} from "./types";

// ─── Constants ──────────────────────────────────────────────────────
//
// Label / description text is intentionally omitted from these module-level
// arrays — it's resolved at render time from content.json so both zh and en
// modes render correctly. Only IDs, icons, and color classes live here.

export const CONTENT_TYPE_DEFS: ContentTypeDef[] = [
  { id: "faq", icon: "📋" },
  { id: "aeo_article", icon: "🤖" },
  { id: "article", icon: "✍️" },
  { id: "recommendations", icon: "💡" },
  { id: "brief", icon: "📝" },
];

export const ALL_DOMAINS = ["visibility", "citation", "sentiment"];

export const DOMAIN_META: Record<DomainKey, { color: string; icon: string }> = {
  visibility: { color: "bg-blue-500/10 text-blue-400 border-blue-500/20", icon: "🔍" },
  citation: { color: "bg-purple-500/10 text-purple-400 border-purple-500/20", icon: "📎" },
  sentiment: { color: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20", icon: "💬" },
};

// Template name → content_type id mapping. Keys must match what the backend
// stores as geo_agent_task_templates.name for the Content Agent templates.
// This is data-layer matching, not UI text; stays in source.
export const TEMPLATE_CONTENT_TYPE: Record<string, string> = {
  "FAQ 内容生成": "faq",
  "AEO 优化文章": "aeo_article",
  "SEO 优化文章": "article",
  "内容优化建议": "recommendations",
  "Content Brief": "brief",
};

export const SORT_KEYS: SortKey[] = ["visibility", "citation", "sentiment"];

export const PLATFORM_OPTIONS = [
  { id: "chatgpt", label: "ChatGPT", icon: "🤖" },
  { id: "gemini", label: "Gemini", icon: "✨" },
  { id: "aimode", label: "AI Mode", icon: "🔍" },
  { id: "perplexity", label: "Perplexity", icon: "🔎" },
  { id: "aioverview", label: "AI Overview", icon: "🌐" },
];

// ─── Content Goals ──────────────────────────────────────────────────
//
// Each goal's label/description is resolved at render time via
// `t(\`taskModal.goals.items.${dictKey}.label\`)`. GOAL_DICT_KEY maps the
// runtime `ContentGoal` id (used by backend + existing form state) to the
// dictionary subkey (shorter, locale-agnostic).

export const GOAL_DICT_KEY: Record<ContentGoal, GoalDictKey> = {
  visibility_boost: "visibility",
  citation_optimize: "citation",
  sentiment_repair: "sentiment",
  full_optimize: "general",
};

export const CONTENT_GOAL_DEFS: ContentGoalDef[] = [
  { id: "visibility_boost", icon: Target, recommendedTypes: ["faq", "aeo_article"], recommendedDomains: ["visibility", "citation"], defaultSort: "visibility", color: "text-blue-400 border-blue-500/30 bg-blue-500/5" },
  { id: "citation_optimize", icon: TrendingUp, recommendedTypes: ["aeo_article", "brief"], recommendedDomains: ["citation", "visibility"], defaultSort: "citation", color: "text-purple-400 border-purple-500/30 bg-purple-500/5" },
  { id: "sentiment_repair", icon: MessageSquare, recommendedTypes: ["recommendations", "faq"], recommendedDomains: ["sentiment", "citation"], defaultSort: "sentiment", color: "text-amber-400 border-amber-500/30 bg-amber-500/5" },
  { id: "full_optimize", icon: Shield, recommendedTypes: ["faq", "aeo_article", "article", "recommendations", "brief"], recommendedDomains: ["visibility", "citation", "sentiment"], defaultSort: "visibility", color: "text-emerald-400 border-emerald-500/30 bg-emerald-500/5" },
];

// ─── Content Depth ──────────────────────────────────────────────────

export const DEPTH_KEYS: ContentDepth[] = ["quick", "standard", "deep"];
export const DEPTH_ICON: Record<ContentDepth, string> = { quick: "⚡", standard: "📊", deep: "🔬" };

// ─── RAFT Methodology Snippets ──────────────────────────────────────
//
// The snippet bodies are long methodology text that currently lives in
// Chinese only — translating + wiring into the i18n dict is B6 debt.
// The section headers above the snippet grid (category name) DO resolve
// via taskModal.raftCategories.* at render time, so the frame is bilingual
// even while the snippet cards stay Chinese.

export const RAFT_SNIPPETS: { categoryKey: RaftCategoryKey; items: { label: string; snippet: string }[] }[] = [
  {
    categoryKey: "raft4",
    items: [
      { label: "Retrievability（可检索性）", snippet: "确保内容包含目标关键词和语义变体，使AI搜索引擎能够准确检索并关联到品牌。" },
      { label: "Accuracy（准确性）", snippet: "内容必须基于产品真实规格和事实，避免夸大或不实描述，确保AI引擎引用时信息准确。" },
      { label: "Fluency（流畅度）", snippet: "内容应自然流畅，易于AI引擎在回答中无缝引用和整合，避免生硬的营销语言。" },
      { label: "Trustworthiness（可信度）", snippet: "引用可信来源和数据支撑论点，使用专业语气，提升AI引擎对品牌信息的信任度评分。" },
    ],
  },
  {
    categoryKey: "strategy",
    items: [
      { label: "结构化 FAQ", snippet: "使用问答对格式组织内容，每个问题聚焦一个用户场景，答案精准引用产品事实。" },
      { label: "竞品差异化", snippet: "在内容中自然融入品牌与竞品的关键差异点，突出自有品牌的独特优势。" },
      { label: "多平台适配", snippet: "考虑不同 AI 平台的回答风格差异，内容需兼顾直接答案、引用结构和搜索式摘要。" },
    ],
  },
];

export const TOTAL_STEPS = 7;
