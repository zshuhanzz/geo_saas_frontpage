import { useState, useEffect } from "react";
import { Trans, useTranslation } from "react-i18next";
import { useSaaS } from "../contexts/SaaSContext";
import { getBrandProfile, updateBrandProfile } from "../lib/api";
import {
    Card,
    CardContent,
    CardHeader,
    CardTitle,
    CardDescription,
} from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Badge } from "@/components/ui/badge";
import { Textarea } from "@/components/ui/textarea";
import { X, Plus, Save, Sparkles } from "lucide-react";
import { toast } from "sonner";

export default function BrandHub() {
    const { t } = useTranslation(["dashboards", "sidebar"]);
    const { clientId, activeClientName } = useSaaS();
    const [loading, setLoading] = useState(true);
    const [saving, setSaving] = useState(false);

    const [brandName, setBrandName] = useState("");
    const [toneOfVoice, setToneOfVoice] = useState("");
    const [targetAudience, setTargetAudience] = useState("");
    const [keyMessages, setKeyMessages] = useState<string[]>([]);
    const [brandValues, setBrandValues] = useState<string[]>([]);
    const [language, setLanguage] = useState("");

    const [newMessage, setNewMessage] = useState("");
    const [newValue, setNewValue] = useState("");

    useEffect(() => {
        if (clientId) loadProfile();
    }, [clientId]);

    async function loadProfile() {
        if (!clientId) return;
        setLoading(true);
        try {
            const data = await getBrandProfile(clientId);
            setBrandName(data.brand_name || "");
            setToneOfVoice(data.tone_of_voice || "");
            setTargetAudience(data.target_audience || "");
            setKeyMessages(data.key_messages || []);
            setBrandValues(data.brand_values || []);
            setLanguage(data.language || "");
        } catch (err: any) {
            console.error("Failed to load brand profile", err);
        } finally {
            setLoading(false);
        }
    }

    async function handleSave() {
        if (!clientId) return;
        setSaving(true);
        try {
            await updateBrandProfile(clientId, {
                brand_name: brandName || null,
                tone_of_voice: toneOfVoice || null,
                target_audience: targetAudience || null,
                key_messages: keyMessages.length > 0 ? keyMessages : null,
                brand_values: brandValues.length > 0 ? brandValues : null,
                language: language || null,
            });
            toast.success(t("brandHub.toastSaved"));
        } catch (err: any) {
            toast.error(t("brandHub.toastSaveFailed", { message: err.message }));
        } finally {
            setSaving(false);
        }
    }

    function addMessage() {
        if (!newMessage.trim()) return;
        setKeyMessages([...keyMessages, newMessage.trim()]);
        setNewMessage("");
    }

    function removeMessage(idx: number) {
        setKeyMessages(keyMessages.filter((_, i) => i !== idx));
    }

    function addValue() {
        if (!newValue.trim()) return;
        setBrandValues([...brandValues, newValue.trim()]);
        setNewValue("");
    }

    function removeValue(idx: number) {
        setBrandValues(brandValues.filter((_, i) => i !== idx));
    }

    if (!clientId) {
        return (
            <div className="h-full flex flex-col items-center justify-center space-y-2">
                <h2 className="text-xl font-medium text-foreground">{t("brandHub.title")}</h2>
                <p className="text-sm text-muted-foreground">{t("brandHub.noClient")}</p>
            </div>
        );
    }

    return (
        <div className="max-w-4xl mx-auto space-y-6">
            <div className="flex items-center justify-between">
                <div className="flex flex-col gap-2">
                    <h1 className="text-3xl font-bold tracking-tight flex items-center gap-2">
                        <Sparkles className="h-7 w-7 text-primary" /> {t("brandHub.title")}
                    </h1>
                    <p className="text-muted-foreground">
                        <Trans
                            i18nKey="brandHub.description"
                            ns="dashboards"
                            values={{ clientName: activeClientName }}
                            components={{ 1: <span className="font-semibold text-foreground" /> }}
                        />
                    </p>
                </div>
                <Button onClick={handleSave} disabled={saving || loading} size="lg">
                    <Save className="h-4 w-4 mr-2" />
                    {saving ? t("brandHub.saveSaving") : t("brandHub.saveButton")}
                </Button>
            </div>

            {loading ? (
                <div className="flex py-12 items-center justify-center text-muted-foreground">{t("brandHub.loading")}</div>
            ) : (
                <div className="space-y-6">
                    {/* Basic Info */}
                    <Card className="shadow-sm border-muted/50">
                        <CardHeader>
                            <CardTitle>{t("brandHub.sections.basicTitle")}</CardTitle>
                            <CardDescription>{t("brandHub.sections.basicDescription")}</CardDescription>
                        </CardHeader>
                        <CardContent className="space-y-4">
                            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                                <div className="space-y-2">
                                    <Label>{t("brandHub.fields.brandName")}</Label>
                                    <Input
                                        placeholder={t("brandHub.fields.brandNamePlaceholder")}
                                        value={brandName}
                                        onChange={(e) => setBrandName(e.target.value)}
                                    />
                                </div>
                                <div className="space-y-2">
                                    <Label>{t("brandHub.fields.primaryLanguage")}</Label>
                                    <Input
                                        placeholder={t("brandHub.fields.primaryLanguagePlaceholder")}
                                        value={language}
                                        onChange={(e) => setLanguage(e.target.value)}
                                    />
                                </div>
                            </div>
                            <div className="space-y-2">
                                <Label>{t("brandHub.fields.targetAudience")}</Label>
                                <Input
                                    placeholder={t("brandHub.fields.targetAudiencePlaceholder")}
                                    value={targetAudience}
                                    onChange={(e) => setTargetAudience(e.target.value)}
                                />
                            </div>
                        </CardContent>
                    </Card>

                    {/* Tone of Voice */}
                    <Card className="shadow-sm border-muted/50">
                        <CardHeader>
                            <CardTitle>{t("brandHub.sections.toneTitle")}</CardTitle>
                            <CardDescription>
                                {t("brandHub.sections.toneDescription")}
                            </CardDescription>
                        </CardHeader>
                        <CardContent>
                            <Textarea
                                placeholder={t("brandHub.fields.tonePlaceholder")}
                                value={toneOfVoice}
                                onChange={(e) => setToneOfVoice(e.target.value)}
                                rows={4}
                                className="resize-none"
                            />
                        </CardContent>
                    </Card>

                    {/* Key Messages */}
                    <Card className="shadow-sm border-muted/50">
                        <CardHeader>
                            <CardTitle>{t("brandHub.sections.messagesTitle")}</CardTitle>
                            <CardDescription>
                                {t("brandHub.sections.messagesDescription")}
                            </CardDescription>
                        </CardHeader>
                        <CardContent className="space-y-4">
                            <div className="flex flex-wrap gap-2">
                                {keyMessages.map((msg, idx) => (
                                    <Badge key={idx} variant="secondary" className="pl-3 pr-1 py-1.5 text-sm bg-accent/60">
                                        {msg}
                                        <button
                                            onClick={() => removeMessage(idx)}
                                            className="ml-2 rounded-full hover:bg-destructive/10 hover:text-destructive transition-colors p-0.5"
                                        >
                                            <X className="h-3 w-3" />
                                        </button>
                                    </Badge>
                                ))}
                                {keyMessages.length === 0 && (
                                    <span className="text-sm text-muted-foreground italic py-1">{t("brandHub.fields.messagesEmpty")}</span>
                                )}
                            </div>
                            <div className="flex gap-2 max-w-lg">
                                <Input
                                    placeholder={t("brandHub.fields.messagesPlaceholder")}
                                    value={newMessage}
                                    onChange={(e) => setNewMessage(e.target.value)}
                                    onKeyDown={(e) => e.key === "Enter" && addMessage()}
                                />
                                <Button variant="outline" onClick={addMessage}>
                                    <Plus className="h-4 w-4 mr-1" /> {t("brandHub.fields.addButton")}
                                </Button>
                            </div>
                        </CardContent>
                    </Card>

                    {/* Brand Values */}
                    <Card className="shadow-sm border-muted/50">
                        <CardHeader>
                            <CardTitle>{t("brandHub.sections.valuesTitle")}</CardTitle>
                            <CardDescription>
                                {t("brandHub.sections.valuesDescription")}
                            </CardDescription>
                        </CardHeader>
                        <CardContent className="space-y-4">
                            <div className="flex flex-wrap gap-2">
                                {brandValues.map((val, idx) => (
                                    <Badge key={idx} variant="outline" className="pl-3 pr-1 py-1.5 text-sm">
                                        {val}
                                        <button
                                            onClick={() => removeValue(idx)}
                                            className="ml-2 rounded-full hover:bg-destructive/10 hover:text-destructive transition-colors p-0.5"
                                        >
                                            <X className="h-3 w-3" />
                                        </button>
                                    </Badge>
                                ))}
                                {brandValues.length === 0 && (
                                    <span className="text-sm text-muted-foreground italic py-1">{t("brandHub.fields.valuesEmpty")}</span>
                                )}
                            </div>
                            <div className="flex gap-2 max-w-lg">
                                <Input
                                    placeholder={t("brandHub.fields.valuesPlaceholder")}
                                    value={newValue}
                                    onChange={(e) => setNewValue(e.target.value)}
                                    onKeyDown={(e) => e.key === "Enter" && addValue()}
                                />
                                <Button variant="outline" onClick={addValue}>
                                    <Plus className="h-4 w-4 mr-1" /> {t("brandHub.fields.addButton")}
                                </Button>
                            </div>
                        </CardContent>
                    </Card>
                </div>
            )}
        </div>
    );
}
