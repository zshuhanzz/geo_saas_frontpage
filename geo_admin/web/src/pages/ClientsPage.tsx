import { useState, useEffect } from "react";
import type { components } from "../api/openapi";
import { useToast } from "../components/Toast";
import {
    getClients,
    createClient,
    updateClient,
    runCollectorJob,
    runAnalyzerJob,
    runLLMDiscoveryJob,
    getBatchSummaries,
    getSchedulerStatus,
    enableSchedulerJob,
    pauseSchedulerJob,
    resumeSchedulerJob,
    getGlobalPlatforms,
    getGlobalLanguages,
    getFeaturePackages,
    getFeatureRegistry,
} from "../api/client";
import type { BatchSummaryRow, FeatureDefinition, FeaturePackage } from "../api/client";
import ClientBrandAliases from "../components/ClientBrandAliases";
import WorkspaceDeletionDialog from "../components/WorkspaceDeletionDialog";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Switch } from "@/components/ui/switch";
import { Building2, Search, Plus, Trash2, ArrowRightCircle, Save, Play, Loader2, Clock, Pause, CheckCircle2, Pencil, X, Globe, Languages, Monitor, Check, Settings2, Zap, Sparkles } from "lucide-react";

type ClientOut = components["schemas"]["ClientOut"];
type PlatformOut = components["schemas"]["PlatformOut"];
type LanguageOut = components["schemas"]["LanguageOut"];
type SchedulerStatusOut = components["schemas"]["SchedulerStatusOut"];

type ClientWithExpansionSettings = ClientOut & {
    reuse_latest_final_prompt?: boolean | null;
    country_localization_mode?: "generic" | "localized_by_country" | null;
    final_prompt_per_client_prompt?: number | null;
    default_calls_per_prompt?: number | null;
};

interface SchedulerJobState {
    state?: string;
    [key: string]: unknown;
}

type JobType = "collector" | "analyzer" | "llm_discovery";

/* ============================================================================
   Searchable Multi-Select Panel (Inline chip-based, for config editing)
   ============================================================================ */
interface SearchableMultiPanelProps<T> {
    label: string;
    icon: React.ReactNode;
    options: T[];
    selected: string[];
    onChange: (next: string[]) => void;
    getLabel: (opt: T) => string;
    getValue: (opt: T) => string;
    placeholder?: string;
}

function SearchableMultiPanel<T>({ label, icon, options, selected, onChange, getLabel, getValue }: SearchableMultiPanelProps<T>) {
    const [search, setSearch] = useState<string>("");
    const filtered = options.filter((o) => getLabel(o).toLowerCase().includes(search.toLowerCase()));

    return (
        <div className="space-y-2">
            <Label className="text-sm font-semibold flex items-center gap-1.5">
                {icon} {label}
                <Badge variant="secondary" className="ml-1 text-[10px] h-4 px-1.5">
                    {selected.length}
                </Badge>
            </Label>
            {/* Search */}
            <div className="relative">
                <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 h-3.5 w-3.5 text-muted-foreground" />
                <Input
                    className="h-8 pl-8 text-sm"
                    placeholder={`Search ${label.toLowerCase()}...`}
                    value={search}
                    onChange={(e: React.ChangeEvent<HTMLInputElement>) => setSearch(e.target.value)}
                />
            </div>
            {/* Options Grid */}
            <div className="border rounded-md max-h-[160px] overflow-y-auto">
                {filtered.length === 0 && (
                    <div className="p-3 text-center text-xs text-muted-foreground">No options found</div>
                )}
                {filtered.map((opt) => {
                    const val = getValue(opt);
                    const isSelected = selected.includes(val);
                    return (
                        <button
                            key={val}
                            className={`w-full flex items-center gap-2 px-3 py-1.5 text-sm hover:bg-accent/50 transition-colors text-left border-b last:border-b-0 ${isSelected ? 'bg-accent/20' : ''}`}
                            onClick={() => {
                                onChange(isSelected ? selected.filter((v) => v !== val) : [...selected, val]);
                            }}
                        >
                            <div className={`w-4 h-4 rounded border flex items-center justify-center shrink-0 ${isSelected ? 'bg-primary border-primary' : 'border-input'}`}>
                                {isSelected && <Check className="h-3 w-3 text-primary-foreground" />}
                            </div>
                            <span className="truncate flex-1">{getLabel(opt)}</span>
                        </button>
                    );
                })}
            </div>
        </div>
    );
}


export default function ClientsPage() {
    const toast = useToast();
    const [clients, setClients] = useState<ClientWithExpansionSettings[]>([]);
    const [loading, setLoading] = useState<boolean>(true);
    const [showNewClient, setShowNewClient] = useState<boolean>(false);

    // New Client Form
    const [newClientName, setNewClientName] = useState<string>("");
    const [newClientQuota, setNewClientQuota] = useState<number>(50);
    const [featurePackages, setFeaturePackages] = useState<FeaturePackage[]>([]);
    const [featureCatalog, setFeatureCatalog] = useState<FeatureDefinition[]>([]);
    const [newFeatureMode, setNewFeatureMode] = useState<string>("full_platform");
    const [newFeatureKeys, setNewFeatureKeys] = useState<string[]>([]);

    const [selectedClient, setSelectedClient] = useState<ClientWithExpansionSettings | null>(null);
    const [deletionClient, setDeletionClient] = useState<ClientWithExpansionSettings | null>(null);
    const [searchTerm, setSearchTerm] = useState<string>("");

    // Job Execution
    const [runningJob, setRunningJob] = useState<JobType | null>(null);

    // Setting details
    const [editCronCollector, setEditCronCollector] = useState<string>("");
    const [editCronAnalyzer, setEditCronAnalyzer] = useState<string>("");
    const [editCronLLMDiscovery, setEditCronLLMDiscovery] = useState<string>("");
    const [savingCron, setSavingCron] = useState<boolean>(false);

    // Scheduler status
    const [schedulerStatus, setSchedulerStatus] = useState<SchedulerStatusOut | null>(null);
    const [loadingScheduler, setLoadingScheduler] = useState<boolean>(false);
    const [schedulerAction, setSchedulerAction] = useState<JobType | null>(null);
    const [editingSchedule, setEditingSchedule] = useState<boolean>(false);

    // Allowed Configurations
    const [globalPlatforms, setGlobalPlatforms] = useState<PlatformOut[]>([]);
    const [globalLanguages, setGlobalLanguages] = useState<LanguageOut[]>([]);
    const [editingConfig, setEditingConfig] = useState<boolean>(false);
    const [editPlatforms, setEditPlatforms] = useState<string[]>([]);
    const [editCountries, setEditCountries] = useState<string[]>([]);
    const [editLanguages, setEditLanguages] = useState<string[]>([]);
    const [savingConfig, setSavingConfig] = useState<boolean>(false);

    // Client Info editing (quota + agent settings)
    const [editingClientInfo, setEditingClientInfo] = useState<boolean>(false);
    const [editQuota, setEditQuota] = useState<number>(50);
    const [savingClientInfo, setSavingClientInfo] = useState<boolean>(false);
    const [editAgentDailyTokens, setEditAgentDailyTokens] = useState<number>(500000);
    const [editAgentRpm, setEditAgentRpm] = useState<number>(10);
    const [editReuseFinalPrompt, setEditReuseFinalPrompt] = useState<boolean | null>(null);
    const [editCountryLocalizationMode, setEditCountryLocalizationMode] = useState<"inherit" | "generic" | "localized_by_country">("inherit");
    const [editFinalPromptPerClientPrompt, setEditFinalPromptPerClientPrompt] = useState<string>("");
    const [editDefaultCallsPerPrompt, setEditDefaultCallsPerPrompt] = useState<string>("");
    const [batchSummaries, setBatchSummaries] = useState<BatchSummaryRow[]>([]);
    const [loadingBatchSummaries, setLoadingBatchSummaries] = useState<boolean>(false);
    const [selectedAnalyzerBatchId, setSelectedAnalyzerBatchId] = useState<string>("");

    useEffect(() => {
        loadClients();
        loadGlobalData();
    }, []);

    async function loadGlobalData(): Promise<void> {
        try {
            const [platformsRaw, languagesRaw, packagesRaw, registryRaw] = await Promise.all([
                getGlobalPlatforms(true),
                getGlobalLanguages(),
                getFeaturePackages(),
                getFeatureRegistry(),
            ]);
            const platforms = (platformsRaw as PlatformOut[]) || [];
            const languages = (languagesRaw as LanguageOut[]) || [];
            setGlobalPlatforms(platforms);
            setGlobalLanguages(languages.filter((l) => l.is_active !== false));
            setFeaturePackages(packagesRaw.filter((item) => item.is_active));
            setFeatureCatalog(registryRaw.features.filter((item) => item.is_active));
            const fullPlatform = packagesRaw.find((item) => item.package_key === "full_platform");
            setNewFeatureKeys(fullPlatform?.feature_keys || []);
        } catch (err) {
            console.error("Failed to load global data:", err);
        }
    }

    async function loadClients(): Promise<void> {
        setLoading(true);
        try {
            const data = ((await getClients(searchTerm)) as ClientWithExpansionSettings[]) || [];
            setClients(data);
            if (selectedClient) {
                const updated = data.find((c) => c.id === selectedClient.id);
                if (updated) {
                    setSelectedClient(updated);
                    setEditCronCollector(updated.cron_collector || "");
                    setEditCronAnalyzer(updated.cron_analyzer || "");
                    setEditCronLLMDiscovery(updated.cron_llm_discovery || "");
                }
            }
        } catch (err) {
            console.error("Failed to load clients:", err);
        } finally {
            setLoading(false);
        }
    }

    function hydratePromptExpansionEditState(client: ClientWithExpansionSettings): void {
        setEditReuseFinalPrompt(client.reuse_latest_final_prompt ?? null);
        setEditCountryLocalizationMode(client.country_localization_mode ?? "inherit");
        setEditFinalPromptPerClientPrompt(
            client.final_prompt_per_client_prompt != null
                ? String(client.final_prompt_per_client_prompt)
                : "",
        );
        setEditDefaultCallsPerPrompt(
            client.default_calls_per_prompt != null
                ? String(client.default_calls_per_prompt)
                : "",
        );
    }

    function parseOptionalPositiveInt(value: string, label: string): number | null {
        const trimmed = value.trim();
        if (!trimmed) return null;
        const parsed = Number(trimmed);
        if (!Number.isInteger(parsed) || parsed < 1) {
            throw new Error(`${label} must be a positive integer.`);
        }
        return parsed;
    }

    async function handleCreateClient(e: React.FormEvent<HTMLFormElement>): Promise<void> {
        e.preventDefault();
        if (!newClientName.trim()) return;
        try {
            await createClient({
                name: newClientName,
                client_prompt_quota: newClientQuota,
                config_platforms: [],
                config_countries: [],
                config_languages: [],
                feature_package_key: newFeatureMode === "custom" ? null : newFeatureMode,
                feature_keys: newFeatureMode === "custom" ? newFeatureKeys : null,
            });
            setNewClientName("");
            setNewClientQuota(50);
            setNewFeatureMode("full_platform");
            setNewFeatureKeys(
                featurePackages.find((item) => item.package_key === "full_platform")?.feature_keys || [],
            );
            setShowNewClient(false);
            loadClients();
        } catch (err) {
            toast.error("Failed to create client: " + (err as Error).message);
        }
    }

    async function handleSaveCron(): Promise<void> {
        if (!sc) return;
        setSavingCron(true);
        try {
            await updateClient(sc.id, {
                cron_collector: editCronCollector,
                cron_analyzer: editCronAnalyzer,
                cron_llm_discovery: editCronLLMDiscovery,
            });
            loadClients();
            loadSchedulerStatus(sc.id);
        } catch (err) {
            toast.error("Failed to save schedule: " + (err as Error).message);
        } finally {
            setSavingCron(false);
        }
    }

    async function handleRunJob(type: JobType): Promise<void> {
        if (!sc) return;
        setRunningJob(type);
        try {
            if (type === 'collector') {
                await runCollectorJob(sc.id);
                toast.success("Collector job triggered successfully. Check Cloud Run for execution status.");
            } else if (type === 'analyzer') {
                await runAnalyzerJob(sc.id, selectedAnalyzerBatchId || undefined);
                toast.success("Analyzer job triggered successfully. Check Cloud Run for execution status.");
            } else if (type === 'llm_discovery') {
                await runLLMDiscoveryJob(sc.id);
                toast.success("LLM Discovery job triggered successfully. Candidates will appear in the SaaS review panel after it finishes.");
            }
        } catch (err) {
            toast.error(`Failed to run ${type}: ${(err as Error).message}`);
        } finally {
            setRunningJob(null);
        }
    }

    async function loadSchedulerStatus(clientId: string): Promise<void> {
        setLoadingScheduler(true);
        try {
            const status = (await getSchedulerStatus(clientId)) as SchedulerStatusOut;
            setSchedulerStatus(status);
        } catch {
            setSchedulerStatus(null);
        } finally {
            setLoadingScheduler(false);
        }
    }

    async function loadBatchSummaries(clientId: string): Promise<void> {
        setLoadingBatchSummaries(true);
        try {
            const summaries = await getBatchSummaries(clientId);
            setBatchSummaries(summaries);
            const defaultBatch = summaries.find((batch) => batch.is_default_selection);
            setSelectedAnalyzerBatchId((current) => {
                if (current && summaries.some((batch) => batch.batch_id === current)) {
                    return current;
                }
                return defaultBatch?.batch_id || summaries[0]?.batch_id || "";
            });
        } catch (err) {
            console.error("Failed to load batch summaries:", err);
            setBatchSummaries([]);
            setSelectedAnalyzerBatchId("");
        } finally {
            setLoadingBatchSummaries(false);
        }
    }

    async function handleToggleScheduler(jobType: JobType, currentState: string | undefined): Promise<void> {
        if (!sc) return;
        setSchedulerAction(jobType);
        try {
            if (currentState === 'ENABLED') {
                await pauseSchedulerJob(sc.id, jobType);
            } else if (currentState === 'NOT_FOUND') {
                await enableSchedulerJob(sc.id, jobType);
            } else {
                await resumeSchedulerJob(sc.id, jobType);
            }
            await loadSchedulerStatus(sc.id);
        } catch (err) {
            toast.error(`Failed to toggle ${jobType} scheduler: ${(err as Error).message}`);
        } finally {
            setSchedulerAction(null);
        }
    }

    // Config editing
    function startEditConfig(): void {
        if (!sc) return;
        setEditPlatforms(sc.config_platforms || []);
        setEditCountries(sc.config_countries || []);
        setEditLanguages(sc.config_languages || []);
        setEditingConfig(true);
    }

    function cancelEditConfig(): void {
        setEditingConfig(false);
    }

    async function handleSaveConfig(): Promise<void> {
        if (!sc) return;
        setSavingConfig(true);
        try {
            await updateClient(sc.id, {
                config_platforms: editPlatforms,
                config_countries: editCountries,
                config_languages: editLanguages,
            });
            setEditingConfig(false);
            loadClients();
        } catch (err) {
            toast.error("Failed to save config: " + (err as Error).message);
        } finally {
            setSavingConfig(false);
        }
    }

    // Derive available countries from selected platforms (edit mode)
    const availableCountries: string[] = editingConfig
        ? Array.from(new Set(
            globalPlatforms
                .filter((p) => editPlatforms.includes(p.platform_id))
                .flatMap((p) => p.supported_countries || [])
        )).sort()
        : [];

    const sc = selectedClient;

    return (
        <div className="space-y-6">
            <div className="flex items-start justify-between">
                <div>
                    <h1 className="text-3xl font-bold tracking-tight text-foreground">Clients</h1>
                    <p className="mt-2 text-sm text-muted-foreground">
                        Manage top-level corporate entities and their global prompt quotas.
                    </p>
                </div>
                <Button onClick={() => setShowNewClient(true)}>
                    <Plus className="mr-2 h-4 w-4" /> New Client
                </Button>
            </div>

            <div className="flex gap-4">
                <div className="relative flex-1 max-w-sm">
                    <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                    <Input
                        placeholder="Search clients..."
                        className="pl-10"
                        value={searchTerm}
                        onChange={(e: React.ChangeEvent<HTMLInputElement>) => setSearchTerm(e.target.value)}
                        onKeyDown={(e: React.KeyboardEvent<HTMLInputElement>) => e.key === "Enter" && loadClients()}
                    />
                </div>
            </div>

            {/* ============== New Client Dialog ============== */}
            <Dialog open={showNewClient} onOpenChange={setShowNewClient}>
                <DialogContent>
                    <DialogHeader>
                        <DialogTitle>Create New Client</DialogTitle>
                    </DialogHeader>
                    <form id="new-client-form" onSubmit={handleCreateClient} className="space-y-4 py-2">
                        <div className="space-y-2">
                            <Label htmlFor="client-name">Corporate Name</Label>
                            <Input
                                id="client-name"
                                placeholder="e.g., Eufy Innovations"
                                value={newClientName}
                                onChange={(e: React.ChangeEvent<HTMLInputElement>) => setNewClientName(e.target.value)}
                                autoFocus
                            />
                        </div>
                        <div className="space-y-2">
                            <Label>Feature Package</Label>
                            <Select
                                value={newFeatureMode}
                                onValueChange={(value) => {
                                    setNewFeatureMode(value);
                                    if (value !== "custom") {
                                        setNewFeatureKeys(
                                            featurePackages.find((item) => item.package_key === value)?.feature_keys || [],
                                        );
                                    }
                                }}
                            >
                                <SelectTrigger>
                                    <SelectValue placeholder="Select feature package" />
                                </SelectTrigger>
                                <SelectContent>
                                    {featurePackages.map((item) => (
                                        <SelectItem key={item.package_key} value={item.package_key}>
                                            {item.display_name_zh} · {item.display_name_en}
                                        </SelectItem>
                                    ))}
                                    <SelectItem value="custom">自定义 · Custom</SelectItem>
                                </SelectContent>
                            </Select>
                            <p className="text-xs text-muted-foreground">
                                The selected package is copied as a Workspace entitlement snapshot.
                            </p>
                        </div>
                        {newFeatureMode === "custom" && (
                            <div className="max-h-56 space-y-2 overflow-y-auto rounded-md border p-3">
                                {featureCatalog.map((feature) => (
                                    <div key={feature.key} className="flex items-start justify-between gap-4 rounded-md px-2 py-1.5">
                                        <div>
                                            <div className="text-sm font-medium">{feature.display_name_zh}</div>
                                            <div className="text-[11px] text-muted-foreground">{feature.key}</div>
                                        </div>
                                        <Switch
                                            checked={newFeatureKeys.includes(feature.key)}
                                            onCheckedChange={(checked) => setNewFeatureKeys(
                                                checked
                                                    ? [...newFeatureKeys, feature.key]
                                                    : newFeatureKeys.filter((key) => key !== feature.key),
                                            )}
                                        />
                                    </div>
                                ))}
                            </div>
                        )}
                        <div className="space-y-2">
                            <Label htmlFor="prompt-quota">Prompt Quota</Label>
                            <Input
                                id="prompt-quota"
                                type="number"
                                min={1}
                                value={newClientQuota}
                                onChange={(e: React.ChangeEvent<HTMLInputElement>) => setNewClientQuota(parseInt(e.target.value) || 50)}
                            />
                        </div>
                    </form>
                    <DialogFooter>
                        <Button
                            type="button"
                            variant="ghost"
                            onClick={() => setShowNewClient(false)}
                        >
                            Cancel
                        </Button>
                        <Button type="submit" form="new-client-form">
                            Create Client
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>

            <div className="grid grid-cols-1 gap-6 lg:grid-cols-12">
                {/* Left Panel: Clients List */}
                <div className="lg:col-span-4">
                    <Card className="h-[calc(100vh-240px)] flex flex-col shadow-sm">
                        <CardHeader className="pb-3 border-b">
                            <CardTitle className="text-lg font-semibold flex items-center">
                                <Building2 className="mr-2 h-5 w-5 text-primary" /> Active Workspaces
                            </CardTitle>
                        </CardHeader>
                        <CardContent className="p-0 flex-1 overflow-y-auto">
                            {loading ? (
                                <div className="flex h-32 items-center justify-center">
                                    <div className="h-6 w-6 animate-spin rounded-full border-b-2 border-primary"></div>
                                </div>
                            ) : clients.length === 0 ? (
                                <div className="p-8 text-center text-sm text-muted-foreground">No clients found</div>
                            ) : (
                                <div className="divide-y border-t-0">
                                    {clients.map((client) => (
                                        <button
                                            key={client.id}
                                            onClick={() => {
                                                setSelectedClient(client);
                                                setEditCronCollector(client.cron_collector || "");
                                                setEditCronAnalyzer(client.cron_analyzer || "");
                                                setEditCronLLMDiscovery(client.cron_llm_discovery || "");
                                                hydratePromptExpansionEditState(client);
                                                setEditingConfig(false);
                                                setEditingSchedule(false);
                                                loadSchedulerStatus(client.id);
                                                loadBatchSummaries(client.id);
                                            }}
                                            className={`w-full flex flex-col items-start p-4 text-left transition-colors ${sc?.id === client.id
                                                ? "bg-accent border-l-4 border-l-primary"
                                                : "hover:bg-accent/50 border-l-4 border-l-transparent"
                                                }`}
                                        >
                                            <span className={`font-medium ${sc?.id === client.id ? "text-foreground" : "text-foreground/80"}`}>
                                                {client.name}
                                            </span>
                                            <div className="mt-1 flex gap-3 text-xs text-muted-foreground">
                                                <span>Quota: {client.client_prompt_quota || "—"}</span>
                                            </div>
                                        </button>
                                    ))}
                                </div>
                            )}
                        </CardContent>
                    </Card>
                </div>

                {/* Right Panel: Client Detail with Minimal View */}
                <div className="lg:col-span-8">
                    <Card className="min-h-[calc(100vh-240px)] shadow-sm bg-muted/10 border-dashed">
                        {sc ? (
                            <>
                                <CardHeader className="border-b bg-card pb-6">
                                    <div className="flex items-start justify-between">
                                        <div>
                                            <CardTitle className="text-2xl font-bold mb-1">{sc.name}</CardTitle>
                                            <div className="flex items-center gap-3 text-sm text-muted-foreground">
                                                <Badge variant="outline" className="font-mono text-xs font-normal">ID: {sc.id}</Badge>
                                                {editingClientInfo ? (
                                                    <span className="flex items-center gap-1.5">
                                                        Quota:
                                                        <Input
                                                            type="number"
                                                            min={1}
                                                            className="h-7 w-20 text-sm"
                                                            value={editQuota}
                                                            onChange={(e: React.ChangeEvent<HTMLInputElement>) => setEditQuota(parseInt(e.target.value) || 1)}
                                                        />
                                                        Prompts
                                                    </span>
                                                ) : (
                                                    <span>Quota: <strong className="text-foreground">{sc.client_prompt_quota}</strong> Prompts</span>
                                                )}
                                            </div>
                                            {/* Client limits and expansion settings */}
                                            {editingClientInfo ? (
                                                <div className="mt-3 space-y-2">
                                                    {/* Agent Quota Settings */}
                                                    <div className="mt-4 pt-3 border-t space-y-3">
                                                        <Label className="text-sm font-semibold flex items-center gap-1.5">
                                                            <Zap className="h-4 w-4 text-muted-foreground" /> Agent Quota
                                                        </Label>
                                                        <div className="grid grid-cols-2 gap-3">
                                                            <div className="space-y-1">
                                                                <Label className="text-xs text-muted-foreground">Daily Token Limit</Label>
                                                                <Input
                                                                    type="number"
                                                                    min={10000}
                                                                    step={10000}
                                                                    className="h-8 text-sm"
                                                                    value={editAgentDailyTokens}
                                                                    onChange={(e: React.ChangeEvent<HTMLInputElement>) => setEditAgentDailyTokens(parseInt(e.target.value) || 500000)}
                                                                />
                                                                <p className="text-[10px] text-muted-foreground">
                                                                    {editAgentDailyTokens >= 1000000
                                                                        ? `${(editAgentDailyTokens / 1000000).toFixed(1)}M tokens/day`
                                                                        : `${(editAgentDailyTokens / 1000).toFixed(0)}K tokens/day`}
                                                                </p>
                                                            </div>
                                                            <div className="space-y-1">
                                                                <Label className="text-xs text-muted-foreground">RPM Limit</Label>
                                                                <Input
                                                                    type="number"
                                                                    min={1}
                                                                    max={60}
                                                                    className="h-8 text-sm"
                                                                    value={editAgentRpm}
                                                                    onChange={(e: React.ChangeEvent<HTMLInputElement>) => setEditAgentRpm(parseInt(e.target.value) || 10)}
                                                                />
                                                                <p className="text-[10px] text-muted-foreground">{editAgentRpm} requests/minute</p>
                                                            </div>
                                                        </div>
                                                    </div>

                                                    {/* Prompt Expansion Settings */}
                                                    <div className="mt-4 pt-3 border-t space-y-4">
                                                        <div>
                                                            <Label className="text-sm font-semibold flex items-center gap-1.5">
                                                                <Sparkles className="h-4 w-4 text-muted-foreground" /> Prompt Expansion Settings
                                                            </Label>
                                                            <p className="text-xs text-muted-foreground mt-1">
                                                                Numeric blanks use Global Config. Empty country mode uses the default Generic behavior.
                                                            </p>
                                                        </div>
                                                        <div className="flex items-center justify-between rounded-md border bg-muted/20 px-3 py-2">
                                                            <div>
                                                                <Label className="text-xs font-semibold">Reuse latest Final Prompt</Label>
                                                                <p className="text-[10px] text-muted-foreground">Disabled inherits the normal per-run Gemini expansion behavior.</p>
                                                            </div>
                                                            <Switch
                                                                checked={editReuseFinalPrompt === true}
                                                                onCheckedChange={(checked) => setEditReuseFinalPrompt(checked)}
                                                            />
                                                        </div>
                                                        <div className="grid grid-cols-2 gap-3">
                                                            <div className="space-y-1">
                                                                <Label className="text-xs text-muted-foreground">Country Localization Mode</Label>
                                                                <Select
                                                                    value={editCountryLocalizationMode}
                                                                    onValueChange={(value) => setEditCountryLocalizationMode(value as "inherit" | "generic" | "localized_by_country")}
                                                                >
                                                                    <SelectTrigger className="h-8">
                                                                        <SelectValue />
                                                                    </SelectTrigger>
                                                                    <SelectContent>
                                                                        <SelectItem value="inherit">Use default (Generic)</SelectItem>
                                                                        <SelectItem value="generic">Generic</SelectItem>
                                                                        <SelectItem value="localized_by_country">Localized by country</SelectItem>
                                                                    </SelectContent>
                                                                </Select>
                                                            </div>
                                                            <div className="space-y-1">
                                                                <Label className="text-xs text-muted-foreground">Final Prompts per Client Prompt</Label>
                                                                <Input
                                                                    type="number"
                                                                    min={1}
                                                                    className="h-8 text-sm"
                                                                    placeholder="Use Global Config"
                                                                    value={editFinalPromptPerClientPrompt}
                                                                    onChange={(e: React.ChangeEvent<HTMLInputElement>) => setEditFinalPromptPerClientPrompt(e.target.value)}
                                                                />
                                                            </div>
                                                            <div className="space-y-1">
                                                                <Label className="text-xs text-muted-foreground">Calls per Final Prompt</Label>
                                                                <Input
                                                                    type="number"
                                                                    min={1}
                                                                    className="h-8 text-sm"
                                                                    placeholder="Use Global Config"
                                                                    value={editDefaultCallsPerPrompt}
                                                                    onChange={(e: React.ChangeEvent<HTMLInputElement>) => setEditDefaultCallsPerPrompt(e.target.value)}
                                                                />
                                                            </div>
                                                        </div>
                                                    </div>

                                                    <div className="flex gap-2 pt-1">
                                                        <Button variant="outline" size="sm" onClick={() => setEditingClientInfo(false)}>
                                                            <X className="mr-1.5 h-3.5 w-3.5" /> Cancel
                                                        </Button>
                                                        <Button size="sm" disabled={savingClientInfo} onClick={async () => {
                                                            setSavingClientInfo(true);
                                                            try {
                                                                if (!sc) return;
                                                                await updateClient(sc.id, {
                                                                    client_prompt_quota: editQuota,
                                                                    agent_daily_token_quota: editAgentDailyTokens,
                                                                    agent_rpm_limit: editAgentRpm,
                                                                    reuse_latest_final_prompt: editReuseFinalPrompt,
                                                                    country_localization_mode: editCountryLocalizationMode === "inherit" ? null : editCountryLocalizationMode,
                                                                    final_prompt_per_client_prompt: parseOptionalPositiveInt(
                                                                        editFinalPromptPerClientPrompt,
                                                                        "Final Prompt per Client Prompt",
                                                                    ),
                                                                    default_calls_per_prompt: parseOptionalPositiveInt(
                                                                        editDefaultCallsPerPrompt,
                                                                        "Default Calls per Prompt",
                                                                    ),
                                                                } as any);
                                                                setEditingClientInfo(false);
                                                                loadClients();
                                                            } catch (err) {
                                                                toast.error("Save failed: " + (err as Error).message);
                                                            } finally {
                                                                setSavingClientInfo(false);
                                                            }
                                                        }}>
                                                            {savingClientInfo ? <Loader2 className="mr-1.5 h-3.5 w-3.5 animate-spin" /> : <Save className="mr-1.5 h-3.5 w-3.5" />}
                                                            Save
                                                        </Button>
                                                    </div>
                                                </div>
                                            ) : (
                                                <div className="mt-2">
                                                    <div className="flex items-center gap-3 mt-2 text-sm text-muted-foreground bg-muted/50 rounded-md px-3 py-1.5">
                                                        <span className="flex items-center gap-1.5">
                                                            <Zap className="h-3.5 w-3.5 text-amber-500" />
                                                            Daily Token Limit: <strong className="text-foreground">
                                                                {(sc.agent_daily_token_quota ?? 500000) >= 1000000
                                                                    ? `${((sc.agent_daily_token_quota ?? 500000) / 1000000).toFixed(1)}M`
                                                                    : `${((sc.agent_daily_token_quota ?? 500000) / 1000).toFixed(0)}K`}
                                                            </strong> tokens/day
                                                        </span>
                                                        <span className="text-muted-foreground/50">|</span>
                                                        <span>RPM: <strong className="text-foreground">{sc.agent_rpm_limit ?? 10}</strong> req/min</span>
                                                    </div>
                                                    <div className="mt-2 rounded-md border bg-muted/30 px-3 py-2 text-xs text-muted-foreground">
                                                        <div className="font-semibold text-foreground mb-1">Prompt Expansion Settings</div>
                                                        <div className="grid grid-cols-2 gap-x-4 gap-y-1">
                                                            <span>Reuse latest Final Prompt: <strong className="text-foreground">{sc.reuse_latest_final_prompt === true ? "Enabled" : "Disabled"}</strong></span>
                                                            <span>Country mode: <strong className="text-foreground">{sc.country_localization_mode || "generic"}</strong></span>
                                                            <span>Final Prompts per Client Prompt: <strong className="text-foreground">{sc.final_prompt_per_client_prompt ?? "Global Config"}</strong></span>
                                                            <span>Calls per Final Prompt: <strong className="text-foreground">{sc.default_calls_per_prompt ?? "Global Config"}</strong></span>
                                                        </div>
                                                    </div>
                                                </div>
                                            )}
                                        </div>
                                        <div className="flex items-center gap-2 ml-4">
                                            {!editingClientInfo && (
                                                <Button
                                                    variant="outline"
                                                    size="sm"
                                                    onClick={() => {
                                                        setEditQuota(sc.client_prompt_quota || 50);
                                                        setEditAgentDailyTokens(sc.agent_daily_token_quota ?? 500000);
                                                        setEditAgentRpm(sc.agent_rpm_limit ?? 10);
                                                        hydratePromptExpansionEditState(sc);
                                                        setEditingClientInfo(true);
                                                    }}
                                                    className="gap-1.5"
                                                >
                                                    <Pencil className="h-3.5 w-3.5" /> Edit Info
                                                </Button>
                                            )}
                                            <Button
                                                variant="destructive"
                                                size="sm"
                                                onClick={() => setDeletionClient(sc)}
                                            >
                                                <Trash2 className="h-4 w-4 mr-2" /> Delete Workspace
                                            </Button>
                                        </div>
                                    </div>
                                </CardHeader>

                                <CardContent className="h-full space-y-8 p-6 overflow-y-auto max-h-[calc(100vh-380px)]">
                                    {/* System Migrated Notice */}
                                    <div className="bg-muted border border-border rounded-lg p-5 flex items-start gap-4">
                                        <div className="bg-primary/20 p-2 rounded-full mt-1">
                                            <ArrowRightCircle className="h-6 w-6 text-primary" />
                                        </div>
                                        <div>
                                            <h3 className="text-base font-semibold">Workspace Configuration Migrated to SaaS</h3>
                                            <p className="text-sm text-muted-foreground mt-1">
                                                Business entities (Topics, Peers, Domains, Personas) are now managed directly by end-users
                                                in the AnswerX SaaS platform.
                                            </p>
                                        </div>
                                    </div>

                                    <ClientBrandAliases clientId={sc.id} />

                                    {/* ====================== Allowed Configurations ====================== */}
                                    <div>
                                        <h3 className="text-lg font-semibold flex items-center justify-between mb-4">
                                            <span className="flex items-center">
                                                <Settings2 className="mr-2 h-5 w-5 text-primary" /> Allowed Configurations
                                            </span>
                                            {!editingConfig && (
                                                <Button variant="outline" size="sm" onClick={startEditConfig} className="gap-1.5">
                                                    <Pencil className="h-3.5 w-3.5" /> Edit
                                                </Button>
                                            )}
                                        </h3>

                                        {editingConfig ? (
                                            /* ---- Edit Mode ---- */
                                            <div className="bg-card border rounded-lg p-6 space-y-5">
                                                <p className="text-xs text-muted-foreground -mt-1">
                                                    Configure which platforms, countries, and languages this client can use.
                                                    Only items selected here will be available in the SaaS brainstorm dialog.
                                                </p>

                                                {/* Platforms */}
                                                <SearchableMultiPanel<PlatformOut>
                                                    label="Platforms"
                                                    icon={<Monitor className="h-4 w-4 text-muted-foreground" />}
                                                    options={globalPlatforms}
                                                    selected={editPlatforms}
                                                    onChange={(val: string[]) => {
                                                        setEditPlatforms(val);
                                                        // Auto-remove countries that are no longer available
                                                        const newAvailableCountries = new Set<string>(
                                                            globalPlatforms
                                                                .filter((p) => val.includes(p.platform_id))
                                                                .flatMap((p) => p.supported_countries || [])
                                                        );
                                                        setEditCountries((prev: string[]) => prev.filter((c) => newAvailableCountries.has(c)));
                                                    }}
                                                    getLabel={(p) => p.display_name}
                                                    getValue={(p) => p.platform_id}
                                                    placeholder="Search platforms..."
                                                />

                                                {/* Countries (filtered by selected platforms) */}
                                                <SearchableMultiPanel<{ code: string; name: string }>
                                                    label={`Countries ${editPlatforms.length === 0 ? '(select platforms first)' : ''}`}
                                                    icon={<Globe className="h-4 w-4 text-muted-foreground" />}
                                                    options={availableCountries.map((c) => ({ code: c, name: c }))}
                                                    selected={editCountries}
                                                    onChange={setEditCountries}
                                                    getLabel={(c) => c.name}
                                                    getValue={(c) => c.code}
                                                    placeholder="Search countries..."
                                                />

                                                {/* Languages */}
                                                <SearchableMultiPanel<LanguageOut>
                                                    label="Languages"
                                                    icon={<Languages className="h-4 w-4 text-muted-foreground" />}
                                                    options={globalLanguages}
                                                    selected={editLanguages}
                                                    onChange={setEditLanguages}
                                                    getLabel={(l) => `${l.language} (${l.language_code})`}
                                                    getValue={(l) => l.language_code}
                                                    placeholder="Search languages..."
                                                />

                                                <div className="flex justify-end gap-2 pt-2 border-t">
                                                    <Button variant="outline" onClick={cancelEditConfig}>
                                                        <X className="mr-2 h-4 w-4" /> Cancel
                                                    </Button>
                                                    <Button onClick={handleSaveConfig} disabled={savingConfig} className="min-w-[120px]">
                                                        {savingConfig ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Save className="mr-2 h-4 w-4" />}
                                                        Save Config
                                                    </Button>
                                                </div>
                                            </div>
                                        ) : (
                                            /* ---- Read-Only Mode ---- */
                                            <div className="bg-card border rounded-lg p-6 space-y-4">
                                                {/* Platforms */}
                                                <div>
                                                    <Label className="text-sm font-semibold flex items-center gap-1.5 mb-2">
                                                        <Monitor className="h-4 w-4 text-muted-foreground" /> Platforms
                                                    </Label>
                                                    {(sc.config_platforms || []).length > 0 ? (
                                                        <div className="flex flex-wrap gap-1.5">
                                                            {(sc.config_platforms ?? []).map((p: string) => {
                                                                const g = globalPlatforms.find((gp) => gp.platform_id === p);
                                                                return (
                                                                    <Badge key={p} variant="secondary" className="font-normal">
                                                                        {g ? g.display_name : p}
                                                                    </Badge>
                                                                );
                                                            })}
                                                        </div>
                                                    ) : (
                                                        <p className="text-xs text-muted-foreground italic">No platforms configured — SaaS brainstorm will not show any platforms.</p>
                                                    )}
                                                </div>

                                                {/* Countries */}
                                                <div>
                                                    <Label className="text-sm font-semibold flex items-center gap-1.5 mb-2">
                                                        <Globe className="h-4 w-4 text-muted-foreground" /> Countries
                                                    </Label>
                                                    {(sc.config_countries || []).length > 0 ? (
                                                        <div className="flex flex-wrap gap-1.5">
                                                            {(sc.config_countries ?? []).map((c: string) => (
                                                                <Badge key={c} variant="secondary" className="font-normal">{c}</Badge>
                                                            ))}
                                                        </div>
                                                    ) : (
                                                        <p className="text-xs text-muted-foreground italic">No countries configured — SaaS brainstorm will not show any countries.</p>
                                                    )}
                                                </div>

                                                {/* Languages */}
                                                <div>
                                                    <Label className="text-sm font-semibold flex items-center gap-1.5 mb-2">
                                                        <Languages className="h-4 w-4 text-muted-foreground" /> Languages
                                                    </Label>
                                                    {(sc.config_languages || []).length > 0 ? (
                                                        <div className="flex flex-wrap gap-1.5">
                                                            {(sc.config_languages ?? []).map((l: string) => {
                                                                const g = globalLanguages.find((gl) => gl.language_code === l);
                                                                return (
                                                                    <Badge key={l} variant="secondary" className="font-normal">
                                                                        {g ? `${g.language} (${l})` : l}
                                                                    </Badge>
                                                                );
                                                            })}
                                                        </div>
                                                    ) : (
                                                        <p className="text-xs text-muted-foreground italic">No languages configured — SaaS brainstorm will not show any languages.</p>
                                                    )}
                                                </div>
                                            </div>
                                        )}
                                    </div>

                                    {/* ====================== Cron Scheduler Section ====================== */}
                                    <div>
                                        <h3 className="text-lg font-semibold flex items-center justify-between mb-4">
                                            <span className="flex items-center">
                                                <Clock className="mr-2 h-5 w-5 text-primary" /> Schedule & Execution Configuration
                                            </span>
                                            {!editingSchedule && (
                                                <Button variant="outline" size="sm" onClick={() => setEditingSchedule(true)} className="gap-1.5">
                                                    <Pencil className="h-3.5 w-3.5" /> Edit
                                                </Button>
                                            )}
                                        </h3>
                                        <div className="grid grid-cols-3 gap-6 bg-card border rounded-lg p-6">
                                            {/* Collector */}
                                            <div className="space-y-4">
                                                <div>
                                                    <Label className="text-sm font-semibold mb-1 block">Collector Schedule (Cron)</Label>
                                                    <p className="text-xs text-muted-foreground mb-2">Controls when Client Prompts are expanded and dispatched.</p>
                                                    {editingSchedule ? (
                                                        <Input
                                                            value={editCronCollector}
                                                            onChange={(e: React.ChangeEvent<HTMLInputElement>) => setEditCronCollector(e.target.value)}
                                                            placeholder="e.g. 0 2 * * *"
                                                        />
                                                    ) : (
                                                        <div className="h-10 px-3 py-2 rounded-md border bg-muted/30 text-sm flex items-center">
                                                            <code className="text-foreground">{editCronCollector || <span className="text-muted-foreground italic">Not configured</span>}</code>
                                                        </div>
                                                    )}
                                                </div>
                                                <Button
                                                    variant="secondary" size="sm" className="w-full"
                                                    onClick={() => handleRunJob('collector')}
                                                    disabled={runningJob !== null}
                                                >
                                                    {runningJob === 'collector' ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Play className="mr-2 h-4 w-4" />}
                                                    Run Collector Now
                                                </Button>
                                                {(() => {
                                                    const col = schedulerStatus?.collector as SchedulerJobState | null | undefined;
                                                    if (!col) return null;
                                                    return (
                                                        <div className="flex items-center justify-between text-xs mt-2">
                                                            <Badge variant={col.state === 'ENABLED' ? 'default' : 'secondary'} className="text-[10px]">
                                                                {col.state === 'ENABLED' ? <CheckCircle2 className="mr-1 h-3 w-3" /> : <Pause className="mr-1 h-3 w-3" />}
                                                                {col.state}
                                                            </Badge>
                                                            <Button
                                                                variant="ghost" size="sm" className="h-6 text-xs"
                                                                onClick={() => handleToggleScheduler('collector', col.state)}
                                                                disabled={schedulerAction !== null || (col.state === 'NOT_FOUND' && !editCronCollector)}
                                                            >
                                                                {schedulerAction === 'collector' ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : null}
                                                                {col.state === 'ENABLED' ? 'Pause' : col.state === 'NOT_FOUND' ? 'Enable' : 'Resume'}
                                                            </Button>
                                                        </div>
                                                    );
                                                })()}
                                            </div>

                                            {/* Analyzer */}
                                            <div className="space-y-4">
                                                <div>
                                                    <Label className="text-sm font-semibold mb-1 block">Analyzer Schedule (Cron)</Label>
                                                    <p className="text-xs text-muted-foreground mb-2">Controls when RAW results are processed into Insight stats.</p>
                                                    {editingSchedule ? (
                                                        <Input
                                                            value={editCronAnalyzer}
                                                            onChange={(e: React.ChangeEvent<HTMLInputElement>) => setEditCronAnalyzer(e.target.value)}
                                                            placeholder="e.g. 0 4 * * *"
                                                        />
                                                    ) : (
                                                        <div className="h-10 px-3 py-2 rounded-md border bg-muted/30 text-sm flex items-center">
                                                            <code className="text-foreground">{editCronAnalyzer || <span className="text-muted-foreground italic">Not configured</span>}</code>
                                                        </div>
                                                    )}
                                                </div>
                                                <div className="space-y-2 rounded-md border bg-muted/20 p-3">
                                                    <div className="flex items-center justify-between gap-2">
                                                        <Label className="text-xs font-semibold">Analyzer Batch</Label>
                                                        <Button
                                                            variant="ghost"
                                                            size="sm"
                                                            className="h-6 px-2 text-xs"
                                                            onClick={() => sc && loadBatchSummaries(sc.id)}
                                                            disabled={loadingBatchSummaries}
                                                        >
                                                            {loadingBatchSummaries ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : null}
                                                            Refresh
                                                        </Button>
                                                    </div>
                                                    {batchSummaries.length > 0 ? (
                                                        <>
                                                            <Select value={selectedAnalyzerBatchId} onValueChange={setSelectedAnalyzerBatchId}>
                                                                <SelectTrigger className="h-8 text-xs">
                                                                    <SelectValue />
                                                                </SelectTrigger>
                                                                <SelectContent>
                                                                    {batchSummaries.map((batch) => (
                                                                        <SelectItem key={batch.batch_id} value={batch.batch_id}>
                                                                            {batch.batch_id} · {batch.unanalyzed_results} unanalyzed
                                                                        </SelectItem>
                                                                    ))}
                                                                </SelectContent>
                                                            </Select>
                                                            {(() => {
                                                                const batch = batchSummaries.find((item) => item.batch_id === selectedAnalyzerBatchId);
                                                                if (!batch) return null;
                                                                return (
                                                                    <div className="grid grid-cols-2 gap-x-3 gap-y-1 text-[10px] text-muted-foreground">
                                                                        <span>Analyzed: <strong className="text-foreground">{batch.analyzed_results}</strong></span>
                                                                        <span>Unanalyzed: <strong className="text-foreground">{batch.unanalyzed_results}</strong></span>
                                                                        <span>Completed tasks: <strong className="text-foreground">{batch.completed_tasks}</strong></span>
                                                                        <span>Dispatched: <strong className="text-foreground">{batch.dispatched_tasks}</strong></span>
                                                                        <span>Dispatch failed: <strong className="text-foreground">{batch.dispatch_failed_tasks}</strong></span>
                                                                        <span>Latest ingest: <strong className="text-foreground">{batch.latest_ingested_at ? new Date(batch.latest_ingested_at).toLocaleString() : "—"}</strong></span>
                                                                    </div>
                                                                );
                                                            })()}
                                                        </>
                                                    ) : (
                                                        <p className="text-[10px] text-muted-foreground">
                                                            No batch summary loaded. Analyzer will auto-select the earliest pending batch.
                                                        </p>
                                                    )}
                                                </div>
                                                <Button
                                                    variant="secondary" size="sm" className="w-full"
                                                    onClick={() => handleRunJob('analyzer')}
                                                    disabled={runningJob !== null}
                                                >
                                                    {runningJob === 'analyzer' ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Play className="mr-2 h-4 w-4" />}
                                                    Run Analyzer Now
                                                </Button>
                                                {(() => {
                                                    const an = schedulerStatus?.analyzer as SchedulerJobState | null | undefined;
                                                    if (!an) return null;
                                                    return (
                                                        <div className="flex items-center justify-between text-xs mt-2">
                                                            <Badge variant={an.state === 'ENABLED' ? 'default' : 'secondary'} className="text-[10px]">
                                                                {an.state === 'ENABLED' ? <CheckCircle2 className="mr-1 h-3 w-3" /> : <Pause className="mr-1 h-3 w-3" />}
                                                                {an.state}
                                                            </Badge>
                                                            <Button
                                                                variant="ghost" size="sm" className="h-6 text-xs"
                                                                onClick={() => handleToggleScheduler('analyzer', an.state)}
                                                                disabled={schedulerAction !== null || (an.state === 'NOT_FOUND' && !editCronAnalyzer)}
                                                            >
                                                                {schedulerAction === 'analyzer' ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : null}
                                                                {an.state === 'ENABLED' ? 'Pause' : an.state === 'NOT_FOUND' ? 'Enable' : 'Resume'}
                                                            </Button>
                                                        </div>
                                                    );
                                                })()}
                                            </div>

                                            {/* LLM Discovery */}
                                            <div className="space-y-4">
                                                <div>
                                                    <Label className="text-sm font-semibold mb-1 flex items-center gap-1.5">
                                                        <Sparkles className="h-3.5 w-3.5 text-amber-500" /> LLM Discovery (Cron)
                                                    </Label>
                                                    <p className="text-xs text-muted-foreground mb-2">Offline Gemini pass that mines new brand/model candidates from recent results.</p>
                                                    {editingSchedule ? (
                                                        <Input
                                                            value={editCronLLMDiscovery}
                                                            onChange={(e: React.ChangeEvent<HTMLInputElement>) => setEditCronLLMDiscovery(e.target.value)}
                                                            placeholder="e.g. 0 3 * * *"
                                                        />
                                                    ) : (
                                                        <div className="h-10 px-3 py-2 rounded-md border bg-muted/30 text-sm flex items-center">
                                                            <code className="text-foreground">{editCronLLMDiscovery || <span className="text-muted-foreground italic">Not configured</span>}</code>
                                                        </div>
                                                    )}
                                                </div>
                                                <Button
                                                    variant="secondary" size="sm" className="w-full"
                                                    onClick={() => handleRunJob('llm_discovery')}
                                                    disabled={runningJob !== null}
                                                >
                                                    {runningJob === 'llm_discovery' ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Play className="mr-2 h-4 w-4" />}
                                                    Run LLM Discovery Now
                                                </Button>
                                                {(() => {
                                                    const ld = schedulerStatus?.llm_discovery as SchedulerJobState | null | undefined;
                                                    if (!ld) return null;
                                                    return (
                                                        <div className="flex items-center justify-between text-xs mt-2">
                                                            <Badge variant={ld.state === 'ENABLED' ? 'default' : 'secondary'} className="text-[10px]">
                                                                {ld.state === 'ENABLED' ? <CheckCircle2 className="mr-1 h-3 w-3" /> : <Pause className="mr-1 h-3 w-3" />}
                                                                {ld.state}
                                                            </Badge>
                                                            <Button
                                                                variant="ghost" size="sm" className="h-6 text-xs"
                                                                onClick={() => handleToggleScheduler('llm_discovery', ld.state)}
                                                                disabled={schedulerAction !== null || (ld.state === 'NOT_FOUND' && !editCronLLMDiscovery)}
                                                            >
                                                                {schedulerAction === 'llm_discovery' ? <Loader2 className="mr-1 h-3 w-3 animate-spin" /> : null}
                                                                {ld.state === 'ENABLED' ? 'Pause' : ld.state === 'NOT_FOUND' ? 'Enable' : 'Resume'}
                                                            </Button>
                                                        </div>
                                                    );
                                                })()}
                                            </div>
                                        </div>
                                        {/* Scheduler status indicator */}
                                        {!loadingScheduler && !schedulerStatus && (
                                            <p className="text-xs text-muted-foreground mt-2 italic">Scheduler status unavailable — Cloud Scheduler jobs may not be deployed yet. Pause/Resume will appear after deployment.</p>
                                        )}
                                        {editingSchedule && (
                                            <div className="mt-4 flex justify-end gap-2">
                                                <Button variant="outline" onClick={() => {
                                                    setEditingSchedule(false);
                                                    setEditCronCollector(sc.cron_collector || "");
                                                    setEditCronAnalyzer(sc.cron_analyzer || "");
                                                    setEditCronLLMDiscovery(sc.cron_llm_discovery || "");
                                                }}>
                                                    <X className="mr-2 h-4 w-4" /> Cancel
                                                </Button>
                                                <Button onClick={async () => { await handleSaveCron(); setEditingSchedule(false); }} disabled={savingCron} className="min-w-[120px]">
                                                    {savingCron ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Save className="mr-2 h-4 w-4" />} Save Schedule
                                                </Button>
                                            </div>
                                        )}
                                    </div>

                                </CardContent>
                            </>
                        ) : (
                            <div className="flex flex-col items-center justify-center h-full min-h-[500px] text-muted-foreground">
                                <Building2 className="h-12 w-12 mb-4 opacity-50" />
                                <span>Select a client from the left pane to view details.</span>
                            </div>
                        )}
                    </Card>
                </div>
            </div>
            <WorkspaceDeletionDialog
                client={deletionClient}
                open={Boolean(deletionClient)}
                onOpenChange={(open) => {
                    if (!open) setDeletionClient(null);
                }}
                onDeleted={async (clientId) => {
                    if (selectedClient?.id === clientId) setSelectedClient(null);
                    setDeletionClient(null);
                    await loadClients();
                    toast.success("Workspace deleted successfully.");
                }}
            />
        </div>
    );
}
