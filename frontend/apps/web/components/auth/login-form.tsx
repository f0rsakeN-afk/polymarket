"use client"

import { useState, useEffect, useCallback } from "react"
import { useRouter, useSearchParams } from "next/navigation"
import { useForm } from "react-hook-form"
import { zodResolver } from "@hookform/resolvers/zod"
import { z } from "zod"
import { authApi, magicLinkApi } from "@/lib/api/auth"
import { OtpInput } from "@/components/auth/otp-input"
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

// ─── Schema ───────────────────────────────────────────────────────────────────

const emailSchema = z.object({
  email: z.string().email("Please enter a valid email"),
})

const passwordSchema = z.object({
  email: z.string().email(),
  password: z.string().min(1, "Password is required"),
  totp_code: z.string().optional(),
})

// ─── Polygon Logo ───────────────────────────────────────────────────────────────

function PolygonMark({ className }: { className?: string }) {
  return (
    <svg width="28" height="28" viewBox="0 0 20 20" fill="none" className={className} aria-hidden="true">
      <path
        d="M10 1L18.5 6.5V15.5L10 21L1.5 15.5V6.5L10 1Z"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinejoin="round"
        fill="none"
      />
      <path
        d="M10 1V21M1.5 6.5L18.5 6.5M1.5 15.5L18.5 15.5"
        stroke="currentColor"
        strokeWidth="1.5"
        strokeLinejoin="round"
      />
    </svg>
  )
}

// ─── Step 1: Email ────────────────────────────────────────────────────────────

function EmailStep({
  onPasswordLogin,
  onMagicLink,
  onForgotPassword,
  onSignup,
}: {
  onPasswordLogin: (email: string) => void
  onMagicLink: (email: string) => void
  onForgotPassword: (email: string) => void
  onSignup: () => void
}) {
  const [isLoading, setIsLoading] = useState(false)
  const [error, setError] = useState("")

  const form = useForm<{ email: string }>({
    resolver: zodResolver(emailSchema),
    defaultValues: { email: "" },
  })

  const handlePasswordSubmit = form.handleSubmit(({ email }) => {
    setError("")
    onPasswordLogin(email)
  })

  const handleMagicLinkSubmit = async () => {
    const valid = await form.trigger()
    if (!valid) return
    const emailVal = form.getValues("email")
    if (!emailVal.includes("@")) return
    setError("")
    setIsLoading(true)
    try {
      await magicLinkApi.sendCode(emailVal)
      onMagicLink(emailVal)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to send code")
    } finally {
      setIsLoading(false)
    }
  }

  return (
    <div className="space-y-4">
      <Form {...form}>
        <form onSubmit={handlePasswordSubmit} className="space-y-4">
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
          <Button type="submit" disabled={isLoading} className="w-full">
            Continue
          </Button>
        </form>
      </Form>

      {error && (
        <p className="text-xs text-destructive text-center">{error}</p>
      )}

      <div className="mt-4 mb-4 relative">
        <div className="absolute inset-0 flex items-center">
          <span className="w-full border-t border-border/60" />
        </div>
        <div className="relative flex justify-center text-xs uppercase">
          <span className="bg-card px-2 text-muted-foreground">or</span>
        </div>
      </div>

      <Button
        type="button"
        variant="outline"
        onClick={handleMagicLinkSubmit}
        disabled={isLoading}
        className="w-full"
      >
        Send me a login code
      </Button>

      <div className="mt-4 flex items-center justify-between">
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => onForgotPassword(form.getValues("email"))}
          className="text-xs text-muted-foreground hover:text-foreground h-auto p-0"
        >
          Forgot password?
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={onSignup}
          className="text-xs text-muted-foreground hover:text-foreground h-auto p-0"
        >
          Create account
        </Button>
      </div>
    </div>
  )
}

// ─── Step 2: Password ─────────────────────────────────────────────────────────

function PasswordStep({
  email,
  onBack,
}: {
  email: string
  onBack: () => void
}) {
  const router = useRouter()
  const searchParams = useSearchParams()
  const rawNext = searchParams.get("next") ?? "/portfolio"
  const next = rawNext.startsWith("/") && !rawNext.startsWith("//") ? rawNext : "/portfolio"

  const [isLoading, setIsLoading] = useState(false)
  const [globalError, setGlobalError] = useState("")

  const form = useForm<z.infer<typeof passwordSchema>>({
    resolver: zodResolver(passwordSchema),
    defaultValues: { email, password: "", totp_code: "" },
  })

  const onSubmit = form.handleSubmit(async (data) => {
    setGlobalError("")
    setIsLoading(true)
    try {
      await authApi.login(data.email, data.password, data.totp_code || undefined)
      router.push(next)
    } catch (err) {
      setGlobalError(err instanceof Error ? err.message : "Login failed")
    } finally {
      setIsLoading(false)
    }
  })

  return (
    <div className="space-y-4">
      <Form {...form}>
        <form onSubmit={onSubmit} className="space-y-4">
          <p className="text-sm text-muted-foreground text-center py-2">{email}</p>

          <FormField
            control={form.control}
            name="password"
            render={({ field }) => (
              <FormItem>
                <FormLabel className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                  Password
                </FormLabel>
                <FormControl>
                  <Input
                    type="password"
                    placeholder="••••••••"
                    autoFocus
                    autoComplete="current-password"
                    {...field}
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />

          <FormField
            control={form.control}
            name="totp_code"
            render={({ field }) => (
              <FormItem>
                <FormLabel className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                  2FA code{" "}
                  <span className="normal-case font-normal text-muted-foreground/60">
                    (if enabled)
                  </span>
                </FormLabel>
                <FormControl>
                  <Input
                    type="text"
                    inputMode="numeric"
                    maxLength={6}
                    placeholder="000000"
                    autoComplete="one-time-code"
                    {...field}
                    value={field.value ?? ""}
                  />
                </FormControl>
                <FormMessage />
              </FormItem>
            )}
          />

          {globalError && (
            <div className="rounded-md border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm text-destructive">
              {globalError}
            </div>
          )}

          <Button type="submit" disabled={isLoading} className="w-full">
            {isLoading ? "Signing in..." : "Sign in"}
          </Button>
        </form>
      </Form>

      <div className="mt-4 flex items-center justify-between">
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={onBack}
          className="text-xs text-muted-foreground hover:text-foreground h-auto p-0"
        >
          ← Use different email
        </Button>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={() => router.push(`/forgot-password?email=${encodeURIComponent(email)}`)}
          className="text-xs text-muted-foreground hover:text-foreground h-auto p-0"
        >
          Forgot password?
        </Button>
      </div>
    </div>
  )
}

// ─── Step 3: Magic Link OTP ──────────────────────────────────────────────────

const RESEND_COOLDOWN = 60

function MagicLinkStep({
  email,
  onBack,
}: {
  email: string
  onBack: () => void
}) {
  const router = useRouter()
  const searchParams = useSearchParams()
  const rawNext = searchParams.get("next") ?? "/portfolio"
  const next = rawNext.startsWith("/") && !rawNext.startsWith("//") ? rawNext : "/portfolio"

  const [otp, setOtp] = useState("")
  const [isLoading, setIsLoading] = useState(false)
  const [resendTimer, setResendTimer] = useState(RESEND_COOLDOWN)
  const [error, setError] = useState("")
  const [magicPartialToken, setMagicPartialToken] = useState("")
  const [step, setStep] = useState<"otp" | "totp">("otp")
  const [totpCode, setTotpCode] = useState("")

  const handleVerifyOtp = useCallback(async () => {
    if (otp.length !== 6) return
    setError("")
    setIsLoading(true)
    try {
      await magicLinkApi.verifyCode(email, otp)
      router.push(next)
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Invalid or expired code"
      if (msg.startsWith("2FA code required:")) {
        setMagicPartialToken(msg.split(":")[1] ?? "")
        setStep("totp")
        setIsLoading(false)
        return
      }
      if (msg === "2FA code required") {
        setStep("totp")
        setIsLoading(false)
        return
      }
      setError(msg)
      setOtp("")
    } finally {
      setIsLoading(false)
    }
  }, [email, otp, next, router])

  const handleTotp = useCallback(async () => {
    if (totpCode.length !== 6) return
    setError("")
    setIsLoading(true)
    try {
      if (magicPartialToken) {
        await magicLinkApi.verifyMagic2fa(magicPartialToken, totpCode)
      } else {
        await magicLinkApi.verifyUrl2fa(totpCode, totpCode)
      }
      router.push(next)
    } catch (err) {
      setError(err instanceof Error ? err.message : "Invalid 2FA code")
    } finally {
      setIsLoading(false)
    }
  }, [magicPartialToken, totpCode, next, router])

  const handleResend = useCallback(async () => {
    try {
      await magicLinkApi.sendCode(email)
      setResendTimer(RESEND_COOLDOWN)
      sileo.success({ title: "Code resent" })
    } catch {
      sileo.error({ title: "Failed to resend" })
    }
  }, [email])

  // Auto-verify
  useEffect(() => {
    if (step === "otp" && otp.length === 6) handleVerifyOtp()
  }, [otp, step, handleVerifyOtp])

  useEffect(() => {
    if (step === "totp" && totpCode.length === 6) handleTotp()
  }, [totpCode, step, handleTotp])

  // Countdown
  useEffect(() => {
    if (resendTimer <= 0) return
    const id = setInterval(() => setResendTimer((t) => t - 1), 1_000)
    return () => clearInterval(id)
  }, [resendTimer])

  return (
    <div className="space-y-4">
      {step === "otp" ? (
        <>
          <OtpInput value={otp} onChange={setOtp} error={!!error} />
          {error && <p className="text-xs text-destructive text-center">{error}</p>}
          <div className="flex items-center justify-between">
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={onBack}
              className="text-xs text-muted-foreground hover:text-foreground h-auto p-0"
            >
              Use different email
            </Button>
            <Button
              type="button"
              variant="ghost"
              size="sm"
              onClick={handleResend}
              disabled={resendTimer > 0}
              className="text-xs text-muted-foreground hover:text-foreground h-auto p-0 disabled:opacity-50"
            >
              {resendTimer > 0 ? `Resend in ${resendTimer}s` : "Resend code"}
            </Button>
          </div>
        </>
      ) : (
        <>
          <p className="text-sm text-muted-foreground text-center py-2">
            Enter the code from your authenticator app
          </p>
          <OtpInput value={totpCode} onChange={setTotpCode} error={!!error} />
          {error && <p className="text-xs text-destructive text-center">{error}</p>}
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => { setStep("otp"); setTotpCode(""); setError("") }}
            className="text-xs text-muted-foreground hover:text-foreground h-auto p-0"
          >
            ← Back to login code
          </Button>
        </>
      )}
    </div>
  )
}

// ─── Main export ──────────────────────────────────────────────────────────────

export function LoginForm() {
  const router = useRouter()
  const [flow, setFlow] = useState<"password" | "magic" | null>(null)
  const [email, setEmail] = useState("")

  const handlePasswordLogin = (e: string) => {
    setEmail(e)
    setFlow("password")
  }

  const handleMagicLink = (e: string) => {
    setEmail(e)
    setFlow("magic")
  }

  const handleForgotPassword = (e: string) => {
    router.push(`/forgot-password${e ? `?email=${encodeURIComponent(e)}` : ""}`)
  }

  return (
    <div className="flex min-h-dvh flex-col items-center justify-center px-4 py-12">
      {/* Logo */}
      <div className="mb-8 flex flex-col items-center gap-2">
        <div className="text-foreground">
          <PolygonMark />
        </div>
        <span className="text-sm font-medium text-foreground tracking-tight">Polymarket</span>
      </div>

      <Card className="w-full max-w-sm border-border/60 bg-card/80 backdrop-blur-sm shadow-none">
        <CardContent className="p-6">
          {/* Header */}
          <div className="mb-6 text-center">
            <h1 className="text-lg font-semibold text-foreground tracking-tight">
              {flow === "password" ? "Welcome back" : flow === "magic" ? "Check your email" : "Sign in"}
            </h1>
            {flow === "magic" && (
              <p className="mt-1 text-sm text-muted-foreground">
                Code sent to {email}
              </p>
            )}
            {flow === null && (
              <p className="mt-1 text-sm text-muted-foreground">
                Enter your email to continue
              </p>
            )}
          </div>

          {flow === null && (
            <EmailStep
              onPasswordLogin={handlePasswordLogin}
              onMagicLink={handleMagicLink}
              onForgotPassword={handleForgotPassword}
              onSignup={() => router.push("/signup")}
            />
          )}

          {flow === "password" && (
            <PasswordStep email={email} onBack={() => setFlow(null)} />
          )}

          {flow === "magic" && (
            <MagicLinkStep email={email} onBack={() => setFlow(null)} />
          )}
        </CardContent>
      </Card>

      {flow === null && (
        <p className="mt-6 text-center text-xs text-muted-foreground">
          Don&apos;t have an account?{" "}
          <Button
            type="button"
            variant="ghost"
            size="sm"
            onClick={() => router.push("/signup")}
            className="text-xs text-foreground h-auto p-0"
          >
            Sign up
          </Button>
        </p>
      )}
    </div>
  )
}
