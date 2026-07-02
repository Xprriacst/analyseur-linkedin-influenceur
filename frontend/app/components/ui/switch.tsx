"use client";

import * as React from "react";
import { cn } from "@/app/lib/utils";

export interface SwitchProps extends React.InputHTMLAttributes<HTMLInputElement> {
  onCheckedChange?: (checked: boolean) => void;
}

const Switch = React.forwardRef<HTMLInputElement, SwitchProps>(
  ({ className, onCheckedChange, onChange, checked, ...props }, ref) => {
    const handleChange = (e: React.ChangeEvent<HTMLInputElement>) => {
      onChange?.(e);
      onCheckedChange?.(e.target.checked);
    };

    return (
      <label
        className={cn(
          "relative inline-flex h-5 w-9 cursor-pointer items-center",
          className
        )}
      >
        <input
          type="checkbox"
          className="peer sr-only"
          ref={ref}
          checked={checked}
          onChange={handleChange}
          {...props}
        />
        <span
          className={cn(
            "absolute inset-0 rounded-full transition-colors",
            "bg-[var(--surface-high)] peer-checked:bg-[var(--primary)]",
            "peer-focus-visible:ring-2 peer-focus-visible:ring-[var(--primary)] peer-focus-visible:ring-offset-1",
            "peer-disabled:cursor-not-allowed peer-disabled:opacity-50"
          )}
        />
        <span
          className={cn(
            "absolute left-0.5 top-0.5 h-4 w-4 rounded-full bg-white shadow transition-transform",
            "peer-checked:translate-x-4"
          )}
        />
      </label>
    );
  }
);
Switch.displayName = "Switch";

export { Switch };
