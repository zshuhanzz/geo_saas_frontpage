/**
 * GenericStepRenderer — renders one resolved wizard step as a stack of
 * FieldRenderer instances.
 *
 * This component is deliberately dumb — it knows nothing about the task
 * type, the backend, or the overall step navigation. Give it a resolved
 * step + a form state + an onChange, and it outputs the fields.
 *
 * The wizard shell composes this per visible step into the step panels it
 * renders alongside the step indicator.
 */
import { FieldRenderer } from "./FieldRenderer";
import type {
    ResolvedWizardStep,
    WizardFormState,
    WizardRenderContext,
} from "./schema";

export interface GenericStepRendererProps {
    step: ResolvedWizardStep;
    formState: WizardFormState;
    onChange: (key: string, value: unknown, userEdited?: boolean) => void;
    /** Bulk set helper forwarded to custom fields (e.g. Mode Gate AI preselect). */
    setFields?: (values: Record<string, unknown>, userEdited?: boolean) => void;
    context: WizardRenderContext;
    disabled?: boolean;
}

export function GenericStepRenderer({
    step,
    formState,
    onChange,
    setFields,
    context,
    disabled,
}: GenericStepRendererProps) {
    // Filter out admin-only fields — they still seed defaults via formState
    // but are not rendered to SaaS end users.
    const visibleFields = step.fields.filter(
        (f) => !(f.config as Record<string, unknown> | undefined)?.admin_only,
    );

    if (visibleFields.length === 0) {
        return (
            <div className="rounded-md border border-dashed border-border/60 bg-muted/20 p-6 text-center text-xs text-muted-foreground">
                {step.description ||
                    "此步骤无需配置 — 点击下一步继续"}
            </div>
        );
    }
    return (
        <div className="space-y-4">
            {step.description && (
                <p className="text-xs text-muted-foreground leading-relaxed">
                    {step.description}
                </p>
            )}
            <div className="space-y-5">
                {visibleFields.map((field) => (
                    <FieldRenderer
                        key={field.key}
                        field={field}
                        value={formState[field.key]}
                        onChange={(v, userEdited) =>
                            onChange(field.key, v, userEdited)
                        }
                        setFields={setFields}
                        context={context}
                        formState={formState}
                        disabled={disabled}
                    />
                ))}
            </div>
        </div>
    );
}
