/**
 * Custom field registry — maps custom field type names to React components.
 *
 * FieldRenderer delegates to this registry whenever it encounters a field
 * `type` that is not one of the base primitives. This is the extension seam
 * for the complex Analyze/Content wizard widgets (chart builder, prompt
 * editor, analyzer import, etc.).
 *
 * Round 1 ships STUBS only — each registered component renders a clearly
 * labeled placeholder so the end-to-end plumbing works and runs. Round 2
 * replaces each stub with the real component by porting the existing JSX
 * out of TemplateConfigModal / ContentPipelineModal into these files.
 *
 * Registration happens at module import time — the `customFieldRegistry`
 * barrel is imported once from the WizardShell, which triggers every
 * `registerCustomField` call below. No runtime registration needed from
 * within components.
 */
import type { ComponentType } from "react";
import { AlertTriangle } from "lucide-react";
import type {
    WizardFieldSchema,
    WizardRenderContext,
    WizardFormState,
} from "./schema";

export interface CustomFieldProps {
    field: WizardFieldSchema;
    value: unknown;
    onChange: (value: unknown, userEdited?: boolean) => void;
    /** Bulk-set multiple form fields. Used by compound fields that need to
     *  cascade downstream defaults (e.g. the Mode Gate's AI preselect that
     *  fills target_topic_id + target_prompt_ids + content_type in one shot).
     *  Each key dispatches a separate `set_field` action — the reducer will
     *  coalesce equal-value writes. userEdited=false keeps fields clean so
     *  user overrides still take precedence on subsequent edits. */
    setFields?: (values: Record<string, unknown>, userEdited?: boolean) => void;
    context: WizardRenderContext;
    formState: WizardFormState;
    disabled?: boolean;
}

export type CustomFieldComponent = ComponentType<CustomFieldProps>;

const registry = new Map<string, CustomFieldComponent>();

export function registerCustomField(
    type: string,
    component: CustomFieldComponent,
): void {
    if (registry.has(type)) {
        // eslint-disable-next-line no-console
        console.warn(`[wizard] custom field '${type}' re-registered`);
    }
    registry.set(type, component);
}

export function getCustomField(type: string): CustomFieldComponent | undefined {
    return registry.get(type);
}

export function listCustomFields(): string[] {
    return Array.from(registry.keys()).sort();
}

// ─── Round 1 stubs ───────────────────────────────────────────────────
//
// Each of the confirmed custom field types gets a placeholder component
// so the FieldRenderer does not throw "unknown type" in Round 1. Round 2
// replaces each one with its real implementation and moves the file into
// `customFields/` to keep this registry file small.

function StubField({ field, value }: CustomFieldProps) {
    const preview =
        value === undefined
            ? "—"
            : Array.isArray(value)
              ? `[${value.length} items]`
              : typeof value === "object"
                ? "{object}"
                : String(value);
    return (
        <div className="flex items-center gap-2 rounded-md border border-dashed border-amber-500/40 bg-amber-500/5 px-3 py-2 text-xs text-amber-500">
            <AlertTriangle className="h-3.5 w-3.5 shrink-0" />
            <span className="font-mono">
                {field.type} <span className="opacity-60">(round 2)</span>
            </span>
            <span className="ml-auto font-mono text-[10px] text-amber-500/70">
                {preview}
            </span>
        </div>
    );
}

registerCustomField("chart_builder", StubField);
registerCustomField("prompt_editor", StubField);
registerCustomField("analyzer_import", StubField);
registerCustomField("strategy_generator", StubField);
registerCustomField("prompt_ref_picker", StubField);
registerCustomField("metric_ref_multi", StubField);
registerCustomField("platform_picker", StubField);
registerCustomField("peer_picker", StubField);
