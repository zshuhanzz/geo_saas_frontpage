import type { WizardFormState, WizardTemplate } from "../schema";

function templateCitationStep(template?: WizardTemplate | null): Record<string, unknown> {
    return (
        ((template?.wizard_config?.steps as Record<string, unknown> | undefined)
            ?.citation_analysis as Record<string, unknown> | undefined) || {}
    );
}

function templateCitationTop(template?: WizardTemplate | null): Record<string, unknown> {
    return (
        (template?.wizard_config?.citation_analysis as Record<string, unknown> | undefined) || {}
    );
}

export function isCitationAnalysisEnabled(template?: WizardTemplate | null): boolean {
    const step = templateCitationStep(template);
    const top = templateCitationTop(template);
    return typeof step.enabled === "boolean" ? step.enabled : Boolean(top.enabled);
}

export function buildCitationAnalysisConfig(
    formState: WizardFormState,
    template?: WizardTemplate | null,
): Record<string, unknown> {
    const step = templateCitationStep(template);
    return {
        enabled: isCitationAnalysisEnabled(template),
        citation_source_scope:
            (formState.citation_source_scope as string | undefined) ||
            (step.citation_source_scope as string | undefined) ||
            "auto_by_template",
        citation_brand_mention_policy:
            (formState.citation_brand_mention_policy as string | undefined) ||
            (step.citation_brand_mention_policy as string | undefined) ||
            "triage_all",
        citation_action_strategy:
            (formState.citation_action_strategy as string | undefined) ||
            (step.citation_action_strategy as string | undefined) ||
            "auto",
        citation_max_sources:
            Number(formState.citation_max_sources ?? step.citation_max_sources) || 10,
        citation_fetch_full_pages:
            formState.citation_fetch_full_pages !== undefined
                ? Boolean(formState.citation_fetch_full_pages)
                : step.citation_fetch_full_pages !== undefined
                  ? Boolean(step.citation_fetch_full_pages)
                  : true,
        citation_include_domains:
            (formState.citation_include_domains as string | undefined) ||
            (step.citation_include_domains as string | undefined) ||
            "",
        citation_exclude_domains:
            (formState.citation_exclude_domains as string | undefined) ||
            (step.citation_exclude_domains as string | undefined) ||
            "",
        citation_query_override:
            (formState.citation_query_override as string | undefined) ||
            (step.citation_query_override as string | undefined) ||
            "",
    };
}

export function buildCitationAnalysisInputs(
    formState: WizardFormState,
    template?: WizardTemplate | null,
): Record<string, unknown> {
    const contentType =
        (formState.default as string | undefined) ||
        (formState.content_type as string | undefined) ||
        "";
    return {
        content_type: contentType,
        publish_platform:
            (formState.default_publish_platform as string | undefined) || "",
        target_prompt_ids: (formState.prompt_ids as string[] | undefined) || [],
        topic_ids: (formState.topic_ids as string[] | undefined) || [],
        citation_analysis: buildCitationAnalysisConfig(formState, template),
    };
}

export function getCitationAnalysisResult(
    formState: WizardFormState,
): Record<string, unknown> | null {
    const value = formState.citation_analysis_result;
    return value && typeof value === "object" ? (value as Record<string, unknown>) : null;
}
