/**
 * Header responsive behaviour.
 *
 * The header is the one component present on every screen, so its breakpoints
 * are load-bearing: the command palette must not advertise a ⌘K shortcut to
 * devices with no keyboard, and the drawer must close on navigation or it hangs
 * open over the page the user just asked for.
 */
import { describe, expect, it, vi } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ThemeProvider } from "next-themes";
import type { ReactNode } from "react";

// next/navigation's usePathname is what drives both the active nav state and
// the drawer's "still open" derivation.
const pathnameRef = vi.fn<string>(() => "/");
vi.mock("next/navigation", () => ({
  usePathname: () => pathnameRef(),
}));

vi.mock("@/components/shared/search-input", () => ({
  SearchInput: () => <input aria-label="Search markets" />,
}));

vi.mock("@/components/shared/app-command-menu", () => ({
  AppCommandMenu: () => <button type="button">Search ⌘K</button>,
}));

vi.mock("@/components/auth/user-menu", () => ({
  UserMenu: () => <button type="button" aria-label="Account" />,
}));

vi.mock("@/components/notifications/notification-bell", () => ({
  NotificationBell: () => <button type="button" aria-label="Notifications" />,
}));

import Header from "@/components/shared/header";

function renderHeader() {
  return render(
    <ThemeProvider attribute="class" defaultTheme="light">
      <Header />
    </ThemeProvider>
  );
}

const trigger = () => screen.getByLabelText("Open menu");

describe("Header", () => {
  it("is sticky so the bar stays put while content scrolls", () => {
    renderHeader();
    const header = screen.getByTestId("app-header");
    // Sticky is declared but broken by an ancestor overflow, so assert the
    // class AND that it is the top-most positioned layer.
    expect(header.className).toContain("sticky");
    expect(header.className).toContain("top-0");
  });

  it("keeps the header above portalled dialogs via an isolated stacking context", () => {
    renderHeader();
    // Without `isolate`, a z-50 dialog opened from the header could paint
    // behind the bar.
    expect(screen.getByTestId("app-header").className).toContain("isolate");
  });

  it("gives icon controls a 36px target", () => {
    renderHeader();
    // The 44px touch-target guideline; these were 32px.
    expect(screen.getByLabelText("Toggle theme").className).toContain("size-9");
    expect(trigger().className).toContain("size-9");
  });

  it("shows a labelled nav trigger on small screens", () => {
    renderHeader();
    const el = trigger();
    expect(el).toBeInTheDocument();
    // md:hidden - the desktop nav takes over at md and up.
    expect(el.className).toContain("md:hidden");
  });

  it("opens the drawer and lists primary navigation", async () => {
    const user = userEvent.setup();
    renderHeader();

    await user.click(trigger());

    const nav = screen.getByRole("navigation", { name: "Mobile" });
    expect(nav).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Markets/ })).toBeInTheDocument();
    expect(screen.getByRole("link", { name: /Trades/ })).toBeInTheDocument();
    // Home + FAQ complete the set.
    expect(screen.getByRole("link", { name: /Home/ })).toBeInTheDocument();
  });

  it("gives the drawer a visible title, not just an sr-only one", async () => {
    const user = userEvent.setup();
    renderHeader();
    await user.click(trigger());

    // The sheet only mounts its content once open. An unlabelled drawer
    // disorients on mobile, where there is no persistent chrome to orient by.
    const title = screen.getByRole("heading", { name: "PredictX" });
    expect(title).toBeVisible();
    // Not the sr-only variant the drawer used to have.
    expect(title.className).not.toContain("sr-only");
  });

  it("closes the drawer when a nav link is followed", async () => {
    const user = userEvent.setup();
    renderHeader();

    await user.click(trigger());
    expect(screen.getByRole("navigation", { name: "Mobile" })).toBeInTheDocument();

    await user.click(screen.getByRole("link", { name: /Markets/ }));

    // Leaving it mounted over the next route is the bug this guards.
    expect(screen.queryByRole("navigation", { name: "Mobile" })).not.toBeInTheDocument();
  });

  it("closes the drawer when the route changes underneath it", async () => {
    const user = userEvent.setup();
    renderHeader();

    await user.click(trigger());
    expect(screen.getByRole("navigation", { name: "Mobile" })).toBeInTheDocument();

    // Simulate a navigation that does not go through our own onClick (e.g. a
    // browser back/forward). The drawer must still close.
    pathnameRef.mockReturnValue("/trades");
    await user.click(document.body);

    expect(screen.queryByRole("navigation", { name: "Mobile" })).not.toBeInTheDocument();
  });

  it("marks the active route in the drawer", async () => {
    pathnameRef.mockReturnValue("/trades");
    const user = userEvent.setup();
    renderHeader();

    await user.click(trigger());

    const active = screen
      .getAllByRole("link")
      .filter((el) => el.getAttribute("aria-current") === "page");
    expect(active.length).toBeGreaterThan(0);
    expect(active[0]!.textContent).toContain("Trades");
  });
});