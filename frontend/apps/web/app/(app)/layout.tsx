import type { Metadata } from "next";
import Header from "@/components/shared/header";
import Footer from "@/components/shared/footer";

const baseUrl = process.env.NEXT_PUBLIC_API_URL?.replace("/api/v1", "") ?? "https://predictx.io";

export const metadata: Metadata = {
  alternates: {
    canonical: baseUrl,
  },
};

export default function AppLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex flex-col min-h-dvh">
      <Header />
      <main id="main-content" className="flex-1 outline-none" tabIndex={-1}>
        {children}
      </main>
      <Footer />
    </div>
  );
}
