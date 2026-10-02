/**
 * TemplateDetailDialog
 *
 * Read-only detail view for a template row. Replaces the expand-in-place
 * <pre>{JSON.stringify(d)}</pre> block that used to hang off the row.
 *
 * Shows a compact summary on top (name / icon / domains / goal / platforms /
 * depth), then a formatted view of the three critical JSON fields:
 * defaults, wizard_config, default_prompt.
 *
 * Edit / Delete actions are optional — the parent page passes handlers if it
 * wants them to appear in the footer.
 */
import type { ReactNode } from "react";
import type { components } from "../api/openapi";
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
    DialogDescription,
    DialogFooter,
} from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { Badge } from "@/components/ui/badge";
import { getDomainMeta } from "../lib/domainMeta";
import { Pencil, Trash2, X } from "lucide-react";

type Mode = "analysis" | "content";
type TemplateRow = components["schemas"]["TemplateOut"];

interface DictOption {
    key: string;
    label: string;
    [k: string]: unknown;
}

interface DefaultsShape {
    goal?: string;
    content_type?: string;
    platforms?: string[];
    depth?: string;
    count?: number;
    [k: string]: unknown;
}

function parseJson(raw: unknown): Record<string, unknown> | null {
    if (!raw) return null;
    if (typeof raw === "object" && !Array.isArray(raw)) {
        return raw as Record<string, unknown>;
    }
    if (typeof raw !== "string") return null;
    try {
        const parsed: unknown = JSON.parse(raw);
        return parsed && typeof parsed === "object" && !Array.isArray(parsed)
            ? parsed as Record<string, unknown>
            : null;
    } catch {
        return null;
    }
}

interface TemplateDetailDialogProps {
    open: boolean;
    onOpenChange: (open: boolean) => void;
    template: TemplateRow | null;
    mode: Mode;
    goalOptions?: DictOption[];
    platformOptions?: DictOption[];
    depthOptions?: DictOption[];
    contentTypeOptions?: DictOption[];
    onEdit?: () => void;
    onDelete?: () => void;
}

export default function TemplateDetailDialog({
    open,
    onOpenChange,
    template,
    mode,
    goalOptions = [],
    platformOptions = [],
    depthOptions = [],
    contentTypeOptions = [],
    onEdit,
    onDelete,
}: TemplateDetailDialogProps) {
    void platformOptions;
    if (!template) return null;
    const isContent = mode === "content";

    const defaults: DefaultsShape = (parseJson(template.defaults) as DefaultsShape) || {};
    const wizardConfig: Record<string, unknown> = parseJson(template.wizard_config) || {};

    const goalLabel = goalOptions.find((g) => g.key === defaults.goal)?.label;
    const typeLabel = contentTypeOptions.find(
        (c) => c.key === defaults.content_type,
    )?.label;
    const depthLabel = depthOptions.find((x) => x.key === defaults.depth)?.label;

    return (
        <Dialog open={open} onOpenChange={onOpenChange}>
            <DialogContent className="max-w-4xl max-h-[92vh] overflow-y-auto">
                <DialogHeader>
                    <div className="flex items-start gap-4">
                        <span className="text-4xl flex-shrink-0">
                            {template.icon || (isContent ? "📋" : "📊")}
                        </span>
                        <div className="flex-1 min-w-0">
                            <DialogTitle className="text-xl flex items-center gap-2 flex-wrap">
                                {template.name}
                                {template.is_builtin && (
                                    <Badge className="text-[10px] bg-primary/10 text-primary border-primary/30">
                                        Built-in
                                    </Badge>
                                )}
                                {!template.is_active && (
                                    <Badge
                                        variant="secondary"
                                        className="text-[10px]"
                                    >
                                        Inactive
                                    </Badge>
                                )}
                            </DialogTitle>
                            <DialogDescription className="mt-1">
                                {template.description || "(no description)"}
                            </DialogDescription>
                        </div>
                    </div>
                </DialogHeader>

                <div className="space-y-5 py-2">
                    {/* Summary pills */}
                    <div className="flex gap-1.5 flex-wrap">
                        {(template.data_domains || []).map((d) => {
                            const meta = getDomainMeta(d);
                            return (
                                <span
                                    key={d}
                                    className={`text-[11px] px-2 py-1 rounded border font-medium inline-flex items-center gap-1 ${meta.color}`}
                                >
                                    <span>{meta.icon}</span>
                                    {meta.label}
                                </span>
                            );
                        })}
                        {goalLabel && (
                            <span className="text-[11px] px-2 py-1 rounded border font-medium bg-amber-500/10 text-amber-400 border-amber-500/30">
                                Goal: {goalLabel}
                            </span>
                        )}
                        {typeLabel && (
                            <span className="text-[11px] px-2 py-1 rounded border font-medium bg-pink-500/10 text-pink-400 border-pink-500/30">
                                Type: {typeLabel}
                            </span>
                        )}
                        {defaults.platforms && defaults.platforms.length > 0 && (
                            <span className="text-[11px] px-2 py-1 rounded border font-medium bg-indigo-500/10 text-indigo-400 border-indigo-500/30">
                                Platforms: {defaults.platforms.join(", ")}
                            </span>
                        )}
                        {depthLabel && (
                            <span className="text-[11px] px-2 py-1 rounded border font-medium bg-cyan-500/10 text-cyan-400 border-cyan-500/30">
                                Depth: {depthLabel}
                            </span>
                        )}
                        {defaults.count !== undefined && defaults.count > 1 && (
                            <span className="text-[11px] px-2 py-1 rounded border font-medium bg-orange-500/10 text-orange-400 border-orange-500/30">
                                Count: {defaults.count}
                            </span>
                        )}
                        <span className="text-[11px] px-2 py-1 rounded border font-medium bg-muted text-muted-foreground border-border">
                            Sort: #{template.sort_order || 0}
                        </span>
                    </div>

                    {/* Workflow Defaults */}
                    <Section label="Workflow Defaults" labelZh="默认选项 (JSON)">
                        <JsonBlock
                            value={defaults}
                            empty="No defaults configured."
                        />
                    </Section>

                    {/* Wizard Config */}
                    <Section
                        label="Wizard Config"
                        labelZh="向导契约 (required_metrics / steps ...)"
                    >
                        <JsonBlock
                            value={wizardConfig}
                            empty="No wizard config."
                        />
                    </Section>

                    {/* Prompt */}
                    <Section
                        label={isContent ? "Strategy Prompt" : "Default Prompt"}
                        labelZh={isContent ? "策略提示词" : "默认提示词"}
                    >
                        <pre className="text-xs text-foreground font-mono whitespace-pre-wrap bg-background border rounded-lg p-4 max-h-[320px] overflow-y-auto">
                            {template.default_prompt || "(empty)"}
                        </pre>
                    </Section>
                </div>

                <DialogFooter>
                    <Button
                        variant="outline"
                        onClick={() => onOpenChange(false)}
                    >
                        <X className="mr-1.5 h-3.5 w-3.5" /> Close
                    </Button>
                    {onDelete && (
                        <Button
                            variant="outline"
                            className="text-destructive hover:text-destructive hover:bg-destructive/10"
                            onClick={onDelete}
                        >
                            <Trash2 className="mr-1.5 h-3.5 w-3.5" /> Delete
                        </Button>
                    )}
                    {onEdit && (
                        <Button onClick={onEdit}>
                            <Pencil className="mr-1.5 h-3.5 w-3.5" /> Edit
                        </Button>
                    )}
                </DialogFooter>
            </DialogContent>
        </Dialog>
    );
}

interface SectionProps {
    label: string;
    labelZh?: string;
    children: ReactNode;
}

function Section({ label, labelZh, children }: SectionProps) {
    return (
        <div>
            <div className="text-xs font-semibold text-muted-foreground uppercase tracking-wider mb-2 flex items-center gap-2">
                {label}
                {labelZh && (
                    <span className="normal-case tracking-normal text-[11px] text-muted-foreground/80">
                        · {labelZh}
                    </span>
                )}
            </div>
            {children}
        </div>
    );
}

interface JsonBlockProps {
    value: Record<string, unknown> | null | undefined;
    empty: string;
}

function JsonBlock({ value, empty }: JsonBlockProps) {
    if (!value || (typeof value === "object" && Object.keys(value).length === 0)) {
        return (
            <div className="text-xs text-muted-foreground italic border border-dashed rounded-md p-3">
                {empty}
            </div>
        );
    }
    return (
        <pre className="text-xs text-foreground font-mono whitespace-pre-wrap bg-background border rounded-lg p-4 max-h-[200px] overflow-y-auto">
            {JSON.stringify(value, null, 2)}
        </pre>
    );
}
