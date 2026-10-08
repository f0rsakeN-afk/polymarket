/**
 * The ⌘K affordance must not be advertised to devices that cannot press it.
 *
 * `sm:` is 640px, which a portrait tablet clears, so the previous `sm:` classes
 * still showed the shortcut badge on exactly the devices it was meant to hide
 * from. These tests pin the breakpoint to `lg:` and check that the listener
 * stays live regardless - hiding the hint must not disable the shortcut.
 *
 * Note on assertions: this project does not resolve Tailwind utilities to
 * computed styles under jsdom, so these assert the *class contract* rather than
 * measured layout. That is the durable thing to pin - the breakpoint tokens -
 * not a value jsdom cannot compute.
 */
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { CommandPalette, type CommandItem } from "@/components/shared/command-palette";

const items: CommandItem[] = [
  { id: "home", label: "Home", category: "Navigation", action: () => {} },
];

const trigger = () => screen.getByRole("button", { name: /search/i });

describe("CommandPalette trigger", () => {
  it("is hidden below lg and shown from lg up", () => {
    render(<CommandPalette items={items} />);
    const cls = trigger().className;

    // Hidden by default, revealed at lg - the pair that makes it desktop-only.
    expect(cls).toMatch(/(^|\s)hidden(\s|$)/);
    expect(cls).toContain("lg:inline-flex");

    // `sm:` would leave the badge showing on portrait tablets.
    expect(cls).not.toContain("sm:inline-flex");
    expect(cls).not.toContain("sm:flex");
  });

  it("renders the shortcut hint inside a now-unconditional badge", () => {
    render(<CommandPalette items={items} />);
    // The badge itself needs no breakpoint: the whole trigger is hidden below
    // lg, so the hint is unreachable there anyway.
    expect(screen.getByText("⌘K").className).toContain("inline-flex");
  });

  it("still opens on click at any viewport", async () => {
    const user = userEvent.setup();
    render(<CommandPalette items={items} />);

    await user.click(trigger());
    expect(screen.getByPlaceholderText("Search...")).toBeInTheDocument();
  });

  it("still opens on Ctrl+K even though the hint is hidden on small screens", async () => {
    const user = userEvent.setup();
    render(<CommandPalette items={items} />);

    // The listener is unconditional. A tablet with a hardware keyboard can fire
    // Ctrl+K, and a shortcut that dies with its hint is worse than a stray one.
    await user.keyboard("{Control>}k{/Control}");
    expect(screen.getByPlaceholderText("Search...")).toBeInTheDocument();
  });

  it("keeps a text label for screen readers at every size", () => {
    render(<CommandPalette items={items} />);
    // The visible "Search..." text is now unconditional, so the trigger still
    // has an accessible name once the button is displayed on desktop.
    expect(screen.getByText("Search...")).toBeInTheDocument();
  });
});