// ── Types ────────────────────────────────────────────────────

// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type AgentsTFn = (key: string, opts?: any) => string;

export interface ChatSession {
  thread_id: string;
  title: string;
  created_at: string;
  updated_at: string;
}

export interface ThinkingStep {
  node: string;
  tier: number;
  label: string;
  detail: string;
  sql?: string;
  data?: any;
}

export interface WidgetEntry {
  widget_id: string;
  widget_type: string;
  field: string;
  label?: string;
  description?: string;
  options?: any[];
  default_value?: any;
  placeholder?: string;
  config?: Record<string, any>;
  summary?: Record<string, any>;
  /** Step grouping metadata (set by backend workflow_config builder). When
   *  multiple widgets share the same step_key, the chat groups them under one
   *  step card and renders a single "下一步 →" button at the bottom. */
  step_key?: string;
  step_num?: number;
  step_label?: string;
  step_description?: string;
  /** Whether this widget is required to advance the step. Used by the
   *  step-level submit button to gate "下一步" + power "跳过剩余". */
  required?: boolean;
  /** Confirmation card row metadata — see ChatWidgetRenderer.ConfirmationStep. */
  steps?: any[];
  resolved?: boolean;
  resolvedValue?: any;
}

export interface ChatMessage {
  role: "human" | "ai" | "tool" | "task_card";
  content: string;
  tool_results?: any;
  created_at?: string;
  charts?: any[];
  thinking?: ThinkingStep[];
  widgets?: WidgetEntry[];
  streaming?: boolean;
  taskInputs?: Record<string, any>;
  /** Translated Chinese-label rows for ChatTaskCard. Carried straight from
   *  the agent's `task_ready` SSE event so the card can render labels like
   *  "分析目标: 品牌健康诊断" without re-querying workflow_config. */
  summaryDisplay?: Array<{ step_key?: string; field?: string; label: string; value?: any; display: string }>;
  exportReady?: { threadId: string; turnCount: number; chartCount: number };
}
