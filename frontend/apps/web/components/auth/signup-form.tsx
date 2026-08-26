"use client";

import { useState, useEffect, useCallback } from "react";
import Link from "next/link";
import { useSearchParams } from "next/navigation";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { registerApi } from "@/lib/api/auth";
import { registerSchema, type RegisterInput } from "@/lib/schemas/auth";
import { OtpInput } from "./otp-input";
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
import { Card, CardContent } from "@workspace/ui/components/card";
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

// ─── Step content with fade animation ─────────────────────────────────────────

function StepContent({ step, children }: { step: string; children: React.ReactNode }) {
  return (
    <div
      key={step}
      className="animate-in fade-in slide-in-from-bottom-2 duration-200 ease-out"
    >
      {children}
    </div>
  );
}

// ─── Signup form ───────────────────────────────────────────────────────────────

const RESEND_COOLDOWN = 60;

export function SignupForm() {
  const [step, setStep] = useState<"details" | "otp">("details");
  const [email, setEmail] = useState("");
  const [otp, setOtp] = useState("");
  const [isLoading, setIsLoading] = useState(false);
  const [resendTimer, setResendTimer] = useState(0);
  const [otpError, setOtpError] = useState("");

  const refParam = useSearchParams().get("ref") ?? undefined;

  const form = useForm<RegisterInput>({
    resolver: zodResolver(registerSchema),
    defaultValues: { email: "", username: "", password: "", referral_code: "" },
  });

  const onSubmit = useCallback(
    async (data: RegisterInput) => {
      setIsLoading(true);
      try {
        await registerApi.register(data.email, data.username, data.password, data.referral_code || undefined);
        setEmail(data.email);
        setStep("otp");
        setResendTimer(RESEND_COOLDOWN);
      } catch (err) {
        sileo.error({ title: err instanceof Error ? err.message : "Registration failed" });
      } finally {
        setIsLoading(false);
      }
    },
    []
  );

  const handleVerifyOtp = useCallback(async () => {
    if (otp.length !== 6) return;
    setIsLoading(true);
    try {
      await registerApi.verifyEmail(email, otp);
      sileo.success({ title: "Email verified!" });
      window.location.href = "/login";
    } catch (err) {
      sileo.error({ title: err instanceof Error ? err.message : "Invalid or expired code" });
      setOtpError(err instanceof Error ? err.message : "Invalid or expired code");
      setOtp("");
    } finally {
      setIsLoading(false);
    }
  }, [email, otp]);

  const handleResend = useCallback(async () => {
    try {
      await registerApi.resendVerification(email);
      setResendTimer(RESEND_COOLDOWN);
      setOtpError("");
      sileo.success({ title: "Code resent" });
    } catch (err) {
      sileo.error({ title: err instanceof Error ? err.message : "Failed to resend code" });
    }
  }, [email]);

  useEffect(() => {
    if (resendTimer <= 0) return;
    const id = setInterval(() => setResendTimer((t) => t - 1), 1_000);
    return () => clearInterval(id);
  }, [resendTimer]);

  // Auto-verify on 6 digits
  useEffect(() => {
    if (step === "otp" && otp.length === 6) handleVerifyOtp();
  }, [otp, step]);

  // Pre-fill referral code from ?ref= URL param
  useEffect(() => {
    if (refParam) {
      form.setValue("referral_code", refParam);
    }
  }, [refParam, form]);

  return (
    <div className="flex min-h-dvh flex-col items-center justify-center px-4 py-12">
      {/* Logo + wordmark */}
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
              {step === "details" ? "Create account" : "Verify email"}
            </h1>
            <p className="mt-1 text-sm text-muted-foreground">
              {step === "details"
                ? "Join to start trading"
                : `Code sent to ${email}`}
            </p>
            </div>

          <StepContent step={step}>
            {/* ── Details step ── */}
            {step === "details" && (
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
                  <FormField
                    control={form.control}
                    name="username"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                          Username
                        </FormLabel>
                        <FormControl>
                          <Input
                            type="text"
                            placeholder="trader_123"
                            autoComplete="username"
                            {...field}
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
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
                            placeholder="Min. 8 characters"
                            autoComplete="new-password"
                            {...field}
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                  <FormField
                    control={form.control}
                    name="referral_code"
                    render={({ field }) => (
                      <FormItem>
                        <FormLabel className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                          Referral Code <span className="text-muted-foreground/50">(optional)</span>
                        </FormLabel>
                        <FormControl>
                          <Input
                            type="text"
                            placeholder="FRIEND123"
                            autoComplete="off"
                            {...field}
                          />
                        </FormControl>
                        <FormMessage />
                      </FormItem>
                    )}
                  />
                  <Button type="submit" disabled={isLoading} className="w-full">
                    {isLoading ? "Creating account..." : "Create account"}
                  </Button>
                </form>
              </Form>
            )}

            {/* ── OTP step ── */}
            {step === "otp" && (
              <div className="space-y-4">
                <OtpInput value={otp} onChange={(v) => setOtp(v)} error={!!otpError} />
                <div className="flex items-center justify-between text-xs text-muted-foreground">
                  <button
                    onClick={() => { setStep("details"); setOtp(""); }}
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
          </StepContent>
        </CardContent>
      </Card>

      <p className="mt-6 text-center text-xs text-muted-foreground">
        Already have an account?{" "}
        <Link href="/login" className="text-foreground underline-offset-4 hover:underline">
          Sign in
        </Link>
      </p>
    </div>
  );
}
