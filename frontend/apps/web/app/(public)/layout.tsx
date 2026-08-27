import Header from "@/components/shared/header"
import Footer from "@/components/shared/footer"

export default function PublicLayout({ children }: { children: React.ReactNode }) {
  return (
    <div className="flex flex-col min-h-dvh">
      <Header />
      <main id="main-content" className="flex-1 outline-none" tabIndex={-1}>
        {children}
      </main>
      <Footer />
    </div>
  )
}
