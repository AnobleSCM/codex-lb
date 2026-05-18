import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it, vi } from "vitest";

import { AccountActions } from "@/features/accounts/components/account-actions";
import { createAccountSummary } from "@/test/mocks/factories";

function renderActions(
  overrides: Partial<Parameters<typeof AccountActions>[0]> = {},
) {
  const handlers = {
    onPause: vi.fn(),
    onResume: vi.fn(),
    onDelete: vi.fn(),
    onProbe: vi.fn(),
    onReauth: vi.fn(),
  };
  const account =
    overrides.account ?? createAccountSummary({ status: "active" });
  const props = {
    account,
    busy: false,
    ...handlers,
    ...overrides,
  };
  render(<AccountActions {...props} />);
  return { handlers, account };
}

describe("AccountActions", () => {
  it("renders the Probe button for active accounts", () => {
    renderActions({ account: createAccountSummary({ status: "active" }) });
    expect(screen.getByRole("button", { name: /probe/i })).toBeInTheDocument();
  });

  it("renders the Probe button for rate_limited accounts", () => {
    renderActions({
      account: createAccountSummary({ status: "rate_limited" }),
    });
    expect(screen.getByRole("button", { name: /probe/i })).toBeInTheDocument();
  });

  it("renders the Probe button for quota_exceeded accounts", () => {
    renderActions({
      account: createAccountSummary({ status: "quota_exceeded" }),
    });
    expect(screen.getByRole("button", { name: /probe/i })).toBeInTheDocument();
  });

  it("hides the Probe button for paused accounts", () => {
    renderActions({ account: createAccountSummary({ status: "paused" }) });
    expect(
      screen.queryByRole("button", { name: /probe/i }),
    ).not.toBeInTheDocument();
  });

  it("hides the Probe button for deactivated accounts", () => {
    renderActions({
      account: createAccountSummary({ status: "deactivated" }),
    });
    expect(
      screen.queryByRole("button", { name: /probe/i }),
    ).not.toBeInTheDocument();
  });

  it("invokes onProbe with the account id when clicked", () => {
    const { handlers, account } = renderActions({
      account: createAccountSummary({
        accountId: "acc_probe",
        status: "rate_limited",
      }),
    });
    fireEvent.click(screen.getByRole("button", { name: /probe/i }));
    expect(handlers.onProbe).toHaveBeenCalledTimes(1);
    expect(handlers.onProbe).toHaveBeenCalledWith(account.accountId);
  });

  it("disables the Probe button while busy", () => {
    renderActions({
      account: createAccountSummary({ status: "rate_limited" }),
      busy: true,
    });
    const probe = screen.getByRole("button", { name: /probe/i });
    expect(probe).toBeDisabled();
  });
});
