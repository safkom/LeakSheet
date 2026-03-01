import type { VariantProps } from "class-variance-authority"
import { cva } from "class-variance-authority"

export { default as Badge } from "./Badge.vue"

export const badgeVariants = cva(
  "inline-flex gap-1 items-center border px-1.5 py-0.5 text-[10px] font-semibold uppercase tracking-wide transition-colors focus:outline-none focus:ring-2 focus:ring-ring focus:ring-offset-2 rounded-[3px] whitespace-nowrap",
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
        // Quality badge variants
        og: "border-transparent bg-[rgba(78,205,196,0.15)] text-[#4ecdc4]",
        hq: "border-transparent bg-[rgba(88,166,255,0.15)] text-[#58a6ff]",
        cd: "border-transparent bg-[rgba(163,113,247,0.15)] text-[#a371f7]",
        lq: "border-transparent bg-[rgba(240,136,62,0.15)] text-[#f0883e]",
        rec: "border-transparent bg-[rgba(210,168,255,0.15)] text-[#d2a8ff]",
        na: "border-transparent bg-[rgba(82,90,101,0.15)] text-[#525a65]",
        // Availability badge variants
        full: "border-transparent bg-[rgba(78,205,196,0.15)] text-[#4ecdc4]",
        partial: "border-transparent bg-[rgba(240,136,62,0.15)] text-[#f0883e]",
        snippet: "border-transparent bg-[rgba(210,168,255,0.15)] text-[#d2a8ff]",
        confirmed: "border-transparent bg-[rgba(88,166,255,0.15)] text-[#58a6ff]",
        unavailable: "border-transparent bg-[rgba(82,90,101,0.15)] text-[#525a65]",
      },
    },
    defaultVariants: {
      variant: "default",
    },
  },
)

export type BadgeVariants = VariantProps<typeof badgeVariants>
