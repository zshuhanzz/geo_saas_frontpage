/**
 * FieldRenderer — single React component that renders a field from its
 * schema against the current form state.
 *
 * Primitive types (text / textarea / number / boolean / single_ref /
 * multi_ref / date / date_range / checkbox_group) are rendered inline
 * here. Anything else is delegated to the custom field registry.
 *
 * This component is deliberately UI-minimal — each field is a label + a
 * single input + an optional helper line. The wizard shell handles
 * ordering, step chrome, and submit validation.
 */
import { useMemo } from "react";
import { AlertTriangle } from "lucide-react";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Switch } from "@/components/ui/switch";
import { Checkbox } from "@/components/ui/checkbox";
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from "@/components/ui/select";
import type {
    WizardDictionaryRow,
    WizardFieldSchema,
    WizardFormState,
    WizardRenderContext,
} from "./schema";
import { getCustomField } from "./customFieldRegistry";

// Defensive side-effect import: FieldRenderer is the component that actually
// resolves custom field types, so it should not rely on callers importing
// WizardShell first. Module caching keeps this idempotent when WizardShell
// also imports the custom-field barrel.
import "./customFields";

export interface FieldRendererProps {
    field: WizardFieldSchema;
    value: unknown;
    onChange: (value: unknown, userEdited?: boolean) => void;
    /** Optional bulk set helper forwarded to custom fields. */
    setFields?: (values: Record<string, unknown>, userEdited?: boolean) => void;
    context: WizardRenderContext;
    formState: WizardFormState;
    disabled?: boolean;
}

export function FieldRenderer(props: FieldRendererProps) {
    const { field } = props;

    // Custom field? Delegate and skip the primitive switch entirely.
    const customComponent = getCustomField(field.type);
    if (customComponent) {
        const Cmp = customComponent;
        return (
            <FieldWrapper field={field}>
                <Cmp {...props} />
            </FieldWrapper>
        );
    }

    switch (field.type) {
        case "text":
            return (
                <FieldWrapper field={field}>
                    <Input
                        value={(props.value as string) || ""}
                        onChange={(e) => props.onChange(e.target.value)}
                        disabled={props.disabled}
                        placeholder={field.description}
                    />
                </FieldWrapper>
            );

        case "textarea":
            return (
                <FieldWrapper field={field}>
                    <Textarea
                        value={(props.value as string) || ""}
                        onChange={(e) => props.onChange(e.target.value)}
                        disabled={props.disabled}
                        rows={6}
                        placeholder={field.description}
                    />
                </FieldWrapper>
            );

        case "number":
            return (
                <FieldWrapper field={field}>
                    <Input
                        type="number"
                        value={
                            typeof props.value === "number"
                                ? props.value
                                : props.value === ""
                                  ? ""
                                  : ""
                        }
                        onChange={(e) => {
                            const raw = e.target.value;
                            if (raw === "") return props.onChange("");
                            const n = Number(raw);
                            props.onChange(Number.isNaN(n) ? raw : n);
                        }}
                        disabled={props.disabled}
                    />
                </FieldWrapper>
            );

        case "boolean":
            return (
                <FieldWrapper field={field} inline>
                    <Switch
                        checked={Boolean(props.value)}
                        onCheckedChange={(v) => props.onChange(v)}
                        disabled={props.disabled}
                    />
                </FieldWrapper>
            );

        case "single_ref":
            return <SingleRefField {...props} />;

        case "multi_ref":
            return <MultiRefField {...props} />;

        case "date":
            return (
                <FieldWrapper field={field}>
                    <Input
                        type="date"
                        value={(props.value as string) || ""}
                        onChange={(e) => props.onChange(e.target.value)}
                        disabled={props.disabled}
                    />
                </FieldWrapper>
            );

        case "date_range":
            return <DateRangeField {...props} />;

        case "checkbox_group":
            return <CheckboxGroupField {...props} />;

        default:
            return (
                <FieldWrapper field={field}>
                    <div className="flex items-center gap-2 rounded-md border border-dashed border-destructive/40 bg-destructive/5 px-3 py-2 text-xs text-destructive">
                        <AlertTriangle className="h-3.5 w-3.5" />
                        <span>
                            Unknown field type <code>{field.type}</code> — check
                            `customFieldRegistry` or `FieldRenderer` switch.
                        </span>
                    </div>
                </FieldWrapper>
            );
    }
}

// ─── Wrapper ─────────────────────────────────────────────────────────

function FieldWrapper({
    field,
    children,
    inline,
}: {
    field: WizardFieldSchema;
    children: React.ReactNode;
    inline?: boolean;
}) {
    if (inline) {
        return (
            <div className="flex items-center justify-between gap-3">
                <div className="flex-1 min-w-0">
                    <div className="text-xs font-medium text-foreground">
                        {field.label || field.key}
                        {field.required && (
                            <span className="ml-1 text-destructive">*</span>
                        )}
                    </div>
                    {field.description && (
                        <p className="text-[11px] text-muted-foreground leading-relaxed">
                            {field.description}
                        </p>
                    )}
                </div>
                <div className="shrink-0">{children}</div>
            </div>
        );
    }
    return (
        <div className="space-y-1.5">
            <label className="block text-xs font-medium text-foreground">
                {field.label || field.key}
                {field.required && (
                    <span className="ml-1 text-destructive">*</span>
                )}
            </label>
            {children}
            {field.description && (
                <p className="text-[11px] text-muted-foreground leading-relaxed">
                    {field.description}
                </p>
            )}
        </div>
    );
}

// ─── single_ref ──────────────────────────────────────────────────────

function SingleRefField(props: FieldRendererProps) {
    const { field, value, onChange, context, disabled } = props;
    const rows = useMemo(
        () => resolveRefRows(field, context),
        [field, context],
    );
    const strValue = typeof value === "string" ? value : "";
    return (
        <FieldWrapper field={field}>
            {rows.length === 0 ? (
                <EmptyRefNotice field={field} />
            ) : (
                <Select
                    value={strValue || "__unset__"}
                    onValueChange={(v) =>
                        onChange(v === "__unset__" ? undefined : v)
                    }
                    disabled={disabled}
                >
                    <SelectTrigger className="h-9 text-xs">
                        <SelectValue placeholder="Not set" />
                    </SelectTrigger>
                    <SelectContent>
                        <SelectItem value="__unset__">
                            <span className="italic text-muted-foreground">
                                Not set
                            </span>
                        </SelectItem>
                        {rows.map((r) => (
                            <SelectItem key={r.key} value={r.key}>
                                <span className="inline-flex items-center gap-1.5">
                                    <span>{r.label}</span>
                                    <code className="text-[9px] text-muted-foreground font-mono">
                                        {r.key}
                                    </code>
                                </span>
                            </SelectItem>
                        ))}
                    </SelectContent>
                </Select>
            )}
        </FieldWrapper>
    );
}

// ─── multi_ref ───────────────────────────────────────────────────────

function MultiRefField(props: FieldRendererProps) {
    const { field, value, onChange, context, disabled } = props;
    const rows = useMemo(
        () => resolveRefRows(field, context),
        [field, context],
    );
    const current = Array.isArray(value) ? (value as string[]) : [];

    const toggle = (key: string) => {
        const on = current.includes(key);
        const next = on ? current.filter((x) => x !== key) : [...current, key];
        onChange(next);
    };

    return (
        <FieldWrapper field={field}>
            {rows.length === 0 ? (
                <EmptyRefNotice field={field} />
            ) : (
                <div className="rounded-md border bg-background max-h-56 overflow-y-auto">
                    {rows.map((r) => {
                        const on = current.includes(r.key);
                        return (
                            <label
                                key={r.key}
                                className="flex items-start gap-2 px-3 py-2 border-b border-border/40 last:border-b-0 cursor-pointer hover:bg-accent/30"
                            >
                                <Checkbox
                                    checked={on}
                                    onCheckedChange={() => toggle(r.key)}
                                    disabled={disabled}
                                    className="mt-0.5"
                                />
                                <div className="flex-1 min-w-0">
                                    <div className="flex items-center gap-1.5 flex-wrap">
                                        <span className="text-xs font-medium text-foreground">
                                            {r.label}
                                        </span>
                                        <code className="text-[9px] text-muted-foreground font-mono">
                                            {r.key}
                                        </code>
                                    </div>
                                    {r.description && (
                                        <p className="text-[11px] text-muted-foreground line-clamp-2 mt-0.5">
                                            {r.description}
                                        </p>
                                    )}
                                </div>
                            </label>
                        );
                    })}
                </div>
            )}
            {current.length > 0 && (
                <div className="text-[11px] text-muted-foreground">
                    {current.length} selected
                </div>
            )}
        </FieldWrapper>
    );
}

// ─── date_range ──────────────────────────────────────────────────────

function DateRangeField(props: FieldRendererProps) {
    const { field, value, onChange, disabled } = props;
    const range =
        value && typeof value === "object"
            ? (value as { from?: string; to?: string })
            : { from: "", to: "" };
    const update = (key: "from" | "to", v: string) =>
        onChange({ ...range, [key]: v });
    return (
        <FieldWrapper field={field}>
            <div className="grid grid-cols-2 gap-2">
                <Input
                    type="date"
                    value={range.from || ""}
                    onChange={(e) => update("from", e.target.value)}
                    disabled={disabled}
                />
                <Input
                    type="date"
                    value={range.to || ""}
                    onChange={(e) => update("to", e.target.value)}
                    disabled={disabled}
                />
            </div>
        </FieldWrapper>
    );
}

// ─── checkbox_group (arbitrary static options) ───────────────────────

function CheckboxGroupField(props: FieldRendererProps) {
    const { field, value, onChange, disabled } = props;
    const options =
        (field.config?.options as { key: string; label: string }[]) || [];
    const current = Array.isArray(value) ? (value as string[]) : [];
    const toggle = (k: string) => {
        const on = current.includes(k);
        const next = on ? current.filter((x) => x !== k) : [...current, k];
        onChange(next);
    };
    return (
        <FieldWrapper field={field}>
            <div className="grid grid-cols-2 gap-1.5">
                {options.map((o) => {
                    const on = current.includes(o.key);
                    return (
                        <label
                            key={o.key}
                            className="flex items-center gap-2 rounded border border-border/60 px-2 py-1.5 text-xs cursor-pointer hover:bg-accent/30"
                        >
                            <Checkbox
                                checked={on}
                                onCheckedChange={() => toggle(o.key)}
                                disabled={disabled}
                            />
                            <span className="flex-1">{o.label}</span>
                        </label>
                    );
                })}
            </div>
        </FieldWrapper>
    );
}

// ─── ref helpers ─────────────────────────────────────────────────────

function resolveRefRows(
    field: WizardFieldSchema,
    context: WizardRenderContext,
): WizardDictionaryRow[] {
    const type = field.ref_config_type;
    if (!type) return [];
    return context.dictionary[type] || [];
}

function EmptyRefNotice({ field }: { field: WizardFieldSchema }) {
    return (
        <div className="flex items-start gap-1.5 rounded border border-yellow-500/30 bg-yellow-500/5 px-2.5 py-1.5 text-[11px] text-yellow-500">
            <AlertTriangle className="h-3 w-3 shrink-0 mt-0.5" />
            <span>
                No options for config_type{" "}
                <code className="font-mono">{field.ref_config_type}</code> —
                seed it in the Workflow Config dictionary first.
            </span>
        </div>
    );
}
