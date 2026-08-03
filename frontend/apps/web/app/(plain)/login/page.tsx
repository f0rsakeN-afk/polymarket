import type { Metadata } from "next";
import { LoginForm } from "@/components/auth/login-form";

export const metadata: Metadata = {
  title: "Sign In",
  description: "Sign in to your PredictX account to trade on prediction markets.",
};

export default function LoginPage() {
  return <LoginForm />;
}
