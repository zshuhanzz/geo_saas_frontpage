import { ArrowDown, ArrowUp } from "lucide-react";
import { useTranslation } from "react-i18next";
import { cn } from "@/lib/utils";
import {
    buildMetricSortAccessibility,
    defaultMetricSortDirection,
    isBusinessMetricSortKey,
    metricSortCurrentStateKey,
    nextMetricSort,
    type MetricSortDirection,
    type MetricSortState,
} from "@/lib/metricSort";

interface SortableMetricHeaderProps {
    label: string;
    metricKey: string;
    sort: MetricSortState | null;
    onChange: (next: MetricSortState) => void;
    defaultDirection?: MetricSortDirection;
    align?: "left" | "center" | "right";
    disabled?: boolean;
    className?: string;
}

export function SortableMetricHeader({
    label,
    metricKey,
    sort,
    onChange,
    defaultDirection = defaultMetricSortDirection(metricKey),
    align = "right",
    disabled = false,
    className,
}: SortableMetricHeaderProps) {
    const { t } = useTranslation("insights");
    if (!isBusinessMetricSortKey(metricKey)) {
        return (
            <span
                className={cn(
                    "inline-flex w-full items-center px-1 py-0.5 text-xs font-medium",
                    align === "right" && "justify-end",
                    align === "center" && "justify-center",
                    align === "left" && "justify-start",
                    className,
                )}
                data-metric-sort-blocked={metricKey}
            >
                {label}
            </span>
        );
    }
    const activeDirection = sort?.metricKey === metricKey ? sort.direction : null;
    const next = nextMetricSort(sort, metricKey, defaultDirection);
    const actionLabel = next.direction === "asc"
        ? t("metricSort.activateAscending", { label })
        : t("metricSort.activateDescending", { label });
    const accessibility = buildMetricSortAccessibility({
        actionLabel,
        currentStateLabel: t(metricSortCurrentStateKey(activeDirection)),
        direction: activeDirection,
    });

    return (
        <button
            type="button"
            className={cn(
                "inline-flex w-full items-center gap-1 rounded-sm px-1 py-0.5 text-xs font-medium hover:text-foreground focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring disabled:cursor-not-allowed disabled:opacity-50",
                align === "right" && "justify-end",
                align === "center" && "justify-center",
                align === "left" && "justify-start",
                className,
            )}
            {...accessibility}
            aria-pressed={activeDirection !== null}
            data-metric-sort-key={metricKey}
            disabled={disabled}
            onClick={(event) => {
                event.stopPropagation();
                onChange(next);
            }}
        >
            <span>{label}</span>
            <span className="inline-flex flex-col" aria-hidden="true">
                <ArrowUp className={cn("h-2.5 w-2.5 -mb-0.5", activeDirection === "asc" ? "text-primary" : "text-muted-foreground/45")} />
                <ArrowDown className={cn("h-2.5 w-2.5 -mt-0.5", activeDirection === "desc" ? "text-primary" : "text-muted-foreground/45")} />
            </span>
        </button>
    );
}
