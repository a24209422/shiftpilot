import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { SidePanel } from "./SidePanel";

const panel = () => screen.getByRole("complementary", { name: "問答面板" });

test("testShowsNotYetAvailableAndNoInput", () => {
  render(<SidePanel />);
  expect(screen.getByText("Ask the desk", { selector: ".chatTitle" })).toBeInTheDocument();
  expect(screen.getByText(/問答尚未開放/)).toBeInTheDocument();
  // 沒有功能就不能有輸入框或送出按鈕
  expect(screen.queryByRole("textbox")).toBeNull();
  expect(screen.queryByRole("button", { name: "送出" })).toBeNull();
});

test("testCollapseAndExpand", async () => {
  render(<SidePanel />);
  const user = userEvent.setup();
  await user.click(screen.getByRole("button", { name: "收合問答面板" }));
  expect(panel()).toHaveClass("collapsed");
  await user.click(screen.getByRole("button", { name: "展開問答面板" }));
  expect(panel()).not.toHaveClass("collapsed");
});

test("testKeyboardResizeIsClampedAndResettable", () => {
  render(<SidePanel />);
  const handle = screen.getByRole("separator", { name: "調整問答面板寬度" });
  expect(handle).toHaveAttribute("aria-valuenow", "400");
  fireEvent.keyDown(handle, { key: "ArrowLeft" });
  expect(handle).toHaveAttribute("aria-valuenow", "424");
  for (let index = 0; index < 20; index += 1) fireEvent.keyDown(handle, { key: "ArrowRight" });
  expect(handle).toHaveAttribute("aria-valuenow", "320");
  fireEvent.keyDown(handle, { key: "Home" });
  expect(handle).toHaveAttribute("aria-valuenow", "400");
});

test("testDragWidensPanel", () => {
  render(<SidePanel />);
  const handle = screen.getByRole("separator", { name: "調整問答面板寬度" });
  fireEvent.pointerDown(handle, { clientX: 1000 });
  fireEvent.pointerMove(window, { clientX: 950 });
  fireEvent.pointerUp(window);
  expect(handle).toHaveAttribute("aria-valuenow", "450");
});
