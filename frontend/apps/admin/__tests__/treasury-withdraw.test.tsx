/**
 * Withdrawing a chosen amount.
 *
 * ## Why this needs its own tests
 *
 * It is the only screen in the admin app where an operator types a number and
 * money moves that exact number. The fee sweep derives its amount, so an error in
 * the arithmetic cannot do much; here the operator decides how much leaves, and
 * the failures worth guarding are the ones where the wrong amount moves or the
 * right one silently cannot.
 *
 * The specific traps asserted below are all ways this screen could plausibly be
 * wrong without ever looking wrong:
 *
 * - `parseFloat` accepts `"1e5"`, `" 12 "` and `"0x10"`. None of those are amounts
 *   anyone means to withdraw, and all of them pass a naive numeric check.
 * - `0.3 - 0.1` is `0.19999999999999998` in floating point. A number an operator
 *   cannot read is a number they should not be asked to approve.
 * - an overdraw of one unit in the eighth decimal place is invisible in a float
 *   comparison but real.
 * - the client balance check is a convenience; the server's is the authority, and
 *   a balance can move between render and click.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";

const adminApi = vi.hoisted(() => ({ treasuryDistribute: vi.fn() }));

vi.mock("@workspace/api-client/admin", () => ({ adminApi }));
vi.mock("sileo", () => ({ sileo: { success: vi.fn(), error: vi.fn() } }));

const begin = vi.hoisted(() => vi.fn());
vi.mock("@/hooks/use-step-up", () => ({ useStepUp: () => ({ begin, promptProps: {} }) }));

import { TreasuryWithdraw } from "@/components/treasury-withdraw";

const BALANCE = "1000.50000000";

function wrap(ui: React.ReactElement) {
  const client = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(<QueryClientProvider client={client}>{ui}</QueryClientProvider>);
}

/** Run the step-up hook's payload, asserting it asked first. */
async function intent(credentials: { password: string; code?: string }) {
  const first = begin.mock.calls[0]?.[0];
  if (!first) throw new Error("step-up was never started");
  return first.run(credentials);
}

async function attempt(amount: string) {
  const user = userEvent.setup();
  wrap(<TreasuryWithdraw balance={BALANCE} />);

  const field = screen.getByLabelText(/amount/i);
  await user.type(field, amount);
  await user.click(screen.getByRole("button", { name: /^withdraw$/i }));
}

beforeEach(() => {
  vi.clearAllMocks();
  adminApi.treasuryDistribute.mockResolvedValue({ success: true, data: { status: "ok", amount: "1" } });
});

describe("entering an amount", () => {
  it("shows what is available before anything is typed", () => {
    wrap(<TreasuryWithdraw balance={BALANCE} />);
    expect(screen.getByText(/available/i)).toBeTruthy();
  });

  it("refuses exponential notation, which parseFloat would accept", async () => {
    // `1e5` is 100000 to a float and nonsense to a person.
    await attempt("1e5");
    expect(await screen.findByText(/plain number/i)).toBeTruthy();
    expect(begin).not.toHaveBeenCalled();
  });

  it("refuses hex, which parseFloat would also accept", async () => {
    await attempt("0x10");
    expect(await screen.findByText(/plain number/i)).toBeTruthy();
  });

  it("refuses a negative amount", async () => {
    await attempt("-5");
    expect(begin).not.toHaveBeenCalled();
  });

  it("refuses zero", async () => {
    // Moving nothing is a no-op that writes an audit row and a treasury log.
    await attempt("0");
    expect(await screen.findByText(/more than zero/i)).toBeTruthy();
  });

  it("refuses more decimal places than the column holds", async () => {
    // Eight is the scale of the column; the ninth place would be rounded away by
    // the database rather than by anything the operator can see.
    await attempt("1.123456789");
    expect(await screen.findByText(/8 decimal places/i)).toBeTruthy();
  });

  it("refuses more than the API's own ceiling", async () => {
    // Mirrors the API's `le=100_000_000`, so the ceiling is visible here rather
    // than as a 422 after a round trip.
    await attempt("100000001");
    expect(await screen.findByText(/maximum single withdrawal/i)).toBeTruthy();
  });

  it("accepts a plain amount", async () => {
    const user = userEvent.setup();
    wrap(<TreasuryWithdraw balance={BALANCE} />);

    await user.type(screen.getByLabelText(/amount/i), "250.50");
    await user.click(screen.getByRole("button", { name: /^withdraw$/i }));

    expect(await screen.findByRole("button", { name: /continue/i })).toBeTruthy();
  });
});

describe("the amount shown is the amount that moves", () => {
  it("confirms with the exact grouped figure, not a float", async () => {
    const user = userEvent.setup();
    wrap(<TreasuryWithdraw balance={BALANCE} />);

    await user.type(screen.getByLabelText(/amount/i), "750.12345678");
    await user.click(screen.getByRole("button", { name: /^withdraw$/i }));

    // `0.1 + 0.2` is `0.30000000000000004`. Nothing that reads like that belongs
    // in a confirmation for a money movement.
    const dialog = await screen.findByRole("button", { name: /continue/i });
    expect(dialog).toBeTruthy();
    const text = document.body.textContent ?? "";
    expect(text).toContain("750.12345678");
    expect(text).not.toMatch(/\d\.\d{9,}/);
  });

  it("passes the number to the API only after step-up", async () => {
    const user = userEvent.setup();
    wrap(<TreasuryWithdraw balance={BALANCE} />);

    await user.type(screen.getByLabelText(/amount/i), "250");
    await user.click(screen.getByRole("button", { name: /^withdraw$/i }));
    await user.click(await screen.findByRole("button", { name: /continue/i }));

    // Step-up first: the request must not exist until the operator has proved who
    // they are, or the step-up is a speed bump in front of nothing.
    expect(begin).toHaveBeenCalledTimes(1);
    expect(adminApi.treasuryDistribute).not.toHaveBeenCalled();

    await intent({ password: "pw" });

    await waitFor(() =>
      expect(adminApi.treasuryDistribute).toHaveBeenCalledWith({ amount: 250, password: "pw" })
    );
  });

  it("forwards a 2FA code when one was supplied", async () => {
    const user = userEvent.setup();
    wrap(<TreasuryWithdraw balance={BALANCE} />);

    await user.type(screen.getByLabelText(/amount/i), "100");
    await user.click(screen.getByRole("button", { name: /^withdraw$/i }));
    await user.click(await screen.findByRole("button", { name: /continue/i }));
    await intent({ password: "pw", code: "123456" });

    await waitFor(() =>
      expect(adminApi.treasuryDistribute).toHaveBeenCalledWith({
        amount: 100,
        password: "pw",
        code: "123456",
      })
    );
  });
});

describe("the balance check", () => {
  it("blocks an overdraw and says which of the two numbers is wrong", async () => {
    // The operator can see the balance, so "this is more than you have" is more
    // useful than a disabled button.
    await attempt("2000");
    expect(await screen.findByText(/more than the .* available/i)).toBeTruthy();
    expect(begin).not.toHaveBeenCalled();
  });

  it("catches an overdraw of one unit in the eighth decimal place", async () => {
    // Invisible to a float comparison, real in the database.
    await attempt("1000.50000001");
    expect(await screen.findByText(/more than the .* available/i)).toBeTruthy();
  });

  it("allows withdrawing the entire balance exactly", async () => {
    const user = userEvent.setup();
    wrap(<TreasuryWithdraw balance={BALANCE} />);

    await user.type(screen.getByLabelText(/amount/i), "1000.5");
    await user.click(screen.getByRole("button", { name: /^withdraw$/i }));

    expect(await screen.findByRole("button", { name: /continue/i })).toBeTruthy();
  });
});