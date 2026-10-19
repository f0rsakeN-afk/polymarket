/**
 * The admin sign-in route, and the case that made it unusable.
 *
 * ## The bug this pins
 *
 * Cookies are keyed by domain, not port, so the storefront and the admin panel
 * share one session. An operator signed into the storefront with an ordinary
 * account opened the admin app and was redirected to `siteUrl()` — which
 * resolves to the **API** origin when `NEXT_PUBLIC_SITE_URL` is unset. So they
 * landed on `{"message":"PredictX API"}`: no form, no links, no way in.
 *
 * The login page already had a `?reason=not-admin` branch written and explained
 * for exactly this state. It was unreachable, because the proxy redirected
 * signed-in non-admins away before the page could render. Both halves were
 * wrong in the same direction, which is why the feature looked finished and was
 * not.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const push = vi.hoisted(() => vi.fn());
const replace = vi.hoisted(() => vi.fn());
vi.mock("next/navigation", () => ({
  useRouter: () => ({ push, replace }),
  useSearchParams: () => new URLSearchParams(),
}));

const post = vi.hoisted(() => vi.fn());
vi.mock("@workspace/api-client/client", () => ({
  api: { post: (...args: unknown[]) => post(...args) },
  apiErrorCode: () => undefined,
  apiErrorMessage: () => "failed",
}));

vi.mock("sileo", () => ({ sileo: { success: vi.fn(), error: vi.fn() } }));

vi.mock("@/lib/site-url", () => ({ storefrontUrl: () => null }));

import { AdminLoginClient } from "@/app/login/AdminLoginClient";
import { storefrontUrl } from "@/lib/site-url";

beforeEach(() => {
  vi.clearAllMocks();
});

/** The proxy's redirect decision, as the page receives it. */
function renderLogin(reason?: string) {
  return render(
    <QueryWrapper>
      <AdminLoginClient reason={reason} next="/" />
    </QueryWrapper>
  );
}

function QueryWrapper({ children }: { children: React.ReactNode }) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return <QueryClientProvider client={client}>{children}</QueryClientProvider>;
}

describe("admin sign-in", () => {
  it("offers a form to a signed-out visitor", () => {
    renderLogin();
    expect(screen.getByLabelText(/email/i)).toBeTruthy();
    expect(screen.getByRole("button", { name: /^sign in$/i })).toBeTruthy();
  });

  it("still offers a form when another, non-admin account is signed in", () => {
    // The regression. This branch used to render an explanation and one link back
    // to the storefront, with no form — on the one page whose entire purpose is
    // to let somebody establish an admin session.
    renderLogin("not-admin");

    expect(screen.getByLabelText(/email/i)).toBeTruthy();
    expect(screen.getByLabelText(/password/i)).toBeTruthy();
    expect(screen.getByRole("button", { name: /^sign in$/i })).toBeTruthy();
  });

  it("says why, and says that signing in will fix it", () => {
    renderLogin("not-admin");

    // The remedy is signing in with a different account. A page that only
    // explains the problem without offering it is a dead end with better copy.
    expect(screen.getByText(/another account is signed in/i)).toBeTruthy();
    expect(screen.getByText(/will replace the current session/i)).toBeTruthy();
  });

  it("does not claim signing in elsewhere does not carry over", () => {
    renderLogin();

    // It does carry over — that is the entire reason this bug happens. Telling an
    // operator the opposite sends them looking for a separate admin login that
    // does not exist.
    expect(screen.queryByText(/does not carry over/i)).toBeNull();
  });
});

describe("the storefront link", () => {
  it("is not rendered when no storefront is configured", () => {
    // Returns null rather than guessing. The old fallback pointed at the API
    // origin, so a "go to the site" link sent an operator to a JSON response.
    expect(storefrontUrl()).toBeNull();
  });
});