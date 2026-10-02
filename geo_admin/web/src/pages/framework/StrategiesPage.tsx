import { useState, useEffect, useCallback } from "react";
import { useToast, useConfirm } from "../../components/Toast";
import { getMetrics, getSubgoals, getStrategies, createStrategy, updateStrategy, deleteStrategy } from "../../api/client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import { Lightbulb, Plus, Pencil, Trash2, Loader2, Filter, ChevronDown, ChevronUp } from "lucide-react";

const GENERATION_METHODS = [
  { value: "llm_with_postprocess", label: "LLM + Post-process" },
  { value: "llm_only", label: "LLM Only" },
  { value: "template", label: "Template" },
  { value: "manual", label: "Manual" },
];

const EMPTY_FORM = {
  name: "",
  description: "",
  dimensions: "{}",
  source_metrics: [],
  source_subgoals: [],
  content_type: "",
  generation_method: "llm_with_postprocess",
  is_seed: false,
  is_active: true,
};

export default function StrategiesPage() {
  const [strategies, setStrategies] = useState([]);
  const [metrics, setMetrics] = useState([]);
  const [subgoals, setSubgoals] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showDialog, setShowDialog] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [saving, setSaving] = useState(false);
  const [expandedId, setExpandedId] = useState(null);

  // Filters
  const [filterContentType, setFilterContentType] = useState("");
  const [filterSeed, setFilterSeed] = useState("");

  const toast = useToast();
  const confirm = useConfirm();

  useEffect(() => {
    getMetrics().then(setMetrics).catch(() => setMetrics([]));
    getSubgoals().then(setSubgoals).catch(() => setSubgoals([]));
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      const params: Record<string, unknown> = {};
      if (filterContentType) params.content_type = filterContentType;
      if (filterSeed !== "") params.is_seed = filterSeed;
      // ``getStrategies`` typed as ``Promise<unknown>`` until codegen lands.
      setStrategies((await getStrategies(params)) as any[]);
    } catch {
      toast.error("Failed to load strategies");
    } finally {
      setLoading(false);
    }
  }, [filterContentType, filterSeed]);

  useEffect(() => { load(); }, [load]);

  // Collect unique content_types for filter dropdown
  const contentTypes = [...new Set(strategies.map((s) => s.content_type).filter(Boolean))];

  function openCreate() {
    setEditing(null);
    setForm(EMPTY_FORM);
    setShowDialog(true);
  }

  function openEdit(item) {
    setEditing(item);
    const dims = item.dimensions;
    let dimsStr = "{}";
    if (dims && typeof dims === "object") {
      dimsStr = JSON.stringify(dims, null, 2);
    } else if (typeof dims === "string") {
      dimsStr = dims;
    }
    setForm({
      name: item.name || "",
      description: item.description || "",
      dimensions: dimsStr,
      source_metrics: item.source_metrics || [],
      source_subgoals: item.source_subgoals || [],
      content_type: item.content_type || "",
      generation_method: item.generation_method || "llm_with_postprocess",
      is_seed: item.is_seed ?? false,
      is_active: item.is_active ?? true,
    });
    setShowDialog(true);
  }

  async function handleSave() {
    if (!form.name) {
      toast.error("Name is required");
      return;
    }
    let dimensions;
    try {
      dimensions = JSON.parse(form.dimensions);
    } catch {
      toast.error("Dimensions must be valid JSON");
      return;
    }
    setSaving(true);
    try {
      const payload = { ...form, dimensions };
      if (editing) {
        await updateStrategy(editing.id, payload);
        toast.success("Strategy updated");
      } else {
        await createStrategy(payload);
        toast.success("Strategy created");
      }
      setShowDialog(false);
      load();
    } catch (err) {
      toast.error(err.message);
    } finally {
      setSaving(false);
    }
  }

  async function handleDelete(item) {
    if (!await confirm(`Delete strategy "${item.name}"?`, "Delete Strategy")) return;
    try {
      await deleteStrategy(item.id);
      toast.success("Deleted");
      load();
    } catch (err) {
      toast.error(err.message);
    }
  }

  function metricLabel(id) {
    const m = metrics.find((x) => x.id === id);
    return m ? m.name_en : id;
  }

  function subgoalLabel(id) {
    const s = subgoals.find((x) => x.id === id);
    return s ? s.name_en : id;
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-foreground">Content Strategies</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Layer 3 of the content optimization framework. Strategies drive content generation.
          </p>
        </div>
        <Button onClick={openCreate}>
          <Plus className="mr-2 h-4 w-4" /> Add Strategy
        </Button>
      </div>

      {/* Filters */}
      <Card>
        <CardContent className="pt-4 pb-4">
          <div className="flex items-center gap-4">
            <Filter className="h-4 w-4 text-muted-foreground" />
            <div className="w-[200px]">
              <Select value={filterContentType || "__all__"} onValueChange={(v) => setFilterContentType(v === "__all__" ? "" : v)}>
                <SelectTrigger>
                  <SelectValue placeholder="All content types" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__all__">All content types</SelectItem>
                  {contentTypes.map((ct) => (
                    <SelectItem key={ct} value={ct}>{ct}</SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="w-[160px]">
              <Select value={filterSeed || "__all__"} onValueChange={(v) => setFilterSeed(v === "__all__" ? "" : v)}>
                <SelectTrigger>
                  <SelectValue placeholder="Seed filter" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__all__">All</SelectItem>
                  <SelectItem value="true">Seed only</SelectItem>
                  <SelectItem value="false">Non-seed only</SelectItem>
                </SelectContent>
              </Select>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-lg font-semibold flex items-center">
            <Lightbulb className="mr-2 h-5 w-5 text-primary" />
            Strategies
            <Badge variant="secondary" className="ml-2">{strategies.length}</Badge>
          </CardTitle>
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
                    <TableHead>Name</TableHead>
                    <TableHead>Content Type</TableHead>
                    <TableHead>Method</TableHead>
                    <TableHead>Sources</TableHead>
                    <TableHead>Flags</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead className="text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {strategies.map((item) => (
                    <>
                      <TableRow key={item.id} className="cursor-pointer" onClick={() => setExpandedId(expandedId === item.id ? null : item.id)}>
                        <TableCell className="font-medium">
                          <div className="flex items-center gap-1">
                            {expandedId === item.id ? <ChevronUp className="h-3 w-3" /> : <ChevronDown className="h-3 w-3" />}
                            {item.name}
                          </div>
                        </TableCell>
                        <TableCell>
                          {item.content_type ? <Badge variant="outline">{item.content_type}</Badge> : <span className="text-muted-foreground">-</span>}
                        </TableCell>
                        <TableCell className="text-sm">
                          {GENERATION_METHODS.find((m) => m.value === item.generation_method)?.label || item.generation_method}
                        </TableCell>
                        <TableCell>
                          <div className="flex flex-wrap gap-1">
                            {(item.source_metrics || []).map((id) => (
                              <Badge key={id} variant="secondary" className="text-[10px]">M: {metricLabel(id)}</Badge>
                            ))}
                            {(item.source_subgoals || []).map((id) => (
                              <Badge key={id} variant="secondary" className="text-[10px]">S: {subgoalLabel(id)}</Badge>
                            ))}
                            {!(item.source_metrics?.length || item.source_subgoals?.length) && <span className="text-muted-foreground text-xs">-</span>}
                          </div>
                        </TableCell>
                        <TableCell>
                          {item.is_seed && <Badge className="bg-amber-500/10 text-amber-400 border-amber-500/20 text-[10px]">Seed</Badge>}
                        </TableCell>
                        <TableCell>
                          <Badge variant={item.is_active ? "default" : "secondary"}>
                            {item.is_active ? "Active" : "Inactive"}
                          </Badge>
                        </TableCell>
                        <TableCell className="text-right" onClick={(e) => e.stopPropagation()}>
                          <Button variant="ghost" size="sm" onClick={() => openEdit(item)}>
                            <Pencil className="h-4 w-4" />
                          </Button>
                          <Button variant="ghost" size="sm" onClick={() => handleDelete(item)} className="text-destructive">
                            <Trash2 className="h-4 w-4" />
                          </Button>
                        </TableCell>
                      </TableRow>
                      {expandedId === item.id && (
                        <TableRow key={`${item.id}-detail`}>
                          <TableCell colSpan={7} className="bg-muted/30 px-6 py-4">
                            <div className="grid grid-cols-2 gap-4 text-sm">
                              <div>
                                <div className="text-xs text-muted-foreground font-medium mb-1">Description</div>
                                <div>{item.description || "-"}</div>
                              </div>
                              <div>
                                <div className="text-xs text-muted-foreground font-medium mb-1">Dimensions</div>
                                <pre className="text-xs bg-muted/50 rounded p-2 max-h-32 overflow-auto">
                                  {typeof item.dimensions === "object"
                                    ? JSON.stringify(item.dimensions, null, 2)
                                    : item.dimensions || "{}"}
                                </pre>
                              </div>
                              <div>
                                <div className="text-xs text-muted-foreground font-medium mb-1">ID</div>
                                <div className="font-mono text-xs">{item.id}</div>
                              </div>
                              <div>
                                <div className="text-xs text-muted-foreground font-medium mb-1">Created</div>
                                <div className="text-xs">{item.created_at ? new Date(item.created_at).toLocaleString() : "-"}</div>
                              </div>
                            </div>
                          </TableCell>
                        </TableRow>
                      )}
                    </>
                  ))}
                  {strategies.length === 0 && (
                    <TableRow>
                      <TableCell colSpan={7} className="text-center py-8 text-muted-foreground">
                        No strategies found.
                      </TableCell>
                    </TableRow>
                  )}
                </TableBody>
              </Table>
            </div>
          )}
        </CardContent>
      </Card>

      <Dialog open={showDialog} onOpenChange={setShowDialog}>
        <DialogContent className="max-w-2xl max-h-[85vh] overflow-y-auto">
          <DialogHeader>
            <DialogTitle>{editing ? "Edit Strategy" : "Add Strategy"}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>Name</Label>
              <Input
                placeholder="Strategy name"
                value={form.name}
                onChange={(e) => setForm({ ...form, name: e.target.value })}
              />
            </div>
            <div className="space-y-2">
              <Label>Description</Label>
              <Textarea
                placeholder="Describe the strategy"
                value={form.description}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
                rows={2}
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>Content Type</Label>
                <Input
                  placeholder="e.g. faq, article, social"
                  value={form.content_type}
                  onChange={(e) => setForm({ ...form, content_type: e.target.value })}
                />
              </div>
              <div className="space-y-2">
                <Label>Generation Method</Label>
                <Select value={form.generation_method} onValueChange={(v) => setForm({ ...form, generation_method: v })}>
                  <SelectTrigger>
                    <SelectValue />
                  </SelectTrigger>
                  <SelectContent>
                    {GENERATION_METHODS.map((m) => (
                      <SelectItem key={m.value} value={m.value}>{m.label}</SelectItem>
                    ))}
                  </SelectContent>
                </Select>
              </div>
            </div>
            <div className="space-y-2">
              <Label>Source Metrics (comma-separated IDs)</Label>
              <Input
                placeholder="e.g. visibility,citation"
                value={form.source_metrics.join(",")}
                onChange={(e) => setForm({ ...form, source_metrics: e.target.value ? e.target.value.split(",").map((s) => s.trim()) : [] })}
              />
              {metrics.length > 0 && (
                <div className="flex flex-wrap gap-1 mt-1">
                  {metrics.map((m) => (
                    <button
                      key={m.id}
                      type="button"
                      className={`text-[10px] px-1.5 py-0.5 rounded border transition-colors ${
                        form.source_metrics.includes(m.id)
                          ? "bg-primary/10 border-primary/30 text-primary"
                          : "border-border text-muted-foreground hover:border-primary/30"
                      }`}
                      onClick={() => {
                        const has = form.source_metrics.includes(m.id);
                        setForm({
                          ...form,
                          source_metrics: has
                            ? form.source_metrics.filter((x) => x !== m.id)
                            : [...form.source_metrics, m.id],
                        });
                      }}
                    >
                      {m.icon} {m.name_en}
                    </button>
                  ))}
                </div>
              )}
            </div>
            <div className="space-y-2">
              <Label>Source Subgoals (comma-separated IDs)</Label>
              <Input
                placeholder="e.g. sov_improve,citation_boost"
                value={form.source_subgoals.join(",")}
                onChange={(e) => setForm({ ...form, source_subgoals: e.target.value ? e.target.value.split(",").map((s) => s.trim()) : [] })}
              />
              {subgoals.length > 0 && (
                <div className="flex flex-wrap gap-1 mt-1">
                  {subgoals.map((s) => (
                    <button
                      key={s.id}
                      type="button"
                      className={`text-[10px] px-1.5 py-0.5 rounded border transition-colors ${
                        form.source_subgoals.includes(s.id)
                          ? "bg-primary/10 border-primary/30 text-primary"
                          : "border-border text-muted-foreground hover:border-primary/30"
                      }`}
                      onClick={() => {
                        const has = form.source_subgoals.includes(s.id);
                        setForm({
                          ...form,
                          source_subgoals: has
                            ? form.source_subgoals.filter((x) => x !== s.id)
                            : [...form.source_subgoals, s.id],
                        });
                      }}
                    >
                      {s.name_en}
                    </button>
                  ))}
                </div>
              )}
            </div>
            <div className="space-y-2">
              <Label>Dimensions (JSON)</Label>
              <Textarea
                className="font-mono text-xs"
                placeholder='{"key": "value"}'
                value={form.dimensions}
                onChange={(e) => setForm({ ...form, dimensions: e.target.value })}
                rows={4}
              />
            </div>
            <div className="flex items-center gap-6">
              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={form.is_seed}
                  onChange={(e) => setForm({ ...form, is_seed: e.target.checked })}
                  className="h-4 w-4 rounded border-border"
                />
                <Label>Seed Strategy</Label>
              </div>
              <div className="flex items-center gap-2">
                <input
                  type="checkbox"
                  checked={form.is_active}
                  onChange={(e) => setForm({ ...form, is_active: e.target.checked })}
                  className="h-4 w-4 rounded border-border"
                />
                <Label>Active</Label>
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowDialog(false)}>Cancel</Button>
            <Button onClick={handleSave} disabled={saving || !form.name}>
              {saving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
              {editing ? "Update" : "Create"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
