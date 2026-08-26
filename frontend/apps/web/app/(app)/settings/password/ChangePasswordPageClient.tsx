"use client";

import { useCallback, useState } from "react";
import { useMutation, useQueryClient } from "@tanstack/react-query";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import { z } from "zod";
import { accountApi } from "@/lib/api/auth";
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
import { Alert, AlertDescription } from "@workspace/ui/components/alert";
import {
  Card,
  CardContent,
  CardDescription,
  CardHeader,
  CardTitle,
} from "@workspace/ui/components/card";
import { sileo } from "sileo";

const schema = z
  .object({
    oldPassword: z.string().min(1, "Current password is required"),
    newPassword: z.string().min(8, "Password must be at least 8 characters"),
    confirmPassword: z.string(),
  })
  .refine((d) => d.newPassword === d.confirmPassword, {
    message: "Passwords do not match",
    path: ["confirmPassword"],
  });

type Input = z.infer<typeof schema>;

export function ChangePasswordPageClient() {
  const queryClient = useQueryClient();
  const [success, setSuccess] = useState(false);

  const form = useForm<Input>({
    resolver: zodResolver(schema),
    defaultValues: { oldPassword: "", newPassword: "", confirmPassword: "" },
  });

  const mutation = useMutation({
    mutationFn: (data: Input) => accountApi.changePassword({ old_password: data.oldPassword, new_password: data.newPassword }),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ["me"] });
      form.reset();
      setSuccess(true);
      sileo.success({ title: "Password changed" });
    },
    onError: (err) => {
      form.setError("root", { message: err instanceof Error ? err.message : "Failed to change password" });
    },
  });

  const onSubmit = useCallback(
    (data: Input) => {
      setSuccess(false);
      mutation.mutate(data);
    },
    [mutation]
  );

  return (
    <div className="container mx-auto max-w-md px-4 py-8 space-y-6">
      <div>
        <h1 className="text-2xl font-semibold">Change Password</h1>
        <p className="text-sm text-muted-foreground mt-1">Update your account password</p>
      </div>

      <Card>
        <CardHeader className="pb-4">
          <CardTitle className="text-base">Update password</CardTitle>
          <CardDescription>Choose a strong password you don&apos;t use elsewhere</CardDescription>
        </CardHeader>
        <CardContent>
          {form.formState.errors.root && (
            <Alert variant="destructive" className="mb-4">
              <AlertDescription>{form.formState.errors.root.message}</AlertDescription>
            </Alert>
          )}
          {success && (
            <Alert className="mb-4 border-green-500/50 text-green-600 dark:text-green-400">
              <AlertDescription>Password updated successfully.</AlertDescription>
            </Alert>
          )}

          <Form {...form}>
            <form onSubmit={form.handleSubmit(onSubmit)} className="space-y-4">
              <FormField
                control={form.control}
                name="oldPassword"
                render={({ field }) => (
                  <FormItem>
                    <FormLabel>Current password</FormLabel>
                    <FormControl>
                      <Input type="password" autoFocus {...field} />
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
                    <FormLabel>New password</FormLabel>
                    <FormControl>
                      <Input type="password" placeholder="Min. 8 characters" {...field} />
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
                    <FormLabel>Confirm new password</FormLabel>
                    <FormControl>
                      <Input type="password" placeholder="Repeat password" {...field} />
                    </FormControl>
                    <FormMessage />
                  </FormItem>
                )}
              />
              <Button type="submit" disabled={mutation.isPending}>
                {mutation.isPending ? "Saving..." : "Update password"}
              </Button>
            </form>
          </Form>
        </CardContent>
      </Card>
    </div>
  );
}
