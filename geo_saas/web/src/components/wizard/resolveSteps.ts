/**
 * Merge the scope-wide workflow_step definitions with a template's per-step
 * overrides into the list of steps the wizard actually renders.
 *
 * Dictionary rows come from `/tasks/workflow-config` (seeded by migration
 * 028/029/031). Template overrides come from `template.wizard_config.steps`.
 *
 * Resolution rules (in priority order):
 *
 *   enabled:
 *     templateOverride.enabled ?? definition.default_enabled ?? true
 *
 *   label:
 *     templateOverride.__label_override ?? definition.label
 *
 *   description:
 *     templateOverride.__description_override ?? definition.description
 *
 *   sort_order (for display):
 *     templateOverride.__sort_override ?? definition.num
 *
 * Unknown / disabled steps are dropped from the returned array. The caller
 * can filter further (for example, to build the step indicator vs. to
 * compute default values for all fields regardless of enablement).
 */
import type {
    ResolvedWizardStep,
    TemplateStepOverride,
    TemplateWizardConfig,
    WizardDictionary,
    WizardDictionaryRow,
    WizardTemplate,
    WorkflowStepDefinition,
} from "./schema";

/**
 * Normalize the raw dictionary payload from `/tasks/workflow-config` into
 * the flat `WizardDictionaryRow` shape the FieldRenderer consumes.
 *
 * Backend row shape:
 *   { config_type, scope, key, parent_key, value: { label, description, icon, ... }, sort_order }
 *
 * Frontend row shape:
 *   { key, parent_key, label, description?, icon?, sort_order?, raw }
 *
 * We hoist `label`, `description`, `icon` out of `value` so FieldRenderer
 * does not need to peek inside jsonb bags at render time. Unknown value
 * fields are preserved in `raw` for custom field components that need them.
 */
export function normalizeDictionary(
    raw: Record<string, Array<Record<string, unknown>>> | null | undefined,
): WizardDictionary {
    if (!raw) return {};
    const out: WizardDictionary = {};
    for (const [configType, rows] of Object.entries(raw)) {
        out[configType] = (rows || []).map((r) => normalizeDictionaryRow(r));
    }
    return out;
}

export function normalizeDictionaryRow(
    r: Record<string, unknown>,
): WizardDictionaryRow {
    const v = (r.value as Record<string, unknown>) || {};
    return {
        key: (r.key as string) || "",
        parent_key: (r.parent_key as string) || "",
        label: (v.label as string) || (r.key as string) || "",
        description: v.description as string | undefined,
        icon: v.icon as string | undefined,
        sort_order:
            typeof r.sort_order === "number" ? (r.sort_order as number) : undefined,
        raw: v,
    };
}

/** Normalize a raw workflow_config row's `value` into WorkflowStepDefinition. */
export function rowToWorkflowStep(row: {
    key: string;
    scope: string;
    value: Record<string, unknown>;
    sort_order: number | null;
}): WorkflowStepDefinition {
    const v = row.value || {};
    const rawFields = Array.isArray(v.fields) ? v.fields : [];
    // Shallow-copy each field so downstream mutation does not corrupt the
    // cached dictionary response. Cast via `unknown` since the backend
    // jsonb payload does not expose the exact WizardFieldSchema shape until
    // we inspect it at render time.
    const fields = rawFields.map((f) => ({
        ...(f as Record<string, unknown>),
    })) as unknown as WorkflowStepDefinition["fields"];
    return {
        key: row.key,
        scope: row.scope,
        label: (v.label as string) || row.key,
        description: (v.description as string) || "",
        icon: v.icon as string | undefined,
        num: typeof v.num === "number" ? (v.num as number) : row.sort_order || 0,
        default_enabled:
            typeof v.default_enabled === "boolean"
                ? (v.default_enabled as boolean)
                : undefined,
        group:
            v.group && typeof v.group === "object"
                ? (v.group as WorkflowStepDefinition["group"])
                : undefined,
        fields,
        raw: v,
    };
}

/**
 * Resolve a full list of workflow_step definitions against a template.
 * Returns only the steps the template wants visible, sorted by the resolved
 * order. Disabled steps are excluded — callers that need ALL steps (e.g.
 * for default-value seeding) should call `resolveAllSteps` instead.
 */
export function resolveVisibleSteps(
    definitions: WorkflowStepDefinition[],
    template: WizardTemplate | TemplateWizardConfig | null | undefined,
): ResolvedWizardStep[] {
    const all = resolveAllSteps(definitions, template);
    return all.filter((s) => s.enabled).sort((a, b) => a.num - b.num);
}

/**
 * Like `resolveVisibleSteps` but keeps disabled entries (with `enabled:false`).
 * Used when seeding defaults — disabled steps may still carry template
 * defaults that matter for submission.
 */
export function resolveAllSteps(
    definitions: WorkflowStepDefinition[],
    templateOrConfig: WizardTemplate | TemplateWizardConfig | null | undefined,
): ResolvedWizardStep[] {
    const wizardConfig = extractWizardConfig(templateOrConfig);
    const stepsOverride = (wizardConfig.steps || {}) as Record<string, TemplateStepOverride>;
    return definitions.map((def) => {
        const override = stepsOverride[def.key] || {};
        const defaultEnabled =
            typeof def.raw?.default_enabled === "boolean"
                ? (def.raw.default_enabled as boolean)
                : true;
        return {
            key: def.key,
            label: (override.__label_override as string) || def.label,
            description:
                (override.__description_override as string) || def.description,
            icon: def.icon,
            num:
                typeof override.__sort_override === "number"
                    ? (override.__sort_override as number)
                    : def.num,
            enabled:
                typeof override.enabled === "boolean"
                    ? override.enabled
                    : defaultEnabled,
            group:
                override.group && typeof override.group === "object"
                    ? (override.group as ResolvedWizardStep["group"])
                    : def.group,
            fields: def.fields,
            templateOverride: override,
        };
    });
}

/** Extract the wizard_config object from either a template or a raw config. */
function extractWizardConfig(
    input: WizardTemplate | TemplateWizardConfig | null | undefined,
): TemplateWizardConfig {
    if (!input) return {};
    // `WizardTemplate` has a `wizard_config` field; a raw config does not.
    if ((input as WizardTemplate).wizard_config !== undefined) {
        return (input as WizardTemplate).wizard_config || {};
    }
    return input as TemplateWizardConfig;
}

/**
 * Build the initial FormState map from resolved steps + template defaults.
 *
 * Order of precedence per field (weakest → strongest):
 *   1. field.default (hard-coded in the workflow_step definition)
 *   2. template.defaults[field.key] (legacy — geo_report_templates.defaults)
 *   3. template.wizard_config.steps[stepKey][field.key] (new override)
 *
 * Disabled steps still contribute defaults (a hidden step with
 * `default_count = 5` should still carry that value into submission).
 */
export function seedInitialFormState(
    resolvedSteps: ResolvedWizardStep[],
    template?: WizardTemplate | null,
): Record<string, unknown> {
    const out: Record<string, unknown> = {};
    const legacyDefaults: Record<string, unknown> =
        (template?.defaults as Record<string, unknown>) || {};

    for (const step of resolvedSteps) {
        for (const field of step.fields) {
            // 1. hard-coded default
            if (field.default !== undefined) {
                out[field.key] = field.default;
            }
            // 2. legacy defaults bag
            if (legacyDefaults[field.key] !== undefined) {
                out[field.key] = legacyDefaults[field.key];
            }
            // 3. per-step override — strongest
            const override = step.templateOverride[field.key];
            if (override !== undefined) {
                out[field.key] = override;
            }
        }
    }
    return out;
}
