import { useState, useEffect, useCallback } from "react";
import { useToast, useConfirm } from "../../components/Toast";
import { getMetrics, getSubgoals, createSubgoal, updateSubgoal, deleteSubgoal } from "../../api/client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Label } from "@/components/ui/label";
import { Crosshair, Plus, Pencil, Trash2, Loader2, Filter } from "lucide-react";

const EMPTY_FORM = {
  id: "",
  metric_id: "",
  name_zh: "",
  name_en: "",
  description: "",
  sort_order: 0,
  is_active: true,
};

export default function SubgoalsPage() {
  const [subgoals, setSubgoals] = useState([]);
  const [metrics, setMetrics] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showDialog, setShowDialog] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [saving, setSaving] = useState(false);

  // Filter
  const [filterMetric, setFilterMetric] = useState("");

  const toast = useToast();
  const confirm = useConfirm();

  useEffect(() => {
    getMetrics().then(setMetrics).catch(() => setMetrics([]));
  }, []);

  const load = useCallback(async () => {
    setLoading(true);
    try {
      // ``getSubgoals`` typed as ``Promise<unknown>`` until codegen lands.
      setSubgoals((await getSubgoals(filterMetric)) as any[]);
    } catch {
      toast.error("Failed to load subgoals");
    } finally {
      setLoading(false);
    }
  }, [filterMetric]);

  useEffect(() => { load(); }, [load]);

  function metricLabel(metricId) {
    const m = metrics.find((x) => x.id === metricId);
    return m ? `${m.icon || ""} ${m.name_en}` : metricId;
  }

  function openCreate() {
    setEditing(null);
    setForm({ ...EMPTY_FORM, metric_id: filterMetric || "" });
    setShowDialog(true);
  }

  function openEdit(item) {
    setEditing(item);
    setForm({
      id: item.id,
      metric_id: item.metric_id || "",
      name_zh: item.name_zh || "",
      name_en: item.name_en || "",
      description: item.description || "",
      sort_order: item.sort_order ?? 0,
      is_active: item.is_active ?? true,
    });
    setShowDialog(true);
  }

  async function handleSave() {
    if (!form.id || !form.metric_id || !form.name_zh || !form.name_en) {
      toast.error("ID, metric, Chinese name, and English name are required");
      return;
    }
    setSaving(true);
    try {
      if (editing) {
        const { id, ...updates } = form;
        await updateSubgoal(editing.id, updates);
        toast.success("Subgoal updated");
      } else {
        await createSubgoal(form);
        toast.success("Subgoal created");
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
    if (!await confirm(`Delete subgoal "${item.name_en}"?`, "Delete Subgoal")) return;
    try {
      await deleteSubgoal(item.id);
      toast.success("Deleted");
      load();
    } catch (err) {
      toast.error(err.message);
    }
  }

  return (
    <div className="space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-3xl font-bold tracking-tight text-foreground">Optimization Subgoals</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Layer 2 of the content optimization framework. Subgoals belong to a parent metric.
          </p>
        </div>
        <Button onClick={openCreate}>
          <Plus className="mr-2 h-4 w-4" /> Add Subgoal
        </Button>
      </div>

      {/* Filters */}
      <Card>
        <CardContent className="pt-4 pb-4">
          <div className="flex items-center gap-4">
            <Filter className="h-4 w-4 text-muted-foreground" />
            <div className="w-[260px]">
              <Select value={filterMetric || "__all__"} onValueChange={(v) => setFilterMetric(v === "__all__" ? "" : v)}>
                <SelectTrigger>
                  <SelectValue placeholder="All metrics" />
                </SelectTrigger>
                <SelectContent>
                  <SelectItem value="__all__">All metrics</SelectItem>
                  {metrics.map((m) => (
                    <SelectItem key={m.id} value={m.id}>
                      {m.icon} {m.name_en}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>
        </CardContent>
      </Card>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-lg font-semibold flex items-center">
            <Crosshair className="mr-2 h-5 w-5 text-primary" />
            Subgoals
            <Badge variant="secondary" className="ml-2">{subgoals.length}</Badge>
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
                    <TableHead className="w-[120px]">ID</TableHead>
                    <TableHead>Metric</TableHead>
                    <TableHead>Chinese Name</TableHead>
                    <TableHead>English Name</TableHead>
                    <TableHead>Description</TableHead>
                    <TableHead className="w-[80px]">Order</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead className="text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {subgoals.map((item) => (
                    <TableRow key={item.id}>
                      <TableCell className="font-mono text-xs">{item.id}</TableCell>
                      <TableCell>
                        <Badge variant="outline" className="text-xs">{metricLabel(item.metric_id)}</Badge>
                      </TableCell>
                      <TableCell className="font-medium">{item.name_zh}</TableCell>
                      <TableCell>{item.name_en}</TableCell>
                      <TableCell className="max-w-[250px] truncate text-muted-foreground text-sm">{item.description}</TableCell>
                      <TableCell className="text-center">{item.sort_order}</TableCell>
                      <TableCell>
                        <Badge variant={item.is_active ? "default" : "secondary"}>
                          {item.is_active ? "Active" : "Inactive"}
                        </Badge>
                      </TableCell>
                      <TableCell className="text-right">
                        <Button variant="ghost" size="sm" onClick={() => openEdit(item)}>
                          <Pencil className="h-4 w-4" />
                        </Button>
                        <Button variant="ghost" size="sm" onClick={() => handleDelete(item)} className="text-destructive">
                          <Trash2 className="h-4 w-4" />
                        </Button>
                      </TableCell>
                    </TableRow>
                  ))}
                  {subgoals.length === 0 && (
                    <TableRow>
                      <TableCell colSpan={8} className="text-center py-8 text-muted-foreground">
                        No subgoals found.
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
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>{editing ? "Edit Subgoal" : "Add Subgoal"}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>ID (unique key)</Label>
              <Input
                placeholder="e.g. sov_improve"
                value={form.id}
                onChange={(e) => setForm({ ...form, id: e.target.value })}
                disabled={!!editing}
              />
            </div>
            <div className="space-y-2">
              <Label>Parent Metric</Label>
              <Select value={form.metric_id} onValueChange={(v) => setForm({ ...form, metric_id: v })}>
                <SelectTrigger>
                  <SelectValue placeholder="Select metric" />
                </SelectTrigger>
                <SelectContent>
                  {metrics.map((m) => (
                    <SelectItem key={m.id} value={m.id}>
                      {m.icon} {m.name_en}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>Chinese Name</Label>
                <Input
                  placeholder="e.g. 提升品牌份额"
                  value={form.name_zh}
                  onChange={(e) => setForm({ ...form, name_zh: e.target.value })}
                />
              </div>
              <div className="space-y-2">
                <Label>English Name</Label>
                <Input
                  placeholder="e.g. Improve SOV"
                  value={form.name_en}
                  onChange={(e) => setForm({ ...form, name_en: e.target.value })}
                />
              </div>
            </div>
            <div className="space-y-2">
              <Label>Description</Label>
              <Input
                placeholder="Describe this subgoal"
                value={form.description}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>Sort Order</Label>
                <Input
                  type="number"
                  value={form.sort_order}
                  onChange={(e) => setForm({ ...form, sort_order: parseInt(e.target.value) || 0 })}
                />
              </div>
              <div className="space-y-2">
                <Label>Active</Label>
                <div className="flex items-center h-10">
                  <input
                    type="checkbox"
                    checked={form.is_active}
                    onChange={(e) => setForm({ ...form, is_active: e.target.checked })}
                    className="h-4 w-4 rounded border-border"
                  />
                  <span className="ml-2 text-sm text-muted-foreground">{form.is_active ? "Active" : "Inactive"}</span>
                </div>
              </div>
            </div>
          </div>
          <DialogFooter>
            <Button variant="outline" onClick={() => setShowDialog(false)}>Cancel</Button>
            <Button onClick={handleSave} disabled={saving || !form.id || !form.metric_id || !form.name_zh || !form.name_en}>
              {saving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
              {editing ? "Update" : "Create"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
