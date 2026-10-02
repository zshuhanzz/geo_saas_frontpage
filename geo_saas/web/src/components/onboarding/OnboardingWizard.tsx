/**
 * OnboardingWizard — Spec §8.6 first-login dialog.
 *
 * Pops on first load for a workspace whose `/api/settings/onboarding_status`
 * reports `onboarding_wizard_completed=false`. Asks the user which of four
 * business shapes describes their brand, then hands off:
 *
 *   - own  → seed Own Brand (client.name), open Brands tab
 *   - oem  → steer user to Brands tab (Shadow section pre-expanded)
 *   - both → seed Own Brand + steer user to both sections
 *   - skip → close; wizard won't pop again until admin resets
 *
 * On `complete_onboarding`, backend seeds the Own Brand row and flips
 * `onboarding_wizard_completed=true` so we never nag again.
 *
 * The OEM branch also lets the user enter a first Shadow Brand name + alias
 * inline, so they can skip one hop. When they hit Finish, we create the
 * Shadow Brand via `addBrand` before dismissing.
 */
import { useState } from "react";
import { toast } from "sonner";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogHeader,
    DialogTitle,
    DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Loader2, Sparkles, Building2, Warehouse, Layers3, Clock } from "lucide-react";
import { Trans, useTranslation } from "react-i18next";
import HelpTooltip from "@/components/ui/HelpTooltip";
import {
    addBrand,
    completeOnboarding,
    type OnboardingBranch,
} from "@/lib/api";

interface OnboardingWizardProps {
    open: boolean;
    clientId: string;
    clientName: string;
    onClose: (opts?: { navigateTo?: string; tab?: "brands" | "peers" | "topics" }) => void;
}

type Step = "choose" | "oem-detail" | "done";

type BranchTooltipKey = "onboardingOwn" | "onboardingOem" | "onboardingBoth" | "onboardingSkip";
type BranchLabelKey = "own" | "oem" | "both" | "skip";

const BRANCH_OPTIONS: {
    key: OnboardingBranch;
    labelKey: BranchLabelKey;
    icon: typeof Building2;
    tooltipKey: BranchTooltipKey;
}[] = [
    { key: "own", labelKey: "own", icon: Building2, tooltipKey: "onboardingOwn" },
    { key: "oem", labelKey: "oem", icon: Warehouse, tooltipKey: "onboardingOem" },
    { key: "both", labelKey: "both", icon: Layers3, tooltipKey: "onboardingBoth" },
    { key: "skip", labelKey: "skip", icon: Clock, tooltipKey: "onboardingSkip" },
];

export function OnboardingWizard({ open, clientId, clientName, onClose }: OnboardingWizardProps) {
    const { t } = useTranslation("onboarding");
    const [step, setStep] = useState<Step>("choose");
    const [selected, setSelected] = useState<OnboardingBranch | null>(null);
    const [submitting, setSubmitting] = useState(false);

    // OEM detail fields
    const [shadowName, setShadowName] = useState("");
    const [shadowAlias, setShadowAlias] = useState("");

    function resetAndClose(opts?: Parameters<OnboardingWizardProps["onClose"]>[0]) {
        setStep("choose");
        setSelected(null);
        setShadowName("");
        setShadowAlias("");
        onClose(opts);
    }

    async function commitBranch(branch: OnboardingBranch, extra?: { shadow_brand_name?: string; shadow_alias?: string }) {
        setSubmitting(true);
        try {
            await completeOnboarding(clientId, branch);

            // If the OEM flow provided a Shadow Brand name inline, seed it
            // with a single POST /brands?is_shadow=true call. If this fails
            // we still treat the wizard as complete — the user can always
            // retry via the Settings Shadow Brand section.
            if (branch === "oem" && extra?.shadow_brand_name?.trim()) {
                try {
                    await addBrand(clientId, {
                        brand_name: extra.shadow_brand_name.trim(),
                        aliases: extra.shadow_alias?.trim() ? [extra.shadow_alias.trim()] : [],
                        is_shadow: true,
                        is_active: true,
                    });
                } catch (e: any) {
                    toast.error(
                        t("toasts.shadowBrandSaveFailed", { message: e?.message || t("toasts.unknownError") }),
                    );
                }
            }

            // Route post-dismiss:
            //   own   → Brands tab
            //   oem   → Brands tab (Shadow section)
            //   both  → Brands tab
            //   skip  → stay put
            if (branch === "skip") {
                resetAndClose();
            } else {
                resetAndClose({ navigateTo: "/settings", tab: "brands" });
            }
            toast.success(t("toasts.success"));
        } catch (e: any) {
            toast.error(e?.message || t("toasts.completeFailed"));
            setSubmitting(false);
        }
    }

    function handleChooseSubmit() {
        if (!selected) return;
        if (selected === "oem") {
            // Surface the OEM Step 2: "add first Shadow Brand + optional alias".
            setStep("oem-detail");
            return;
        }
        commitBranch(selected);
    }

    function handleOemDetailSubmit() {
        commitBranch("oem", {
            shadow_brand_name: shadowName,
            shadow_alias: shadowAlias,
        });
    }

    // Block close via Escape/backdrop while submitting to avoid half-seeded state.
    const canDismiss = !submitting;

    return (
        <Dialog
            open={open}
            onOpenChange={(o) => {
                if (!o && canDismiss) {
                    resetAndClose();
                }
            }}
        >
            <DialogContent className="max-w-xl" onEscapeKeyDown={(e) => submitting && e.preventDefault()}>
                <DialogHeader>
                    <DialogTitle className="flex items-center gap-2">
                        <Sparkles className="h-5 w-5 text-primary" />
                        {t("welcomeTitle")}
                    </DialogTitle>
                    <DialogDescription>
                        <Trans
                            i18nKey="welcomeDescription"
                            ns="onboarding"
                            values={{ clientName }}
                            components={{ 1: <span className="font-semibold text-foreground" /> }}
                        />
                    </DialogDescription>
                </DialogHeader>

                {step === "choose" && (
                    <div className="space-y-3 py-2">
                        <div className="text-sm font-medium text-foreground">
                            <HelpTooltip content={t("tooltips.onboardingBusinessShape")}>
                                {t("question")}
                            </HelpTooltip>
                        </div>

                        <div className="grid grid-cols-1 gap-2">
                            {BRANCH_OPTIONS.map((opt) => {
                                const Icon = opt.icon;
                                const active = selected === opt.key;
                                return (
                                    <button
                                        key={opt.key}
                                        type="button"
                                        onClick={() => setSelected(opt.key)}
                                        className={`flex items-start gap-3 rounded-lg border p-3 text-left transition-colors ${
                                            active
                                                ? "border-primary bg-primary/5"
                                                : "border-border hover:bg-muted/40"
                                        }`}
                                    >
                                        <div
                                            className={`h-9 w-9 rounded-md flex items-center justify-center shrink-0 ${
                                                active
                                                    ? "bg-primary/15 text-primary"
                                                    : "bg-muted text-muted-foreground"
                                            }`}
                                        >
                                            <Icon className="h-4 w-4" />
                                        </div>
                                        <div className="flex-1 min-w-0">
                                            <div className="flex items-center gap-1.5">
                                                <span className="text-sm font-semibold text-foreground">
                                                    {t(`branches.${opt.labelKey}Title`)}
                                                </span>
                                                <HelpTooltip content={t(`tooltips.${opt.tooltipKey}`)} />
                                            </div>
                                            <div className="text-xs text-muted-foreground mt-0.5 leading-relaxed">
                                                {t(`branches.${opt.labelKey}Desc`)}
                                            </div>
                                        </div>
                                    </button>
                                );
                            })}
                        </div>
                    </div>
                )}

                {step === "oem-detail" && (
                    <div className="space-y-4 py-2">
                        <div className="rounded-lg border bg-primary/5 px-3 py-2 text-xs text-muted-foreground">
                            <HelpTooltip content={t("tooltips.onboardingOem")}>
                                {t("oemStep.prompt")}
                            </HelpTooltip>
                        </div>

                        <div className="space-y-1.5">
                            <Label className="text-xs">
                                <HelpTooltip content={t("tooltips.onboardingShadowBrandName")}>{t("oemStep.shadowBrandName")}</HelpTooltip>
                            </Label>
                            <Input
                                value={shadowName}
                                onChange={(e) => setShadowName(e.target.value)}
                                placeholder={t("oemStep.shadowBrandPlaceholder")}
                                disabled={submitting}
                            />
                        </div>

                        <div className="space-y-1.5">
                            <Label className="text-xs">
                                <HelpTooltip content={t("tooltips.onboardingShadowAlias")}>
                                    {t("oemStep.alias")}
                                </HelpTooltip>
                            </Label>
                            <Input
                                value={shadowAlias}
                                onChange={(e) => setShadowAlias(e.target.value)}
                                placeholder={t("oemStep.aliasPlaceholder")}
                                disabled={submitting}
                            />
                        </div>

                        <div className="text-xs text-muted-foreground border-t pt-3 flex items-start gap-2">
                            <Badge variant="secondary" className="text-[10px] font-normal mt-0.5">
                                {t("oemStep.nextBadge")}
                            </Badge>
                            <span className="leading-relaxed">
                                <Trans
                                    i18nKey="oemStep.nextHint"
                                    ns="onboarding"
                                    components={{ 1: <strong /> }}
                                />
                            </span>
                        </div>
                    </div>
                )}

                <DialogFooter>
                    {step === "choose" ? (
                        <>
                            <Button
                                variant="outline"
                                onClick={() => commitBranch("skip")}
                                disabled={submitting}
                            >
                                {t("actions.skip")}
                            </Button>
                            <Button
                                onClick={handleChooseSubmit}
                                disabled={submitting || !selected}
                            >
                                {submitting ? (
                                    <Loader2 className="h-4 w-4 animate-spin" />
                                ) : (
                                    t("actions.next")
                                )}
                            </Button>
                        </>
                    ) : (
                        <>
                            <Button
                                variant="outline"
                                onClick={() => setStep("choose")}
                                disabled={submitting}
                            >
                                {t("actions.back")}
                            </Button>
                            <Button
                                onClick={handleOemDetailSubmit}
                                disabled={submitting}
                            >
                                {submitting ? (
                                    <Loader2 className="h-4 w-4 animate-spin" />
                                ) : (
                                    t("actions.finish")
                                )}
                            </Button>
                        </>
                    )}
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}

export default OnboardingWizard;
