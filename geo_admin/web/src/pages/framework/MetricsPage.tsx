import { useState, useEffect } from "react";
import { useToast, useConfirm } from "../../components/Toast";
import { getMetrics, createMetric, updateMetric, deleteMetric } from "../../api/client";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Target, Plus, Pencil, Trash2, Loader2 } from "lucide-react";

const EMPTY_FORM = {
  id: "",
  name_zh: "",
  name_en: "",
  description: "",
  icon: "📊",
  sort_order: 0,
  is_active: true,
};

export default function MetricsPage() {
  const [metrics, setMetrics] = useState([]);
  const [loading, setLoading] = useState(true);
  const [showDialog, setShowDialog] = useState(false);
  const [editing, setEditing] = useState(null);
  const [form, setForm] = useState(EMPTY_FORM);
  const [saving, setSaving] = useState(false);

  const toast = useToast();
  const confirm = useConfirm();

  useEffect(() => { load(); }, []);

  async function load() {
    setLoading(true);
    try {
      // ``getMetrics`` is typed as ``Promise<unknown>`` until OpenAPI codegen
      // tightens ``client.ts``; the actual payload is a list of metric rows.
      setMetrics((await getMetrics()) as any[]);
    } catch (err) {
      toast.error("Failed to load metrics");
    } finally {
      setLoading(false);
    }
  }

  function openCreate() {
    setEditing(null);
    setForm(EMPTY_FORM);
    setShowDialog(true);
  }

  function openEdit(item) {
    setEditing(item);
    setForm({
      id: item.id,
      name_zh: item.name_zh || "",
      name_en: item.name_en || "",
      description: item.description || "",
      icon: item.icon || "📊",
      sort_order: item.sort_order ?? 0,
      is_active: item.is_active ?? true,
    });
    setShowDialog(true);
  }

  async function handleSave() {
    if (!form.id || !form.name_zh || !form.name_en) {
      toast.error("ID, Chinese name, and English name are required");
      return;
    }
    setSaving(true);
    try {
      if (editing) {
        const { id, ...updates } = form;
        await updateMetric(editing.id, updates);
        toast.success("Metric updated");
      } else {
        await createMetric(form);
        toast.success("Metric created");
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
    if (!await confirm(`Delete metric "${item.name_en}"?`, "Delete Metric")) return;
    try {
      await deleteMetric(item.id);
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
          <h1 className="text-3xl font-bold tracking-tight text-foreground">Optimization Metrics</h1>
          <p className="mt-2 text-sm text-muted-foreground">
            Layer 1 of the content optimization framework. Define high-level GEO metrics.
          </p>
        </div>
        <Button onClick={openCreate}>
          <Plus className="mr-2 h-4 w-4" /> Add Metric
        </Button>
      </div>

      <Card>
        <CardHeader className="pb-3">
          <CardTitle className="text-lg font-semibold flex items-center">
            <Target className="mr-2 h-5 w-5 text-primary" />
            Metrics
            <Badge variant="secondary" className="ml-2">{metrics.length}</Badge>
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
                    <TableHead className="w-[100px]">ID</TableHead>
                    <TableHead>Icon</TableHead>
                    <TableHead>Chinese Name</TableHead>
                    <TableHead>English Name</TableHead>
                    <TableHead>Description</TableHead>
                    <TableHead className="w-[80px]">Order</TableHead>
                    <TableHead>Status</TableHead>
                    <TableHead className="text-right">Actions</TableHead>
                  </TableRow>
                </TableHeader>
                <TableBody>
                  {metrics.map((item) => (
                    <TableRow key={item.id}>
                      <TableCell className="font-mono text-xs">{item.id}</TableCell>
                      <TableCell className="text-lg">{item.icon}</TableCell>
                      <TableCell className="font-medium">{item.name_zh}</TableCell>
                      <TableCell>{item.name_en}</TableCell>
                      <TableCell className="max-w-[300px] truncate text-muted-foreground text-sm">{item.description}</TableCell>
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
                  {metrics.length === 0 && (
                    <TableRow>
                      <TableCell colSpan={8} className="text-center py-8 text-muted-foreground">
                        No metrics configured yet.
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
            <DialogTitle>{editing ? "Edit Metric" : "Add Metric"}</DialogTitle>
          </DialogHeader>
          <div className="space-y-4">
            <div className="space-y-2">
              <Label>ID (unique key)</Label>
              <Input
                placeholder="e.g. visibility"
                value={form.id}
                onChange={(e) => setForm({ ...form, id: e.target.value })}
                disabled={!!editing}
              />
            </div>
            <div className="grid grid-cols-2 gap-4">
              <div className="space-y-2">
                <Label>Chinese Name</Label>
                <Input
                  placeholder="e.g. 品牌可见度"
                  value={form.name_zh}
                  onChange={(e) => setForm({ ...form, name_zh: e.target.value })}
                />
              </div>
              <div className="space-y-2">
                <Label>English Name</Label>
                <Input
                  placeholder="e.g. Brand Visibility"
                  value={form.name_en}
                  onChange={(e) => setForm({ ...form, name_en: e.target.value })}
                />
              </div>
            </div>
            <div className="space-y-2">
              <Label>Description</Label>
              <Input
                placeholder="Describe this metric"
                value={form.description}
                onChange={(e) => setForm({ ...form, description: e.target.value })}
              />
            </div>
            <div className="grid grid-cols-3 gap-4">
              <div className="space-y-2">
                <Label>Icon (emoji)</Label>
                <Input
                  value={form.icon}
                  onChange={(e) => setForm({ ...form, icon: e.target.value })}
                />
              </div>
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
            <Button onClick={handleSave} disabled={saving || !form.id || !form.name_zh || !form.name_en}>
              {saving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
              {editing ? "Update" : "Create"}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>
  );
}
