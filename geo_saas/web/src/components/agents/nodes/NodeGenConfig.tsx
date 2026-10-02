import { useState, useEffect } from "react";
import { Settings, ChevronDown, ChevronUp } from "lucide-react";
import { useTranslation } from "react-i18next";

const AI_PLATFORMS = [
  { id: "chatgpt", label: "ChatGPT", icon: "🤖" },
  { id: "gemini", label: "Gemini", icon: "✨" },
  { id: "aimode", label: "AI Mode", icon: "🔍" },
  { id: "perplexity", label: "Perplexity", icon: "🔎" },
  { id: "aioverview", label: "AI Overview", icon: "🌐" },
];

// Publish platform labels resolve from translation keys at render time.
type PublishPlatformKey = "official_site" | "reddit" | "wiki" | "review_site" | "youtube" | "media";
const PUBLISH_PLATFORM_KEYS: PublishPlatformKey[] = ["official_site", "reddit", "wiki", "review_site", "youtube", "media"];
const PUBLISH_PLATFORM_FIXED_LABELS: Partial<Record<PublishPlatformKey, string>> = {
  reddit: "Reddit",
  wiki: "Wikipedia",
  youtube: "YouTube",
};

const LANGUAGES = [
  { id: "en-US", label: "English" },
  { id: "zh-CN", label: "中文" },
  { id: "ja-JP", label: "日本語" },
  { id: "de-DE", label: "Deutsch" },
];

interface GenConfigData {
  aiPlatforms: string[];
  publishPlatform: string;
  language: string;
  count: number;
  productFacts: { specs: string; features: string; differentiators: string };
}

interface PlatformRec {
  platform_type: string;
  engines: string[];
  citation_share: number;
  priority: string;
  engine_breakdown: Record<string, number>;
}

interface NodeGenConfigProps {
  value: GenConfigData;
  onChange: (data: GenConfigData) => void;
  analyzerContext?: any;
  clientPlatforms: string[];
  platformRecommendations?: PlatformRec[];
}

const ENGINE_COLORS: Record<string, string> = {
  chatgpt: "#10a37f",
  gemini: "#4285f4",
  aimode: "#f97316",
  ai_mode: "#f97316",
  perplexity: "#8b5cf6",
  aioverview: "#0ea5e9",
  ai_overview: "#0ea5e9",
  google_ai_overview: "#0ea5e9",
  copilot: "#0078d4",
};

export default function NodeGenConfig({ value, onChange, analyzerContext, clientPlatforms, platformRecommendations }: NodeGenConfigProps) {
  const { t } = useTranslation("content");
  const [brandExpanded, setBrandExpanded] = useState(false);

  const [autoSelected, setAutoSelected] = useState(false);
  const [autoReason, setAutoReason] = useState("");

  const publishPlatformLabel = (id: PublishPlatformKey): string =>
    PUBLISH_PLATFORM_FIXED_LABELS[id] ?? t(`publishPlatforms.${id}`, { defaultValue: id });

  // Pre-fill from analyzer
  useEffect(() => {
    if (analyzerContext?.platform_recommendations && !autoSelected) {
      const recs = analyzerContext.platform_recommendations || [];
      if (recs.length === 0) return;

      const topRec = recs[0];
      const topPlatformType = topRec?.platform_type || "";
      const topEngines: string[] = topRec?.engines || [];
      const citationShare = topRec?.citation_share || 0;

      // Auto-select publish platform
      const platformMap: Record<string, string> = {
        "官网FAQ": "official_site", "官网 FAQ/Blog": "official_site",
        "Earned Media (赢得媒体)": "media", "Earned Media": "media",
        "Reddit": "reddit", "Wikipedia": "wiki", "测评站": "review_site",
        "Owned Media (自有媒体)": "official_site", "Owned Media": "official_site",
        "Social Media (社交媒体)": "reddit", "Social Media": "reddit",
      };
      const mappedPublish = platformMap[topPlatformType] || "official_site";

      // Auto-select AI platforms from top engine recommendations
      const engineMap: Record<string, string> = {
        "chatgpt": "chatgpt", "ChatGPT": "chatgpt",
        "gemini": "gemini", "Gemini": "gemini",
        "aimode": "aimode", "AI Mode": "aimode", "ai_mode": "aimode",
        "perplexity": "perplexity", "Perplexity": "perplexity",
        "aioverview": "aioverview", "AI Overview": "aioverview",
        "ai_overview": "aioverview", "google_ai_overview": "aioverview",
      };
      const autoAiPlatforms: string[] = [];
      for (const engine of topEngines) {
        const mapped = engineMap[engine];
        if (mapped && clientPlatforms.includes(mapped) && !autoAiPlatforms.includes(mapped)) {
          autoAiPlatforms.push(mapped);
        }
      }
      // Fallback: if no engines matched, use first client platform
      if (autoAiPlatforms.length === 0 && clientPlatforms.length > 0) {
        autoAiPlatforms.push(clientPlatforms[0]);
      }

      // Build reason with engine percentages
      const bd = topRec?.engine_breakdown || {};
      const bdTotal = (Object.values(bd) as number[]).reduce((a: number, b: number) => a + b, 0) || 1;
      const engineParts = topEngines.map((e: string) => {
        const pct = Math.round(((bd[e] || 0) / bdTotal) * 100);
        return `${e} ${pct}%`;
      });
      const reason = t("nodes.genConfig.autoReason", {
        platform: topPlatformType,
        share: Math.round(citationShare * 100),
        engines: engineParts.join("、") || "—",
      });
      setAutoReason(reason);
      setAutoSelected(true);

      onChange({
        ...value,
        publishPlatform: value.publishPlatform || mappedPublish,
        aiPlatforms: value.aiPlatforms.length > 0 ? value.aiPlatforms : autoAiPlatforms,
      });
    }
  }, [analyzerContext]);

  const toggleAiPlatform = (id: string) => {
    const next = value.aiPlatforms.includes(id)
      ? value.aiPlatforms.filter((p) => p !== id)
      : [...value.aiPlatforms, id];
    onChange({ ...value, aiPlatforms: next });
  };

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 mb-2">
        <Settings className="w-5 h-5 text-cyan-400" />
        <h3 className="text-lg font-semibold text-foreground">{t("nodes.genConfig.title")}</h3>
      </div>

      {/* Auto-selection hint + engine breakdown */}
      {autoReason && (
        <div className="rounded-lg border border-amber-500/20 bg-amber-500/5 px-3 py-2.5">
          <p className="text-xs text-amber-600 dark:text-amber-400 font-medium mb-0.5">{t("nodes.genConfig.autofillBadge")}</p>
          <p className="text-[11px] text-amber-600/70 dark:text-amber-400/70">{autoReason}</p>
          {/* Per-platform engine breakdown bars */}
          {platformRecommendations && platformRecommendations.length > 0 && (
            <div className="mt-2 pt-2 border-t border-amber-500/10 space-y-1.5">
              <p className="text-[10px] text-amber-600/50 dark:text-amber-400/50 font-medium">{t("nodes.genConfig.autofillHint")}</p>
              {platformRecommendations.slice(0, 5).map((rec, i) => {
                const total = Object.values(rec.engine_breakdown || {}).reduce((a, b) => a + b, 0) || 1;
                const share = Math.round(rec.citation_share * 100);
                return (
                  <div key={i} className="flex items-center gap-2">
                    <span className="text-[10px] text-amber-700/70 dark:text-amber-300/70 w-28 shrink-0 truncate">{rec.platform_type} ({share}%)</span>
                    <div className="flex-1 h-3 rounded-full overflow-hidden bg-amber-500/10 flex">
                      {Object.entries(rec.engine_breakdown || {}).map(([eng, count]) => {
                        const pct = Math.round((count / total) * 100);
                        return (
                          <div
                            key={eng}
                            style={{ width: `${pct}%`, backgroundColor: ENGINE_COLORS[eng.toLowerCase()] || "#8b5cf6" }}
                            className="h-full"
                            title={`${eng} ${pct}%`}
                          />
                        );
                      })}
                    </div>
                    <div className="flex gap-1.5 shrink-0">
                      {Object.entries(rec.engine_breakdown || {}).map(([eng, count]) => {
                        const pct = Math.round((count / total) * 100);
                        return (
                          <span key={eng} className="text-[9px] text-amber-600/60 dark:text-amber-400/50 flex items-center gap-0.5">
                            <span className="w-1.5 h-1.5 rounded-full inline-block" style={{ backgroundColor: ENGINE_COLORS[eng.toLowerCase()] || "#8b5cf6" }} />
                            {eng} {pct}%
                          </span>
                        );
                      })}
                    </div>
                  </div>
                );
              })}
            </div>
          )}
        </div>
      )}

      {/* AI Platforms */}
      <div>
        <p className="text-xs text-muted-foreground mb-2">{t("nodes.genConfig.aiPlatformsLabel")}</p>
        <div className="flex gap-2">
          {AI_PLATFORMS.filter((p) => clientPlatforms.includes(p.id)).map((p) => (
            <button
              key={p.id}
              onClick={() => toggleAiPlatform(p.id)}
              className={`px-3 py-1.5 rounded-lg border text-sm transition-colors ${
                value.aiPlatforms.includes(p.id)
                  ? "border-cyan-500/50 bg-cyan-500/10 text-cyan-300"
                  : "border-border text-muted-foreground hover:border-border/80"
              }`}
            >
              {p.icon} {p.label}
            </button>
          ))}
        </div>
      </div>

      {/* Publish Platform */}
      <div>
        <p className="text-xs text-muted-foreground mb-2">{t("nodes.genConfig.publishPlatformsLabel")}</p>
        <div className="flex flex-wrap gap-2">
          {PUBLISH_PLATFORM_KEYS.map((id) => (
            <button
              key={id}
              onClick={() => onChange({ ...value, publishPlatform: id })}
              className={`px-3 py-1.5 rounded-lg border text-sm transition-colors ${
                value.publishPlatform === id
                  ? "border-cyan-500/50 bg-cyan-500/10 text-cyan-300"
                  : "border-border text-muted-foreground hover:border-border/80"
              }`}
            >
              {publishPlatformLabel(id)}
            </button>
          ))}
        </div>
      </div>

      {/* Language + Count */}
      <div className="grid grid-cols-2 gap-4">
        <div>
          <p className="text-xs text-muted-foreground mb-2">{t("nodes.genConfig.languageLabel")}</p>
          <select
            className="w-full bg-muted border border-border rounded-lg p-2 text-sm text-foreground"
            value={value.language}
            onChange={(e) => onChange({ ...value, language: e.target.value })}
          >
            {LANGUAGES.map((l) => (
              <option key={l.id} value={l.id}>{l.label}</option>
            ))}
          </select>
        </div>
        <div>
          <p className="text-xs text-muted-foreground mb-2">{t("nodes.genConfig.countLabel")}</p>
          <input
            type="number"
            min={1}
            max={20}
            className="w-full bg-muted border border-border rounded-lg p-2 text-sm text-foreground"
            value={value.count}
            onChange={(e) => onChange({ ...value, count: parseInt(e.target.value) || 1 })}
          />
        </div>
      </div>

      {/* Brand info expandable */}
      <div className="border border-border rounded-lg">
        <button
          className="w-full flex items-center justify-between p-3 text-sm text-muted-foreground hover:text-foreground"
          onClick={() => setBrandExpanded(!brandExpanded)}
        >
          <span>{t("nodes.genConfig.brandFactsToggle")}</span>
          {brandExpanded ? <ChevronUp className="w-4 h-4" /> : <ChevronDown className="w-4 h-4" />}
        </button>
        {brandExpanded && (
          <div className="px-3 pb-3 space-y-3">
            <div>
              <label className="text-xs text-muted-foreground">{t("nodes.genConfig.productSpecs")}</label>
              <textarea
                className="w-full bg-muted border border-border rounded p-2 text-sm text-foreground resize-none mt-1"
                rows={2}
                placeholder={t("nodes.genConfig.productSpecsPlaceholder")}
                value={value.productFacts.specs}
                onChange={(e) => onChange({ ...value, productFacts: { ...value.productFacts, specs: e.target.value } })}
              />
            </div>
            <div>
              <label className="text-xs text-muted-foreground">{t("nodes.genConfig.keyFeatures")}</label>
              <textarea
                className="w-full bg-muted border border-border rounded p-2 text-sm text-foreground resize-none mt-1"
                rows={2}
                placeholder={t("nodes.genConfig.keyFeaturesPlaceholder")}
                value={value.productFacts.features}
                onChange={(e) => onChange({ ...value, productFacts: { ...value.productFacts, features: e.target.value } })}
              />
            </div>
            <div>
              <label className="text-xs text-muted-foreground">{t("nodes.genConfig.differentiators")}</label>
              <textarea
                className="w-full bg-muted border border-border rounded p-2 text-sm text-foreground resize-none mt-1"
                rows={2}
                placeholder={t("nodes.genConfig.differentiatorsPlaceholder")}
                value={value.productFacts.differentiators}
                onChange={(e) => onChange({ ...value, productFacts: { ...value.productFacts, differentiators: e.target.value } })}
              />
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
