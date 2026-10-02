/**
 * Schema-driven wizard — TypeScript contracts
 * ============================================
 *
 * These types describe the JSON shape that the SaaS wizard expects from the
 * backend (geo_agent `/tasks/workflow-config` and `/tasks/templates/{id}`
 * endpoints). The runtime data is seeded by migrations 028 / 029 / 031 into
 * the `geo_workflow_config` and `geo_report_templates.wizard_config` tables.
 *
 * The three layers:
 *
 *   1. WorkflowStepDefinition — one row in `geo_workflow_config` with
 *      config_type = 'workflow_step'. Defines the canonical shape of a step
 *      (label, description, icon, ordered list of fields). Scope-wide:
 *      every template in that scope sees the same list of *possible* steps.
 *
 *   2. Template.wizard_config.steps[stepKey] — per-template override layer.
 *      Holds default values that the template wants to pre-fill for each
 *      field in that step, plus optional reserved meta keys (`enabled`,
 *      `__sort_override`, `__label_override`) that can hide or re-label a
 *      step for that specific template.
 *
 *   3. FormState — the live, per-task form state that the user is editing.
 *      Flat map keyed by field key. Submitted as `inputs` to `createAgentTask`.
 *
 * The FieldRenderer + GenericStepRenderer consume (1) + (2) and produce (3).
 */

/** Base primitive types supported out of the box by FieldRenderer. */
export type WizardFieldPrimitiveType =
    | "text"
    | "textarea"
    | "number"
    | "boolean"
    | "single_ref"
    | "multi_ref"
    | "date_range"
    | "date"
    | "checkbox_group";

/** Custom field types — each maps to a React component in the
 *  customFieldRegistry. Keep this union in sync with the registry keys. */
export type WizardFieldCustomType =
    | "chart_builder"
    | "prompt_editor"
    | "analyzer_import"
    | "strategy_generator"
    | "prompt_ref_picker"
    | "product_facts_form"
    | "reddit_discovery_config"
    | "official_website_discovery_config"
    | "citation_analysis_preflight"
    | "subreddit_targeting_preflight"
    | "reddit_discovery_preflight"
    | "prompt_artifact_preparation_preflight"
    | "metric_ref_multi"
    | "platform_picker"
    | "peer_picker";

export type WizardFieldType = WizardFieldPrimitiveType | WizardFieldCustomType;

/**
 * One field inside a workflow step. Matches the JSON shape written to
 * `geo_workflow_config.value.fields[*]` (see migration 029 sections H + I
 * for concrete examples).
 */
export interface WizardFieldSchema {
    /** Stable identifier — used as the key in FormState. Snake_case. */
    key: string;
    type: WizardFieldType;
    /** Human-readable label shown above the field. */
    label?: string;
    /** Short helper text shown under the field. */
    description?: string;
    /** Hard-coded default if no template override and no computed default. */
    default?: unknown;
    /** Marks the field as required for form submission. */
    required?: boolean;
    /** For `single_ref` / `multi_ref`: the config_type key in the dictionary
     *  map returned by `/tasks/workflow-config`. */
    ref_config_type?: string;
    /** Optional: pin the ref lookup to a specific scope (defaults to the
     *  wizard's current scope). */
    ref_scope?: string;
    /** For `multi_ref`: minimum / maximum selection counts. */
    min_select?: number;
    max_select?: number;
    /** Declarative dependency list. When any of these field keys change in
     *  FormState, `compute_default` (if set) re-runs to recompute this
     *  field's default value. */
    depends_on?: string[];
    /** Name of a frontend-registered computer function (see
     *  `fieldComputers.ts`). Called as
     *  `computer(formState, field, context) => newValue`. */
    compute_default?: string;
    /** Optional visibility predicate — name of a registered function that
     *  returns whether this field should be shown. Allows conditional
     *  fields without baking the condition into the field's type. */
    visible_when?: string;
    /** Free-form extra config passed through to custom field components. */
    config?: Record<string, unknown>;
}

/**
 * One workflow step. Matches `geo_workflow_config.value` for
 * `config_type = 'workflow_step'` rows.
 */
export interface WorkflowStepDefinition {
    /** e.g. "analysis_goal", "content_framework". */
    key: string;
    /** Scope — "analysis" or "content_generation". */
    scope: string;
    /** Canonical display label. */
    label: string;
    description?: string;
    /** Optional lucide-react icon name (same convention as admin-side). */
    icon?: string;
    /** Step index (1-based). */
    num: number;
    /** Defaults whether the step is visible when a template has no override. */
    default_enabled?: boolean;
    /** Ordered list of fields rendered inside this step. */
    fields: WizardFieldSchema[];
    group?: {
        key: string;
        label: string;
        description?: string;
    };
    /** Raw row for debugging / power-user access. */
    raw?: Record<string, unknown>;
}

/**
 * One dictionary row that can be referenced by a `single_ref` / `multi_ref`
 * field. Returned by `/tasks/workflow-config` as part of the `dictionary`
 * map (keyed by config_type).
 */
export interface WizardDictionaryRow {
    key: string;
    parent_key: string;
    /** Resolved display label (may be bilingual). */
    label: string;
    description?: string;
    /** Optional lucide-react icon name. */
    icon?: string;
    sort_order?: number;
    /** The full raw value dict from the workflow_config row. */
    raw?: Record<string, unknown>;
}

/** Map of config_type → rows. */
export type WizardDictionary = Record<string, WizardDictionaryRow[]>;

/**
 * Per-template override for a single step. Lives at
 * `template.wizard_config.steps[stepKey]`. Field keys map to their default
 * values; reserved `__*` keys control meta-level behavior.
 */
export interface TemplateStepOverride {
    /** If set, overrides the workflow step's default visibility. */
    enabled?: boolean;
    group?: {
        key: string;
        label: string;
        description?: string;
    };
    /** Overrides the canonical sort_order for this template only. */
    __sort_override?: number;
    /** Overrides the canonical label for this template only. */
    __label_override?: string;
    /** Overrides the canonical description for this template only. */
    __description_override?: string;
    /** All other keys are field defaults. Shape:
     *    [fieldKey]: defaultValue
     *  Example (migration 029 J.1):
     *    { "default_goal": "health" }
     */
    [fieldKey: string]: unknown;
}

/**
 * Full `template.wizard_config` JSONB payload. Matches what the admin
 * WizardConfigEditor writes. Deliberately loose: unknown keys are preserved
 * so backend-only fields don't get dropped on round-trip.
 */
export interface TemplateWizardConfig {
    version?: number;
    required_metrics?: string[];
    required_chapters?: string[];
    required_subgoals?: string[];
    steps?: Record<string, TemplateStepOverride>;
    [k: string]: unknown;
}

/**
 * The shape returned by `GET /api/agent/tasks/templates/{id}` and
 * `GET /api/agent/tasks/templates`. Parsed jsonb fields are always plain
 * objects / arrays — the backend calls `_parse_jsonb` before serialization.
 */
export interface WizardTemplate {
    id: string;
    name: string;
    description?: string;
    icon?: string;
    data_domains?: string[];
    default_prompt?: string;
    is_builtin?: boolean;
    task_type: string;
    wizard_config: TemplateWizardConfig;
    filters?: Record<string, unknown>;
    chart_requests?: unknown[];
    defaults?: Record<string, unknown>;
}

/** The full payload returned by `GET /tasks/workflow-config?scope=...`. */
export interface WizardWorkflowConfigPayload {
    scope: string;
    steps: WorkflowStepDefinition[];
    dictionary: WizardDictionary;
}

/**
 * The live form state. Flat map keyed by field key. The GenericStepRenderer
 * and FieldRenderer both read and write this object via the reducer in
 * `useWizardFormState`.
 */
export type WizardFormState = Record<string, unknown>;

/**
 * Additional context passed into custom field components and field-computer
 * functions. Exposes everything a field might need without turning every
 * component prop list into a shopping list.
 */
export interface WizardRenderContext {
    /** 'analysis' | 'content_generation'. */
    scope: string;
    /** Active template id (for backend calls like generate-strategy). */
    templateId?: string;
    /** Multi-tenant client id — required by most backend calls. */
    clientId: string;
    /** Current user id. */
    userId: string;
    /** Dictionary map for resolving `ref_*` field options. */
    dictionary: WizardDictionary;
    /** All step definitions — some custom fields need cross-step lookups. */
    steps: WorkflowStepDefinition[];
    /** Full template payload (custom fields sometimes need `defaults`). */
    template?: WizardTemplate;
}

/**
 * Result of resolving a workflow step against a template override. This is
 * what the GenericStepRenderer actually renders.
 */
export interface ResolvedWizardStep {
    key: string;
    label: string;
    description?: string;
    icon?: string;
    num: number;
    enabled: boolean;
    fields: WizardFieldSchema[];
    group?: {
        key: string;
        label: string;
        description?: string;
    };
    /** The raw template override, for debugging / custom field access. */
    templateOverride: TemplateStepOverride;
}
