"use client"

/**
 * Proposing a market.
 *
 * ## Why this exists as a page rather than dead code
 *
 * A fully built form was sitting in the repo with no route pointing at it. The
 * backend endpoint had been there all along. So from the outside, the ability to
 * create a market simply did not exist.
 *
 * ## What this form is careful about
 *
 * **The slug is derived, not typed.** Asking someone to hand-write a URL slug is
 * a request to guess at our storage format, and every wrong guess is a 422 they
 * cannot act on. It is generated from the question, kept editable, and validated
 * against the server's actual rule — which is stricter than the old regex here
 * allowed (`^[a-z0-9-]+$` accepts leading, trailing and doubled hyphens; the API
 * requires `^[a-z0-9]+(?:-[a-z0-9]+)*$`).
 *
 * **Two outcomes, not N.** The form used to offer "Add Outcome" and let a user
 * build a five-way market that the API rejects — `outcome_index` is capped at 1,
 * so index 2 is a 422. Offering a control the server cannot honour is worse than
 * not offering it, so the outcomes are fixed at Yes/No and stated as such.
 *
 * **The empty optional number is not NaN.** The old form registered the initial
 * probability with `valueAsNumber`, so an untouched input submitted `NaN`, which
 * fails `ge=0.01` — every user who skipped the field got a validation error on
 * an optional field. Blank is now normalised to "omit the key".
 *
 * **Resolution criteria are asked for up front.** A market with no stated way to
 * settle it can only be resolved by guess or by dispute, and both cost every
 * participant far more than answering one extra question. It is optional — many
 * questions are self-resolving — but it is the first optional field, not the
 * last.
 */

import { useCallback, useMemo, useState } from "react"
import { useRouter } from "next/navigation"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { AlertCircle, CheckCircle2, Clock } from "lucide-react"
import { z } from "zod"
import { sileo } from "sileo"

import { Button } from "@workspace/ui/components/button"
import { Input } from "@workspace/ui/components/input"
import { Textarea } from "@workspace/ui/components/textarea"
import { Spinner } from "@workspace/ui/components/spinner"
import { Alert, AlertDescription, AlertTitle } from "@workspace/ui/components/alert"
import {
  Field,
  FieldContent,
  FieldDescription,
  FieldError,
  FieldLabel,
} from "@workspace/ui/components/field"
import { useCreateMarket } from "@/hooks/api/use-markets"
import { apiErrorMessage } from "@/lib/api/client"

/**
 * The API's rule, mirrored.
 *
 * Deliberately the server's regex rather than the looser `^[a-z0-9-]+$` this file
 * used to use. The looser one passes client validation and fails at the API, so
 * the user fills the form in, presses submit, and is told they did something
 * wrong by a field they were told was valid.
 */
const SLUG_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/

const createMarketSchema = z.object({
  question: z
    .string()
    .trim()
    .min(10, "Ask a full question — at least 10 characters.")
    .max(1000, "Keep the question under 1000 characters."),
  description: z.string().trim().max(5000).optional(),
  category: z.string().trim().max(100).optional(),
  subcategory: z.string().trim().max(100).optional(),
  // An untouched optional text input submits `""`, and `.optional()` only skips
  // `undefined` — so the empty string reached `.url()` and the whole form
  // refused to submit with "That has to be a full URL" on a field nobody filled
  // in. Accepting the blank as a member of the union is what `optional` was
  // meant to express, and it keeps zod's input and output types identical —
  // which `z.preprocess` would not, and a mismatch there breaks the generic on
  // `useForm` in a way whose error message points nowhere near the schema.
  image_url: z
    .union([
      z.literal(""),
      z
        .string()
        .trim()
        .min(1)
        .max(500)
        .url("That has to be a full URL, including https://")
        .refine((v) => /^https?:\/\//i.test(v), {
          message: "Only http:// and https:// image URLs are allowed.",
        }),
    ])
    .optional(),
  slug: z
    .string()
    .trim()
    .min(3, "A slug needs at least 3 characters.")
    .max(255)
    .regex(SLUG_PATTERN, "Use lowercase letters, numbers, and single hyphens only."),
  closes_at: z.string().min(1, "A close date is required."),
  resolution_criteria: z.string().trim().max(2000).optional(),
  resolution_source: z.string().trim().max(1000).optional(),
  initial_liquidity: z
    .union([z.number(), z.nan()])
    .transform((n) => (Number.isFinite(n) && n > 0 ? n : 0))
    .pipe(z.number().min(0, "Liquidity cannot be negative.")),
  initial_probability: z
    .union([z.number(), z.nan()])
    .optional()
    .transform((n) => (n === undefined || !Number.isFinite(n) ? undefined : n))
    .pipe(z.number().min(0.01).max(0.99).optional()),
})

type CreateMarketInput = z.infer<typeof createMarketSchema>

/**
 * Turn a question into a slug.
 *
 * Strips the punctuation people actually put in questions, collapses runs of
 * separators into a single hyphen, and trims hyphens off both ends — which is
 * exactly the case the old client regex let through and the API rejected.
 */
function slugify(question: string): string {
  return question
    .toLowerCase()
    .normalize("NFKD")
    // Drop combining marks so "Café" → "cafe" rather than "caf".
    .replace(/[̀-ͯ]/g, "")
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 255)
    .replace(/-+$/g, "")
}

export function CreateMarketForm() {
  const router = useRouter()
  const createMarket = useCreateMarket()

  /**
   * Whether the user has taken the derived slug over.
   *
   * Only then does the question stop driving it. Without this, typing a single
   * character into the question rewrites the slug and undoes any manual fix —
   * which is the behaviour that made hand-editing feel impossible.
   */
  const [slugTouched, setSlugTouched] = useState(false)

  const form = useForm<CreateMarketInput>({
    resolver: zodResolver(createMarketSchema),
    mode: "onBlur",
    defaultValues: {
      question: "",
      description: "",
      category: "",
      subcategory: "",
      image_url: "",
      slug: "",
      closes_at: "",
      resolution_criteria: "",
      resolution_source: "",
      initial_liquidity: 0,
      initial_probability: undefined,
    },
  })

  const slugValue = form.watch("slug")

  /**
   * Registered once, then wrapped.
   *
   * Calling `form.register("question")` inside the `onChange` body — as the first
   * version of this did — hands react-hook-form a *new* registration object on
   * every keystroke, which detaches the ref bookkeeping and leaves the field
   * permanently empty and unsubmittable. The registration has to be captured and
   * its own `onChange` called explicitly.
   */
  const questionField = form.register("question")
  const slugField = form.register("slug")

  /**
   * Live preview of the market's public URL.
   *
   * Slugs are permanent and shareable, and a typo in one means editing every
   * link ever posted. Showing the URL as it is typed costs one line and makes
   * the field self-evidently about a link rather than about internal naming.
   */
  const previewUrl = useMemo(() => {
    const origin =
      typeof window !== "undefined" ? window.location.origin : "predictx.io"
    return `${origin}/markets/${slugValue || "…"}`
  }, [slugValue])

  const onSubmit = useCallback(
    (data: CreateMarketInput) => {
      createMarket.mutate(
        {
          question: data.question,
          description: data.description || undefined,
          category: data.category || undefined,
          subcategory: data.subcategory || undefined,
          image_url: data.image_url || undefined,
          slug: data.slug,
          closes_at: new Date(data.closes_at).toISOString(),
          resolution_criteria: data.resolution_criteria || undefined,
          resolution_source: data.resolution_source || undefined,
          initial_liquidity: data.initial_liquidity,
          // Omitted rather than sent as `NaN`, which fails the API's `ge=0.01`
          // on a field the user simply left blank.
          ...(data.initial_probability === undefined
            ? {}
            : { initial_probability: data.initial_probability }),
          outcomes_create: [
            { name: "Yes", outcome_index: 0 },
            { name: "No", outcome_index: 1 },
          ],
        },
        {
          onSuccess: (res) => {
            sileo.success({
              title: "Market submitted for review",
              description:
                "An admin will review it. You can follow its status under My markets.",
            })
            const slug = res?.data?.slug
            router.push(slug ? `/markets/mine?highlight=${slug}` : "/markets/mine")
          },
          onError: (err) => {
            sileo.error({
              title: "Could not submit the market",
              description: apiErrorMessage(err, "Try again."),
            })
          },
        }
      )
    },
    [createMarket, router]
  )

  const rootError = form.formState.errors.root

  return (
    <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-6" noValidate>
      {rootError ? (
        <Alert variant="destructive" role="alert">
          <AlertCircle className="size-4" aria-hidden />
          <AlertTitle>Submission failed</AlertTitle>
          <AlertDescription>{rootError.message}</AlertDescription>
        </Alert>
      ) : null}

      {/* ── The question ─────────────────────────────────────────────────── */}
      <Field data-invalid={!!form.formState.errors.question}>
        <FieldLabel htmlFor="question">
          Question <span aria-hidden>*</span>
        </FieldLabel>
        <FieldContent>
          <Input
            id="question"
            {...questionField}
            placeholder="Will X happen by Y date?"
            aria-describedby={
              form.formState.errors.question ? "question-error" : "question-hint"
            }
            onChange={(event) => {
              // Fill the slug from the question until it is edited by hand.
              if (!slugTouched) {
                form.setValue("slug", slugify(event.target.value), {
                  shouldValidate: false,
                  shouldDirty: true,
                })
              }
              questionField.onChange(event)
            }}
          />
          {form.formState.errors.question ? (
            <FieldError id="question-error">
              {form.formState.errors.question.message}
            </FieldError>
          ) : (
            <FieldDescription id="question-hint">
              Write it so it has one unambiguous answer. It becomes the market&apos;s
              title, and traders bet on it.
            </FieldDescription>
          )}
        </FieldContent>
      </Field>

      <Field>
        <FieldLabel htmlFor="description">Description</FieldLabel>
        <FieldContent>
          <Textarea
            id="description"
            rows={4}
            {...form.register("description")}
            placeholder="Context, definitions, and anything a trader needs to price it fairly."
          />
        </FieldContent>
      </Field>

      {/* ── How it resolves ──────────────────────────────────────────────── */}
      <Field data-invalid={!!form.formState.errors.resolution_criteria}>
        <FieldLabel htmlFor="resolution_criteria">
          How does this resolve?
        </FieldLabel>
        <FieldContent>
          <Textarea
            id="resolution_criteria"
            rows={3}
            {...form.register("resolution_criteria")}
            placeholder="e.g. Resolves Yes if the official result is published by the Commission before 1 June 2027."
          />
          {form.formState.errors.resolution_criteria ? (
            <FieldError>
              {form.formState.errors.resolution_criteria.message}
            </FieldError>
          ) : (
            <FieldDescription>
              Optional, but the single most useful thing you can supply. A market
              with no stated settlement is settled by argument — which is slow and
              expensive for everyone holding a position.
            </FieldDescription>
          )}
        </FieldContent>
      </Field>

      <Field>
        <FieldLabel htmlFor="resolution_source">Source</FieldLabel>
        <FieldContent>
          <Input
            id="resolution_source"
            {...form.register("resolution_source")}
            placeholder="https:// or the name of the data feed"
          />
          <FieldDescription>
            Where the answer will come from — a URL, or a named official source.
          </FieldDescription>
        </FieldContent>
      </Field>

      {/* ── Classification ───────────────────────────────────────────────── */}
      <div className="grid gap-4 sm:grid-cols-2">
        <Field>
          <FieldLabel htmlFor="category">Category</FieldLabel>
          <FieldContent>
            <Input
              id="category"
              {...form.register("category")}
              placeholder="Politics, Sports, Crypto…"
            />
          </FieldContent>
        </Field>
        <Field>
          <FieldLabel htmlFor="subcategory">Subcategory</FieldLabel>
          <FieldContent>
            <Input
              id="subcategory"
              {...form.register("subcategory")}
              placeholder="Optional refinement"
            />
          </FieldContent>
        </Field>
      </div>

      <Field>
        <FieldLabel htmlFor="image_url">Image URL</FieldLabel>
        <FieldContent>
          <Input
            id="image_url"
            type="url"
            {...form.register("image_url")}
            placeholder="https://…"
            aria-invalid={form.formState.errors.image_url ? true : undefined}
          />
          {form.formState.errors.image_url ? (
            <FieldError>{form.formState.errors.image_url.message}</FieldError>
          ) : (
            <FieldDescription>
              Optional. Must be a full http:// or https:// link.
            </FieldDescription>
          )}
        </FieldContent>
      </Field>

      {/* ── Closing ─────────────────────────────────────────────────────── */}
      <Field data-invalid={!!form.formState.errors.closes_at}>
        <FieldLabel htmlFor="closes_at">
          Closes at <span aria-hidden>*</span>
        </FieldLabel>
        <FieldContent>
          <Input
            id="closes_at"
            type="datetime-local"
            {...form.register("closes_at")}
            aria-describedby={
              form.formState.errors.closes_at ? "closes-error" : "closes-hint"
            }
          />
          {form.formState.errors.closes_at ? (
            <FieldError id="closes-error">
              {form.formState.errors.closes_at.message}
            </FieldError>
          ) : (
            <FieldDescription id="closes-hint">
              The moment trading stops. It must be in the future, and it cannot be
              changed after approval.
            </FieldDescription>
          )}
        </FieldContent>
      </Field>

      {/* ── The URL ─────────────────────────────────────────────────────── */}
      <Field data-invalid={!!form.formState.errors.slug}>
        <FieldLabel htmlFor="slug">
          URL <span aria-hidden>*</span>
        </FieldLabel>
        <FieldContent>
          <Input
            id="slug"
            {...slugField}
            onChange={(event) => {
              setSlugTouched(true)
              slugField.onChange(event)
            }}
            className="font-mono"
            aria-describedby={form.formState.errors.slug ? "slug-error" : "slug-preview"}
          />
          {form.formState.errors.slug ? (
            <FieldError id="slug-error">{form.formState.errors.slug.message}</FieldError>
          ) : (
            <FieldDescription id="slug-preview">
              Generated from your question. It becomes permanent once approved, so
              check it now:{" "}
              <span className="font-mono text-foreground">{previewUrl}</span>
            </FieldDescription>
          )}
        </FieldContent>
      </Field>

      {/* ── Optional seeding ─────────────────────────────────────────────── */}
      <div className="grid gap-4 sm:grid-cols-2">
        <Field data-invalid={!!form.formState.errors.initial_liquidity}>
          <FieldLabel htmlFor="initial_liquidity">Initial liquidity</FieldLabel>
          <FieldContent>
            <Input
              id="initial_liquidity"
              type="number"
              step="any"
              min="0"
              inputMode="decimal"
              {...form.register("initial_liquidity", { valueAsNumber: true })}
            />
            <FieldDescription>
              Optional. Funds you are putting in to get the market started — comes
              out of your balance, and returns to you if you withdraw it.
            </FieldDescription>
          </FieldContent>
        </Field>
        <Field data-invalid={!!form.formState.errors.initial_probability}>
          <FieldLabel htmlFor="initial_probability">Starting price (Yes)</FieldLabel>
          <FieldContent>
            <Input
              id="initial_probability"
              type="number"
              step="0.01"
              min="0.01"
              max="0.99"
              inputMode="decimal"
              {...form.register("initial_probability", { valueAsNumber: true })}
              placeholder="0.50"
            />
            <FieldDescription>
              Optional. Leave blank for the default. Requires liquidity above.
            </FieldDescription>
          </FieldContent>
        </Field>
      </div>

      {/* Stated before the button, not discovered after it. The most common
          surprise on this form is that submitting does not make a market
          tradable, and the expectation that it does is what makes people think
          the submission failed. */}
      <Alert>
        <Clock className="size-4" aria-hidden />
        <AlertTitle>This goes to review first</AlertTitle>
        <AlertDescription>
          New markets are checked by a moderator before they become tradable. You
          will see the status — and the reason, if it is declined — under My
          markets.
        </AlertDescription>
      </Alert>

      <div className="flex flex-col-reverse gap-3 sm:flex-row sm:justify-end">
        <Button
          type="button"
          variant="outline"
          onClick={() => router.push("/markets")}
          disabled={createMarket.isPending}
        >
          Cancel
        </Button>
        <Button type="submit" disabled={createMarket.isPending} className="sm:min-w-40">
          {createMarket.isPending ? (
            <>
              <Spinner className="mr-2" aria-hidden />
              <span>Submitting…</span>
            </>
          ) : (
            <>
              <CheckCircle2 className="mr-2 size-4" aria-hidden />
              <span>Submit for review</span>
            </>
          )}
        </Button>
      </div>

      {/* Announced to screen readers when the submit fails, since the toast is
          visual and the button's own label does not change. */}
      <p className="sr-only" role="status" aria-live="polite">
        {createMarket.isPending ? "Submitting your market for review" : ""}
      </p>
    </form>
  )
}

export { slugify }