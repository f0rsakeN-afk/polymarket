"use client";

import { useCallback } from "react";
import Link from "next/link";
import { useRouter } from "next/navigation";
import {
  DropdownMenu,
  DropdownMenuContent,
  DropdownMenuItem,
  DropdownMenuLabel,
  DropdownMenuSeparator,
  DropdownMenuTrigger,
} from "@workspace/ui/components/dropdown-menu";
import { Avatar, AvatarFallback } from "@workspace/ui/components/avatar";
import { Button } from "@workspace/ui/components/button";
import { useAuth } from "@/hooks/use-auth-context";

export function UserMenu() {
  const { user, logout } = useAuth();
  const router = useRouter();

  const handleLogout = useCallback(async () => {
    await logout();  // logout() already calls authApi.logout() internally
    router.push("/");
  }, [logout, router]);

  if (!user) {
    return (
      <Button variant="outline" onClick={() => router.push("/login")}>
        Sign in
      </Button>
    );
  }

  const initials = (user.username ?? user.email ?? "?")
    .split(/[_\- ]/)
    .map((p) => p[0] ?? "")
    .join("")
    .toUpperCase()
    .slice(0, 2);

  return (
    <DropdownMenu>
      <DropdownMenuTrigger className="relative flex h-8 w-8 shrink-0 items-center justify-center rounded-full bg-transparent outline-none ring-offset-background transition-colors focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 hover:bg-accent hover:text-accent-foreground" aria-label="User menu">
        <Avatar className="h-8 w-8">
          <AvatarFallback className="bg-primary/10 text-primary text-xs font-semibold">
            {initials}
          </AvatarFallback>
        </Avatar>
      </DropdownMenuTrigger>

      <DropdownMenuContent align="end" className="w-56">
        <DropdownMenuLabel className="font-normal">
          <div className="flex flex-col gap-1">
            <p className="text-sm font-medium">{user.username}</p>
            <p className="text-xs text-muted-foreground">{user.email}</p>
          </div>
        </DropdownMenuLabel>

        <DropdownMenuSeparator />

        <DropdownMenuItem>
          <Link href="/portfolio" className="w-full">Portfolio</Link>
        </DropdownMenuItem>
        <DropdownMenuItem>
          <Link href="/orders" className="w-full">Orders</Link>
        </DropdownMenuItem>
        <DropdownMenuItem>
          <Link href="/settings/sessions" className="w-full">Sessions</Link>
        </DropdownMenuItem>
        <DropdownMenuItem>
          <Link href="/settings/referrals" className="w-full">Referrals</Link>
        </DropdownMenuItem>
        <DropdownMenuItem>
          <Link href="/settings/notifications" className="w-full">Notifications</Link>
        </DropdownMenuItem>

        {user.is_admin && (
          <>
            <DropdownMenuSeparator />
            <DropdownMenuItem>
              <Link href="/admin" className="w-full">Admin</Link>
            </DropdownMenuItem>
          </>
        )}

        <DropdownMenuSeparator />

        <DropdownMenuItem onClick={handleLogout} className="text-destructive cursor-pointer">
          Sign out
        </DropdownMenuItem>
      </DropdownMenuContent>
    </DropdownMenu>
  );
}
