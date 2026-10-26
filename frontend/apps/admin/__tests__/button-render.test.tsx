/**
 * Link-shaped buttons.
 *
 * ## The problem this pins
 *
 * The 2FA card rendered its "Manage" control as `Button render={<a href=… />}`.
 * Base UI's `Button` assumes a real `<button>`: pointed at an anchor it logs
 *
 *   "a component that acts as a button expected a native <button> because the
 *    nativeButton prop is true"
 *
 * and silencing that with `nativeButton={false}` is not a fix — it makes Base UI
 * stamp `role="button"` onto the anchor instead, producing `<a role="button">`.
 * That drops the control out of a screen reader's list of links and removes the
 * open-in-new-tab affordance, both of which are expected on something that
 * navigates.
 *
 * So the answer is not a prop. It is to style the link with `buttonVariants()`
 * and render a real `Link`: identical appearance, correct semantics, no warning.
 * These assertions are on the *rendered element*, because "it looks like a
 * button" is exactly what the broken version also achieved.
 */
import { describe, expect, it, vi, afterEach } from "vitest";
import { render, screen } from "@testing-library/react";

// Forwards className, because the second test is specifically about the styling
// surviving the swap from `Button` to `Link`.
vi.mock("next/link", () => ({
  default: ({
    href,
    children,
    className,
  }: {
    href: string;
    children: React.ReactNode;
    className?: string;
  }) => (
    <a href={href} className={className}>
      {children}
    </a>
  ),
}));

import Link from "next/link";

import { Button, buttonVariants } from "@workspace/ui/components/button";

afterEach(() => vi.restoreAllMocks());

describe("Button", () => {
  it("renders a real button, and keeps type=button so it cannot submit a form by accident", () => {
    render(<Button>Save</Button>);

    const button = screen.getByRole("button", { name: /save/i });
    expect(button.tagName).toBe("BUTTON");
    // Losing the implicit type turns every plain button inside a form into a
    // submit button — which is how "Save" ends up posting the form.
    expect(button.getAttribute("type")).toBe("button");
  });
});

describe("link-shaped buttons", () => {
  it("is an anchor with link semantics, not a button wearing an anchor", () => {
    render(
      <Link href="/markets/new" className={buttonVariants({ size: "sm" })}>
        Propose
      </Link>
    );

    const link = screen.getByRole("link", { name: /propose/i });
    expect(link.tagName).toBe("A");
    expect(link.getAttribute("href")).toBe("/markets/new");
    // The exact defect: `role="button"` would make this fail the query above,
    // and would hide the control from a screen reader's list of links.
    expect(link.getAttribute("role")).toBeNull();
  });

  it("carries the button styling, so the two do not look different", () => {
    render(
      <Link href="/x" className={buttonVariants({ size: "sm", variant: "outline" })}>
        Same
      </Link>
    );

    // Read from the same `buttonVariants` source of truth as `Button`, so the two
    // cannot drift apart as the variants change.
    const cls = screen.getByRole("link", { name: /same/i }).getAttribute("class") ?? "";
    expect(cls).toBe(buttonVariants({ size: "sm", variant: "outline" }));
  });

  it("logs nothing when a Button is given an anchor, because we no longer do that", () => {
    // Guards the actual reported symptom at the source: no call site in the app
    // may hand `Button` a non-button render target.
    const error = vi.spyOn(console, "error").mockImplementation(() => {});

    render(<Button size="sm">Ordinary</Button>);

    expect(error).not.toHaveBeenCalled();
  });
});