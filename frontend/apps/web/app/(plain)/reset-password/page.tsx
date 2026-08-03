"use client";

import { useCallback, useState } from "react";
import Link from "next/link";
import { useSearchParams, useRouter } from "next/navigation";
import { useMutation } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { passwordApi } from "@/lib/api/auth";
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
import { OtpInput } from "@/components/auth/otp-input";
import { sileo } from "sileo";

function PolygonMark({ className }: { className?: string }) {
  return (
    <svg width="28" height="28" viewBox="0 0 20 20" fill="none" className={className} aria-hidden="true">
      <path d="M10 1L18.5 6.5V15.5L10 21L1.5 15.5V6.5L10 1Z" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" fill="none" />
      <path d="M10 1V21M1.5 6.5L18.5 6.5M1.5 15.5L18.5 15.5" stroke="currentColor" strokeWidth="1.5" strokeLinejoin="round" />
    </svg>
  );
}

const schema = z
  .object({
    email: z.string().email("Please enter a valid email address"),
    code: z.string().length(6, "Code must be 6 digits").regex(/^\d{6}$/, "Code must be 6 digits"),
    newPassword: z.string().min(8, "Password must be at least 8 characters"),
    confirmPassword: z.string(),
  })
  .refine((d) => d.newPassword === d.confirmPassword, {
    message: "Passwords do not match",
    path: ["confirmPassword"],
  });

type Input = z.infer<typeof schema>;

export default function ResetPasswordPage() {
  const searchParams = useSearchParams();
  const router = useRouter();
  const emailParam = searchParams.get("email") ?? "";
  const codeParam = searchParams.get("code") ?? "";
  const [code, setCode] = useState(codeParam);

  const form = useForm<Input>({
    resolver: zodResolver(schema),
    defaultValues: { email: emailParam, code: codeParam, newPassword: "", confirmPassword: "" },
  });

  const mutation = useMutation({
    mutationFn: (data: Input) => passwordApi.resetPassword(data.email, data.code, data.newPassword),
    onSuccess: () => {
      sileo.success({ title: "Password reset!" });
      router.push("/login");
    },
    onError: (err) => {
      sileo.error({ title: err instanceof Error ? err.message : "Failed to reset password" });
    },
  });

  const onSubmit = useCallback(
    (data: Input) => mutation.mutate(data),
    [mutation]
  );

  return (
    <div className="flex min-h-dvh flex-col items-center justify-center px-4 py-12">
      {/* Logo */}
      <div className="mb-8 flex flex-col items-center gap-2">
        <div className="text-foreground"><PolygonMark /></div>
        <span className="text-sm font-medium text-foreground tracking-tight">Polymarket</span>
      </div>

      <Card className="w-full max-w-sm border-border/60 bg-card/80 backdrop-blur-sm shadow-none">
        <CardContent className="p-6">
          <div className="mb-6 text-center">
            <h1 className="text-lg font-semibold text-foreground tracking-tight">Set new password</h1>
            <p className="mt-1 text-sm text-muted-foreground">
              Enter the code from your email and choose a new password
            </p>
          </div>

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
                      <Input type="email" placeholder="you@example.com" autoComplete="email" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="code"
                render={() => (
                  <FormItem>
                    <FormLabel className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                      Reset code
                    </FormLabel>
                    <FormControl>
                      <OtpInput
                        value={code}
                        onChange={(v) => {
                          setCode(v);
                          form.setValue("code", v, { shouldValidate: true });
                        }}
                        error={!!form.formState.errors.code}
                      />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="newPassword"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                      New password
                    </FormLabel>
                    <FormControl>
                      <Input type="password" placeholder="Min. 8 characters" autoComplete="new-password" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <FormField
                control={form.control}
                name="confirmPassword"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel className="text-xs font-medium text-muted-foreground uppercase tracking-wide">
                      Confirm password
                    </FormLabel>
                    <FormControl>
                      <Input type="password" placeholder="Repeat password" autoComplete="new-password" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />

              <Button type="submit" disabled={mutation.isPending} className="w-full">
                {mutation.isPending ? "Resetting..." : "Reset password"}
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
        </CardContent>
      </Card>
    </div>
  );
}
