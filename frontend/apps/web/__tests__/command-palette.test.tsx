/**
 * Two bugs guarded here, both of which only showed up at runtime:
 *
 *  1. The `undefined.subscribe` crash. cmdk's Input/List/Group/Item each read a
 *     store from React context that only `<Command>` provides. For a while
 *     CommandDialog rendered just the Dialog shell, so nothing above them
 *     supplied a store and every child dereferenced undefined. CommandDialog now
 *     wraps its children itself.
 *
 *  2. Keyboard navigation. A custom onKeyDown used to call preventDefault() on
 *     ArrowDown/ArrowUp/Enter. cmdk's root handler runs the consumer's onKeyDown
 *     first and then skips its own branch when `e.defaultPrevented`, so that
 *     suppressed cmdk's navigation entirely — while the replacement never worked
 *     either, because its selection state was indexed off an empty array while
 *     the search box was empty. cmdk now owns selection.
 */
import { describe, expect, it, vi } from "vitest";
import { render, screen, act } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { useState } from "react";
import { CommandPalette, type CommandItem } from "@/components/shared/command-palette";

function makeItems(picked: string[]): CommandItem[] {
  return [
    { id: "home", label: "Home", description: "Go to homepage", category: "Navigation", keywords: ["home", "dashboard"], action: () => picked.push("home") },
    { id: "markets", label: "Markets", description: "Browse prediction markets", category: "Navigation", keywords: ["markets", "trade"], action: () => picked.push("markets") },
    { id: "trades", label: "Trades", description: "View trade feed", category: "Navigation", keywords: ["trades"], action: () => picked.push("trades") },
    { id: "portfolio", label: "Portfolio", description: "View your portfolio", category: "Navigation", keywords: ["portfolio"], action: () => picked.push("portfolio") },
  ];
}

/** The dialog only mounts its content once open, so open it first. */
async function openPalette(items: CommandItem[]) {
  const user = userEvent.setup();
  render(<CommandPalette items={items} placeholder="Search" />);
  await user.click(screen.getByRole("button", { name: /search/i }));
  return user;
}

function cmdkItems() {
  return Array.from(document.querySelectorAll("[cmdk-item]"));
}

function selectedLabel() {
  const el = document.querySelector('[cmdk-item][aria-selected="true"]');
  // The item renders label + description + a category badge, so read the label
  // span rather than the whole textContent.
  return el?.querySelector("span")?.textContent?.trim() ?? null;
}

describe("CommandPalette", () => {
  it("renders without the undefined.subscribe crash", async () => {
    // Opening mounts CommandInput/List/Group/Item under the dialog. Before the
    // store was provided this threw on every child.
    await openPalette(makeItems([]));
    expect(screen.getByPlaceholderText("Search")).toBeInTheDocument();
  });

  it("lists every item when opened with no query", async () => {
    await openPalette(makeItems([]));
    expect(cmdkItems()).toHaveLength(4);
  });

  it("auto-selects the first item so arrows have somewhere to go", async () => {
    await openPalette(makeItems([]));
    expect(selectedLabel()).toBe("Home");
  });

  it("moves selection with ArrowDown and ArrowUp", async () => {
    const user = await openPalette(makeItems([]));
    const input = screen.getByPlaceholderText("Search");

    await user.click(input);
    await user.keyboard("{ArrowDown}");
    expect(selectedLabel()).toBe("Markets");

    await user.keyboard("{ArrowDown}");
    expect(selectedLabel()).toBe("Trades");

    await user.keyboard("{ArrowUp}");
    expect(selectedLabel()).toBe("Markets");
  });

  it("jumps with Home and End", async () => {
    const user = await openPalette(makeItems([]));
    await user.click(screen.getByPlaceholderText("Search"));

    await user.keyboard("{End}");
    expect(selectedLabel()).toBe("Portfolio");

    await user.keyboard("{Home}");
    expect(selectedLabel()).toBe("Home");
  });

  it("runs the selected item's action on Enter", async () => {
    const picked: string[] = [];
    const user = await openPalette(makeItems(picked));
    await user.click(screen.getByPlaceholderText("Search"));

    await user.keyboard("{ArrowDown}{Enter}");
    expect(picked).toEqual(["markets"]);
  });

  it("filters by keyword, which cmdk scores from value + keywords", async () => {
    const user = await openPalette(makeItems([]));
    await user.click(screen.getByPlaceholderText("Search"));

    // "dashboard" is only in Home's keywords, never in its visible label.
    await user.keyboard("dash");
    expect(cmdkItems()).toHaveLength(1);
    expect(cmdkItems()[0]?.textContent).toContain("Home");
  });

  it("filters by description text", async () => {
    const user = await openPalette(makeItems([]));
    await user.click(screen.getByPlaceholderText("Search"));

    await user.keyboard("feed");
    expect(cmdkItems()).toHaveLength(1);
    expect(cmdkItems()[0]?.textContent).toContain("Trades");
  });

  it("shows the empty message when nothing matches", async () => {
    await openPalette(makeItems([]));
    const user = userEvent.setup();
    await user.click(screen.getByPlaceholderText("Search"));
    await user.keyboard("zzzzz");

    expect(cmdkItems()).toHaveLength(0);
    expect(screen.getByText("No results found.")).toBeInTheDocument();
  });

  it("selects with Enter after filtering", async () => {
    const picked: string[] = [];
    const user = await openPalette(makeItems(picked));
    await user.click(screen.getByPlaceholderText("Search"));

    await user.keyboard("portf");
    await user.keyboard("{Enter}");
    expect(picked).toEqual(["portfolio"]);
  });

  it("keeps recent selections and can replay one", async () => {
    const picked: string[] = [];
    const onChange = vi.fn();
    const user = userEvent.setup();
    const items = makeItems(picked);

    function Harness() {
      const [recent, setRecent] = useState<string[]>([]);
      return (
        <CommandPalette
          items={items}
          recentSearches={recent}
          onRecentSearchChange={(next) => {
            onChange(next);
            setRecent(next);
          }}
        />
      );
    }

    render(<Harness />);
    await user.click(screen.getByRole("button", { name: /search/i }));
    await user.click(screen.getByPlaceholderText("Search..."));
    await user.keyboard("Home{Enter}");

    expect(picked).toEqual(["home"]);
    // Recents are tracked by label, not id.
    expect(onChange).toHaveBeenCalledWith(["Home"]);

    // Reopening shows the Recent group, and picking one restores the query.
    await act(async () => {});
    await user.click(screen.getByRole("button", { name: /search/i }));
    expect(screen.getByText("Recent")).toBeInTheDocument();
    const replayed = cmdkItems().find((el) => el.textContent?.trim() === "Home");
    expect(replayed).toBeDefined();
  });
});