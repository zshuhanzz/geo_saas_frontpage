/**
 * ExecutionPreview — read-only custom field that renders a visual preview
 * of the execution pipeline steps that will run after the user confirms.
 *
 * Registered under the custom field type `execution_preview`. The steps
 * are declaratively configured in the field's `config.steps` array (seeded
 * by migration 036 into the `confirm_execute` workflow_step rows).
 *
 * This component is display-only — it writes nothing to FormState.
 */
import { CheckCircle2, ArrowRight } from "lucide-react";
import { useTranslation } from "react-i18next";
import { registerCustomField, type CustomFieldProps } from "../customFieldRegistry";

interface PreviewStep {
    name: string;
    label: string;
    description?: string;
}

function ExecutionPreview({ field }: CustomFieldProps) {
    const { t } = useTranslation("wizard");
    const rawSteps = (field.config?.steps as PreviewStep[]) || [];
    const steps = expandRevisePreviewSteps(rawSteps, t);

    if (steps.length === 0) return null;

    return (
        <div className="space-y-3">
            <p className="text-xs text-muted-foreground leading-relaxed">
                {t("executionPreview.intro")}
            </p>
            <div className="rounded-lg border bg-muted/10 divide-y divide-border/40">
                {steps.map((step, idx) => (
                    <div
                        key={step.name}
                        className="flex items-start gap-3 px-4 py-3"
                    >
                        <div className="flex items-center gap-2 shrink-0 mt-0.5">
                            <span className="flex h-5 w-5 items-center justify-center rounded-full bg-primary/10 text-[10px] font-mono font-semibold text-primary">
                                {idx + 1}
                            </span>
                            {idx < steps.length - 1 && (
                                <ArrowRight className="h-3 w-3 text-muted-foreground/30 hidden" />
                            )}
                        </div>
                        <div className="flex-1 min-w-0">
                            <div className="flex items-center gap-2">
                                <span className="text-xs font-medium text-foreground">
                                    {step.label}
                                </span>
                                <code className="text-[9px] text-muted-foreground/50 font-mono">
                                    {step.name}
                                </code>
                            </div>
                            {step.description && (
                                <p className="text-[11px] text-muted-foreground mt-0.5 leading-relaxed">
                                    {step.description}
                                </p>
                            )}
                        </div>
                        <CheckCircle2 className="h-3.5 w-3.5 text-muted-foreground/20 shrink-0 mt-0.5" />
                    </div>
                ))}
            </div>
            <p className="text-[11px] text-muted-foreground/60">
                {t("executionPreview.bgHint")}
            </p>
        </div>
    );
}

type ExecutionPreviewTextKey =
    | "executionPreview.reviseSteps.round1"
    | "executionPreview.reviseSteps.round1Desc"
    | "executionPreview.reviseSteps.recheck"
    | "executionPreview.reviseSteps.recheckDesc"
    | "executionPreview.reviseSteps.round2"
    | "executionPreview.reviseSteps.round2Desc"
    | "executionPreview.reviseSteps.recheck2"
    | "executionPreview.reviseSteps.recheck2Desc";

function expandRevisePreviewSteps(
    steps: PreviewStep[],
    t: (key: ExecutionPreviewTextKey) => string,
): PreviewStep[] {
    return steps.flatMap((step) => {
        const name = String(step.name || "");
        if (name !== "revise" && name !== "content_revise") return [step];
        return [
            {
                name: "revise_round_1",
                label: t("executionPreview.reviseSteps.round1"),
                description: t("executionPreview.reviseSteps.round1Desc"),
            },
            {
                name: "quality_recheck",
                label: t("executionPreview.reviseSteps.recheck"),
                description: t("executionPreview.reviseSteps.recheckDesc"),
            },
            {
                name: "revise_round_2",
                label: t("executionPreview.reviseSteps.round2"),
                description: t("executionPreview.reviseSteps.round2Desc"),
            },
            {
                name: "quality_recheck_round_2",
                label: t("executionPreview.reviseSteps.recheck2"),
                description: t("executionPreview.reviseSteps.recheck2Desc"),
            },
        ];
    });
}

registerCustomField("execution_preview", ExecutionPreview);

export default ExecutionPreview;
