import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";

export function StaticListErrorState({ onRetry }: { onRetry: () => void }) {
  const { t } = useTranslation("reports");
  const { t: commonT } = useTranslation("common");
  return (
    <div role="alert" className="flex items-center justify-between gap-3 rounded-md border border-destructive/30 bg-destructive/5 px-3 py-2 text-sm">
      <span>{t("detail.listLoadError")}</span>
      <Button type="button" variant="outline" size="sm" onClick={onRetry}>{commonT("actions.retry")}</Button>
    </div>
  );
}
