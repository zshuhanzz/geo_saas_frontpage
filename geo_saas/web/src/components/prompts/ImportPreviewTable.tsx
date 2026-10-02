import { ChevronDown, ChevronLeft, ChevronRight } from "lucide-react";
import { useTranslation } from "react-i18next";

import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import type { PromptImportAction, PromptImportPreviewRow, PromptImportVariant } from "@/lib/api/prompts";
import { describePromptImportIssue } from "@/lib/promptImport";
import { lazyPromptImportVariants, paginatePromptImportRows } from "./promptImportViewModel";

const ACTION_VARIANT: Record<PromptImportAction, "default" | "secondary" | "destructive" | "outline"> = {
    create: "default",
    skip: "secondary",
    conflict: "destructive",
    invalid: "destructive",
};

const PREVIEW_PAGE_SIZE = 20;

interface ImportPreviewTableProps {
    rows: readonly PromptImportPreviewRow[];
    page: number;
    onPageChange: (page: number) => void;
    expandedRowNumber: number | null;
    onExpandedRowChange: (rowNumber: number | null) => void;
}

export function ImportPreviewTable({
    rows,
    page,
    onPageChange,
    expandedRowNumber,
    onExpandedRowChange,
}: ImportPreviewTableProps) {
    const { t } = useTranslation(["insights", "common"]);
    const pageState = paginatePromptImportRows(rows, page, PREVIEW_PAGE_SIZE);
    const issueText = (issue: PromptImportPreviewRow["errors"][number]) => {
        const descriptor = describePromptImportIssue(issue);
        return t(descriptor.key, descriptor.values);
    };

    if (rows.length === 0) {
        return <div className="rounded-md border p-6 text-center text-sm text-muted-foreground">{t("prompts.import.preview.empty")}</div>;
    }

    return (
        <div className="rounded-md border">
            <div className="max-h-[360px] overflow-auto">
            <Table>
                <TableHeader className="sticky top-0 z-10 bg-background">
                    <TableRow>
                        <TableHead className="w-16">{t("prompts.import.preview.columns.row")}</TableHead>
                        <TableHead>{t("prompts.import.preview.columns.normalized")}</TableHead>
                        <TableHead className="w-24 text-right">{t("prompts.import.preview.columns.expanded")}</TableHead>
                        <TableHead className="w-24">{t("prompts.import.preview.columns.action")}</TableHead>
                        <TableHead>{t("prompts.import.preview.columns.feedback")}</TableHead>
                    </TableRow>
                </TableHeader>
                <TableBody>
                    {pageState.rows.map((row) => {
                        const visibleVariants = lazyPromptImportVariants<PromptImportVariant, PromptImportPreviewRow>(row, expandedRowNumber);
                        const expanded = row.row_number === expandedRowNumber;
                        return (
                        <TableRow key={row.row_number} className="align-top">
                            <TableCell className="font-mono text-xs">{row.row_number}</TableCell>
                            <TableCell className="min-w-[280px]">
                                <div className="font-medium">{row.prompt || t("prompts.import.preview.missingValue")}</div>
                                <div className="mt-1 text-xs text-muted-foreground">
                                    {[row.topic, row.product, row.intent, row.language].filter(Boolean).join(" · ")}
                                </div>
                                <div className="mt-1 text-xs text-muted-foreground">
                                    {(row.platforms || []).join(" | ")} / {(row.countries || []).join(" | ")}
                                </div>
                                {(row.variants || []).length > 0 && (
                                    <div className="mt-2 text-xs">
                                        <Button
                                            type="button"
                                            variant="ghost"
                                            size="sm"
                                            className="h-7 px-1 text-primary"
                                            aria-expanded={expanded}
                                            onClick={() => onExpandedRowChange(expanded ? null : row.row_number)}
                                        >
                                            {expanded ? <ChevronDown className="mr-1 h-3.5 w-3.5" /> : <ChevronRight className="mr-1 h-3.5 w-3.5" />}
                                            {t("prompts.import.preview.variants", { count: row.variants.length })}
                                        </Button>
                                        {expanded && (
                                        <ul className="mt-1 space-y-1 pl-4 text-muted-foreground">
                                            {visibleVariants.map((variant, index) => (
                                                <li key={`${variant.platform}-${variant.country}-${variant.language}-${index}`}>
                                                    {variant.platform} · {variant.country} · {variant.language} · {t(`prompts.import.actions.${variant.action}`)}
                                                </li>
                                            ))}
                                        </ul>
                                        )}
                                    </div>
                                )}
                            </TableCell>
                            <TableCell className="text-right tabular-nums">{row.expanded_count ?? row.variants?.length ?? 0}</TableCell>
                            <TableCell>
                                <Badge variant={ACTION_VARIANT[row.action]}>{t(`prompts.import.actions.${row.action}`)}</Badge>
                            </TableCell>
                            <TableCell className="min-w-[260px]">
                                {row.errors?.map((issue, index) => (
                                    <div key={`error-${issue.code}-${index}`} className="mb-1 text-xs text-destructive">
                                        {issueText(issue)}
                                    </div>
                                ))}
                                {row.warnings?.map((issue, index) => (
                                    <div key={`warning-${issue.code}-${index}`} className="mb-1 text-xs text-amber-600 dark:text-amber-400">
                                        {issueText(issue)}
                                    </div>
                                ))}
                                {!row.errors?.length && !row.warnings?.length && (
                                    <span className="text-xs text-muted-foreground">{t("prompts.import.preview.noIssues")}</span>
                                )}
                            </TableCell>
                        </TableRow>
                        );
                    })}
                </TableBody>
            </Table>
            </div>
            {pageState.pageCount > 1 && (
                <div className="flex items-center justify-between border-t px-3 py-2">
                    <span className="text-xs text-muted-foreground">
                        {t("prompts.import.preview.page", { page: pageState.page + 1, count: pageState.pageCount })}
                    </span>
                    <div className="flex gap-1">
                        <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            disabled={pageState.page === 0}
                            onClick={() => onPageChange(pageState.page - 1)}
                        >
                            <ChevronLeft className="mr-1 h-4 w-4" />{t("common:actions.back")}
                        </Button>
                        <Button
                            type="button"
                            variant="outline"
                            size="sm"
                            disabled={pageState.page >= pageState.pageCount - 1}
                            onClick={() => onPageChange(pageState.page + 1)}
                        >
                            {t("common:actions.next")}<ChevronRight className="ml-1 h-4 w-4" />
                        </Button>
                    </div>
                </div>
            )}
        </div>
    );
}
