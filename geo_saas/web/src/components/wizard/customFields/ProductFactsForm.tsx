/**
 * ProductFactsForm — schema-driven replacement for the productFacts block
 * inside NodeGenConfig.
 *
 * Registered under the custom field type `product_facts_form`. Renders an
 * expandable section with three textareas (specs / features / differentiators)
 * — these are the factual anchors fed into the content-generation prompt as
 * hard constraints to prevent LLM hallucination.
 *
 * The form value shape stored under field.key (typically
 * `default_product_facts`) is:
 *
 *     { specs: string, features: string, differentiators: string }
 *
 * Sub-fields are driven by the schema's `config.fields` list — migration 031
 * ships `["specs", "features", "differentiators"]`, but extra facts can be
 * added later without touching this component.
 */
import { useState } from "react";
import { ChevronDown, ChevronUp, Package } from "lucide-react";
import { registerCustomField, type CustomFieldProps } from "../customFieldRegistry";

type Facts = Record<string, string>;

const DEFAULT_SUB_FIELDS = ["specs", "features", "differentiators"];

const SUB_FIELD_META: Record<
    string,
    { label: string; placeholder: string }
> = {
    specs: {
        label: "Product Specs",
        placeholder: "Core parameters, technical specifications…",
    },
    features: {
        label: "Key Features",
        placeholder: "Product highlights, unique capabilities…",
    },
    differentiators: {
        label: "Differentiators",
        placeholder: "Key advantages over competitors…",
    },
};

function toFacts(v: unknown, keys: string[]): Facts {
    if (v && typeof v === "object") {
        const o = v as Record<string, unknown>;
        const out: Facts = {};
        for (const k of keys) out[k] = typeof o[k] === "string" ? (o[k] as string) : "";
        return out;
    }
    const out: Facts = {};
    for (const k of keys) out[k] = "";
    return out;
}

function ProductFactsForm({ field, value, onChange, disabled }: CustomFieldProps) {
    const [expanded, setExpanded] = useState(false);

    const subFields =
        (field.config?.fields as string[] | undefined) || DEFAULT_SUB_FIELDS;
    const facts = toFacts(value, subFields);

    const filledCount = subFields.reduce(
        (acc, k) => (facts[k]?.trim() ? acc + 1 : acc),
        0,
    );

    function update(key: string, next: string) {
        onChange({ ...facts, [key]: next }, true);
    }

    return (
        <div className="border border-border rounded-lg bg-muted/10">
            <button
                type="button"
                onClick={() => setExpanded((e) => !e)}
                disabled={disabled}
                className="w-full flex items-center justify-between p-3 text-sm text-muted-foreground hover:text-foreground transition-colors disabled:opacity-50"
            >
                <span className="flex items-center gap-2">
                    <Package className="w-4 h-4 text-cyan-400" />
                    <span className="font-medium">展开/收起</span>
                    {filledCount > 0 && (
                        <span className="text-[10px] font-normal px-1.5 py-0.5 rounded-full bg-cyan-500/10 text-cyan-400 border border-cyan-500/20">
                            {filledCount}/{subFields.length} filled
                        </span>
                    )}
                </span>
                {expanded ? (
                    <ChevronUp className="w-4 h-4" />
                ) : (
                    <ChevronDown className="w-4 h-4" />
                )}
            </button>

            {expanded && (
                <div className="px-3 pb-3 space-y-3">
                    {/* Description rendered by outer FieldWrapper. */}
                    {subFields.map((key) => {
                        const meta = SUB_FIELD_META[key] || {
                            label: key,
                            placeholder: "",
                        };
                        return (
                            <div key={key}>
                                <label className="text-[11px] font-medium text-muted-foreground">
                                    {meta.label}
                                </label>
                                <textarea
                                    className="w-full bg-background border border-input rounded p-2 text-sm text-foreground resize-none mt-1 focus:outline-none focus:ring-2 focus:ring-ring/30"
                                    rows={2}
                                    placeholder={meta.placeholder}
                                    value={facts[key] || ""}
                                    onChange={(e) => update(key, e.target.value)}
                                    disabled={disabled}
                                />
                            </div>
                        );
                    })}
                </div>
            )}
        </div>
    );
}

registerCustomField("product_facts_form", ProductFactsForm);

export default ProductFactsForm;
