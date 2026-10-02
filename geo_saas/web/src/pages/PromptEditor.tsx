import { useEffect, useRef, useState } from "react";
import { toast } from "sonner";
import { useSaaS } from "@/contexts/SaaSContext";
import { getPrompts, addPrompt, batchDeletePrompts, getPromptIntentFacets, batchCreatePrompts, batchUpdatePrompts, createTopic, addProductToTopic, API_BASE, authHeaders, fetchJSON, handleAuthExpiredResponse } from "@/lib/api";
import { Tabs, TabsContent, TabsList, TabsTrigger } from "@/components/ui/tabs";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { Popover, PopoverContent, PopoverTrigger } from "@/components/ui/popover";

import { ChevronLeft, Sparkles, Upload, FileDown, Plus, Loader2, ChevronDown, Monitor, Save, Trash2 } from "lucide-react";
import { useLocation, useNavigate } from "react-router-dom";
import { useTranslation } from "react-i18next";
import { useConfirm } from "@/components/ui/confirm-dialog";

import type { CandidatePrompt, GlobalLanguage, GlobalPlatform } from "./PromptEditor.parts/types";
import { countUniquePrompts } from "./PromptEditor.parts/utils";
import { TopicSidebar } from "./PromptEditor.parts/TopicSidebar";
import { PromptTable } from "./PromptEditor.parts/PromptTable";
import { BulkActionBar } from "./PromptEditor.parts/BulkActionBar";
import { BrainstormDialog } from "./PromptEditor.parts/BrainstormDialog";
import { WorkspaceCleanupDialog } from "./PromptEditor.parts/WorkspaceCleanupDialog";
import { PromptImportDialog } from "@/components/prompts/PromptImportDialog";
import { promptImportWorkspaceRenderKey } from "@/lib/promptImport";
import {
    createSingleFlightGuard,
    getManualPromptDeleteBatchSize,
    getWorkspaceCleanupRequest,
    runSerialPromptCleanup,
    type WorkspaceCleanupProgress,
} from "@/lib/workspaceCleanup";
import {
    areSelectedCandidateIntentsActive,
    getIntentWriteValidation,
    isWorkspaceStateOwned,
    resolveCanonicalIntent,
} from "./insights/promptIntentFilter";


export default function PromptEditor() {
    const { t } = useTranslation(["insights", "common"]);
    const { clients, clientId, refreshClients, can } = useSaaS();
    const configurationReadOnly = !can("actions.configuration", "manage");
    const navigate = useNavigate();
    const location = useLocation();
    const confirmDialog = useConfirm();
    const [data, setData] = useState<any[]>([]);
    const [loadedClientId, setLoadedClientId] = useState<string | null>(null);
    const [editorStateClientId, setEditorStateClientId] = useState<string | null>(null);
    const [loading, setLoading] = useState(true);
    const [selectedRows, setSelectedRows] = useState<string[]>([]);
    const [statusTab, setStatusTab] = useState<"active" | "inactive">("active");
    const [cleanupDialogOpen, setCleanupDialogOpen] = useState(false);
    const [importOpen, setImportOpen] = useState(false);
    const cleanupRunGuard = useRef(createSingleFlightGuard());

    const [brainstormOpen, setBrainstormOpen] = useState(false);
    const [filterTopicId, setFilterTopicId] = useState<string | null>(null);
    const [filterPlatform, setFilterPlatform] = useState<string | null>(null);
    const [filterProduct, setFilterProduct] = useState<string | null>(null);
    const [sidebarExpandedTopics, setSidebarExpandedTopics] = useState<Set<string>>(new Set());

    // Inline editing state
    const [pendingEdits, setPendingEdits] = useState<Record<string, Record<string, any>>>({});
    const [newRows, setNewRows] = useState<any[]>([]);
    const [savingAll, setSavingAll] = useState(false);
    const [activeIntents, setActiveIntents] = useState<string[]>([]);
    const [intentConfigLoading, setIntentConfigLoading] = useState(false);
    const [intentConfigError, setIntentConfigError] = useState(false);
    const [intentConfigLoaded, setIntentConfigLoaded] = useState(false);
    const [intentConfigClientId, setIntentConfigClientId] = useState<string | null>(null);
    const [intentConfigReloadKey, setIntentConfigReloadKey] = useState(0);
    const intentConfigLoadSeq = useRef(0);
    // Inline add topic / product
    const [addingTopic, setAddingTopic] = useState(false);
    const [newTopicName, setNewTopicName] = useState("");
    const [addingProductForTopic, setAddingProductForTopic] = useState<string | null>(null);
    const [newProductName, setNewProductName] = useState("");

    // ---------- Brainstorm Multi-Select State ----------
    const [bsTopicSelections, setBsTopicSelections] = useState<Record<string, string[]>>({});
    const [bsExpandedTopics, setBsExpandedTopics] = useState<Set<string>>(new Set());
    const [bsCount, setBsCount] = useState("10");
    const [bsCountries, setBsCountries] = useState<string[]>([]);
    const [bsLanguage, setBsLanguage] = useState<string>("");
    const [bsPlatforms, setBsPlatforms] = useState<string[]>([]);

    // Brainstorm Generation State
    const [isGenerating, setIsGenerating] = useState(false);
    const [candidates, setCandidates] = useState<CandidatePrompt[]>([]);
    const [candidatesClientId, setCandidatesClientId] = useState<string | null>(null);

    // Global Languages & Platforms
    const [globalLanguages, setGlobalLanguages] = useState<GlobalLanguage[]>([]);
    const [globalPlatforms, setGlobalPlatforms] = useState<GlobalPlatform[]>([]);
    const clientIdRef = useRef(clientId);
    const promptLoadSeq = useRef(0);
    const promptLoadAbortRef = useRef<AbortController | null>(null);
    const brainstormSeq = useRef(0);
    const brainstormAbortRef = useRef<AbortController | null>(null);
    const candidatesClientIdRef = useRef<string | null>(null);
    clientIdRef.current = clientId;

    useEffect(() => {
        fetchJSON(`${API_BASE}/languages`).then(d => setGlobalLanguages(Array.isArray(d) ? d : [])).catch(() => { });
        fetchJSON(`${API_BASE}/platforms`).then(d => setGlobalPlatforms(Array.isArray(d) ? d : [])).catch(() => { });
    }, []);

    const activeClient = clients.find(c => c.id === clientId) as any;
    const cleanupRequest = getWorkspaceCleanupRequest(location.search);
    const cleanupModeActive = cleanupRequest.enabled && cleanupRequest.clientId === clientId;
    const cleanupWorkspaceMismatch = cleanupRequest.enabled && cleanupRequest.clientId !== clientId;

    // ===== Intersection logic: global ∩ client config (empty client config = nothing) =====
    const clientPlatformIds: string[] = activeClient?.config_platforms || [];
    const clientCountryCodes: string[] = activeClient?.config_countries || [];
    const clientLanguageCodes: string[] = activeClient?.config_languages || [];

    // Available platforms = global platforms ∩ client's allowed platforms
    const availablePlatforms: GlobalPlatform[] = clientPlatformIds.length > 0
        ? globalPlatforms.filter(p => clientPlatformIds.includes(p.platform_id))
        : [];

    // Available countries = union of available platforms' supported_countries ∩ client's allowed countries
    const platformCountries: string[] = Array.from(
        new Set(availablePlatforms.flatMap(p => p.supported_countries || []))
    ).sort();
    const availableCountries: string[] = clientCountryCodes.length > 0
        ? platformCountries.filter(c => clientCountryCodes.includes(c))
        : [];

    // Available languages = global languages ∩ client's allowed languages
    const availableLanguages: GlobalLanguage[] = clientLanguageCodes.length > 0
        ? globalLanguages.filter(l => clientLanguageCodes.includes(l.language_code))
        : [];

    useEffect(() => {
        promptLoadSeq.current += 1;
        promptLoadAbortRef.current?.abort();
        promptLoadAbortRef.current = null;
        brainstormSeq.current += 1;
        brainstormAbortRef.current?.abort();
        brainstormAbortRef.current = null;
        candidatesClientIdRef.current = null;

        setData([]);
        setLoadedClientId(null);
        setEditorStateClientId(null);
        setLoading(Boolean(clientId));
        setSelectedRows([]);
        setStatusTab("active");
        setFilterTopicId(null);
        setFilterPlatform(null);
        setFilterProduct(null);
        setSidebarExpandedTopics(new Set());
        setPendingEdits({});
        setNewRows([]);
        setSavingAll(false);
        setCleanupDialogOpen(false);
        setImportOpen(false);
        setAddingTopic(false);
        setNewTopicName("");
        setAddingProductForTopic(null);
        setNewProductName("");
        setBrainstormOpen(false);
        setBsTopicSelections({});
        setBsExpandedTopics(new Set());
        setBsCount("10");
        setBsCountries([]);
        setBsLanguage("");
        setBsPlatforms([]);
        setIsGenerating(false);
        setCandidates([]);
        setCandidatesClientId(null);
    }, [clientId]);

    useEffect(() => {
        if (!clientId) return;
        void load(clientId);
        return () => {
            promptLoadSeq.current += 1;
            promptLoadAbortRef.current?.abort();
            promptLoadAbortRef.current = null;
        };
    }, [clientId]);

    useEffect(() => {
        setActiveIntents([]);
        setIntentConfigError(false);
        setIntentConfigLoaded(false);
        setIntentConfigClientId(null);
    }, [clientId]);

    useEffect(() => {
        if (!clientId) {
            setIntentConfigLoading(false);
            return;
        }

        const requestId = ++intentConfigLoadSeq.current;
        const controller = new AbortController();
        setIntentConfigLoading(true);
        setIntentConfigError(false);

        getPromptIntentFacets(clientId, { signal: controller.signal })
            .then((facets) => {
                if (requestId !== intentConfigLoadSeq.current) return;
                setActiveIntents(facets.active);
                setIntentConfigLoaded(true);
                setIntentConfigClientId(clientId);
            })
            .catch((err) => {
                if (err?.name === "AbortError" || requestId !== intentConfigLoadSeq.current) return;
                setActiveIntents([]);
                setIntentConfigError(true);
                setIntentConfigLoaded(false);
                setIntentConfigClientId(null);
            })
            .finally(() => {
                if (requestId === intentConfigLoadSeq.current) setIntentConfigLoading(false);
            });

        return () => {
            controller.abort();
            if (intentConfigLoadSeq.current === requestId) intentConfigLoadSeq.current += 1;
        };
    }, [clientId, intentConfigReloadKey]);

    async function load(requestClientId: string = clientIdRef.current) {
        if (!requestClientId || requestClientId !== clientIdRef.current) return;
        promptLoadAbortRef.current?.abort();
        const controller = new AbortController();
        promptLoadAbortRef.current = controller;
        const requestId = ++promptLoadSeq.current;
        setLoading(true);
        try {
            const prompts = await getPrompts(requestClientId, {}, { signal: controller.signal });
            if (requestId !== promptLoadSeq.current || requestClientId !== clientIdRef.current) return;
            setData(prompts);
            setLoadedClientId(requestClientId);
            setEditorStateClientId(requestClientId);
            setSelectedRows([]);
        } catch (e: any) {
            if (e?.name === "AbortError" || requestId !== promptLoadSeq.current) return;
            console.error("Failed to load prompts:", e);
        } finally {
            if (requestId === promptLoadSeq.current && requestClientId === clientIdRef.current) {
                setLoading(false);
                if (promptLoadAbortRef.current === controller) promptLoadAbortRef.current = null;
            }
        }
    }

    function handlePromptImported() {
        const importedClientId = clientIdRef.current;
        if (importedClientId) void load(importedClientId);
    }

    const intentConfigReady = intentConfigClientId === clientId
        && intentConfigLoaded
        && !intentConfigError
        && activeIntents.length > 0;
    const editorStateIsCurrent = isWorkspaceStateOwned(clientId, loadedClientId)
        && isWorkspaceStateOwned(clientId, editorStateClientId);
    const visibleData = editorStateIsCurrent ? data : [];
    const candidatesAreCurrent = isWorkspaceStateOwned(clientId, candidatesClientId)
        && candidatesClientIdRef.current === clientId;
    const visibleCandidates = candidatesAreCurrent ? candidates : [];

    function isEditorStateOwnedNow(): boolean {
        const currentClientId = clientIdRef.current;
        return isWorkspaceStateOwned(currentClientId, loadedClientId)
            && isWorkspaceStateOwned(currentClientId, editorStateClientId);
    }

    function ensureEditorStateOwned(): boolean {
        if (isEditorStateOwnedNow()) return true;
        const currentClientId = clientIdRef.current;
        toast.warning(t("promptEditor.workspaceState.stale"));
        if (currentClientId) void load(currentClientId);
        return false;
    }

    function validateIntentForWrite(intent: string | null | undefined): boolean {
        if (!ensureEditorStateOwned()) return false;
        if (!intentConfigReady) {
            toast.warning(t(intentConfigError
                ? "promptEditor.intentConfig.loadFailed"
                : "promptEditor.intentConfig.unavailable"));
            return false;
        }
        const validation = getIntentWriteValidation(intent, activeIntents);
        if (validation === "missing") {
            toast.warning(t("promptEditor.intentConfig.missingIntent"));
            return false;
        }
        if (validation === "inactive") {
            toast.warning(t("promptEditor.intentConfig.inactiveIntent"));
            return false;
        }
        return true;
    }

    function canonicalIntentForWrite(intent: string | null | undefined): string | null {
        return resolveCanonicalIntent(intent, activeIntents);
    }


    const toggleAll = (prompts: any[]) => {
        if (selectedRows.length === prompts.length) {
            setSelectedRows([]);
        } else {
            setSelectedRows(prompts.map(p => p.id));
        }
    };

    // Filtering: by topic and by platform
    let filteredData = visibleData;
    if (filterTopicId) filteredData = filteredData.filter(p => p.topic_id === filterTopicId);
    if (filterProduct) filteredData = filteredData.filter(p => p.product === filterProduct);
    if (filterPlatform) filteredData = filteredData.filter(p => p.platform === filterPlatform);

    const activePrompts = filteredData.filter(p => p.is_active);
    const inactivePrompts = filteredData.filter(p => !p.is_active);

    // Quota calculation (unique prompt count)
    const clientQuota = (activeClient as any)?.client_prompt_quota || 50;
    const totalPrompts = countUniquePrompts(visibleData.filter(p => p.is_active));
    const quotaPercent = Math.min(100, (totalPrompts / clientQuota) * 100);

    // Topic prompt counts (unique per topic)
    const topicPromptCounts: Record<string, number> = {};
    {
        const topicSeen: Record<string, Set<string>> = {};
        visibleData.forEach(p => {
            if (!topicSeen[p.topic_id]) topicSeen[p.topic_id] = new Set();
            topicSeen[p.topic_id].add(p.text);
        });
        for (const [tid, texts] of Object.entries(topicSeen)) {
            topicPromptCounts[tid] = texts.size;
        }
    }

    async function handleBulkSetStatus(ids: string[], isActive: boolean) {
        if (ids.length === 0) return;
        if (!ensureEditorStateOwned()) return;
        const mutationClientId = clientIdRef.current;
        if (!mutationClientId) return;
        try {
            await batchUpdatePrompts(mutationClientId, ids, { is_active: isActive });
            if (!isWorkspaceStateOwned(clientIdRef.current, mutationClientId)) return;
            await load(mutationClientId);
        } catch (err: any) {
            if (!isWorkspaceStateOwned(clientIdRef.current, mutationClientId)) return;
            toast.error(t("promptEditor.toasts.error", { message: err.message }));
        }
    }



    async function handleDuplicatePrompt(prompt: any) {
        if (!validateIntentForWrite(prompt.intent)) return;
        const canonicalIntent = canonicalIntentForWrite(prompt.intent);
        if (!canonicalIntent) return;
        const mutationClientId = clientIdRef.current;
        if (!mutationClientId) return;
        try {
            await addPrompt(mutationClientId, {
                text: prompt.text,
                topic_id: prompt.topic_id,
                product: prompt.product || "",
                country: prompt.country,
                language: prompt.language,
                platform: prompt.platform,
                intent: canonicalIntent,
            });
            if (!isWorkspaceStateOwned(clientIdRef.current, mutationClientId)) return;
            void load(mutationClientId);
        } catch (err: any) {
            if (!isWorkspaceStateOwned(clientIdRef.current, mutationClientId)) return;
            toast.error(t("promptEditor.toasts.duplicateError", { message: err.message }));
        }
    }

    // ── Bulk Actions ──
    async function handleBulkDuplicate() {
        if (selectedRows.length === 0) return;
        if (!ensureEditorStateOwned()) return;
        const mutationClientId = clientIdRef.current;
        if (!mutationClientId) return;
        try {
            const selectedPrompts = visibleData.filter(p => selectedRows.includes(p.id));
            if (selectedPrompts.length > 0) {
                if (!selectedPrompts.every((prompt) => validateIntentForWrite(prompt.intent))) return;
                await batchCreatePrompts(mutationClientId, selectedPrompts.map(p => ({
                    text: p.text,
                    topic_id: p.topic_id,
                    product: p.product || "",
                    countries: [p.country],
                    language: p.language,
                    platforms: [p.platform],
                    intent: canonicalIntentForWrite(p.intent)!,
                })));
            }
            if (!isWorkspaceStateOwned(clientIdRef.current, mutationClientId)) return;
            await load(mutationClientId);
        } catch (err: any) {
            if (!isWorkspaceStateOwned(clientIdRef.current, mutationClientId)) return;
            toast.error(t("promptEditor.toasts.bulkDuplicateError", { message: err.message }));
        }
    }

    async function handleBulkStatusChange() {
        if (selectedRows.length === 0) return;
        if (!ensureEditorStateOwned()) return;
        const mutationClientId = clientIdRef.current;
        if (!mutationClientId) return;
        const nextActive = statusTab === "inactive";
        try {
            await batchUpdatePrompts(mutationClientId, selectedRows, { is_active: nextActive });
            if (!isWorkspaceStateOwned(clientIdRef.current, mutationClientId)) return;
            await load(mutationClientId);
        } catch (err: any) {
            if (!isWorkspaceStateOwned(clientIdRef.current, mutationClientId)) return;
            toast.error(t("promptEditor.toasts.bulkDisableError", { message: err.message }));
        }
    }

    async function handleBulkDelete() {
        if (selectedRows.length === 0) return;
        if (!ensureEditorStateOwned()) return;
        const mutationClientId = clientIdRef.current;
        if (!mutationClientId) return;
        const batchSize = getManualPromptDeleteBatchSize(selectedRows.length);
        if (batchSize == null) {
            toast.warning(t("promptEditor.toasts.bulkDeleteTooLarge", { max: 100 }));
            return;
        }
        if (!await confirmDialog(
            t("promptEditor.toasts.bulkDeleteConfirmMessage", { count: selectedRows.length }),
            t("promptEditor.toasts.bulkDeleteConfirmTitle"),
        )) return;
        if (!isWorkspaceStateOwned(clientIdRef.current, mutationClientId)) return;
        setLoading(true);
        const toastId = toast.loading(t("promptEditor.toasts.bulkDeleting", { count: selectedRows.length }));
        try {
            await batchDeletePrompts(mutationClientId, selectedRows, batchSize);
            if (!isWorkspaceStateOwned(clientIdRef.current, mutationClientId)) return;
            toast.success(t("promptEditor.toasts.bulkDeleted"), { id: toastId });
            await load(mutationClientId);
        } catch (err: any) {
            if (!isWorkspaceStateOwned(clientIdRef.current, mutationClientId)) return;
            toast.error(t("promptEditor.toasts.bulkDeleteError", { message: err.message }), { id: toastId });
        } finally {
            if (isWorkspaceStateOwned(clientIdRef.current, mutationClientId)) {
                setLoading(false);
            } else {
                toast.dismiss(toastId);
            }
        }
    }

    async function handleWorkspaceCleanup(
        onProgress: (progress: WorkspaceCleanupProgress) => void,
    ): Promise<WorkspaceCleanupProgress> {
        const mutationClientId = clientIdRef.current;
        if (!mutationClientId || mutationClientId !== cleanupRequest.clientId || !cleanupRunGuard.current.tryStart()) {
            return {
                status: "failed",
                total: 0,
                deleted: 0,
                remaining: 0,
                error: new Error(t("promptEditor.cleanup.staleWorkspace")),
            };
        }
        try {
            let latestPromptRows: Awaited<ReturnType<typeof getPrompts>> = [];
            const result = await runSerialPromptCleanup({
                loadPromptIds: async () => {
                    const prompts = await getPrompts(mutationClientId);
                    if (clientIdRef.current !== mutationClientId) throw new Error(t("promptEditor.cleanup.staleWorkspace"));
                    latestPromptRows = prompts;
                    return prompts.map((prompt) => prompt.id);
                },
                deleteBatch: (promptIds, batchSize) => {
                    if (clientIdRef.current !== mutationClientId) {
                        throw new Error(t("promptEditor.cleanup.staleWorkspace"));
                    }
                    return batchDeletePrompts(mutationClientId, promptIds, batchSize);
                },
                onProgress,
                onRefreshedPromptIds: () => {
                    if (!isWorkspaceStateOwned(clientIdRef.current, mutationClientId)) return;
                    setData(latestPromptRows);
                    setLoadedClientId(mutationClientId);
                    setEditorStateClientId(mutationClientId);
                    setSelectedRows([]);
                },
            });
            return result;
        } finally {
            cleanupRunGuard.current.finish();
        }
    }

    async function handleBulkEditField(field: string, value: string) {
        if (selectedRows.length === 0) return;
        if (!ensureEditorStateOwned()) return;
        const mutationClientId = clientIdRef.current;
        if (!mutationClientId) return;
        if (field === "intent" && !validateIntentForWrite(value)) return;
        const canonicalValue = field === "intent" ? canonicalIntentForWrite(value) : value;
        if (field === "intent" && !canonicalValue) return;
        try {
            await batchUpdatePrompts(mutationClientId, selectedRows, { [field]: canonicalValue });
            if (!isWorkspaceStateOwned(clientIdRef.current, mutationClientId)) return;
            await load(mutationClientId);
        } catch (err: any) {
            if (!isWorkspaceStateOwned(clientIdRef.current, mutationClientId)) return;
            toast.error(t("promptEditor.toasts.bulkEditError", { message: err.message }));
        }
    }

    // ── Topic/Product Management ──
    async function handleAddTopicSubmit() {
        if (!newTopicName.trim()) { setAddingTopic(false); return; }
        if (!ensureEditorStateOwned()) return;
        const mutationClientId = clientIdRef.current;
        if (!mutationClientId) return;
        try {
            await createTopic(mutationClientId, newTopicName.trim());
            if (!isWorkspaceStateOwned(clientIdRef.current, mutationClientId)) return;
            await refreshClients();
            if (!isWorkspaceStateOwned(clientIdRef.current, mutationClientId)) return;
            setNewTopicName("");
            setAddingTopic(false);
        } catch (err: any) {
            if (!isWorkspaceStateOwned(clientIdRef.current, mutationClientId)) return;
            toast.error(t("promptEditor.toasts.addTopicError", { message: err.message }));
        }
    }

    async function handleAddProductSubmit(topicId: string) {
        if (!newProductName.trim()) { setAddingProductForTopic(null); return; }
        if (!ensureEditorStateOwned()) return;
        const mutationClientId = clientIdRef.current;
        if (!mutationClientId) return;
        try {
            await addProductToTopic(mutationClientId, topicId, newProductName.trim());
            if (!isWorkspaceStateOwned(clientIdRef.current, mutationClientId)) return;
            await refreshClients();
            if (!isWorkspaceStateOwned(clientIdRef.current, mutationClientId)) return;
            setNewProductName("");
            setAddingProductForTopic(null);
        } catch (err: any) {
            if (!isWorkspaceStateOwned(clientIdRef.current, mutationClientId)) return;
            toast.error(t("promptEditor.toasts.addProductError", { message: err.message }));
        }
    }

    // Inline editing
    function editField(id: string, field: string, value: any) {
        setPendingEdits(prev => ({
            ...prev,
            [id]: { ...(prev[id] || {}), [field]: value },
        }));
    }

    function getEditValue(prompt: any, field: string) {
        return pendingEdits[prompt.id]?.[field] ?? prompt[field];
    }

    function handleAddRow() {
        if (!intentConfigReady) {
            validateIntentForWrite(null);
            return;
        }
        const firstTopic = activeClient?.topics?.[0] as any;
        const newId = `new_${Date.now()}_${Math.random().toString(36).slice(2, 7)}`;
        setNewRows(prev => [{
            _tempId: newId,
            text: "",
            topic_id: filterTopicId || firstTopic?.id || "",
            product: filterProduct || "",
            countries: [...availableCountries],
            language: availableLanguages[0]?.language_code || "en-US",
            platforms: availablePlatforms.map(p => p.platform_id),
            intent: "",
            is_active: true,
        }, ...prev]);
    }

    async function handleSaveAll() {
        if (!ensureEditorStateOwned()) return;
        const mutationClientId = clientIdRef.current;
        if (!mutationClientId) return;
        const rowsToCreate = newRows.filter((row) => row.text?.trim() && row.topic_id);
        if (rowsToCreate.some((row) => !validateIntentForWrite(row.intent))) return;
        const pendingIntentValues = Object.values(pendingEdits)
            .filter((edits) => Object.prototype.hasOwnProperty.call(edits, "intent"))
            .map((edits) => edits.intent as string | null | undefined);
        if (pendingIntentValues.some((intent) => !validateIntentForWrite(intent))) return;

        setSavingAll(true);
        try {
            const newPromptPayload = rowsToCreate
                .map((row) => ({
                    topic_id: row.topic_id,
                    text: row.text.trim(),
                    intent: canonicalIntentForWrite(row.intent)!,
                    product: row.product || "",
                    platforms: row.platforms || [],
                    countries: row.countries || [],
                    language: row.language || "en-US",
                }));

            if (newPromptPayload.length > 0) {
                await batchCreatePrompts(mutationClientId, newPromptPayload);
                if (!isWorkspaceStateOwned(clientIdRef.current, mutationClientId)) return;
            }
            const editGroups = new Map<string, { ids: string[]; edits: Record<string, any> }>();
            for (const [promptId, edits] of Object.entries(pendingEdits)) {
                if (Object.keys(edits).length === 0) continue;
                const canonicalEdits = Object.prototype.hasOwnProperty.call(edits, "intent")
                    ? { ...edits, intent: canonicalIntentForWrite(edits.intent) }
                    : edits;
                const key = JSON.stringify(canonicalEdits);
                const existing = editGroups.get(key);
                if (existing) {
                    existing.ids.push(promptId);
                } else {
                    editGroups.set(key, { ids: [promptId], edits: canonicalEdits });
                }
            }
            for (const { ids, edits } of editGroups.values()) {
                if (!isWorkspaceStateOwned(clientIdRef.current, mutationClientId)) return;
                await batchUpdatePrompts(mutationClientId, ids, edits);
            }
            if (!isWorkspaceStateOwned(clientIdRef.current, mutationClientId)) return;
            setPendingEdits({});
            setNewRows([]);
            await load(mutationClientId);
        } catch (err: any) {
            if (!isWorkspaceStateOwned(clientIdRef.current, mutationClientId)) return;
            toast.error(t("promptEditor.toasts.saveError", { message: err.message }));
        } finally {
            if (isWorkspaceStateOwned(clientIdRef.current, mutationClientId)) setSavingAll(false);
        }
    }

    const hasPendingChanges = Object.keys(pendingEdits).length > 0 || newRows.length > 0;
    const pendingCount = Object.keys(pendingEdits).length + newRows.length;

    // ---------- Brainstorm Dialog Helpers ----------

    // Initialize defaults when dialog opens
    useEffect(() => {
        if (brainstormOpen && activeClient) {
            if (!bsLanguage && availableLanguages.length > 0) {
                setBsLanguage(availableLanguages[0].language_code);
            }
            if (bsPlatforms.length === 0 && availablePlatforms.length > 0) {
                setBsPlatforms([availablePlatforms[0].platform_id]);
            }
        }
    }, [brainstormOpen, activeClient, availableLanguages, availablePlatforms]);

    // Reset brainstorm state when dialog closes
    useEffect(() => {
        if (!brainstormOpen) {
            setBsCountries([]);
        }
    }, [brainstormOpen]);

    // Topic/Product tree
    const toggleTopicSelection = (topicId: string) => {
        setBsTopicSelections(prev => {
            const next = { ...prev };
            if (next[topicId]) {
                delete next[topicId];
            } else {
                const topic = activeClient?.topics.find((tp: any) => tp.id === topicId);
                next[topicId] = topic?.products || [];
            }
            return next;
        });
    };

    const toggleProductSelection = (topicId: string, product: string) => {
        setBsTopicSelections(prev => {
            const next = { ...prev };
            const current = next[topicId] || [];
            if (current.includes(product)) {
                next[topicId] = current.filter(p => p !== product);
                if (next[topicId].length === 0) delete next[topicId];
            } else {
                next[topicId] = [...current, product];
            }
            return next;
        });
    };

    const toggleTopicExpand = (topicId: string) => {
        setBsExpandedTopics(prev => {
            const next = new Set(prev);
            next.has(topicId) ? next.delete(topicId) : next.add(topicId);
            return next;
        });
    };

    const selectedTopicCount = Object.keys(bsTopicSelections).length;

    const selectAllCandidates = (select: boolean) => {
        if (!candidatesAreCurrent) return;
        setCandidates((current) => current.map(c => ({ ...c, selected: select })));
    };

    const toggleCandidate = (index: number) => {
        if (!candidatesAreCurrent) return;
        setCandidates((current) => current.map((candidate, candidateIndex) => (
            candidateIndex === index ? { ...candidate, selected: !candidate.selected } : candidate
        )));
    };

    const updateCandidateIntent = (index: number, intent: string) => {
        if (!candidatesAreCurrent || !activeIntents.includes(intent)) return;
        setCandidates((current) => current.map((candidate, candidateIndex) => (
            candidateIndex === index ? { ...candidate, intent } : candidate
        )));
    };

    function handleBrainstormOpenChange(open: boolean) {
        if (open) {
            setBrainstormOpen(true);
            return;
        }
        brainstormSeq.current += 1;
        brainstormAbortRef.current?.abort();
        brainstormAbortRef.current = null;
        candidatesClientIdRef.current = null;
        setBrainstormOpen(false);
        setIsGenerating(false);
        setCandidates([]);
        setCandidatesClientId(null);
    }

    // ---------- Brainstorm Generate ----------
    async function handleStartBrainstorm() {
        if (!ensureEditorStateOwned()) return;
        if (!clientId || selectedTopicCount === 0) {
            toast.warning(t("promptEditor.toasts.needTopic"));
            return;
        }
        if (bsPlatforms.length === 0) {
            toast.warning(t("promptEditor.toasts.needPlatform"));
            return;
        }
        if (bsCountries.length === 0) {
            toast.warning(t("promptEditor.toasts.needCountry"));
            return;
        }
        if (!bsLanguage) {
            toast.warning(t("promptEditor.toasts.needLanguage"));
            return;
        }

        const requestClientId = clientIdRef.current;
        if (!requestClientId) return;
        brainstormAbortRef.current?.abort();
        const controller = new AbortController();
        brainstormAbortRef.current = controller;
        const requestId = ++brainstormSeq.current;
        candidatesClientIdRef.current = requestClientId;
        setCandidatesClientId(requestClientId);
        setIsGenerating(true);
        setCandidates([]);

        try {
            const response = await fetch(`${API_BASE}/brainstorming/generate`, {
                method: "POST",
                headers: { "Content-Type": "application/json", ...authHeaders() },
                signal: controller.signal,
                body: JSON.stringify({
                    client_id: requestClientId,
                    topics: Object.entries(bsTopicSelections).map(([topic_id, product_names]) => ({
                        topic_id,
                        product_names,
                    })),
                    prompts_per_product: parseInt(bsCount) || 10,
                    countries: bsCountries,
                    language: bsLanguage,
                    platforms: bsPlatforms,
                }),
            });

            if (requestId !== brainstormSeq.current || requestClientId !== clientIdRef.current) return;

            if (!response.ok) {
                const detail = await response
                    .json()
                    .then((body) => body?.detail)
                    .catch(() => "");
                handleAuthExpiredResponse(response, detail || `HTTP ${response.status}`);
                throw new Error(detail || `HTTP ${response.status}`);
            }
            if (!response.body) throw new Error("No response body");

            const reader = response.body.getReader();
            const decoder = new TextDecoder();
            let buffer = "";

            try {
                while (true) {
                    const { done, value } = await reader.read();
                    if (done) break;
                    buffer += decoder.decode(value, { stream: true });
                    const lines = buffer.split("\n\n");
                    buffer = lines.pop() || "";

                    for (const chunk of lines) {
                        if (requestId !== brainstormSeq.current || requestClientId !== clientIdRef.current) return;
                        if (chunk.startsWith("data: ")) {
                            try {
                                const event = JSON.parse(chunk.slice(6));
                                if (event.type === "prompt") {
                                    setCandidates(prev => {
                                        if (requestId !== brainstormSeq.current
                                            || requestClientId !== clientIdRef.current
                                            || candidatesClientIdRef.current !== requestClientId) return prev;
                                        return [...prev, {
                                            text: event.text,
                                            intent: typeof event.intent === "string" ? event.intent : "",
                                            selected: true,
                                            topic_id: event.topic_id || "",
                                            topic_name: event.topic_name || "",
                                            product: event.product || "",
                                            platforms: event.platforms || bsPlatforms,
                                            countries: event.countries || bsCountries,
                                            language: event.language || "",
                                        }];
                                    });
                                }
                            } catch { }
                        }
                    }
                }
            } finally {
                await reader.cancel().catch(() => undefined);
                reader.releaseLock();
            }
        } catch (err: any) {
            if (err?.name === "AbortError" || requestId !== brainstormSeq.current || requestClientId !== clientIdRef.current) return;
            toast.error(t("promptEditor.toasts.brainstormError", { message: err.message }));
        } finally {
            if (requestId === brainstormSeq.current && requestClientId === clientIdRef.current) {
                setIsGenerating(false);
                if (brainstormAbortRef.current === controller) brainstormAbortRef.current = null;
            }
        }
    }

    // ---------- Save Brainstormed Prompts ----------
    async function handleSaveBrainstorms() {
        if (!ensureEditorStateOwned()) return;
        if (!candidatesAreCurrent) {
            toast.warning(t("promptEditor.workspaceState.stale"));
            return;
        }
        const selected = visibleCandidates.filter(c => c.selected);
        if (selected.length === 0) return;
        if (!areSelectedCandidateIntentsActive(selected, activeIntents)) {
            toast.warning(t("promptEditor.intentConfig.inactiveIntent"));
            return;
        }
        const mutationClientId = clientIdRef.current;
        if (!mutationClientId) return;

        // Quota check: count unique new prompt texts being added
        const existingTexts = new Set(visibleData.filter(p => p.is_active).map(p => `${p.text}|||${p.topic_id}`));
        const newUniqueCount = new Set(
            selected.map(c => `${c.text}|||${c.topic_id}`).filter(k => !existingTexts.has(k))
        ).size;
        if (totalPrompts + newUniqueCount > clientQuota) {
            toast.error(t("promptEditor.toasts.quotaExceeded", {
                existing: totalPrompts,
                new_count: newUniqueCount,
                total: totalPrompts + newUniqueCount,
                quota: clientQuota,
            }));
            return;
        }

        setLoading(true);
        try {
            const promptsPayload = selected.map((c) => ({
                topic_id: c.topic_id,
                text: c.text,
                intent: canonicalIntentForWrite(c.intent)!,
                product: c.product,
                platforms: c.platforms,
                countries: c.countries,
                language: c.language,
            }));
            await batchCreatePrompts(mutationClientId, promptsPayload);
            if (!isWorkspaceStateOwned(clientIdRef.current, mutationClientId)) return;
            handleBrainstormOpenChange(false);
            void load(mutationClientId);
        } catch (err: any) {
            if (!isWorkspaceStateOwned(clientIdRef.current, mutationClientId)) return;
            toast.error(t("promptEditor.toasts.saveBrainstormError", { message: err.message }));
        } finally {
            if (isWorkspaceStateOwned(clientIdRef.current, mutationClientId)) setLoading(false);
        }
    }

    // ---------- Unique values for table filters ----------
    const uniquePlatforms = Array.from(new Set(visibleData.map(p => p.platform).filter(Boolean)));

    if (!clientId) {
        return <div className="p-8 text-center text-muted-foreground">{t("promptEditor.pleaseSelectWorkspace")}</div>;
    }

    return (
        <div className="flex flex-col h-full bg-muted/10 p-6">
            {/* Header */}
            <div className="flex items-center justify-between mb-6">
                <div className="flex items-center gap-3">
                    <Button variant="ghost" size="sm" onClick={() => navigate("/insights/prompts")}>
                        <ChevronLeft className="h-4 w-4 mr-1" /> {t("promptEditor.back")}
                    </Button>
                    <h1 className="text-2xl font-bold tracking-tight">{t("promptEditor.pageTitle")}</h1>
                </div>

                {/* Quota Progress */}
                <div className="text-right">
                    <div className="text-xs text-muted-foreground mb-1">{t("promptEditor.quotaUsed", { used: totalPrompts, quota: clientQuota })}</div>
                    <div className="w-40 h-2 bg-muted rounded-full overflow-hidden">
                        <div
                            className={`h-full rounded-full transition-all ${quotaPercent > 90 ? 'bg-red-500' : quotaPercent > 70 ? 'bg-yellow-500' : 'bg-primary'}`}
                            style={{ width: `${quotaPercent}%` }}
                        />
                    </div>
                </div>
            </div>

            <fieldset
                disabled={configurationReadOnly}
                className="min-h-0 flex flex-1 flex-col border-0 p-0"
            >
            {cleanupModeActive && (
                <div className="mb-4 flex flex-wrap items-center justify-between gap-3 rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-3">
                    <div>
                        <div className="font-semibold text-destructive">{t("promptEditor.cleanup.modeTitle")}</div>
                        <p className="text-sm text-muted-foreground">
                            {t("promptEditor.cleanup.modeDescription", { count: visibleData.length })}
                        </p>
                    </div>
                    <Button variant="destructive" onClick={() => setCleanupDialogOpen(true)} disabled={!editorStateIsCurrent}>
                        <Trash2 className="mr-2 h-4 w-4" /> {t("promptEditor.cleanup.open")}
                    </Button>
                </div>
            )}
            {cleanupWorkspaceMismatch && (
                <div role="alert" className="mb-4 rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-3 text-sm text-destructive">
                    {t("promptEditor.cleanup.workspaceUnavailable")}
                </div>
            )}

            {/* Topic Sidebar + Main Content */}
            <div className="flex gap-4 flex-1 min-h-0">
                {/* Topic Sidebar */}
                <TopicSidebar
                    data={visibleData}
                    activeClient={activeClient}
                    filterTopicId={filterTopicId}
                    setFilterTopicId={setFilterTopicId}
                    filterProduct={filterProduct}
                    setFilterProduct={setFilterProduct}
                    sidebarExpandedTopics={sidebarExpandedTopics}
                    setSidebarExpandedTopics={setSidebarExpandedTopics}
                    topicPromptCounts={topicPromptCounts}
                    addingTopic={addingTopic}
                    setAddingTopic={setAddingTopic}
                    newTopicName={newTopicName}
                    setNewTopicName={setNewTopicName}
                    handleAddTopicSubmit={handleAddTopicSubmit}
                    addingProductForTopic={addingProductForTopic}
                    setAddingProductForTopic={setAddingProductForTopic}
                    newProductName={newProductName}
                    setNewProductName={setNewProductName}
                    handleAddProductSubmit={handleAddProductSubmit}
                />

                {/* Main Content Area */}
                <div className="flex-1 flex flex-col min-w-0">
                    {(intentConfigLoading || intentConfigError || (intentConfigLoaded && activeIntents.length === 0)) && (
                        <div
                            role={intentConfigError || (intentConfigLoaded && activeIntents.length === 0) ? "alert" : "status"}
                            className="mb-4 flex items-center justify-between gap-3 rounded-md border bg-card px-3 py-2 text-sm"
                        >
                            <div className="flex items-center gap-2 text-muted-foreground">
                                {intentConfigLoading && <Loader2 className="h-4 w-4 animate-spin" />}
                                <span>
                                    {intentConfigLoading
                                        ? t("promptEditor.intentConfig.loading")
                                        : intentConfigError
                                            ? t("promptEditor.intentConfig.loadFailed")
                                            : t("promptEditor.intentConfig.noActive")}
                                </span>
                            </div>
                            {intentConfigError && (
                                <Button
                                    type="button"
                                    variant="outline"
                                    size="sm"
                                    onClick={() => setIntentConfigReloadKey((key) => key + 1)}
                                >
                                    {t("common:actions.retry")}
                                </Button>
                            )}
                        </div>
                    )}
                    <Tabs
                        value={statusTab}
                        onValueChange={(value) => {
                            setStatusTab(value as "active" | "inactive");
                            setSelectedRows([]);
                        }}
                        className="flex-1 flex flex-col"
                    >
                        <div className="flex justify-between items-center mb-4">
                            <div className="flex items-center gap-3">
                                <TabsList>
                                    <TabsTrigger value="active">{t("promptEditor.tabs.active")} <Badge variant="secondary" className="ml-2 bg-background">{countUniquePrompts(activePrompts)}</Badge></TabsTrigger>
                                    <TabsTrigger value="inactive">{t("promptEditor.tabs.inactive")} <Badge variant="secondary" className="ml-2 bg-background">{countUniquePrompts(inactivePrompts)}</Badge></TabsTrigger>
                                </TabsList>

                                {/* Topic Filter Dropdown */}
                                <Popover>
                                    <PopoverTrigger asChild>
                                        <Button variant="outline" size="sm" className="gap-1.5 h-8 text-xs">
                                            <span className="text-muted-foreground">#</span>
                                            {filterTopicId ? (activeClient?.topics.find((tp: any) => tp.id === filterTopicId)?.topic_name || t("promptEditor.filterTopicAll")) : t("promptEditor.filterTopicAll")}
                                            <ChevronDown className="h-3 w-3 ml-1 text-muted-foreground" />
                                        </Button>
                                    </PopoverTrigger>
                                    <PopoverContent className="w-48 p-1" align="start">
                                        <button
                                            className={`w-full text-left px-3 py-1.5 rounded text-sm hover:bg-accent/50 ${!filterTopicId ? 'font-semibold' : ''}`}
                                            onClick={() => setFilterTopicId(null)}
                                        >{t("promptEditor.allTopics")}</button>
                                        {(activeClient?.topics || []).map((tp: any) => (
                                            <button
                                                key={tp.id}
                                                className={`w-full text-left px-3 py-1.5 rounded text-sm hover:bg-accent/50 truncate ${filterTopicId === tp.id ? 'font-semibold bg-accent/30' : ''}`}
                                                onClick={() => setFilterTopicId(tp.id)}
                                            >{tp.topic_name}</button>
                                        ))}
                                    </PopoverContent>
                                </Popover>

                                {/* Platform Filter Dropdown */}
                                <Popover>
                                    <PopoverTrigger asChild>
                                        <Button variant="outline" size="sm" className="gap-1.5 h-8 text-xs">
                                            <Monitor className="h-3.5 w-3.5 text-muted-foreground" />
                                            {filterPlatform || t("promptEditor.filterPlatformAll")}
                                            <ChevronDown className="h-3 w-3 ml-1 text-muted-foreground" />
                                        </Button>
                                    </PopoverTrigger>
                                    <PopoverContent className="w-44 p-1" align="start">
                                        <button
                                            className={`w-full text-left px-3 py-1.5 rounded text-sm hover:bg-accent/50 ${!filterPlatform ? 'font-semibold' : ''}`}
                                            onClick={() => setFilterPlatform(null)}
                                        >{t("prompts.filters.allPlatforms")}</button>
                                        {uniquePlatforms.map(p => (
                                            <button
                                                key={p}
                                                className={`w-full text-left px-3 py-1.5 rounded text-sm hover:bg-accent/50 ${filterPlatform === p ? 'font-semibold bg-accent/30' : ''}`}
                                                onClick={() => setFilterPlatform(p)}
                                            >{p}</button>
                                        ))}
                                    </PopoverContent>
                                </Popover>
                            </div>

                            <div className="flex gap-2">
                                <Button
                                    variant="outline"
                                    onClick={() => setImportOpen(true)}
                                    disabled={!editorStateIsCurrent}
                                >
                                    <Upload className="h-4 w-4 mr-2" /> {t("promptEditor.batchUpload")}
                                </Button>
                                <Button variant="outline"><FileDown className="h-4 w-4 mr-2" /> {t("promptEditor.exportBtn")}</Button>
                                <Button variant="outline" onClick={handleAddRow} disabled={!intentConfigReady || !editorStateIsCurrent}><Plus className="h-4 w-4 mr-2" /> {t("promptEditor.addPromptBtn")}</Button>
                                <Button onClick={() => setBrainstormOpen(true)} disabled={!intentConfigReady || !editorStateIsCurrent}>
                                    <Sparkles className="h-4 w-4 mr-2" /> {t("promptEditor.generate")}
                                </Button>
                                <Button
                                    onClick={handleSaveAll}
                                    disabled={!hasPendingChanges || savingAll || !editorStateIsCurrent || (newRows.length > 0 && !intentConfigReady)}
                                    className="min-w-[150px]"
                                >
                                    {savingAll ? <Loader2 className="h-4 w-4 mr-2 animate-spin" /> : <Save className="h-4 w-4 mr-2" />}
                                    {t("promptEditor.saveAllChanges")}
                                    {pendingCount > 0 && (
                                        <Badge variant="secondary" className="ml-2 bg-primary-foreground/20 text-[10px] h-4 px-1.5">
                                            {pendingCount}
                                        </Badge>
                                    )}
                                </Button>
                            </div>
                        </div>

                        <TabsContent value="active" className="flex-1 m-0">
                            {loading ? <div className="p-8 text-center text-muted-foreground animate-pulse">{t("promptEditor.loading")}</div> : (
                                <PromptTable
                                    prompts={activePrompts}
                                    showNewRows={true}
                                    newRows={newRows}
                                    setNewRows={setNewRows}
                                    selectedRows={selectedRows}
                                    setSelectedRows={setSelectedRows}
                                    pendingEdits={pendingEdits}
                                    activeClient={activeClient}
                                    availableCountries={availableCountries}
                                    availableLanguages={availableLanguages}
                                    availablePlatforms={availablePlatforms}
                                    activeIntents={activeIntents}
                                    validateIntentForWrite={validateIntentForWrite}
                                    ensureWorkspaceStateOwned={ensureEditorStateOwned}
                                    isWorkspaceStateOwned={isEditorStateOwnedNow}
                                    clientId={clientId}
                                    load={load}
                                    editField={editField}
                                    getEditValue={getEditValue}
                                    toggleAll={toggleAll}
                                    handleDuplicatePrompt={handleDuplicatePrompt}
                                    handleBulkSetStatus={handleBulkSetStatus}
                                    confirmDialog={confirmDialog}
                                />
                            )}
                        </TabsContent>

                        <TabsContent value="inactive" className="flex-1 m-0">
                            {loading ? <div className="p-8 text-center text-muted-foreground animate-pulse">{t("promptEditor.loading")}</div> : (
                                <PromptTable
                                    prompts={inactivePrompts}
                                    newRows={newRows}
                                    setNewRows={setNewRows}
                                    selectedRows={selectedRows}
                                    setSelectedRows={setSelectedRows}
                                    pendingEdits={pendingEdits}
                                    activeClient={activeClient}
                                    availableCountries={availableCountries}
                                    availableLanguages={availableLanguages}
                                    availablePlatforms={availablePlatforms}
                                    activeIntents={activeIntents}
                                    validateIntentForWrite={validateIntentForWrite}
                                    ensureWorkspaceStateOwned={ensureEditorStateOwned}
                                    isWorkspaceStateOwned={isEditorStateOwnedNow}
                                    clientId={clientId}
                                    load={load}
                                    editField={editField}
                                    getEditValue={getEditValue}
                                    toggleAll={toggleAll}
                                    handleDuplicatePrompt={handleDuplicatePrompt}
                                    handleBulkSetStatus={handleBulkSetStatus}
                                    confirmDialog={confirmDialog}
                                />
                            )}
                        </TabsContent>
                    </Tabs>

                    {/* ══ Bulk Action Bar ══ */}
                    {selectedRows.length > 0 && (
                        <BulkActionBar
                            selectedRows={selectedRows}
                            setSelectedRows={setSelectedRows}
                            availableCountries={availableCountries}
                            availablePlatforms={availablePlatforms}
                            statusAction={statusTab === "inactive" ? "activate" : "disable"}
                            handleBulkDuplicate={handleBulkDuplicate}
                            handleBulkStatusChange={handleBulkStatusChange}
                            handleBulkDelete={handleBulkDelete}
                            handleBulkEditField={handleBulkEditField}
                        />
                    )}

                    {/* ====================== Brainstorm Dialog ====================== */}
                    <BrainstormDialog
                        brainstormOpen={brainstormOpen && editorStateIsCurrent}
                        setBrainstormOpen={handleBrainstormOpenChange}
                        activeClient={activeClient}
                        bsTopicSelections={bsTopicSelections}
                        bsExpandedTopics={bsExpandedTopics}
                        toggleTopicSelection={toggleTopicSelection}
                        toggleProductSelection={toggleProductSelection}
                        toggleTopicExpand={toggleTopicExpand}
                        selectedTopicCount={selectedTopicCount}
                        bsCount={bsCount}
                        setBsCount={setBsCount}
                        bsCountries={bsCountries}
                        setBsCountries={setBsCountries}
                        bsLanguage={bsLanguage}
                        setBsLanguage={setBsLanguage}
                        bsPlatforms={bsPlatforms}
                        setBsPlatforms={setBsPlatforms}
                        availableCountries={availableCountries}
                        availableLanguages={availableLanguages}
                        availablePlatforms={availablePlatforms}
                        isGenerating={isGenerating && candidatesAreCurrent}
                        candidates={visibleCandidates}
                        activeIntents={activeIntents}
                        selectedCandidateIntentsValid={areSelectedCandidateIntentsActive(visibleCandidates, activeIntents)}
                        selectAllCandidates={selectAllCandidates}
                        toggleCandidate={toggleCandidate}
                        updateCandidateIntent={updateCandidateIntent}
                        handleStartBrainstorm={handleStartBrainstorm}
                        handleSaveBrainstorms={handleSaveBrainstorms}
                    />
                    <WorkspaceCleanupDialog
                        open={cleanupDialogOpen && cleanupModeActive}
                        onOpenChange={setCleanupDialogOpen}
                        workspaceName={activeClient?.name || ""}
                        currentPhysicalCount={visibleData.length}
                        runCleanup={handleWorkspaceCleanup}
                    />
                    <PromptImportDialog
                        key={promptImportWorkspaceRenderKey(clientId)}
                        clientId={clientId}
                        workspaceName={activeClient?.name || ""}
                        open={importOpen && editorStateIsCurrent}
                        onOpenChange={setImportOpen}
                        onImported={handlePromptImported}
                    />
                </div>{/* end main content area */}
            </div>{/* end sidebar + main wrapper */}
            </fieldset>
        </div>
    );
}
