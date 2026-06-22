import * as React from "react";
import { cva, type VariantProps } from "class-variance-authority";
import { cn } from "@/app/lib/utils";

const buttonVariants = cva(
  "inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50",
  {
    variants: {
      variant: {
        default:
          "bg-[var(--primary)] text-white hover:opacity-90 focus-visible:ring-[var(--primary)]",
        coral:
          "bg-[#ff6b4a] text-white hover:bg-[#e85a39] focus-visible:ring-[#ff6b4a]",
        destructive:
          "bg-[var(--danger)] text-white hover:opacity-90 focus-visible:ring-[var(--danger)]",
        outline:
          "border border-[var(--border)] bg-transparent hover:bg-[var(--surface-low)] focus-visible:ring-[var(--primary)]",
        secondary:
          "bg-[var(--surface-high)] text-[var(--ink)] hover:bg-[var(--surface-low)] focus-visible:ring-[var(--primary)]",
        ghost:
          "hover:bg-[var(--surface-low)] text-[var(--ink)] focus-visible:ring-[var(--primary)]",
        link: "text-[var(--primary)] underline-offset-4 hover:underline",
      },
      size: {
        default: "h-9 px-4 py-2",
        sm: "h-7 rounded-md px-3 text-xs",
        lg: "h-11 rounded-md px-8 text-base",
        icon: "h-9 w-9",
      },
    },
    defaultVariants: {
      variant: "default",
      size: "default",
    },
  }
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, ...props }, ref) => {
    return (
      <button
        className={cn(buttonVariants({ variant, size, className }))}
        ref={ref}
        {...props}
      />
    );
  }
);
Button.displayName = "Button";

export { Button, buttonVariants };
