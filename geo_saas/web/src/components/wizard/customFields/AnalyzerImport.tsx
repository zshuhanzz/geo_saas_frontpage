/**
 * AnalyzerImport — schema-driven replacement for NodeAnalyzerImport.
 *
 * Registered under the custom field type `analyzer_import`. Self-fetches
 * completed opportunity_discovery analyzer tasks via
 * `getOpportunityTasks(clientId)` and renders them as selectable cards.
 *
 * The value shape stored under `field.key` (typically `analyzer_task_id`)
 * is an object:
 *
 *     { task_id: string | null, context: any | null }
 *
 * Carrying both the id AND the cached analyzer output under a single key
 * avoids duplicate fetches (strategy_generator + prompt_ref_picker + the
 * modal submit handler all need the full context; without caching each
 * one would re-hit getAgentTask).
 *
 * Downstream consumers (StrategyGenerator, PromptRefPicker, the
 * ContentPipelineModal submit handler) must read the value as this shape.
 *
 * UX: amber accent, matches the original NodeAnalyzerImport. Includes a
 * "skip" option that writes `{task_id:null, context:null}` so the user
 * can proceed without importing a report.
 */
import { useEffect, useState } from "react";
import { SkipForward, Loader2 } from "lucide-react";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Card } from "@/components/ui/card";
import {
    getOpportunityTasks,
    getAgentTask,
    type OpportunityTaskSummary,
} from "@/lib/api";
import { registerCustomField, type CustomFieldProps } from "../customFieldRegistry";

export interface AnalyzerImportValue {
    task_id: string | null;
    context: Record<string, unknown> | null;
}

function isAnalyzerImportValue(v: unknown): v is AnalyzerImportValue {
    return Boolean(v && typeof v === "object" && "task_id" in (v as object));
}

function AnalyzerImport({ value, onChange, context, disabled }: CustomFieldProps) {
    const clientId = context.clientId;
    const [tasks, setTasks] = useState<OpportunityTaskSummary[]>([]);
    const [loading, setLoading] = useState(true);
    const [selecting, setSelecting] = useState(false);

    const current: AnalyzerImportValue = isAnalyzerImportValue(value)
        ? value
        : { task_id: null, context: null };

    useEffect(() => {
        if (!clientId) return;
        let cancelled = false;
        setLoading(true);
        getOpportunityTasks(clientId)
            .then((rows) => {
                if (!cancelled) setTasks(rows || []);
            })
            .catch(() => {
                if (!cancelled) setTasks([]);
            })
            .finally(() => {
                if (!cancelled) setLoading(false);
            });
        return () => {
            cancelled = true;
        };
    }, [clientId]);

    async function handleSelect(taskId: string) {
        if (selecting) return;
        setSelecting(true);
        try {
            const task = await getAgentTask(taskId, clientId);
            onChange({ task_id: taskId, context: task.output || null }, true);
        } catch {
            onChange({ task_id: taskId, context: null }, true);
        } finally {
            setSelecting(false);
        }
    }

    function handleSkip() {
        onChange({ task_id: null, context: null }, true);
    }

    // Label + description rendered by outer FieldWrapper. Skip inline to
    // avoid double-rendering.
    return (
        <div className="space-y-4">
            {loading ? (
                <div className="flex items-center gap-2 text-xs text-muted-foreground py-4">
                    <Loader2 className="h-3.5 w-3.5 animate-spin" />
                    Loading analysis tasks…
                </div>
            ) : tasks.length === 0 ? (
                <div className="rounded-md border border-dashed border-border/60 bg-muted/20 p-4 text-xs text-muted-foreground text-center">
                    No completed Opportunity Discovery tasks found.
                    <br />
                    <span className="text-[11px] text-muted-foreground/70">
                        Run an Opportunity Discovery analysis first for data-driven recommendations.
                    </span>
                </div>
            ) : (
                <div className="space-y-2 max-h-[320px] overflow-y-auto">
                    {tasks.map((t) => {
                        const selected = current.task_id === t.id;
                        return (
                            <Card
                                key={t.id}
                                className={`p-3 cursor-pointer border transition-colors ${
                                    selected
                                        ? "border-amber-500/60 bg-amber-500/5"
                                        : "border-border bg-muted/40 hover:border-amber-500/30"
                                } ${disabled ? "opacity-60 pointer-events-none" : ""}`}
                                onClick={() => handleSelect(t.id)}
                            >
                                <div className="flex items-center justify-between gap-3">
                                    <div className="min-w-0">
                                        <p className="text-sm font-medium text-foreground truncate">
                                            {t.task_name || "Opportunity Discovery"}
                                        </p>
                                        <p className="text-[11px] text-muted-foreground mt-0.5">
                                            {t.completed_at
                                                ? new Date(
                                                      t.completed_at,
                                                  ).toLocaleDateString("en-US")
                                                : ""}
                                            {t.topic_scope ? ` · ${t.topic_scope}` : ""}
                                        </p>
                                    </div>
                                    <div className="flex gap-1.5 shrink-0">
                                        <Badge
                                            variant="secondary"
                                            className="text-[10px]"
                                        >
                                            {t.summary.topic_count} Topics
                                        </Badge>
                                        <Badge
                                            variant="secondary"
                                            className="text-[10px]"
                                        >
                                            {t.summary.opportunity_count} Opportunities
                                        </Badge>
                                    </div>
                                </div>
                            </Card>
                        );
                    })}
                </div>
            )}

            <div className="flex items-center justify-between pt-1">
                {selecting ? (
                    <span className="flex items-center gap-1.5 text-[11px] text-muted-foreground">
                        <Loader2 className="h-3 w-3 animate-spin" />
                        Loading analysis context…
                    </span>
                ) : current.task_id ? (
                    <span className="text-[11px] text-amber-500">
                        Analysis report context imported
                    </span>
                ) : (
                    <span className="text-[11px] text-muted-foreground/70">
                        Not selected — continuing in manual mode
                    </span>
                )}
                <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    disabled={disabled}
                    onClick={handleSkip}
                    className="text-muted-foreground hover:text-foreground"
                >
                    <SkipForward className="w-3.5 h-3.5 mr-1" />
                    Skip, configure manually
                </Button>
            </div>
        </div>
    );
}

registerCustomField("analyzer_import", AnalyzerImport);

export default AnalyzerImport;
