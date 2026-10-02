import { type AvailabilityFlags } from "@/lib/api";
import type { Template } from "./types";

/** Lightweight SQL formatter: adds line breaks before major keywords */
export function formatSql(sql: string): string {
    return sql
        .replace(/\s+/g, " ")
        .replace(/\b(SELECT|FROM|WHERE|LEFT JOIN|INNER JOIN|JOIN|GROUP BY|ORDER BY|HAVING|LIMIT|AND|OR|ON|UNION|WITH|AS \()\b/gi,
            (m) => "\n" + m.toUpperCase())
        .trim();
}

/** Check if a template's visibility_condition is satisfied by the current
 *  client's availability flags. Unknown condition keys are ignored (fail-open). */
export function templateMatchesAvailability(t: Template, avail: AvailabilityFlags | null): boolean {
    const cond = t.wizard_config?.visibility_condition;
    if (!cond || Object.keys(cond).length === 0) return true;
    if (!avail) return true; // avail not loaded yet → don't hide
    for (const [k, required] of Object.entries(cond)) {
        if (required && !(avail as any)[k]) return false;
    }
    return true;
}

// DOMAIN_META holds static color classes; label is resolved at render time
// via `t(`analysis.domains.${key}`)` so both zh / en modes stay correct.
export const DOMAIN_META: Record<string, { labelKey: "visibility" | "citation" | "sentiment"; color: string }> = {
    visibility: { labelKey: "visibility", color: "bg-blue-500/10 text-blue-400 border-blue-500/20" },
    citation: { labelKey: "citation", color: "bg-purple-500/10 text-purple-400 border-purple-500/20" },
    sentiment: { labelKey: "sentiment", color: "bg-emerald-500/10 text-emerald-400 border-emerald-500/20" },
};

export const ALL_DOMAINS = ["visibility", "citation", "sentiment"];

// ─── Canonical workflow steps (must match backend ANALYSIS_WORKFLOW_STEPS) ────
export const CANONICAL_ANALYSIS_STEPS = [
    { step: 1, name: "validate_inputs", label: "输入校验", status: "pending" },
    { step: 2, name: "hydrate_metrics", label: "指标注入", status: "pending" },
    { step: 3, name: "generate_charts", label: "图表生成", status: "pending" },
    { step: 4, name: "synthesize_report", label: "报告合成", status: "pending" },
    { step: 5, name: "quality_check", label: "质量检查", status: "pending" },
];

export const CANONICAL_OPPORTUNITY_STEPS = [
    { step: 1, name: "topic_quadrant", label: "话题象限分析", status: "pending" },
    { step: 2, name: "content_opportunities", label: "内容机会发现", status: "pending" },
    { step: 3, name: "platform_analysis", label: "平台引用分析", status: "pending" },
    { step: 4, name: "synthesize_output", label: "综合输出", status: "pending" },
];

/** Merge DB workflow_steps with canonical definition (handles old 3-step tasks) */
export function mergeWorkflowSteps(
    dbSteps: Array<{ step: number; name: string; label: string; status: string }> | null | undefined,
    taskType?: string,
): Array<{ step: number; name: string; label: string; status: string }> {
    const canonical = taskType === "opportunity_discovery" ? CANONICAL_OPPORTUNITY_STEPS : CANONICAL_ANALYSIS_STEPS;
    if (!dbSteps || !Array.isArray(dbSteps)) return canonical;
    if (dbSteps.length >= canonical.length) return dbSteps;
    // Old task has fewer steps — match by name first, then by step number as fallback
    const dbByName = new Map(dbSteps.map(s => [s.name, s]));
    const dbByNum = new Map(dbSteps.map(s => [s.step, s]));
    return canonical.map(cs => {
        const byName = dbByName.get(cs.name);
        if (byName) return { ...cs, status: byName.status };
        const byNum = dbByNum.get(cs.step);
        if (byNum) return { ...cs, status: byNum.status };
        return cs;
    });
}

// ─── Step Output Helpers ──────────────────────────────────────────────────────

/** Extract per-step outputs from status_logs */
export function getStepOutputs(statusLogs: any): Record<number, any> {
    const outputs: Record<number, any> = {};
    const logs = typeof statusLogs === "string" ? JSON.parse(statusLogs) : statusLogs;
    if (!Array.isArray(logs)) return outputs;
    for (const log of logs) {
        if (log.event === "step_output" && log.step && log.data) {
            outputs[log.step] = log.data;
        }
    }
    return outputs;
}
