import { describe, it, expect } from "vitest";
import { render, screen } from "@testing-library/react";

describe("test harness smoke test", () => {
  it("renders a react component under jsdom", () => {
    render(<div data-testid="smoke">it works</div>);
    expect(screen.getByTestId("smoke")).toHaveTextContent("it works");
  });

  it("has window.electronAPI mocked", () => {
    // @ts-expect-error
    expect(window.electronAPI).toBeDefined();
    // @ts-expect-error
    expect(window.electronAPI.StreamStart).toBeTypeOf("function");
  });

  it("resets electronAPI mock between tests", () => {
    // @ts-expect-error
    expect(window.electronAPI.StreamStart).not.toHaveBeenCalled();
  });
});
