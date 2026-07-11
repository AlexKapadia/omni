/**
 * Partial OAuth credentials must surface an honest error — never a silent no-op.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { GoogleConnectPanel } from "./google-connect-panel";

afterEach(cleanup);

describe("GoogleConnectPanel partial credentials", () => {
  it("shows an error when only Client ID is filled", () => {
    const onConnect = vi.fn();
    render(
      <GoogleConnectPanel connected={false} busy={false} message={null} onConnect={onConnect} />,
    );
    fireEvent.change(screen.getByLabelText("Client ID"), { target: { value: "only-id" } });
    fireEvent.click(screen.getByRole("button", { name: "Connect Google" }));
    expect(onConnect).not.toHaveBeenCalled();
    expect(
      screen.getByText("Provide both Client ID and Client Secret, or leave both empty."),
    ).toBeTruthy();
  });
});
