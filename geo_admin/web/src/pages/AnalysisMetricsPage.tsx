import { useState, useEffect } from "react";
import type { components } from "../api/openapi";
import { useToast, useConfirm } from "../components/Toast";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Textarea } from "@/components/ui/textarea";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import {
    Dialog,
    DialogContent,
    DialogHeader,
    DialogTitle,
    DialogFooter,
    DialogDescription,
} from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import {
    Select,
    SelectContent,
    SelectItem,
    SelectTrigger,
    SelectValue,
} from "@/components/ui/select";
import { Checkbox } from "@/components/ui/checkbox";
import { Switch } from "@/components/ui/switch";
import {
    Ruler,
    Plus,
    Pencil,
    Trash2,
    Loader2,
    Search,
    AlertTriangle,
} from "lucide-react";
import { getDomainMeta } from "../lib/domainMeta";
import {
    createAnalysisMetric,
    deleteAnalysisMetric,
    getAnalysisMetricSchemaTables,
    getAnalysisMetrics,
    updateAnalysisMetric,
} from "../api/client";

type MetricOut = components["schemas"]["routers__analysis_metrics__MetricOut"];
type MetricListOut = components["schemas"]["MetricListOut"];

interface MetricFilters {
    domain?: string;
    is_active?: string;
    q?: string;
}

interface MetricForm {
    metric_name: string;
    display_name_zh: string;
    display_name_en: string;
    domain: string;
    description: string;
    calculation_hint: string;
    relevant_tables: string[];
    sample_question: string;
    null_behavior: string;
    unit: string;
    is_active: boolean;
    sort_order: number;
}

interface MetricDeleteRefDetail {
    message: string;
    references: Array<{ name: string }>;
}

// ─── API helpers ─────────────────────────────────────────────────────

async function fetchMetrics(params: MetricFilters = {}): Promise<MetricListOut> {
    return getAnalysisMetrics(params);
}

async function fetchSchemaTables(): Promise<string[]> {
    return getAnalysisMetricSchemaTables();
}

async function createMetric(data: MetricForm): Promise<MetricOut> {
    return createAnalysisMetric(data);
}

async function updateMetric(id: string, data: Partial<MetricForm>): Promise<MetricOut> {
    return updateAnalysisMetric(id, data);
}

async function deleteMetric(id: string): Promise<true> {
    try {
        await deleteAnalysisMetric(id);
    } catch (error) {
        const detail = (error as { detail?: unknown }).detail;
        if (detail && typeof detail === "object" && (detail as MetricDeleteRefDetail).references) {
            const refDetail = detail as MetricDeleteRefDetail;
            const names = refDetail.references.map((r) => r.name).join("、");
            throw new Error(`${refDetail.message}\n\n引用方：${names}`);
        }
        throw error;
    }
    return true;
}

// ─── Constants ───────────────────────────────────────────────────────

interface DomainOption {
    value: string;
    label: string;
}

const DOMAIN_OPTIONS: DomainOption[] = [
    { value: "visibility", label: "可见度 (Visibility)" },
    { value: "citation", label: "引用 (Citation)" },
    { value: "sentiment", label: "情感 (Sentiment)" },
    { value: "custom", label: "自定义 (Custom)" },
];

const NULL_BEHAVIOR_OPTIONS: DomainOption[] = [
    { value: "return_null", label: "返回 NULL（推荐）" },
    { value: "return_zero", label: "返回 0" },
    { value: "raise", label: "抛出错误" },
];

const DEFAULT_FORM: MetricForm = {
    metric_name: "",
    display_name_zh: "",
    display_name_en: "",
    domain: "visibility",
    description: "",
    calculation_hint: "",
    relevant_tables: [],
    sample_question: "",
    null_behavior: "return_null",
    unit: "",
    is_active: true,
    sort_order: 0,
};

// ─── Page component ──────────────────────────────────────────────────

export default function AnalysisMetricsPage() {
    const [metrics, setMetrics] = useState<MetricOut[]>([]);
    const [loading, setLoading] = useState<boolean>(true);
    const [schemaTables, setSchemaTables] = useState<string[]>([]);

    const [filterDomain, setFilterDomain] = useState<string>("all");
    const [filterActive, setFilterActive] = useState<string>("all");
    const [search, setSearch] = useState<string>("");

    const [showDialog, setShowDialog] = useState<boolean>(false);
    const [editing, setEditing] = useState<MetricOut | null>(null);
    const [form, setForm] = useState<MetricForm>(DEFAULT_FORM);
    const [saving, setSaving] = useState<boolean>(false);

    const toast = useToast();
    const confirm = useConfirm();

    useEffect(() => {
        load();
        fetchSchemaTables()
            .then(setSchemaTables)
            .catch((e) => console.error(e));
    }, []);

    useEffect(() => {
        load();
        // eslint-disable-next-line react-hooks/exhaustive-deps
    }, [filterDomain, filterActive, search]);

    async function load(): Promise<void> {
        setLoading(true);
        try {
            const params: MetricFilters = {};
            if (filterDomain !== "all") params.domain = filterDomain;
            if (filterActive === "active") params.is_active = "true";
            if (filterActive === "inactive") params.is_active = "false";
            if (search.trim()) params.q = search.trim();
            const data = await fetchMetrics(params);
            setMetrics(data.data || []);
        } catch (err) {
            toast.error((err as Error).message);
        } finally {
            setLoading(false);
        }
    }

    function openCreate(): void {
        setEditing(null);
        setForm({ ...DEFAULT_FORM });
        setShowDialog(true);
    }

    function openEdit(m: MetricOut): void {
        setEditing(m);
        setForm({
            metric_name: m.metric_name,
            display_name_zh: m.display_name_zh || "",
            display_name_en: m.display_name_en || "",
            domain: m.domain || "visibility",
            description: m.description || "",
            calculation_hint: m.calculation_hint || "",
            relevant_tables: Array.isArray(m.relevant_tables) ? m.relevant_tables : [],
            sample_question: m.sample_question || "",
            null_behavior: m.null_behavior || "return_null",
            unit: m.unit || "",
            is_active: m.is_active !== false,
            sort_order: m.sort_order || 0,
        });
        setShowDialog(true);
    }

    async function handleSave(): Promise<void> {
        // Client-side validation — keep messages in Chinese to match the UI.
        if (!form.metric_name.trim()) {
            toast.error("metric_name 不能为空");
            return;
        }
        if (!/^[a-z][a-z0-9_]*$/.test(form.metric_name)) {
            toast.error("metric_name 只能包含小写字母、数字、下划线，且以字母开头");
            return;
        }
        if (!form.display_name_zh.trim()) {
            toast.error("中文显示名不能为空");
            return;
        }
        if (!form.description.trim() || !form.calculation_hint.trim()) {
            toast.error("description 和 calculation_hint 都是必填");
            return;
        }

        setSaving(true);
        try {
            if (editing) {
                const { metric_name: _ignored, ...updateBody } = form;
                await updateMetric(editing.id, updateBody);
                toast.success("指标已更新");
            } else {
                await createMetric(form);
                toast.success("指标已创建");
            }
            setShowDialog(false);
            load();
        } catch (err) {
            toast.error((err as Error).message);
        } finally {
            setSaving(false);
        }
    }

    async function handleDelete(m: MetricOut): Promise<void> {
        const ok = await confirm(
            `确认删除指标 "${m.display_name_zh}" (${m.metric_name})？\n\n如果有任何模板的 wizard_config.required_metrics 引用了它，删除会被拒绝。`,
            "删除指标",
        );
        if (!ok) return;
        try {
            await deleteMetric(m.id);
            toast.success("指标已删除");
            load();
        } catch (err) {
            toast.error((err as Error).message);
        }
    }

    function toggleTable(table: string): void {
        setForm((f) => {
            const exists = f.relevant_tables.includes(table);
            return {
                ...f,
                relevant_tables: exists
                    ? f.relevant_tables.filter((t) => t !== table)
                    : [...f.relevant_tables, table],
            };
        });
    }

    return (
        <div className="space-y-6">
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-3xl font-bold tracking-tight text-foreground">Analysis Metrics</h1>
                    <p className="mt-2 text-sm text-muted-foreground">
                        管理 Analyze Agent 的指标注册表。每一行定义一个指标的 NL2SQL 提示
                        （description + calculation_hint）与可用表集合，供
                        Template × Wizard 2D 契约模式调用。
                    </p>
                </div>
                <Button onClick={openCreate}>
                    <Plus className="mr-2 h-4 w-4" /> 新增指标
                </Button>
            </div>

            <Card>
                <CardHeader className="pb-3">
                    <CardTitle className="text-lg font-semibold flex items-center">
                        <Ruler className="mr-2 h-5 w-5 text-primary" />
                        Metric Registry
                        <Badge variant="secondary" className="ml-2">
                            {metrics.length}
                        </Badge>
                    </CardTitle>

                    <div className="mt-4 flex flex-wrap items-center gap-3">
                        <div className="relative flex-1 min-w-[220px] max-w-sm">
                            <Search className="absolute left-3 top-1/2 -translate-y-1/2 h-4 w-4 text-muted-foreground" />
                            <Input
                                className="pl-9"
                                placeholder="搜索 metric_name / 显示名"
                                value={search}
                                onChange={(e: React.ChangeEvent<HTMLInputElement>) => setSearch(e.target.value)}
                            />
                        </div>
                        <Select value={filterDomain} onValueChange={setFilterDomain}>
                            <SelectTrigger className="w-[180px]">
                                <SelectValue placeholder="领域" />
                            </SelectTrigger>
                            <SelectContent>
                                <SelectItem value="all">全部领域</SelectItem>
                                {DOMAIN_OPTIONS.map((opt) => (
                                    <SelectItem key={opt.value} value={opt.value}>
                                        {opt.label}
                                    </SelectItem>
                                ))}
                            </SelectContent>
                        </Select>
                        <Select value={filterActive} onValueChange={setFilterActive}>
                            <SelectTrigger className="w-[160px]">
                                <SelectValue placeholder="状态" />
                            </SelectTrigger>
                            <SelectContent>
                                <SelectItem value="all">全部状态</SelectItem>
                                <SelectItem value="active">Active</SelectItem>
                                <SelectItem value="inactive">Inactive</SelectItem>
                            </SelectContent>
                        </Select>
                    </div>
                </CardHeader>
                <CardContent>
                    {loading ? (
                        <div className="flex justify-center py-12">
                            <Loader2 className="h-6 w-6 animate-spin text-muted-foreground" />
                        </div>
                    ) : (
                        <div className="border rounded-lg overflow-hidden">
                            <Table>
                                <TableHeader>
                                    <TableRow>
                                        <TableHead>metric_name</TableHead>
                                        <TableHead>显示名</TableHead>
                                        <TableHead>领域</TableHead>
                                        <TableHead>相关表</TableHead>
                                        <TableHead>单位</TableHead>
                                        <TableHead>状态</TableHead>
                                        <TableHead className="text-right">操作</TableHead>
                                    </TableRow>
                                </TableHeader>
                                <TableBody>
                                    {metrics.map((m) => (
                                        <TableRow key={m.id}>
                                            <TableCell className="font-mono text-xs">{m.metric_name}</TableCell>
                                            <TableCell>
                                                <div className="font-medium">{m.display_name_zh}</div>
                                                {m.display_name_en && (
                                                    <div className="text-xs text-muted-foreground">
                                                        {m.display_name_en}
                                                    </div>
                                                )}
                                            </TableCell>
                                            <TableCell>
                                                {(() => {
                                                    const meta = getDomainMeta(m.domain);
                                                    return (
                                                        <span
                                                            className={`inline-flex items-center gap-1 px-2 py-0.5 rounded border text-[11px] font-medium ${meta.color}`}
                                                        >
                                                            <span>{meta.icon}</span>
                                                            {meta.label}
                                                        </span>
                                                    );
                                                })()}
                                            </TableCell>
                                            <TableCell>
                                                <div className="flex flex-wrap gap-1 max-w-[260px]">
                                                    {(m.relevant_tables || []).map((t: string) => (
                                                        <Badge
                                                            key={t}
                                                            variant="outline"
                                                            className="font-mono text-[10px] px-1.5 py-0"
                                                        >
                                                            {t}
                                                        </Badge>
                                                    ))}
                                                </div>
                                            </TableCell>
                                            <TableCell className="text-xs">{m.unit || "—"}</TableCell>
                                            <TableCell>
                                                <Badge variant={m.is_active ? "default" : "secondary"}>
                                                    {m.is_active ? "Active" : "Inactive"}
                                                </Badge>
                                            </TableCell>
                                            <TableCell className="text-right">
                                                <Button variant="ghost" size="sm" onClick={() => openEdit(m)}>
                                                    <Pencil className="h-4 w-4" />
                                                </Button>
                                                <Button
                                                    variant="ghost"
                                                    size="sm"
                                                    onClick={() => handleDelete(m)}
                                                    className="text-destructive"
                                                >
                                                    <Trash2 className="h-4 w-4" />
                                                </Button>
                                            </TableCell>
                                        </TableRow>
                                    ))}
                                    {metrics.length === 0 && (
                                        <TableRow>
                                            <TableCell
                                                colSpan={7}
                                                className="text-center py-10 text-muted-foreground"
                                            >
                                                暂无指标。点击"新增指标"开始添加，或先运行 migration 026 载入种子数据。
                                            </TableCell>
                                        </TableRow>
                                    )}
                                </TableBody>
                            </Table>
                        </div>
                    )}
                </CardContent>
            </Card>

            {/* ─── Create / Edit Dialog ─── */}
            <Dialog open={showDialog} onOpenChange={setShowDialog}>
                <DialogContent className="max-w-2xl max-h-[90vh] overflow-y-auto">
                    <DialogHeader>
                        <DialogTitle>{editing ? "编辑指标" : "新增指标"}</DialogTitle>
                        <DialogDescription>
                            ⚠️ <strong>metric_name</strong> 一经创建不可修改，它是 wizard_config
                            契约引用的稳定 ID。要"改名"请新建一个再删除旧行。
                        </DialogDescription>
                    </DialogHeader>

                    <div className="space-y-5">
                        <div className="grid grid-cols-2 gap-4">
                            <div className="space-y-2">
                                <Label>metric_name *</Label>
                                <Input
                                    placeholder="例如 sov_trend"
                                    value={form.metric_name}
                                    disabled={!!editing}
                                    onChange={(e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, metric_name: e.target.value })}
                                    className="font-mono"
                                />
                            </div>
                            <div className="space-y-2">
                                <Label>领域 *</Label>
                                <Select
                                    value={form.domain}
                                    onValueChange={(v: string) => setForm({ ...form, domain: v })}
                                >
                                    <SelectTrigger>
                                        <SelectValue />
                                    </SelectTrigger>
                                    <SelectContent>
                                        {DOMAIN_OPTIONS.map((opt) => (
                                            <SelectItem key={opt.value} value={opt.value}>
                                                {opt.label}
                                            </SelectItem>
                                        ))}
                                    </SelectContent>
                                </Select>
                            </div>
                        </div>

                        <div className="grid grid-cols-2 gap-4">
                            <div className="space-y-2">
                                <Label>中文显示名 *</Label>
                                <Input
                                    placeholder="例如 Share of Voice 趋势"
                                    value={form.display_name_zh}
                                    onChange={(e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, display_name_zh: e.target.value })}
                                />
                            </div>
                            <div className="space-y-2">
                                <Label>英文显示名</Label>
                                <Input
                                    placeholder="例如 SOV Trend"
                                    value={form.display_name_en}
                                    onChange={(e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, display_name_en: e.target.value })}
                                />
                            </div>
                        </div>

                        <div className="space-y-2">
                            <Label>description *（给人看的简短描述）</Label>
                            <Textarea
                                rows={2}
                                placeholder="一句话概括这个指标是什么、回答什么问题"
                                value={form.description}
                                onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => setForm({ ...form, description: e.target.value })}
                            />
                        </div>

                        <div className="space-y-2">
                            <Label className="flex items-center gap-2">
                                calculation_hint *（给 NL2SQL 看的计算提示）
                                <AlertTriangle className="h-3.5 w-3.5 text-yellow-500" />
                            </Label>
                            <Textarea
                                rows={5}
                                placeholder="描述 SQL 应该怎么算：用哪些表、怎么 JOIN、分子分母是什么、返回什么形状..."
                                value={form.calculation_hint}
                                onChange={(e: React.ChangeEvent<HTMLTextAreaElement>) => setForm({ ...form, calculation_hint: e.target.value })}
                                className="font-mono text-xs"
                            />
                            <p className="text-[11px] text-muted-foreground">
                                这段话会直接塞进 Gemini 的 SQL 生成提示里作为 metric description，
                                越具体越可靠。
                            </p>
                        </div>

                        <div className="space-y-2">
                            <Label>relevant_tables（多选）</Label>
                            <div className="border rounded-md p-3 max-h-48 overflow-y-auto space-y-1.5">
                                {schemaTables.length === 0 ? (
                                    <div className="text-xs text-muted-foreground py-2">
                                        未加载到 schema 表（检查 /api/analysis/metrics/schema-tables）
                                    </div>
                                ) : (
                                    schemaTables.map((t: string) => (
                                        <label
                                            key={t}
                                            className="flex items-center gap-2 cursor-pointer hover:bg-accent/40 px-1.5 py-1 rounded text-xs"
                                        >
                                            <Checkbox
                                                checked={form.relevant_tables.includes(t)}
                                                onCheckedChange={() => toggleTable(t)}
                                            />
                                            <span className="font-mono">{t}</span>
                                        </label>
                                    ))
                                )}
                            </div>
                            {form.relevant_tables.length > 0 && (
                                <div className="flex flex-wrap gap-1 pt-1">
                                    {form.relevant_tables.map((t: string) => (
                                        <Badge key={t} variant="outline" className="font-mono text-[10px]">
                                            {t}
                                        </Badge>
                                    ))}
                                </div>
                            )}
                        </div>

                        <div className="grid grid-cols-3 gap-4">
                            <div className="space-y-2">
                                <Label>null_behavior</Label>
                                <Select
                                    value={form.null_behavior}
                                    onValueChange={(v: string) => setForm({ ...form, null_behavior: v })}
                                >
                                    <SelectTrigger>
                                        <SelectValue />
                                    </SelectTrigger>
                                    <SelectContent>
                                        {NULL_BEHAVIOR_OPTIONS.map((opt) => (
                                            <SelectItem key={opt.value} value={opt.value}>
                                                {opt.label}
                                            </SelectItem>
                                        ))}
                                    </SelectContent>
                                </Select>
                            </div>
                            <div className="space-y-2">
                                <Label>单位</Label>
                                <Input
                                    placeholder="%, count, ..."
                                    value={form.unit}
                                    onChange={(e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, unit: e.target.value })}
                                />
                            </div>
                            <div className="space-y-2">
                                <Label>sort_order</Label>
                                <Input
                                    type="number"
                                    value={form.sort_order}
                                    onChange={(e: React.ChangeEvent<HTMLInputElement>) =>
                                        setForm({ ...form, sort_order: parseInt(e.target.value, 10) || 0 })
                                    }
                                />
                            </div>
                        </div>

                        <div className="space-y-2">
                            <Label>sample_question（可选，给用户展示的自然语言示例）</Label>
                            <Input
                                placeholder="例如:我的品牌最近 30 天在 Gemini 上的 SOV 趋势如何？"
                                value={form.sample_question}
                                onChange={(e: React.ChangeEvent<HTMLInputElement>) => setForm({ ...form, sample_question: e.target.value })}
                            />
                        </div>

                        <div className="flex items-center justify-between border-t pt-3">
                            <Label className="flex items-center gap-2">
                                启用该指标
                                <span className="text-xs text-muted-foreground">
                                    (inactive 的指标不会被契约模式选中)
                                </span>
                            </Label>
                            <Switch
                                checked={form.is_active}
                                onCheckedChange={(v: boolean) => setForm({ ...form, is_active: v })}
                            />
                        </div>
                    </div>

                    <DialogFooter>
                        <Button variant="outline" onClick={() => setShowDialog(false)}>
                            取消
                        </Button>
                        <Button onClick={handleSave} disabled={saving}>
                            {saving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                            {editing ? "保存修改" : "创建"}
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </div>
    );
}
