/**
 * The step-up flow, end to end.
 *
 * The three server codes mean three different things, and the whole difficulty of
 * this feature is that they arrive through the *same* failure channel. A client
 * that treats them all as "something went wrong" looks like it works — it opens a
 * dialog, it reports the problem — while being unusable for every account with 2FA
 * and mildly wrong for every account without it.
 *
 * So these tests drive the real hook against the real prompt and assert on the
 * *states* an operator would see, not on which function was called.
 */
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { ApiError } from "@workspace/api-client/client";

import { StepUpPrompt } from "@/components/step-up-prompt";
import { useStepUp } from "@/hooks/use-step-up";

/** A rejected promise shaped the way the transport rejects it. */
const refuse = (message: string, error_code: string) =>
  Promise.reject(new ApiError(message, 401, undefined, error_code));

function Harness({ run }: { run: (c: { password: string; code?: string }) => Promise<unknown> }) {
  const stepUp = useStepUp();
  return (
    <>
      <button onClick={() => stepUp.begin({ title: "Uphold", description: "A market", run })}>
        open
      </button>
      <StepUpPrompt {...stepUp.promptProps} />
    </>
  );
}

function renderHarness(run: (c: { password: string; code?: string }) => Promise<unknown>) {
  const user = userEvent.setup();
  render(<Harness run={run} />);
  return user;
}

async function submitPassword(user: ReturnType<typeof userEvent.setup>, value: string) {
  await user.click(screen.getByRole("button", { name: "open" }));
  await user.type(screen.getByLabelText(/your password/i), value);
  await user.click(screen.getByRole("button", { name: /^confirm$/i }));
}

beforeEach(() => {
  vi.restoreAllMocks();
});

describe("step-up • asking", () => {
  it("does not ask for a 2FA code it was never told about", async () => {
    // The server has not said this account has 2FA. Showing the field would ask a
    // password-only admin for something they cannot have.
    renderHarness(() => Promise.resolve());
    await userEvent.setup().click(screen.getByRole("button", { name: "open" }));

    expect(screen.getByLabelText(/your password/i)).toBeTruthy();
    expect(screen.queryByLabelText(/two-factor code/i)).toBeNull();
  });

  it("will not submit without a password", async () => {
    const run = vi.fn().mockResolvedValue({});
    const user = renderHarness(run);
    await user.click(screen.getByRole("button", { name: "open" }));

    const confirm = screen.getByRole("button", { name: /^confirm$/i });
    expect(confirm).toBeDisabled();
    expect(run).not.toHaveBeenCalled();
  });

  it("sends the password and no code when none is required", async () => {
    const run = vi.fn().mockResolvedValue({});
    const user = renderHarness(run);
    await submitPassword(user, "hunter2");

    await waitFor(() => expect(run).toHaveBeenCalledTimes(1));
    // `code` absent, not `code: undefined`-with-a-value and not an empty string —
    // the API distinguishes "no code" from "an empty code".
    expect(run.mock.calls[0]![0]).toEqual({ password: "hunter2" });
  });
});

describe("step-up • when the account has 2FA", () => {
  it("treats STEP_UP_2FA_REQUIRED as the next step, not a failure", async () => {
    // This is the single most important assertion in the file. The password was
    // *accepted*. Rendering it as an error tells the operator they got it wrong and
    // they will retype it, forever.
    const run = vi.fn().mockImplementation(() => refuse("2FA code required", "STEP_UP_2FA_REQUIRED"));
    const user = renderHarness(run);
    await submitPassword(user, "hunter2");

    await waitFor(() => expect(screen.getByLabelText(/two-factor code/i)).toBeTruthy());
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("keeps the password the server already accepted", async () => {
    const run = vi.fn().mockImplementation(() => refuse("2FA code required", "STEP_UP_2FA_REQUIRED"));
    const user = renderHarness(run);
    await submitPassword(user, "hunter2");

    await waitFor(() =>
      expect(screen.getByLabelText(/your password/i)).toHaveValue("hunter2")
    );
  });

  it("retries with the code once it is supplied", async () => {
    const run = vi
      .fn()
      .mockImplementationOnce(() => refuse("2FA code required", "STEP_UP_2FA_REQUIRED"))
      .mockResolvedValueOnce({ ok: true });
    const user = renderHarness(run);
    await submitPassword(user, "hunter2");

    await waitFor(() => expect(screen.getByLabelText(/two-factor code/i)).toBeTruthy());
    await user.type(screen.getByLabelText(/two-factor code/i), "123456");
    await user.click(screen.getByRole("button", { name: /^confirm$/i }));

    await waitFor(() => expect(run).toHaveBeenCalledTimes(2));
    expect(run.mock.calls[1]![0]).toEqual({ password: "hunter2", code: "123456" });
  });

  it("clears the code but keeps the password when the code is wrong", async () => {
    // Clearing both would make the operator retype a password the server had just
    // accepted — and would make the flow feel broken in a way that leads people to
    // give up on the action entirely.
    const run = vi
      .fn()
      .mockImplementationOnce(() => refuse("2FA code required", "STEP_UP_2FA_REQUIRED"))
      .mockImplementation(() => refuse("Invalid 2FA code", "STEP_UP_2FA_INVALID"));
    const user = renderHarness(run);
    await submitPassword(user, "hunter2");
    await waitFor(() => expect(screen.getByLabelText(/two-factor code/i)).toBeTruthy());
    await user.type(screen.getByLabelText(/two-factor code/i), "000000");
    await user.click(screen.getByRole("button", { name: /^confirm$/i }));

    await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
    expect(screen.getByLabelText(/your password/i)).toHaveValue("hunter2");
    expect(screen.getByLabelText(/two-factor code/i)).toHaveValue("");
  });

  it("clears the password when the password is wrong", async () => {
    // The opposite trade: a rejected password must not stay in the field for the
    // next attempt to send it again.
    const run = vi.fn().mockImplementation(() => refuse("Bad password", "STEP_UP_PASSWORD_INVALID"));
    const user = renderHarness(run);
    await submitPassword(user, "wrongpass");

    await waitFor(() => expect(screen.getByLabelText(/your password/i)).toHaveValue(""));
  });
});

describe("step-up • failure handling", () => {
  it("stays open after a failure", async () => {
    // Closing on failure would tell the operator the action completed. On a ruling
    // that resolves a market, "the dialog vanished" reads as "it worked".
    const run = vi.fn().mockImplementation(() => refuse("Bad password", "STEP_UP_PASSWORD_INVALID"));
    const user = renderHarness(run);
    await submitPassword(user, "hunter2");

    await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
    expect(screen.getByLabelText(/your password/i)).toBeTruthy();
  });

  it("surfaces a non-step-up failure rather than swallowing it", async () => {
    const run = vi.fn().mockImplementation(() => refuse("Market already resolved", "ALREADY_RULED"));
    const user = renderHarness(run);
    await submitPassword(user, "hunter2");

    await waitFor(() =>
      expect(screen.getByRole("alert")).toHaveTextContent(/market already resolved/i)
    );
  });

  it("does not ask for a code after an unrelated failure", async () => {
    const run = vi.fn().mockImplementation(() => refuse("Server exploded", "INTERNAL"));
    const user = renderHarness(run);
    await submitPassword(user, "hunter2");

    await waitFor(() => expect(screen.getByRole("alert")).toBeTruthy());
    expect(screen.queryByLabelText(/two-factor code/i)).toBeNull();
  });

  it("closes on success", async () => {
    const run = vi.fn().mockResolvedValue({ ok: true });
    const user = renderHarness(run);
    await submitPassword(user, "hunter2");

    await waitFor(() => expect(screen.queryByLabelText(/your password/i)).toBeNull());
  });
});

describe("step-up • credential hygiene", () => {
  it("does not keep a password after the dialog closes", async () => {
    // A shared operator machine should not hold an admin password in memory
    // because someone opened a dialog and thought about it.
    const run = vi.fn().mockImplementation(() => Promise.reject(new Error("offline")));
    const user = renderHarness(run);
    await user.click(screen.getByRole("button", { name: "open" }));
    await user.type(screen.getByLabelText(/your password/i), "hunter2");
    await user.click(screen.getByRole("button", { name: /cancel/i }));

    await waitFor(() => expect(screen.queryByLabelText(/your password/i)).toBeNull());

    // Reopening must not restore it.
    await user.click(screen.getByRole("button", { name: "open" }));
    await waitFor(() => expect(screen.getByLabelText(/your password/i)).toHaveValue(""));
  });

  it("starts a fresh prompt for a different action", async () => {
    // `requiresCode` is a fact about the server's answer to a previous attempt.
    // Carrying it forward means every later action is gated on a code forever.
    const run = vi
      .fn()
      .mockImplementationOnce(() => refuse("2FA code required", "STEP_UP_2FA_REQUIRED"))
      .mockResolvedValue({ ok: true });
    const user = renderHarness(run);
    await submitPassword(user, "hunter2");
    await waitFor(() => expect(screen.getByLabelText(/two-factor code/i)).toBeTruthy());
    await user.click(screen.getByRole("button", { name: /cancel/i }));
    await waitFor(() => expect(screen.queryByLabelText(/two-factor code/i)).toBeNull());

    await user.click(screen.getByRole("button", { name: "open" }));
    expect(screen.queryByLabelText(/two-factor code/i)).toBeNull();
  });
});