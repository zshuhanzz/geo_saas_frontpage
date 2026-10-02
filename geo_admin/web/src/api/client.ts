/**
 * API client for GEO Admin Web (V2.5 SaaS).
 *
 * Phase 5 (2026-04-25): converted from JS → TS. Public function signatures
 * preserved verbatim so the 19 existing import sites resolve unchanged.
 *
 * Phase 7c (2026-04-25): hand-written ``Promise<unknown>`` return types are
 * now replaced with the precise schema type pulled from the auto-generated
 * ``./openapi`` (``openapi-typescript`` output). All errors are thrown as
 * ``ApiError`` (see ``./types``) so call-sites can branch on
 * ``err instanceof ApiError`` to recover the FastAPI ``detail`` and HTTP
 * ``status``. The ``./openapi.d.ts`` file is generated — DO NOT edit it
 * manually; re-run ``npm run gen:openapi`` after backend schema changes.
 */

import type { components } from "./openapi";
import { ApiError } from "./types";
import type { WorkflowConfigGroupedOut } from "../lib/workflowConfig";
export type { WorkflowConfigGroupedOut } from "../lib/workflowConfig";

// ───────────────────────── Schema aliases ──────────────────────────────────
// Local short aliases so the function signatures below stay readable.
// Each alias is a thin re-name of the canonical generated path.

type Schemas = components["schemas"];

// Global configs
type SettingOut = Schemas["SettingOut"];
type SettingUpsert = Schemas["SettingUpsert"];
type PlatformOut = Schemas["PlatformOut"];
type PlatformCreate = Schemas["PlatformCreate"];
type PlatformUpdate = Schemas["PlatformUpdate"];
type IntentOut = Schemas["IntentOut"];
type IntentCreate = Schemas["IntentCreate"];
type IntentUpdate = Schemas["IntentUpdate"];
type DomainCategoryListOut = Schemas["DomainCategoryListOut"];
type DomainCategoryOut = Schemas["DomainCategoryOut"];
type DomainCategoryCreate = Schemas["DomainCategoryCreate"];
type DomainCategoryUpdate = Schemas["DomainCategoryUpdate"];
type SentimentThemeListOut = Schemas["SentimentThemeListOut"];
type SentimentThemeOut = Schemas["SentimentThemeOut"];
type SentimentThemeCreate = Schemas["SentimentThemeCreate"];
type SentimentThemeUpdate = Schemas["SentimentThemeUpdate"];

// Languages
type LanguageOut = Schemas["LanguageOut"];
type LanguageCreate = Schemas["LanguageCreate"];
type LanguageCreateOut = Schemas["LanguageCreateOut"];
type LanguageUpdate = Schemas["LanguageUpdate"];
type LanguageUpdateOut = Schemas["LanguageUpdateOut"];
type LanguageDeleteOut = Schemas["LanguageDeleteOut"];

// Clients
type ClientOut = Schemas["ClientOut"];
type ClientCreate = Schemas["ClientCreate"];
type ClientUpdate = Schemas["ClientUpdate"];
export type ClientBrand = Schemas["ClientBrandOut"];
type BrandAliasesUpdate = Schemas["BrandAliasesUpdate"];
export type WorkspaceDeletionReadiness = Schemas["WorkspaceDeletionReadinessOut"];
type WorkspaceDeleteConfirm = Schemas["WorkspaceDeleteConfirm"];

// Brand profiles
type BrandProfileOut = Schemas["BrandProfileOut"];
type BrandProfileUpdate = Schemas["BrandProfileUpdate"];

// Jobs / scheduler
type JobTriggerOut = Schemas["JobTriggerOut"];
type SchedulerStatusOut = Schemas["SchedulerStatusOut"];
type SchedulerActionOut = Schemas["SchedulerActionOut"];

// Tasks & results
type TaskListOut = Schemas["TaskListOut"];
type ResultListOut = Schemas["ResultListOut"];

export interface BatchSummaryRow {
    batch_id: string;
    total_results: number;
    analyzed_results: number;
    unanalyzed_results: number;
    completed_tasks: number;
    dispatched_tasks: number;
    dispatch_failed_tasks: number;
    latest_ingested_at?: string | null;
    latest_analyzed_at?: string | null;
    is_default_selection: boolean;
}

// Prompts
type PromptListOut = Schemas["PromptListOut"];

export interface PromptConceptOut {
    text: string;
    topic_id: string;
    topic_name?: string | null;
    intent?: string | null;
    product?: string | null;
    language?: string | null;
    prompt_ids: string[];
    countries: string[];
    platforms: string[];
    final_prompt_count: number;
    active_final_prompt_count: number;
    inactive_final_prompt_count: number;
    created_at?: string | null;
    updated_at?: string | null;
}

export interface PromptConceptListOut {
    data: PromptConceptOut[];
    pagination: {
        page: number;
        limit: number;
        total: number;
        pages: number;
    };
}

// Report templates
type TemplateListOut = Schemas["TemplateListOut"];
type TemplateOut = Schemas["TemplateOut"];
type TemplateCreate = Schemas["TemplateCreate"];
type TemplateUpdate = Schemas["TemplateUpdate"];
type WorkflowConfigItemOut = Schemas["WorkflowConfigItemOut"];
type WorkflowConfigCreate = Schemas["WorkflowConfigCreate"];
type WorkflowConfigUpdate = Schemas["WorkflowConfigUpdate"];

// Agent tasks
type AgentTaskListOut = Schemas["AgentTaskListOut"];
type ScheduleToggleOut = Schemas["ScheduleToggleOut"];

// Memories
type MemoryListOut = Schemas["MemoryListOut"];
type MemoryOut = Schemas["MemoryOut"];
type MemoryCreate = Schemas["MemoryCreate"];
type MemoryUpdate = Schemas["MemoryUpdate"];
type MemoryToggleSharedOut = Schemas["MemoryToggleSharedOut"];
type MemoryUserRow = Schemas["MemoryUserRow"];
type OkResult = Schemas["OkResult"];

// Sessions
type AgentSessionListOut = Schemas["AgentSessionListOut"];
type AgentMessageOut = Schemas["AgentMessageOut"];

// Token usage
type UsageSummaryRow = Schemas["UsageSummaryRow"];
type UsageByUserRow = Schemas["UsageByUserRow"];
type UsageByModelRow = Schemas["UsageByModelRow"];
type UsageTodayOut = Schemas["UsageTodayOut"];

// User profiles
type ProfileListOut = Schemas["ProfileListOut"];
type ProfileOut = Schemas["ProfileOut"];
type ProfileUpdate = Schemas["ProfileUpdate"];

// Analysis metrics (router: ``analysis/metrics``)
type AnalysisMetricCreate = Schemas["routers__analysis_metrics__MetricCreate"];
type AnalysisMetricOut = Schemas["routers__analysis_metrics__MetricOut"];
type AnalysisMetricUpdate = Schemas["routers__analysis_metrics__MetricUpdate"];
type MetricListOut = Schemas["MetricListOut"];

// Content framework — note FastAPI emits two ``MetricOut`` schemas (one per
// router), namespaced via ``routers__<module>__MetricOut`` in OpenAPI.
type ContentMetricOut = Schemas["routers__content_framework__MetricOut"];
type StrategyOut = Schemas["StrategyOut"];
type StrategyCreate = Schemas["StrategyCreate"];
type StrategyUpdate = Schemas["StrategyUpdate"];
type SubgoalOut = Schemas["SubgoalOut"];
type SubgoalCreate = Schemas["SubgoalCreate"];
type SubgoalUpdate = Schemas["SubgoalUpdate"];
type ContentAssetListOut = Schemas["ContentAssetListOut"];
type ContentAssetOut = Schemas["ContentAssetOut"];
type ContentAssetCreate = Schemas["ContentAssetCreate"];
type ContentAssetUpdate = Schemas["ContentAssetUpdate"];

// ───────────────────────── HTTP helper ─────────────────────────────────────

const API_BASE = "/api";
export const AUTH_EXPIRED_EVENT = "geo_admin_auth_expired";
export const SESSION_EXPIRED_MESSAGE = "登录已过期，请重新登录";

let authExpiredDispatched = false;

type FetchOpts = RequestInit & { headers?: Record<string, string> };

function authHeaders(): Record<string, string> {
    const headers: Record<string, string> = {};
    const devEmail = import.meta.env.VITE_DEV_AUTH_USER_EMAIL as string | undefined;
    if (devEmail) {
        headers["X-Dev-User-Email"] = devEmail;
    }
    return headers;
}

function shouldExpireSession(status: number, detail: unknown): boolean {
    if (status === 401) return true;
    return Boolean(
        status === 403
        && detail
        && typeof detail === "object"
        && !Array.isArray(detail)
        && (detail as { code?: string }).code === "user_inactive",
    );
}

function handleAuthExpiredResponse(response: Response, detail: unknown): void {
    if (!shouldExpireSession(response.status, detail)) return;
    if (authExpiredDispatched) return;
    authExpiredDispatched = true;
    window.dispatchEvent(
        new CustomEvent(AUTH_EXPIRED_EVENT, {
            detail: SESSION_EXPIRED_MESSAGE,
        }),
    );
    window.setTimeout(() => {
        authExpiredDispatched = false;
    }, 1000);
}

async function fetchJSON<T = unknown>(url: string, options: FetchOpts = {}): Promise<T> {
    const response = await fetch(url, {
        ...options,
        credentials: "same-origin",
        headers: {
            "Content-Type": "application/json",
            ...authHeaders(),
            ...(options.headers || {}),
        },
    });

    if (!response.ok) {
        const error = await response
            .json()
            .catch(() => ({ detail: "Unknown error" }));
        const detail =
            (error as { detail?: unknown }).detail || `HTTP ${response.status}`;
        handleAuthExpiredResponse(response, detail);
        throw new ApiError(detail, response.status);
    }

    if (response.status === 204) {
        return null as T;
    }

    return response.json() as Promise<T>;
}

// ============== Global Configs ==============
export async function getGlobalSettings(): Promise<SettingOut[]> {
    return fetchJSON<SettingOut[]>(`${API_BASE}/global-configs/settings`);
}

export async function upsertGlobalSetting(
    key: string,
    value: unknown,
    description: string = "",
): Promise<SettingOut> {
    const body: SettingUpsert = { key, value: value as SettingUpsert["value"], description };
    return fetchJSON<SettingOut>(`${API_BASE}/global-configs/settings`, {
        method: "PUT",
        body: JSON.stringify(body),
    });
}

export async function deleteGlobalSetting(key: string): Promise<void> {
    return fetchJSON<void>(
        `${API_BASE}/global-configs/settings/${encodeURIComponent(key)}`,
        { method: "DELETE" },
    );
}

export async function getGlobalPlatforms(activeOnly: boolean = false): Promise<PlatformOut[]> {
    return fetchJSON<PlatformOut[]>(
        `${API_BASE}/global-configs/platforms${activeOnly ? "?active_only=true" : ""}`,
    );
}

export async function createGlobalPlatform(data: PlatformCreate): Promise<PlatformOut> {
    return fetchJSON<PlatformOut>(`${API_BASE}/global-configs/platforms`, {
        method: "POST",
        body: JSON.stringify(data),
    });
}

export async function updateGlobalPlatform(
    platformUuid: string,
    data: PlatformUpdate,
): Promise<PlatformOut> {
    return fetchJSON<PlatformOut>(`${API_BASE}/global-configs/platforms/${platformUuid}`, {
        method: "PUT",
        body: JSON.stringify(data),
    });
}

export async function deleteGlobalPlatform(platformUuid: string): Promise<void> {
    return fetchJSON<void>(`${API_BASE}/global-configs/platforms/${platformUuid}`, {
        method: "DELETE",
    });
}

export async function getGlobalIntents(activeOnly: boolean = false): Promise<IntentOut[]> {
    return fetchJSON<IntentOut[]>(
        `${API_BASE}/global-configs/intents${activeOnly ? "?active_only=true" : ""}`,
    );
}

export async function createGlobalIntent(data: IntentCreate): Promise<IntentOut> {
    return fetchJSON<IntentOut>(`${API_BASE}/global-configs/intents`, {
        method: "POST",
        body: JSON.stringify(data),
    });
}

export async function updateGlobalIntent(
    intentUuid: string,
    data: IntentUpdate,
): Promise<IntentOut> {
    return fetchJSON<IntentOut>(`${API_BASE}/global-configs/intents/${intentUuid}`, {
        method: "PUT",
        body: JSON.stringify(data),
    });
}

export async function deleteGlobalIntent(intentUuid: string): Promise<void> {
    return fetchJSON<void>(`${API_BASE}/global-configs/intents/${intentUuid}`, {
        method: "DELETE",
    });
}

// ============== Domain Categories ==============
export async function getDomainCategories(
    search: string = "",
    category: string = "",
    page: number = 1,
    limit: number = 50,
): Promise<DomainCategoryListOut> {
    const params = new URLSearchParams();
    if (search) params.set("search", search);
    if (category) params.set("category", category);
    params.set("page", String(page));
    params.set("limit", String(limit));
    return fetchJSON<DomainCategoryListOut>(
        `${API_BASE}/global-configs/domain-categories?${params.toString()}`,
    );
}

export async function getDomainCategoryEnums(): Promise<string[]> {
    return fetchJSON<string[]>(`${API_BASE}/global-configs/domain-categories/enums`);
}

export async function createDomainCategory(data: DomainCategoryCreate): Promise<DomainCategoryOut> {
    return fetchJSON<DomainCategoryOut>(`${API_BASE}/global-configs/domain-categories`, {
        method: "POST",
        body: JSON.stringify(data),
    });
}

export async function updateDomainCategory(
    dcUuid: string,
    data: DomainCategoryUpdate,
): Promise<DomainCategoryOut> {
    return fetchJSON<DomainCategoryOut>(`${API_BASE}/global-configs/domain-categories/${dcUuid}`, {
        method: "PUT",
        body: JSON.stringify(data),
    });
}

export async function deleteDomainCategory(dcUuid: string): Promise<void> {
    return fetchJSON<void>(`${API_BASE}/global-configs/domain-categories/${dcUuid}`, {
        method: "DELETE",
    });
}

// ============== Sentiment Theme Dictionary ==============
export async function getSentimentThemes(
    search: string = "",
    industry: string = "",
    created_by: string = "",
    page: number = 1,
    limit: number = 50,
): Promise<SentimentThemeListOut> {
    const params = new URLSearchParams();
    if (search) params.set("search", search);
    if (industry) params.set("industry", industry);
    if (created_by) params.set("created_by", created_by);
    params.set("page", String(page));
    params.set("limit", String(limit));
    return fetchJSON<SentimentThemeListOut>(
        `${API_BASE}/global-configs/sentiment-themes?${params.toString()}`,
    );
}

export async function createSentimentTheme(data: SentimentThemeCreate): Promise<SentimentThemeOut> {
    return fetchJSON<SentimentThemeOut>(`${API_BASE}/global-configs/sentiment-themes`, {
        method: "POST",
        body: JSON.stringify(data),
    });
}

export async function updateSentimentTheme(
    themeId: string,
    data: SentimentThemeUpdate,
): Promise<SentimentThemeOut> {
    return fetchJSON<SentimentThemeOut>(`${API_BASE}/global-configs/sentiment-themes/${themeId}`, {
        method: "PUT",
        body: JSON.stringify(data),
    });
}

export async function deleteSentimentTheme(themeId: string): Promise<void> {
    return fetchJSON<void>(`${API_BASE}/global-configs/sentiment-themes/${themeId}`, {
        method: "DELETE",
    });
}


// ============== Languages ==============
export async function getGlobalLanguages(): Promise<LanguageOut[]> {
    return fetchJSON<LanguageOut[]>(`${API_BASE}/languages`);
}

export async function createGlobalLanguage(data: LanguageCreate): Promise<LanguageCreateOut> {
    return fetchJSON<LanguageCreateOut>(`${API_BASE}/languages`, {
        method: "POST",
        body: JSON.stringify(data),
    });
}

export async function updateGlobalLanguage(
    languageId: string,
    data: LanguageUpdate,
): Promise<LanguageUpdateOut> {
    return fetchJSON<LanguageUpdateOut>(`${API_BASE}/languages/${languageId}`, {
        method: "PUT",
        body: JSON.stringify(data),
    });
}

export async function deleteGlobalLanguage(languageId: string): Promise<LanguageDeleteOut> {
    return fetchJSON<LanguageDeleteOut>(`${API_BASE}/languages/${languageId}`, {
        method: "DELETE",
    });
}

// ============== Clients ==============
export async function getClients(search: string = ""): Promise<ClientOut[]> {
    let url = `${API_BASE}/clients`;
    if (search) url += `?search=${encodeURIComponent(search)}`;
    return fetchJSON<ClientOut[]>(url);
}

export async function getClient(clientId: string): Promise<ClientOut> {
    return fetchJSON<ClientOut>(`${API_BASE}/clients/${clientId}`);
}

export async function createClient(data: ClientCreate): Promise<ClientOut> {
    return fetchJSON<ClientOut>(`${API_BASE}/clients`, {
        method: "POST",
        body: JSON.stringify(data),
    });
}

export interface FeatureModule {
    key: string;
    label_zh: string;
    label_en: string;
    sort_order: number;
}

export interface FeatureDefinition {
    key: string;
    module_key: string;
    display_name_zh: string;
    display_name_en: string;
    description_zh: string;
    description_en: string;
    sort_order: number;
    is_active: boolean;
}

export interface FeatureRegistryResponse {
    modules: FeatureModule[];
    features: FeatureDefinition[];
    role_capabilities: Record<string, Record<string, string[]>>;
}

export interface FeaturePackage {
    package_key: string;
    display_name_zh: string;
    display_name_en: string;
    description_zh: string;
    description_en: string;
    sort_order: number;
    is_system: boolean;
    is_active: boolean;
    feature_keys: string[];
}

export interface WorkspaceEntitlements {
    client_id: string;
    applied_package_key: string | null;
    is_custom: boolean;
    feature_keys: string[];
    updated_at?: string | null;
}

export interface WorkspaceOption {
    id: string;
    name: string;
}

export async function getFeatureRegistry(): Promise<FeatureRegistryResponse> {
    return fetchJSON<FeatureRegistryResponse>(`${API_BASE}/feature-access/registry`);
}

export async function updateFeatureMetadata(
    featureKey: string,
    data: Partial<Omit<FeatureDefinition, "key" | "module_key">>,
): Promise<FeatureDefinition> {
    return fetchJSON<FeatureDefinition>(
        `${API_BASE}/feature-access/registry/${encodeURIComponent(featureKey)}`,
        {
            method: "PATCH",
            body: JSON.stringify(data),
        },
    );
}

export async function getFeaturePackages(): Promise<FeaturePackage[]> {
    return fetchJSON<FeaturePackage[]>(`${API_BASE}/feature-access/packages`);
}

export async function saveFeaturePackage(data: FeaturePackage): Promise<FeaturePackage> {
    return fetchJSON<FeaturePackage>(
        `${API_BASE}/feature-access/packages/${encodeURIComponent(data.package_key)}`,
        {
            method: "PUT",
            body: JSON.stringify(data),
        },
    );
}

export async function getFeatureWorkspaceOptions(): Promise<WorkspaceOption[]> {
    return fetchJSON<WorkspaceOption[]>(`${API_BASE}/feature-access/workspaces`);
}

export async function getWorkspaceEntitlements(clientId: string): Promise<WorkspaceEntitlements> {
    return fetchJSON<WorkspaceEntitlements>(
        `${API_BASE}/feature-access/workspaces/${clientId}`,
    );
}

export async function saveWorkspaceEntitlements(
    clientId: string,
    data: { package_key?: string | null; feature_keys?: string[] | null },
): Promise<WorkspaceEntitlements> {
    return fetchJSON<WorkspaceEntitlements>(
        `${API_BASE}/feature-access/workspaces/${clientId}`,
        {
            method: "PUT",
            body: JSON.stringify(data),
        },
    );
}

export async function updateClient(clientId: string, data: ClientUpdate): Promise<ClientOut> {
    return fetchJSON<ClientOut>(`${API_BASE}/clients/${clientId}`, {
        method: "PUT",
        body: JSON.stringify(data),
    });
}

export async function deleteClient(
    clientId: string,
    workspaceName: string,
    options: Pick<RequestInit, "signal"> = {},
): Promise<void> {
    const body: WorkspaceDeleteConfirm = { workspace_name: workspaceName };
    return fetchJSON<void>(`${API_BASE}/clients/${clientId}`, {
        method: "DELETE",
        body: JSON.stringify(body),
        signal: options.signal,
    });
}

export async function getWorkspaceDeletionReadiness(
    clientId: string,
    options: Pick<RequestInit, "signal"> = {},
): Promise<WorkspaceDeletionReadiness> {
    return fetchJSON<WorkspaceDeletionReadiness>(
        `${API_BASE}/clients/${clientId}/deletion-readiness`,
        { signal: options.signal },
    );
}

export async function stopAllWorkspaceScheduling(
    clientId: string,
    options: Pick<RequestInit, "signal"> = {},
): Promise<WorkspaceDeletionReadiness> {
    return fetchJSON<WorkspaceDeletionReadiness>(
        `${API_BASE}/clients/${clientId}/deletion-readiness/stop-all-scheduling`,
        { method: "POST", signal: options.signal },
    );
}

export async function getClientBrands(clientId: string): Promise<ClientBrand[]> {
    return fetchJSON<ClientBrand[]>(`${API_BASE}/clients/${clientId}/brands`);
}

export async function updateClientBrandAliases(
    clientId: string,
    brandId: string,
    aliases: string[],
): Promise<ClientBrand> {
    const body: BrandAliasesUpdate = { aliases };
    return fetchJSON<ClientBrand>(
        `${API_BASE}/clients/${clientId}/brands/${brandId}/aliases`,
        {
            method: "PUT",
            body: JSON.stringify(body),
        },
    );
}

// ============== Brand Profiles ==============
export async function getBrandProfile(clientId: string): Promise<BrandProfileOut> {
    return fetchJSON<BrandProfileOut>(`${API_BASE}/brand-profiles/${clientId}`);
}

export async function updateBrandProfile(
    clientId: string,
    data: BrandProfileUpdate,
): Promise<OkResult> {
    return fetchJSON<OkResult>(`${API_BASE}/brand-profiles/${clientId}`, {
        method: "PUT",
        body: JSON.stringify(data),
    });
}

// Domains, Topics, Peers, Personas moved to SaaS Web

// ============== Jobs ==============
export async function runCollectorJob(clientId: string): Promise<JobTriggerOut> {
    return fetchJSON<JobTriggerOut>(`${API_BASE}/clients/${clientId}/jobs/collector/run`, {
        method: "POST",
    });
}

export async function runAnalyzerJob(clientId: string, batchId?: string): Promise<JobTriggerOut> {
    return fetchJSON<JobTriggerOut>(`${API_BASE}/clients/${clientId}/jobs/analyzer/run`, {
        method: "POST",
        body: JSON.stringify(batchId ? { batch_id: batchId } : {}),
    });
}

export async function runLLMDiscoveryJob(clientId: string): Promise<JobTriggerOut> {
    return fetchJSON<JobTriggerOut>(`${API_BASE}/clients/${clientId}/jobs/llm_discovery/run`, {
        method: "POST",
    });
}

// ============== Scheduler ==============
export async function getSchedulerStatus(clientId: string): Promise<SchedulerStatusOut> {
    return fetchJSON<SchedulerStatusOut>(`${API_BASE}/clients/${clientId}/scheduler/status`);
}

export async function pauseSchedulerJob(
    clientId: string,
    jobType: string,
): Promise<SchedulerActionOut> {
    return fetchJSON<SchedulerActionOut>(
        `${API_BASE}/clients/${clientId}/scheduler/${jobType}/pause`,
        { method: "POST" },
    );
}

export async function enableSchedulerJob(
    clientId: string,
    jobType: string,
): Promise<SchedulerActionOut> {
    return fetchJSON<SchedulerActionOut>(
        `${API_BASE}/clients/${clientId}/scheduler/${jobType}/enable`,
        { method: "POST" },
    );
}

export async function resumeSchedulerJob(
    clientId: string,
    jobType: string,
): Promise<SchedulerActionOut> {
    return fetchJSON<SchedulerActionOut>(
        `${API_BASE}/clients/${clientId}/scheduler/${jobType}/resume`,
        { method: "POST" },
    );
}

// ============== Tasks & Results ==============
export async function getTasks(
    clientId: string,
    params: Record<string, unknown> = {},
): Promise<TaskListOut> {
    const url = new URL(`${window.location.origin}${API_BASE}/clients/${clientId}/tasks`);
    Object.entries(params).forEach(([k, v]) => {
        if (v !== undefined && v !== "" && v !== null) url.searchParams.set(k, String(v));
    });
    return fetchJSON<TaskListOut>(url.toString());
}

export async function getResults(taskId: string): Promise<ResultListOut> {
    return fetchJSON<ResultListOut>(`${API_BASE}/tasks/${taskId}/results`);
}

// ============== Prompts (Query Fanouts) ==============
export async function getPrompts(clientId: string): Promise<PromptListOut> {
    return fetchJSON<PromptListOut>(`${API_BASE}/prompts?client_id=${clientId}&limit=200`);
}

export async function getPromptConcepts(
    clientId: string,
    params: Record<string, unknown> = {},
): Promise<PromptConceptListOut> {
    const url = new URL(`${window.location.origin}${API_BASE}/prompts/concepts`);
    url.searchParams.set("client_id", clientId);
    Object.entries(params).forEach(([k, v]) => {
        if (v !== undefined && v !== "" && v !== null && v !== "all") {
            url.searchParams.set(k, String(v));
        }
    });
    return fetchJSON<PromptConceptListOut>(url.toString());
}

export async function getPromptTasks(clientId: string, promptId: string): Promise<TaskListOut> {
    return fetchJSON<TaskListOut>(
        `${API_BASE}/clients/${clientId}/tasks?client_prompt_id=${promptId}&limit=100`,
    );
}

export async function getPromptTasksByPromptIds(
    clientId: string,
    promptIds: string[],
    params: Record<string, unknown> = {},
): Promise<TaskListOut> {
    const url = new URL(`${window.location.origin}${API_BASE}/clients/${clientId}/tasks/by-prompts`);
    url.searchParams.set("prompt_ids", promptIds.join(","));
    Object.entries(params).forEach(([k, v]) => {
        if (v !== undefined && v !== "" && v !== null && v !== "all") {
            url.searchParams.set(k, String(v));
        }
    });
    return fetchJSON<TaskListOut>(url.toString());
}

export async function getBatchIds(clientId: string): Promise<string[]> {
    return fetchJSON<string[]>(`${API_BASE}/clients/${clientId}/batch-ids`);
}

export async function getBatchSummaries(clientId: string): Promise<BatchSummaryRow[]> {
    return fetchJSON<BatchSummaryRow[]>(`${API_BASE}/clients/${clientId}/batch-summaries`);
}

// ============== Report Templates ==============
export async function getReportTemplates(taskType: string = ""): Promise<TemplateListOut> {
    const params = new URLSearchParams();
    params.set("active_only", "false");
    if (taskType) params.set("task_type", taskType);
    return fetchJSON<TemplateListOut>(`${API_BASE}/analysis/templates?${params.toString()}`);
}

export async function createReportTemplate(data: TemplateCreate): Promise<TemplateOut> {
    return fetchJSON<TemplateOut>(`${API_BASE}/analysis/templates`, {
        method: "POST",
        body: JSON.stringify(data),
    });
}

export async function updateReportTemplate(
    templateId: string,
    data: TemplateUpdate,
): Promise<TemplateOut> {
    return fetchJSON<TemplateOut>(`${API_BASE}/analysis/templates/${templateId}`, {
        method: "PUT",
        body: JSON.stringify(data),
    });
}

export async function deleteReportTemplate(templateId: string): Promise<void> {
    return fetchJSON<void>(`${API_BASE}/analysis/templates/${templateId}`, {
        method: "DELETE",
    });
}

export async function getWorkflowConfig(scope: string): Promise<WorkflowConfigGroupedOut> {
    return fetchJSON<WorkflowConfigGroupedOut>(
        `${API_BASE}/analysis/templates/workflow-config?scope=${scope}`,
    );
}

export async function createWorkflowConfig(
    data: WorkflowConfigCreate,
): Promise<WorkflowConfigItemOut> {
    return fetchJSON<WorkflowConfigItemOut>(`${API_BASE}/analysis/templates/workflow-config`, {
        method: "POST",
        body: JSON.stringify(data),
    });
}

export async function updateWorkflowConfig(
    itemId: string,
    data: WorkflowConfigUpdate,
): Promise<WorkflowConfigItemOut> {
    return fetchJSON<WorkflowConfigItemOut>(
        `${API_BASE}/analysis/templates/workflow-config/${itemId}`,
        { method: "PUT", body: JSON.stringify(data) },
    );
}

export async function deleteWorkflowConfig(itemId: string): Promise<void> {
    return fetchJSON<void>(`${API_BASE}/analysis/templates/workflow-config/${itemId}`, {
        method: "DELETE",
    });
}

export async function syncTemplateScheduler(templateId: string): Promise<unknown> {
    // Endpoint not modelled in OpenAPI (returns a free-form scheduler sync ack).
    return fetchJSON(`${API_BASE}/analysis/templates/${templateId}/scheduler/sync`, {
        method: "POST",
    });
}

export async function pauseTemplateScheduler(templateId: string): Promise<unknown> {
    // Endpoint not modelled in OpenAPI.
    return fetchJSON(`${API_BASE}/analysis/templates/${templateId}/scheduler/pause`, {
        method: "POST",
    });
}

export async function resumeTemplateScheduler(templateId: string): Promise<unknown> {
    // Endpoint not modelled in OpenAPI.
    return fetchJSON(`${API_BASE}/analysis/templates/${templateId}/scheduler/resume`, {
        method: "POST",
    });
}

// ============== Agent Tasks (Analysis + Content) ==============
export async function getAgentTasks(
    params: Record<string, string> = {},
): Promise<AgentTaskListOut> {
    const qs = new URLSearchParams(params).toString();
    return fetchJSON<AgentTaskListOut>(`${API_BASE}/agent-tasks${qs ? "?" + qs : ""}`);
}

export async function toggleAgentTaskSchedule(
    taskId: string,
    schedule_enabled: boolean,
): Promise<ScheduleToggleOut> {
    return fetchJSON<ScheduleToggleOut>(`${API_BASE}/agent-tasks/${taskId}/schedule`, {
        method: "PATCH",
        body: JSON.stringify({ schedule_enabled }),
    });
}

// ============== Agent Memories ==============
export async function getMemories(
    clientId: string,
    params: Record<string, string> = {},
): Promise<MemoryListOut> {
    const qs = new URLSearchParams({ client_id: clientId, ...params }).toString();
    return fetchJSON<MemoryListOut>(`${API_BASE}/memories?${qs}`);
}

export async function getMemoryUsers(clientId: string): Promise<MemoryUserRow[]> {
    return fetchJSON<MemoryUserRow[]>(`${API_BASE}/memories/users?client_id=${clientId}`);
}

export async function getMemory(memoryId: string): Promise<MemoryOut> {
    return fetchJSON<MemoryOut>(`${API_BASE}/memories/${memoryId}`);
}

export async function createMemory(data: MemoryCreate): Promise<MemoryOut> {
    return fetchJSON<MemoryOut>(`${API_BASE}/memories`, {
        method: "POST",
        body: JSON.stringify(data),
    });
}

export async function updateMemory(memoryId: string, data: MemoryUpdate): Promise<MemoryOut> {
    return fetchJSON<MemoryOut>(`${API_BASE}/memories/${memoryId}`, {
        method: "PUT",
        body: JSON.stringify(data),
    });
}

export async function toggleMemoryShared(memoryId: string): Promise<MemoryToggleSharedOut> {
    return fetchJSON<MemoryToggleSharedOut>(`${API_BASE}/memories/${memoryId}/toggle-shared`, {
        method: "PUT",
    });
}

export async function deleteMemory(memoryId: string): Promise<void> {
    return fetchJSON<void>(`${API_BASE}/memories/${memoryId}`, {
        method: "DELETE",
    });
}

export async function bulkDeleteExpiredMemories(clientId: string): Promise<OkResult> {
    return fetchJSON<OkResult>(`${API_BASE}/memories?client_id=${clientId}`, {
        method: "DELETE",
    });
}

// ============== Agent Sessions ==============
export async function getAgentSessions(
    params: Record<string, unknown> = {},
): Promise<AgentSessionListOut> {
    const qs = new URLSearchParams(
        Object.fromEntries(
            Object.entries(params)
                .filter(([, v]) => v != null && v !== "")
                .map(([k, v]) => [k, String(v)]),
        ),
    ).toString();
    return fetchJSON<AgentSessionListOut>(`${API_BASE}/agent-sessions?${qs}`);
}

export async function getSessionMessages(threadId: string): Promise<AgentMessageOut[]> {
    return fetchJSON<AgentMessageOut[]>(
        `${API_BASE}/agent-sessions/${encodeURIComponent(threadId)}/messages`,
    );
}

// ============== Agent Token Usage ==============
export async function getTokenUsageSummary(
    params: Record<string, unknown> = {},
): Promise<UsageSummaryRow[]> {
    const qs = new URLSearchParams(
        Object.fromEntries(
            Object.entries(params)
                .filter(([, v]) => v != null && v !== "")
                .map(([k, v]) => [k, String(v)]),
        ),
    ).toString();
    return fetchJSON<UsageSummaryRow[]>(`${API_BASE}/agent-token-usage/summary?${qs}`);
}

export async function getTokenUsageByUser(
    clientId: string,
    days: number = 7,
): Promise<UsageByUserRow[]> {
    return fetchJSON<UsageByUserRow[]>(
        `${API_BASE}/agent-token-usage/by-user?client_id=${clientId}&days=${days}`,
    );
}

export async function getTokenUsageByModel(
    params: Record<string, unknown> = {},
): Promise<UsageByModelRow[]> {
    const qs = new URLSearchParams(
        Object.fromEntries(
            Object.entries(params)
                .filter(([, v]) => v != null && v !== "")
                .map(([k, v]) => [k, String(v)]),
        ),
    ).toString();
    return fetchJSON<UsageByModelRow[]>(`${API_BASE}/agent-token-usage/by-model?${qs}`);
}

export async function getTokenUsageToday(clientId: string): Promise<UsageTodayOut> {
    return fetchJSON<UsageTodayOut>(`${API_BASE}/agent-token-usage/today?client_id=${clientId}`);
}

// ============== User Profiles ==============
export async function getUserProfiles(
    params: Record<string, unknown> = {},
): Promise<ProfileListOut> {
    const qs = new URLSearchParams(
        Object.fromEntries(
            Object.entries(params)
                .filter(([, v]) => v != null && v !== "")
                .map(([k, v]) => [k, String(v)]),
        ),
    ).toString();
    return fetchJSON<ProfileListOut>(`${API_BASE}/user-profiles?${qs}`);
}

export async function getUserProfile(profileId: string): Promise<ProfileOut> {
    return fetchJSON<ProfileOut>(`${API_BASE}/user-profiles/${profileId}`);
}

export async function updateUserProfile(
    profileId: string,
    data: ProfileUpdate,
): Promise<ProfileOut> {
    return fetchJSON<ProfileOut>(`${API_BASE}/user-profiles/${profileId}`, {
        method: "PUT",
        body: JSON.stringify(data),
    });
}

// ============== Analysis Metrics (Phase 2: wizard_config registry) ==============
export interface AnalysisMetricListParams {
    domain?: string;
    is_active?: boolean | string;
    relevant_table?: string;
    q?: string;
    page?: number;
    limit?: number;
}

export async function getAnalysisMetrics(
    params: AnalysisMetricListParams = {},
): Promise<MetricListOut> {
    const qs = new URLSearchParams();
    Object.entries(params).forEach(([k, v]) => {
        if (v !== undefined && v !== null && v !== "") qs.set(k, String(v));
    });
    return fetchJSON<MetricListOut>(
        `${API_BASE}/analysis/metrics${qs.toString() ? "?" + qs.toString() : ""}`,
    );
}

export async function getAnalysisMetricSchemaTables(): Promise<string[]> {
    return fetchJSON<string[]>(`${API_BASE}/analysis/metrics/schema-tables`);
}

export async function createAnalysisMetric(
    data: AnalysisMetricCreate,
): Promise<AnalysisMetricOut> {
    return fetchJSON<AnalysisMetricOut>(`${API_BASE}/analysis/metrics`, {
        method: "POST",
        body: JSON.stringify(data),
    });
}

export async function updateAnalysisMetric(
    metricId: string,
    data: AnalysisMetricUpdate,
): Promise<AnalysisMetricOut> {
    return fetchJSON<AnalysisMetricOut>(`${API_BASE}/analysis/metrics/${metricId}`, {
        method: "PUT",
        body: JSON.stringify(data),
    });
}

export async function deleteAnalysisMetric(metricId: string): Promise<void> {
    return fetchJSON<void>(`${API_BASE}/analysis/metrics/${metricId}`, {
        method: "DELETE",
    });
}

// ============== Content Framework ==============
// Metrics
export async function getMetrics(activeOnly: boolean = false): Promise<ContentMetricOut[]> {
    return fetchJSON<ContentMetricOut[]>(
        `${API_BASE}/content-framework/metrics${activeOnly ? "?active_only=true" : ""}`,
    );
}
export async function createMetric(data: Record<string, unknown>): Promise<ContentMetricOut> {
    return fetchJSON<ContentMetricOut>(`${API_BASE}/content-framework/metrics`, {
        method: "POST",
        body: JSON.stringify(data),
    });
}
export async function updateMetric(
    metricId: string,
    data: Record<string, unknown>,
): Promise<ContentMetricOut> {
    return fetchJSON<ContentMetricOut>(
        `${API_BASE}/content-framework/metrics/${encodeURIComponent(metricId)}`,
        { method: "PUT", body: JSON.stringify(data) },
    );
}
export async function deleteMetric(metricId: string): Promise<void> {
    return fetchJSON<void>(
        `${API_BASE}/content-framework/metrics/${encodeURIComponent(metricId)}`,
        { method: "DELETE" },
    );
}

// Subgoals
export async function getSubgoals(
    metricId: string = "",
    activeOnly: boolean = false,
): Promise<SubgoalOut[]> {
    const params = new URLSearchParams();
    if (metricId) params.set("metric_id", metricId);
    if (activeOnly) params.set("active_only", "true");
    const qs = params.toString();
    return fetchJSON<SubgoalOut[]>(
        `${API_BASE}/content-framework/subgoals${qs ? "?" + qs : ""}`,
    );
}
export async function createSubgoal(data: SubgoalCreate): Promise<SubgoalOut> {
    return fetchJSON<SubgoalOut>(`${API_BASE}/content-framework/subgoals`, {
        method: "POST",
        body: JSON.stringify(data),
    });
}
export async function updateSubgoal(
    subgoalId: string,
    data: SubgoalUpdate,
): Promise<SubgoalOut> {
    return fetchJSON<SubgoalOut>(
        `${API_BASE}/content-framework/subgoals/${encodeURIComponent(subgoalId)}`,
        { method: "PUT", body: JSON.stringify(data) },
    );
}
export async function deleteSubgoal(subgoalId: string): Promise<void> {
    return fetchJSON<void>(
        `${API_BASE}/content-framework/subgoals/${encodeURIComponent(subgoalId)}`,
        { method: "DELETE" },
    );
}

// Strategies
export async function getStrategies(
    params: Record<string, unknown> = {},
): Promise<StrategyOut[]> {
    const qs = new URLSearchParams(
        Object.fromEntries(
            Object.entries(params)
                .filter(([, v]) => v != null && v !== "")
                .map(([k, v]) => [k, String(v)]),
        ),
    ).toString();
    return fetchJSON<StrategyOut[]>(
        `${API_BASE}/content-framework/strategies${qs ? "?" + qs : ""}`,
    );
}
export async function createStrategy(data: StrategyCreate): Promise<StrategyOut> {
    return fetchJSON<StrategyOut>(`${API_BASE}/content-framework/strategies`, {
        method: "POST",
        body: JSON.stringify(data),
    });
}
export async function updateStrategy(
    strategyId: string,
    data: StrategyUpdate,
): Promise<StrategyOut> {
    return fetchJSON<StrategyOut>(`${API_BASE}/content-framework/strategies/${strategyId}`, {
        method: "PUT",
        body: JSON.stringify(data),
    });
}
export async function deleteStrategy(strategyId: string): Promise<void> {
    return fetchJSON<void>(`${API_BASE}/content-framework/strategies/${strategyId}`, {
        method: "DELETE",
    });
}

// Content Assets
export async function getContentAssets(
    params: Record<string, unknown> = {},
): Promise<ContentAssetListOut> {
    const qs = new URLSearchParams(
        Object.fromEntries(
            Object.entries(params)
                .filter(([, v]) => v != null && v !== "")
                .map(([k, v]) => [k, String(v)]),
        ),
    ).toString();
    return fetchJSON<ContentAssetListOut>(
        `${API_BASE}/content-framework/assets${qs ? "?" + qs : ""}`,
    );
}
export async function createContentAsset(data: ContentAssetCreate): Promise<ContentAssetOut> {
    return fetchJSON<ContentAssetOut>(`${API_BASE}/content-framework/assets`, {
        method: "POST",
        body: JSON.stringify(data),
    });
}
export async function updateContentAsset(
    assetId: string,
    data: ContentAssetUpdate,
): Promise<ContentAssetOut> {
    return fetchJSON<ContentAssetOut>(`${API_BASE}/content-framework/assets/${assetId}`, {
        method: "PUT",
        body: JSON.stringify(data),
    });
}
export async function deleteContentAsset(assetId: string): Promise<void> {
    return fetchJSON<void>(`${API_BASE}/content-framework/assets/${assetId}`, {
        method: "DELETE",
    });
}

// ============== Access Control ==============
export interface AccessControlUser {
    id: string;
    email: string;
    google_sub?: string | null;
    name?: string | null;
    avatar_url?: string | null;
    quota_limit?: number | null;
    is_active: boolean;
    joined_at?: string | null;
    last_login_at?: string | null;
    created_at?: string | null;
    updated_at?: string | null;
}

export interface ClientAccessGrant {
    id: string;
    user_id: string;
    email: string;
    name?: string | null;
    avatar_url?: string | null;
    client_id: string;
    client_name: string;
    role: "admin" | "viewer" | "account_manager";
    is_active: boolean;
    granted_at?: string | null;
    created_at?: string | null;
    updated_at?: string | null;
}

export interface AdminAccessGrant {
    id: string;
    user_id: string;
    email: string;
    name?: string | null;
    avatar_url?: string | null;
    role: "super_admin" | "viewer";
    support_all_clients: boolean;
    is_active: boolean;
    granted_at?: string | null;
    created_at?: string | null;
    updated_at?: string | null;
}

export interface AccessControlMe {
    user: AccessControlUser;
    admin_access: AdminAccessGrant;
}

export interface UserAuditEvent {
    id: string;
    user_id: string;
    email: string;
    name?: string | null;
    client_id?: string | null;
    client_name?: string | null;
    event_type: "page_view" | "api_action";
    action_key: string;
    action_label?: string | null;
    route?: string | null;
    method?: string | null;
    status_code?: number | null;
    target_type?: string | null;
    target_id?: string | null;
    metadata: Record<string, unknown>;
    created_at?: string | null;
}

export interface UserAuditPage {
    items: UserAuditEvent[];
    total: number;
    page: number;
    page_size: number;
}

export async function getCurrentAccessControlMe(): Promise<AccessControlMe> {
    return fetchJSON<AccessControlMe>(`${API_BASE}/access-control/me`);
}

export async function getUserAuditEvents(
    clientSearch = "",
    userSearch = "",
    page = 1,
    pageSize = 25,
): Promise<UserAuditPage> {
    const params = new URLSearchParams();
    if (clientSearch) params.set("client_search", clientSearch);
    if (userSearch) params.set("user_search", userSearch);
    params.set("page", String(page));
    params.set("page_size", String(pageSize));
    return fetchJSON<UserAuditPage>(`${API_BASE}/access-control/user-audit?${params.toString()}`);
}

export async function getAccessControlUsers(
    search = "",
    activeOnly = false,
): Promise<AccessControlUser[]> {
    const params = new URLSearchParams();
    if (search) params.set("search", search);
    if (activeOnly) params.set("active_only", "true");
    const suffix = params.toString() ? `?${params.toString()}` : "";
    return fetchJSON<AccessControlUser[]>(`${API_BASE}/access-control/users${suffix}`);
}

export async function upsertAccessControlUser(data: {
    email: string;
    name?: string | null;
    quota_limit?: number | null;
    is_active: boolean;
}): Promise<AccessControlUser> {
    return fetchJSON<AccessControlUser>(`${API_BASE}/access-control/users`, {
        method: "POST",
        body: JSON.stringify(data),
    });
}

export async function updateAccessControlUser(
    userId: string,
    data: {
        email: string;
        name?: string | null;
        quota_limit?: number | null;
        is_active: boolean;
    },
): Promise<AccessControlUser> {
    return fetchJSON<AccessControlUser>(`${API_BASE}/access-control/users/${userId}`, {
        method: "PUT",
        body: JSON.stringify(data),
    });
}

export async function getClientAccessGrants(
    search = "",
    clientId = "",
    activeOnly = false,
): Promise<ClientAccessGrant[]> {
    const params = new URLSearchParams();
    if (search) params.set("search", search);
    if (clientId) params.set("client_id", clientId);
    if (activeOnly) params.set("active_only", "true");
    const suffix = params.toString() ? `?${params.toString()}` : "";
    return fetchJSON<ClientAccessGrant[]>(`${API_BASE}/access-control/client-access${suffix}`);
}

export async function upsertClientAccessGrant(data: {
    user_id: string;
    client_id: string;
    role: "admin" | "viewer" | "account_manager";
    is_active: boolean;
}): Promise<ClientAccessGrant> {
    return fetchJSON<ClientAccessGrant>(`${API_BASE}/access-control/client-access`, {
        method: "POST",
        body: JSON.stringify(data),
    });
}

export async function updateClientAccessGrant(
    grantId: string,
    data: { role?: "admin" | "viewer" | "account_manager"; is_active?: boolean },
): Promise<ClientAccessGrant> {
    return fetchJSON<ClientAccessGrant>(`${API_BASE}/access-control/client-access/${grantId}`, {
        method: "PUT",
        body: JSON.stringify(data),
    });
}

export async function removeClientAccessGrant(grantId: string): Promise<ClientAccessGrant> {
    return fetchJSON<ClientAccessGrant>(`${API_BASE}/access-control/client-access/${grantId}`, {
        method: "DELETE",
    });
}

export async function getAdminAccessGrants(
    search = "",
    activeOnly = false,
): Promise<AdminAccessGrant[]> {
    const params = new URLSearchParams();
    if (search) params.set("search", search);
    if (activeOnly) params.set("active_only", "true");
    const suffix = params.toString() ? `?${params.toString()}` : "";
    return fetchJSON<AdminAccessGrant[]>(`${API_BASE}/access-control/admin-access${suffix}`);
}

export async function upsertAdminAccessGrant(data: {
    user_id: string;
    role: "super_admin" | "viewer";
    support_all_clients: boolean;
    is_active: boolean;
}): Promise<AdminAccessGrant> {
    return fetchJSON<AdminAccessGrant>(`${API_BASE}/access-control/admin-access`, {
        method: "POST",
        body: JSON.stringify(data),
    });
}

export async function updateAdminAccessGrant(
    grantId: string,
    data: {
        role?: "super_admin" | "viewer";
        support_all_clients?: boolean;
        is_active?: boolean;
    },
): Promise<AdminAccessGrant> {
    return fetchJSON<AdminAccessGrant>(`${API_BASE}/access-control/admin-access/${grantId}`, {
        method: "PUT",
        body: JSON.stringify(data),
    });
}

export async function removeAdminAccessGrant(grantId: string): Promise<AdminAccessGrant> {
    return fetchJSON<AdminAccessGrant>(`${API_BASE}/access-control/admin-access/${grantId}`, {
        method: "DELETE",
    });
}

// ============== Static Reports ==============
export interface StaticReportListRow {
    id: string;
    client_id: string;
    client_name?: string | null;
    report_date: string;
    timezone: string;
    status: "PENDING" | "MATERIALIZING" | "COMPLETED" | "NOT_READY" | "FAILED" | string;
    snapshot_version: string;
    data_window_start: string;
    data_window_end: string;
    window_days: number;
    rendering_mode: "single_day" | "multi_day" | string;
    data_completeness: Record<string, unknown>;
    warnings: unknown[];
    error_message?: string | null;
    materialized_at?: string | null;
    created_at?: string | null;
    updated_at?: string | null;
}

export interface StaticReportDetail extends StaticReportListRow {
    snapshot_json?: Record<string, unknown> | null;
}

export interface StaticReportAdminActionOut {
    ok: boolean;
    report_id: string;
    client_id: string;
    report_date: string;
    action: "delete" | "regenerate" | string;
    message: string;
}

export interface StaticReportListOut {
    data: StaticReportListRow[];
    pagination: {
        page: number;
        limit: number;
        total: number;
        pages: number;
    };
}

export interface StaticReportListParams {
    page?: number;
    limit?: number;
    client_id?: string;
    status?: string;
    date_from?: string;
    date_to?: string;
}

export async function getStaticReports(params: StaticReportListParams = {}): Promise<StaticReportListOut> {
    const search = new URLSearchParams();
    Object.entries(params).forEach(([key, value]) => {
        if (value !== undefined && value !== null && String(value).trim() !== "") {
            search.set(key, String(value));
        }
    });
    const suffix = search.toString() ? `?${search.toString()}` : "";
    return fetchJSON<StaticReportListOut>(`${API_BASE}/static-reports${suffix}`);
}

export async function getStaticReport(reportId: string): Promise<StaticReportDetail> {
    return fetchJSON<StaticReportDetail>(`${API_BASE}/static-reports/${encodeURIComponent(reportId)}`);
}

export async function deleteStaticReport(reportId: string): Promise<StaticReportAdminActionOut> {
    return fetchJSON<StaticReportAdminActionOut>(`${API_BASE}/static-reports/${encodeURIComponent(reportId)}`, {
        method: "DELETE",
    });
}

export async function regenerateStaticReport(reportId: string): Promise<StaticReportAdminActionOut> {
    return fetchJSON<StaticReportAdminActionOut>(`${API_BASE}/static-reports/${encodeURIComponent(reportId)}/regenerate`, {
        method: "POST",
    });
}
