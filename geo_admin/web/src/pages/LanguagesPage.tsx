import { useState, useEffect } from "react";
import { useToast, useConfirm } from "../components/Toast";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Badge } from "@/components/ui/badge";
import { Table, TableBody, TableCell, TableHead, TableHeader, TableRow } from "@/components/ui/table";
import { Dialog, DialogContent, DialogHeader, DialogTitle, DialogFooter } from "@/components/ui/dialog";
import { Label } from "@/components/ui/label";
import { Languages as LanguagesIcon, Plus, Pencil, Trash2, Loader2 } from "lucide-react";
import {
    createGlobalLanguage,
    deleteGlobalLanguage,
    getGlobalLanguages,
    updateGlobalLanguage,
} from "../api/client";

interface LanguageRow {
    id: string;
    language_code: string;
    language: string;
    is_active?: boolean;
}

interface LanguageForm {
    language_code: string;
    language: string;
}

async function fetchLanguages(): Promise<LanguageRow[]> {
    return getGlobalLanguages() as Promise<LanguageRow[]>;
}

async function createLanguage(data: LanguageForm): Promise<LanguageRow> {
    return createGlobalLanguage(data) as Promise<LanguageRow>;
}

async function updateLanguage(id: string, data: LanguageForm): Promise<LanguageRow> {
    return updateGlobalLanguage(id, data) as Promise<LanguageRow>;
}

async function deleteLanguage(id: string): Promise<unknown> {
    return deleteGlobalLanguage(id);
}

export default function LanguagesPage() {
    const [languages, setLanguages] = useState<LanguageRow[]>([]);
    const [loading, setLoading] = useState<boolean>(true);
    const [showDialog, setShowDialog] = useState<boolean>(false);
    const [editingLang, setEditingLang] = useState<LanguageRow | null>(null);
    const [form, setForm] = useState<LanguageForm>({ language_code: "", language: "" });
    const [saving, setSaving] = useState<boolean>(false);

    const toast = useToast();
    const confirm = useConfirm();

    useEffect(() => {
        load();
    }, []);

    async function load() {
        setLoading(true);
        try {
            const data = await fetchLanguages();
            setLanguages(data);
        } catch (err) {
            console.error(err);
        } finally {
            setLoading(false);
        }
    }

    function openCreate() {
        setEditingLang(null);
        setForm({ language_code: "", language: "" });
        setShowDialog(true);
    }

    function openEdit(lang: LanguageRow) {
        setEditingLang(lang);
        setForm({ language_code: lang.language_code, language: lang.language });
        setShowDialog(true);
    }

    async function handleSave(): Promise<void> {
        setSaving(true);
        try {
            if (editingLang) {
                await updateLanguage(editingLang.id, form);
            } else {
                await createLanguage(form);
            }
            setShowDialog(false);
            load();
        } catch (err) {
            toast.error((err as Error).message);
        } finally {
            setSaving(false);
        }
    }

    async function handleDelete(id: string): Promise<void> {
        if (!await confirm("Are you sure you want to delete this language?", "Delete Language")) return;
        try {
            await deleteLanguage(id);
            load();
        } catch (err) {
            toast.error((err as Error).message);
        }
    }

    return (
        <div className="space-y-6">
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-3xl font-bold tracking-tight text-foreground">Languages</h1>
                    <p className="mt-2 text-sm text-muted-foreground">
                        Manage global language options available for prompt generation.
                    </p>
                </div>
                <Button onClick={openCreate}>
                    <Plus className="mr-2 h-4 w-4" /> Add Language
                </Button>
            </div>

            <Card>
                <CardHeader className="pb-3">
                    <CardTitle className="text-lg font-semibold flex items-center">
                        <LanguagesIcon className="mr-2 h-5 w-5 text-primary" />
                        Global Languages
                        <Badge variant="secondary" className="ml-2">{languages.length}</Badge>
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
                                        <TableHead>Language Code</TableHead>
                                        <TableHead>Display Name</TableHead>
                                        <TableHead>Status</TableHead>
                                        <TableHead className="text-right">Actions</TableHead>
                                    </TableRow>
                                </TableHeader>
                                <TableBody>
                                    {languages.map((lang) => (
                                        <TableRow key={lang.id}>
                                            <TableCell className="font-mono text-sm">{lang.language_code}</TableCell>
                                            <TableCell>{lang.language}</TableCell>
                                            <TableCell>
                                                <Badge variant={lang.is_active ? "default" : "secondary"}>
                                                    {lang.is_active ? "Active" : "Inactive"}
                                                </Badge>
                                            </TableCell>
                                            <TableCell className="text-right">
                                                <Button variant="ghost" size="sm" onClick={() => openEdit(lang)}>
                                                    <Pencil className="h-4 w-4" />
                                                </Button>
                                                <Button variant="ghost" size="sm" onClick={() => handleDelete(lang.id)} className="text-destructive">
                                                    <Trash2 className="h-4 w-4" />
                                                </Button>
                                            </TableCell>
                                        </TableRow>
                                    ))}
                                    {languages.length === 0 && (
                                        <TableRow>
                                            <TableCell colSpan={4} className="text-center py-8 text-muted-foreground">
                                                No languages configured. Run the seed SQL to initialize.
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
                <DialogContent>
                    <DialogHeader>
                        <DialogTitle>{editingLang ? "Edit Language" : "Add Language"}</DialogTitle>
                    </DialogHeader>
                    <div className="space-y-4">
                        <div className="space-y-2">
                            <Label>Language Code</Label>
                            <Input
                                placeholder="e.g. en-US, zh-CN, es"
                                value={form.language_code}
                                onChange={(e) => setForm({ ...form, language_code: e.target.value })}
                            />
                        </div>
                        <div className="space-y-2">
                            <Label>Display Name</Label>
                            <Input
                                placeholder="e.g. English (en-US)"
                                value={form.language}
                                onChange={(e) => setForm({ ...form, language: e.target.value })}
                            />
                        </div>
                    </div>
                    <DialogFooter>
                        <Button variant="outline" onClick={() => setShowDialog(false)}>Cancel</Button>
                        <Button onClick={handleSave} disabled={saving || !form.language_code || !form.language}>
                            {saving ? <Loader2 className="mr-2 h-4 w-4 animate-spin" /> : null}
                            {editingLang ? "Update" : "Create"}
                        </Button>
                    </DialogFooter>
                </DialogContent>
            </Dialog>
        </div>
    );
}
