import {
    AlertCircle, CheckCircle2, Globe, Link2, Loader2, Plus, Sparkles, Trash2, X,
} from "lucide-react";
import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Checkbox } from "@/components/ui/checkbox";
import {
    Dialog,
    DialogContent,
    DialogDescription,
    DialogFooter,
    DialogHeader,
    DialogTitle,
} from "@/components/ui/dialog";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from "@/components/ui/select";
import { Textarea } from "@/components/ui/textarea";
import type { AutoDiscoverResult, Brand, DiscoveredTopic } from "@/lib/api";
import DraftProductAdder from "./DraftProductAdder";
import {
    INSTRUCTION_MAX_CHARS,
    OTHER_BRAND_SENTINEL,
    OTHER_URL_SENTINEL,
    type ProgressEntry,
} from "./types";

interface AutoDiscoveryDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    ownBrands: Brand[];
    shadowBrands: Brand[];
    brandOwnedDomains: any[];
    discoverBrandChoice: string;
    discoverBrand: string;
    setDiscoverBrand: (v: string) => void;
    handleDiscoverBrandChoiceChange: (v: string) => void;
    discoverUrlChoice: string;
    discoverUrl: string;
    setDiscoverUrl: (v: string) => void;
    handleDomainChoiceChange: (v: string) => void;
    discoverSeedUrls: string[];
    setDiscoverSeedUrls: (urls: string[]) => void;
    discoverInstruction: string;
    setDiscoverInstruction: (v: string) => void;
    discoverLoading: boolean;
    discoverImporting: boolean;
    discoverProgress: ProgressEntry[];
    discoverResult: AutoDiscoverResult | null;
    discoverDraft: DiscoveredTopic[];
    discoverSelection: Record<string, boolean>;
    seedUrlIndex: Record<string, string[]>;
    handleRunAutoDiscover: () => void;
    handleImportDiscovered: () => void;
    toggleDiscoverTopic: (key: string) => void;
    updateDraftTopicName: (idx: number, newName: string) => void;
    removeDraftProduct: (topicIdx: number, prodIdx: number) => void;
    addDraftProduct: (topicIdx: number, value: string) => void;
    removeDraftTopic: (topicIdx: number) => void;
}

export default function AutoDiscoveryDialog(props: AutoDiscoveryDialogProps) {
    const { t } = useTranslation("settings");
    const {
        open, onOpenChange,
        ownBrands, shadowBrands, brandOwnedDomains,
        discoverBrandChoice, discoverBrand, setDiscoverBrand, handleDiscoverBrandChoiceChange,
        discoverUrlChoice, discoverUrl, setDiscoverUrl, handleDomainChoiceChange,
        discoverSeedUrls, setDiscoverSeedUrls,
        discoverInstruction, setDiscoverInstruction,
        discoverLoading, discoverImporting,
        discoverProgress, discoverResult, discoverDraft, discoverSelection, seedUrlIndex,
        handleRunAutoDiscover, handleImportDiscovered,
        toggleDiscoverTopic, updateDraftTopicName, removeDraftProduct, addDraftProduct, removeDraftTopic,
    } = props;

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="max-w-3xl max-h-[85vh] overflow-y-auto">
                <DialogHeader>
                    <DialogTitle className="flex items-center gap-2">
                        <Sparkles className="h-5 w-5 text-primary" /> {t("autoDiscover.modalTitle")}
                    </DialogTitle>
                    <DialogDescription>
                        {t("autoDiscover.modalDescription")}
                    </DialogDescription>
                </DialogHeader>

                <div className="grid gap-4 py-2">
                    <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
                        {/* ---------------------- 品牌名 ---------------------- */}
                        <div className="space-y-1.5">
                            <Label htmlFor="discover-brand-select" className="text-xs">
                                {t("autoDiscover.brandLabel")}
                            </Label>
                            {ownBrands.length + shadowBrands.length > 0 ? (
                                <Select
                                    value={discoverBrandChoice}
                                    onValueChange={handleDiscoverBrandChoiceChange}
                                    disabled={discoverLoading}
                                >
                                    <SelectTrigger id="discover-brand-select">
                                        <SelectValue placeholder={t("autoDiscover.brandSelectPlaceholder")} />
                                    </SelectTrigger>
                                    <SelectContent>
                                        {ownBrands.length > 0 && (
                                            <>
                                                <div className="px-2 py-1 text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">
                                                    {t("autoDiscover.brandGroupOwn")}
                                                </div>
                                                {ownBrands.map((b) => (
                                                    <SelectItem
                                                        key={b.id}
                                                        value={b.brand_name}
                                                    >
                                                        <span className="flex items-center gap-2">
                                                            <span className="text-xs">
                                                                {b.brand_name}
                                                            </span>
                                                        </span>
                                                    </SelectItem>
                                                ))}
                                            </>
                                        )}
                                        {shadowBrands.length > 0 && (
                                            <>
                                                <div className="px-2 py-1 text-[10px] font-semibold text-muted-foreground uppercase tracking-wider">
                                                    {t("autoDiscover.brandGroupShadow")}
                                                </div>
                                                {shadowBrands.map((b) => (
                                                    <SelectItem
                                                        key={b.id}
                                                        value={b.brand_name}
                                                    >
                                                        <span className="flex items-center gap-2">
                                                            <span className="text-xs">
                                                                {b.brand_name}
                                                            </span>
                                                            <Badge
                                                                variant="outline"
                                                                className="text-[10px] px-1 py-0 h-4"
                                                            >
                                                                {t("autoDiscover.channelBadge")}
                                                            </Badge>
                                                        </span>
                                                    </SelectItem>
                                                ))}
                                            </>
                                        )}
                                        <SelectItem value={OTHER_BRAND_SENTINEL}>
                                            <span className="flex items-center gap-2 text-muted-foreground">
                                                <Plus className="h-3.5 w-3.5" />
                                                <span className="text-xs">{t("autoDiscover.brandOther")}</span>
                                            </span>
                                        </SelectItem>
                                    </SelectContent>
                                </Select>
                            ) : null}
                            {(ownBrands.length + shadowBrands.length === 0 ||
                                discoverBrandChoice === OTHER_BRAND_SENTINEL) && (
                                    <Input
                                        id="discover-brand"
                                        placeholder={t("autoDiscover.brandInputPlaceholder")}
                                        value={discoverBrand}
                                        onChange={(e) => setDiscoverBrand(e.target.value)}
                                        disabled={discoverLoading}
                                    />
                                )}
                        </div>

                        {/* ---------------------- 网站 URL ---------------------- */}
                        <div className="space-y-1.5">
                            <Label htmlFor="discover-url-select" className="text-xs">
                                {t("autoDiscover.urlLabel")}
                            </Label>
                            {brandOwnedDomains.length > 0 ? (
                                <Select
                                    value={discoverUrlChoice}
                                    onValueChange={handleDomainChoiceChange}
                                    disabled={discoverLoading}
                                >
                                    <SelectTrigger id="discover-url-select">
                                        <SelectValue placeholder={t("autoDiscover.urlSelectPlaceholder")} />
                                    </SelectTrigger>
                                    <SelectContent>
                                        {brandOwnedDomains.map((d: any) => {
                                            const brand = [...ownBrands, ...shadowBrands].find(
                                                (b) => b.id === d.brand_id,
                                            );
                                            const isShadow = brand?.is_shadow;
                                            return (
                                                <SelectItem key={d.id} value={d.domain}>
                                                    <span className="flex items-center gap-2">
                                                        <Globe className="h-3.5 w-3.5 text-muted-foreground" />
                                                        <span className="font-mono text-xs">
                                                            {d.domain}
                                                        </span>
                                                        {d.is_primary && (
                                                            <Badge
                                                                variant="outline"
                                                                className="text-[10px] px-1 py-0 h-4"
                                                            >
                                                                {t("autoDiscover.urlPrimaryBadge")}
                                                            </Badge>
                                                        )}
                                                        {isShadow && (
                                                            <Badge
                                                                variant="outline"
                                                                className="text-[10px] px-1 py-0 h-4"
                                                            >
                                                                {t("autoDiscover.channelBadge")}
                                                            </Badge>
                                                        )}
                                                    </span>
                                                </SelectItem>
                                            );
                                        })}
                                        <SelectItem value={OTHER_URL_SENTINEL}>
                                            <span className="flex items-center gap-2 text-muted-foreground">
                                                <Plus className="h-3.5 w-3.5" />
                                                <span className="text-xs">{t("autoDiscover.urlOther")}</span>
                                            </span>
                                        </SelectItem>
                                    </SelectContent>
                                </Select>
                            ) : null}
                            {(brandOwnedDomains.length === 0 ||
                                discoverUrlChoice === OTHER_URL_SENTINEL) && (
                                    <Input
                                        id="discover-url"
                                        placeholder="https://www.answerx.ai"
                                        value={discoverUrl}
                                        onChange={(e) => setDiscoverUrl(e.target.value)}
                                        disabled={discoverLoading}
                                    />
                                )}
                        </div>
                    </div>

                    <div className="space-y-1.5">
                        <div className="flex items-center justify-between">
                            <Label className="text-xs">
                                {t("autoDiscover.seedUrlsLabel")}{" "}
                                <span className="text-muted-foreground font-normal">
                                    {t("autoDiscover.seedUrlsBadge")}
                                </span>
                            </Label>
                            <span className="text-[10px] text-muted-foreground">
                                {t("autoDiscover.seedUrlsHint")}
                            </span>
                        </div>
                        {discoverSeedUrls.map((url, idx) => (
                            <div key={idx} className="flex items-center gap-1.5">
                                <Input
                                    placeholder="https://www.answerx.ai/category/product-series/10118"
                                    value={url}
                                    onChange={(e) => {
                                        const next = [...discoverSeedUrls];
                                        next[idx] = e.target.value;
                                        setDiscoverSeedUrls(next);
                                    }}
                                    disabled={discoverLoading}
                                    className="flex-1 text-xs"
                                />
                                {discoverSeedUrls.length > 1 && (
                                    <Button
                                        type="button"
                                        variant="ghost"
                                        size="sm"
                                        className="h-8 w-8 p-0 shrink-0"
                                        disabled={discoverLoading}
                                        onClick={() =>
                                            setDiscoverSeedUrls(
                                                discoverSeedUrls.filter((_, i) => i !== idx),
                                            )
                                        }
                                    >
                                        ×
                                    </Button>
                                )}
                            </div>
                        ))}
                        <Button
                            type="button"
                            variant="ghost"
                            size="sm"
                            className="h-7 text-xs"
                            disabled={discoverLoading || discoverSeedUrls.length >= 10}
                            onClick={() =>
                                setDiscoverSeedUrls([...discoverSeedUrls, ""])
                            }
                        >
                            <Plus className="h-3 w-3 mr-1" />
                            {t("autoDiscover.seedUrlsAdd")}
                        </Button>
                    </div>

                    <div className="space-y-1.5">
                        <div className="flex items-center justify-between">
                            <Label htmlFor="discover-instruction" className="text-xs">
                                {t("autoDiscover.noteLabel")}{" "}
                                <span className="text-muted-foreground font-normal">{t("autoDiscover.noteBadge")}</span>
                            </Label>
                            <span
                                className={`text-[10px] font-mono ${discoverInstruction.length > INSTRUCTION_MAX_CHARS
                                    ? "text-destructive"
                                    : "text-muted-foreground"
                                    }`}
                            >
                                {discoverInstruction.length} / {INSTRUCTION_MAX_CHARS}
                            </span>
                        </div>
                        <Textarea
                            id="discover-instruction"
                            value={discoverInstruction}
                            onChange={(e) =>
                                setDiscoverInstruction(
                                    e.target.value.slice(0, INSTRUCTION_MAX_CHARS),
                                )
                            }
                            disabled={discoverLoading}
                            rows={3}
                            placeholder={t("autoDiscover.notePlaceholder")}
                            className="text-xs resize-none font-sans"
                        />
                    </div>

                    <Button
                        onClick={handleRunAutoDiscover}
                        disabled={
                            discoverLoading ||
                            !discoverBrand.trim() ||
                            !discoverUrl.trim()
                        }
                        className="w-full"
                    >
                        {discoverLoading ? (
                            <>
                                <Loader2 className="h-4 w-4 mr-2 animate-spin" /> {t("autoDiscover.running")}
                            </>
                        ) : (
                            <>
                                <Sparkles className="h-4 w-4 mr-2" /> {t("autoDiscover.runButton")}
                            </>
                        )}
                    </Button>

                    {discoverProgress.length > 0 && (
                        <div className="rounded-md border bg-muted/10 p-3 space-y-1.5 max-h-[220px] overflow-y-auto">
                            <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider flex items-center gap-2 mb-1">
                                {discoverLoading ? (
                                    <Loader2 className="h-3 w-3 animate-spin text-primary" />
                                ) : (
                                    <CheckCircle2 className="h-3 w-3 text-primary" />
                                )}
                                {t("autoDiscover.progressLogsTitle")}
                            </div>
                            {discoverProgress.map((p, i) => (
                                <div
                                    key={i}
                                    className={`flex items-start gap-2 text-xs ${p.kind === "error"
                                        ? "text-destructive"
                                        : p.kind === "warn"
                                            ? "text-amber-600 dark:text-amber-400"
                                            : p.kind === "progress"
                                                ? "text-foreground"
                                                : "text-muted-foreground"
                                        }`}
                                >
                                    <span className="font-mono shrink-0 w-[96px] truncate">
                                        {p.stage}
                                    </span>
                                    <span className="flex-1">
                                        {p.message}
                                        {typeof p.count === "number" && (
                                            <span className="ml-1 font-semibold">({p.count})</span>
                                        )}
                                    </span>
                                </div>
                            ))}
                        </div>
                    )}

                    {discoverResult && (
                        <div className="space-y-3 mt-2 rounded-md border bg-muted/20 p-4">
                            <div className="flex items-center justify-between">
                                <div className="flex items-center gap-2">
                                    {discoverResult.source_layer === "failed" ? (
                                        <AlertCircle className="h-4 w-4 text-destructive" />
                                    ) : (
                                        <CheckCircle2 className="h-4 w-4 text-primary" />
                                    )}
                                    <span className="text-xs font-mono text-muted-foreground">
                                        Source: {discoverResult.source_layer}
                                    </span>
                                </div>
                                <span className="text-xs text-muted-foreground">
                                    {t("autoDiscover.draftStats", {
                                        topics: discoverDraft.length,
                                        products: discoverDraft.reduce(
                                            (acc, topic) => acc + (topic.products?.length || 0),
                                            0,
                                        ),
                                    })}
                                    {(() => {
                                        const totalSeed = discoverResult.seed_products?.length || 0;
                                        if (totalSeed === 0) return null;
                                        const matchedUrls = new Set<string>();
                                        Object.values(seedUrlIndex).forEach((arr) =>
                                            arr.forEach((u) => matchedUrls.add(u)),
                                        );
                                        return (
                                            <>
                                                {" · "}
                                                <span className="text-primary font-medium">
                                                    {t("autoDiscover.draftUrlsMatched", {
                                                        matched: matchedUrls.size,
                                                        total: totalSeed,
                                                    })}
                                                </span>
                                            </>
                                        );
                                    })()}
                                </span>
                            </div>

                            {discoverDraft.length > 0 ? (
                                <div className="space-y-3 max-h-[44vh] overflow-y-auto pr-1">
                                    {discoverDraft.map((topic, idx) => {
                                        const key = String(idx);
                                        const selected = !!discoverSelection[key];
                                        return (
                                            <div
                                                key={idx}
                                                className={`rounded border p-3 transition-colors ${selected
                                                    ? "border-primary bg-primary/5"
                                                    : "border-border bg-background"
                                                    }`}
                                            >
                                                <div className="flex items-center gap-2">
                                                    <Checkbox
                                                        checked={selected}
                                                        onCheckedChange={() => toggleDiscoverTopic(key)}
                                                    />
                                                    <Input
                                                        value={topic.topic_name}
                                                        onChange={(e) =>
                                                            updateDraftTopicName(idx, e.target.value)
                                                        }
                                                        className="h-7 text-sm font-medium flex-1"
                                                        placeholder={t("autoDiscover.topicNamePlaceholder")}
                                                    />
                                                    <Badge
                                                        variant="secondary"
                                                        className="text-[10px] font-normal"
                                                    >
                                                        {t("topics.semanticTopic")}
                                                    </Badge>
                                                    <Badge variant="outline" className="text-xs">
                                                        {t("autoDiscover.productCount", { count: topic.products.length })}
                                                    </Badge>
                                                    <Button
                                                        variant="ghost"
                                                        size="sm"
                                                        onClick={() => removeDraftTopic(idx)}
                                                        className="h-7 w-7 p-0 text-muted-foreground hover:text-destructive"
                                                    >
                                                        <Trash2 className="h-3.5 w-3.5" />
                                                    </Button>
                                                </div>
                                                <div className="mt-2 flex flex-wrap gap-1 pl-8">
                                                    {topic.products.map((p, pidx) => {
                                                        const urlCount =
                                                            (seedUrlIndex[p.trim().toLowerCase()] || []).length;
                                                        return (
                                                            <Badge
                                                                key={pidx}
                                                                variant="outline"
                                                                className="text-xs font-normal pl-2 pr-1 py-0.5"
                                                                title={
                                                                    urlCount > 0
                                                                        ? t("autoDiscover.matchedUrlsHint", { count: urlCount })
                                                                        : t("autoDiscover.unmatchedUrlsHint")
                                                                }
                                                            >
                                                                {p}
                                                                {urlCount > 0 && (
                                                                    <span className="ml-1.5 inline-flex items-center gap-0.5 rounded-sm bg-primary/15 text-primary px-1 py-px text-[10px] font-medium">
                                                                        <Link2 className="h-2.5 w-2.5" />
                                                                        {urlCount}
                                                                    </span>
                                                                )}
                                                                <button
                                                                    onClick={() =>
                                                                        removeDraftProduct(idx, pidx)
                                                                    }
                                                                    className="ml-1.5 rounded-full hover:bg-destructive/10 hover:text-destructive transition-colors"
                                                                >
                                                                    <X className="h-3 w-3" />
                                                                </button>
                                                            </Badge>
                                                        );
                                                    })}
                                                    <DraftProductAdder
                                                        onAdd={(value) => addDraftProduct(idx, value)}
                                                    />
                                                </div>
                                            </div>
                                        );
                                    })}
                                </div>
                            ) : (
                                <div className="rounded-md border border-amber-500/30 bg-amber-500/5 p-4 space-y-2">
                                    <div className="flex items-center gap-2 text-sm font-medium text-amber-600 dark:text-amber-400">
                                        <AlertCircle className="h-4 w-4" /> {t("autoDiscover.errorTitle")}
                                    </div>
                                    <p className="text-xs text-muted-foreground leading-relaxed">
                                        {t("autoDiscover.errorHint")}
                                    </p>
                                </div>
                            )}
                        </div>
                    )}
                </div>

                <DialogFooter>
                    <Button
                        variant="outline"
                        onClick={() => onOpenChange(false)}
                        disabled={discoverImporting}
                    >
                        {t("autoDiscover.cancel")}
                    </Button>
                    {(() => {
                        const selectedTopics = discoverDraft.filter(
                            (_topic, i) => discoverSelection[String(i)],
                        );
                        const productCount = selectedTopics.reduce(
                            (acc, topic) => acc + (topic.products?.length || 0),
                            0,
                        );
                        const urlCount = selectedTopics.reduce(
                            (acc, topic) =>
                                acc +
                                (topic.products || []).reduce(
                                    (a, p) =>
                                        a + (seedUrlIndex[p.trim().toLowerCase()]?.length || 0),
                                    0,
                                ),
                            0,
                        );
                        return (
                            <Button
                                onClick={handleImportDiscovered}
                                disabled={
                                    discoverLoading ||
                                    discoverImporting ||
                                    discoverDraft.length === 0 ||
                                    selectedTopics.length === 0
                                }
                            >
                                {discoverImporting ? (
                                    <>
                                        <Loader2 className="h-4 w-4 mr-2 animate-spin" />
                                        {t("autoDiscover.importing", {
                                            topics: selectedTopics.length,
                                            products: productCount,
                                        })}
                                        {urlCount > 0 ? ` · ${urlCount} URL…` : "…"}
                                    </>
                                ) : (
                                    <>
                                        {t("autoDiscover.importButton")}
                                        {urlCount > 0 ? (
                                            <span className="ml-2 text-xs opacity-80">
                                                {t("autoDiscover.importButtonDetail", {
                                                    topics: selectedTopics.length,
                                                    products: productCount,
                                                    urls: urlCount,
                                                })}
                                            </span>
                                        ) : null}
                                    </>
                                )}
                            </Button>
                        );
                    })()}
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}
