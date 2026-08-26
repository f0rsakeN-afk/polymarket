"use client";

import { useState, useEffect, useCallback } from "react";
import { useSearchParams } from "next/navigation";
import Link from "next/link";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { authApi, magicLinkApi } from "@/lib/api/auth";
import { loginSchema, type LoginInput } from "@/lib/schemas/auth";
import { OtpInput } from "@/components/auth/otp-input";
import { Button } from "@workspace/ui/components/button";
import { Input } from "@workspace/ui/components/input";
import {
  Form,
  FormControl,
  FormField,
  FormItem,
  FormLabel,
  FormMessage,
} from "@workspace/ui/components/form";
import {
  Card,
  CardContent,
} from "@workspace/ui/components/card";
import { sileo } from "sileo";

// ─── Polygon Logo ───────────────────────────────────────────────────────────────

function PolygonMark({ className }: { className?: string }) {
  return (
    <svg
      width="28"
      height="28"
      viewBox="0 0 20 20"
      fill="none"
      className={className}
      aria-hidden="true"
    >
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
  );
}

// ─── Step labels ───────────────────────────────────────────────────────────────

const STEP_LABELS = {
  email: { title: "Sign in", sub: "Enter your email to continue" },
  otp: { title: "Check your email", sub: "" },
  password: { title: "Welcome back", sub: "Enter your password" },
  totp2fa: { title: "Two-factor auth", sub: "Enter the code from your app" },
} as const;

type Step = keyof typeof STEP_LABELS;

// ─── Animated step wrapper ────────────────────────────────────────────────────

function StepContent({ step, children }: { step: Step; children: React.ReactNode }) {
  return (
    <div
      key={step}
      className="animate-in fade-in slide-in-from-bottom-2 duration-200 ease-out"
    >
      {children}
    </div>
  );
}

// ─── Login form ────────────────────────────────────────────────────────────────

const RESEND_COOLDOWN = 60;

export function LoginForm() {
  const searchParams = useSearchParams();
  // Only allow relative redirects — prevents open redirect to external domains
  const rawNext = searchParams.get("next") ?? "/portfolio"
  const next = rawNext.startsWith("/") && !rawNext.startsWith("//") ? rawNext : "/portfolio"

  const [step, setStep] = useState<Step>("email");
  const [email] = useState("");
  const [otp, setOtp] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [resendTimer, setResendTimer] = useState(0);
  const [globalError, setGlobalError] = useState("");
  const [totp2faCode, setTotp2faCode] = useState("");
  const [magicPartialToken, setMagicPartialToken] = useState("");

  const passwordForm = useForm<LoginInput>({
    resolver: zodResolver(loginSchema),
    defaultValues: { email: "", password: "", totp_code: undefined },
  });

  // ── Password login ─────────────────────────────────────────────────────────
  const handlePasswordLogin = useCallback(
    async (data: LoginInput) => {
      setGlobalError("");
      setIsLoading(true);
      try {
        await authApi.login(data.email, data.password, data.totp_code);
        window.location.href = next;
      } catch (err) {
        setGlobalError(err instanceof Error ? err.message : "Login failed");
        setIsLoading(false);
      }
    },
    [next]
  );

  // ── Magic link code request ───────────────────────────────────────────────
  const handleSendCode = useCallback(async () => {
    if (!email || !email.includes("@")) return;
    setGlobalError("");
    setIsLoading(true);
    try {
      await magicLinkApi.sendCode(email);
      setStep("otp");
      setResendTimer(RESEND_COOLDOWN);
      sileo.success({ title: "Code sent" });
    } catch (err) {
      setGlobalError(err instanceof Error ? err.message : "Failed to send code");
    } finally {
      setIsLoading(false);
    }
  }, [email]);

  // ── Verify magic link code ────────────────────────────────────────────────
  const handleVerifyOtp = useCallback(async () => {
    if (otp.length !== 6) return;
    setGlobalError("");
    setIsLoading(true);
    try {
      await magicLinkApi.verifyCode(email, otp);
      window.location.href = next;
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Invalid or expired code";
      if (msg.startsWith("2FA code required:")) {
        const partial = msg.split(":")[1] ?? "";
        setMagicPartialToken(partial);
        setStep("totp2fa");
        setIsLoading(false);
        return;
      }
      if (msg === "2FA code required") {
        setStep("totp2fa");
        setIsLoading(false);
        return;
      }
      setGlobalError(msg);
      setOtp("");
      setIsLoading(false);
    }
  }, [email, otp, next]);

  // ── Complete magic link with 2FA ──────────────────────────────────────────
  const handleTotp2fa = useCallback(
    async (totpCode: string) => {
      setGlobalError("");
      setIsLoading(true);
      try {
        if (magicPartialToken) {
          await magicLinkApi.verifyMagic2fa(magicPartialToken, totpCode);
        } else {
          await magicLinkApi.verifyUrl2fa(totp2faCode, totp2faCode);
        }
        window.location.href = next;
      } catch (err) {
        setGlobalError(err instanceof Error ? err.message : "Invalid 2FA code");
        setIsLoading(false);
      }
    },
    [magicPartialToken, totp2faCode, next]
  );

  // ── Resend ───────────────────────────────────────────────────────────────
  const handleResend = useCallback(async () => {
    try {
      await magicLinkApi.sendCode(email);
      setResendTimer(RESEND_COOLDOWN);
      sileo.success({ title: "Code resent" });
    } catch {
      sileo.error({ title: "Failed to resend" });
    }
  }, [email]);

  useEffect(() => {
    if (resendTimer <= 0) return;
    const id = setInterval(() => setResendTimer((t) => t - 1), 1_000);
    return () => clearInterval(id);
  }, [resendTimer]);

  // Auto-submit OTP on 6 digits
  useEffect(() => {
    if (step === "otp" && otp.length === 6) handleVerifyOtp();
  }, [otp, step]);

  // Auto-submit 2FA on 6 digits
  useEffect(() => {
    if (step === "totp2fa" && totp2faCode.length === 6) handleTotp2fa(totp2faCode);
  }, [totp2faCode, step]);

  const { title, sub } = STEP_LABELS[step];

  return (
    <div className="flex min-h-dvh flex-col items-center justify-center px-4 py-12">
      {/* Logo + wordmark */}
      <div className="mb-8 flex flex-col items-center gap-2">
        <div className="text-foreground">
          <PolygonMark />
        </div>
        <span className="text-sm font-medium text-foreground tracking-tight">Polymarket</span>
      </div>

      {/* Card */}
      <Card className="w-full max-w-sm border-border/60 bg-card/80 backdrop-blur-sm shadow-none">
        <CardContent className="p-6">
          {/* Header */}
          <div className="mb-6 text-center">
            <h1 className="text-lg font-semibold text-foreground tracking-tight">{title}</h1>
            {sub && (
              <p className="mt-1 text-sm text-muted-foreground">
                {step === "otp" ? `Code sent to ${email}` : sub}
              </p>
            )}
          </div>

          {/* Error */}
          {globalError && (
            <div className="mb-4 rounded-md border border-destructive/40 bg-destructive/10 px-4 py-3 text-sm text-destructive">
              {globalError}
            </div>
          )}

          <StepContent step={step}>
            {/* ── Email step ── */}
            {step === "email" && (
              <div className="space-y-4">
                <Form {...passwordForm}>
                  <form onSubmit={passwordForm.handleSubmit(handlePasswordLogin)} className="space-y-4">
                    <FormField
                      control={passwordForm.control}
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
                    <Button
                      type="submit"
                      disabled={isLoading}
                      className="w-full"
                    >
                      {isLoading ? "Sending..." : "Continue with email"}
                    </Button>
                  </form>
                </Form>

                <div className="relative">
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
                  onClick={handleSendCode}
                  disabled={isLoading || !email.includes("@")}
                  className="w-full"
                >
                  Send me a login code
                </Button>

                <button
                  type="button"
                  onClick={() => setStep("password")}
                  className="w-full text-center text-sm text-muted-foreground hover:text-foreground transition-colors"
                >
                  Sign in with password
                </button>
              </div>
            )}

            {/* ── OTP step ── */}
            {step === "otp" && (
              <div className="space-y-4">
                <OtpInput value={otp} onChange={(v) => setOtp(v)} error={!!globalError} />
                <div className="flex items-center justify-between text-xs text-muted-foreground">
                  <button
                    onClick={() => { setStep("email"); setOtp(""); }}
                    className="hover:text-foreground transition-colors"
                  >
                    Use different email
                  </button>
                  <button
                    onClick={handleResend}
                    disabled={resendTimer > 0}
                    className="hover:text-foreground transition-colors disabled:opacity-50"
                  >
                    {resendTimer > 0 ? `Resend in ${resendTimer}s` : "Resend code"}
                  </button>
                </div>
              </div>
            )}

            {/* ── Password step ── */}
            {step === "password" && (
              <div className="space-y-4">
                <Form {...passwordForm}>
                  <form onSubmit={passwordForm.handleSubmit(handlePasswordLogin)} className="space-y-4">
                    <FormField
                      control={passwordForm.control}
                      name="email"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                            Email
                          </FormLabel>
                          <FormControl>
                            <Input type="email" placeholder="you@example.com" autoComplete="email" {...field} />
                          </FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                    <FormField
                      control={passwordForm.control}
                      name="password"
                      render={({ field }) => (
                        <FormItem>
                          <FormLabel className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                            Password
                          </FormLabel>
                          <FormControl>
                            <Input type="password" placeholder="••••••••" autoComplete="current-password" {...field} />
                          </FormControl>
                          <FormMessage />
                        </FormItem>
                      )}
                    />
                    <FormField
                      control={passwordForm.control}
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
                    <Button type="submit" disabled={isLoading} className="w-full">
                      {isLoading ? "Signing in..." : "Sign in"}
                    </Button>
                  </form>
                </Form>
                <button
                  type="button"
                  onClick={() => setStep("email")}
                  className="w-full text-center text-sm text-muted-foreground hover:text-foreground transition-colors"
                >
                  Sign in with a code instead
                </button>
              </div>
            )}

            {/* ── Magic link 2FA step ── */}
            {step === "totp2fa" && (
              <div className="space-y-4">
                <OtpInput
                  value={totp2faCode}
                  onChange={(v) => setTotp2faCode(v)}
                  error={!!globalError}
                  autoFocus
                />
                <button
                  type="button"
                  onClick={() => { setStep("otp"); setTotp2faCode(""); setOtp(""); }}
                  className="w-full text-center text-sm text-muted-foreground hover:text-foreground transition-colors"
                >
                  Back to login code
                </button>
              </div>
            )}
          </StepContent>
        </CardContent>
      </Card>

      {/* Footer */}
      <p className="mt-6 text-center text-xs text-muted-foreground">
        Don&apos;t have an account?{" "}
        <Link href="/signup" className="text-foreground underline-offset-4 hover:underline">
          Sign up
        </Link>
      </p>

      {step === "password" && (
        <Link
          href={`/forgot-password${email ? `?email=${encodeURIComponent(email)}` : ""}`}
          className="mt-3 text-center text-xs text-muted-foreground hover:text-foreground transition-colors"
        >
          Forgot password?
        </Link>
      )}
    </div>
  );
}
