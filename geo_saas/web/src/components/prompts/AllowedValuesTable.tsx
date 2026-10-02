import { useMemo, useState } from "react";
import { Check, Copy, Download, Loader2, RotateCw, Search } from "lucide-react";
import { useTranslation } from "react-i18next";
import { toast } from "sonner";

import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import type { PromptAllowedValue } from "@/lib/api/prompts";
import { groupAllowedValues } from "./promptImportViewModel";

type AllowedTypeTranslationKey =
    | "prompts.import.allowed.types.topic"
    | "prompts.import.allowed.types.product"
    | "prompts.import.allowed.types.platform"
    | "prompts.import.allowed.types.country"
    | "prompts.import.allowed.types.language"
    | "prompts.import.allowed.types.intent"
    | "prompts.import.allowed.types.other";

const TYPE_KEY: Record<string, AllowedTypeTranslationKey> = {
    Topic: "prompts.import.allowed.types.topic",
    Product: "prompts.import.allowed.types.product",
    "AI Platform": "prompts.import.allowed.types.platform",
    Country: "prompts.import.allowed.types.country",
    Language: "prompts.import.allowed.types.language",
    Intent: "prompts.import.allowed.types.intent",
};

interface AllowedValuesTableProps {
    rows: readonly PromptAllowedValue[];
    loading: boolean;
    error: string;
    downloading: boolean;
    onRetry: () => void;
    onDownload: () => void;
}

export function AllowedValuesTable({
    rows,
    loading,
    error,
    downloading,
    onRetry,
    onDownload,
}: AllowedValuesTableProps) {
    const { t } = useTranslation(["insights", "common"]);
    const [query, setQuery] = useState("");
    const [copied, setCopied] = useState("");
    const grouped = useMemo(() => groupAllowedValues(rows, query), [query, rows]);

    async function copyValue(value: string) {
        try {
            await navigator.clipboard.writeText(value);
            setCopied(value);
            window.setTimeout(() => setCopied((current) => current === value ? "" : current), 1500);
            toast.success(t("prompts.import.allowed.copySuccess", { value }));
        } catch {
            toast.error(t("prompts.import.allowed.copyFailed"));
        }
    }

    if (loading) {
        return <div className="flex min-h-48 items-center justify-center gap-2 text-sm text-muted-foreground"><Loader2 className="h-4 w-4 animate-spin" />{t("common:states.loading")}</div>;
    }

    if (error) {
        return (
            <div className="flex min-h-48 flex-col items-center justify-center gap-3 rounded-md border border-destructive/30 p-6 text-center">
                <p className="text-sm text-destructive">{error}</p>
                <Button variant="outline" size="sm" onClick={onRetry}><RotateCw className="mr-2 h-4 w-4" />{t("common:actions.retry")}</Button>
            </div>
        );
    }

    return (
        <div className="space-y-4">
            <div className="flex flex-wrap gap-2">
                <div className="relative min-w-64 flex-1">
                    <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-muted-foreground" />
                    <Input
                        value={query}
                        onChange={(event) => setQuery(event.target.value)}
                        placeholder={t("prompts.import.allowed.searchPlaceholder")}
                        className="pl-9"
                    />
                </div>
                <Button variant="outline" onClick={onDownload} disabled={downloading}>
                    {downloading ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : <Download className="mr-2 h-4 w-4" />}
                    {t("prompts.import.allowed.download")}
                </Button>
            </div>
            <p className="text-xs text-muted-foreground">{t("prompts.import.allowed.canonicalHint")}</p>
            {Object.keys(grouped).length === 0 ? (
                <div className="rounded-md border p-6 text-center text-sm text-muted-foreground">{t("prompts.import.allowed.empty")}</div>
            ) : (
                <div className="max-h-[470px] space-y-4 overflow-auto pr-1">
                    {Object.entries(grouped).map(([type, values]) => (
                        <section key={type} className="rounded-md border">
                            <div className="border-b bg-muted/30 px-3 py-2 text-sm font-semibold">
                                {t(TYPE_KEY[type] || "prompts.import.allowed.types.other", { type })}
                                <span className="ml-2 font-normal text-muted-foreground">{values.length}</span>
                            </div>
                            <div className="divide-y">
                                {values.map((row) => (
                                    <div key={`${row.type}-${row.parent_value}-${row.value}`} className="flex items-start gap-3 px-3 py-2">
                                        <div className="min-w-0 flex-1">
                                            <code className="break-all text-sm font-semibold">{row.value}</code>
                                            {row.label && row.label !== row.value && <div className="text-xs text-muted-foreground">{row.label}</div>}
                                            {row.type === "Product" && row.parent_value && (
                                                <div className="text-xs text-muted-foreground">{t("prompts.import.allowed.parentTopic", { topic: row.parent_value })}</div>
                                            )}
                                            {row.notes && <div className="text-xs text-muted-foreground">{row.notes}</div>}
                                        </div>
                                        <Button
                                            type="button"
                                            variant="ghost"
                                            size="icon"
                                            aria-label={t("prompts.import.allowed.copyValue", { value: row.value })}
                                            onClick={() => void copyValue(row.value)}
                                        >
                                            {copied === row.value ? <Check className="h-4 w-4 text-emerald-600" /> : <Copy className="h-4 w-4" />}
                                        </Button>
                                    </div>
                                ))}
                            </div>
                        </section>
                    ))}
                </div>
            )}
        </div>
    );
}
