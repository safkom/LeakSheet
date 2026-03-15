import type { VariantProps } from "class-variance-authority"
import { cva } from "class-variance-authority"

export { default as Badge } from "./Badge.vue"

export const badgeVariants = cva(
  "inline-flex gap-1 items-center border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 rounded-[6px] whitespace-nowrap",
  {
    variants: {
      variant: {
        default:
          "border-transparent bg-primary text-primary-foreground hover:bg-primary/80",
        secondary:
          "border-transparent bg-secondary text-secondary-foreground hover:bg-secondary/80",
        destructive:
          "border-transparent bg-destructive text-destructive-foreground hover:bg-destructive/80",
        outline: "text-foreground",
        // Quality badge variants (using CSS variable tokens)
        og: "border-transparent bg-[hsl(var(--badge-og)/0.15)] text-[hsl(var(--badge-og))]",
        hq: "border-transparent bg-[hsl(var(--badge-hq)/0.15)] text-[hsl(var(--badge-hq))]",
        cd: "border-transparent bg-[hsl(var(--badge-cd)/0.15)] text-[hsl(var(--badge-cd))]",
        lq: "border-transparent bg-[hsl(var(--badge-lq)/0.15)] text-[hsl(var(--badge-lq))]",
        rec: "border-transparent bg-[hsl(var(--badge-rec)/0.15)] text-[hsl(var(--badge-rec))]",
        na: "border-transparent bg-[hsl(var(--badge-na)/0.15)] text-[hsl(var(--badge-na))]",
        // Availability badge variants
        ogfile: "border-transparent bg-[hsl(var(--badge-og)/0.15)] text-[hsl(var(--badge-og))]",
        full: "border-transparent bg-[hsl(var(--badge-og)/0.15)] text-[hsl(var(--badge-og))]",
        tagged: "border-transparent bg-[hsl(var(--badge-cd)/0.15)] text-[hsl(var(--badge-cd))]",
        stem: "border-transparent bg-[hsl(var(--badge-hq)/0.15)] text-[hsl(var(--badge-hq))]",
        partial: "border-transparent bg-[hsl(var(--badge-lq)/0.15)] text-[hsl(var(--badge-lq))]",
        snippet: "border-transparent bg-[hsl(var(--badge-rec)/0.15)] text-[hsl(var(--badge-rec))]",
        confirmed: "border-transparent bg-[hsl(var(--badge-hq)/0.15)] text-[hsl(var(--badge-hq))]",
        unavailable: "border-transparent bg-[hsl(var(--badge-na)/0.15)] text-[hsl(var(--badge-na))]",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
)

export type BadgeVariants = VariantProps<typeof badgeVariants>
