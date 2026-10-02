import { CheckCircle2, Maximize2, Sparkles, Plus, X, Tag } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Dialog, DialogContent, DialogTitle, DialogDescription } from "@/components/ui/dialog";
import {
  ALL_DOMAINS,
  DOMAIN_META,
  DEPTH_KEYS,
  DEPTH_ICON,
  RAFT_SNIPPETS,
} from "../constants";
import type { ContentDepth, ContentTemplate, DomainKey } from "../types";

// ── Step 5: Data & Strategy ──

interface DataStrategyStepProps {
  contentDepth: ContentDepth;
  setContentDepth: (d: ContentDepth) => void;
  focusTags: string[];
  setFocusTags: (tags: string[]) => void;
  tagInput: string;
  setTagInput: (s: string) => void;
  addTag: () => void;
  contentGoal: string | null;
  selectedDomains: string[];
  toggleDomain: (d: string) => void;
  dateFrom: string;
  setDateFrom: (s: string) => void;
  dateTo: string;
  setDateTo: (s: string) => void;
  showMethodology: boolean;
  setShowMethodology: React.Dispatch<React.SetStateAction<boolean>>;
  insertSnippet: (s: string) => void;
  strategyPrompt: string;
  setStrategyPrompt: (s: string) => void;
  expandPrompt: boolean;
  setExpandPrompt: (b: boolean) => void;
  template: ContentTemplate | null;
  domainLabel: (id: string) => string;
}

export function DataStrategyStep({
  contentDepth,
  setContentDepth,
  focusTags,
  setFocusTags,
  tagInput,
  setTagInput,
  addTag,
  contentGoal,
  selectedDomains,
  toggleDomain,
  dateFrom,
  setDateFrom,
  dateTo,
  setDateTo,
  showMethodology,
  setShowMethodology,
  insertSnippet,
  strategyPrompt,
  setStrategyPrompt,
  expandPrompt,
  setExpandPrompt,
  template,
  domainLabel,
}: DataStrategyStepProps) {
  const { t } = useTranslation("content");

  return (
    <div className="space-y-5">
      {/* Content Depth + Focus Tags */}
      <div className="grid grid-cols-2 gap-5">
        <div>
          <h3 className="text-sm font-semibold mb-2">{t("taskModal.dataStrategy.depthTitle")}</h3>
          <div className="space-y-2">
            {DEPTH_KEYS.map(id => (
              <button
                key={id}
                onClick={() => setContentDepth(id)}
                className={`w-full flex items-center gap-3 px-3 py-2.5 rounded-lg border-2 text-left transition-all ${
                  contentDepth === id
                    ? "border-primary bg-primary/5"
                    : "border-border hover:border-primary/30"
                }`}
              >
                <span className="text-lg">{DEPTH_ICON[id]}</span>
                <div>
                  <span className="text-xs font-semibold">{t(`taskModal.depth.${id}.label`)}</span>
                  <p className="text-[10px] text-muted-foreground">{t(`taskModal.depth.${id}.desc`)}</p>
                </div>
                {contentDepth === id && <CheckCircle2 className="h-3.5 w-3.5 text-primary ml-auto shrink-0" />}
              </button>
            ))}
          </div>
        </div>
        <div>
          <h3 className="text-sm font-semibold mb-2">{t("taskModal.dataStrategy.focusTitle")}</h3>
          <p className="text-[11px] text-muted-foreground mb-2.5">{t("taskModal.dataStrategy.focusHint")}</p>
          <div className="flex gap-2 mb-2.5">
            <input
              type="text"
              value={tagInput}
              onChange={e => setTagInput(e.target.value)}
              onKeyDown={e => { if (e.key === "Enter") { e.preventDefault(); addTag(); } }}
              placeholder={t("taskModal.dataStrategy.focusPlaceholder")}
              className="flex-1 rounded-md border border-input bg-background px-3 py-1.5 text-sm focus:outline-none focus:ring-2 focus:ring-ring/30"
            />
            <button
              onClick={addTag}
              disabled={!tagInput.trim()}
              className="px-3 py-1.5 rounded-md text-xs font-medium bg-primary text-primary-foreground hover:bg-primary/90 disabled:opacity-50 transition-colors"
            >
              <Plus className="h-3.5 w-3.5" />
            </button>
          </div>
          <div className="flex flex-wrap gap-1.5 min-h-[36px]">
            {focusTags.map(tag => (
              <span key={tag} className="inline-flex items-center gap-1 px-2.5 py-1 rounded-full bg-primary/10 text-primary text-xs font-medium">
                <Tag className="h-3 w-3" />
                {tag}
                <button onClick={() => setFocusTags(focusTags.filter(t => t !== tag))} className="hover:text-destructive ml-0.5">
                  <X className="h-3 w-3" />
                </button>
              </span>
            ))}
            {focusTags.length === 0 && (
              <span className="text-[11px] text-muted-foreground/50 self-center">{t("taskModal.dataStrategy.focusEmpty")}</span>
            )}
          </div>
        </div>
      </div>

      {/* Data Domains + Date Range */}
      <div className="grid grid-cols-2 gap-5">
        <div>
          <div className="flex items-center justify-between mb-2">
            <h3 className="text-sm font-semibold">{t("taskModal.dataStrategy.domainsTitle")}</h3>
            {contentGoal && (
              <span className="text-[10px] text-primary bg-primary/10 px-2 py-0.5 rounded-full font-medium">
                {t("taskModal.dataStrategy.recommendedBadge")}
              </span>
            )}
          </div>
          <div className="grid grid-cols-3 gap-2">
            {ALL_DOMAINS.map((domain) => {
              const meta = DOMAIN_META[domain as DomainKey];
              if (!meta) return null;
              const selected = selectedDomains.includes(domain);
              return (
                <button
                  key={domain}
                  onClick={() => toggleDomain(domain)}
                  className={`flex flex-col items-center gap-1.5 p-3 rounded-xl border-2 transition-all duration-200 ${
                    selected
                      ? "border-primary bg-primary/5 shadow-sm"
                      : "border-border hover:border-primary/40 hover:bg-muted/30"
                  }`}
                >
                  <span className="text-xl">{meta.icon}</span>
                  <span className="text-xs font-medium">{domainLabel(domain)}</span>
                  {selected && <CheckCircle2 className="h-3.5 w-3.5 text-primary" />}
                </button>
              );
            })}
          </div>
        </div>
        <div>
          <h3 className="text-sm font-semibold mb-2">{t("taskModal.dataStrategy.rangeTitle")}</h3>
          <div className="space-y-3">
            <div>
              <label className="text-xs text-muted-foreground mb-1 block">{t("taskModal.dataStrategy.rangeFrom")}</label>
              <input
                type="date"
                value={dateFrom}
                onChange={(e) => setDateFrom(e.target.value)}
                className="w-full rounded-lg border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
              />
            </div>
            <div>
              <label className="text-xs text-muted-foreground mb-1 block">{t("taskModal.dataStrategy.rangeTo")}</label>
              <input
                type="date"
                value={dateTo}
                onChange={(e) => setDateTo(e.target.value)}
                className="w-full rounded-lg border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
              />
            </div>
          </div>
        </div>
      </div>

      {/* Strategy Prompt with Methodology Panel */}
      <div>
        <div className="flex items-center justify-between mb-2">
          <h3 className="text-sm font-semibold">{t("taskModal.dataStrategy.strategyPromptTitle")}</h3>
          <button
            onClick={() => setShowMethodology(s => !s)}
            className={`text-[11px] font-medium px-2.5 py-1 rounded-md transition-colors ${
              showMethodology ? "bg-primary/10 text-primary" : "text-muted-foreground hover:text-foreground hover:bg-muted/40"
            }`}
          >
            {showMethodology ? t("taskModal.dataStrategy.methodToggleClose") : t("taskModal.dataStrategy.methodToggleOpen")}
          </button>
        </div>
        <p className="text-xs text-muted-foreground mb-3">
          {t("taskModal.dataStrategy.strategyHint")}
        </p>
      </div>

      {showMethodology && (
        <div className="rounded-xl border border-primary/15 bg-primary/[0.02] p-4 space-y-3">
          <div className="flex items-center gap-2 text-xs font-semibold text-muted-foreground uppercase tracking-wider">
            <Sparkles className="h-3.5 w-3.5 text-primary" />
            {t("taskModal.dataStrategy.methodHeader")}
          </div>
          {RAFT_SNIPPETS.map(cat => (
            <div key={cat.categoryKey}>
              <div className="text-[11px] font-semibold text-muted-foreground mb-1.5">{t(`taskModal.raftCategories.${cat.categoryKey}`)}</div>
              <div className="flex flex-wrap gap-1.5">
                {cat.items.map(item => (
                  <button
                    key={item.label}
                    onClick={() => insertSnippet(item.snippet)}
                    title={item.snippet}
                    className="px-2.5 py-1.5 rounded-md text-[11px] bg-background border hover:border-primary/40 hover:bg-primary/5 transition-all text-left"
                  >
                    <span className="font-medium text-foreground">{item.label}</span>
                  </button>
                ))}
              </div>
            </div>
          ))}
        </div>
      )}

      <div className="relative">
        <textarea
          value={strategyPrompt}
          onChange={(e) => setStrategyPrompt(e.target.value)}
          rows={8}
          placeholder={t("taskModal.dataStrategy.strategyPromptPlaceholder")}
          className="w-full rounded-lg border bg-background px-3 py-2.5 pr-10 text-sm font-mono leading-relaxed focus:outline-none focus:ring-2 focus:ring-primary/30 resize-y min-h-[160px]"
        />
        <button
          type="button"
          onClick={() => setExpandPrompt(true)}
          title={t("taskModal.dataStrategy.expandEdit")}
          className="absolute top-2 right-2 z-20 p-1 rounded text-muted-foreground hover:text-foreground hover:bg-muted/40 transition-colors"
        >
          <Maximize2 className="h-3.5 w-3.5" />
        </button>
      </div>
      {template?.default_prompt && strategyPrompt !== template.default_prompt && (
        <button
          onClick={() => setStrategyPrompt(template.default_prompt || "")}
          className="text-xs text-primary hover:underline"
        >
          {t("taskModal.dataStrategy.restoreDefault")}
        </button>
      )}

      {/* Expand prompt dialog */}
      <Dialog open={expandPrompt} onOpenChange={setExpandPrompt}>
        <DialogContent className="max-w-4xl w-[90vw] max-h-[90vh] flex flex-col overflow-hidden p-0 gap-0 sm:rounded-2xl">
          <DialogTitle className="sr-only">{t("taskModal.dataStrategy.dialogTitle")}</DialogTitle>
          <DialogDescription className="hidden">Fullscreen strategy prompt editor</DialogDescription>
          <div className="flex items-center justify-between px-5 py-3.5 border-b shrink-0">
            <span className="text-sm font-semibold">{t("taskModal.dataStrategy.dialogHeader")}</span>
          </div>
          <div className="flex-1 flex flex-col overflow-hidden p-5 gap-4">
            <textarea
              value={strategyPrompt}
              onChange={(e) => setStrategyPrompt(e.target.value)}
              className="flex-1 w-full rounded-md border border-input px-3 py-2 text-sm font-mono min-h-[50vh] resize-none focus:outline-none focus:ring-2 focus:ring-ring/30"
              placeholder={t("taskModal.dataStrategy.strategyPromptPlaceholder")}
            />
          </div>
          <div className="shrink-0 flex justify-end px-5 pb-5">
            <button
              onClick={() => setExpandPrompt(false)}
              className="px-4 py-2 rounded-md text-sm font-medium bg-primary text-primary-foreground hover:bg-primary/90 transition-colors"
            >
              {t("taskModal.dataStrategy.dialogConfirm")}
            </button>
          </div>
        </DialogContent>
      </Dialog>
    </div>
  );
}
