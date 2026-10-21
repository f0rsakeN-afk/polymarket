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
import userEvent from "@testing-library/user-event";
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
// The setter is a spy so the keyboard shortcut can be asserted on directly.
const setTheme = vi.hoisted(() => vi.fn());
vi.mock("next-themes", () => ({
  useTheme: () => ({ resolvedTheme: "dark", setTheme }),
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
  // The rail's preference lives in a real cookie, and jsdom shares one document
  // across every test in the file. Without this, whichever test collapsed the
  // rail leaves `sidebar_state=false` behind and every test after it starts
  // collapsed — order-dependent assertions that pass or fail for no visible
  // reason.
  for (const c of document.cookie.split(";")) {
    const name = c.split("=")[0]?.trim();
    if (name) document.cookie = `${name}=; path=/; max-age=0`;
  }
});

describe("admin shell • gate", () => {
  it("shows a signed-in non-admin an explanation, not a redirect", () => {
    meResult.data = { id: "u2", is_admin: false, email: "user@x.com", username: "someone" };
    renderShell();

    expect(screen.getByText(/admin access required/i)).toBeTruthy();
    // The loop was this exact pair of redirects. Neither may happen.
    expect(redirect).not.toHaveBeenCalled();
  });

  it("tells a signed-out operator to sign in, rather than blaming their account", () => {
    // The two are different problems with different fixes. Told "admin access
    // required" when they are simply not signed in, an operator's only move is to
    // ask someone for access they did not need.
    meResult.data = null;
    renderShell();

    expect(screen.getByText(/sign in to continue/i)).toBeTruthy();
    expect(screen.getByRole("link", { name: /^sign in$/i })).toBeTruthy();
  });

  it("offers a way to swap accounts to a signed-in non-admin", () => {
    meResult.data = { id: "u2", is_admin: false, email: "user@x.com", username: "someone" };
    renderShell();

    // Without this the gate is a dead end on a shared machine: the operator needs
    // to sign in as themselves, and the only offered route was the storefront.
    expect(screen.getByRole("link", { name: /sign in as someone else/i })).toBeTruthy();
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

describe("admin shell • the rail is toggleable", () => {
  /** Both triggers, collapsed by label rather than by position. */
  function triggers() {
    return screen.getAllByRole("button", { name: /collapse navigation|open navigation|toggle sidebar/i });
  }

  it("offers a toggle on desktop, not only the 4px edge strip", async () => {
    renderShell();

    // `SidebarRail` has `tabIndex={-1}`, so before this existed the rail was
    // collapsible *only* by clicking a 4px strip nobody can see — and a keyboard
    // user could not collapse it at all. The header trigger is what makes it
    // reachable.
    expect(triggers().length).toBeGreaterThan(0);
  });

  it("collapses the rail when the toggle is pressed, and expands it again", async () => {
    const user = userEvent.setup();
    const { container } = renderShell();

    const rail = () => container.querySelector('[data-slot="sidebar"]');
    expect(rail()?.getAttribute("data-state")).toBe("expanded");

    await user.click(triggers()[0]!);
    expect(rail()?.getAttribute("data-state")).toBe("collapsed");

    await user.click(screen.getAllByRole("button", { name: /collapse navigation|open navigation|toggle sidebar/i })[0]!);
    expect(rail()?.getAttribute("data-state")).toBe("expanded");
  });

  it("remembers the choice, so a reload does not slam the rail open again", async () => {
    const user = userEvent.setup();
    const { container, unmount } = renderShell();

    await user.click(triggers()[0]!);
    expect(container.querySelector('[data-slot="sidebar"]')?.getAttribute("data-state")).toBe(
      "collapsed"
    );

    // A full navigation is the case that matters: an operator who collapsed the
    // rail to read a wide audit row should not have it back on every visit.
    unmount();
    renderShell();

    await screen.findByText("panel content");
    expect(
      document.cookie.includes("sidebar_state=false")
    ).toBe(true);
  });

  it("collapses to icons rather than sliding off-screen at desktop width", async () => {
    const user = userEvent.setup();
    renderShell();

    // `collapsible="offcanvas"` at `md` and up makes the rail vanish entirely and
    // leaves the content full-bleed — a mobile drawer on a desktop. `icon`
    // narrows the rail to the icon column so the page gets the space back, and
    // `data-collapsible` is what the width rules key off.
    const rail = document.querySelector('[data-slot="sidebar"]');
    expect(rail?.getAttribute("data-collapsible")).toBe("");

    await user.click(triggers()[0]!);
    expect(rail?.getAttribute("data-collapsible")).toBe("icon");
  });
});

describe("admin shell • theme", () => {
  it("offers the theme toggle where a desktop operator can reach it", () => {
    renderShell();

    // It used to live only inside a `md:hidden` sticky bar, so on a desktop —
    // the main way this tool is used — there was no way to switch theme at all.
    // Asserting on presence alone would have passed then too, because the element
    // exists; what matters is that it is in the rail, not gated to small screens.
    const inRail = screen
      .getAllByRole("button", { name: /switch to (light|dark) theme/i })
      .some((el) => el.closest('[data-slot="sidebar-footer"]') !== null);
    expect(inRail).toBe(true);
  });

  it("switches on the keyboard shortcut, and ignores it without the modifier", () => {
    renderShell();
    const fire = (init: KeyboardEventInit) =>
      window.dispatchEvent(new KeyboardEvent("keydown", { ...init, cancelable: true }));

    fire({ key: "d", shiftKey: true }); // no Ctrl/Cmd — must be ignored
    expect(setTheme).not.toHaveBeenCalled();

    fire({ key: "d", shiftKey: true, ctrlKey: true });
    expect(setTheme).toHaveBeenCalledWith("light");
  });
});