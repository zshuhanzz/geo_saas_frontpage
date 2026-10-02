import { useState, useEffect } from "react";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";
import {
  API_BASE,
  fetchJSON,
  createAgentTask,
  updateAgentTask,
  getAgentTask,
  getRankedPrompts,
  getBrands,
  type Brand,
} from "@/lib/api";
import {
  CONTENT_GOAL_DEFS,
  GOAL_DICT_KEY,
  TEMPLATE_CONTENT_TYPE,
  ALL_DOMAINS,
  DEPTH_KEYS,
  DEPTH_ICON,
} from "./constants";
import type {
  ContentTemplate,
  ContentGoal,
  ContentDepth,
  PeerItem,
  RankedPrompt,
} from "./types";
import { addLocalDays, todayDateOnlyString } from "@/lib/dateOnly";

// ─── useContentTask ─────────────────────────────────────────────────
//
// Holds all wizard state, side effects, derived values and submit/complete
// handlers. The main `ContentTaskModal` component remains a thin orchestrator
// that wires these into the step components and the global modal chrome.

interface UseContentTaskArgs {
  open: boolean;
  template: ContentTemplate | null;
  clientId: string;
  userId: string;
  clientPlatforms: string[];
  existingTaskId?: string | null;
  onClose: () => void;
  onTaskCreated?: () => void;
}

export function useContentTask({
  open,
  template,
  clientId,
  userId,
  clientPlatforms,
  existingTaskId,
  onClose,
  onTaskCreated,
}: UseContentTaskArgs) {
  const { t } = useTranslation("content");
  const [step, setStep] = useState(1);
  const [view, setView] = useState<"config" | "running" | "result">("config");

  // Step 1: Content Goal
  const [contentGoal, setContentGoal] = useState<ContentGoal | null>(null);

  // Step 2: Content type + topic
  const [contentType, setContentType] = useState("faq");
  const [topic, setTopic] = useState("");

  // Step 3: Target config + product facts + peers
  const [platforms, setPlatforms] = useState<string[]>([]);
  const [count, setCount] = useState(5);
  const [language, setLanguage] = useState("zh-CN");
  const [additionalInstructions, setAdditionalInstructions] = useState("");
  const [productFacts, setProductFacts] = useState({ specs: "", features: "", differentiators: "" });
  const [peers, setPeers] = useState<PeerItem[]>([]);
  const [selectedPeers, setSelectedPeers] = useState<string[]>([]);

  // Step 4: Prompt selection
  const [rankedPrompts, setRankedPrompts] = useState<RankedPrompt[]>([]);
  const [loadingPrompts, setLoadingPrompts] = useState(false);
  const [promptSortBy, setPromptSortBy] = useState("visibility");
  const [selectedPromptIds, setSelectedPromptIds] = useState<string[]>([]);
  const [promptSearch, setPromptSearch] = useState("");

  // Step 5: Data & Strategy
  const [selectedDomains, setSelectedDomains] = useState<string[]>([]);
  const defaultDateTo = todayDateOnlyString();
  const defaultDateFrom = addLocalDays(defaultDateTo, -6);
  const [dateFrom, setDateFrom] = useState(defaultDateFrom);
  const [dateTo, setDateTo] = useState(defaultDateTo);
  const [strategyPrompt, setStrategyPrompt] = useState("");
  const [expandPrompt, setExpandPrompt] = useState(false);
  const [contentDepth, setContentDepth] = useState<ContentDepth>("standard");
  const [focusTags, setFocusTags] = useState<string[]>([]);
  const [tagInput, setTagInput] = useState("");
  const [showMethodology, setShowMethodology] = useState(false);

  // Step 6: Model + Cron
  const [contentModelIds, setContentModelIds] = useState<string[]>(["gemini-3.1-pro-preview"]);
  const [modelId, setModelId] = useState("");
  const [cronExpression, setCronExpression] = useState("");

  // Execution state
  const [isSubmitting, setIsSubmitting] = useState(false);
  const [taskId, setTaskId] = useState<string | null>(null);
  const [taskOutput, setTaskOutput] = useState<any>(null);

  // Fetch peers + own brands (v1.2: own brands live in geo_client_brands now,
  // not in geo_client_peers with is_own_brand=true). We merge both lists into
  // the `peers` state so the rest of the modal keeps the same pill-filter
  // semantics.
  useEffect(() => {
    if (open && clientId) {
      Promise.allSettled([
        fetchJSON(`${API_BASE}/settings/peers?client_id=${clientId}`) as Promise<
          { id: string; primary_name: string }[]
        >,
        getBrands(clientId, false),
      ]).then(([peerRes, brandRes]) => {
        const merged: PeerItem[] = [];
        if (brandRes.status === "fulfilled" && Array.isArray(brandRes.value)) {
          for (const b of brandRes.value as Brand[]) {
            merged.push({ id: b.id, primary_name: b.brand_name, is_own_brand: true });
          }
        }
        if (peerRes.status === "fulfilled" && Array.isArray(peerRes.value)) {
          for (const p of peerRes.value) {
            merged.push({ id: p.id, primary_name: p.primary_name, is_own_brand: false });
          }
        }
        setPeers(merged);
      });
    }
  }, [open, clientId]);

  // Reset form when template changes
  useEffect(() => {
    if (!template) return;
    setStep(1);
    setView("config");
    setTaskId(null);
    setTaskOutput(null);
    setContentGoal(null);

    const defaultCT = template.defaults?.content_type || TEMPLATE_CONTENT_TYPE[template.name] || "faq";
    setContentType(defaultCT);
    setCount(5);
    setTopic("");
    setPlatforms([...clientPlatforms]);
    setLanguage("zh-CN");
    setAdditionalInstructions("");
    setProductFacts({ specs: "", features: "", differentiators: "" });
    setSelectedPeers([]);
    setSelectedPromptIds([]);
    setPromptSearch("");
    setPromptSortBy("visibility");
    setContentDepth("standard");
    setFocusTags([]);
    setTagInput("");
    setShowMethodology(false);

    setSelectedDomains(
      template.data_domains && template.data_domains.length > 0
        ? [...template.data_domains]
        : [...ALL_DOMAINS]
    );
    setStrategyPrompt(template.default_prompt || "");
    setExpandPrompt(false);
    setCronExpression("");

    const dt = todayDateOnlyString();
    const df = addLocalDays(dt, -6);
    setDateFrom(df);
    setDateTo(dt);

    fetchJSON(`${API_BASE}/settings/config?key=content_generation_model_list`)
      .then((d: any) => {
        if (d?.value) {
          const ids = d.value.split(",").map((m: string) => m.trim()).filter(Boolean);
          setContentModelIds(ids);
          setModelId(ids[0] || "");
        }
      })
      .catch(() => { });
  }, [template, clientPlatforms]);

  // Fetch ranked prompts when entering step 4
  useEffect(() => {
    if (step === 4 && clientId) {
      setLoadingPrompts(true);
      getRankedPrompts(clientId, promptSortBy, 30)
        .then((data) => setRankedPrompts(data || []))
        .catch(() => setRankedPrompts([]))
        .finally(() => setLoadingPrompts(false));
    }
  }, [step, promptSortBy, clientId]);

  function togglePrompt(id: string) {
    setSelectedPromptIds((prev) =>
      prev.includes(id) ? prev.filter((x) => x !== id) : [...prev, id]
    );
  }

  function toggleDomain(domain: string) {
    setSelectedDomains((prev) =>
      prev.includes(domain) ? prev.filter((d) => d !== domain) : [...prev, domain]
    );
  }

  function togglePeer(peerId: string) {
    setSelectedPeers((prev) =>
      prev.includes(peerId) ? prev.filter((p) => p !== peerId) : [...prev, peerId]
    );
  }

  function addTag() {
    const tag = tagInput.trim();
    if (tag && !focusTags.includes(tag)) setFocusTags([...focusTags, tag]);
    setTagInput("");
  }

  function insertSnippet(snippet: string) {
    setStrategyPrompt(prev => prev + (prev ? "\n" : "") + snippet);
  }

  const filteredPrompts = promptSearch
    ? rankedPrompts.filter(
        (p) =>
          p.prompt_text.toLowerCase().includes(promptSearch.toLowerCase()) ||
          p.topic_name.toLowerCase().includes(promptSearch.toLowerCase())
      )
    : rankedPrompts;

  const goalMeta = CONTENT_GOAL_DEFS.find(g => g.id === contentGoal);
  const goalLabel = goalMeta ? t(`taskModal.goals.items.${GOAL_DICT_KEY[goalMeta.id]}.label`) : "";
  const depthKey = DEPTH_KEYS.find(k => k === contentDepth);
  const depthLabel = depthKey ? t(`taskModal.depth.${depthKey}.label`) : "";
  const depthIcon = depthKey ? DEPTH_ICON[depthKey] : "";
  const contentTypeLabel = (id: string): string =>
    t(`taskModal.contentTypes.items.${id}.label`, { defaultValue: id });
  const domainLabel = (id: string): string =>
    t(`domains.${id}`, { defaultValue: id });
  const hasFacts = !!(productFacts.specs || productFacts.features || productFacts.differentiators);
  const ownBrands = peers.filter(p => p.is_own_brand);
  const competitors = peers.filter(p => !p.is_own_brand);

  const handleSubmit = async (saveOnly: boolean) => {
    setIsSubmitting(true);
    try {
      const taskName = template?.name || `${contentTypeLabel(contentType)} - ${topic.slice(0, 40)}`;
      const inputs = {
        content_goal: contentGoal,
        content_type: contentType,
        topic,
        platforms,
        count,
        language,
        additional_instructions: additionalInstructions,
        product_facts: hasFacts ? productFacts : null,
        peer_ids: selectedPeers.length > 0 ? selectedPeers : null,
        target_prompt_ids: selectedPromptIds,
        data_domains: selectedDomains,
        date_from: dateFrom,
        date_to: dateTo,
        strategy_prompt: strategyPrompt,
        content_depth: contentDepth,
        focus_tags: focusTags.length > 0 ? focusTags : null,
        model_id: modelId || undefined,
        cron_expression: cronExpression || null,
      };

      let result;
      if (existingTaskId) {
        // Editing an existing task — update in place
        result = await updateAgentTask(existingTaskId, {
          client_id: clientId,
          user_id: userId,
          task_name: taskName,
          inputs,
          save_only: saveOnly,
        });
      } else {
        // Creating a new task
        result = await createAgentTask({
          client_id: clientId,
          user_id: userId,
          task_type: "content_generation",
          task_name: taskName,
          template_id: template?.id,
          inputs,
          save_only: saveOnly,
        });
      }

      if (result?.id) {
        setTaskId(result.id);
        if (!saveOnly) {
          setView("running");
        } else {
          onClose();
        }
        onTaskCreated?.();
      }
    } catch (err: any) {
      toast.error(existingTaskId ? t("taskModal.toasts.updateFailed", { message: err.message }) : t("taskModal.toasts.createFailed", { message: err.message }));
    } finally {
      setIsSubmitting(false);
    }
  };

  const handleTaskCompleted = async (completedTaskId: string) => {
    try {
      const detail = await getAgentTask(completedTaskId, clientId);
      if (detail?.output) {
        setTaskOutput(typeof detail.output === "string" ? JSON.parse(detail.output) : detail.output);
      }
      setView("result");
    } catch {
      setView("result");
    }
  };

  return {
    // top-level
    step, setStep,
    view,
    // step 1
    contentGoal, setContentGoal,
    // step 2
    contentType, setContentType,
    topic, setTopic,
    // step 3
    platforms, setPlatforms,
    count, setCount,
    language, setLanguage,
    additionalInstructions, setAdditionalInstructions,
    productFacts, setProductFacts,
    peers,
    selectedPeers,
    togglePeer,
    // step 4
    loadingPrompts,
    promptSortBy, setPromptSortBy,
    selectedPromptIds,
    promptSearch, setPromptSearch,
    togglePrompt,
    filteredPrompts,
    // step 5
    selectedDomains, setSelectedDomains,
    toggleDomain,
    dateFrom, setDateFrom,
    dateTo, setDateTo,
    strategyPrompt, setStrategyPrompt,
    expandPrompt, setExpandPrompt,
    contentDepth, setContentDepth,
    focusTags, setFocusTags,
    tagInput, setTagInput,
    addTag,
    insertSnippet,
    showMethodology, setShowMethodology,
    // step 6
    contentModelIds,
    modelId, setModelId,
    cronExpression, setCronExpression,
    // execution
    isSubmitting,
    taskId,
    taskOutput,
    handleSubmit,
    handleTaskCompleted,
    // derived
    goalMeta,
    goalLabel,
    depthKey,
    depthLabel,
    depthIcon,
    contentTypeLabel,
    domainLabel,
    hasFacts,
    ownBrands,
    competitors,
  };
}
