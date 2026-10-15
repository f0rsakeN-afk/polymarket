/**
 * The admin shell: the gate, and the way out.
 *
 * The gate is where the real bug was. `app/(admin)/page.tsx` and the shell both
 * redirected a non-admin with `NEXT_PUBLIC_SITE_URL ?? "/"`, on the reasoning
 * that "there is no index here to fall back to" - but there *is* one, and it
 * redirects to the same place. `/users` → `/` → `/` → … until the browser gives
 * up. Every non-admin who opened the app got a spinner instead of a page.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const currentUser = { id: "u1", is_admin: true, email: "admin@x.com", username: "ops" };
const meResult: { data: typeof currentUser | null } = { data: currentUser };

vi.mock("@/hooks/use-auth", () => ({
  useCurrentUser: () => ({ data: meResult.data, isLoading: false }),
}));

const redirect = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push: vi.fn() }),
  usePathname: () => "/users",
  redirect: (...args: unknown[]) => redirect(...args),
}));

const logout = vi.fn().mockResolvedValue({ success: true });
vi.mock("@workspace/api-client/client", () => ({
  api: { post: (...args: unknown[]) => logout(...args) },
  isUnauthorized: () => false,
}));

vi.mock("sileo", () => ({ sileo: { success: vi.fn(), error: vi.fn() } }));

// next-themes needs a DOM; the real provider is not what these tests are about.
vi.mock("next-themes", () => ({
  useTheme: () => ({ resolvedTheme: "dark", setTheme: vi.fn() }),
}));

import { AdminShell } from "@/components/admin-shell";

function renderShell() {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={client}>
      <AdminShell>
        <p>panel content</p>
      </AdminShell>
    </QueryClientProvider>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  meResult.data = { ...currentUser };
  delete process.env.NEXT_PUBLIC_SITE_URL;
});

describe("admin shell • gate", () => {
  it("shows a non-admin an explanation, not a redirect", () => {
    meResult.data = null;
    renderShell();

    expect(screen.getByText(/admin access required/i)).toBeTruthy();
    // The loop was this exact pair of redirects. Neither may happen.
    expect(redirect).not.toHaveBeenCalled();
  });

  it("does not redirect a non-admin to its own index", () => {
    // `/users` → `/` → `/` → … with SITE_URL unset. The bug only exists when the
    // variable is absent, which is why the previous test clears it.
    meResult.data = null;
    renderShell();

    const target = redirect.mock.calls[0]?.[0];
    expect(target).not.toBe("/");
  });

  it("renders the panel for an admin", () => {
    renderShell();
    expect(screen.getByText("panel content")).toBeTruthy();
    expect(screen.queryByText(/admin access required/i)).toBeNull();
  });

  it("always offers a way out", () => {
    renderShell();
    // An operator tool gets used on shared and borrowed machines. "Who was in
    // this session" has to be answerable by whoever is at the keyboard.
    expect(screen.getByRole("button", { name: /account menu/i })).toBeTruthy();
    expect(screen.getByText("admin@x.com")).toBeTruthy();
  });
});

describe("admin shell • accessibility", () => {
  it("marks the active section", () => {
    renderShell();
    const link = screen.getByRole("link", { name: /users/i });
    expect(link.getAttribute("aria-current")).toBe("page");
  });

  it("offers a skip link, as the storefront does", () => {
    renderShell();
    expect(screen.getByRole("link", { name: /skip to main content/i })).toBeTruthy();
  });
});