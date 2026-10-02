import { useTranslation } from "react-i18next";
import { Loader2, Search, ChevronRight } from "lucide-react";
import { cn } from "@/lib/utils";
import { type AvailabilityFlags } from "@/lib/api";
import type { Template } from "./types";
import { DOMAIN_META, templateMatchesAvailability } from "./utils";

export function TemplateGallery({
    templates,
    loadingTemplates,
    availability,
    onPickTemplate,
    onOpenOpportunity,
}: {
    templates: Template[];
    loadingTemplates: boolean;
    availability: AvailabilityFlags | null;
    onPickTemplate: (t: Template) => void;
    onOpenOpportunity: () => void;
}) {
    const { t } = useTranslation("agents");
    return (
        <div className="flex-1 flex flex-col overflow-auto">
            <div className="max-w-4xl mx-auto w-full px-6 py-8">
                {/* Opportunity Discovery hero card */}
                <div className="mb-6">
                    <button
                        onClick={onOpenOpportunity}
                        className="w-full group text-left p-4 rounded-2xl border border-amber-500/20 bg-amber-500/[0.03] hover:bg-amber-500/[0.06] hover:border-amber-500/30 hover:shadow-lg hover:shadow-amber-500/5 transition-all duration-300 flex items-center gap-4"
                    >
                        <div className="w-11 h-11 rounded-xl bg-amber-500/10 flex items-center justify-center shrink-0">
                            <Search className="h-5 w-5 text-amber-500" />
                        </div>
                        <div className="flex-1 min-w-0">
                            <p className="text-sm font-semibold text-foreground">{t("analysis.opportunityTitle")}</p>
                            <p className="text-xs text-muted-foreground mt-0.5 leading-relaxed">
                                {t("analysis.opportunityDesc")}
                            </p>
                        </div>
                        <ChevronRight className="h-5 w-5 text-muted-foreground group-hover:text-amber-500 transition-colors shrink-0" />
                    </button>
                </div>

                {/* Template gallery */}
                <div>
                    <p className="text-sm font-medium text-muted-foreground mb-4">{t("analysis.templateGallery")}</p>
                    {loadingTemplates ? (
                        <div className="flex items-center justify-center py-10">
                            <Loader2 className="h-5 w-5 animate-spin text-muted-foreground" />
                        </div>
                    ) : (
                        <div className="grid grid-cols-2 md:grid-cols-5 gap-3">
                            {templates.filter((tpl) => tpl.name !== "优化机会发现" && templateMatchesAvailability(tpl, availability)).map((tpl) => {
                                const isCustom = !tpl.data_domains || tpl.data_domains.length === 0;
                                return (
                                    <button
                                        key={tpl.id}
                                        onClick={() => onPickTemplate(tpl)}
                                        className={cn(
                                            "group text-left p-4 rounded-2xl bg-card hover:bg-primary/[0.03] hover:border-primary/30 hover:shadow-lg hover:shadow-primary/5 transition-all duration-300",
                                            isCustom
                                                ? "border-2 border-dashed border-border"
                                                : "border bg-card"
                                        )}
                                    >
                                        <div className="flex items-center gap-2 mb-2.5">
                                            <div className={cn(
                                                "w-10 h-10 rounded-xl flex items-center justify-center text-xl transition-colors",
                                                isCustom ? "bg-muted/50 group-hover:bg-primary/10" : "bg-primary/10 group-hover:bg-primary/15"
                                            )}>
                                                {isCustom ? "✨" : (tpl.icon || "📊")}
                                            </div>
                                        </div>
                                        <p className="text-sm font-semibold text-foreground leading-snug group-hover:text-primary transition-colors mb-1.5">
                                            {tpl.name}
                                        </p>
                                        {tpl.data_domains.length > 0 && (
                                            <div className="flex flex-wrap gap-1">
                                                {tpl.data_domains.map(d => {
                                                    const meta = DOMAIN_META[d];
                                                    return meta ? (
                                                        <span key={d} className={`text-[10px] px-1.5 py-0.5 rounded-md border font-medium ${meta.color}`}>
                                                            {t(`analysis.domains.${meta.labelKey}`)}
                                                        </span>
                                                    ) : null;
                                                })}
                                            </div>
                                        )}
                                    </button>
                                );
                            })}
                        </div>
                    )}
                </div>
            </div>
        </div>
    );
}
