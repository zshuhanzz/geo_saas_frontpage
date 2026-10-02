import { useTranslation } from "react-i18next";

export default function AgentTracking() {
  const { t } = useTranslation("agents");
  return (
    <div className="h-full flex flex-col items-center justify-center space-y-4">
      <div className="w-16 h-16 rounded-2xl bg-gradient-to-br from-primary/20 to-primary/5 flex items-center justify-center">
        <svg xmlns="http://www.w3.org/2000/svg" width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" className="text-primary"><circle cx="12" cy="12" r="10"/><circle cx="12" cy="12" r="6"/><circle cx="12" cy="12" r="2"/></svg>
      </div>
      <h2 className="text-2xl font-semibold text-foreground">{t("tracking.pageTitle")}</h2>
      <p className="text-muted-foreground text-sm max-w-md text-center">
        {t("tracking.subtitle")} {t("tracking.comingSoon")}.
      </p>
      <span className="inline-flex items-center px-3 py-1 rounded-full text-xs font-medium bg-muted text-muted-foreground">
        {t("tracking.comingSoon")}
      </span>
    </div>
  );
}
