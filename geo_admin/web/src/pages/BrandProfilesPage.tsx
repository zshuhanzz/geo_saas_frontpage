import { useState, useEffect } from "react";
import { useToast } from "../components/Toast";
import { getClients, getBrandProfile, updateBrandProfile } from "../api/client";
import type { components } from "@/api/openapi";
import { Card, CardContent, CardHeader, CardTitle, CardDescription } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import { Select, SelectContent, SelectItem, SelectTrigger, SelectValue } from "@/components/ui/select";
import { Sparkles, Save, X, Plus, Loader2 } from "lucide-react";

// Phase 7c (2026-04-25): replaced hand-written ``ClientRow`` /
// ``BrandProfileData`` with the generated OpenAPI schemas.
type ClientRow = components["schemas"]["ClientOut"];
type BrandProfileData = components["schemas"]["BrandProfileOut"];

export default function BrandProfilesPage() {
    const toast = useToast();
    const [clients, setClients] = useState<ClientRow[]>([]);
    const [selectedClientId, setSelectedClientId] = useState<string>("");
    const [loading, setLoading] = useState<boolean>(false);
    const [saving, setSaving] = useState<boolean>(false);

    const [brandName, setBrandName] = useState<string>("");
    const [toneOfVoice, setToneOfVoice] = useState<string>("");
    const [targetAudience, setTargetAudience] = useState<string>("");
    const [keyMessages, setKeyMessages] = useState<string[]>([]);
    const [brandValues, setBrandValues] = useState<string[]>([]);
    const [language, setLanguage] = useState<string>("");

    const [newMessage, setNewMessage] = useState<string>("");
    const [newValue, setNewValue] = useState<string>("");

    useEffect(() => {
        getClients().then(setClients).catch(() => setClients([]));
    }, []);

    useEffect(() => {
        if (selectedClientId) loadProfile(selectedClientId);
    }, [selectedClientId]);

    async function loadProfile(clientId: string): Promise<void> {
        setLoading(true);
        try {
            const data = await getBrandProfile(clientId);
            setBrandName(data.brand_name || "");
            setToneOfVoice(data.tone_of_voice || "");
            setTargetAudience(data.target_audience || "");
            setKeyMessages(data.key_messages || []);
            setBrandValues(data.brand_values || []);
            setLanguage(data.language || "");
        } catch {
            toast.error("Failed to load brand profile");
        } finally {
            setLoading(false);
        }
    }

    async function handleSave() {
        if (!selectedClientId) return;
        setSaving(true);
        try {
            await updateBrandProfile(selectedClientId, {
                brand_name: brandName || null,
                tone_of_voice: toneOfVoice || null,
                target_audience: targetAudience || null,
                key_messages: keyMessages.length > 0 ? keyMessages : null,
                brand_values: brandValues.length > 0 ? brandValues : null,
                language: language || null,
            });
            toast.success("Brand profile saved");
        } catch (err) {
            toast.error("Save failed: " + err.message);
        } finally {
            setSaving(false);
        }
    }

    const selectedClient = clients.find((c) => c.id === selectedClientId);

    return (
        <div className="max-w-4xl mx-auto space-y-6">
            <div className="flex items-center justify-between">
                <div>
                    <h1 className="text-2xl font-bold tracking-tight flex items-center gap-2">
                        <Sparkles className="h-6 w-6 text-primary" /> Brand Profiles
                    </h1>
                    <p className="text-sm text-muted-foreground mt-1">
                        Manage brand tonality settings for Agent content generation (Anthony Chat & Action Agent).
                    </p>
                </div>
                {selectedClientId && (
                    <Button onClick={handleSave} disabled={saving || loading}>
                        {saving ? <Loader2 className="h-4 w-4 animate-spin mr-2" /> : <Save className="h-4 w-4 mr-2" />}
                        {saving ? "Saving..." : "Save"}
                    </Button>
                )}
            </div>

            {/* Client Selector */}
            <Card>
                <CardContent className="p-4">
                    <Label className="text-sm font-medium mb-2 block">Select Client</Label>
                    <Select value={selectedClientId || "__all__"} onValueChange={(v) => setSelectedClientId(v === "__all__" ? "" : v)}>
                        <SelectTrigger className="w-full">
                            <SelectValue placeholder="-- Select a client --" />
                        </SelectTrigger>
                        <SelectContent>
                            <SelectItem value="__all__">-- Select a client --</SelectItem>
                            {clients.map((c) => (
                                <SelectItem key={c.id} value={c.id}>{c.name}</SelectItem>
                            ))}
                        </SelectContent>
                    </Select>
                </CardContent>
            </Card>

            {!selectedClientId && (
                <div className="text-center py-12 text-muted-foreground">
                    Select a client above to view or edit their brand profile.
                </div>
            )}

            {selectedClientId && loading && (
                <div className="text-center py-12 text-muted-foreground">Loading...</div>
            )}

            {selectedClientId && !loading && (
                <div className="space-y-5">
                    {/* Basic Info */}
                    <Card>
                        <CardHeader className="pb-3">
                            <CardTitle className="text-base">Basic Information</CardTitle>
                            <CardDescription>Core brand identity for {selectedClient?.name}.</CardDescription>
                        </CardHeader>
                        <CardContent className="space-y-4">
                            <div className="grid grid-cols-2 gap-4">
                                <div className="space-y-1.5">
                                    <Label className="text-xs">Brand Name</Label>
                                    <Input placeholder="e.g. AnswerX" value={brandName} onChange={(e) => setBrandName(e.target.value)} />
                                </div>
                                <div className="space-y-1.5">
                                    <Label className="text-xs">Language</Label>
                                    <Input placeholder="e.g. zh-CN" value={language} onChange={(e) => setLanguage(e.target.value)} />
                                </div>
                            </div>
                            <div className="space-y-1.5">
                                <Label className="text-xs">Target Audience</Label>
                                <Input placeholder="e.g. Tech-savvy homeowners" value={targetAudience} onChange={(e) => setTargetAudience(e.target.value)} />
                            </div>
                        </CardContent>
                    </Card>

                    {/* Tone of Voice */}
                    <Card>
                        <CardHeader className="pb-3">
                            <CardTitle className="text-base">Tone of Voice</CardTitle>
                        </CardHeader>
                        <CardContent>
                            <Textarea
                                placeholder="Describe how this brand communicates..."
                                value={toneOfVoice}
                                onChange={(e) => setToneOfVoice(e.target.value)}
                                rows={3}
                                className="resize-none"
                            />
                        </CardContent>
                    </Card>

                    {/* Key Messages */}
                    <Card>
                        <CardHeader className="pb-3">
                            <CardTitle className="text-base">Key Messages</CardTitle>
                        </CardHeader>
                        <CardContent className="space-y-3">
                            <div className="flex flex-wrap gap-2">
                                {keyMessages.map((msg, idx) => (
                                    <Badge key={idx} variant="secondary" className="pl-2.5 pr-1 py-1 text-xs">
                                        {msg}
                                        <button onClick={() => setKeyMessages(keyMessages.filter((_, i) => i !== idx))} className="ml-1.5 rounded-full hover:text-destructive p-0.5">
                                            <X className="h-3 w-3" />
                                        </button>
                                    </Badge>
                                ))}
                                {keyMessages.length === 0 && <span className="text-xs text-muted-foreground">None</span>}
                            </div>
                            <div className="flex gap-2 max-w-md">
                                <Input
                                    placeholder="Add key message..."
                                    value={newMessage}
                                    onChange={(e) => setNewMessage(e.target.value)}
                                    onKeyDown={(e) => { if (e.key === "Enter" && newMessage.trim()) { setKeyMessages([...keyMessages, newMessage.trim()]); setNewMessage(""); } }}
                                    className="h-8 text-sm"
                                />
                                <Button size="sm" variant="outline" className="h-8" onClick={() => { if (newMessage.trim()) { setKeyMessages([...keyMessages, newMessage.trim()]); setNewMessage(""); } }}>
                                    <Plus className="h-3 w-3 mr-1" /> Add
                                </Button>
                            </div>
                        </CardContent>
                    </Card>

                    {/* Brand Values */}
                    <Card>
                        <CardHeader className="pb-3">
                            <CardTitle className="text-base">Brand Values</CardTitle>
                        </CardHeader>
                        <CardContent className="space-y-3">
                            <div className="flex flex-wrap gap-2">
                                {brandValues.map((val, idx) => (
                                    <Badge key={idx} variant="outline" className="pl-2.5 pr-1 py-1 text-xs">
                                        {val}
                                        <button onClick={() => setBrandValues(brandValues.filter((_, i) => i !== idx))} className="ml-1.5 rounded-full hover:text-destructive p-0.5">
                                            <X className="h-3 w-3" />
                                        </button>
                                    </Badge>
                                ))}
                                {brandValues.length === 0 && <span className="text-xs text-muted-foreground">None</span>}
                            </div>
                            <div className="flex gap-2 max-w-md">
                                <Input
                                    placeholder="Add brand value..."
                                    value={newValue}
                                    onChange={(e) => setNewValue(e.target.value)}
                                    onKeyDown={(e) => { if (e.key === "Enter" && newValue.trim()) { setBrandValues([...brandValues, newValue.trim()]); setNewValue(""); } }}
                                    className="h-8 text-sm"
                                />
                                <Button size="sm" variant="outline" className="h-8" onClick={() => { if (newValue.trim()) { setBrandValues([...brandValues, newValue.trim()]); setNewValue(""); } }}>
                                    <Plus className="h-3 w-3 mr-1" /> Add
                                </Button>
                            </div>
                        </CardContent>
                    </Card>
                </div>
            )}
        </div>
    );
}
