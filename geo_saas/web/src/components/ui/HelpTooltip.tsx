/**
 * HelpTooltip — thin wrapper over shadcn/radix <Tooltip> that renders a
 * uniform "(i) info" glyph next to a label or control.
 *
 * Phase 5 intentionally ships the component with empty / placeholder copy at
 * every call-site; Phase 7 batch-fills the final zh-CN strings from Spec
 * §10.2. Keeping the wrapper in place now means Phase 7 is a pure search +
 * replace on `__TBD_PHASE_7__` sentinels, rather than a hunt-and-peck through
 * every new settings / insights component.
 *
 * Usage:
 *   <HelpTooltip content="短说明">
 *     <span>我的品牌</span>
 *   </HelpTooltip>
 *
 *   // icon-only — renders a small inline (i) glyph:
 *   <HelpTooltip content="..." />
 *
 * Design note (2026-04-21): ONLY the (i) icon is the tooltip trigger. The
 * optional `children` render next to the icon but hovering over them does
 * NOT open the tooltip. This prevents the "tooltip latches on and covers
 * the now-open Select dropdown" class of bugs — the tooltip's open state
 * is driven exclusively by pointer interaction with the icon itself.
 */
import type { ReactNode } from "react";
import { Info } from "lucide-react";
import {
    Tooltip,
    TooltipContent,
    TooltipProvider,
    TooltipTrigger,
} from "@/components/ui/tooltip";
import { cn } from "@/lib/utils";

// Sentinel for Phase 7 copywriter: grep this string and fill with the final
// zh-CN copy per Spec §10.2. Keep both spellings in one place so the sweep
// is mechanical.
export const TOOLTIP_TBD = "__TBD_PHASE_7__";

interface HelpTooltipProps {
    /** Tooltip body text. Pass TOOLTIP_TBD in Phase 5 — Phase 7 fills final copy. */
    content: string;
    /** Optional label / control rendered next to the icon. NOT a tooltip
     *  trigger — only the (i) icon triggers the tooltip. */
    children?: ReactNode;
    /** Extra classes on the wrapper. */
    className?: string;
    /** Placement hint for the Tooltip. */
    side?: "top" | "right" | "bottom" | "left";
}

export function HelpTooltip({ content, children, className, side = "top" }: HelpTooltipProps) {
    // An empty or TBD string still renders — we want Phase 7 to see every call
    // site. But don't show a tooltip body that literally says "__TBD_PHASE_7__"
    // to end users — render a placeholder dash instead so a shipping build
    // doesn't leak the sentinel into the UI.
    const body = content === TOOLTIP_TBD || content.trim() === "" ? "—" : content;

    // Only the (i) glyph is wrapped in TooltipTrigger. The optional children
    // render alongside but do not participate in the trigger — their own
    // hover/focus behaviour (e.g. a <Select> opening its menu) is untouched.
    const icon = (
        <TooltipTrigger asChild>
            <span
                className="inline-flex items-center justify-center cursor-help text-muted-foreground/70 hover:text-muted-foreground transition-colors"
                tabIndex={0}
                role="button"
                aria-label="More info"
            >
                <Info className={children ? "h-3 w-3" : "h-3.5 w-3.5"} aria-hidden="true" />
            </span>
        </TooltipTrigger>
    );

    return (
        <TooltipProvider delayDuration={150}>
            <Tooltip>
                {children ? (
                    <span className={cn("inline-flex items-center gap-1", className)}>
                        {children}
                        {icon}
                    </span>
                ) : (
                    <span className={className}>{icon}</span>
                )}
                <TooltipContent side={side} className="max-w-xs text-xs leading-relaxed">
                    {body}
                </TooltipContent>
            </Tooltip>
        </TooltipProvider>
    );
}

export default HelpTooltip;
