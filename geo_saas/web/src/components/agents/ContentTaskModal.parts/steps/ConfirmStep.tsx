import { ChevronRight, Sparkles } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/badge";
import { DOMAIN_META } from "../constants";
import type { ContentDepth, ContentGoalDef, DomainKey, PeerItem } from "../types";

// ── Step 7: Confirm ──

interface ConfirmStepProps {
  goalMeta: ContentGoalDef | undefined;
  goalLabel: string;
  contentTypeLabel: (id: string) => string;
  domainLabel: (id: string) => string;
  contentType: string;
  topic: string;
  platforms: string[];
  count: number;
  hasFacts: boolean;
  selectedPeers: string[];
  peers: PeerItem[];
  selectedPromptIds: string[];
  selectedDomains: string[];
  dateFrom: string;
  dateTo: string;
  depthKey: ContentDepth | undefined;
  depthIcon: string;
  depthLabel: string;
  focusTags: string[];
  language: string;
  modelId: string;
  strategyPrompt: string;
}

export function ConfirmStep({
  goalMeta,
  goalLabel,
  contentTypeLabel,
  domainLabel,
  contentType,
  topic,
  platforms,
  count,
  hasFacts,
  selectedPeers,
  peers,
  selectedPromptIds,
  selectedDomains,
  dateFrom,
  dateTo,
  depthKey,
  depthIcon,
  depthLabel,
  focusTags,
  language,
  modelId,
  strategyPrompt,
}: ConfirmStepProps) {
  const { t } = useTranslation("content");

  return (
    <div className="space-y-4">
      <h4 className="text-sm font-semibold">{t("taskModal.confirm.title")}</h4>

      {/* Pipeline Preview */}
      <div className="rounded-xl border bg-primary/[0.02] p-4 space-y-3">
        <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider flex items-center gap-2">
          <Sparkles className="h-3.5 w-3.5 text-primary" />
          {t("taskModal.confirm.flowPreview")}
        </div>
        <div className="flex items-center gap-1 flex-wrap">
          {[
            { step: 1, label: t("taskModal.confirm.flowSteps.strategyAnalysis"), icon: "🎯" },
            { step: 2, label: t("taskModal.confirm.flowSteps.promptDiscovery"), icon: "🔍" },
            { step: 3, label: t("taskModal.confirm.flowSteps.contentPlan"), icon: "📋" },
            { step: 4, label: t("taskModal.confirm.flowSteps.contentGen"), icon: "✍️" },
            { step: 5, label: t("taskModal.confirm.flowSteps.qualityReview"), icon: "✅" },
            { step: 6, label: t("taskModal.confirm.flowSteps.reviseRound1"), icon: "🛠️" },
            { step: 7, label: t("taskModal.confirm.flowSteps.qualityRecheck"), icon: "🔁" },
            { step: 8, label: t("taskModal.confirm.flowSteps.reviseRound2"), icon: "🧹" },
            { step: 9, label: t("taskModal.confirm.flowSteps.qualityRecheck2"), icon: "🔎" },
          ].map((ws, i, arr) => (
            <div key={ws.step} className="flex items-center gap-1.5">
              <div className="flex items-center gap-2 px-3 py-2 rounded-lg bg-muted/30 border border-border/60">
                <span className="text-sm">{ws.icon}</span>
                <div>
                  <span className="text-xs font-medium text-foreground">{ws.label}</span>
                  <span className="text-[10px] text-muted-foreground ml-1.5">Step {ws.step}</span>
                </div>
              </div>
              {i < arr.length - 1 && (
                <ChevronRight className="h-3.5 w-3.5 text-muted-foreground/40 shrink-0" />
              )}
            </div>
          ))}
        </div>
        <p className="text-[11px] text-muted-foreground">
          {t("taskModal.confirm.flowHint")}
        </p>
      </div>

      {/* Task Summary */}
      <div className="rounded-xl border p-4 space-y-2.5 text-sm">
        <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2">{t("taskModal.confirm.summaryTitle")}</div>
        {goalMeta && (
          <div className="flex justify-between">
            <span className="text-muted-foreground">{t("taskModal.confirm.summary.goal")}</span>
            <span className="font-medium text-xs">{goalLabel}</span>
          </div>
        )}
        <div className="flex justify-between">
          <span className="text-muted-foreground">{t("taskModal.confirm.summary.type")}</span>
          <span className="font-medium">{contentTypeLabel(contentType)}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">{t("taskModal.confirm.summary.topic")}</span>
          <span className="font-medium max-w-[60%] text-right text-xs">{topic || t("taskModal.confirm.summary.topicAuto")}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">{t("taskModal.confirm.summary.platform")}</span>
          <div className="flex gap-1">
            {platforms.map((p) => (
              <Badge key={p} variant="outline" className="text-[10px]">{p}</Badge>
            ))}
          </div>
        </div>
        {contentType === "faq" && (
          <div className="flex justify-between">
            <span className="text-muted-foreground">{t("taskModal.confirm.summary.count")}</span>
            <span className="font-medium">{count}</span>
          </div>
        )}
        <div className="flex justify-between">
          <span className="text-muted-foreground">{t("taskModal.confirm.summary.facts")}</span>
          <span className="font-medium text-xs">{hasFacts ? t("taskModal.confirm.summary.factsFilled") : t("taskModal.confirm.summary.factsEmpty")}</span>
        </div>
        {selectedPeers.length > 0 && (
          <div className="flex justify-between">
            <span className="text-muted-foreground">{t("taskModal.confirm.summary.brandPeer")}</span>
            <span className="font-medium text-xs">
              {selectedPeers.map(pid => peers.find(p => p.id === pid)?.primary_name || pid).join(", ")}
            </span>
          </div>
        )}
        <div className="flex justify-between">
          <span className="text-muted-foreground">{t("taskModal.confirm.summary.targetPrompt")}</span>
          <span className="font-medium">{selectedPromptIds.length > 0 ? t("taskModal.confirm.summary.targetPromptCount", { count: selectedPromptIds.length }) : t("taskModal.confirm.summary.targetPromptAll")}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">{t("taskModal.confirm.summary.domains")}</span>
          <div className="flex gap-1">
            {selectedDomains.map((d) => {
              const meta = DOMAIN_META[d as DomainKey];
              return meta ? (
                <span key={d} className={`text-[10px] px-1.5 py-0.5 rounded-md border font-medium ${meta.color}`}>
                  {domainLabel(d)}
                </span>
              ) : null;
            })}
          </div>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">{t("taskModal.confirm.summary.range")}</span>
          <span className="font-medium text-xs">{dateFrom} ~ {dateTo}</span>
        </div>
        {depthKey && (
          <div className="flex justify-between">
            <span className="text-muted-foreground">{t("taskModal.confirm.summary.depth")}</span>
            <span className="font-medium text-xs">{depthIcon} {depthLabel}</span>
          </div>
        )}
        {focusTags.length > 0 && (
          <div className="flex justify-between items-start">
            <span className="text-muted-foreground">{t("taskModal.confirm.summary.focus")}</span>
            <div className="flex flex-wrap gap-1 justify-end max-w-[60%]">
              {focusTags.map(tag => (
                <span key={tag} className="text-[10px] px-1.5 py-0.5 rounded-full bg-primary/10 text-primary font-medium">
                  {tag}
                </span>
              ))}
            </div>
          </div>
        )}
        <div className="flex justify-between">
          <span className="text-muted-foreground">{t("taskModal.confirm.summary.language")}</span>
          <span className="font-medium">{language === "zh-CN" ? "中文" : "English"}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">{t("taskModal.confirm.summary.model")}</span>
          <span className="font-medium text-xs">{modelId ? modelId.replace("gemini-", "Gemini ").replace("-preview", "") : t("taskModal.confirm.summary.modelDefault")}</span>
        </div>
        <div className="flex justify-between">
          <span className="text-muted-foreground">{t("taskModal.confirm.summary.strategyPrompt")}</span>
          <span className="font-medium text-xs">{strategyPrompt ? t("taskModal.confirm.summary.strategyPromptLen", { count: strategyPrompt.length }) : t("taskModal.confirm.summary.strategyPromptEmpty")}</span>
        </div>
      </div>
    </div>
  );
}
