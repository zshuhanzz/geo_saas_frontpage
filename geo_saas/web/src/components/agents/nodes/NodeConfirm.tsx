import { CheckCircle2, Play, Save } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";

interface NodeConfirmProps {
  summary: {
    analyzerTask: string | null;
    metrics: string[];
    subgoals: string[];
    contentType: string;
    strategyCount: number;
    aiPlatforms: string[];
    publishPlatform: string;
    language: string;
    count: number;
    promptCount: number;
  };
  onExecute: () => void;
  onSaveDraft: () => void;
  executing: boolean;
}

export default function NodeConfirm({ summary, onExecute, onSaveDraft, executing }: NodeConfirmProps) {
  const { t } = useTranslation("content");
  const contentTypeLabel = (id: string): string =>
    t(`taskModal.contentTypes.items.${id}.label`, { defaultValue: id });

  const rows = [
    { label: t("nodes.confirm.summary.source"), value: summary.analyzerTask || t("nodes.confirm.summary.sourceEmpty") },
    { label: t("nodes.confirm.summary.metrics"), value: summary.metrics.join(", ") || t("nodes.confirm.summary.metricsEmpty") },
    { label: t("nodes.confirm.summary.subgoals"), value: summary.subgoals.join(", ") || t("nodes.confirm.summary.subgoalsEmpty") },
    { label: t("nodes.confirm.summary.contentType"), value: contentTypeLabel(summary.contentType) },
    { label: t("nodes.confirm.summary.strategyCount"), value: t("nodes.confirm.summary.strategyCountValue", { count: summary.strategyCount }) },
    { label: t("nodes.confirm.summary.aiPlatforms"), value: summary.aiPlatforms.join(", ") || t("nodes.confirm.summary.aiPlatformsEmpty") },
    { label: t("nodes.confirm.summary.publishPlatform"), value: summary.publishPlatform || t("nodes.confirm.summary.publishPlatformEmpty") },
    { label: t("nodes.confirm.summary.language"), value: summary.language },
    { label: t("nodes.confirm.summary.count"), value: String(summary.count) },
    { label: t("nodes.confirm.summary.linkedPrompts"), value: t("nodes.confirm.summary.linkedPromptsValue", { count: summary.promptCount }) },
  ];

  return (
    <div className="space-y-4">
      <div className="flex items-center gap-2 mb-2">
        <CheckCircle2 className="w-5 h-5 text-green-400" />
        <h3 className="text-lg font-semibold text-foreground">{t("nodes.confirm.title")}</h3>
      </div>

      <div className="border border-border rounded-lg divide-y divide-border">
        {rows.map((r) => (
          <div key={r.label} className="flex items-center justify-between px-4 py-2.5">
            <span className="text-sm text-muted-foreground">{r.label}</span>
            <span className="text-sm text-foreground">{r.value}</span>
          </div>
        ))}
      </div>

      <div className="flex gap-3 pt-2">
        <Button variant="outline" onClick={onSaveDraft} className="flex-1" disabled={executing}>
          <Save className="w-4 h-4 mr-2" />
          {t("nodes.confirm.saveDraft")}
        </Button>
        <Button onClick={onExecute} className="flex-1 bg-green-600 hover:bg-green-700" disabled={executing}>
          <Play className="w-4 h-4 mr-2" />
          {executing ? t("nodes.confirm.executing") : t("nodes.confirm.confirmExec")}
        </Button>
      </div>
    </div>
  );
}
