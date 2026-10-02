import { useState, useEffect } from "react";
import { toast } from "sonner";
import {
  ChevronLeft, ChevronRight, Loader2, Play, Save, X,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { Dialog, DialogContent, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { API_BASE, fetchJSON, createAgentTask, updateAgentTask, getAgentTask, getRankedPrompts, getBrands, type Brand } from "@/lib/api";

import {
  CONTENT_GOAL_DEFS,
  GOAL_DICT_KEY,
  TEMPLATE_CONTENT_TYPE,
  ALL_DOMAINS,
  DEPTH_KEYS,
  DEPTH_ICON,
  TOTAL_STEPS,
} from "./ContentTaskModal.parts/constants";
import type {
  ContentTaskModalProps,
  ContentGoal,
  ContentDepth,
  PeerItem,
  RankedPrompt,
} from "./ContentTaskModal.parts/types";
import { StepIndicator } from "./ContentTaskModal.parts/StepIndicator";
import { GoalStep } from "./ContentTaskModal.parts/steps/GoalStep";
import { ContentTypeStep } from "./ContentTaskModal.parts/steps/ContentTypeStep";
import { TargetConfigStep } from "./ContentTaskModal.parts/steps/TargetConfigStep";
import { PromptSelectStep } from "./ContentTaskModal.parts/steps/PromptSelectStep";
import { DataStrategyStep } from "./ContentTaskModal.parts/steps/DataStrategyStep";
import { ModelScheduleStep } from "./ContentTaskModal.parts/steps/ModelScheduleStep";
import { ConfirmStep } from "./ContentTaskModal.parts/steps/ConfirmStep";
import { RunningView } from "./ContentTaskModal.parts/views/RunningView";
import { ResultView } from "./ContentTaskModal.parts/views/ResultView";
import { addLocalDays, todayDateOnlyString } from "@/lib/dateOnly";

// ─── Main Component ─────────────────────────────────────────────────

export default function ContentTaskModal({
  open,
  template,
  clientId,
  userId,
  clientPlatforms,
  existingTaskId,
  onClose,
  onTaskCreated,
}: ContentTaskModalProps) {
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

  if (!template) return null;

  return (
    <Dialog open={open} onOpenChange={(o) => { if (!o) onClose(); }}>
      <DialogContent className="max-w-5xl w-[90vw] max-h-[90vh] flex flex-col overflow-hidden p-0" hideCloseButton>
        <DialogTitle className="sr-only">{template.name}</DialogTitle>
        <DialogDescription className="hidden">Configure content generation task</DialogDescription>

        {/* Header */}
        <div className="flex items-center gap-4 px-6 pt-5 pb-4 border-b border-border bg-muted/20 shrink-0">
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
              <span className="text-[10px] px-1.5 py-0.5 rounded-full bg-primary/10 text-primary font-medium">{t("taskModal.persona")}</span>
              <span className="text-xl ml-1">{template.icon}</span>
              <span className="text-sm font-medium text-foreground">{template.name}</span>
            </div>
            <p className="text-xs text-muted-foreground mt-0.5">
              {t("taskModal.intro")}
            </p>
          </div>
          <button onClick={onClose} className="text-muted-foreground hover:text-foreground transition-colors p-1 rounded">
            <X className="h-5 w-5" />
          </button>
        </div>

        {view === "config" ? (
          <>
            {/* Step Indicator */}
            <div className="px-6 py-3 border-b shrink-0">
              <StepIndicator currentStep={step} />
            </div>

            {/* Step Content */}
            <div className="flex-1 overflow-auto px-6 py-5 space-y-5">

              {/* ── Step 1: Content Goal ── */}
              {step === 1 && (
                <GoalStep
                  contentGoal={contentGoal}
                  setContentGoal={setContentGoal}
                  setSelectedDomains={setSelectedDomains}
                  setPromptSortBy={setPromptSortBy}
                  setContentType={setContentType}
                  goalMeta={goalMeta}
                  goalLabel={goalLabel}
                  contentTypeLabel={contentTypeLabel}
                  domainLabel={domainLabel}
                />
              )}

              {/* ── Step 2: Content Type ── */}
              {step === 2 && (
                <ContentTypeStep
                  contentType={contentType}
                  setContentType={setContentType}
                  topic={topic}
                  setTopic={setTopic}
                  goalMeta={goalMeta}
                />
              )}

              {/* ── Step 3: Target Config + Facts + Peers ── */}
              {step === 3 && (
                <TargetConfigStep
                  contentType={contentType}
                  platforms={platforms}
                  setPlatforms={setPlatforms}
                  count={count}
                  setCount={setCount}
                  language={language}
                  setLanguage={setLanguage}
                  productFacts={productFacts}
                  setProductFacts={setProductFacts}
                  peers={peers}
                  ownBrands={ownBrands}
                  competitors={competitors}
                  selectedPeers={selectedPeers}
                  togglePeer={togglePeer}
                  additionalInstructions={additionalInstructions}
                  setAdditionalInstructions={setAdditionalInstructions}
                />
              )}

              {/* ── Step 4: Prompt Selection ── */}
              {step === 4 && (
                <PromptSelectStep
                  goalMeta={goalMeta}
                  goalLabel={goalLabel}
                  promptSearch={promptSearch}
                  setPromptSearch={setPromptSearch}
                  promptSortBy={promptSortBy}
                  setPromptSortBy={setPromptSortBy}
                  loadingPrompts={loadingPrompts}
                  filteredPrompts={filteredPrompts}
                  selectedPromptIds={selectedPromptIds}
                  togglePrompt={togglePrompt}
                />
              )}

              {/* ── Step 5: Data & Strategy ── */}
              {step === 5 && (
                <DataStrategyStep
                  contentDepth={contentDepth}
                  setContentDepth={setContentDepth}
                  focusTags={focusTags}
                  setFocusTags={setFocusTags}
                  tagInput={tagInput}
                  setTagInput={setTagInput}
                  addTag={addTag}
                  contentGoal={contentGoal}
                  selectedDomains={selectedDomains}
                  toggleDomain={toggleDomain}
                  dateFrom={dateFrom}
                  setDateFrom={setDateFrom}
                  dateTo={dateTo}
                  setDateTo={setDateTo}
                  showMethodology={showMethodology}
                  setShowMethodology={setShowMethodology}
                  insertSnippet={insertSnippet}
                  strategyPrompt={strategyPrompt}
                  setStrategyPrompt={setStrategyPrompt}
                  expandPrompt={expandPrompt}
                  setExpandPrompt={setExpandPrompt}
                  template={template}
                  domainLabel={domainLabel}
                />
              )}

              {/* ── Step 6: Model + Cron ── */}
              {step === 6 && (
                <ModelScheduleStep
                  contentModelIds={contentModelIds}
                  modelId={modelId}
                  setModelId={setModelId}
                  cronExpression={cronExpression}
                  setCronExpression={setCronExpression}
                />
              )}

              {/* ── Step 7: Confirm ── */}
              {step === 7 && (
                <ConfirmStep
                  goalMeta={goalMeta}
                  goalLabel={goalLabel}
                  contentTypeLabel={contentTypeLabel}
                  domainLabel={domainLabel}
                  contentType={contentType}
                  topic={topic}
                  platforms={platforms}
                  count={count}
                  hasFacts={hasFacts}
                  selectedPeers={selectedPeers}
                  peers={peers}
                  selectedPromptIds={selectedPromptIds}
                  selectedDomains={selectedDomains}
                  dateFrom={dateFrom}
                  dateTo={dateTo}
                  depthKey={depthKey}
                  depthIcon={depthIcon}
                  depthLabel={depthLabel}
                  focusTags={focusTags}
                  language={language}
                  modelId={modelId}
                  strategyPrompt={strategyPrompt}
                />
              )}
            </div>

            {/* Footer */}
            <div className="shrink-0 flex items-center justify-between px-6 pb-5 pt-3 border-t">
              <div>
                {step > 1 ? (
                  <Button variant="ghost" size="sm" onClick={() => setStep((s) => s - 1)}>
                    <ChevronLeft className="h-4 w-4 mr-1" />
                    {t("taskModal.footer.prev")}
                  </Button>
                ) : (
                  <Button variant="outline" size="sm" onClick={onClose}>
                    <X className="h-4 w-4 mr-1" />
                    {t("taskModal.footer.cancel")}
                  </Button>
                )}
              </div>
              <div className="flex gap-2">
                {step < TOTAL_STEPS ? (
                  <Button size="sm" onClick={() => setStep((s) => s + 1)}>
                    {step === 4 && selectedPromptIds.length === 0 ? t("taskModal.footer.skip") : t("taskModal.footer.next")}
                    <ChevronRight className="h-4 w-4 ml-1" />
                  </Button>
                ) : (
                  <>
                    <Button
                      variant="outline"
                      size="sm"
                      disabled={isSubmitting}
                      onClick={() => handleSubmit(true)}
                    >
                      {isSubmitting ? <Loader2 className="h-3 w-3 animate-spin mr-1" /> : <Save className="h-3 w-3 mr-1" />}
                      {t("taskModal.footer.save")}
                    </Button>
                    <Button
                      size="sm"
                      disabled={isSubmitting}
                      onClick={() => handleSubmit(false)}
                    >
                      {isSubmitting ? <Loader2 className="h-3 w-3 animate-spin mr-1" /> : <Play className="h-3 w-3 mr-1" />}
                      {t("taskModal.footer.start")}
                    </Button>
                  </>
                )}
              </div>
            </div>
          </>
        ) : view === "running" && taskId ? (
          <RunningView taskId={taskId} onCompleted={handleTaskCompleted} onClose={onClose} />
        ) : view === "result" && taskOutput ? (
          <ResultView taskId={taskId} taskOutput={taskOutput} clientId={clientId} onClose={onClose} />
        ) : (
          <div className="flex-1 flex items-center justify-center p-6">
            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
          </div>
        )}
      </DialogContent>
    </Dialog>
  );
}
