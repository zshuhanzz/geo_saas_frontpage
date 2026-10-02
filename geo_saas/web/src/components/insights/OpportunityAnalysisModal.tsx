import { useState } from "react";
import { toast } from "sonner";
import { useTranslation } from "react-i18next";
import {
    Dialog, DialogContent, DialogTitle, DialogDescription
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Loader2, Search, ArrowRight, Crosshair, Lightbulb, Network } from "lucide-react";
import { createAgentTask } from "@/lib/api";
import { cn } from "@/lib/utils";
import { addLocalDays, todayDateOnlyString } from "@/lib/dateOnly";

interface OpportunityAnalysisModalProps {
    open: boolean;
    clientId: string;
    userId: string;
    onClose: () => void;
    onTaskCreated?: () => void;
}

const DATE_RANGES = [7, 14, 30, 90] as const;

const PLATFORMS = [
    { label: "ChatGPT", value: "chatgpt" },
    { label: "Gemini", value: "gemini" },
    { label: "AI Mode", value: "aimode" },
    { label: "Perplexity", value: "perplexity" },
    { label: "AI Overview", value: "aioverview" },
] as const;

type MethodologyStepKey = "quadrant" | "opportunity" | "graph";
const METHODOLOGY_STEPS: { key: MethodologyStepKey; icon: typeof Crosshair }[] = [
    { key: "quadrant", icon: Crosshair },
    { key: "opportunity", icon: Lightbulb },
    { key: "graph", icon: Network },
];

export default function OpportunityAnalysisModal({
    open,
    clientId,
    userId,
    onClose,
    onTaskCreated,
}: OpportunityAnalysisModalProps) {
    const { t } = useTranslation("insights");
    const [dateRange, setDateRange] = useState(30);
    const [selectedPlatforms, setSelectedPlatforms] = useState<string[]>([]);
    const [submitting, setSubmitting] = useState(false);

    const togglePlatform = (value: string) => {
        setSelectedPlatforms((prev) =>
            prev.includes(value) ? prev.filter((p) => p !== value) : [...prev, value]
        );
    };

    const handleSubmit = async () => {
        setSubmitting(true);
        try {
            const dateTo = todayDateOnlyString();
            const dateFrom = addLocalDays(dateTo, -dateRange + 1);

            await createAgentTask({
                client_id: clientId,
                user_id: userId,
                task_type: "opportunity_discovery",
                task_name: t("opportunityModal.taskName", { date: new Date().toLocaleDateString() }),
                inputs: {
                    domains: ["visibility", "citation"],
                    date_from: dateFrom,
                    date_to: dateTo,
                    platforms: selectedPlatforms.length > 0 ? selectedPlatforms : null,
                    analysis_goal: "opportunity",
                },
                save_only: false,
            });

            toast.success(t("opportunityModal.toastSuccess"));
            onTaskCreated?.();
        } catch (err: any) {
            toast.error(err.message || t("opportunityModal.toastFailed"));
        } finally {
            setSubmitting(false);
        }
    };

    return (
        <Dialog open={open} onOpenChange={(v) => !v && onClose()}>
            <DialogContent className="sm:max-w-[560px] bg-background border-border p-0 gap-0">
                {/* Header */}
                <div className="px-6 pt-6 pb-4">
                    <DialogTitle className="flex items-center gap-2.5 text-lg font-semibold text-foreground">
                        <div className="w-9 h-9 rounded-xl bg-amber-500/10 flex items-center justify-center">
                            <Search className="h-4.5 w-4.5 text-amber-500" />
                        </div>
                        {t("opportunityModal.title")}
                    </DialogTitle>
                    <DialogDescription className="mt-2 text-sm text-muted-foreground">
                        {t("opportunityModal.description")}
                    </DialogDescription>
                </div>

                {/* Methodology steps */}
                <div className="px-6 pb-4 space-y-2.5">
                    {METHODOLOGY_STEPS.map((step) => {
                        const Icon = step.icon;
                        return (
                            <div
                                key={step.key}
                                className="flex items-start gap-3 rounded-xl border border-border bg-muted/30 p-3.5"
                            >
                                <div className="mt-0.5 flex h-8 w-8 shrink-0 items-center justify-center rounded-lg bg-amber-500/10">
                                    <Icon className="h-4 w-4 text-amber-500" />
                                </div>
                                <div className="min-w-0">
                                    <p className="text-sm font-medium text-foreground leading-tight">
                                        {t(`opportunityModal.methodology.${step.key}Title`)}
                                    </p>
                                    <p className="mt-0.5 text-xs text-muted-foreground leading-relaxed">
                                        {t(`opportunityModal.methodology.${step.key}Desc`)}
                                    </p>
                                </div>
                            </div>
                        );
                    })}
                </div>

                {/* Config section */}
                <div className="border-t border-border px-6 py-4 space-y-4">
                    {/* Date range */}
                    <div>
                        <p className="text-xs font-medium text-muted-foreground mb-2">{t("opportunityModal.dateRange")}</p>
                        <div className="flex gap-2">
                            {DATE_RANGES.map((days) => (
                                <Button
                                    key={days}
                                    size="sm"
                                    variant={dateRange === days ? "default" : "outline"}
                                    className={cn(
                                        "h-8 px-3 text-xs",
                                        dateRange === days
                                            ? "bg-primary text-primary-foreground"
                                            : "text-muted-foreground"
                                    )}
                                    onClick={() => setDateRange(days)}
                                >
                                    {t("opportunityModal.dateRangeOption", { days })}
                                </Button>
                            ))}
                        </div>
                    </div>

                    {/* Platform filter */}
                    <div>
                        <p className="text-xs font-medium text-muted-foreground mb-2">
                            {t("opportunityModal.platformFilter")} <span className="font-normal text-muted-foreground/70">{t("opportunityModal.platformFilterHint")}</span>
                        </p>
                        <div className="flex gap-2">
                            {PLATFORMS.map((p) => {
                                const active = selectedPlatforms.includes(p.value);
                                return (
                                    <Button
                                        key={p.value}
                                        size="sm"
                                        variant={active ? "default" : "outline"}
                                        className={cn(
                                            "h-8 px-3 text-xs",
                                            active
                                                ? "bg-primary text-primary-foreground"
                                                : "text-muted-foreground"
                                        )}
                                        onClick={() => togglePlatform(p.value)}
                                    >
                                        {p.label}
                                    </Button>
                                );
                            })}
                        </div>
                    </div>
                </div>

                {/* Footer */}
                <div className="border-t border-border px-6 py-4 flex justify-end">
                    <Button
                        onClick={handleSubmit}
                        disabled={submitting}
                        className="gap-2"
                    >
                        {submitting ? (
                            <Loader2 className="h-4 w-4 animate-spin" />
                        ) : (
                            <ArrowRight className="h-4 w-4" />
                        )}
                        {t("opportunityModal.submit")}
                    </Button>
                </div>
            </DialogContent>
        </Dialog>
    );
}
