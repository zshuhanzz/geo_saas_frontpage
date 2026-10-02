import { useTranslation } from "react-i18next";

export default function Fanouts() {
    const { t } = useTranslation(["insights", "common"]);
    return (
        <div className="h-full flex flex-col items-center justify-center space-y-3 text-center py-24">
            <h2 className="text-2xl font-semibold text-foreground">{t("fanouts.title")}</h2>
            <p className="text-muted-foreground max-w-sm">
                {t("common:states.comingSoon")}
            </p>
        </div>
    );
}
