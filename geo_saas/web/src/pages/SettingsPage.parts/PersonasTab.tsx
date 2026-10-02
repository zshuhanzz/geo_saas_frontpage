import { X } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Card, CardContent, CardHeader, CardTitle } from "@/components/ui/card";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { TabsContent } from "@/components/ui/tabs";

interface PersonasTabProps {
    personas: any[];
    newPersonaName: string;
    setNewPersonaName: (v: string) => void;
    newPersonaDesc: string;
    setNewPersonaDesc: (v: string) => void;
    handleAddPersona: () => void;
    handleRemovePersona: (personaId: string) => void;
}

export default function PersonasTab(props: PersonasTabProps) {
    const { t } = useTranslation("settings");
    const {
        personas,
        newPersonaName, setNewPersonaName,
        newPersonaDesc, setNewPersonaDesc,
        handleAddPersona, handleRemovePersona,
    } = props;

    return (
        <TabsContent value="personas" className="space-y-6 mt-0 animate-in fade-in-50 duration-500">
            <h3 className="text-sm font-semibold uppercase tracking-wider text-muted-foreground border-b pb-2">
                {t("personas.title")}
            </h3>
            <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
                {personas.map((p: any) => (
                    <Card
                        key={p.id}
                        className="shadow-none border bg-muted/10 relative group"
                    >
                        <Button
                            variant="ghost"
                            size="icon"
                            className="absolute top-2 right-2 h-6 w-6 opacity-0 group-hover:opacity-100 transition-opacity text-muted-foreground hover:text-destructive"
                            onClick={() => handleRemovePersona(p.id)}
                        >
                            <X className="h-4 w-4" />
                        </Button>
                        <CardHeader className="p-4 pb-2">
                            <CardTitle className="text-base font-semibold">
                                {p.persona_name}
                            </CardTitle>
                        </CardHeader>
                        <CardContent className="p-4 pt-0">
                            <p className="text-sm text-muted-foreground">
                                {p.persona_description || "No description provided."}
                            </p>
                        </CardContent>
                    </Card>
                ))}
            </div>
            {personas.length === 0 && (
                <div className="text-center py-6 text-muted-foreground">
                    {t("personas.empty")}
                </div>
            )}

            <div className="bg-muted/20 border rounded-xl p-4 space-y-4">
                <h4 className="text-sm font-medium">{t("personas.addTitle")}</h4>
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                    <div className="space-y-2">
                        <Label>{t("personas.nameLabel")}</Label>
                        <Input
                            placeholder={t("personas.namePlaceholder")}
                            value={newPersonaName}
                            onChange={(e) => setNewPersonaName(e.target.value)}
                        />
                    </div>
                    <div className="space-y-2">
                        <Label>{t("personas.descLabel")}</Label>
                        <Input
                            placeholder={t("personas.descPlaceholder")}
                            value={newPersonaDesc}
                            onChange={(e) => setNewPersonaDesc(e.target.value)}
                            onKeyDown={(e) => e.key === "Enter" && handleAddPersona()}
                        />
                    </div>
                </div>
                <Button onClick={handleAddPersona} variant="secondary">
                    {t("personas.submit")}
                </Button>
            </div>
        </TabsContent>
    );
}
