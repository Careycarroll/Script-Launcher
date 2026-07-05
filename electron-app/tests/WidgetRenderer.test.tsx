import { describe, it, expect, vi } from "vitest";
import { render, screen, fireEvent } from "@testing-library/react";
import WidgetRenderer from "../src/WidgetRenderer.jsx";

// Helper: minimal harness for common test setup.
function setup(argDefs: any[], args: any[] = [], overrides: any = {}) {
  const setArg = vi.fn();
  const pickFile = vi.fn();
  const pickFolder = vi.fn();
  render(
    <WidgetRenderer
      argDefs={argDefs}
      args={args}
      setArg={setArg}
      pickFile={pickFile}
      pickFolder={pickFolder}
      {...overrides}
    />,
  );
  return { setArg, pickFile, pickFolder };
}

describe("WidgetRenderer", () => {
  it("renders nothing when argDefs is null", () => {
    const { container } = render(
      <WidgetRenderer
        argDefs={null as any}
        args={[]}
        setArg={vi.fn()}
        pickFile={vi.fn()}
        pickFolder={vi.fn()}
      />,
    );
    expect(container).toBeEmptyDOMElement();
  });

  it("skips multiFile widgets", () => {
    setup([{ label: "Files", multiFile: true, filePicker: true }]);
    expect(screen.queryByText("Files")).not.toBeInTheDocument();
  });

  it("skips hidden widgets", () => {
    setup([{ label: "Echo mode", hidden: true, default: true }]);
    expect(screen.queryByText("Echo mode")).not.toBeInTheDocument();
  });

  it("showWhen hides widget when target value does not match", () => {
    setup(
      [
        { label: "Mode", options: ["fast", "slow"], default: "fast" },
        { label: "Slow options", showWhen: { field: "Mode", value: "slow" } },
      ],
      ["fast", ""],
    );
    expect(screen.queryByText("Slow options")).not.toBeInTheDocument();
  });

  it("showWhen shows widget when target value matches", () => {
    setup(
      [
        { label: "Mode", options: ["fast", "slow"], default: "fast" },
        { label: "Slow options", showWhen: { field: "Mode", value: "slow" } },
      ],
      ["slow", ""],
    );
    expect(screen.getByText("Slow options")).toBeInTheDocument();
  });

  it("showWhen falls back to target's default when args[targetIdx] is undefined", () => {
    setup(
      [
        { label: "Mode", options: ["fast", "slow"], default: "slow" },
        { label: "Slow options", showWhen: { field: "Mode", value: "slow" } },
      ],
      [undefined, ""],
    );
    expect(screen.getByText("Slow options")).toBeInTheDocument();
  });

  it("checkbox toggles between 'true' and 'false' string values", () => {
    const { setArg } = setup(
      [{ label: "Embed captions", type: "checkbox" }],
      ["false"],
    );
    const checkbox = screen.getByRole("checkbox");
    expect(checkbox).not.toBeChecked();
    fireEvent.click(checkbox);
    expect(setArg).toHaveBeenCalledWith(0, "true");
  });

  it("dropdown renders options and reflects current value", () => {
    const { setArg } = setup(
      [{ label: "Layout", options: ["layout", "plain"], default: "layout" }],
      ["plain"],
    );
    const select = screen.getByRole("combobox") as HTMLSelectElement;
    expect(select.value).toBe("plain");
    fireEvent.change(select, { target: { value: "layout" } });
    expect(setArg).toHaveBeenCalledWith(0, "layout");
  });

  it("filePicker button calls pickFile with correct index", () => {
    const { pickFile } = setup([
      { label: "First arg" },
      { label: "PDF file", filePicker: true },
    ]);
    fireEvent.click(screen.getByRole("button", { name: /pick file/i }));
    expect(pickFile).toHaveBeenCalledWith(1);
  });

  it("dirPicker (non-multiFile) renders Pick Folder button", () => {
    const { pickFolder } = setup([{ label: "Output folder", dirPicker: true }]);
    fireEvent.click(screen.getByRole("button", { name: /pick folder/i }));
    expect(pickFolder).toHaveBeenCalledWith(0);
  });

  it("tooltip renders as ? icon with tooltip text in title attribute", () => {
    setup([{ label: "Quality", tooltip: "Higher = larger files" }]);
    const tooltip = screen.getByText("?");
    expect(tooltip).toHaveAttribute("title", "Higher = larger files");
  });
});
