"use client"

import { useState, useCallback } from "react"
import Link from "next/link"
import { useSearchParams } from "next/navigation"
import { useMutation } from "@tanstack/react-query"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { forgotPasswordSchema, type ForgotPasswordInput } from "@/lib/schemas/auth"
import { passwordApi } from "@/lib/api/auth"
import { Button } from "@workspace/ui/components/button"
import { Input } from "@workspace/ui/components/input"
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@workspace/ui/components/form"
import { Card, CardContent } from "@workspace/ui/components/card"
import { sileo } from "sileo"

function PolygonMark({ className }: { className?: string }) {
  return (
    <svg width="28" height="28" viewBox="0 0 20 20" fill="none" className={className} aria-hidden="true">
      <path d="M10 1L18.5 6.5V15.5L10 21L1.5 15.5V6.5L10 1Z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" fill="none" />
      <path d="M10 1V21M1.5 6.5L18.5 6.5M1.5 15.5L18.5 15.5" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
    </svg>
  )
}

export function ForgotPasswordClient() {
  const searchParams = useSearchParams()
  const emailParam = searchParams.get("email") ?? ""
  const [sent, setSent] = useState(false)
  const [submittedEmail, setSubmittedEmail] = useState(emailParam)

  const form = useForm<ForgotPasswordInput>({
    resolver: zodResolver(forgotPasswordSchema),
    defaultValues: { email: emailParam },
  })

  const mutation = useMutation({
    mutationFn: (data: ForgotPasswordInput) => passwordApi.forgotPassword(data.email),
    onSuccess: () => {
      setSent(true)
      setSubmittedEmail(form.getValues("email"))
    },
    onError: (err) => {
      sileo.error({ title: err instanceof Error ? err.message : "Failed to send code" })
    },
  })

  const onSubmit = useCallback(
    (data: ForgotPasswordInput) => mutation.mutate(data),
    [mutation]
  )

  return (
    <div className="flex min-h-dvh flex-col items-center justify-center px-4 py-12">
      <div className="mb-8 flex flex-col items-center gap-2">
        <div className="text-foreground"><PolygonMark /></div>
        <span className="text-sm font-medium text-foreground tracking-tight">Polymarket</span>
      </div>

      <Card className="w-full max-w-sm border-border/60 bg-card/80 backdrop-blur-sm shadow-none">
        <CardContent className="p-6">
          <div className="mb-6 text-center">
            <h1 className="text-lg font-semibold text-foreground tracking-tight">
              {sent ? "Check your email" : "Reset password"}
            </h1>
            <p className="mt-1 text-sm text-muted-foreground">
              {sent
                ? `If an account exists for ${submittedEmail || "that email"}, a code was sent.`
                : "Enter your email and we'll send you a reset code"}
            </p>
          </div>

          {sent ? (
            <div className="space-y-4 text-center">
              <div className="rounded-md border border-border/60 bg-muted/50 px-4 py-6 text-sm text-muted-foreground">
                Check your inbox — we sent a password reset code to{" "}
                <strong className="text-foreground">{submittedEmail}</strong>.
                <br />
                Didn&apos;t receive it? Check your spam folder.
              </div>
              <button
                onClick={() => setSent(false)}
                className="text-sm text-muted-foreground hover:text-foreground transition-colors"
              >
                Try a different email
              </button>
            </div>
          ) : (
            <>
              <Form {...form}>
                <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
                  <FormField
                    control={form.control}
                    name="email"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                          Email
                        </FormLabel>
                        <FormControl>
                          <Input
                            type="email"
                            placeholder="you@example.com"
                            autoFocus
                            autoComplete="email"
                            {...field}
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                  <Button type="submit" disabled={mutation.isPending} className="w-full">
                    {mutation.isPending ? "Sending..." : "Send reset code"}
                  </Button>
                </form>
              </Form>
              <p className="mt-4 text-center">
                <Link
                  href="/login"
                  className="text-xs text-muted-foreground hover:text-foreground transition-colors"
                >
                  Back to sign in
                </Link>
              </p>
            </>
          )}
        </CardContent>
      </Card>
    </div>
  )
}
