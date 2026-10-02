import { CheckCircle2, Database } from "lucide-react";
import { useTranslation } from "react-i18next";
import { PLATFORM_OPTIONS } from "../constants";
import type { PeerItem } from "../types";

// ── Step 3: Target Config + Facts + Peers ──

interface TargetConfigStepProps {
  contentType: string;
  platforms: string[];
  setPlatforms: React.Dispatch<React.SetStateAction<string[]>>;
  count: number;
  setCount: (n: number) => void;
  language: string;
  setLanguage: (l: string) => void;
  productFacts: { specs: string; features: string; differentiators: string };
  setProductFacts: (f: { specs: string; features: string; differentiators: string }) => void;
  peers: PeerItem[];
  ownBrands: PeerItem[];
  competitors: PeerItem[];
  selectedPeers: string[];
  togglePeer: (peerId: string) => void;
  additionalInstructions: string;
  setAdditionalInstructions: (s: string) => void;
}

export function TargetConfigStep({
  contentType,
  platforms,
  setPlatforms,
  count,
  setCount,
  language,
  setLanguage,
  productFacts,
  setProductFacts,
  peers,
  ownBrands,
  competitors,
  selectedPeers,
  togglePeer,
  additionalInstructions,
  setAdditionalInstructions,
}: TargetConfigStepProps) {
  const { t } = useTranslation("content");

  return (
    <div className="space-y-6">
      {/* Platform + Language + Count row */}
      <div className="grid grid-cols-2 gap-5">
        <div>
          <h3 className="text-sm font-semibold mb-2">{t("taskModal.targetConfig.aiPlatforms")}</h3>
          <div className="flex flex-col gap-2">
            {PLATFORM_OPTIONS.map((p) => {
              const selected = platforms.includes(p.id);
              return (
                <button
                  key={p.id}
                  onClick={() =>
                    setPlatforms((prev) =>
                      prev.includes(p.id) ? prev.filter((x) => x !== p.id) : [...prev, p.id]
                    )
                  }
                  className={`flex items-center gap-2.5 px-3 py-2 rounded-lg border-2 transition-all duration-200 text-left ${
                    selected
                      ? "border-primary bg-primary/5"
                      : "border-border hover:border-primary/40 hover:bg-muted/30"
                  }`}
                >
                  <span className="text-base">{p.icon}</span>
                  <span className="text-xs font-medium flex-1">{p.label}</span>
                  {selected && <CheckCircle2 className="h-3.5 w-3.5 text-primary" />}
                </button>
              );
            })}
          </div>
        </div>
        <div className="space-y-4">
          {contentType === "faq" && (
            <div>
              <label className="text-sm font-medium mb-2 block">{t("taskModal.targetConfig.faqCount")}</label>
              <input
                type="number"
                min={1}
                max={10}
                value={count}
                onChange={(e) => setCount(Math.min(10, Math.max(1, parseInt(e.target.value) || 5)))}
                className="w-24 rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
              />
            </div>
          )}
          <div>
            <label className="text-sm font-medium mb-2 block">{t("taskModal.targetConfig.outputLanguage")}</label>
            <div className="flex gap-2">
              {[
                { id: "zh-CN", label: "中文" },
                { id: "en", label: "English" },
              ].map((l) => (
                <button
                  key={l.id}
                  onClick={() => setLanguage(l.id)}
                  className={`px-3 py-1.5 rounded-full border text-xs font-medium transition-all ${
                    language === l.id
                      ? "bg-primary text-primary-foreground border-primary"
                      : "hover:bg-muted/50"
                  }`}
                >
                  {l.label}
                </button>
              ))}
            </div>
          </div>
        </div>
      </div>

      {/* Product Facts Input */}
      <div className="rounded-xl border border-amber-500/20 bg-amber-500/[0.03] p-4 space-y-3">
        <div className="flex items-center gap-2">
          <Database className="h-4 w-4 text-amber-500" />
          <span className="text-sm font-semibold">{t("taskModal.targetConfig.factsTitle")}</span>
          <span className="text-[10px] text-amber-500 bg-amber-500/10 px-2 py-0.5 rounded-full font-medium">{t("taskModal.targetConfig.factsBadge")}</span>
        </div>
        <p className="text-[11px] text-muted-foreground leading-relaxed">
          {t("taskModal.targetConfig.factsHint")}
        </p>
        <div className="space-y-3">
          <div>
            <label className="text-[11px] font-medium text-muted-foreground mb-1 block">{t("taskModal.targetConfig.facts.specs")}</label>
            <textarea
              value={productFacts.specs}
              onChange={(e) => setProductFacts({ ...productFacts, specs: e.target.value })}
              placeholder={t("taskModal.targetConfig.facts.specsPlaceholder")}
              rows={2}
              className="w-full rounded-lg border px-3 py-2 text-xs focus:outline-none focus:ring-2 focus:ring-amber-500/30 resize-y"
            />
          </div>
          <div>
            <label className="text-[11px] font-medium text-muted-foreground mb-1 block">{t("taskModal.targetConfig.facts.features")}</label>
            <textarea
              value={productFacts.features}
              onChange={(e) => setProductFacts({ ...productFacts, features: e.target.value })}
              placeholder={t("taskModal.targetConfig.facts.featuresPlaceholder")}
              rows={2}
              className="w-full rounded-lg border px-3 py-2 text-xs focus:outline-none focus:ring-2 focus:ring-amber-500/30 resize-y"
            />
          </div>
          <div>
            <label className="text-[11px] font-medium text-muted-foreground mb-1 block">{t("taskModal.targetConfig.facts.differentiators")}</label>
            <textarea
              value={productFacts.differentiators}
              onChange={(e) => setProductFacts({ ...productFacts, differentiators: e.target.value })}
              placeholder={t("taskModal.targetConfig.facts.differentiatorsPlaceholder")}
              rows={2}
              className="w-full rounded-lg border px-3 py-2 text-xs focus:outline-none focus:ring-2 focus:ring-amber-500/30 resize-y"
            />
          </div>
        </div>
      </div>

      {/* Brand / Competitor Selection */}
      {peers.length > 0 && (
        <div>
          <h3 className="text-sm font-semibold mb-2">{t("taskModal.targetConfig.scopeTitle")}</h3>
          <p className="text-[11px] text-muted-foreground mb-3">{t("taskModal.targetConfig.scopeHint")}</p>
          <div className="flex flex-wrap gap-2">
            {ownBrands.map(peer => {
              const selected = selectedPeers.includes(peer.id);
              return (
                <button
                  key={peer.id}
                  onClick={() => togglePeer(peer.id)}
                  className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full border-2 text-xs font-medium transition-all ${
                    selected
                      ? "border-primary bg-primary/10 text-primary"
                      : "border-border hover:border-primary/40 text-foreground"
                  }`}
                >
                  <span className="w-2 h-2 rounded-full bg-primary shrink-0" />
                  {peer.primary_name}
                  {selected && <CheckCircle2 className="h-3 w-3" />}
                </button>
              );
            })}
            {competitors.length > 0 && ownBrands.length > 0 && (
              <div className="w-px h-6 bg-border self-center mx-1" />
            )}
            {competitors.map(peer => {
              const selected = selectedPeers.includes(peer.id);
              return (
                <button
                  key={peer.id}
                  onClick={() => togglePeer(peer.id)}
                  className={`inline-flex items-center gap-1.5 px-3 py-1.5 rounded-full border-2 text-xs font-medium transition-all ${
                    selected
                      ? "border-amber-500 bg-amber-500/10 text-amber-500"
                      : "border-border hover:border-amber-500/40 text-muted-foreground"
                  }`}
                >
                  <span className="w-2 h-2 rounded-full bg-amber-500 shrink-0" />
                  {peer.primary_name}
                  {selected && <CheckCircle2 className="h-3 w-3" />}
                </button>
              );
            })}
          </div>
        </div>
      )}

      {/* Additional Instructions */}
      <div>
        <label className="text-sm font-medium mb-2 block">{t("taskModal.targetConfig.extraNote")}</label>
        <textarea
          value={additionalInstructions}
          onChange={(e) => setAdditionalInstructions(e.target.value)}
          placeholder={t("taskModal.targetConfig.extraNotePlaceholder")}
          rows={2}
          className="w-full rounded-lg border px-3 py-2 text-sm focus:outline-none focus:ring-2 focus:ring-primary/30"
        />
      </div>
    </div>
  );
}
