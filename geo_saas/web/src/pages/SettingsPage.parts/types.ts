// Types and constants shared across SettingsPage parts.
// Extracted from SettingsPage.tsx (Phase 3B.2) — preserve verbatim.

import type { CandidateType } from "@/lib/api";

// Sentinel values for the Auto-discover dialog's dropdowns to let the user
// type a one-off value that isn't yet saved in workspace settings.
export const OTHER_URL_SENTINEL = "__other_url__";
export const OTHER_BRAND_SENTINEL = "__other_brand__";

export type TabKey = "brands" | "peers" | "topics" | "personas";

// Map each tab → every CandidateType that should surface under its banner.
// Used both for the "X 条候选待 Review" count AND for the per-tab
// SuggestionsPanel filter. Keeping these in sync was the cause of the
// "banner shows N but panel shows 0" bug — the old code picked the
// array's first element, so candidates of any later type disappeared.
export const TAB_RELEVANT_CANDIDATES: Record<TabKey, CandidateType[]> = {
    brands: ["brand", "shadow_brand"],
    peers: ["peer"],
    topics: ["own_product", "shadow_product", "peer_product", "tracked_url"],
    personas: [],
};

export type ProgressEntry = {
    kind: "stage" | "progress" | "warn" | "error";
    stage: string;
    message: string;
    count?: number;
    ts: number;
};

export const INSTRUCTION_MAX_CHARS = 800;
