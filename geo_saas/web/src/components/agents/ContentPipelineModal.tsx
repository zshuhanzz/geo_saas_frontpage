/**
 * ContentPipelineModal — Content wizard host (Round 3: schema-driven).
 *
 * The modal used to own 7 hand-coded Node* components (NodeAnalyzerImport,
 * NodeContentGoals, NodeContentType, NodeStrategy, NodeGenConfig,
 * NodePromptLink, NodeConfirm) plus a dozen useState slices for the
 * PipelineState. Round 3 migrates it to a thin shell around `<WizardShell>`:
 * the wizard fetches `/tasks/workflow-config?scope=content_generation`,
 * resolves it against `template.wizard_config`, and hands back a plain
 * FormState on submit.
 *
 * This file now only owns:
 *
 *   1. Dialog chrome + Anthony header
 *   2. Submit handlers — `executeTask(formState)` + `saveDraft(formState)`
 *      that map the schema FormState into the content_generation
 *      pipeline inputs contract
 *   3. Initial-values plumbing for the two resume flows:
 *        a. preselectedAnalyzerTaskId — CTA from Analyzer page
 *        b. existingTaskId — "edit task" flow from the All Tasks list
 *   4. executing state + toast feedback
 *
 * Everything else — step ordering, field labels, default values, node UX,
 * analyzer import cards, strategy generation, prompt picker, product facts
 * form — comes from the DB via the schema-driven wizard layer.
 */
import { useCallback, useEffect, useState, useMemo } from "react";
import { toast } from "sonner";
import { Loader2, Save, Play, X } from "lucide-react";
import { Trans, useTranslation } from "react-i18next";
import { fetchJSON, API_BASE } from "@/lib/api";
import { Switch } from "@/components/ui/switch";
import {
    Dialog,
    DialogContent,
    DialogTitle,
    DialogDescription,
} from "@/components/ui/dialog";
import {
    createAgentTask,
    updateAgentTask,
    getAgentTask,
} from "@/lib/api";

import { WizardShell } from "@/components/wizard";
import {
    buildCitationAnalysisConfig,
    getCitationAnalysisResult,
    isCitationAnalysisEnabled,
} from "@/components/wizard/customFields/citationAnalysisUtils";
import {
    promptArtifactInputFingerprint,
    redditDiscoveryInputFingerprint,
    redditRulesReviewComplete,
} from "@/components/wizard/customFields/redditResearchUtils";
import type {
    WizardFormState,
    WizardTemplate,
    TemplateWizardConfig,
} from "@/components/wizard";

// ─────────────────────────────────────────────────────────────────────────────
// Types
// ─────────────────────────────────────────────────────────────────────────────
export interface ContentTemplate {
    id: string;
    name: string;
    icon?: string;
    description?: string;
    data_domains?: string[];
    default_prompt?: string;
    defaults?: Record<string, unknown>;
    wizard_config?: TemplateWizardConfig | Record<string, unknown> | string | null;
}

interface ContentPipelineModalProps {
    open: boolean;
    clientId: string;
    userId: string;
    clientPlatforms: string[];
    preselectedAnalyzerTaskId?: string | null;
    existingTaskId?: string | null;
    /** Selected content template — drives wizard_config overrides + defaults. */
    template?: ContentTemplate | null;
    onClose: () => void;
    onTaskCreated?: () => void;
}

// ─────────────────────────────────────────────────────────────────────────────
// wizard_config normalization — backend may serialize jsonb as a string.
// ─────────────────────────────────────────────────────────────────────────────
function normalizeWizardConfig(
    raw: TemplateWizardConfig | Record<string, unknown> | string | null | undefined,
): TemplateWizardConfig {
    if (!raw) return {};
    if (typeof raw === "string") {
        try {
            return JSON.parse(raw) as TemplateWizardConfig;
        } catch {
            return {};
        }
    }
    return raw as TemplateWizardConfig;
}

// ─────────────────────────────────────────────────────────────────────────────
// FormState → content_generation pipeline inputs contract.
// Keeping this mapping in one place makes it trivial to audit the contract
// whenever migrations change a field key.
// ─────────────────────────────────────────────────────────────────────────────
interface ContentTaskInputs {
    analyzer_task_id: string | null;
    analyzer_context: Record<string, unknown> | null;
    selected_metrics: string[];
    selected_subgoals: string[];
    content_type: string;
    strategy?: unknown;
    user_strategy_edits: string | null;
    ai_platforms: string[];
    publish_platform: string;
    language: string;
    count: number;
    product_facts: { specs: string; features: string; differentiators: string };
    target_prompt_ids: string[];
    topic_ids: string[];
    subreddit_targeting?: Record<string, unknown> | null;
    reddit_discovery?: Record<string, unknown> | null;
    official_website_discovery?: Record<string, unknown> | null;
    citation_analysis?: Record<string, unknown> | null;
    citation_analysis_result?: Record<string, unknown> | null;
    derived_prompt_artifacts?: Record<string, unknown> | null;
    derived_prompt_artifacts_source?: string | null;
    derived_prompt_artifacts_edited?: boolean;
    include_data_disclosure: boolean;
    depth: string | null;
    model_id?: string;
    search_grounding_enabled: boolean;
    cron_expression?: string | null;
}

interface AnalyzerImportValue {
    task_id?: string;
    context?: Record<string, unknown> | null;
}

interface StrategyValue {
    data?: unknown;
    user_strategy_edits?: string | null;
}

function buildTaskInputs(
    formState: WizardFormState,
    template?: WizardTemplate | null,
    modelId?: string,
    cronExpression?: string,
    searchGroundingEnabled = false,
): ContentTaskInputs {
    const analyzerVal = formState.analyzer_task_id as
        | AnalyzerImportValue
        | string
        | null
        | undefined;
    const analyzerTaskId =
        analyzerVal && typeof analyzerVal === "object"
            ? analyzerVal.task_id || null
            : typeof analyzerVal === "string"
              ? analyzerVal
              : null;
    const analyzerContext =
        analyzerVal && typeof analyzerVal === "object"
            ? analyzerVal.context || null
            : null;

    const strategyVal = formState.strategy as StrategyValue | undefined;
    const userStrategyEdits =
        (strategyVal && strategyVal.user_strategy_edits) || null;

    const facts = (formState.default_product_facts as
        | { specs?: string; features?: string; differentiators?: string }
        | undefined) || {};

    // content_type is stored under field key `default` per migration 031
    // (the content_type step has a single_ref field keyed `default`). We
    // also accept `content_type` as a fallback for forward-compat seeds.
    const contentType =
        (formState.default as string | undefined) ||
        (formState.content_type as string | undefined) ||
        "";

    return {
        analyzer_task_id: analyzerTaskId,
        analyzer_context: analyzerContext,
        selected_metrics: (formState.default_metrics as string[] | undefined) || [],
        selected_subgoals:
            (formState.default_sub_goals as string[] | undefined) || [],
        content_type: contentType,
        strategy: strategyVal?.data || null,
        user_strategy_edits: userStrategyEdits,
        ai_platforms: (formState.default_ai_platforms as string[] | undefined) || [],
        publish_platform:
            (formState.default_publish_platform as string | undefined) || "",
        language: (formState.default_language as string | undefined) || "en-US",
        count: Number(formState.default_count) || 5,
        product_facts: {
            specs: facts.specs || "",
            features: facts.features || "",
            differentiators: facts.differentiators || "",
        },
        target_prompt_ids: (formState.prompt_ids as string[] | undefined) || [],
        topic_ids: (formState.topic_ids as string[] | undefined) || [],
        subreddit_targeting:
            (formState.subreddit_targeting as Record<string, unknown> | undefined) || null,
        reddit_discovery:
            (formState.reddit_discovery as Record<string, unknown> | undefined) || null,
        official_website_discovery:
            (formState.official_website_discovery as Record<string, unknown> | undefined) || null,
        citation_analysis: buildCitationAnalysisConfig(formState, template),
        citation_analysis_result: getCitationAnalysisResult(formState),
        derived_prompt_artifacts:
            (formState.derived_prompt_artifacts as Record<string, unknown> | undefined) || null,
        derived_prompt_artifacts_source:
            (formState.derived_prompt_artifacts_source as string | undefined) || null,
        derived_prompt_artifacts_edited: Boolean(formState.derived_prompt_artifacts_edited),
        include_data_disclosure: formState.include_data_disclosure !== false,
        depth: (formState.default_depth as string | null | undefined) || null,
        model_id: modelId || undefined,
        search_grounding_enabled: searchGroundingEnabled,
        cron_expression: cronExpression || null,
    };
}

// ─────────────────────────────────────────────────────────────────────────────
// Build the initial FormState for the wizard — pre-fills the `analyzer_task_id`
// field when the modal is opened from the Analyzer CTA or an edit action.
// Everything else flows from template.wizard_config defaults (resolved inside
// WizardShell via seedInitialFormState).
// ─────────────────────────────────────────────────────────────────────────────
function buildInitialValues(opts: {
    preselectedAnalyzer: { task_id: string; context: Record<string, unknown> | null } | null;
    existingInputs: Record<string, unknown> | null;
}): WizardFormState {
    const out: WizardFormState = {};

    if (opts.preselectedAnalyzer) {
        out.analyzer_task_id = {
            task_id: opts.preselectedAnalyzer.task_id,
            context: opts.preselectedAnalyzer.context,
        };
    }

    if (opts.existingInputs) {
        const ei = opts.existingInputs as Record<string, unknown>;
        // Map the persisted task inputs back into schema field keys so the
        // user resumes the edit flow with everything pre-populated.
        if (ei.analyzer_task_id || ei.analyzer_context) {
            out.analyzer_task_id = {
                task_id: (ei.analyzer_task_id as string) || null,
                context: (ei.analyzer_context as Record<string, unknown>) || null,
            };
        }
        if (Array.isArray(ei.selected_metrics))
            out.default_metrics = ei.selected_metrics;
        if (Array.isArray(ei.selected_subgoals))
            out.default_sub_goals = ei.selected_subgoals;
        if (typeof ei.content_type === "string") {
            out.default = ei.content_type;
            out.content_type = ei.content_type;
        }
        if (typeof ei.user_strategy_edits === "string") {
            out.strategy = {
                data: null,
                user_strategy_edits: ei.user_strategy_edits,
                status: "idle",
            };
        }
        if (Array.isArray(ei.ai_platforms)) out.default_ai_platforms = ei.ai_platforms;
        if (typeof ei.publish_platform === "string")
            out.default_publish_platform = ei.publish_platform;
        if (typeof ei.language === "string") out.default_language = ei.language;
        if (typeof ei.count === "number") out.default_count = ei.count;
        if (ei.product_facts && typeof ei.product_facts === "object")
            out.default_product_facts = ei.product_facts;
        if (Array.isArray(ei.target_prompt_ids)) out.prompt_ids = ei.target_prompt_ids;
        if (ei.subreddit_targeting && typeof ei.subreddit_targeting === "object")
            out.subreddit_targeting = ei.subreddit_targeting;
        if (ei.subreddit_targeting && typeof ei.subreddit_targeting === "object") {
            const st = ei.subreddit_targeting as Record<string, unknown>;
            out.subreddit_targeting_preflight = {
                status: st.status === "ready" ? "ready" : "idle",
                error: null,
                input_fingerprint: st.input_fingerprint || null,
                generated_at: st.generated_at || null,
            };
        }
        if (ei.reddit_discovery && typeof ei.reddit_discovery === "object")
            out.reddit_discovery = ei.reddit_discovery;
        if (ei.reddit_discovery && typeof ei.reddit_discovery === "object") {
            const rd = ei.reddit_discovery as Record<string, unknown>;
            out.reddit_discovery_preflight = {
                status: redditRulesReviewComplete(rd) ? "ready" : "error",
                error: redditRulesReviewComplete(rd) ? null : "Rules review is required",
                input_fingerprint: rd.input_fingerprint || null,
                generated_at: rd.generated_at || null,
            };
        }
        if (ei.official_website_discovery && typeof ei.official_website_discovery === "object")
            out.official_website_discovery = ei.official_website_discovery;
        if (ei.derived_prompt_artifacts && typeof ei.derived_prompt_artifacts === "object")
            out.derived_prompt_artifacts = ei.derived_prompt_artifacts;
        if (ei.derived_prompt_artifacts && typeof ei.derived_prompt_artifacts === "object") {
            const artifacts = ei.derived_prompt_artifacts as Record<string, unknown>;
            out.prompt_artifact_preparation = {
                status: artifacts.status === "ready" ? "ready" : "idle",
                error: null,
                input_fingerprint: artifacts.input_fingerprint || null,
                generated_at: artifacts.generated_at || null,
            };
        }
        if (typeof ei.derived_prompt_artifacts_source === "string")
            out.derived_prompt_artifacts_source = ei.derived_prompt_artifacts_source;
        if (typeof ei.derived_prompt_artifacts_edited === "boolean")
            out.derived_prompt_artifacts_edited = ei.derived_prompt_artifacts_edited;
        if (ei.citation_analysis && typeof ei.citation_analysis === "object") {
            const ca = ei.citation_analysis as Record<string, unknown>;
            if (typeof ca.citation_source_scope === "string")
                out.citation_source_scope = ca.citation_source_scope;
            if (typeof ca.citation_brand_mention_policy === "string")
                out.citation_brand_mention_policy = ca.citation_brand_mention_policy;
            if (typeof ca.citation_action_strategy === "string")
                out.citation_action_strategy = ca.citation_action_strategy;
            if (typeof ca.citation_max_sources === "number")
                out.citation_max_sources = ca.citation_max_sources;
            if (typeof ca.citation_fetch_full_pages === "boolean")
                out.citation_fetch_full_pages = ca.citation_fetch_full_pages;
            if (typeof ca.citation_include_domains === "string")
                out.citation_include_domains = ca.citation_include_domains;
            if (typeof ca.citation_exclude_domains === "string")
                out.citation_exclude_domains = ca.citation_exclude_domains;
            if (typeof ca.citation_query_override === "string")
                out.citation_query_override = ca.citation_query_override;
        }
        if (ei.citation_analysis_result && typeof ei.citation_analysis_result === "object") {
            const car = ei.citation_analysis_result as Record<string, unknown>;
            out.citation_analysis_result = car;
            out.citation_analysis_preflight = {
                status: car.enabled ? "ready" : "idle",
                error: null,
                fingerprint: car.fingerprint || null,
                generated_at: car.generated_at || null,
            };
        }
        if (typeof ei.include_data_disclosure === "boolean")
            out.include_data_disclosure = ei.include_data_disclosure;
        if (typeof ei.depth === "string") out.default_depth = ei.depth;
    }

    return out;
}

function requiresRedditConfirmedArtifacts(template?: WizardTemplate | null): boolean {
    const config = template?.wizard_config as Record<string, unknown> | undefined;
    const redditResearch = config?.reddit_research as Record<string, unknown> | undefined;
    const artifact = redditResearch?.artifact_preparation as Record<string, unknown> | undefined;
    return Boolean(
        redditResearch?.enabled === true &&
        artifact?.reuse_confirmed_artifacts_in_final_generation === true &&
        artifact?.allow_runtime_generation !== true,
    );
}

// ─────────────────────────────────────────────────────────────────────────────
// Main Modal
// ─────────────────────────────────────────────────────────────────────────────
export default function ContentPipelineModal({
    open,
    clientId,
    userId,
    preselectedAnalyzerTaskId,
    existingTaskId,
    template,
    onClose,
    onTaskCreated,
}: ContentPipelineModalProps) {
    const { t } = useTranslation("content");
    const [executing, setExecuting] = useState(false);
    const [saving, setSaving] = useState(false);
    const [taskId, setTaskId] = useState<string | null>(existingTaskId || null);
    const [initialValues, setInitialValues] = useState<WizardFormState>({});
    const [bootstrapping, setBootstrapping] = useState(false);
    // Monotonic key that forces WizardShell to re-seed its internal FormState
    // when we bump it (used on open/reset so stale state from a previous
    // modal session cannot leak).
    const [shellKey, setShellKey] = useState(0);

    // ── Host-level runtime settings (model + cron, not owned by any step) ──
    const [modelIds, setModelIds] = useState<string[]>([]);
    const [modelId, setModelId] = useState("");
    const [searchGroundingEnabled, setSearchGroundingEnabled] = useState(false);
    const [cronExpression, setCronExpression] = useState("");
    const [currentFormState, setCurrentFormState] = useState<WizardFormState>({});

    useEffect(() => {
        fetchJSON(`${API_BASE}/settings/config?key=content_generation_model_list`)
            .then((data: { value?: string }) => {
                const ids = data?.value
                    ? data.value.split(",").map((m: string) => m.trim()).filter(Boolean)
                    : [];
                setModelIds(ids);
                setModelId((prev) => prev || ids[0] || "");
            })
            .catch(() => {});
    }, []);

    // Normalize the template once per template change so WizardShell always
    // receives a plain object.
    const wizardTemplate: WizardTemplate | null = useMemo(() => {
        if (!template) return null;
        return {
            id: template.id,
            name: template.name,
            description: template.description,
            icon: template.icon,
            data_domains: template.data_domains,
            default_prompt: template.default_prompt,
            task_type: "content_generation",
            wizard_config: normalizeWizardConfig(template.wizard_config),
            defaults: template.defaults,
        };
    }, [template]);

    // ─── Reset state when modal opens ───────────────────────────────────
    useEffect(() => {
        if (!open) return;
        setExecuting(false);
        setSaving(false);
        setTaskId(existingTaskId || null);
        setInitialValues({});
        setCurrentFormState({});
        setSearchGroundingEnabled(false);
        setShellKey((k) => k + 1);
    }, [open, existingTaskId]);

    // ─── Bootstrap: load preselected analyzer context and/or existing task
    // inputs before rendering the shell so the shell's seed pass can pick
    // everything up on the first render. ─────────────────────────────────
    useEffect(() => {
        if (!open) return;
        if (!clientId) return;
        if (!preselectedAnalyzerTaskId && !existingTaskId) return;

        let cancelled = false;
        setBootstrapping(true);

        (async () => {
            let preselected: {
                task_id: string;
                context: Record<string, unknown> | null;
            } | null = null;
            let existingInputs: Record<string, unknown> | null = null;

            try {
                if (preselectedAnalyzerTaskId) {
                    const task = await getAgentTask(
                        preselectedAnalyzerTaskId,
                        clientId,
                    );
                    preselected = {
                        task_id: preselectedAnalyzerTaskId,
                        context: (task.output as Record<string, unknown>) || null,
                    };
                }
            } catch {
                toast.error(t("pipelineModal.toasts.loadAnalysisFailed"));
            }

            try {
                if (existingTaskId) {
                    const task = await getAgentTask(existingTaskId, clientId);
                    const raw =
                        typeof task.inputs === "string"
                            ? JSON.parse(task.inputs)
                            : task.inputs;
                    existingInputs = (raw as Record<string, unknown>) || null;
                }
            } catch {
                // silent — just open a blank wizard
            }

            if (cancelled) return;
            setInitialValues(
                buildInitialValues({
                    preselectedAnalyzer: preselected,
                    existingInputs,
                }),
            );
            setShellKey((k) => k + 1);
            setBootstrapping(false);
        })();

        return () => {
            cancelled = true;
        };
    }, [open, clientId, preselectedAnalyzerTaskId, existingTaskId]);

    // ─── Submit handlers — receive the schema-driven FormState ───────────
    const executeTask = useCallback(
        async (formState: WizardFormState) => {
            if (!clientId) return;
            if (isCitationAnalysisEnabled(wizardTemplate) && !getCitationAnalysisResult(formState)) {
                toast.error(t("pipelineModal.toasts.citationPreflightRequired"));
                return;
            }
            if (requiresRedditConfirmedArtifacts(wizardTemplate)) {
                const artifacts = formState.derived_prompt_artifacts as Record<string, unknown> | undefined;
                const discovery = formState.reddit_discovery as Record<string, unknown> | undefined;
                if (!redditRulesReviewComplete(formState.reddit_discovery)) {
                    toast.error(t("pipelineModal.toasts.redditRulesReviewRequired"));
                    return;
                }
                if (!discovery?.input_fingerprint || discovery.input_fingerprint !== redditDiscoveryInputFingerprint(formState)) {
                    toast.error(t("pipelineModal.toasts.redditDiscoveryStale"));
                    return;
                }
                if (!artifacts || artifacts.source !== "wizard_confirmed" || artifacts.status !== "ready") {
                    toast.error(t("pipelineModal.toasts.redditArtifactsRequired"));
                    return;
                }
                if (!artifacts.input_fingerprint || artifacts.input_fingerprint !== promptArtifactInputFingerprint(formState)) {
                    toast.error(t("pipelineModal.toasts.redditArtifactsStale"));
                    return;
                }
            }
            setExecuting(true);
            try {
                const inputs = buildTaskInputs(formState, wizardTemplate, modelId, cronExpression, searchGroundingEnabled);
                if (taskId) {
                    await updateAgentTask(taskId, {
                        client_id: clientId,
                        user_id: userId,
                        inputs,
                        save_only: false,
                    });
                } else {
                    await createAgentTask({
                        client_id: clientId,
                        user_id: userId,
                        task_type: "content_generation",
                        task_name: `${template?.name || t("pipelineModal.defaultTaskName")} - ${new Date().toLocaleDateString()}`,
                        template_id: template?.id || undefined,
                        inputs,
                        save_only: false,
                    });
                }
                toast.success(t("pipelineModal.toasts.taskStarted"));
                onTaskCreated?.();
                onClose();
            } catch (e) {
                const msg = e instanceof Error ? e.message : String(e);
                toast.error(t("pipelineModal.toasts.taskCreateFailed", { message: msg }));
            } finally {
                setExecuting(false);
            }
        },
        [taskId, clientId, userId, template, wizardTemplate, modelId, cronExpression, searchGroundingEnabled, onTaskCreated, onClose],
    );

    const saveDraft = useCallback(
        async (formState: WizardFormState) => {
            if (!clientId) return;
            setSaving(true);
            try {
                const inputs = buildTaskInputs(formState, wizardTemplate, modelId, cronExpression, searchGroundingEnabled);
                if (taskId) {
                    await updateAgentTask(taskId, {
                        client_id: clientId,
                        user_id: userId,
                        inputs,
                        save_only: true,
                    });
                } else {
                    const res = await createAgentTask({
                        client_id: clientId,
                        user_id: userId,
                        task_type: "content_generation",
                        task_name: `${template?.name || t("pipelineModal.defaultTaskName")} ${t("pipelineModal.draftSuffix")} - ${new Date().toLocaleDateString()}`,
                        template_id: template?.id || undefined,
                        inputs,
                        save_only: true,
                    });
                    setTaskId((res as { id: string }).id);
                }
                toast.success(t("pipelineModal.toasts.draftSaved"));
                onTaskCreated?.();
            } catch (e) {
                const msg = e instanceof Error ? e.message : String(e);
                toast.error(t("pipelineModal.toasts.saveFailed", { message: msg }));
            } finally {
                setSaving(false);
            }
        },
        [taskId, clientId, userId, template, wizardTemplate, modelId, cronExpression, searchGroundingEnabled, onTaskCreated],
    );

    const handleWizardSubmit = useCallback(
        async (formState: WizardFormState, actionKey: string) => {
            if (actionKey === "save_draft") {
                await saveDraft(formState);
            } else if (actionKey === "execute") {
                await executeTask(formState);
            }
        },
        [saveDraft, executeTask],
    );

    const runtimeSettingsBar = modelIds.length > 0 ? (
        <div className="border border-border/60 rounded-lg p-4 bg-muted/10 space-y-3">
            <div className="flex items-center gap-3 flex-wrap">
                <span className="text-xs font-medium text-muted-foreground shrink-0">
                    {t("pipelineModal.genModelLabel")}
                </span>
                <div className="flex items-center gap-2 flex-wrap">
                    {modelIds.map((m) => (
                        <button
                            key={m}
                            type="button"
                            onClick={() => setModelId(m)}
                            className={`px-3 py-1.5 rounded-md text-xs font-medium border transition-all ${
                                modelId === m
                                    ? "bg-primary/10 border-primary/40 text-primary"
                                    : "bg-muted/30 border-border text-muted-foreground hover:border-primary/20"
                            }`}
                        >
                            {m.replace("gemini-", "Gemini ").replace("-preview", "")}
                        </button>
                    ))}
                </div>
            </div>
            <div className="flex items-start justify-between gap-4 rounded-md border border-border/50 bg-background/30 px-3 py-2">
                <div className="space-y-0.5">
                    <label
                        htmlFor="content-search-grounding"
                        className="text-xs font-medium cursor-pointer select-none"
                    >
                        {t("pipelineModal.searchGroundingToggle")}
                    </label>
                    <p className="text-[11px] text-muted-foreground leading-relaxed">
                        {t("pipelineModal.searchGroundingHint")}
                    </p>
                </div>
                <Switch
                    id="content-search-grounding"
                    checked={searchGroundingEnabled}
                    onCheckedChange={setSearchGroundingEnabled}
                    aria-label={t("pipelineModal.searchGroundingToggle")}
                    className="mt-0.5"
                />
            </div>
            <div className="flex items-center gap-2 flex-wrap">
                <input
                    type="checkbox"
                    id="content-enable-cron"
                    className="rounded"
                    checked={!!cronExpression}
                    onChange={(e) =>
                        setCronExpression(e.target.checked ? "0 9 * * 1" : "")
                    }
                />
                <label
                    htmlFor="content-enable-cron"
                    className="text-xs font-medium cursor-pointer select-none"
                >
                    {t("pipelineModal.scheduleToggle")}
                </label>
                {!!cronExpression && (
                    <input
                        type="text"
                        value={cronExpression}
                        onChange={(e) => setCronExpression(e.target.value)}
                        placeholder={t("pipelineModal.cronPlaceholder")}
                        className="flex-1 min-w-[180px] max-w-sm rounded-md border border-input bg-background px-3 py-1.5 text-xs font-mono h-8 focus:outline-none focus:ring-2 focus:ring-ring/30"
                    />
                )}
            </div>
            {!!cronExpression && (
                <p className="text-[11px] text-muted-foreground pl-6">
                    <Trans
                        i18nKey="pipelineModal.cronHintIntro"
                        ns="content"
                    />
                    <code>0 9 * * 1</code>{" "}
                    {t("pipelineModal.cronHintOutro")}
                </p>
            )}
        </div>
    ) : null;

    if (!open) {
        return null;
    }

    return (
        <Dialog open={open} onOpenChange={(o) => !o && onClose()}>
            <DialogContent
                className="max-w-5xl w-[90vw] max-h-[90vh] flex flex-col overflow-hidden p-0"
                hideCloseButton
            >
                <DialogTitle className="sr-only">
                    {t("pipelineModal.dialogTitle", {
                        template: template?.name || t("pipelineModal.defaultTaskName"),
                    })}
                </DialogTitle>
                <DialogDescription className="sr-only">
                    {t("pipelineModal.dialogDescription")}
                </DialogDescription>

                {/* Anthony header */}
                <div className="flex items-center gap-4 px-6 pt-6 pb-4 border-b border-border bg-muted/20 shrink-0">
                    <div className="relative">
                        <img
                            src="/Anthony_Chat.png"
                            alt="Anthony"
                            className="w-14 h-14 rounded-full object-contain bg-gradient-to-br from-primary/20 to-muted ring-2 ring-primary/30"
                        />
                        <span className="absolute bottom-0 right-0 w-3.5 h-3.5 bg-emerald-400 rounded-full border-2 border-background" />
                    </div>
                    <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                            <h2 className="text-base font-semibold">Anthony</h2>
                            <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-orange-500/10 text-orange-400 font-medium">
                                {t("pipelineModal.persona")}
                            </span>
                            {template && (
                                <>
                                    <span className="text-xl ml-1">
                                        {template.icon || "📝"}
                                    </span>
                                    <span className="text-sm font-medium text-foreground">
                                        {template.name}
                                    </span>
                                </>
                            )}
                        </div>
                        <p className="text-xs text-muted-foreground mt-0.5">
                            {t("pipelineModal.intro")}
                        </p>
                    </div>
                    <button
                        onClick={onClose}
                        className="text-muted-foreground hover:text-foreground transition-colors p-1 rounded"
                    >
                        <X className="h-5 w-5" />
                    </button>
                </div>

                {/* Body */}
                <div className="flex-1 overflow-y-auto px-6 py-4">
                    {bootstrapping ? (
                        <div className="flex flex-col items-center justify-center gap-2 py-20 text-xs text-muted-foreground">
                            <Loader2 className="h-5 w-5 animate-spin" />
                            <span>{t("pipelineModal.loadingContext")}</span>
                        </div>
                    ) : (
                        <WizardShell
                            key={shellKey}
                            scope="content_generation"
                            template={wizardTemplate}
                            clientId={clientId}
                            userId={userId}
                            initialValues={initialValues}
                            disabled={executing || saving}
                            actions={[
                                {
                                    key: "save_draft",
                                    label: saving
                                        ? t("pipelineModal.actions.saving")
                                        : t("pipelineModal.actions.saveDraft"),
                                    variant: "secondary",
                                    icon: <Save className="h-3.5 w-3.5 mr-1.5" />,
                                    loading: saving,
                                    disabled: executing,
                                    persistent: true,
                                },
                                {
                                    key: "execute",
                                    label: executing
                                        ? t("pipelineModal.actions.executing")
                                        : t("pipelineModal.actions.confirmExecute"),
                                    variant: "primary",
                                    icon: <Play className="h-3.5 w-3.5 mr-1.5" />,
                                    loading: executing,
                                    disabled:
                                        saving ||
                                        (isCitationAnalysisEnabled(wizardTemplate) &&
                                            !getCitationAnalysisResult(currentFormState)),
                                },
                            ]}
                            onSubmit={handleWizardSubmit}
                            onStateChange={(state) => setCurrentFormState(state)}
                            footerExtras={runtimeSettingsBar}
                        />
                    )}
                </div>
            </DialogContent>
        </Dialog>
    );
}
