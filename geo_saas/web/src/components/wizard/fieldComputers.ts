/**
 * Field computer registry — declarative `compute_default` implementations.
 *
 * A field schema can declare:
 *
 *     {
 *       "key": "prompt",
 *       "type": "prompt_editor",
 *       "depends_on": ["selected_metrics", "selected_subgoals"],
 *       "compute_default": "prompt_template_with_metrics"
 *     }
 *
 * `compute_default` is a STRING that maps to a frontend-registered function
 * in this module. No eval, no dynamic code execution. The name acts as the
 * wire-level contract: the backend can emit schemas that reference any
 * registered name, and missing names fall through to a no-op (the UI keeps
 * working, with a console.warn).
 *
 * Each computer signature:
 *
 *     (formState, field, context) => newValue | undefined
 *
 * Returning `undefined` signals "no change" — the reducer will skip the
 * update, so a computer can bail out when inputs are incomplete.
 *
 * ---
 *
 * Round 1 ships with a skeleton registry + one stub for the
 * `prompt_template_with_metrics` computer so we can verify the wiring end
 * to end. Round 2 fills in the real implementations as we migrate each
 * custom field.
 */
import type {
    WizardFieldSchema,
    WizardFormState,
    WizardRenderContext,
} from "./schema";
import { addLocalDays } from "@/lib/dateOnly";

export type FieldComputer = (
    formState: WizardFormState,
    field: WizardFieldSchema,
    context: WizardRenderContext,
) => unknown;

const registry = new Map<string, FieldComputer>();

export function registerFieldComputer(name: string, fn: FieldComputer): void {
    if (registry.has(name)) {
        // eslint-disable-next-line no-console
        console.warn(`[wizard] field computer '${name}' re-registered`);
    }
    registry.set(name, fn);
}

export function runFieldComputer(
    name: string,
    formState: WizardFormState,
    field: WizardFieldSchema,
    context: WizardRenderContext,
): unknown {
    const fn = registry.get(name);
    if (!fn) {
        // eslint-disable-next-line no-console
        console.warn(`[wizard] no field computer registered for '${name}'`);
        return undefined;
    }
    return fn(formState, field, context);
}

export function listFieldComputers(): string[] {
    return Array.from(registry.keys()).sort();
}

// ─── Built-in computers ──────────────────────────────────────────────
//
// These are the initial set needed by Round 2 when TemplateConfigModal
// migrates. Each is kept deliberately small — custom fields with heavy
// logic live in their own component under `customFields/` and use
// registerFieldComputer in their own module-init block.

/**
 * `prompt_template_with_metrics` — rebuild the prompt body by substituting
 * `[click to insert visibility metrics]` placeholders (legacy marker) with a markdown
 * bullet list of the currently selected metrics. If the prompt already
 * contains real content and the placeholder is gone, bail out — we never
 * overwrite a user-edited prompt.
 */
registerFieldComputer("prompt_template_with_metrics", (state, _field, ctx) => {
    const current = (state.custom_prompt as string) || "";
    const marker = "[click to insert visibility metrics]";
    if (!current.includes(marker)) return undefined;

    const metricKeys = Array.isArray(state.selected_metrics)
        ? (state.selected_metrics as string[])
        : [];
    if (metricKeys.length === 0) return undefined;

    const metricDict = ctx.dictionary.metric || [];
    const names = metricKeys
        .map((k) => {
            const row = metricDict.find((r) => r.key === k);
            return row ? `- **${row.label}** (\`${row.key}\`)` : `- \`${k}\``;
        })
        .join("\n");

    return current.replace(marker, names);
});

/**
 * `seed_default_date_range` — compute a 30-day-back date_from when a
 * `date_to` field flips to a new value. Currently only a stub — Round 2
 * hooks this up for date_range fields with relative defaults.
 */
registerFieldComputer("seed_default_date_range", (state) => {
    if (state.date_to && !state.date_from) {
        return addLocalDays(String(state.date_to), -30);
    }
    return undefined;
});
