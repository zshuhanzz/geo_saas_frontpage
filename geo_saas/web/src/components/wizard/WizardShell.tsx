/**
 * WizardShell — the composable entry point for the schema-driven wizard.
 *
 * This is the piece TemplateConfigModal (Analyze) and ContentPipelineModal
 * (Content) mount inside their own modal chrome. It knows nothing about
 * running tasks, saving templates, or polling — its only job is:
 *
 *   1. Fetch `/tasks/workflow-config?scope=X` and memoize the raw payload.
 *   2. Normalize dictionary + workflow_step rows into typed definitions.
 *   3. Resolve the steps against the template's wizard_config overrides.
 *   4. Seed an initial FormState (template defaults + callers `initialValues`).
 *   5. Render a step indicator + the current GenericStepRenderer panel + nav.
 *   6. Expose `onSubmit(formState, action)` when the user clicks a final action.
 *
 * The host modal passes an `actions` array (e.g. [{key:"run",label:"运行"},
 * {key:"save",label:"保存为模板"}]) which is rendered as buttons on the final
 * step. Callers then decide what each action means in its own domain language
 * (runReport vs. saveTemplate vs. enqueueContentPipeline).
 *
 * The shell is deliberately style-minimal — host modals own the container
 * chrome (header, close button, sticky footer) so the wizard can live inside
 * both a Dialog and a drawer without cosmetic re-work.
 */
import { useEffect, useMemo, useState, useCallback } from "react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Loader2, ChevronLeft, ChevronRight, AlertTriangle } from "lucide-react";
import { getWizardWorkflowConfig } from "@/lib/api";
import { GenericStepRenderer } from "./GenericStepRenderer";
import {
    normalizeDictionary,
    resolveVisibleSteps,
    resolveAllSteps,
    rowToWorkflowStep,
    seedInitialFormState,
} from "./resolveSteps";
import { useWizardFormState } from "./useWizardFormState";
import type {
    ResolvedWizardStep,
    WizardDictionary,
    WizardFormState,
    WizardRenderContext,
    WizardTemplate,
    WorkflowStepDefinition,
} from "./schema";

// Side-effect import: registers all custom fields (chart_builder, prompt_editor, …)
// before FieldRenderer asks the registry for them.
import "./customFields";

export interface WizardShellAction {
    /** Stable identifier passed to `onSubmit` as the 2nd argument. */
    key: string;
    /** Button label. */
    label: string;
    /** Visual weight. `primary` uses the accent button, `secondary` uses outline. */
    variant?: "primary" | "secondary";
    /** Optional icon element rendered before the label. */
    icon?: React.ReactNode;
    /** When true, the button is disabled regardless of form state. */
    disabled?: boolean;
    /** When true, the button shows a spinner and is not clickable. */
    loading?: boolean;
    /** When true, this action is rendered on every step instead of only the last. */
    persistent?: boolean;
}

export interface WizardShellProps {
    /** 'analysis' | 'content_generation'. */
    scope: string;
    /** Active template — drives step visibility, default values, overrides. */
    template: WizardTemplate | null;
    /** Multi-tenant client id (flows into every downstream backend call). */
    clientId: string;
    /** Current user id. */
    userId: string;
    /** Optional starting values merged ON TOP of template defaults (weakest
     *  wins — the caller decides the priority). Useful for "continue from
     *  analyzer_context" flows where the shell needs to pre-fill
     *  `analyzer_task_id` before the user touches anything. */
    initialValues?: WizardFormState;
    /** Extra read-only render context (e.g. platforms/peers/etc. the host
     *  already fetched). Merged into `WizardRenderContext.dictionary` so
     *  custom fields can resolve refs without re-fetching. */
    extraDictionary?: WizardDictionary;
    /** Buttons shown in the sticky footer. `primary` buttons get a solid fill. */
    actions: WizardShellAction[];
    /** Called when any action button is clicked. The caller owns validation
     *  and side effects; the shell just hands over the current form state. */
    onSubmit: (formState: WizardFormState, actionKey: string) => void | Promise<void>;
    /** Called when the form state changes. Optional — host modals usually
     *  don't care until submit. Gets (state, dirtyKeys). */
    onStateChange?: (state: WizardFormState, dirty: Set<string>) => void;
    /** Disables every field + action button (e.g. while a task is running). */
    disabled?: boolean;
    /** Optional element rendered ABOVE the step indicator. Used by host
     *  modals to show a title / subtitle without baking it into the shell. */
    header?: React.ReactNode;
    /** Optional element rendered BELOW the nav buttons (e.g. cron picker,
     *  model picker, run-time banner). Appears on every step. */
    footerExtras?: React.ReactNode;
}

// ─── Shell ───────────────────────────────────────────────────────────

export function WizardShell(props: WizardShellProps) {
    const { t } = useTranslation("wizard");
    const {
        scope,
        template,
        clientId,
        userId,
        initialValues,
        extraDictionary,
        actions,
        onSubmit,
        onStateChange,
        disabled,
        header,
        footerExtras,
    } = props;

    const [loading, setLoading] = useState(true);
    const [error, setError] = useState<string | null>(null);
    const [definitions, setDefinitions] = useState<WorkflowStepDefinition[]>([]);
    const [dictionary, setDictionary] = useState<WizardDictionary>({});
    const [currentStepIdx, setCurrentStepIdx] = useState(0);

    // ─── Fetch workflow_config on mount / scope change ───────────────
    useEffect(() => {
        let cancelled = false;
        setLoading(true);
        setError(null);
        getWizardWorkflowConfig(scope)
            .then((payload: {
                scope: string;
                steps: Array<{
                    key: string;
                    scope: string;
                    value: Record<string, unknown>;
                    sort_order: number | null;
                }>;
                dictionary: Record<string, Array<Record<string, unknown>>>;
            }) => {
                if (cancelled) return;
                const defs = (payload.steps || []).map((s) => rowToWorkflowStep(s));
                setDefinitions(defs);
                setDictionary(normalizeDictionary(payload.dictionary));
                setLoading(false);
            })
            .catch((err: Error) => {
                if (cancelled) return;
                setError(err.message || "Failed to load workflow config");
                setLoading(false);
            });
        return () => {
            cancelled = true;
        };
    }, [scope]);

    // ─── Resolve steps against the template ──────────────────────────
    const resolvedVisible = useMemo(
        () => resolveVisibleSteps(definitions, template),
        [definitions, template],
    );
    const resolvedAll = useMemo(
        () => resolveAllSteps(definitions, template),
        [definitions, template],
    );

    // Merge extraDictionary INTO the fetched dictionary (caller takes
    // precedence so a host can hot-inject platforms/peers without waiting
    // for a backend refetch).
    const mergedDictionary = useMemo<WizardDictionary>(() => {
        if (!extraDictionary) return dictionary;
        return { ...dictionary, ...extraDictionary };
    }, [dictionary, extraDictionary]);

    // Seed form state from defaults. We seed from `resolvedAll` so disabled
    // steps still contribute hidden defaults into the submitted payload.
    const seededState = useMemo(() => {
        const base = seedInitialFormState(resolvedAll, template || undefined);
        if (initialValues) return { ...base, ...initialValues };
        return base;
    // initialValues is intentionally excluded from deps — it's a "starting
    // point" and should not retriggger seeding on host re-renders. Host
    // modals can call `form.reset(next)` if they need to re-seed mid-run.
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [resolvedAll, template]);

    const context = useMemo<WizardRenderContext>(
        () => ({
            scope,
            templateId: template?.id,
            clientId,
            userId,
            dictionary: mergedDictionary,
            steps: definitions,
            template: template || undefined,
        }),
        [scope, template, clientId, userId, mergedDictionary, definitions],
    );

    const form = useWizardFormState({
        steps: resolvedAll,
        initialState: seededState,
        context,
    });

    // Notify host of state changes when requested.
    useEffect(() => {
        if (onStateChange) onStateChange(form.values, form.internal.dirty);
    // only fire when values change; onStateChange identity is not a dep
    // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [form.values, form.internal.dirty]);

    // ─── Reset current step when the visible list changes ────────────
    useEffect(() => {
        if (currentStepIdx >= resolvedVisible.length) {
            setCurrentStepIdx(Math.max(0, resolvedVisible.length - 1));
        }
    }, [resolvedVisible.length, currentStepIdx]);

    // ─── Loading / error states ──────────────────────────────────────
    if (loading) {
        return (
            <div className="flex flex-col items-center justify-center gap-2 py-16 text-xs text-muted-foreground">
                <Loader2 className="h-5 w-5 animate-spin" />
                <span>{t("shell.loadingSchema")}</span>
            </div>
        );
    }
    if (error) {
        return (
            <div className="flex items-start gap-2 rounded-md border border-destructive/40 bg-destructive/5 p-4 text-xs text-destructive">
                <AlertTriangle className="h-4 w-4 shrink-0" />
                <div>
                    <div className="font-medium">{t("shell.failedToLoad")}</div>
                    <div className="mt-1 opacity-80">{error}</div>
                </div>
            </div>
        );
    }
    if (resolvedVisible.length === 0) {
        return (
            <div className="rounded-md border border-dashed border-border/60 bg-muted/20 p-6 text-center text-xs text-muted-foreground">
                No configuration steps enabled for this template —
                check the {scope} scope workflow_step dictionary
                in Admin Workflow Config.
            </div>
        );
    }

    const currentStep = resolvedVisible[currentStepIdx];
    const isFirst = currentStepIdx === 0;
    const isLast = currentStepIdx === resolvedVisible.length - 1;

    // ─── Render ──────────────────────────────────────────────────────
    return (
        <div className="flex flex-col gap-5">
            {header}

            {/* Step indicator */}
            <StepIndicator
                steps={resolvedVisible}
                currentIdx={currentStepIdx}
                onJump={(idx) => setCurrentStepIdx(idx)}
            />

            {/* Active step body */}
            <div className="rounded-lg border bg-card p-5">
                <div className="mb-3 flex items-baseline justify-between">
                    <div>
                        <h3 className="text-sm font-semibold text-foreground">
                            {currentStep.label}
                        </h3>
                    </div>
                    <div className="text-[10px] font-mono uppercase text-muted-foreground">
                        step {currentStepIdx + 1} / {resolvedVisible.length}
                    </div>
                </div>
                <GenericStepRenderer
                    step={currentStep}
                    formState={form.values}
                    onChange={(key, value, userEdited) =>
                        form.setField(key, value, userEdited)
                    }
                    setFields={(values, userEdited) => {
                        for (const [k, v] of Object.entries(values)) {
                            form.setField(k, v, userEdited);
                        }
                    }}
                    context={context}
                    disabled={disabled}
                />
            </div>

            {isLast && footerExtras}

            {/* Nav + actions */}
            <div className="flex items-center justify-between gap-2 border-t pt-4">
                <Button
                    type="button"
                    variant="outline"
                    size="sm"
                    disabled={isFirst || disabled}
                    onClick={() => setCurrentStepIdx((i) => Math.max(0, i - 1))}
                >
                    <ChevronLeft className="h-3.5 w-3.5 mr-1" />
                    Previous
                </Button>

                <div className="flex items-center gap-2">
                    {/* Persistent actions are always visible; others only on the last step */}
                    {actions
                        .filter((a) => a.persistent || isLast)
                        .map((a) => (
                            <Button
                                key={a.key}
                                type="button"
                                size="sm"
                                variant={
                                    a.variant === "secondary" ? "outline" : "default"
                                }
                                disabled={a.disabled || a.loading || disabled}
                                onClick={() => onSubmit(form.values, a.key)}
                            >
                                {a.loading ? (
                                    <Loader2 className="h-3.5 w-3.5 mr-1 animate-spin" />
                                ) : (
                                    a.icon
                                )}
                                {a.label}
                            </Button>
                        ))}

                    {!isLast && (
                        <Button
                            type="button"
                            size="sm"
                            disabled={disabled}
                            onClick={() =>
                                setCurrentStepIdx((i) =>
                                    Math.min(resolvedVisible.length - 1, i + 1),
                                )
                            }
                        >
                            Next
                            <ChevronRight className="h-3.5 w-3.5 ml-1" />
                        </Button>
                    )}
                </div>
            </div>
        </div>
    );
}

// ─── Step indicator ──────────────────────────────────────────────────

function StepIndicator({
    steps,
    currentIdx,
    onJump,
}: {
    steps: ResolvedWizardStep[];
    currentIdx: number;
    onJump: (idx: number) => void;
}) {
    return (
        <div className="flex items-center gap-1.5 overflow-x-auto pb-1">
            {steps.map((s, idx) => {
                const state =
                    idx === currentIdx
                        ? "active"
                        : idx < currentIdx
                          ? "done"
                          : "pending";
                const previous = idx > 0 ? steps[idx - 1] : null;
                const showGroup =
                    s.group?.key && (!previous || previous.group?.key !== s.group.key);
                return (
                    <div key={s.key} className="flex shrink-0 items-center gap-1.5">
                        {showGroup && (
                            <span className="rounded-full border border-primary/20 bg-primary/[0.04] px-2 py-1 text-[10px] font-semibold uppercase tracking-wide text-primary">
                                {s.group?.label}
                            </span>
                        )}
                        <button
                            type="button"
                            onClick={() => onJump(idx)}
                            className={[
                                "flex shrink-0 items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-medium transition",
                                state === "active"
                                    ? "border-primary/50 bg-primary/10 text-primary"
                                    : state === "done"
                                      ? "border-emerald-500/30 bg-emerald-500/5 text-emerald-500 hover:bg-emerald-500/10"
                                      : "border-border/60 bg-muted/30 text-muted-foreground hover:bg-muted/50",
                            ].join(" ")}
                        >
                            <span
                                className={[
                                    "flex h-4 w-4 items-center justify-center rounded-full text-[9px] font-mono",
                                    state === "active"
                                        ? "bg-primary text-primary-foreground"
                                        : state === "done"
                                          ? "bg-emerald-500 text-white"
                                          : "bg-border/80 text-muted-foreground",
                                ].join(" ")}
                            >
                                {idx + 1}
                            </span>
                            <span>{s.label}</span>
                        </button>
                    </div>
                );
            })}
        </div>
    );
}

// ─── Helper hook — defensive callback identity ───────────────────────
// Guarantees the submit callback sees the latest form state even when
// the host passes a fresh closure on every render.
export function useWizardSubmitHandler(
    onSubmit: (state: WizardFormState, actionKey: string) => void | Promise<void>,
): (state: WizardFormState, actionKey: string) => Promise<void> {
    return useCallback(
        async (state, actionKey) => {
            await onSubmit(state, actionKey);
        },
        [onSubmit],
    );
}
