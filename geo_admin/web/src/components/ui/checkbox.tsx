import * as React from "react"
import { Check } from "lucide-react"

import { cn } from "@/lib/utils"

/**
 * Lightweight Checkbox component mirroring the shadcn/ui Checkbox API
 * (`checked`, `onCheckedChange`, `disabled`) without pulling in
 * `@radix-ui/react-checkbox`. Uses a hidden native input wrapped in a
 * styled span so native form semantics (focus, keyboard) still work.
 */
export interface CheckboxProps
    extends Omit<React.InputHTMLAttributes<HTMLInputElement>, "onChange" | "type"> {
    checked?: boolean
    onCheckedChange?: (checked: boolean) => void
}

const Checkbox = React.forwardRef<HTMLInputElement, CheckboxProps>(
    ({ className, checked, onCheckedChange, disabled, ...props }, ref) => {
        return (
            <span
                className={cn(
                    "peer inline-flex h-4 w-4 shrink-0 items-center justify-center rounded-sm border border-primary shadow transition-colors",
                    "focus-within:outline-none focus-within:ring-1 focus-within:ring-ring",
                    checked
                        ? "bg-primary text-primary-foreground"
                        : "bg-transparent text-transparent",
                    disabled && "cursor-not-allowed opacity-50",
                    className,
                )}
            >
                <input
                    ref={ref}
                    type="checkbox"
                    checked={!!checked}
                    disabled={disabled}
                    onChange={(e) => onCheckedChange?.(e.target.checked)}
                    className="absolute h-4 w-4 cursor-pointer opacity-0"
                    {...props}
                />
                <Check className="h-3 w-3 pointer-events-none" strokeWidth={3} />
            </span>
        )
    },
)
Checkbox.displayName = "Checkbox"

export { Checkbox }
