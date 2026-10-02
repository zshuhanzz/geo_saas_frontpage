/**
 * Premium glass-style tooltip for Recharts.
 * Usage: <Tooltip content={<GlassTooltip />} />
 */
import { cn } from "@/lib/utils";

interface GlassTooltipProps {
    active?: boolean;
    payload?: any[];
    label?: any;
    labelFormatter?: (label: any) => string;
    formatter?: (value: any, name: string) => [string, string];
}

export function GlassTooltip({ active, payload, label, labelFormatter, formatter }: GlassTooltipProps) {
    if (!active || !payload?.length) return null;

    const displayLabel = labelFormatter ? labelFormatter(label) : String(label);

    return (
        <div className={cn(
            "px-3 py-2.5 rounded-lg border shadow-lg backdrop-blur-xl min-w-[120px]",
            "bg-card/95 dark:bg-card/90 border-border/50",
            "text-xs"
        )}>
            <div className="text-muted-foreground mb-1.5 font-medium">{displayLabel}</div>
            {payload.map((entry: any, i: number) => {
                const [val, name] = formatter
                    ? formatter(entry.value, entry.name)
                    : [String(entry.value), entry.name];
                return (
                    <div key={i} className="flex items-center gap-2 py-0.5">
                        <div
                            className="w-2 h-2 rounded-full shrink-0"
                            style={{ backgroundColor: entry.color || entry.stroke }}
                        />
                        <span className="text-muted-foreground">{name}:</span>
                        <span className="font-semibold text-foreground ml-auto">{val}</span>
                    </div>
                );
            })}
        </div>
    );
}
