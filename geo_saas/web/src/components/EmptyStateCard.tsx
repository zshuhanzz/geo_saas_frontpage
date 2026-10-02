/**
 * EmptyStateCard — Spec §8.5 standard empty-state renderer.
 *
 * Used by every chart that depends on a data-driven availability flag (see
 * /api/insights/availability). Rendering this card instead of an empty chart
 * answers the "why is this blank?" question for the user with a concrete
 * pointer to the setting they need to configure.
 *
 * Visual language follows the existing Profound-style (muted card, primary
 * accent on the icon, compact CTA) so empty states sit naturally between
 * real chart cards without breaking the page rhythm.
 */
import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { Card, CardContent } from "@/components/ui/card";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";

interface EmptyStateCardProps {
    icon?: ReactNode;
    title: string;
    description?: string;
    /** Optional CTA label — if provided, ``ctaHref`` is required. */
    ctaLabel?: string;
    /** React Router path. External URLs use <a> fallback. */
    ctaHref?: string;
    /** Smaller muted caption under the CTA. */
    secondaryInfo?: string;
    /** Add margin/padding tweaks for embedding in different layouts. */
    className?: string;
}

export function EmptyStateCard({
    icon,
    title,
    description,
    ctaLabel,
    ctaHref,
    secondaryInfo,
    className,
}: EmptyStateCardProps) {
    return (
        <Card className={cn("border-dashed bg-muted/20 shadow-none", className)}>
            <CardContent className="py-10 px-6 flex flex-col items-center justify-center text-center gap-3">
                {icon && (
                    <div className="h-10 w-10 rounded-full bg-primary/10 text-primary flex items-center justify-center">
                        {icon}
                    </div>
                )}
                <div className="space-y-1">
                    <div className="text-sm font-semibold text-foreground">{title}</div>
                    {description && (
                        <div className="text-xs text-muted-foreground max-w-md mx-auto leading-relaxed">
                            {description}
                        </div>
                    )}
                </div>
                {ctaLabel && ctaHref && (
                    <Button asChild size="sm" variant="secondary" className="mt-2">
                        {ctaHref.startsWith("http") ? (
                            <a href={ctaHref} target="_blank" rel="noreferrer">
                                {ctaLabel}
                            </a>
                        ) : (
                            <Link to={ctaHref}>{ctaLabel}</Link>
                        )}
                    </Button>
                )}
                {secondaryInfo && (
                    <div className="text-[11px] text-muted-foreground/80 max-w-md mx-auto">
                        {secondaryInfo}
                    </div>
                )}
            </CardContent>
        </Card>
    );
}

export default EmptyStateCard;
