/**
 * Wizard barrel — single import surface for the schema-driven wizard.
 *
 * Consumers should import from `@/components/wizard` rather than reaching
 * into individual files. Round 2 will add a `WizardShell` entry point
 * that TemplateConfigModal + ContentPipelineModal can both mount.
 */
export type {
    WizardFieldSchema,
    WizardFieldType,
    WizardFieldPrimitiveType,
    WizardFieldCustomType,
    WorkflowStepDefinition,
    WizardDictionary,
    WizardDictionaryRow,
    TemplateStepOverride,
    TemplateWizardConfig,
    WizardTemplate,
    WizardWorkflowConfigPayload,
    WizardFormState,
    WizardRenderContext,
    ResolvedWizardStep,
} from "./schema";

export {
    rowToWorkflowStep,
    resolveVisibleSteps,
    resolveAllSteps,
    seedInitialFormState,
    normalizeDictionary,
    normalizeDictionaryRow,
} from "./resolveSteps";

export {
    registerFieldComputer,
    runFieldComputer,
    listFieldComputers,
} from "./fieldComputers";

export {
    registerCustomField,
    getCustomField,
    listCustomFields,
} from "./customFieldRegistry";

export type {
    CustomFieldProps,
    CustomFieldComponent,
} from "./customFieldRegistry";

export { FieldRenderer } from "./FieldRenderer";
export type { FieldRendererProps } from "./FieldRenderer";

export { GenericStepRenderer } from "./GenericStepRenderer";
export type { GenericStepRendererProps } from "./GenericStepRenderer";

export { WizardShell } from "./WizardShell";
export type { WizardShellProps, WizardShellAction } from "./WizardShell";

export {
    useWizardFormState,
} from "./useWizardFormState";
export type {
    UseWizardFormStateOptions,
    UseWizardFormStateResult,
    WizardFormAction,
    WizardFormInternalState,
} from "./useWizardFormState";
