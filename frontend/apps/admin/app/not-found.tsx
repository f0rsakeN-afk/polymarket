import Link from "next/link"
import { buttonVariants } from "@workspace/ui/components/button"
import { cn } from "@workspace/ui/lib/utils"

export default function NotFound() {
  return (
    <div className="flex min-h-[60vh] flex-col items-center justify-center px-4 py-16 text-center">
      <h1 className="text-4xl font-bold tracking-tight">404</h1>
      <h2 className="mt-2 text-lg font-semibold">Page not found</h2>
      <p className="mt-2 max-w-md text-sm text-muted-foreground">
        That page does not exist in the admin app. If you were sent here from a
        link, it is worth checking whether the target still exists.
      </p>
      <Link href="/" className={cn(buttonVariants({ variant: "default" }), "mt-6")}>
        Back to the dashboard
      </Link>
    </div>
  )
}
