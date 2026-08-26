"use client";

import { useCallback, useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { QRCodeSVG } from "qrcode.react";
import { twoFactorApi } from "@/lib/api/auth";
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
  CardDescription,
  CardHeader,
  CardTitle,
} from "@workspace/ui/components/card";
import { OtpInput } from "@/components/auth/otp-input";
import { sileo } from "sileo";

const enableSchema = z.object({
  code: z.string().length(6, "Code must be 6 digits").regex(/^\d{6}$/, "Code must be 6 digits"),
  password: z.string().min(1, "Password is required"),
});
type EnableInput = z.infer<typeof enableSchema>;

export function TwoFactorPageClient() {
  const queryClient = useQueryClient();
  const [setupData, setSetupData] = useState<{ uri: string } | null>(null);
  const [step, setStep] = useState<"status" | "setup" | "enable">("status");
  const [code, setCode] = useState("");

  const { data: status, isLoading } = useQuery({
    queryKey: ["2fa-status"] as const,
    queryFn: () => twoFactorApi.status(),
    retry: false,
  });

  const enableForm = useForm<EnableInput>({
    resolver: zodResolver(enableSchema),
    defaultValues: { code: "", password: "" },
  });

  const setupMutation = useMutation({
    mutationFn: () => twoFactorApi.setup(),
    onSuccess: (data) => {
      setSetupData(data.data);
      setStep("setup");
    },
    onError: (err) => {
      sileo.error({ title: err instanceof Error ? err.message : "Failed to setup 2FA" });
    },
  });

  const enableMutation = useMutation({
    mutationFn: (data: EnableInput) => twoFactorApi.enable(data.code),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["2fa-status"] });
      setStep("status");
      setCode("");
      setSetupData(null);
      enableForm.reset();
      sileo.success({ title: "2FA enabled" });
    },
    onError: (err) => {
      sileo.error({ title: err instanceof Error ? err.message : "Failed to enable 2FA" });
    },
  });

  const disableMutation = useMutation({
    mutationFn: (data: EnableInput) => twoFactorApi.disable(data.code, data.password),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["2fa-status"] });
      setCode("");
      enableForm.reset();
      sileo.success({ title: "2FA disabled" });
    },
    onError: (err) => {
      sileo.error({ title: err instanceof Error ? err.message : "Failed to disable 2FA" });
    },
  });

  const handleEnable = useCallback(
    (data: EnableInput) => enableMutation.mutate(data),
    [enableMutation]
  );

  if (isLoading) {
    return (
      <div className="container mx-auto max-w-md px-4 py-8">
        <div className="text-sm text-muted-foreground">Loading...</div>
      </div>
    );
  }

  const isEnabled = status?.data?.is_2fa_enabled;

  return (
    <div className="container mx-auto max-w-md px-4 py-8 space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Two-Factor Authentication</h1>
        <p className="text-sm text-muted-foreground mt-1">
          Add an extra layer of security to your account
        </p>
      </div>

      {/* Enabled — show disable form */}
      {isEnabled && step === "status" && (
        <Card>
          <CardHeader className="pb-4">
            <CardTitle className="text-base flex items-center gap-2">
              <span className="size-2 rounded-full bg-green-500 inline-block" />
              2FA is enabled
            </CardTitle>
            <CardDescription>
              Your account is protected with an authenticator app.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button
              variant="destructive"
              onClick={() => setStep("enable")}
            >
              Disable 2FA
            </Button>
          </CardContent>
        </Card>
      )}

      {/* Disable form */}
      {isEnabled && step === "enable" && (
        <Card>
          <CardHeader className="pb-4">
            <CardTitle className="text-base">Disable 2FA</CardTitle>
            <CardDescription>
              Enter your authenticator code and password to disable.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Form {...enableForm}>
              <form
                onSubmit={enableForm.handleSubmit((data) => disableMutation.mutate(data))}
                className="space-y-4"
              >
                <FormField
                  control={enableForm.control}
                  name="code"
                  render={() => (
                    <FormItem>
                      <FormLabel>Authenticator code</FormLabel>
                      <FormControl>
                        <OtpInput
                          value={code}
                          onChange={(v) => {
                            setCode(v);
                            enableForm.setValue("code", v, { shouldValidate: true });
                          }}
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <FormField
                  control={enableForm.control}
                  name="password"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Password</FormLabel>
                      <FormControl>
                        <Input type="password" placeholder="Your password" {...field} />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <div className="flex gap-2">
                  <Button
                    type="submit"
                    variant="destructive"
                    disabled={disableMutation.isPending}
                  >
                    {disableMutation.isPending ? "Disabling..." : "Disable 2FA"}
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    onClick={() => { setStep("status"); setCode(""); enableForm.reset(); }}
                  >
                    Cancel
                  </Button>
                </div>
              </form>
            </Form>
          </CardContent>
        </Card>
      )}

      {/* Setup — show QR + confirm */}
      {step === "setup" && setupData && (
        <Card>
          <CardHeader className="pb-4">
            <CardTitle className="text-base">Scan the QR code</CardTitle>
            <CardDescription>
              Scan with your authenticator app (Google Authenticator, Authy, etc.)
            </CardDescription>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="flex flex-col items-center gap-3">
              <div className="p-2 bg-white rounded-lg">
                <QRCodeSVG value={setupData.uri} size={128} level="M" />
              </div>
              <p className="text-xs text-muted-foreground">
                Can&apos;t scan? Enter this secret manually:{" "}
                <code className="font-mono text-xs bg-muted px-1 rounded break-all">
                  {(() => { try { return new URL(setupData.uri).searchParams.get("secret") ?? "—" } catch { return "—" } })()}
                </code>
              </p>
            </div>

            <Form {...enableForm}>
              <form onSubmit={enableForm.handleSubmit(handleEnable)} className="space-y-4">
                <FormField
                  control={enableForm.control}
                  name="code"
                  render={() => (
                    <FormItem>
                      <FormLabel>Verification code</FormLabel>
                      <FormControl>
                        <OtpInput
                          value={code}
                          onChange={(v) => {
                            setCode(v);
                            enableForm.setValue("code", v, { shouldValidate: true });
                          }}
                          autoFocus
                        />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <FormField
                  control={enableForm.control}
                  name="password"
                  render={({ field }) => (
                    <FormItem>
                      <FormLabel>Confirm with password</FormLabel>
                      <FormControl>
                        <Input type="password" placeholder="Your password" {...field} />
                      </FormControl>
                      <FormMessage />
                    </FormItem>
                  )}
                />
                <div className="flex gap-2">
                  <Button
                    type="submit"
                    disabled={enableMutation.isPending || code.length !== 6}
                  >
                    {enableMutation.isPending ? "Enabling..." : "Enable 2FA"}
                  </Button>
                  <Button
                    type="button"
                    variant="ghost"
                    onClick={() => { setStep("status"); setCode(""); setSetupData(null); enableForm.reset(); }}
                  >
                    Cancel
                  </Button>
                </div>
              </form>
            </Form>
          </CardContent>
        </Card>
      )}

      {/* Not enabled — start setup */}
      {!isEnabled && step === "status" && (
        <Card>
          <CardHeader className="pb-4">
            <CardTitle className="text-base flex items-center gap-2">
              <span className="size-2 rounded-full bg-muted-foreground inline-block" />
              2FA is not enabled
            </CardTitle>
            <CardDescription>
              Protect your account with an authenticator app.
            </CardDescription>
          </CardHeader>
          <CardContent>
            <Button
              onClick={() => setupMutation.mutate()}
              disabled={setupMutation.isPending}
            >
              {setupMutation.isPending ? "Preparing..." : "Set up 2FA"}
            </Button>
          </CardContent>
        </Card>
      )}
    </div>
  );
}
