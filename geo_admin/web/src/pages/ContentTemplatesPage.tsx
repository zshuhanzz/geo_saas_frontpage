/**
 * ContentTemplatesPage (content_generation task_type)
 *
 * List-first layout mirroring ReportTemplatesPage. Create / Edit / Details
 * are all handled by shared TemplateFormDialog and TemplateDetailDialog
 * components with mode="content". Workflow Config dictionary stays pinned
 * at the bottom.
 */
import { useState, useEffect } from "react";
import type { components } from "../api/openapi";
import { useToast, useConfirm } from "../components/Toast";
import {
    getReportTemplates,
    deleteReportTemplate,
    getWorkflowConfig,
} from "../api/client";
import WorkflowConfigManager from "../components/WorkflowConfigManager";
import TemplateFormDialog from "../components/TemplateFormDialog";
import TemplateDetailDialog from "../components/TemplateDetailDialog";
import { getDomainMeta } from "../lib/domainMeta";
import {
    getWorkflowConfigItems,
    parseWorkflowConfigValue,
    type WorkflowConfigItem,
} from "../lib/workflowConfig";
import { Button } from "@/components/ui/button";
import { Plus, Pencil, Trash2, Eye, Loader2 } from "lucide-react";

type TemplateOut = components["schemas"]["TemplateOut"];

interface ConfigOption {
    key: string;
    label: string;
    icon?: string;
    [key: string]: unknown;
}

interface TemplateDefaults {
    goal?: string;
    content_type?: string;
    depth?: string;
    platforms?: string[];
    count?: number;
    [key: string]: unknown;
}

function parseDefaults(raw: unknown): TemplateDefaults {
    if (!raw) return {};
    if (typeof raw === "object") return raw as TemplateDefaults;
    if (typeof raw === "string") {
        try {
            return JSON.parse(raw) as TemplateDefaults;
        } catch {
            return {};
        }
    }
    return {};
}

export default function ContentTemplatesPage() {
    const toast = useToast();
    const confirm = useConfirm();

    const [templates, setTemplates] = useState<TemplateOut[]>([]);
    const [loading, setLoading] = useState<boolean>(true);

    const [formOpen, setFormOpen] = useState<boolean>(false);
    const [formTemplate, setFormTemplate] = useState<TemplateOut | null>(null);
    const [detailOpen, setDetailOpen] = useState<boolean>(false);
    const [detailTemplate, setDetailTemplate] = useState<TemplateOut | null>(null);

    const [goalOptions, setGoalOptions] = useState<ConfigOption[]>([]);
    const [contentTypeOptions, setContentTypeOptions] = useState<ConfigOption[]>([]);
    const [platformOptions, setPlatformOptions] = useState<ConfigOption[]>([]);
    const [depthOptions, setDepthOptions] = useState<ConfigOption[]>([]);

    useEffect(() => {
        loadTemplates();
        loadConfig();
    }, []);

    async function loadTemplates(): Promise<void> {
        setLoading(true);
        try {
            const resp = await getReportTemplates("content_generation");
            setTemplates(resp?.data || []);
        } catch (err) {
            toast.error((err as Error).message);
        } finally {
            setLoading(false);
        }
    }

    async function loadConfig(): Promise<void> {
        try {
            const config = await getWorkflowConfig("content_generation");
            const toOption = (item: WorkflowConfigItem): ConfigOption => {
                const parsed = parseWorkflowConfigValue(item.value);
                return {
                    ...parsed,
                    key: item.key,
                    label: typeof parsed.label === "string" ? parsed.label : item.key,
                };
            };
            setGoalOptions(getWorkflowConfigItems(config, "goal").map(toOption));
            setContentTypeOptions(getWorkflowConfigItems(config, "content_type").map(toOption));
            setPlatformOptions(getWorkflowConfigItems(config, "platform").map(toOption));
            setDepthOptions(getWorkflowConfigItems(config, "depth").map(toOption));
        } catch {
            setGoalOptions([
                { key: "visibility_boost", label: "可见度提升" },
                { key: "citation_optimize", label: "引用优化" },
                { key: "sentiment_repair", label: "情绪修复" },
                { key: "full_optimize", label: "全面内容优化" },
            ]);
            setContentTypeOptions([
                { key: "faq", label: "FAQ 内容", icon: "📋" },
                { key: "aeo_article", label: "AEO 文章", icon: "🤖" },
                { key: "article", label: "SEO 文章", icon: "✍️" },
                { key: "recommendations", label: "优化建议", icon: "💡" },
                { key: "brief", label: "Content Brief", icon: "📝" },
            ]);
            setPlatformOptions([
                { key: "chatgpt", label: "ChatGPT", icon: "🤖" },
                { key: "gemini", label: "Gemini", icon: "✨" },
                { key: "aimode", label: "AI Mode", icon: "🔍" },
                { key: "perplexity", label: "Perplexity", icon: "🔎" },
                { key: "aioverview", label: "AI Overview", icon: "🌐" },
            ]);
            setDepthOptions([
                { key: "quick", label: "快速生成" },
                { key: "standard", label: "标准生成" },
                { key: "deep", label: "深度优化" },
            ]);
        }
    }

    function openCreate(): void {
        setFormTemplate(null);
        setFormOpen(true);
    }
    function openEdit(t: TemplateOut): void {
        setFormTemplate(t);
        setFormOpen(true);
    }
    function openDetail(t: TemplateOut): void {
        setDetailTemplate(t);
        setDetailOpen(true);
    }

    async function handleDelete(t: TemplateOut): Promise<void> {
        const ok = await confirm(
            `Delete template "${t.name}"?`,
            "Delete Template",
        );
        if (!ok) return;
        try {
            await deleteReportTemplate(String(t.id));
            toast.success("Deleted");
            if (detailTemplate?.id === t.id) setDetailOpen(false);
            if (formTemplate?.id === t.id) setFormOpen(false);
            loadTemplates();
        } catch (err) {
            toast.error((err as Error).message);
        }
    }

    return (
        <div className="space-y-6">
            {/* Header */}
            <div className="flex items-start justify-between gap-4">
                <div>
                    <h1 className="text-3xl font-bold text-foreground">
                        Content Templates
                    </h1>
                    <p className="text-muted-foreground mt-1">
                        Manage content generation templates. Click a row to see
                        details, or the Add button to create a new one.
                    </p>
                </div>
                <Button onClick={openCreate} className="gap-1.5 flex-shrink-0">
                    <Plus className="h-4 w-4" />
                    Add Template
                </Button>
            </div>

            {/* List */}
            {loading ? (
                <div className="flex items-center justify-center py-16">
                    <Loader2 className="h-8 w-8 animate-spin text-muted-foreground" />
                </div>
            ) : templates.length === 0 ? (
                <div className="py-16 text-center border rounded-xl border-dashed">
                    <p className="text-sm text-muted-foreground">
                        No content templates yet.
                    </p>
                    <Button
                        variant="outline"
                        onClick={openCreate}
                        className="mt-4 gap-1.5"
                    >
                        <Plus className="h-4 w-4" /> Create your first template
                    </Button>
                </div>
            ) : (
                <div className="space-y-3">
                    {templates.map((t) => {
                        const d = parseDefaults(t.defaults);
                        const goalLabel = goalOptions.find(
                            (g) => g.key === d.goal,
                        )?.label;
                        const typeLabel = contentTypeOptions.find(
                            (c) => c.key === d.content_type,
                        )?.label;
                        const depthLabel = depthOptions.find(
                            (x) => x.key === d.depth,
                        )?.label;
                        return (
                            <div
                                key={String(t.id)}
                                className="bg-card border rounded-xl shadow-sm hover:border-primary/40 transition-colors cursor-pointer group"
                                onClick={() => openDetail(t)}
                            >
                                <div className="flex items-center gap-4 px-5 py-4">
                                    <span className="text-2xl flex-shrink-0">
                                        {t.icon || "📋"}
                                    </span>
                                    <div className="flex-1 min-w-0">
                                        <div className="flex items-center gap-2 flex-wrap">
                                            <span className="font-semibold text-foreground">
                                                {t.name}
                                            </span>
                                            {t.is_builtin && (
                                                <span className="text-[10px] px-1.5 py-0.5 rounded bg-primary/10 text-primary font-medium">
                                                    Built-in
                                                </span>
                                            )}
                                            {!t.is_active && (
                                                <span className="text-[10px] px-1.5 py-0.5 rounded bg-muted text-muted-foreground font-medium">
                                                    Inactive
                                                </span>
                                            )}
                                        </div>
                                        <div className="flex gap-1.5 mt-1.5 flex-wrap">
                                            {(t.data_domains || []).map((dm: string) => {
                                                const meta = getDomainMeta(dm);
                                                return (
                                                    <span
                                                        key={dm}
                                                        className={`text-[10px] px-1.5 py-0.5 rounded border font-medium inline-flex items-center gap-0.5 ${meta.color}`}
                                                    >
                                                        <span>{meta.icon}</span>
                                                        {meta.label}
                                                    </span>
                                                );
                                            })}
                                            {goalLabel && (
                                                <span className="text-[10px] px-1.5 py-0.5 rounded border bg-amber-500/10 text-amber-400 border-amber-500/30 font-medium">
                                                    Goal: {goalLabel}
                                                </span>
                                            )}
                                            {typeLabel && (
                                                <span className="text-[10px] px-1.5 py-0.5 rounded border bg-pink-500/10 text-pink-400 border-pink-500/30 font-medium">
                                                    Type: {typeLabel}
                                                </span>
                                            )}
                                            {d.platforms?.length > 0 && (
                                                <span className="text-[10px] px-1.5 py-0.5 rounded border bg-indigo-500/10 text-indigo-400 border-indigo-500/30 font-medium">
                                                    {d.platforms.join(", ")}
                                                </span>
                                            )}
                                            {depthLabel && d.depth !== "standard" && (
                                                <span className="text-[10px] px-1.5 py-0.5 rounded border bg-cyan-500/10 text-cyan-400 border-cyan-500/30 font-medium">
                                                    {depthLabel}
                                                </span>
                                            )}
                                            {d.count > 1 && (
                                                <span className="text-[10px] px-1.5 py-0.5 rounded border bg-orange-500/10 text-orange-400 border-orange-500/30 font-medium">
                                                    Count: {d.count}
                                                </span>
                                            )}
                                        </div>
                                        {t.description && (
                                            <p className="text-xs text-muted-foreground mt-1 line-clamp-1">
                                                {t.description}
                                            </p>
                                        )}
                                    </div>
                                    <div
                                        className="flex items-center gap-1 flex-shrink-0 opacity-0 group-hover:opacity-100 transition-opacity"
                                        onClick={(e: React.MouseEvent<HTMLDivElement>) => e.stopPropagation()}
                                    >
                                        <button
                                            type="button"
                                            className="p-2 rounded-md hover:bg-muted hover:text-foreground text-muted-foreground"
                                            title="Details"
                                            onClick={() => openDetail(t)}
                                        >
                                            <Eye className="h-4 w-4" />
                                        </button>
                                        <button
                                            type="button"
                                            className="p-2 rounded-md hover:bg-blue-500/10 text-blue-400 hover:text-blue-300"
                                            title="Edit"
                                            onClick={() => openEdit(t)}
                                        >
                                            <Pencil className="h-4 w-4" />
                                        </button>
                                        <button
                                            type="button"
                                            className="p-2 rounded-md hover:bg-destructive/10 text-red-400 hover:text-red-300"
                                            title="Delete"
                                            onClick={() => handleDelete(t)}
                                        >
                                            <Trash2 className="h-4 w-4" />
                                        </button>
                                    </div>
                                </div>
                            </div>
                        );
                    })}
                </div>
            )}

            {/* Workflow Config Manager (bottom section) */}
            <WorkflowConfigManager
                scope="content_generation"
                onConfigChange={loadConfig}
            />

            {/* Dialogs */}
            <TemplateFormDialog
                open={formOpen}
                onOpenChange={setFormOpen}
                mode="content"
                template={formTemplate}
                goalOptions={goalOptions}
                platformOptions={platformOptions}
                depthOptions={depthOptions}
                contentTypeOptions={contentTypeOptions}
                onSaved={() => {
                    loadTemplates();
                }}
            />
            <TemplateDetailDialog
                open={detailOpen}
                onOpenChange={setDetailOpen}
                template={detailTemplate}
                mode="content"
                goalOptions={goalOptions}
                platformOptions={platformOptions}
                depthOptions={depthOptions}
                contentTypeOptions={contentTypeOptions}
                onEdit={() => {
                    setDetailOpen(false);
                    setFormTemplate(detailTemplate);
                    setFormOpen(true);
                }}
                onDelete={() => {
                    if (detailTemplate) handleDelete(detailTemplate);
                }}
            />
        </div>
    );
}
