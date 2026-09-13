import type { Metadata } from "next";

export const metadata: Metadata = {
  robots: {
    index: false,
    follow: false,
  },
};

export default function PlainLayout({ children }: { children: React.ReactNode }) {
  return (
    <main id="main-content" className="outline-none" tabIndex={-1}>
      {children}
    </main>
  );
}
