/**
 * The ⌘K affordance must not be advertised to devices that cannot press it.
 *
 * The trigger is hidden at every size (`hidden`, no breakpoint) because the
 * header search field and the mobile drawer cover navigation. It is still
 * *rendered*, so the ⌘K / Ctrl+K listener keeps working for anyone with a
 * hardware keyboard.
 *
 * On assertions: this project does not resolve Tailwind utilities to computed
 * styles under jsdom, so `toBeVisible()` would read a `display:none` class as
 * visible. These tests pin the class contract - the breakpoint tokens - which
 * is the durable part anyway. Where behaviour really is observable (the dialog
 * opening), that is asserted directly.
 */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CommandPalette, type CommandItem } from "@/components/shared/command-palette";

const items: CommandItem[] = [
  { id: "home", label: "Home", category: "Navigation", action: () => {} },
];

/**
 * The trigger has no accessible name once it is `display:none` - it leaves the
 * accessibility tree, which is the point. So reach it by its stable content
 * rather than by role.
 */
const trigger = () => screen.getByText("Search...").closest("button")!;

describe("CommandPalette trigger", () => {
  it("is hidden at every size, not just below lg", () => {
    render(<CommandPalette items={items} />);
    const cls = trigger().className;

    // `hidden` with no breakpoint: gone from the header everywhere. It used to
    // carry `lg:inline-flex`, which left it visible on desktop.
    expect(cls).toMatch(/(^|\s)hidden(\s|$)/);
    expect(cls).not.toContain("lg:inline-flex");
    expect(cls).not.toContain("sm:inline-flex");
  });

  it("keeps the ⌘K shortcut working even though the trigger is gone", () => {
    render(<CommandPalette items={items} />);
    // Removing the component outright would silently kill the keyboard path
    // with nothing left indicating it existed.
    expect(trigger()).toBeInTheDocument();
  });

  it("renders the shortcut hint inside a now-unconditional badge", () => {
    render(<CommandPalette items={items} />);
    // The badge itself needs no breakpoint: the whole trigger is hidden, so the
    // hint is unreachable anyway.
    expect(screen.getByText("⌘K").className).toContain("inline-flex");
  });

  it("opens on Ctrl+K even though no hint is visible", async () => {
    const user = userEvent.setup();
    render(<CommandPalette items={items} />);

    // The listener is unconditional. A tablet with a hardware keyboard can fire
    // Ctrl+K, and a shortcut that dies with its hint is worse than a stray one.
    await user.keyboard("{Control>}k{/Control}");
    expect(screen.getByPlaceholderText("Search...")).toBeInTheDocument();
  });

  it("opens on Meta+K as well", async () => {
    const user = userEvent.setup();
    render(<CommandPalette items={items} />);

    await user.keyboard("{Meta>}k{/Meta}");
    expect(screen.getByPlaceholderText("Search...")).toBeInTheDocument();
  });

  it("does not open on a bare k without the modifier", async () => {
    const user = userEvent.setup();
    render(<CommandPalette items={items} />);

    // A bare "k" must not steal the key from whatever field the user is in.
    await user.keyboard("k");
    expect(screen.queryByPlaceholderText("Search...")).toBeNull();
  });

  it("still opens when the hidden trigger is clicked", async () => {
    // `hidden` is CSS only - the handler is still attached, so a programmatic
    // or screen-reader-driven activation opens the palette rather than
    // throwing against a detached node.
    const user = userEvent.setup();
    render(<CommandPalette items={items} />);

    await user.click(trigger());
    expect(screen.getByPlaceholderText("Search...")).toBeInTheDocument();
  });

  it("closes again on Escape", async () => {
    const user = userEvent.setup();
    render(<CommandPalette items={items} />);

    await user.keyboard("{Control>}k{/Control}");
    expect(screen.getByPlaceholderText("Search...")).toBeInTheDocument();

    await user.keyboard("{Escape}");
    expect(screen.queryByPlaceholderText("Search...")).toBeNull();
  });

  it("keeps a text label for screen readers", () => {
    render(<CommandPalette items={items} />);
    // The visible "Search..." text is unconditional, so the trigger has an
    // accessible name from its content.
    expect(screen.getByText("Search...")).toBeInTheDocument();
  });
});