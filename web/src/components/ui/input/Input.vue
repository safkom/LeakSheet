<script setup lang="ts">
import type { HTMLAttributes } from "vue"
import { useVModel } from "@vueuse/core"
import { cn } from "@/lib/utils"

const props = defineProps<{
  defaultValue?: string | number
  modelValue?: string | number
  class?: HTMLAttributes["class"]
  variant?: "default" | "ghost"
}>()

const emits = defineEmits<{
  (e: "update:modelValue", payload: string | number): void
}>()

const modelValue = useVModel(props, "modelValue", emits, {
  passive: true,
  defaultValue: props.defaultValue,
})

const baseClasses = "flex w-full text-sm file:border-0 file:bg-transparent file:text-foreground file:text-sm file:font-medium placeholder:text-muted-foreground focus-visible:outline-none disabled:cursor-not-allowed disabled:opacity-50"

const variantClasses = {
  default: "h-10 rounded-md border border-input bg-background px-3 py-2 ring-offset-background focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2",
  ghost: "h-auto bg-transparent border-0 rounded-none p-0 shadow-none ring-0 ring-offset-0 focus-visible:ring-0 focus-visible:ring-offset-0",
}
</script>

<template>
  <input v-model="modelValue" :class="cn(baseClasses, variantClasses[variant ?? 'default'], props.class)">
</template>
