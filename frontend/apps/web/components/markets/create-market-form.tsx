"use client"

import { useCallback, useState } from "react"
import { useForm, useFieldArray } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { z } from "zod"
import { Button } from "@workspace/ui/components/button"
import { Input } from "@workspace/ui/components/input"
import { Spinner } from "@workspace/ui/components/spinner"
import {
  Field,
  FieldContent,
  FieldError,
} from "@workspace/ui/components/field"
import { cn } from "@workspace/ui/lib/utils"
import { useCreateMarket } from "@/hooks/api/use-markets"
import { sileo } from "sileo"

const createMarketSchema = z.object({
  question: z.string().min(5, "Question must be at least 5 characters").max(1000),
  description: z.string().max(5000).optional(),
  category: z.string().max(100).optional(),
  slug: z.string().min(3, "Slug must be at least 3 characters").max(255).regex(/^[a-z0-9-]+$/, "Slug can only contain lowercase letters, numbers, and hyphens"),
  closes_at: z.string().min(1, "Close date is required"),
  initial_liquidity: z.number().min(0),
  initial_probability: z.number().min(0.01).max(0.99).optional(),
  outcomes: z.array(z.object({
    name: z.string().min(1, "Outcome name is required").max(100),
  })).min(2, "At least 2 outcomes are required"),
})

type CreateMarketInput = z.infer<typeof createMarketSchema>

export function CreateMarketForm() {
  const [serverError, setServerError] = useState<string | null>(null)

  const form = useForm<CreateMarketInput>({
    resolver: zodResolver(createMarketSchema),
    defaultValues: {
      question: "",
      description: "",
      category: "",
      slug: "",
      closes_at: "",
      initial_liquidity: 0,
      initial_probability: undefined,
      outcomes: [
        { name: "Yes" },
        { name: "No" },
      ],
    },
  })

  const { fields, append, remove } = useFieldArray({
    control: form.control,
    name: "outcomes",
  })

  const createMarket = useCreateMarket()

  const onSubmit = useCallback(async (data: CreateMarketInput) => {
    setServerError(null)
    try {
      await createMarket.mutateAsync({
        question: data.question,
        description: data.description || undefined,
        category: data.category || undefined,
        slug: data.slug,
        closes_at: new Date(data.closes_at).toISOString(),
        initial_liquidity: data.initial_liquidity,
        initial_probability: data.initial_probability,
        outcomes_create: data.outcomes.map((o, i) => ({ name: o.name, outcome_index: i })),
      })
      sileo.success({ title: "Market created!" })
      form.reset()
    } catch (e) {
      setServerError(e instanceof Error ? e.message : "Failed to create market")
      sileo.error({ title: "Create failed", description: e instanceof Error ? e.message : "Unknown error" })
    }
  }, [createMarket, form])

  return (
    <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
      {serverError && (
        <div className="rounded-md bg-destructive/10 border border-destructive/30 p-3 text-xs text-destructive">
          {serverError}
        </div>
      )}

      <Field>
        <FieldContent>
          <label className="text-xs font-medium text-foreground mb-1.5 block">Question *</label>
          <Input
            {...form.register("question")}
            placeholder="Will X happen by Y date?"
            className={cn(form.formState.errors.question && "border-destructive")}
          />
          {form.formState.errors.question && (
            <FieldError>{form.formState.errors.question.message}</FieldError>
          )}
        </FieldContent>
      </Field>

      <Field>
        <FieldContent>
          <label className="text-xs font-medium text-foreground mb-1.5 block">Description</label>
          <textarea
            {...form.register("description")}
            placeholder="Additional context (optional)"
            rows={3}
            className={cn(
              "w-full rounded-md border border-border bg-background px-3 py-2 text-sm focus:outline-none focus:ring-1 focus:ring-ring resize-none",
              form.formState.errors.description && "border-destructive"
            )}
          />
        </FieldContent>
      </Field>

      <div className="grid grid-cols-2 gap-3">
        <Field>
          <FieldContent>
            <label className="text-xs font-medium text-foreground mb-1.5 block">Slug *</label>
            <Input
              {...form.register("slug")}
              placeholder="will-x-happen"
              className={cn(form.formState.errors.slug && "border-destructive")}
            />
            {form.formState.errors.slug && (
              <FieldError>{form.formState.errors.slug.message}</FieldError>
            )}
          </FieldContent>
        </Field>

        <Field>
          <FieldContent>
            <label className="text-xs font-medium text-foreground mb-1.5 block">Category</label>
            <Input
              {...form.register("category")}
              placeholder="e.g. Politics, Sports"
              className={cn(form.formState.errors.category && "border-destructive")}
            />
          </FieldContent>
        </Field>
      </div>

      <Field>
        <FieldContent>
          <label className="text-xs font-medium text-foreground mb-1.5 block">Close Date *</label>
          <Input
            type="datetime-local"
            {...form.register("closes_at")}
            className={cn(form.formState.errors.closes_at && "border-destructive")}
          />
          {form.formState.errors.closes_at && (
            <FieldError>{form.formState.errors.closes_at.message}</FieldError>
          )}
        </FieldContent>
      </Field>

      <div className="grid grid-cols-2 gap-3">
        <Field>
          <FieldContent>
            <label className="text-xs font-medium text-foreground mb-1.5 block">Initial Liquidity</label>
            <Input
              type="number"
              step="any"
              min="0"
              {...form.register("initial_liquidity", { valueAsNumber: true })}
              className={cn(form.formState.errors.initial_liquidity && "border-destructive")}
            />
          </FieldContent>
        </Field>

        <Field>
          <FieldContent>
            <label className="text-xs font-medium text-foreground mb-1.5 block">Initial Probability (Yes)</label>
            <Input
              type="number"
              step="any"
              min="0.01"
              max="0.99"
              {...form.register("initial_probability", { valueAsNumber: true })}
              placeholder="0.5"
              className={cn(form.formState.errors.initial_probability && "border-destructive")}
            />
          </FieldContent>
        </Field>
      </div>

      <Field>
        <FieldContent>
          <label className="text-xs font-medium text-foreground mb-1.5 block">Outcomes *</label>
          <div className="space-y-2">
            {fields.map((field, index) => (
              <div key={field.id} className="flex items-center gap-2">
                <Input
                  {...form.register(`outcomes.${index}.name`)}
                  placeholder={`Outcome ${index + 1}`}
                  className={cn(
                    form.formState.errors.outcomes?.[index]?.name && "border-destructive"
                  )}
                />
                {fields.length > 2 && (
                  <Button
                    type="button"
                    variant="ghost"
                    size="sm"
                    onClick={() => remove(index)}
                    className="text-destructive hover:text-destructive"
                  >
                    Remove
                  </Button>
                )}
              </div>
            ))}
            {form.formState.errors.outcomes?.root && (
              <FieldError>{form.formState.errors.outcomes.root.message}</FieldError>
            )}
          </div>
          <Button
            type="button"
            variant="outline"
            size="sm"
            onClick={() => append({ name: "" })}
            className="mt-2"
          >
            Add Outcome
          </Button>
        </FieldContent>
      </Field>

      <Button
        type="submit"
        disabled={createMarket.isPending}
        className="w-full"
      >
        {createMarket.isPending ? <Spinner className="mr-2" /> : null}
        {createMarket.isPending ? "Creating..." : "Create Market"}
      </Button>
    </form>
  )
}
