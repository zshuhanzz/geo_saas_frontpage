import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import TaskProgressCard from "../../TaskProgressCard";

interface RunningViewProps {
  taskId: string;
  onCompleted: (taskId: string) => void;
  onClose: () => void;
}

export function RunningView({ taskId, onCompleted, onClose }: RunningViewProps) {
  const { t } = useTranslation("content");
  return (
    <div className="flex-1 overflow-auto p-6">
      <TaskProgressCard
        taskId={taskId}
        initialStatus="RUNNING"
        onCompleted={onCompleted}
      />
      <p className="text-xs text-muted-foreground text-center mt-4">
        {t("taskModal.runningCard.closeHint")}
      </p>
      <div className="flex justify-center mt-3">
        <Button variant="outline" size="sm" onClick={onClose}>{t("taskModal.runningCard.close")}</Button>
      </div>
    </div>
  );
}
