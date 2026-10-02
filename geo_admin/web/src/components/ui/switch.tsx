import * as React from "react"

import { cn } from "@/lib/utils"

/**
 * Lightweight Switch component mirroring the shadcn/ui Switch API
 * (`checked`, `onCheckedChange`, `disabled`) without pulling in
 * `@radix-ui/react-switch`. Uses a hidden native checkbox for
 * accessibility (keyboard, focus) wrapped in a styled track + thumb.
 */
export interface SwitchProps
    extends Omit<React.InputHTMLAttributes<HTMLInputElement>, "onChange" | "type"> {
    checked?: boolean
    onCheckedChange?: (checked: boolean) => void
}

const Switch = React.forwardRef<HTMLInputElement, SwitchProps>(
    ({ className, checked, onCheckedChange, disabled, ...props }, ref) => {
        return (
            <label
                className={cn(
                    "relative inline-flex h-5 w-9 shrink-0 cursor-pointer items-center rounded-full border-2 border-transparent shadow-sm transition-colors",
                    "focus-within:outline-none focus-within:ring-2 focus-within:ring-ring focus-within:ring-offset-2",
                    checked ? "bg-primary" : "bg-input",
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
                    className="sr-only"
                    {...props}
                />
                <span
                    aria-hidden="true"
                    className={cn(
                        "pointer-events-none block h-4 w-4 rounded-full bg-background shadow-lg ring-0 transition-transform",
                        checked ? "translate-x-4" : "translate-x-0",
                    )}
                />
            </label>
        )
    },
)
Switch.displayName = "Switch"

export { Switch }
