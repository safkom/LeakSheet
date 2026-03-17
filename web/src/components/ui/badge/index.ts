import type { VariantProps } from "class-variance-authority"
import { cva } from "class-variance-authority"

export { default as Badge } from "./Badge.vue"

export const badgeVariants = cva(
  "inline-flex gap-1 items-center border px-2 py-0.5 text-[11px] font-bold uppercase tracking-wide transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 rounded-[6px] whitespace-nowrap",
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
        og: "border-transparent bg-[hsl(var(--badge-og)/0.25)] text-[hsl(var(--badge-og))]",
        lossless: "border-transparent bg-[hsl(var(--badge-lossless)/0.25)] text-[hsl(var(--badge-lossless))]",
        hq: "border-transparent bg-[hsl(var(--badge-hq)/0.25)] text-[hsl(var(--badge-hq))]",
        cd: "border-transparent bg-[hsl(var(--badge-cd)/0.25)] text-[hsl(var(--badge-cd))]",
        lq: "border-transparent bg-[hsl(var(--badge-lq)/0.25)] text-[hsl(var(--badge-lq))]",
        rec: "border-white/15 bg-black/50 text-white/60",
        na: "border-transparent bg-[hsl(var(--badge-na)/0.15)] text-[hsl(var(--badge-na))]",
        beatonly: "border-transparent bg-[hsl(var(--badge-beatonly)/0.25)] text-[hsl(var(--badge-beatonly))]",
        // Availability badge variants
        ogfile: "border-transparent bg-[hsl(var(--badge-ogfile)/0.25)] text-[hsl(var(--badge-ogfile))]",
        full: "border-transparent bg-[hsl(var(--badge-full)/0.25)] text-[hsl(var(--badge-full))]",
        tagged: "border-transparent bg-[hsl(var(--badge-tagged)/0.25)] text-[hsl(var(--badge-tagged))]",
        stem: "border-transparent bg-[hsl(var(--badge-stem)/0.25)] text-[hsl(var(--badge-stem))]",
        partial: "border-transparent bg-[hsl(var(--badge-partial)/0.25)] text-[hsl(var(--badge-partial))]",
        snippet: "border-transparent bg-[hsl(var(--badge-snippet)/0.25)] text-[hsl(var(--badge-snippet))]",
        confirmed: "border-transparent bg-[hsl(var(--badge-confirmed)/0.25)] text-[hsl(var(--badge-confirmed))]",
        unavailable: "border-transparent bg-[hsl(var(--badge-na)/0.15)] text-[hsl(var(--badge-na))]",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
)

export type BadgeVariants = VariantProps<typeof badgeVariants>
