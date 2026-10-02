import { Sparkles, X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import HelpTooltip from "@/components/ui/HelpTooltip";
import SuggestionsPanel from "@/components/settings/SuggestionsPanel";
import type { CandidateType } from "@/lib/api";
import { TAB_RELEVANT_CANDIDATES, type TabKey } from "./types";

interface SuggestionsBannerProps {
    clientId: string;
    activeTab: TabKey;
    readOnly: boolean;
    candidateCounts: Partial<Record<CandidateType, number>>;
    suggestionsOpen: boolean;
    setSuggestionsOpen: (v: boolean) => void;
    suggestionsScope: CandidateType | "all" | "tab";
    setSuggestionsScope: (s: CandidateType | "all" | "tab") => void;
    reloadCandidateCounts: () => void;
}

export default function SuggestionsBanner({
    clientId,
    activeTab,
    readOnly,
    candidateCounts,
    suggestionsOpen,
    setSuggestionsOpen,
    suggestionsScope,
    setSuggestionsScope,
    reloadCandidateCounts,
}: SuggestionsBannerProps) {
    const { t } = useTranslation("settings");
    return (
        <>
            {/* Phase 6 — AI 建议汇总入口(per-tab banner + global panel)*/}
            {(() => {
                const totalPending = Object.values(candidateCounts).reduce(
                    (acc, n) => acc + (n || 0), 0,
                );
                if (totalPending === 0 && !suggestionsOpen) return null;
                const tabCount = TAB_RELEVANT_CANDIDATES[activeTab].reduce(
                    (acc, t) => acc + (candidateCounts[t] || 0), 0,
                );
                return (
                    <div className="mb-4 rounded-md border border-primary/20 bg-primary/5 p-3 flex items-center gap-3">
                        <Sparkles className="h-4 w-4 text-primary shrink-0" />
                        <div className="text-sm flex-1">
                            <HelpTooltip content={t("tooltips.aiSuggestionsBanner")}>
                                <span>
                                    {t("banner.bannerPrefix")} <strong>{tabCount}</strong>{" "}
                                    {activeTab === "brands" && t("banner.bannerSuffixBrand")}
                                    {activeTab === "peers" && t("banner.bannerSuffixPeer")}
                                    {activeTab === "topics" && t("banner.bannerSuffixTopic")}
                                </span>
                            </HelpTooltip>
                            <span className="text-muted-foreground text-xs ml-2">
                                {t("banner.totalPending", { count: totalPending })}
                            </span>
                        </div>
                        <Button
                            size="sm"
                            variant={suggestionsOpen && suggestionsScope === "tab" ? "default" : "outline"}
                            onClick={() => {
                                if (TAB_RELEVANT_CANDIDATES[activeTab].length === 0) return;
                                if (suggestionsOpen && suggestionsScope === "tab") {
                                    // Toggle off — already showing this tab's candidates.
                                    setSuggestionsOpen(false);
                                } else {
                                    setSuggestionsScope("tab");
                                    setSuggestionsOpen(true);
                                }
                            }}
                            disabled={tabCount === 0}
                        >
                            {suggestionsOpen && suggestionsScope === "tab" ? t("banner.closeTabScope") : t("banner.openTabScope")}
                        </Button>
                        <Button
                            size="sm"
                            variant={suggestionsOpen && suggestionsScope === "all" ? "default" : "outline"}
                            onClick={() => {
                                if (suggestionsOpen && suggestionsScope === "all") {
                                    setSuggestionsOpen(false);
                                } else {
                                    setSuggestionsScope("all");
                                    setSuggestionsOpen(true);
                                }
                            }}
                        >
                            {suggestionsOpen && suggestionsScope === "all" ? t("banner.closeAllScope") : t("banner.openAllScope")}
                        </Button>
                    </div>
                );
            })()}
            {suggestionsOpen && clientId && (
                <div className="mb-6 rounded-md border border-muted bg-background p-4">
                    <div className="flex justify-end mb-3">
                        <Button size="sm" variant="ghost" onClick={() => setSuggestionsOpen(false)}>
                            <X className="h-3.5 w-3.5 mr-1" /> {t("banner.collapse")}
                        </Button>
                    </div>
                    <SuggestionsPanel
                        clientId={clientId}
                        readOnly={readOnly}
                        candidateType={
                            suggestionsScope === "all" || suggestionsScope === "tab"
                                ? undefined
                                : suggestionsScope
                        }
                        candidateTypes={
                            suggestionsScope === "tab"
                                ? [...(TAB_RELEVANT_CANDIDATES[activeTab] || [])]
                                : undefined
                        }
                        onDelta={() => void reloadCandidateCounts()}
                    />
                </div>
            )}
        </>
    );
}
