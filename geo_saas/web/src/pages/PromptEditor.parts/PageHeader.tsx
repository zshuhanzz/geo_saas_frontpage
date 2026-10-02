import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { ChevronLeft } from "lucide-react";

interface PageHeaderProps {
    onBack: () => void;
    totalPrompts: number;
    clientQuota: number;
    quotaPercent: number;
}

export function PageHeader({ onBack, totalPrompts, clientQuota, quotaPercent }: PageHeaderProps) {
    const { t } = useTranslation("insights");
    return (
        <div className="flex items-center justify-between mb-6">
            <div className="flex items-center gap-3">
                <Button variant="ghost" size="sm" onClick={onBack}>
                    <ChevronLeft className="h-4 w-4 mr-1" /> {t("promptEditor.back")}
                </Button>
                <h1 className="text-2xl font-bold tracking-tight">{t("promptEditor.pageTitle")}</h1>
            </div>

            {/* Quota Progress */}
            <div className="text-right">
                <div className="text-xs text-muted-foreground mb-1">{t("promptEditor.quotaUsed", { used: totalPrompts, quota: clientQuota })}</div>
                <div className="w-40 h-2 bg-muted rounded-full overflow-hidden">
                    <div
                        className={`h-full rounded-full transition-all ${quotaPercent > 90 ? 'bg-red-500' : quotaPercent > 70 ? 'bg-yellow-500' : 'bg-primary'}`}
                        style={{ width: `${quotaPercent}%` }}
                    />
                </div>
            </div>
        </div>
    );
}
