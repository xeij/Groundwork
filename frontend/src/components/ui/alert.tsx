import * as React from "react";
import { cva } from "class-variance-authority";
import type { VariantProps } from "class-variance-authority";

import { cn } from "@/lib/utils";

const alertVariants = cva("relative w-full rounded-lg border px-4 py-3 text-sm", {
  variants: {
    variant: {
      default: "bg-card border-border text-card-foreground",
      destructive: "border-destructive/40 bg-destructive/10 text-destructive [&>*]:text-current",
    },
  },
  defaultVariants: {
    variant: "default",
  },
});

interface AlertProps extends React.ComponentProps<"div">, VariantProps<typeof alertVariants> {}

function Alert({ className, variant, ...props }: AlertProps) {
  return <div role="alert" className={cn(alertVariants({ variant }), className)} {...props} />;
}

function AlertDescription({ className, ...props }: React.ComponentProps<"div">) {
  return <div className={cn("leading-relaxed", className)} {...props} />;
}

export { Alert, AlertDescription };
