import type { Target } from "lucide-react";

// ─── Types ──────────────────────────────────────────────────────────

export interface ContentTemplate {
  id: string;
  name: string;
  icon: string;
  description?: string;
  data_domains?: string[];
  default_prompt?: string;
  defaults?: Record<string, any>;
}

export interface ContentTaskModalProps {
  open: boolean;
  template: ContentTemplate | null;
  clientId: string;
  userId: string;
  clientPlatforms: string[];
  existingTaskId?: string | null;
  onClose: () => void;
  onTaskCreated?: () => void;
}

export interface RankedPrompt {
  id: string;
  prompt_text: string;
  platform: string;
  intent: string;
  topic_name: string;
  mention_count: number;
  avg_position: number;
  citation_count: number;
  negative_count: number;
}

export interface PeerItem {
  id: string;
  primary_name: string;
  is_own_brand: boolean;
}

export type ContentTypeKey = "faq" | "aeo_article" | "article" | "recommendations" | "brief";

export type DomainKey = "visibility" | "citation" | "sentiment";

export type SortKey = "visibility" | "citation" | "sentiment";

export type ContentGoal = "visibility_boost" | "citation_optimize" | "sentiment_repair" | "full_optimize";
export type GoalDictKey = "visibility" | "citation" | "sentiment" | "general";

export type ContentDepth = "quick" | "standard" | "deep";

export type RaftCategoryKey = "raft4" | "strategy";

export interface ContentTypeDef {
  id: ContentTypeKey;
  icon: string;
}

export interface ContentGoalDef {
  id: ContentGoal;
  icon: typeof Target;
  recommendedTypes: string[];
  recommendedDomains: string[];
  defaultSort: string;
  color: string;
}
