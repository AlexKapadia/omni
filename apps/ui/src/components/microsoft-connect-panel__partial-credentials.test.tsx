/**
 * Partial OAuth credentials must surface an honest error — never a silent no-op.
 */
import { afterEach, describe, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import { MicrosoftConnectPanel } from "./microsoft-connect-panel";

afterEach(cleanup);

describe("MicrosoftConnectPanel partial credentials", () => {
  it("shows an error when only Client Secret is filled", () => {
    const onConnect = vi.fn();
    render(
      <MicrosoftConnectPanel connected={false} busy={false} message={null} onConnect={onConnect} />,
    );
    fireEvent.change(screen.getByLabelText("Client Secret"), {
      target: { value: "only-secret" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Connect Microsoft" }));
    expect(onConnect).not.toHaveBeenCalled();
    expect(
      screen.getByText("Provide both Client ID and Client Secret, or leave both empty."),
    ).toBeTruthy();
  });
});
